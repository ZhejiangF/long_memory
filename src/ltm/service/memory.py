"""清醒时只进缓冲区；攒够一批再整理。回复时间不含整理耗时。"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from ltm.components.facts import SUPERSEDE_SLOTS, RuleExtractor, jaccard
from ltm.components.personality import Personality
from ltm.components.prompt import PromptBuilder
from ltm.components.retrieve import AssociativeRetriever
from ltm.components.strength import initial_strength, reinforce, retention, should_sleep
from ltm.components.text import Tokenizer
from ltm.core.events import emit
from ltm.core.models import Message, Query, RetrievalResult, SleepReport
from ltm.core.errors import MessageError

TZ = timezone(timedelta(hours=8))


class MemoryService:
    def __init__(self, store, clock, book, tokenizer: Tokenizer, cfg: dict) -> None:
        self.store = store
        self.clock = clock
        self.book = book
        self.tokenizer = tokenizer
        self.cfg = cfg
        self.extractor = RuleExtractor()
        self.retriever = AssociativeRetriever(store, tokenizer, book, cfg)
        self.prompts = PromptBuilder(store, book, cfg)
        self.personality = Personality(store, cfg)
        self.nap_count = 0
        self.night_count = 0

    def advance_time(self, ts: float) -> list[SleepReport]:
        prev = float(self.store.get_kv("clock_ts", "0") or 0)
        self.clock.set(ts)
        reports = []
        if prev > 0:
            for night_ts in _nights_between(prev, ts, self.cfg["sleep"]["night_hour"]):
                reports.append(self._night(night_ts))
        self.store.set_kv("clock_ts", str(ts))
        self.store.commit()
        return reports

    def ingest(self, msg: Message) -> SleepReport | None:
        self._check(msg)
        meta = dict(msg.meta)
        msg_id = self.store.add_message(
            msg.ts, msg.session_id, msg.speaker_id, msg.addressee_ids, msg.text, meta
        )
        skip = bool(meta.get("skip_extract"))
        for idx, sentence in enumerate(self.tokenizer.split_sentences(msg.text)):
            # 助手复述出来的带时间戳原文不再入库，避免一次回复拆成几十句把检索挤满。
            if msg.speaker_id == "self" and "｜" in sentence:
                continue
            words = self._index_words(sentence, msg.speaker_id, msg.ts)
            if skip:
                words.append("#skip")
            self.store.add_buffer(msg_id, idx, msg.ts, msg.session_id, msg.speaker_id, sentence, words)
        self.store.commit()
        emit("message.ingested", speaker_id=msg.speaker_id)
        report = None
        limit = self.cfg["buffer"]["nap_sentences"]
        hard = self.cfg["buffer"]["max_sentences"]
        while self.store.buffer_count() >= limit or self.store.buffer_count() >= hard:
            report = self._nap(msg.ts, skip_all=skip and self.store.buffer_count() == 0)
            if self.store.buffer_count() < limit:
                break
        return report

    def retrieve(self, query: Query) -> RetrievalResult:
        return self.retriever.retrieve(query)

    def build_prompt(self, query: Query, retrieved: RetrievalResult) -> tuple[str, int, dict]:
        return self.prompts.build(query, retrieved)

    def flush(self) -> SleepReport:
        return self._nap(self.clock.now(), force=True)

    def _nap(self, ts: float, force: bool = False, skip_all: bool = False) -> SleepReport:
        start = datetime.now().timestamp()
        rows = self.store.load_buffer()
        if not rows and not force:
            return SleepReport("nap", ts, 0.0, {"sentences": 0})
        n_sent = 0
        n_fact = 0
        accepted: list[dict] = []
        for row in rows:
            words = [w for w in _loads(row["words"]) if w != "#skip"]
            skip = "#skip" in _loads(row["words"])
            sent_id = self.store.add_sentence(
                row["msg_id"], row["idx"], row["ts"], row["session_id"], row["speaker_id"], row["text"], words
            )
            self._edges(words, row["speaker_id"], row["ts"], sent_id)
            turn = None
            drafts = self.extractor.extract(
                row["text"], row["speaker_id"], self.book.name_of(row["speaker_id"]), skip=skip
            )
            for draft in drafts:
                if self._upsert_fact(draft, row["ts"], turn):
                    n_fact += 1
                    accepted.append(draft)
            n_sent += 1
        changed = self.personality.observe(accepted, ts)
        self.store.clear_buffer()
        cooled = self.store.cool_overflow(self.cfg["scale"]["hot_sentence_cap"])
        self.store.commit()
        self.nap_count += 1
        duration = (datetime.now().timestamp() - start) * 1000
        report = SleepReport(
            "nap",
            ts,
            duration,
            {"sentences": n_sent, "facts": n_fact, "cooled": cooled, "traits": changed},
        )
        emit("sleep.finished", kind="nap")
        return report

    def _night(self, ts: float) -> SleepReport:
        start = datetime.now().timestamp()
        flushed = self._nap(ts, force=True)
        slept = 0
        mem = self.cfg["memory"]
        for fact in self.store.all_facts():
            if fact["status"] != "active":
                continue
            keep = retention(fact["strength"], fact["last_access_ts"], ts, mem)
            if should_sleep(fact["strength"], fact["importance"], keep, mem):
                self.store.set_fact_status(fact["fact_id"], "dormant")
                slept += 1
        cooled = self.store.cool_overflow(self.cfg["scale"]["hot_sentence_cap"])
        self.store.commit()
        self.night_count += 1
        duration = (datetime.now().timestamp() - start) * 1000
        return SleepReport(
            "night", ts, duration, {"slept": slept, "cooled": cooled, "flushed": flushed.stage_stats}
        )

    def _edges(self, words: list[str], speaker_id: str, ts: float, sent_id: int) -> None:
        graph = self.cfg["graph"]
        cap = self.cfg["scale"]["edge_sources_cap"]
        content = [w for w in words if not w.startswith("@") and not w.startswith("#")]
        factor = graph["self_edge_factor"] if speaker_id == "self" else 1.0
        window = graph["pair_window"]
        for i in range(len(content)):
            for j in range(i + 1, min(len(content), i + window + 1)):
                self.store.add_edge(content[i], content[j], factor / (j - i), ts, sent_id, cap)
        speaker = self.book.speaker_token(speaker_id)
        for word in content:
            self.store.add_edge(speaker, word, factor * graph["speaker_edge_gain"], ts, sent_id, cap)

    def _upsert_fact(self, draft: dict, ts: float, turn: int | None) -> bool:
        gate = self.cfg["personality"]
        mem = self.cfg["memory"]
        importance = int(draft["importance"])
        personal = float(importance)
        if importance < gate["always_keep_importance"] and personal < gate["gate_threshold"]:
            return False
        words = self.tokenizer.content_words(draft["text"])
        existing = self.store.facts_for_owner(draft["owner_id"], ("active", "dormant"))
        same_slot = [f for f in existing if f["slot"] == draft["slot"]]
        best = None
        best_score = 0.0
        for fact in same_slot or existing:
            score = jaccard(words, fact["words"])
            if score > best_score:
                best, best_score = fact, score
        if best is not None and best_score >= 0.45:
            self.store.reinforce_fact(
                best["fact_id"], reinforce(best["strength"], mem["reinforce_mention"], mem), ts, turn
            )
            return True
        if draft["slot"] in SUPERSEDE_SLOTS:
            for fact in same_slot:
                if fact["status"] == "active":
                    # 先插入新事实，再把旧的标成被它取代。
                    pass
        new_id = self.store.insert_fact(
            {
                **draft,
                "words": words,
                "personal_importance": personal,
                "strength": initial_strength(personal, mem),
                "ts": ts,
                "turns": [turn] if turn is not None else [],
            }
        )
        if draft["slot"] in SUPERSEDE_SLOTS:
            for fact in same_slot:
                if fact["status"] == "active":
                    self.store.supersede_fact(fact["fact_id"], new_id)
        return True

    def _index_words(self, sentence: str, speaker_id: str, ts: float) -> list[str]:
        words = self.tokenizer.content_words(sentence)
        words.append(self.book.speaker_token(speaker_id))
        for mentioned in self.book.resolve_mentions(sentence, speaker_id):
            token = self.book.speaker_token(mentioned)
            if token not in words:
                words.append(token)
        day = datetime.fromtimestamp(ts, TZ).strftime("#%Y-%m-%d")
        words.append(day)
        return words

    @staticmethod
    def _check(msg: Message) -> None:
        if msg.ts is None or not msg.session_id or not msg.speaker_id or msg.text is None:
            raise MessageError("消息必须带时间、会话、说话人和正文")


def _nights_between(prev_ts: float, new_ts: float, hour: int) -> list[float]:
    prev = datetime.fromtimestamp(prev_ts, TZ)
    new = datetime.fromtimestamp(new_ts, TZ)
    day = prev.date()
    point = datetime.combine(day, time(hour), TZ)
    if point <= prev:
        day = day + timedelta(days=1)
        point = datetime.combine(day, time(hour), TZ)
    found = []
    while point <= new:
        found.append(point.timestamp())
        day = day + timedelta(days=1)
        point = datetime.combine(day, time(hour), TZ)
    return found


def _loads(raw: str):
    import json

    return json.loads(raw)
