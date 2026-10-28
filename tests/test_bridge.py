"""JSONL 桥：宿主的请求要落到真实记忆引擎上，并且能把记忆体清空。"""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

from ltm.service.bridge import Bridge


def _call(bridge: Bridge, op: str, **params) -> dict:
    return bridge.dispatch(json.dumps({"id": 1, "op": op, "params": params}, ensure_ascii=False))


def test_ingest_then_recall() -> None:
    bridge = Bridge(":memory:")
    ingested = _call(bridge, "ingest", text="我家猫叫橘子。", speaker="张磊", ts=1_700_000_000)
    assert ingested["ok"]
    assert ingested["result"]["speaker_id"] == "zhanglei"
    assert _call(bridge, "sleep")["result"]["kind"] == "nap"

    recalled = _call(bridge, "recall", query="猫叫什么", ts=1_700_000_060)
    assert recalled["ok"]
    assert recalled["result"]["count"] >= 1
    texts = "".join(item["text"] + item["rendered"] for item in recalled["result"]["items"])
    assert "橘子" in texts


def test_stats_reports_counts() -> None:
    bridge = Bridge(":memory:")
    _call(bridge, "ingest", text="老周爱钓鱼。", ts=1_700_000_000)
    _call(bridge, "sleep")
    stats = _call(bridge, "stats")["result"]
    assert stats["messages"] == 1
    assert stats["sentences"] >= 1
    assert stats["buffer"] == 0


def test_reset_clears_memories_but_keeps_members() -> None:
    bridge = Bridge(":memory:")
    _call(bridge, "ingest", text="老周爱钓鱼。", ts=1_700_000_000)
    _call(bridge, "sleep")
    assert _call(bridge, "stats")["result"]["messages"] == 1

    cleared = _call(bridge, "reset")["result"]
    assert cleared["cleared"]["messages"] == 1
    assert cleared["stats"]["messages"] == 0
    assert cleared["stats"]["sentences"] == 0
    assert cleared["stats"]["facts_active"] == 0

    members = bridge.memory.store.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    assert members >= len(bridge.cfg["members"])


def test_bad_requests_are_structured_errors() -> None:
    bridge = Bridge(":memory:")
    assert bridge.dispatch("{not json")["error"]["code"] == "BAD_REQUEST"
    assert bridge.dispatch("[]")["error"]["code"] == "BAD_REQUEST"
    assert _call(bridge, "nope")["error"]["code"] == "UNKNOWN_OP"
    assert _call(bridge, "recall", query="  ")["error"]["code"] == "BAD_REQUEST"
    assert _call(bridge, "ingest", text="x", ts=-1)["error"]["code"] == "BAD_REQUEST"


def test_blank_bridge_starts_without_fixture_people() -> None:
    bridge = Bridge(":memory:", blank=True)
    assert bridge.cfg["members"] == []
    assert bridge.memory.store.conn.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0

    ingested = _call(bridge, "ingest", text="我家猫叫橘子。", speaker="张磊", ts=1_700_000_000)
    assert ingested["result"]["speaker_id"] == "张磊"
    assert _call(bridge, "sleep")["ok"]


def test_duplicate_text_is_skipped() -> None:
    bridge = Bridge(":memory:")
    first = _call(bridge, "ingest", text="你好", ts=1_700_000_000)
    second = _call(bridge, "ingest", text="你好", ts=1_700_000_060)
    assert first["result"].get("skipped") is None
    assert second["result"]["skipped"] == "duplicate"
    assert second["result"]["buffered"] == first["result"]["buffered"]


def test_same_text_after_two_minutes_is_recorded() -> None:
    bridge = Bridge(":memory:")
    _call(bridge, "ingest", text="你好", ts=1_700_000_000)
    again = _call(bridge, "ingest", text="你好", ts=1_700_000_200)
    assert again["result"].get("skipped") is None


def test_nap_and_night_settings_are_overridable() -> None:
    bridge = Bridge(":memory:", nap_sentences=5, night_hour=2)
    assert bridge.cfg["buffer"]["nap_sentences"] == 5
    assert bridge.cfg["sleep"]["night_hour"] == 2


def test_nap_override_keeps_other_buffer_settings() -> None:
    bridge = Bridge(":memory:", overrides={"buffer": {"max_sentences": 9}}, nap_sentences=5)
    assert bridge.cfg["buffer"]["max_sentences"] == 9
    assert bridge.cfg["buffer"]["nap_sentences"] == 5


def test_dump_lists_facts_and_sentences() -> None:
    bridge = Bridge(":memory:")
    _call(bridge, "ingest", text="我家猫叫橘子。", speaker="张磊", ts=1_700_000_000)
    _call(bridge, "sleep")
    data = _call(bridge, "dump")["result"]
    assert data["facts"]
    assert data["facts"][0]["owner"] == "张磊"
    assert data["sentences"]
    assert "橘子" in data["sentences"][0]["text"]
    # 最近几条消息：给「不看窗口」的宿主接上下文用，从早到晚
    assert data["recent"]
    assert data["recent"][-1]["text"] == "我家猫叫橘子。"


def test_dump_recent_can_be_limited_to_one_session() -> None:
    bridge = Bridge(":memory:")
    _call(bridge, "ingest", text="群里的闲聊", speaker="张磊", session_id="群A", ts=1_700_000_000)
    _call(bridge, "ingest", text="私聊里的一句话", speaker="张磊", session_id="私聊B", ts=1_700_000_060)
    data = _call(bridge, "dump", session_id="私聊B", recent=5)["result"]
    assert [row["text"] for row in data["recent"]] == ["私聊里的一句话"]


def test_dump_is_empty_on_blank_memory() -> None:
    bridge = Bridge(":memory:")
    data = _call(bridge, "dump")["result"]
    assert data["facts"] == []
    assert data["sentences"] == []
    assert data["recent"] == []


def test_missing_parent_directory_is_created() -> None:
    base = Path(".tmp") / "test-bridge-db"
    target = base / "nested" / "ltm" / "memory.db"
    shutil.rmtree(base, ignore_errors=True)
    bridge = Bridge(str(target))
    try:
        assert target.exists()
        assert _call(bridge, "stats")["result"]["messages"] == 0
    finally:
        bridge.memory.store.close()
        shutil.rmtree(base, ignore_errors=True)


def test_serve_reads_and_writes_one_json_per_line() -> None:
    bridge = Bridge(":memory:")
    stdin = io.StringIO(
        json.dumps({"id": "a", "op": "ping"}) + "\n"
        + "\n"
        + json.dumps({"id": "b", "op": "stats"}) + "\n"
    )
    stdout = io.StringIO()
    bridge.serve(stdin, stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [line["id"] for line in lines] == ["a", "b"]
    assert all(line["ok"] for line in lines)
