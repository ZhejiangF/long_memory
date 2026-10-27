"""不联网的哈希嵌入。换句子向量模型时实现同样的 embed 接口即可。"""

from __future__ import annotations

import hashlib
import math


class HashEmbedder:
    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        raw = text.strip()
        if len(raw) < 2:
            raw = raw + " "
        for i in range(len(raw) - 1):
            digest = hashlib.md5(raw[i : i + 2].encode("utf-8")).hexdigest()
            vec[int(digest, 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
