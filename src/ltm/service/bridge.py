"""JSONL 桥：把记忆引擎交给非 Python 宿主（例如 DSH 插件）按行调用。

一行一个请求，一行一个响应：

    {"id": 1, "op": "recall", "params": {"query": "猫叫什么"}}
    {"id": 1, "ok": true, "result": {"items": [...]}}

本模块只做协议和参数翻译，记忆规则仍在 components / adapters 里。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Callable

from ltm.core.models import Message, Query, SleepReport
from ltm.service.factory import build_agent

DEFAULT_SPEAKER = "user"


class BridgeError(Exception):
    """可以直接回给宿主的请求错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class Bridge:
    def __init__(
        self,
        db_path: str = ":memory:",
        config_path: str | None = None,
        overrides: dict | None = None,
        blank: bool = False,
    ) -> None:
        if blank:
            # 空白记忆体：不预置阶段一那批人名，成员随第一次出现自动登记成 @名字。
            overrides = {**(overrides or {}), "members": []}
        self.agent = build_agent(db_path, config_path, overrides)
        self.memory = self.agent.memory
        self.cfg = self.agent.cfg
        self.db_path = db_path
        self.speakers = _speaker_table(self.cfg["members"])

    # ---- 协议 ----
    def dispatch(self, line: str) -> dict[str, Any]:
        req_id: Any = None
        try:
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BridgeError("BAD_REQUEST", f"不是合法的 JSON：{exc.msg}") from None
            if not isinstance(request, dict):
                raise BridgeError("BAD_REQUEST", "请求必须是 JSON 对象")
            req_id = request.get("id")
            params = request.get("params") or {}
            if not isinstance(params, dict):
                raise BridgeError("BAD_REQUEST", "params 必须是对象")
            handler = self._handlers().get(request.get("op"))
            if handler is None:
                raise BridgeError("UNKNOWN_OP", f"未知操作：{request.get('op')!r}")
            return {"id": req_id, "ok": True, "result": handler(params)}
        except BridgeError as exc:
            return {"id": req_id, "ok": False, "error": {"code": exc.code, "message": str(exc)}}
        except Exception as exc:  # 宿主拿到结构化错误，进程继续服务
            return {
                "id": req_id,
                "ok": False,
                "error": {"code": "INTERNAL", "message": f"{type(exc).__name__}: {exc}"},
            }

    def serve(self, stdin=None, stdout=None) -> None:
        stdin = stdin or sys.stdin
        stdout = stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            response = self.dispatch(line)
            try:
                stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                stdout.flush()
            except BrokenPipeError:  # 宿主已经退出
                return

    # ---- 操作 ----
    def _handlers(self) -> dict[str, Callable[[dict], dict]]:
        return {
            "ping": self._ping,
            "ingest": self._ingest,
            "recall": self._recall,
            "sleep": self._sleep,
            "stats": self._stats,
            "reset": self._reset,
        }

    def _ping(self, params: dict) -> dict:
        return {"pong": True, "db": self.db_path}

    def _ingest(self, params: dict) -> dict:
        text = str(params.get("text") or "").strip()
        if not text:
            raise BridgeError("BAD_REQUEST", "text 不能为空")
        ts = _ts(params.get("ts"), self.memory.clock.now())
        speaker = self._speaker(params.get("speaker"))
        asleep = [_report(report) for report in self.memory.advance_time(ts)]
        message = Message(
            ts=ts,
            session_id=str(params.get("session_id") or self.cfg["identity"]["session_id"]),
            speaker_id=speaker,
            text=text,
            addressee_ids=tuple(params.get("addressee_ids") or ()),
            meta=dict(params.get("meta") or {}),
        )
        nap = self.memory.ingest(message)
        if nap is not None:
            asleep.append(_report(nap))
        return {"speaker_id": speaker, "buffered": self.memory.store.buffer_count(), "sleep": asleep}

    def _recall(self, params: dict) -> dict:
        text = str(params.get("query") or "").strip()
        if not text:
            raise BridgeError("BAD_REQUEST", "query 不能为空")
        ts = _ts(params.get("ts"), self.memory.clock.now())
        asker = self._speaker(params.get("asker") or params.get("speaker"))
        limit = _limit(params.get("limit"), 8)
        result = self.memory.retrieve(
            Query(
                text=text,
                asker_id=asker,
                session_id=str(params.get("session_id") or self.cfg["identity"]["session_id"]),
                ts=ts,
            )
        )
        items = [
            {
                "source": item.source,
                "ref_id": str(item.ref_id),
                "text": item.text,
                "rendered": item.rendered,
                "score": round(float(item.score), 4),
                "speaker_id": item.speaker_id,
            }
            for item in result.items[:limit]
        ]
        return {
            "items": items,
            "count": len(items),
            "active_words": list(result.debug.get("active_words", []))[:12],
        }

    def _sleep(self, params: dict) -> dict:
        return _report(self.memory.flush())

    def _stats(self, params: dict) -> dict:
        conn = self.memory.store.conn

        def count(sql: str) -> int:
            row = conn.execute(sql).fetchone()
            return int(row[0]) if row else 0

        return {
            "db": self.db_path,
            "db_bytes": _file_size(self.db_path),
            "messages": count("SELECT COUNT(*) FROM messages"),
            "buffer": self.memory.store.buffer_count(),
            "sentences": count("SELECT COUNT(*) FROM sentences"),
            "facts_active": count("SELECT COUNT(*) FROM facts WHERE status='active'"),
            "facts_dormant": count("SELECT COUNT(*) FROM facts WHERE status='dormant'"),
            "vocab": count("SELECT COUNT(*) FROM vocab"),
            "clock_ts": self.memory.clock.now(),
        }

    def _reset(self, params: dict) -> dict:
        cleared = self.memory.store.reset_memories()
        return {"cleared": cleared, "stats": self._stats({})}

    # ---- 参数翻译 ----
    def _speaker(self, raw: Any) -> str:
        if raw is None or str(raw).strip() == "":
            return DEFAULT_SPEAKER
        text = str(raw).strip()
        if text in self.speakers:
            return self.speakers[text]
        return text


