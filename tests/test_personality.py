"""性格：整理后用事实更新特质，并在回复提示词里生效。"""

from __future__ import annotations

from ltm.components.personality import DEFAULTS, Personality, OWNER
from ltm.core.config import load_settings
from ltm.core.models import Message, Query
from ltm.service.factory import build_agent


def _bridge_like(tmp_path, overrides=None):
    cfg = load_settings(None, overrides)
    from ltm.adapters.sqlite_store import SqliteStore
    from ltm.components.identity import IdentityBook
    from ltm.components.text import Tokenizer

    store = SqliteStore(":memory:")
    store.seed_members(cfg["members"])
    return store, Personality(store, cfg), cfg


def test_defaults_before_any_consolidation() -> None:
    store, personality, cfg = _bridge_like(None)
    assert personality.weights() == DEFAULTS
    assert store.traits_for(OWNER) == []


def test_allergy_fact_raises_care_within_daily_cap() -> None:
    store, personality, cfg = _bridge_like(None)
    personality.ensure(1_700_000_000)
    changes = personality.observe(
        [{"slot": "过敏:花生", "importance": 10}], 1_700_000_000
    )
    assert "关怀" in changes
    cap = cfg["personality"]["max_daily_delta"]
    assert changes["关怀"] <= cap + 1e-9
    assert personality.weights()["关怀"] > 0.5


def test_daily_cap_is_enforced_across_many_facts() -> None:
    store, personality, cfg = _bridge_like(None)
    personality.ensure(1_700_000_000)
    drafts = [{"slot": "过敏:花生", "importance": 10} for _ in range(50)]
    changes = personality.observe(drafts, 1_700_000_000)
    cap = cfg["personality"]["max_daily_delta"]
    assert changes["关怀"] <= cap + 1e-9
    # 同一天再整理也不会再涨
    more = personality.observe(drafts, 1_700_003_600)
    assert more == {}


def test_preference_fact_raises_warmth() -> None:
    store, personality, cfg = _bridge_like(None)
    personality.ensure(1_700_000_000)
    changes = personality.observe([{"slot": "偏好", "importance": 9}], 1_700_000_000)
    assert changes.get("热情", 0) > 0


def test_locked_trait_does_not_move() -> None:
    store, personality, cfg = _bridge_like(None)
    personality.ensure(1_700_000_000)
    store.upsert_trait(OWNER, "关怀", "style", 0.5, 0.5, True, 1_700_000_000)
    changes = personality.observe([{"slot": "过敏:花生", "importance": 10}], 1_700_000_000)
    assert "关怀" not in changes
    assert personality.weights()["关怀"] == 0.5


def test_instructions_appear_in_prompt_after_consolidation(tmp_path=None) -> None:
    agent = build_agent(":memory:")
    memory = agent.memory
    memory.ingest(
        Message(
            ts=1_700_000_000,
            session_id="生活群",
            speaker_id="zhanglei",
            text="我对花生过敏。",
            addressee_ids=("self",),
        )
    )
    memory.flush()
    weights = memory.personality.weights()
    assert weights["关怀"] > 0.5

    query = Query(text="我能吃花生吗", asker_id="zhanglei", session_id="生活群", ts=1_700_000_060)
    retrieved = memory.retrieve(query)
    system, tokens, _usage = memory.build_prompt(query, retrieved)
    assert "【我的性格】" in system
    assert "关怀" in system
    assert tokens > 0
