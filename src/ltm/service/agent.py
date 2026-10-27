"""对话入口。整理耗时记在 sleep_ms，不记进 total_ms。"""

from __future__ import annotations

import time

from ltm.core.models import LLMResponse, Message, Query, TurnResult


class ChatAgent:
    def __init__(self, memory, llm, cfg: dict) -> None:
        self.memory = memory
        self.llm = llm
        self.cfg = cfg

    def handle(self, msg: Message, need_reply: bool) -> TurnResult:
        sleep_ms = 0.0
        for report in self.memory.advance_time(msg.ts):
            sleep_ms += report.duration_ms
        nap = self.memory.ingest(msg)
        if nap is not None:
            sleep_ms += nap.duration_ms
        reply = None
        prompt_tokens = completion_tokens = 0
        retrieval_ms = prompt_ms = llm_ms = 0.0
        debug: dict = {}
        if need_reply:
            query = Query(text=msg.text, asker_id=msg.speaker_id, session_id=msg.session_id, ts=msg.ts)
            t0 = time.perf_counter()
            retrieved = self.memory.retrieve(query)
            retrieval_ms = (time.perf_counter() - t0) * 1000
            t1 = time.perf_counter()
            system, prompt_tokens, usage = self.memory.build_prompt(query, retrieved)
            prompt_ms = (time.perf_counter() - t1) * 1000
            t2 = time.perf_counter()
            response: LLMResponse = self.llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": msg.text}]
            )
            llm_ms = (time.perf_counter() - t2) * 1000
            reply = response.text
            completion_tokens = response.completion_tokens
            reply_msg = Message(
                ts=msg.ts + 60,
                session_id=msg.session_id,
                speaker_id="self",
                text=reply,
                addressee_ids=(msg.speaker_id,),
                meta={"turn": msg.meta.get("turn")},
            )
            nap2 = self.memory.ingest(reply_msg)
            if nap2 is not None:
                sleep_ms += nap2.duration_ms
            debug = {"usage": usage, "active_words": list(retrieved.debug.get("active_words", []))[:12]}
        return TurnResult(
            reply=reply,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            retrieval_ms=retrieval_ms,
            prompt_build_ms=prompt_ms,
            llm_ms=llm_ms,
            sleep_ms=sleep_ms,
            total_ms=retrieval_ms + prompt_ms + llm_ms,
            debug=debug,
        )
