"""一年长期记忆：只跑本方案（默认上限），离线回答，不做对照组。

语料不调用大模型。闲聊用模板加 §编号，编号留在原文里保证不重复，
分词时会被去掉，不进词表。可记事实不带编号、不跳过抽取，并且要求回复。
每天另抽 8 条闲聊做回复，用来量提示词和耗时；其余闲聊只入库。
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ltm.core.models import Message
from ltm.service.factory import build_agent

TZ = timezone(timedelta(hours=8))
START = datetime(2026, 11, 1, tzinfo=TZ)
SEED = 20261101
SPRING_FROM = datetime(2027, 2, 5, tzinfo=TZ).date()
SPRING_TO = datetime(2027, 2, 11, tzinfo=TZ).date()
SESSION = "生活群"
SPEAKER = "zhanglei"

# 闲聊词表有意收小，同一句靠 §编号区分，避免每个编号变成一个新词。
PLACES = ["公司", "地铁", "食堂", "小区", "马路", "电梯", "超市", "公交", "公园", "楼下"]
ACTIONS = ["排队", "堵车", "散步", "买菜", "开会", "等人", "回消息", "看通知", "打卡", "找车位"]
FEELS = ["还行", "有点累", "挺安静", "稍微忙", "不太挤", "差不多", "有点冷", "挺顺", "一般", "还好"]


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    ordered = sorted(xs)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * 0.95
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(ordered[lo])
    weight = rank - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def _day_count(day, rng: random.Random) -> int:
    if SPRING_FROM <= day.date() <= SPRING_TO:
        return 800
    return rng.randint(500, 800)


def _timestamps(day: datetime, n: int) -> list[float]:
    """08:00–10:00 占 20%，12:00–14:00 占 25%，19:00–23:30 占 55%。间隔至少 20 秒。"""
    origin = datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp()
    windows = (
        (8 * 3600, 10 * 3600, 0.20),
        (12 * 3600, 14 * 3600, 0.25),
        (19 * 3600, 23 * 3600 + 30 * 60, 0.55),
    )
    counts = [int(n * ratio) for _, _, ratio in windows]
    counts[-1] += n - sum(counts)
    times: list[float] = []
    for (start, end, _), count in zip(windows, counts):
        if count <= 0:
            continue
        step = (end - start) / count
        if step < 20:
            raise RuntimeError(f"{day.date()} 时段放不下 {count} 条（间隔 {step:.1f}s）")
        for i in range(count):
            times.append(origin + start + (i + 0.5) * step)
    times.sort()
    return times


def _facts_for(day_number: int) -> list[str]:
    """第 1 天两条身份/安全事实；之后每 7 天一条火锅（第 8、15、…、365 天）。"""
    if day_number == 1:
        return ["你好，我叫张磊", "我对花生过敏"]
    if day_number > 1 and (day_number - 1) % 7 == 0:
        return ["我特别喜欢吃火锅"]
    return []


def _chitchat(rng: random.Random, serial: int) -> str:
    place = PLACES[rng.randrange(len(PLACES))]
    action = ACTIONS[rng.randrange(len(ACTIONS))]
    feel = FEELS[rng.randrange(len(FEELS))]
    return f"{place}{action}，感觉{feel}§{serial}"


def _reset_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix) if suffix else path
        if candidate.exists():
            candidate.unlink()


def _window(samples: list[dict], first: int, last: int) -> dict:
    rows = [row for row in samples if first <= row["day"] <= last]
    prompts = [row["prompt_tokens"] for row in rows]
    totals = [row["total_ms"] for row in rows]
    retrievals = [row["retrieval_ms"] for row in rows]
    return {
        "days": f"{first}–{last}",
        "replies": len(rows),
        "prompt_avg": _mean(prompts),
        "prompt_max": max(prompts) if prompts else 0,
        "total_avg": _mean(totals),
        "total_p95": _p95(totals),
        "retrieval_avg": _mean(retrievals),
        "retrieval_p95": _p95(retrievals),
    }


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}"


def _write_report(
    path: Path,
    *,
    daily: list[dict],
    samples: list[dict],
    wall_s: float,
    flush_ms: float,
    peanut_rows: list[dict],
    traits: list[dict],
    hot_max: int,
    buffer_max: int,
    changes: str,
) -> None:
    total_messages = sum(row["messages"] for row in daily)
    total_replies = sum(row["replies"] for row in daily)
    prompts = [row["prompt_tokens"] for row in samples]
    over = [n for n in prompts if n > 7500]
    w1 = _window(samples, 1, 20)
    w2 = _window(samples, 121, 140)
    w5 = _window(samples, 346, 365)
    ratio = (w5["prompt_avg"] / w2["prompt_avg"]) if w2["prompt_avg"] else float("inf")
    time_ratio = (w5["total_avg"] / w2["total_avg"]) if w2["total_avg"] else float("inf")
    retrieval_ratio = (w5["retrieval_avg"] / w2["retrieval_avg"]) if w2["retrieval_avg"] else float("inf")
    p95_ratio = (w5["total_p95"] / w2["total_p95"]) if w2["total_p95"] else float("inf")
    lines = [
        "# 本方案一年运行报告",
        "",
        "只跑现有插件（`build_agent` 默认上限：小睡 600 句、缓冲区硬上限 2000 句、热句 20000、提示词硬上限 7000）。离线回答器是 GroundedLLM，没有调用真实大模型，也没有跑无记忆、全量上下文、普通向量检索或取消上限的对照。",
        "",
        "## 全年合计",
        "",
        f"- 总消息数：{total_messages}",
        f"- 总回复次数：{total_replies}",
        f"- 总壁钟时间：{_fmt(wall_s, 1)} 秒（{_fmt(wall_s / 60, 2)} 分钟），含收尾 flush {_fmt(flush_ms, 1)} ms",
        f"- 全程热句数最大 {hot_max}，日末缓冲区最大 {buffer_max}",
        f"- 全程回复的 prompt_tokens 最大 {max(prompts) if prompts else 0}，超过 7500 的回复 {len(over)} 次",
        "",
        "## 三个窗口",
        "",
        "下面的平均、最大、p95 都是窗口内全部回复放在一起算的，不是先算每天再平均。p95 用线性插值。",
        "",
        "| 窗口 | 回复数 | 平均 prompt_tokens | 最大 prompt_tokens | 平均 total_ms | p95 total_ms | 平均 retrieval_ms | p95 retrieval_ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label, stats in (("第 1–20 天", w1), ("第 121–140 天", w2), ("第 346–365 天", w5)):
        lines.append(
            f"| {label} | {stats['replies']} | {_fmt(stats['prompt_avg'], 1)} | {stats['prompt_max']} | "
            f"{_fmt(stats['total_avg'], 2)} | {_fmt(stats['total_p95'], 2)} | "
            f"{_fmt(stats['retrieval_avg'], 2)} | {_fmt(stats['retrieval_p95'], 2)} |"
        )
    lines.extend(["", "## 最后 20 天逐日", "", "| 日期 | 平均 token | 平均耗时 ms | p95 耗时 ms |", "|---|---:|---:|---:|"])
    for row in daily[-20:]:
        lines.append(
            f"| {row['date']} | {_fmt(row['prompt_tokens_avg'], 1)} | {_fmt(row['total_ms_avg'], 2)} | {_fmt(row['total_ms_p95'], 2)} |"
        )
    cap_text = "始终 ≤ 7500" if not over else f"有 {len(over)} 次超过 7500，最大 {max(over)}"
    grow_text = "超过" if ratio > 1.15 else "没有超过"
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"- 提示词：{cap_text}。硬上限是 7000，验收线是 7500（留出系统提示开销）。实测最大 {max(prompts) if prompts else 0}。",
            f"- 最后 20 天平均 prompt_tokens 是第 121–140 天的 {_fmt(ratio, 3)} 倍，{grow_text} 1.15 倍（{_fmt(w5['prompt_avg'], 1)} / {_fmt(w2['prompt_avg'], 1)}）。",
            f"- 回复耗时 total_ms：第 121–140 天平均 {_fmt(w2['total_avg'], 2)}、p95 {_fmt(w2['total_p95'], 2)}；最后 20 天平均 {_fmt(w5['total_avg'], 2)}、p95 {_fmt(w5['total_p95'], 2)}。平均是基准窗口的 {_fmt(time_ratio, 3)} 倍，p95 是 {_fmt(p95_ratio, 3)} 倍。",
            f"- 检索耗时 retrieval_ms：第 121–140 天平均 {_fmt(w2['retrieval_avg'], 2)}、p95 {_fmt(w2['retrieval_p95'], 2)}；最后 20 天平均 {_fmt(w5['retrieval_avg'], 2)}、p95 {_fmt(w5['retrieval_p95'], 2)}。平均是基准窗口的 {_fmt(retrieval_ratio, 3)} 倍。",
            f"- 冷启动窗口（第 1–20 天）平均 total_ms {_fmt(w1['total_avg'], 2)}、平均 retrieval_ms {_fmt(w1['retrieval_avg'], 2)}，只作对照，不拿来当基准。",
            "",
            _time_verdict(w1, w2, w5, time_ratio, retrieval_ratio),
            "",
            "## 花生过敏",
            "",
        ]
    )
    if not peanut_rows:
        lines.append("facts 表里没有含「花生」的行。年末不能算作仍记得。")
    else:
        for row in peanut_rows:
            lines.append(
                f"- fact_id={row['fact_id']} status={row['status']} slot={row['slot']} "
                f"importance={row['importance']} strength={row['strength']:.3f} "
                f"mention_count={row['mention_count']} text={row['text']}"
            )
        active = [row for row in peanut_rows if row["status"] == "active"]
        if active:
            lines.append(f"年末仍有 {len(active)} 条花生相关事实处于 active。")
        else:
            lines.append("年末没有任何花生相关事实处于 active。")
    lines.extend(["", "## 年末性格", "", "| 特质 | 权重 | 基线 | 锁定 |", "|---|---:|---:|---|"])
    if not traits:
        lines.append("| — | — | — | 没有任何特质记录 |")
    for row in traits:
        lines.append(
            f"| {row['key']} | {row['weight']:.3f} | {row['baseline']:.3f} | {'是' if row['locked'] else '否'} |"
        )
    lines.extend(["", "## 为跑完一年做的改动", "", changes, ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _time_verdict(w1: dict, w2: dict, w5: dict, time_ratio: float, retrieval_ratio: float) -> str:
    # 用数字下判断，不把“还在涨”说成“已经平稳”。
    bits = []
    if retrieval_ratio > 1.5 or time_ratio > 1.5:
        bits.append(
            f"从第 121–140 天到最后 20 天，检索平均涨到 {_fmt(retrieval_ratio, 2)} 倍，回复平均涨到 {_fmt(time_ratio, 2)} 倍，不能说已经停住。"
        )
    elif retrieval_ratio > 1.15 or time_ratio > 1.15:
        bits.append(
            f"热区封顶之后耗时仍在涨：检索平均 {_fmt(retrieval_ratio, 2)} 倍，回复平均 {_fmt(time_ratio, 2)} 倍。幅度有限，但不是完全的平台。"
        )
    else:
        bits.append(
            f"热区封顶之后，最后 20 天相对第 121–140 天，检索平均 {_fmt(retrieval_ratio, 2)} 倍、回复平均 {_fmt(time_ratio, 2)} 倍，没有再随天数无上限拉开。"
        )
    bits.append(
        f"三个窗口的检索平均依次是 {_fmt(w1['retrieval_avg'], 2)}、{_fmt(w2['retrieval_avg'], 2)}、{_fmt(w5['retrieval_avg'], 2)} ms。"
    )
    return " ".join(bits)


def _load_peanut(store) -> list[dict]:
    rows = store.conn.execute(
        "SELECT fact_id, text, slot, status, importance, strength, mention_count "
        "FROM facts WHERE text LIKE '%花生%' OR slot LIKE '%花生%'"
    ).fetchall()
    return [dict(row) for row in rows]


def run(days: int, db_path: Path, daily_path: Path | None, report_path: Path | None) -> None:
    _reset_db(db_path)
    agent = build_agent(str(db_path))
    rng = random.Random(SEED)
    daily_handle = daily_path.open("w", encoding="utf-8") if daily_path else None
    samples: list[dict] = []
    daily_rows: list[dict] = []
    serial = 1
    hot_max = 0
    buffer_max = 0
    started = time.perf_counter()
    try:
        for index in range(days):
            day = START + timedelta(days=index)
            day_number = index + 1
            day_started = time.perf_counter()
            nap_before = agent.memory.nap_count
            night_before = agent.memory.night_count
            count = _day_count(day, rng)
            facts = _facts_for(day_number)
            chat_count = count - len(facts)
            reply_slots = set(rng.sample(range(chat_count), 8))
            times = _timestamps(day, count)
            prompts: list[float] = []
            totals: list[float] = []
            retrievals: list[float] = []
            sleep_sum = 0.0
            replies = 0
            for offset, ts in enumerate(times):
                if offset < len(facts):
                    text = facts[offset]
                    need = True
                    meta: dict = {}
                else:
                    chat_index = offset - len(facts)
                    text = _chitchat(rng, serial)
                    serial += 1
                    need = chat_index in reply_slots
                    meta = {"skip_extract": True}
                result = agent.handle(
                    Message(
                        ts=ts,
                        session_id=SESSION,
                        speaker_id=SPEAKER,
                        text=text,
                        addressee_ids=("self",) if need else (),
                        meta=meta,
                    ),
                    need_reply=need,
                )
                sleep_sum += result.sleep_ms
                if need:
                    replies += 1
                    prompts.append(float(result.prompt_tokens))
                    totals.append(float(result.total_ms))
                    retrievals.append(float(result.retrieval_ms))
                    samples.append(
                        {
                            "day": day_number,
                            "date": day.date().isoformat(),
                            "prompt_tokens": int(result.prompt_tokens),
                            "total_ms": float(result.total_ms),
                            "retrieval_ms": float(result.retrieval_ms),
                        }
                    )
            hot = agent.memory.store.hot_count()
            buffer = agent.memory.store.buffer_count()
            hot_max = max(hot_max, hot)
            buffer_max = max(buffer_max, buffer)
            row = {
                "date": day.date().isoformat(),
                "day": day_number,
                "messages": count,
                "replies": replies,
                "prompt_tokens_avg": _mean(prompts),
                "prompt_tokens_max": max(prompts) if prompts else 0,
                "total_ms_avg": _mean(totals),
                "total_ms_p95": _p95(totals),
                "retrieval_ms_avg": _mean(retrievals),
                "retrieval_ms_p95": _p95(retrievals),
                "sleep_ms_sum": sleep_sum,
                "hot_sentences": hot,
                "buffer_sentences": buffer,
                "nap_count": agent.memory.nap_count - nap_before,
                "night_count": agent.memory.night_count - night_before,
                "wall_s": time.perf_counter() - day_started,
                "traits": {
                    row["key"]: round(row["weight"], 4)
                    for row in agent.memory.store.traits_for("self")
                },
            }
            daily_rows.append(row)
            if daily_handle is not None:
                daily_handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                daily_handle.flush()
            if day_number % 10 == 0 or day_number == days:
                elapsed = time.perf_counter() - started
                print(
                    f"第 {day_number} 天 {row['date']} 消息 {count} 回复 {replies} "
                    f"热句 {hot} token均 {row['prompt_tokens_avg']:.0f} "
                    f"检索均 {row['retrieval_ms_avg']:.1f}ms 回复均 {row['total_ms_avg']:.1f}ms "
                    f"本日 {row['wall_s']:.1f}s 累计 {elapsed:.0f}s",
                    flush=True,
                )
        flush = agent.memory.flush()
        wall_s = time.perf_counter() - started
        peanut = _load_peanut(agent.memory.store)
        traits = agent.memory.store.traits_for("self")
    finally:
        if daily_handle is not None:
            daily_handle.close()
    print(
        f"完成 {days} 天，壁钟 {wall_s:.1f}s，消息 {sum(r['messages'] for r in daily_rows)}，"
        f"回复 {sum(r['replies'] for r in daily_rows)}，按已跑天数线性外推 365 天约 {wall_s / days * 365 / 60:.1f} 分钟",
        flush=True,
    )
    if report_path is not None:
        _write_report(
            report_path,
            daily=daily_rows,
            samples=samples,
            wall_s=wall_s,
            flush_ms=float(flush.duration_ms),
            peanut_rows=peanut,
            traits=traits,
            hot_max=hot_max,
            buffer_max=buffer_max,
            changes=CHANGES,
        )
        print(f"报告已写入 {report_path}", flush=True)


CHANGES = """先用带整段编号的语料跑了 3 天：第 1 天 0.6 秒、第 2 天 1.3 秒、第 3 天 2.1 秒。编号如果进词表，边会跟着条数涨，外推是十几个小时。

