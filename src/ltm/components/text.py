"""分词、拆句、停用词。jieba 不可用时退回词表最长匹配。"""

from __future__ import annotations

import re

try:
    import jieba
except ImportError:  # pragma: no cover
    jieba = None

_PUNCT = set(" \t\r\n,，.。!！?？;；、:：\"'“”‘’（）()[]【】<>《》…—-~·")
# 不能把吃、喝、喜欢、不、过敏放进停用词，否则偏好和禁忌的边会断。
_STOP = set(
    "的 了 吗 呢 啊 吧 呀 哦 嗯 是 在 有 就 都 而 及 与 或 被 把 这 那 一个 我们 "
    "他们 自己 什么 怎么 如何 为什么 这个 那个 然后 因为 所以 如果 但是 还是 "
    "已经 可以 没有 帮 请 一下 啦 嘛 哈 很 太 又 也 再 才 只 去 来 到 给 让 从 "
    "对 和 跟 过 着 我 你 他 她 它 您 大家 自己 就是 还 要 会 能 想 说 做 看 "
    "今天 昨天 明天 现在 时候 东西 一点 真的 特别 比较".split()
)
_LEXICON = [
    "张磊", "林夏", "老周", "张悦", "助手", "磊哥", "夏夏", "周哥", "悦悦",
    "嵌入式", "软件开发", "单片机", "火锅", "香菜", "花生", "橘子", "橘猫",
    "美式", "咖啡", "周杰伦", "三体", "跑步", "游泳", "多邻国", "日语", "京都",
    "杭州", "上海", "滨江", "绍兴", "生日", "妹妹", "女朋友", "妈妈", "老师",
    "语文", "临床医学", "协和", "医院", "实习", "机械键盘", "青轴", "青鸟",
    "智能门锁", "特斯拉", "宫崎骏", "绿茶", "芒果", "莫干山", "徒步", "花生过敏",
    "公开课", "三年级", "一年级", "华为", "驱动", "布偶", "吉他", "年糕",
    "喜欢", "过敏", "不吃", "居住", "搬家", "推荐", "电影", "龙猫", "千与千寻",
]
_SPLIT = re.compile(r"[。！？!?；;\n]+")
# 全年语料用 §数字 保证同一句不重复。编号不是实词，不进词表、也不进边。
_SERIAL = re.compile(r"§\d+")


def is_question(text: str) -> bool:
    if any(mark in text for mark in ("?", "？")):
        return True
    keys = ("什么", "怎么", "如何", "哪", "吗", "谁", "多少", "几")
    if any(k in text for k in keys):
        return True
    head = text.lstrip("@助手 ").lstrip()
    return head.startswith(("帮我", "推荐", "解释", "考考", "给我"))


class Tokenizer:
    def __init__(self) -> None:
        self._lex = sorted(set(_LEXICON), key=len, reverse=True)
        if jieba is not None:
            for word in self._lex:
                jieba.add_word(word)

    def split_sentences(self, text: str) -> list[str]:
        parts = [p.strip() for p in _SPLIT.split(text) if p.strip()]
        return parts or ([text.strip()] if text.strip() else [])

    def content_words(self, text: str) -> list[str]:
        text = _SERIAL.sub(" ", text)
        raw = jieba.lcut(text) if jieba is not None else self._fallback(text)
        out: list[str] = []
        seen: set[str] = set()
        for word in raw:
            word = word.strip()
            if len(word) < 1 or word in _STOP or word in _PUNCT:
                continue
            if all(ch in _PUNCT for ch in word):
                continue
            if word not in seen:
                seen.add(word)
                out.append(word)
        return out

    def _fallback(self, text: str) -> list[str]:
        out: list[str] = []
        i = 0
        while i < len(text):
            if text[i] in _PUNCT:
                i += 1
                continue
            if text[i].isascii():
                j = i + 1
                while j < len(text) and text[j].isascii() and text[j] not in _PUNCT:
                    j += 1
                out.append(text[i:j])
                i = j
                continue
            hit = ""
            for word in self._lex:
                if text.startswith(word, i):
                    hit = word
                    break
            if hit:
                out.append(hit)
                i += len(hit)
            else:
                nxt = text[i : i + 2]
                if len(nxt) == 2:
                    out.append(nxt)
                    i += 2
                else:
                    i += 1
        return out
