"""同步事件。订阅方抛错只记日志，不影响主流程。"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Callable

log = logging.getLogger("ltm.events")
_subs: dict[str, list[Callable[..., None]]] = defaultdict(list)


def subscribe(name: str, fn: Callable[..., None]) -> None:
    _subs[name].append(fn)


def emit(name: str, **payload: Any) -> None:
    for fn in list(_subs.get(name, ())):
        try:
            fn(**payload)
        except Exception:
            log.exception("事件订阅失败: %s", name)


def clear() -> None:
    _subs.clear()
