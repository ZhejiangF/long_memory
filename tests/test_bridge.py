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
