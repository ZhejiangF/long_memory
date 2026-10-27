"""规则抽取。要换大模型抽取，实现同样的 extract，并在工厂里换插件名。"""

from __future__ import annotations

import re

from ltm.components.text import is_question

_ALLERGEN = re.compile(r"对(.{1,8}?)过敏")
_CITY_MOVE = re.compile(r"搬到([\u4e00-\u9fff]{2,4})")
_CITY_LIVE = re.compile(r"住在([\u4e00-\u9fff]{2,4})")


def classify(text: str) -> tuple[int, str]:
    allergen = _ALLERGEN.search(text)
    if allergen:
        return 10, "过敏:" + allergen.group(1)
    if "不吃" in text:
        return 9, "饮食禁忌"
    if "我叫" in text or text.startswith("你好，我叫"):
        return 8, "姓名"
    if any(k in text for k in ("妹妹", "女朋友", "妈妈", "爸爸", "小孩")):
        return 8, "亲属"
    if "生日" in text:
        return 8, "生日"
    if _CITY_MOVE.search(text) or _CITY_LIVE.search(text) or "分部" in text:
        return 8, "居住城市"
    if any(k in text for k in ("跑步", "游泳", "膝盖")):
        return 7, "运动习惯"
    if any(k in text for k in ("工作", "开发", "老师", "实习", "工程师")):
        return 7, "职业"
    if any(k in text for k in ("喜欢", "不吃", "火锅", "咖啡", "美式", "绿茶")):
        return 6, "偏好"
    return 4, "其他"


def to_third_person(text: str, name: str) -> str:
    body = text.replace("我家", f"{name}家").replace("我不", f"{name}不")
    if body.startswith("我"):
        body = name + body[1:]
    elif "我" in body:
        body = body.replace("我", name, 1)
    return body


class RuleExtractor:
    def extract(self, text: str, speaker_id: str, speaker_name: str, skip: bool = False) -> list[dict]:
        if skip or is_question(text) or speaker_id == "self":
            return []
        importance, slot = classify(text)
        return [
            {
                "text": to_third_person(text, speaker_name),
                "owner_id": speaker_id,
                "slot": slot,
                "importance": importance,
            }
        ]


def jaccard(a: list[str], b: list[str]) -> float:
    left, right = set(a), set(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


# 这些槽位同一人只保留最新的一条，旧的标成已过时。
SUPERSEDE_SLOTS = {"居住城市", "运动习惯"}
