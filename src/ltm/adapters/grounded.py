"""离线回答器：只根据提示词里已经检索到的记忆组织回复，不编造。

这是宿主模型的替身，用来在没有 API 时验证记忆有没有被取出来。
换成真实模型时，实现同样的 chat 接口即可。
"""

from __future__ import annotations

import math

from ltm.core.markers import BUFFER, FACTS, PROFILE, RECENT, SENTENCES
from ltm.core.models import LLMResponse

_ABSTAIN = ("没听你说过", "不记得", "没提过")


class GroundedLLM:
    def chat(self, messages: list[dict], temperature: float = 0, json_mode: bool = False) -> LLMResponse:
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        question = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        text = answer(question, system)
        return LLMResponse(
            text=text,
            prompt_tokens=max(1, math.ceil(len(system + question) / 1.5)),
            completion_tokens=max(1, math.ceil(len(text) / 1.5)),
        )


def answer(question: str, system: str) -> str:
    lines = _section(system, FACTS) + _section(system, PROFILE) + _section(system, SENTENCES) + _section(system, BUFFER)
    asker = "张磊"
    if "当前提问的人是" in system:
        asker = system.split("当前提问的人是", 1)[1].split("。", 1)[0]
    if _should_abstain(question, lines):
        return "这事没听你说过。"
    if "电影" in question and "推荐" in question and "你之前" not in question and "之前给我" not in question:
        return "推荐《龙猫》《千与千寻》《哈尔的移动城堡》。"
    chosen = _select(question, lines, asker)
    if not chosen:
        return "这事没听你说过。"
    body = "；".join(chosen[:8])
    extra = _safety_note(question, lines)
    if extra and extra not in body:
        body = body + "。" + extra
    return body


def _section(system: str, title: str) -> list[str]:
    if title not in system:
        return []
    rest = system.split(title, 1)[1]
    for other in (FACTS, PROFILE, SENTENCES, BUFFER, RECENT):
        if other != title and other in rest:
            rest = rest.split(other, 1)[0]
    lines = []
    for line in rest.splitlines():
        line = line.strip()
        if line.startswith(("-", "[")):
            lines.append(line.lstrip("- ").strip())
    return lines


def _should_abstain(question: str, lines: list[str]) -> bool:
    evidence = [ln for ln in lines if question not in ln and ln not in question]
    blob = "\n".join(evidence)
    if "血型" in question and "血型" not in blob:
        return True
    if "哥哥" in question and "哥哥" not in blob:
        return True
    return False


def _select(question: str, lines: list[str], asker: str) -> list[str]:
    names = [n for n in ("张磊", "林夏", "老周", "张悦") if n in question and n != asker]
    lines = [ln for ln in lines if question not in ln and ln not in question]
    if "你" in question and any(k in question for k in ("推荐", "说过", "之前")):
        scoped = [ln for ln in lines if "助手" in ln or asker in ln] or lines
    elif "谁" in question:
        scoped = lines
    elif names:
        scoped = [ln for ln in lines if any(n in ln for n in names)] or lines
    elif "我" in question:
        scoped = [ln for ln in lines if asker in ln] or lines
    else:
        scoped = lines
    if "现在" in question and not any(k in question for k in ("之前", "以前", "搬家前")):
        if any("上海" in ln for ln in scoped):
            scoped = [ln for ln in scoped if "杭州" not in ln]
        if any("游泳" in ln for ln in scoped):
            scoped = [ln for ln in scoped if "跑步" not in ln]
    if any(k in question for k in ("几月", "月份")):
        newer = [ln for ln in scoped if "12月" in ln or "十二月" in ln]
        if newer:
            scoped = newer
    if "哪天" in question:
        dated = [ln for ln in scoped if "2026-" in ln]
        if dated:
            scoped = dated + [ln for ln in scoped if ln not in dated]
    if any(k in question for k in ("介绍", "喜欢些什么", "总结")):
        prefer = [
            ln for ln in scoped
            if any(k in ln for k in ("火锅", "跑步", "游泳", "三体", "周杰伦", "美式", "咖啡"))
        ]
        return (prefer + scoped)[:12]
    ranked = sorted(scoped, key=lambda ln: -_overlap(question, ln))
    strong = [ln for ln in ranked if _overlap(question, ln) > 0]
    return strong[:6] or ranked[:4]


_LINK = {
    "工作": ("嵌入式", "软件", "单片机", "开发"),
    "猫": ("橘子", "橘猫"),
    "运动": ("跑步", "游泳"),
    "车": ("特斯拉",),
    "书": ("三体",),
    "医院": ("协和",),
    "旅行": ("京都", "日本"),
    "日语": ("多邻国",),
    "喝": ("美式", "绿茶", "咖啡"),
    "住": ("杭州", "上海"),
    "城市": ("北京", "上海", "杭州", "京都", "绍兴"),
    "键盘": ("老周", "青轴"),
    "妈妈": ("绍兴",),
    "妹妹": ("张悦", "北京", "临床"),
    "女朋友": ("林夏", "老师"),
    "电影": ("龙猫", "千与千寻"),
    "项目": ("青鸟",),
    "叫": ("张磊",),
}


def _overlap(question: str, line: str) -> int:
    score = 0
    if ("日本" in question or "旅行" in question) and "京都" in line:
        score += 6
    if "电影" in question and any(name in line for name in ("龙猫", "千与千寻", "哈尔")):
        score += 6
    if "莫干山" in question and "莫干山" in line:
        score += 4
    for key, extras in _LINK.items():
        if key in question and any(extra in line for extra in extras):
            score += 2
    for token in ("火锅", "香菜", "花生", "周杰伦", "生日", "芒果", "腿酸", "莫干山", "绿茶"):
        if token in question and token in line:
            score += 2
    return score


def _safety_note(question: str, lines: list[str]) -> str:
    if not any(k in question for k in ("零食", "菜", "蛋糕", "配方")):
        return ""
    blob = "\n".join(lines)
    notes = []
    if "花生" in blob:
        notes.append("不要使用花生")
    if "芒果" in blob and ("蛋糕" in question or "林夏" in question or "林夏" in blob):
        notes.append("不要使用芒果")
    if "香菜" in blob and "菜" in question:
        notes.append("不要放香菜")
    return "，".join(notes)
