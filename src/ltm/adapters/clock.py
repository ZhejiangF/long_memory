from __future__ import annotations

import time


class SimClock:
    """实验用时钟。记忆代码只许问它要时间。"""

    def __init__(self, ts: float | None = None) -> None:
        self._ts = time.time() if ts is None else ts

    def now(self) -> float:
        return self._ts

    def set(self, ts: float) -> None:
        self._ts = ts


class SystemClock:
    def now(self) -> float:
        return time.time()