因此改了四处，都没有改上限本身：

1. `Tokenizer.content_words` 在分词前删掉正文里的 `§数字`。原文仍带编号，同一句闲聊全年只出现 1 次；编号不进词表，也不进边。
2. 热句候选改为只看 `tier='hot'` 的倒排，不扫已经冷却的帖子。
3. 去掉编号后再跑，前 30 天检索仍在涨：第 10 天热句 6606、检索平均 132ms；第 20 天热句 13087、348ms；第 30 天热句 19648、560ms。热区快到 20000 时一天大约 6 秒，剩下 330 多天会超过 30 分钟。原因是常见词要在全部热帖上排序才能取出前几条。改成：单词用倒排按 `sent_id` 从新到旧直接截断（在那次 30 天的库上，和按 `ts` 排序取前 N 条的集合一致）；多个词则从最新热句往前收，收满 `candidate_cap` 就停。
4. 截断之后检索停在大约 70ms，但热区一满，把旧句标冷会按 `sent_id` 更新倒排，而倒排主键是 `(word_id, sent_id)`，每次更新都扫全表。第 40 天热句 20000、检索仍是 70ms，可这一天壁钟 17.4 秒，第 31–40 天合计约 96 秒。给 `word_sentence(sent_id)` 加了索引，冷却仍是同一批最旧的热句，只是不再全表扫。

热区上限仍是 20000，提示词硬上限仍是 7000，小睡 600、缓冲区硬上限 2000 没变。没有关睡眠，也没有少入库。

去掉编号后、改截断前，同一套语料的前 3 天壁钟是 4.2 秒。那次外推约 8.5 分钟，没有覆盖热区变满之后的开销，所以不能当成全年时间。

另外，夜间整理内部会再调用一次小睡，所以当天的 `nap_count` 含这次夜间 flush，`night_count` 另计。第 1 天时钟从 0 开始，不会在 03:00 前再睡一次；第 2 天到第 365 天各跨过一次 03:00。火锅句在第 8、15、22……365 天插入（第 1 天之后每 7 天一次）。"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365)
    args = parser.parse_args()
    out = ROOT / "results" / "stage2"
    if args.days >= 365:
        run(365, out / "year.db", out / "daily.jsonl", out / "year_report.md")
    else:
        run(args.days, out / "_speed.db", None, None)


if __name__ == "__main__":
    main()
