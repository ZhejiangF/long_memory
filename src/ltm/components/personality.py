"""性格：每次整理后用这批事实小幅调整特质，再把特质写进回复提示词。

设计见 `长期记忆方案评估与实现.md` 4.6。这里是可运行的简化版：
- 只维护助手自己的风格特质（关怀、热情、简洁、幽默），成员画像仍由事实表承担；
- 证据来自每次整理抽出的事实（过敏/禁忌 → 关怀，喜好/兴趣 → 热情）；
- 每次变化受每日上限、上下界与回归基线约束，锁定的特质不动。
"""

from __future__ import annotations

from datetime import datetime

OWNER = "self"
CATEGORY = "style"

# 初始值即基线；调整只会在这条基线附近小步移动。
DEFAULTS: dict[str, float] = {"关怀": 0.5, "热情": 0.5, "简洁": 0.5, "幽默": 0.3}

# 事实槽位前缀 → (特质, 信号强度)。槽位来自 RuleExtractor.classify：
# 过敏:花生 / 饮食禁忌 / 姓名 / 亲属 / 生日 / 居住城市 / 运动习惯 / 职业 / 偏好 / 其他。
SLOT_SIGNALS: tuple[tuple[str, str, float], ...] = (
    ("过敏", "关怀", 1.0),
    ("饮食禁忌", "关怀", 0.9),
    ("亲属", "关怀", 0.6),
    ("生日", "关怀", 0.5),
    ("姓名", "关怀", 0.3),
    ("偏好", "热情", 0.8),
    ("运动习惯", "热情", 0.5),
    ("居住城市", "热情", 0.2),
)

# 权重达标时追加的回复指令（阈值可在配置里覆盖）。
STYLE_RULES: tuple[tuple[str, float, str], ...] = (
    ("关怀", 0.6, "回答里体现对对方状态和禁忌的关心。"),
    ("热情", 0.6, "语气主动、热络一些。"),
    ("简洁", 0.7, "尽量三句话以内。"),
    ("幽默", 0.6, "可以适当幽默。"),
)


class Personality:
    def __init__(self, store, cfg: dict) -> None:
        self.store = store
        self.cfg = cfg

    # ---- 读写 ----
    def weights(self) -> dict[str, float]:
        rows = {row["key"]: row for row in self.store.traits_for(OWNER)}
        out: dict[str, float] = {}
        for key, default in DEFAULTS.items():
            out[key] = rows[key]["weight"] if key in rows else default
        return out

    def locked(self, key: str) -> bool:
        return any(row["key"] == key and row["locked"] for row in self.store.traits_for(OWNER))

    def ensure(self, ts: float) -> None:
        existing = {row["key"] for row in self.store.traits_for(OWNER)}
        for key, value in DEFAULTS.items():
            if key not in existing:
                self.store.upsert_trait(OWNER, key, CATEGORY, value, value, False, ts)

    # ---- 整理后调整 ----
    def observe(self, drafts: list[dict], ts: float) -> dict[str, float]:
        """用这次整理出的事实调整特质，返回实际变化量。"""
        person = self.cfg["personality"]
        if not drafts:
            return {}
        wanted: dict[str, float] = {}
        for draft in drafts:
            slot = str(draft.get("slot") or "")
            importance = float(draft.get("importance") or 0)
            for prefix, trait, strength in SLOT_SIGNALS:
                if slot.startswith(prefix):
                    wanted[trait] = wanted.get(trait, 0.0) + strength * (importance / 10.0)
                    break

        bounds = person["weight_bounds"]
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        changes: dict[str, float] = {}
        for trait, signal in wanted.items():
            if self.locked(trait):
                continue
            weight = self.weights().get(trait, DEFAULTS.get(trait, 0.5))
            baseline = DEFAULTS.get(trait, 0.5)
            delta = person["learning_rate"] * signal
            remaining = self._daily_budget(day, trait, person["max_daily_delta"])
            delta = max(-remaining, min(remaining, delta))
            if delta == 0:
                continue
            delta += person["homeostasis"] * (baseline - weight)
            new_weight = max(bounds[0], min(bounds[1], weight + delta))
            if abs(new_weight - weight) < 1e-9:
                continue
            self.store.upsert_trait(OWNER, trait, CATEGORY, new_weight, baseline, False, ts)
            self._add_daily_budget(day, trait, abs(new_weight - weight))
            changes[trait] = round(new_weight - weight, 4)
        if changes:
            self.store.commit()
        return changes

    def _daily_budget(self, day: str, trait: str, cap: float) -> float:
        used = float(self.store.get_kv(f"trait_delta:{day}:{trait}", "0") or 0)
        return max(0.0, cap - used)

    def _add_daily_budget(self, day: str, trait: str, amount: float) -> None:
        used = float(self.store.get_kv(f"trait_delta:{day}:{trait}", "0") or 0)
        self.store.set_kv(f"trait_delta:{day}:{trait}", f"{used + amount:.6f}")

    # ---- 用于回复 ----
    def instructions(self) -> str:
        weights = self.weights()
        rules = self.cfg["personality"].get("style_rules") or STYLE_RULES
        numbers = "、".join(f"{key} {value:.2f}" for key, value in weights.items())
        lines = [f"【我的性格】{numbers}"]
        for trait, threshold, text in rules:
            if weights.get(trait, 0.0) >= float(threshold):
                lines.append(f"- {text}")
        return "\n".join(lines)
