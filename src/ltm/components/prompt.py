"""把检索结果拼成有硬上限的提示词。"""

from __future__ import annotations

import math

from ltm.components.identity import IdentityBook
from ltm.components.strength import is_pinned
from ltm.core.markers import BUFFER, FACTS, PERSONA, PROFILE, RECENT, SENTENCES
from ltm.core.models import Query, RetrievalResult


def _tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / 1.5))


class PromptBuilder:
    def __init__(self, store, book: IdentityBook, cfg: dict) -> None:
        self.store = store
        self.book = book
        self.cfg = cfg

    def build(self, query: Query, retrieved: RetrievalResult) -> tuple[str, int, dict]:
        cap = self.cfg["scale"]["prompt_hard_cap_tokens"]
        asker = self.book.name_of(query.asker_id)
        sections: list[tuple[str, str]] = []
        persona = (
            f"{PERSONA}\n"
            "你记得每位说话人说过的话，回答时要写清是谁的事。"
            "记忆里没有的信息就说没听对方说过，不要编造。"
            "同一件事有新旧两种说法时，以较新的为准；标了已过时的是历史。"
            "给建议时避开相关的过敏和不吃的东西。"
        )
        sections.append(("persona", persona))
        profile = self._profile(query)
        if profile:
            sections.append(("profile", PROFILE + "\n" + profile))
        facts = [it.rendered for it in retrieved.items if it.source == "fact"]
        sents = [it.rendered for it in retrieved.items if it.source == "sentence"]
        bufs = [it.rendered for it in retrieved.items if it.source == "buffer"]
        if facts:
            sections.append(("facts", FACTS + "\n" + "\n".join(facts)))
        if sents:
            sections.append(("sentences", SENTENCES + "\n" + "\n".join(sents)))
        if bufs:
            sections.append(("buffer", BUFFER + "\n" + "\n".join(bufs)))
        recent = self._recent()
        if recent:
            sections.append(("recent", RECENT + "\n" + recent))
        body, usage = _fit(sections, cap)
        system = (
            f"你是群聊里的助手。当前提问的人是{asker}。他说的「我」就是{asker}。\n"
            + body
        )
        return system, _tokens(system), usage

    def _profile(self, query: Query) -> str:
        mem = self.cfg["memory"]
        lines = []
        owners = [query.asker_id, *self.book.mentioned_ids_in_query(query.text)]
        seen = set()
        for owner in owners:
            if owner in seen:
                continue
            seen.add(owner)
            facts = [
                f
                for f in self.store.facts_for_owner(owner, ("active",))
                if is_pinned(f["strength"], f["importance"], f["status"], mem)
            ]
            facts.sort(key=lambda f: -(f["importance"] * f["strength"]))
            for fact in facts[: self.cfg["profile"]["max_items_per_person"]]:
                lines.append(f"- {fact['text']}")
        return "\n".join(lines)

    def _recent(self) -> str:
        rows = self.store.recent_messages(self.cfg["memory"]["recent_messages"])
        lines = []
        for row in rows:
            who = self.book.name_of(row["speaker_id"])
            lines.append(f"- {who}: {row['text']}")
        return "\n".join(lines)


def _fit(sections: list[tuple[str, str]], cap: int) -> tuple[str, dict]:
    """超过上限时，先砍原话，再砍缓冲区，不动事实和档案。"""
    order = ["sentences", "buffer", "recent", "facts", "profile", "persona"]
    text_of = {name: text for name, text in sections}
    while _tokens("\n".join(text_of[n] for n, _ in sections if n in text_of)) > cap:
        shrunk = False
        for name in order:
            if name in text_of and "\n" in text_of[name]:
                head, _sep, _tail = text_of[name].partition("\n")
                lines = text_of[name].split("\n")
                if len(lines) > 2:
                    text_of[name] = "\n".join(lines[:-1])
                    shrunk = True
                    break
        if not shrunk:
            break
    ordered = [text_of[name] for name, _ in sections if name in text_of]
    return "\n".join(ordered), {name: _tokens(text_of[name]) for name in text_of}
