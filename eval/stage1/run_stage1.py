"""跑阶段一。默认用离线回答器，不需要 API。"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.stage1.script import RAW, SPEAKER, passes, turn_ts
from ltm.core.models import Message
from ltm.service.factory import build_agent


def _noise(agent, n: int = 200) -> None:
    """本地生成的背景闲聊，不调用模型，也不抽取事实。"""
    topics = ("今天路况一般", "晚上有球赛", "这个游戏更新了", "通勤花了一个小时", "小孩今天放学早")
    start = turn_ts(1) - 86400 * 20
    for i in range(n):
        who = f"passer{i % 10}"
        agent.memory.book.by_id.setdefault(who, {"id": who, "name": f"路人{i % 10}", "aliases": []})
        msg = Message(
            ts=start + i * 60,
            session_id="生活群",
            speaker_id="laozhou" if i % 17 == 0 else "linxia" if i % 19 == 0 else "zhanglei",
            text=topics[i % len(topics)] + f"（{i}）",
            meta={"skip_extract": True, "turn": 0},
        )
        agent.memory.clock.set(msg.ts)
        agent.memory.ingest(msg)


def run(noise: int = 0) -> dict:
    agent = build_agent(
        ":memory:",
        overrides={
            "buffer": {"nap_sentences": 30, "max_sentences": 80, "segment_max_sentences": 15},
        },
    )
    if noise:
        _noise(agent, noise)
    rows = []
    max_prompt = 0
    for turn, name, reply, kind, text, spec in RAW:
        msg = Message(
            ts=turn_ts(turn),
            session_id="生活群",
            speaker_id=SPEAKER[name],
            text=text,
            addressee_ids=("self",) if reply else (),
            meta={"turn": turn},
        )
        result = agent.handle(msg, need_reply=reply)
        max_prompt = max(max_prompt, result.prompt_tokens)
        if spec:
            ok = passes(result.reply or "", spec)
            rows.append({"turn": turn, "cat": spec["cat"], "ok": ok, "reply": result.reply, "spec": spec})
    facts = agent.memory.store.all_facts()
    peanut = [f for f in facts if "花生" in f["text"]]
    car = [f for f in facts if "特斯拉" in f["text"]]
    return {
        "rows": rows,
        "max_prompt": max_prompt,
        "naps": agent.memory.nap_count,
        "nights": agent.memory.night_count,
        "peanut_active": any(f["status"] == "active" for f in peanut),
        "car_dormant": any(f["status"] == "dormant" for f in car),
        "agent": agent,
    }


def summarize(result: dict) -> str:
    rows = result["rows"]
    counted = [r for r in rows if r["cat"] != "forget"]
    hit = sum(1 for r in counted if r["ok"])
    by_cat = Counter()
    by_cat_ok = Counter()
    for row in rows:
        by_cat[row["cat"]] += 1
        if row["ok"]:
            by_cat_ok[row["cat"]] += 1
    lines = [
        f"计入成绩的探针 {hit}/{len(counted)} = {hit / len(counted):.1%}",
        f"提示词最大 token 估算 {result['max_prompt']}",
        f"小睡 {result['naps']} 次，夜间整理 {result['nights']} 次",
        f"花生过敏仍有效: {result['peanut_active']}；车辆事实已休眠: {result['car_dormant']}",
        "分类: " + ", ".join(f"{cat} {by_cat_ok[cat]}/{by_cat[cat]}" for cat in by_cat),
    ]
    missed = [r for r in rows if not r["ok"]]
    if missed:
        lines.append("未通过:")
        for row in missed:
            lines.append(f"  第{row['turn']}轮 [{row['cat']}] {row['reply']}")
    return "\n".join(lines)


if __name__ == "__main__":
    out = Path("results/stage1")
    out.mkdir(parents=True, exist_ok=True)
    clean = run(0)
    noisy = run(200)
    report = "== 干净设置 ==\n" + summarize(clean) + "\n\n== 加 200 句背景闲聊 ==\n" + summarize(noisy) + "\n"
    (out / "report.txt").write_text(report, encoding="utf-8")
    print(report)
