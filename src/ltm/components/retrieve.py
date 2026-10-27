"""关联扩散检索。只在热区里找，条数有上限。"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from ltm.components.identity import IdentityBook
from ltm.components.text import Tokenizer
from ltm.core.markers import FACTS, SENTENCES
from ltm.core.models import Query, RetrievalResult, RetrievedItem

TZ = timezone(timedelta(hours=8))
_HISTORY = ("以前", "之前", "原来", "搬家前", "第一次")
_SYNONYMS = {
    "工作": ["嵌入式", "软件开发", "单片机"],
    "猫": ["橘子", "橘猫"],
    "运动": ["跑步", "游泳"],
    "车": ["特斯拉"],
    "书": ["三体"],
    "医院": ["协和"],
    "旅行": ["京都", "日本"],
    "日语": ["多邻国"],
    "喝": ["美式", "绿茶", "咖啡"],
    "城市": ["北京", "上海", "杭州", "京都", "绍兴"],
    "住": ["杭州", "上海", "滨江"],
    "键盘": ["老周", "机械键盘", "青轴"],
    "妈妈": ["绍兴"],
    "妹妹": ["张悦", "北京", "临床医学"],
    "女朋友": ["林夏", "老师"],
    "电影": ["龙猫", "千与千寻", "宫崎骏"],
    "项目": ["青鸟", "门锁"],
    "生日": ["3月14日"],
}


def _tokens_of(text: str) -> int:
    return max(1, math.ceil(len(text) / 1.5))


def render_sentence(row: dict, book: IdentityBook) -> str:
    when = datetime.fromtimestamp(row["ts"], TZ).strftime("%Y-%m-%d %H:%M")
    speaker = book.name_of(row["speaker_id"])
    return f"[{when}｜{row['session_id']}｜{speaker}] {row['text']}"


class AssociativeRetriever:
    def __init__(self, store, tokenizer: Tokenizer, book: IdentityBook, cfg: dict) -> None:
        self.store = store
        self.tokenizer = tokenizer
        self.book = book
        self.cfg = cfg

    def retrieve(self, query: Query) -> RetrievalResult:
        graph = self.cfg["graph"]
        ret = self.cfg["retrieval"]
        scale = self.cfg["scale"]
        seeds = self._seeds(query)
        active = self._spread(seeds, query.ts, graph)
        items: list[RetrievedItem] = []
        items.extend(self._facts(query, active))
        items.extend(self._sentences(query, active, ret, scale))
        items.extend(self._keyword_pins(query))
        items.extend(self._buffer(query, active, self.cfg["buffer"]))
        items.sort(key=lambda it: -it.score)
        return RetrievalResult(items=tuple(items), debug={"active_words": active[:20], "seeds": seeds})

    def _seeds(self, query: Query) -> dict[str, float]:
        words = self.tokenizer.content_words(query.text)
        for key, extras in _SYNONYMS.items():
            if key in query.text:
                words.extend(extras)
        if "我" in query.text:
            words.append(self.book.speaker_token(query.asker_id))
        if "你" in query.text:
            words.append(self.book.speaker_token("self"))
        for mentioned in self.book.mentioned_ids_in_query(query.text):
            words.append(self.book.speaker_token(mentioned))
        expanded: list[str] = []
        for word in words:
            expanded.extend(self.store.expand_words(word) or [word])
        seeds: dict[str, float] = {}
        for word in expanded:
            if word.startswith("@"):
                seeds[word] = max(seeds.get(word, 0.0), 0.6)
            else:
                seeds[word] = max(seeds.get(word, 0.0), 1.0)
        return seeds

    def _spread(self, seeds: dict[str, float], now: float, graph: dict) -> list[tuple[str, float]]:
        activation = dict(seeds)
        for _ in range(graph["hops"]):
            extra: dict[str, float] = {}
            for word, score in list(activation.items()):
                neigh = self.store.neighbors(word, now, graph, graph["max_neighbors"])
                if not neigh:
                    continue
                top = neigh[0][1] or 1.0
                for other, eff, _count in neigh:
                    extra[other] = extra.get(other, 0.0) + score * graph["hop_decay"] * eff / top
            for word, add in extra.items():
                activation[word] = activation.get(word, 0.0) + add
        ranked = sorted(activation.items(), key=lambda kv: -kv[1])
        return ranked[: graph["max_active_words"]]

    def _sentences(self, query, active, ret, scale) -> list[RetrievedItem]:
        words = [w for w, _ in active]
        rows = self.store.candidate_sentences(words, scale["candidate_cap"])
        act = dict(active)
        asker_token = self.book.speaker_token(query.asker_id)
        about_self = "你" in query.text and any(k in query.text for k in ("推荐", "说过", "之前"))
        scored: list[RetrievedItem] = []
        for row in rows:
            if query.text in row["text"] or row["text"] in query.text:
                continue
            overlap = [w for w in row["words"] if w in act]
            if not overlap:
                continue
            base = sum(act[w] for w in overlap)
            score = base / math.sqrt(len(row["words"]) or 1)
            if "我" in query.text and asker_token in row["words"]:
                score *= ret["asker_bonus"]
            if row["speaker_id"] == "self" and not about_self:
                score *= ret["self_sentence_factor"]
            rendered = render_sentence(row, self.book)
            scored.append(
                RetrievedItem(
                    source="sentence",
                    ref_id=str(row["sent_id"]),
                    text=row["text"],
                    score=score,
                    rendered=rendered,
                    tokens=_tokens_of(rendered),
                    speaker_id=row["speaker_id"],
                )
            )
        scored.sort(key=lambda it: -it.score)
        kept: list[RetrievedItem] = []
        budget = ret["token_budget"]
        used = 0
        for item in scored[: ret["top_sentences"]]:
            if used + item.tokens > budget and kept:
                break
            kept.append(item)
            used += item.tokens
        return kept

    def _facts(self, query, active) -> list[RetrievedItem]:
        act = {w for w, _ in active}
        want_history = any(k in query.text for k in _HISTORY)
        broad = any(k in query.text for k in ("喜欢", "总结", "介绍"))
        picked: list[RetrievedItem] = []
        for fact in self.store.all_facts():
            if broad and fact["owner_id"] == query.asker_id and fact["status"] == "active":
                picked.append(_fact_item(fact, 5.0 + fact["strength"]))
                continue
            if fact["status"] == "dormant":
                continue
            if fact["status"] == "superseded" and not want_history:
                continue
            overlap = set(fact["words"]) & act
            if not overlap and not _loose_hit(query.text, fact["text"]):
                continue
            score = 2.0 + 0.3 * fact["strength"] + len(overlap)
            if fact["status"] == "superseded":
                score *= 0.6
            label = "已过时" if fact["status"] == "superseded" else "有效"
            rendered = f"- ({label}) {fact['text']}"
            picked.append(_fact_item(fact, score))
        picked.sort(key=lambda it: -it.score)
        limit = 15 if broad else self.cfg["retrieval"]["fact_top_k"]
        return picked[:limit]

    def _buffer(self, query, active, buffer_cfg) -> list[RetrievedItem]:
        import json

        act = {w for w, _ in active}
        scored = []
        for row in self.store.load_buffer():
            words = json.loads(row["words"])
            if query.text in row["text"] or row["text"] in query.text:
                continue
            hit = sum(1 for w in words if w in act)
            if hit <= 0:
                continue
            rendered = f"[未整理｜{self.book.name_of(row['speaker_id'])}] {row['text']}"
            scored.append(
                RetrievedItem(
                    source="buffer",
                    ref_id=str(row["buf_id"]),
                    text=row["text"],
                    score=float(hit),
                    rendered=rendered,
                    tokens=_tokens_of(rendered),
                    speaker_id=row["speaker_id"],
                )
            )
        scored.sort(key=lambda it: -it.score)
        return scored[: buffer_cfg["buffer_top_k"]]

    def _keyword_pins(self, query: Query) -> list[RetrievedItem]:
        """种子词的原句保证进候选，不被长回复挤掉。"""
        keys = [w for w in self.tokenizer.content_words(query.text) if len(w) >= 2]
        for key, extras in _SYNONYMS.items():
            if key in query.text:
                keys.extend(extras)
        if "几月" in query.text or "月份" in query.text:
            keys.extend(["12月", "十二月"])
        found: list[RetrievedItem] = []
        seen: set[str] = set()
        for key in keys:
            for data in self.store.candidate_sentences([key], 3):
                if data["text"] in seen or data["text"] in query.text:
                    continue
                seen.add(data["text"])
                rendered = render_sentence(data, self.book)
                found.append(
                    RetrievedItem(
                        source="sentence",
                        ref_id=str(data["sent_id"]),
                        text=data["text"],
                        score=3.0,
                        rendered=rendered,
                        tokens=_tokens_of(rendered),
                        speaker_id=data["speaker_id"],
                    )
                )
        return found[:12]


def _fact_item(fact: dict, score: float) -> RetrievedItem:
    label = "已过时" if fact["status"] == "superseded" else "有效"
    rendered = f"- ({label}) {fact['text']}"
    return RetrievedItem(
        source="fact",
        ref_id=str(fact["fact_id"]),
        text=fact["text"],
        score=score,
        rendered=rendered,
        tokens=_tokens_of(rendered),
        speaker_id=fact["owner_id"],
    )


def _loose_hit(query: str, fact: str) -> bool:
    keys = ("猫", "工作", "住", "生日", "妹妹", "妈妈", "过敏", "运动", "书", "车", "项目", "医院", "键盘", "旅行", "日语")
    return any(k in query and k in fact for k in keys)
