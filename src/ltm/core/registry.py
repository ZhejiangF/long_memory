"""插件注册表。新能力通过 register 挂进来，不改已有模块。"""

from __future__ import annotations

from typing import Any, Callable

from ltm.core.errors import DuplicatePluginError, UnknownPluginError

_REGISTRY: dict[tuple[str, str], Callable[..., Any]] = {}


def register(kind: str, name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def deco(factory: Callable[..., Any]) -> Callable[..., Any]:
        key = (kind, name)
        if key in _REGISTRY:
            raise DuplicatePluginError(f"插件已存在: {kind}:{name}")
        _REGISTRY[key] = factory
        return factory

    return deco


def create(kind: str, name: str, *args: Any, **kwargs: Any) -> Any:
    key = (kind, name)
    if key not in _REGISTRY:
        known = sorted(n for k, n in _REGISTRY if k == kind)
        raise UnknownPluginError(f"未注册 {kind}:{name}，可用: {known}")
    return _REGISTRY[key](*args, **kwargs)


def available(kind: str) -> list[str]:
    return sorted(n for k, n in _REGISTRY if k == kind)
