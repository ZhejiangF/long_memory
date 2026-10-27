"""短程容量冒烟：确认提示词和缓冲区有上限，检索时间不跟着条数线性涨。

完整一年是每天 500～800 条。这里用两天、每天 500 条先看住上限。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ltm.core.models import Message
from ltm.service.factory import build_agent


def main() -> None:
    agent = build_agent(
        ":memory:",
        overrides={"buffer": {"nap_sentences": 200, "max_sentences": 800}},
    )
    base = 1_780_000_000.0
    prompts = []
    retrieval = []
    for day in range(2):
        for i in range(500):
            ts = base + day * 86400 + 9 * 3600 + i * 30
            text = f"今天路况还行，第{day}-{i}次闲聊"
            need = i % 25 == 0
            if need:
                text = "我特别喜欢吃火锅，尤其是周末。" if i else "你好，我叫张磊。"
            msg = Message(
                ts=ts,
                session_id="生活群",
                speaker_id="zhanglei",
                text=text,
                addressee_ids=("self",) if need else (),
                meta={"skip_extract": not need},
            )
            result = agent.handle(msg, need_reply=need)
            if need:
                prompts.append(result.prompt_tokens)
                retrieval.append(result.retrieval_ms)
                assert result.total_ms == result.retrieval_ms + result.prompt_build_ms + result.llm_ms
        assert agent.memory.store.buffer_count() <= 800
    assert max(prompts) <= 7000
    assert agent.memory.store.hot_count() <= 20000
    first = sum(retrieval[:10]) / 10
    last = sum(retrieval[-10:]) / 10
    print(f"回复 {len(prompts)} 次，提示词最大 {max(prompts)}，检索均值前10 {first:.2f} ms，后10 {last:.2f} ms")
    print(f"热句 {agent.memory.store.hot_count()}，小睡 {agent.memory.nap_count}，夜间 {agent.memory.night_count}")


if __name__ == "__main__":
    main()
