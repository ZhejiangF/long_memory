"""命令行试聊：python -m ltm.service.cli --as 张磊"""

from __future__ import annotations

import argparse

from ltm.core.models import Message
from ltm.service.factory import build_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="长期记忆插件的本地试聊")
    parser.add_argument("--db", default="results/chat.db")
    parser.add_argument("--as", dest="speaker", default="张磊")
    args = parser.parse_args()
    agent = build_agent(args.db)
    book = agent.memory.book
    speaker = next(m["id"] for m in book.members if m["name"] == args.speaker or m["id"] == args.speaker)
    print("输入 /sleep 立即整理，输入 /quit 退出。")
    while True:
        text = input("> ").strip()
        if not text:
            continue
        if text == "/quit":
            break
        if text == "/sleep":
            report = agent.memory.flush()
            print(f"整理完成，句子 {report.stage_stats}")
            continue
        msg = Message(
            ts=agent.memory.clock.now() + 1,
            session_id=agent.cfg["identity"]["session_id"],
            speaker_id=speaker,
            text=text,
            addressee_ids=("self",),
        )
        result = agent.handle(msg, need_reply=True)
        print(result.reply)


if __name__ == "__main__":
    main()