def _speaker_table(members: list[dict]) -> dict[str, str]:
    table: dict[str, str] = {}
    for member in members:
        table.setdefault(member["id"], member["id"])
        table.setdefault(member["name"], member["id"])
        for alias in member.get("aliases", []):
            table.setdefault(alias, member["id"])
    return table


def _ts(raw: Any, fallback: float) -> float:
    if raw is None or raw == "":
        return float(fallback)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise BridgeError("BAD_REQUEST", "ts 必须是秒级时间戳") from None
    if value <= 0:
        raise BridgeError("BAD_REQUEST", "ts 必须大于 0")
    return value


def _limit(raw: Any, fallback: int) -> int:
    if raw is None or raw == "":
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise BridgeError("BAD_REQUEST", "limit 必须是整数") from None
    return max(1, min(value, 50))


def _report(report: SleepReport) -> dict:
    return {
        "kind": report.kind,
        "started_ts": report.started_ts,
        "duration_ms": round(float(report.duration_ms), 1),
        "stage_stats": dict(report.stage_stats),
    }


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path) if path != ":memory:" else 0
    except OSError:
        return 0


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="ltm 的 JSONL stdio 桥")
    parser.add_argument("--db", default=":memory:", help="SQLite 文件；:memory: 表示不落盘")
    parser.add_argument("--config", default=None, help="覆盖用的 YAML 配置")
    parser.add_argument("--reset", action="store_true", help="启动时先清空库里的旧记忆体")
    parser.add_argument("--blank", action="store_true", help="空白记忆体：不预置任何人名")
    args = parser.parse_args(argv)
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    bridge = Bridge(args.db, args.config, blank=args.blank)
    if args.reset:
        bridge.memory.store.reset_memories()
    bridge.serve()


if __name__ == "__main__":
    main()
