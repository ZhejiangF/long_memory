"""强度、保持率、边权。全部是纯函数，方便单测。"""

from __future__ import annotations

import math


def initial_strength(personal_importance: float, cfg: dict) -> float:
    return cfg["s_init_base"] + personal_importance / 10.0


def retention(strength: float, last_access_ts: float, now: float, cfg: dict) -> float:
    if strength <= 0:
        return 0.0
    age_days = max(0.0, (now - last_access_ts) / 86400.0)
    return math.exp(-age_days / (cfg["tau_days"] * strength))


def reinforce(strength: float, amount: float, cfg: dict) -> float:
    return min(cfg["s_max"], strength + amount)


def is_longterm(strength: float, cfg: dict) -> bool:
    return strength >= cfg["longterm_strength"]


def is_pinned(strength: float, importance: int, status: str, cfg: dict) -> bool:
    return status == "active" and (
        strength >= cfg["longterm_strength"] or importance >= cfg["pinned_importance"]
    )


def should_sleep(strength: float, importance: int, keep: float, cfg: dict) -> bool:
    return (
        keep < cfg["dormant_retention"]
        and strength < cfg["longterm_strength"]
        and importance < cfg["pinned_importance"]
    )


def edge_effective_weight(weight: float, count: int, last_ts: float, now: float, graph_cfg: dict) -> float:
    age_days = max(0.0, (now - last_ts) / 86400.0)
    scale = graph_cfg["tau_edge_days"] * (1.0 + math.log(1.0 + max(count, 1)))
    return weight * math.exp(-age_days / scale)
