"""SQLite 存储。换数据库时保持这些方法的含义不变。"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS members (
  speaker_id TEXT PRIMARY KEY, name TEXT NOT NULL, aliases TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS vocab (
  word_id INTEGER PRIMARY KEY AUTOINCREMENT, word TEXT UNIQUE NOT NULL, df INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
  msg_id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, session_id TEXT NOT NULL,
  speaker_id TEXT NOT NULL, addressee_ids TEXT NOT NULL, text TEXT NOT NULL, meta TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS buffer (
  buf_id INTEGER PRIMARY KEY AUTOINCREMENT, msg_id INTEGER NOT NULL, idx INTEGER NOT NULL,
  ts REAL NOT NULL, session_id TEXT NOT NULL, speaker_id TEXT NOT NULL,
  text TEXT NOT NULL, words TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sentences (
  sent_id INTEGER PRIMARY KEY AUTOINCREMENT, msg_id INTEGER NOT NULL, idx INTEGER NOT NULL,
  ts REAL NOT NULL, session_id TEXT NOT NULL, speaker_id TEXT NOT NULL, text TEXT NOT NULL,
  words TEXT NOT NULL, tier TEXT NOT NULL DEFAULT 'hot', recall_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS word_sentence (
  word_id INTEGER NOT NULL, sent_id INTEGER NOT NULL, tier TEXT NOT NULL DEFAULT 'hot',
  PRIMARY KEY (word_id, sent_id)
);
CREATE TABLE IF NOT EXISTS word_edges (
  w1 INTEGER NOT NULL, w2 INTEGER NOT NULL, weight REAL NOT NULL, count INTEGER NOT NULL,
  first_ts REAL NOT NULL, last_ts REAL NOT NULL, PRIMARY KEY (w1, w2)
);
CREATE TABLE IF NOT EXISTS edge_sources (
  w1 INTEGER NOT NULL, w2 INTEGER NOT NULL, sent_id INTEGER NOT NULL,
  PRIMARY KEY (w1, w2, sent_id)
);
CREATE TABLE IF NOT EXISTS facts (
  fact_id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, owner_id TEXT NOT NULL,
  slot TEXT NOT NULL, words TEXT NOT NULL, importance INTEGER NOT NULL,
  personal_importance REAL NOT NULL, strength REAL NOT NULL, created_ts REAL NOT NULL,
  last_access_ts REAL NOT NULL, mention_count INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL, superseded_by INTEGER, source_turns TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traits (
  owner_id TEXT NOT NULL, key TEXT NOT NULL, category TEXT NOT NULL,
  weight REAL NOT NULL, baseline REAL NOT NULL, locked INTEGER NOT NULL,
  updated_ts REAL NOT NULL, PRIMARY KEY (owner_id, key)
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_ws_word ON word_sentence(word_id, tier);
CREATE INDEX IF NOT EXISTS idx_ws_sent ON word_sentence(sent_id);
CREATE INDEX IF NOT EXISTS idx_sent_tier ON sentences(tier, ts);
CREATE INDEX IF NOT EXISTS idx_facts_owner ON facts(owner_id, status);
"""

# 清空记忆体时按这个顺序删；members / schema_meta 是身份与版本，不动。
MEMORY_TABLES = (
    "word_sentence",
    "edge_sources",
    "word_edges",
    "sentences",
    "buffer",
    "facts",
    "traits",
    "messages",
    "vocab",
    "kv",
)


class SqliteStore:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)
        self.conn.execute(
            "INSERT INTO schema_meta(key, value) VALUES('version', '1') "
            "ON CONFLICT(key) DO NOTHING"
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def seed_members(self, members: list[dict]) -> None:
        for m in members:
            self.conn.execute(
                "INSERT OR REPLACE INTO members(speaker_id, name, aliases) VALUES(?,?,?)",
                (m["id"], m["name"], json.dumps(m.get("aliases", []), ensure_ascii=False)),
            )
        self.conn.commit()

    def intern(self, word: str) -> int:
        row = self.conn.execute("SELECT word_id FROM vocab WHERE word=?", (word,)).fetchone()
        if row:
            return int(row["word_id"])
        cur = self.conn.execute("INSERT INTO vocab(word) VALUES(?)", (word,))
        return int(cur.lastrowid)

    def add_message(self, ts, session_id, speaker_id, addressee_ids, text, meta) -> int:
        cur = self.conn.execute(
            "INSERT INTO messages(ts, session_id, speaker_id, addressee_ids, text, meta) "
            "VALUES(?,?,?,?,?,?)",
            (ts, session_id, speaker_id, json.dumps(list(addressee_ids)), text, json.dumps(meta, ensure_ascii=False)),
        )
        return int(cur.lastrowid)

    def add_buffer(self, msg_id, idx, ts, session_id, speaker_id, text, words: list[str]) -> None:
        self.conn.execute(
            "INSERT INTO buffer(msg_id, idx, ts, session_id, speaker_id, text, words) "
            "VALUES(?,?,?,?,?,?,?)",
            (msg_id, idx, ts, session_id, speaker_id, text, json.dumps(words, ensure_ascii=False)),
        )

    def buffer_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM buffer").fetchone()["n"])

    def load_buffer(self) -> list[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM buffer ORDER BY buf_id"))

    def clear_buffer(self) -> None:
        self.conn.execute("DELETE FROM buffer")

    def recent_messages(self, limit: int) -> list[sqlite3.Row]:
        rows = list(
            self.conn.execute(
                "SELECT * FROM messages ORDER BY msg_id DESC LIMIT ?", (limit,)
            )
        )
        rows.reverse()
        return rows

    def add_sentence(self, msg_id, idx, ts, session_id, speaker_id, text, words: list[str]) -> int:
        cur = self.conn.execute(
            "INSERT INTO sentences(msg_id, idx, ts, session_id, speaker_id, text, words) "
            "VALUES(?,?,?,?,?,?,?)",
            (msg_id, idx, ts, session_id, speaker_id, text, json.dumps(words, ensure_ascii=False)),
        )
        sent_id = int(cur.lastrowid)
        for word in words:
            wid = self.intern(word)
            self.conn.execute(
                "INSERT OR IGNORE INTO word_sentence(word_id, sent_id, tier) VALUES(?,?, 'hot')",
                (wid, sent_id),
            )
            self.conn.execute("UPDATE vocab SET df = df + 1 WHERE word_id=?", (wid,))
        return sent_id

    def add_edge(self, w1: str, w2: str, delta: float, ts: float, sent_id: int, source_cap: int) -> None:
        a, b = sorted((w1, w2))
        id1, id2 = self.intern(a), self.intern(b)
        row = self.conn.execute(
            "SELECT weight, count FROM word_edges WHERE w1=? AND w2=?", (id1, id2)
        ).fetchone()
        if row is None:
            self.conn.execute(
                "INSERT INTO word_edges(w1, w2, weight, count, first_ts, last_ts) "
                "VALUES(?,?,?,?,?,?)",
                (id1, id2, delta, 1, ts, ts),
            )
        else:
            self.conn.execute(
                "UPDATE word_edges SET weight=weight+?, count=count+1, last_ts=? WHERE w1=? AND w2=?",
                (delta, ts, id1, id2),
            )
        existing = self.conn.execute(
            "SELECT COUNT(*) AS n FROM edge_sources WHERE w1=? AND w2=?", (id1, id2)
        ).fetchone()["n"]
        if int(existing) < source_cap:
            self.conn.execute(
                "INSERT OR IGNORE INTO edge_sources(w1, w2, sent_id) VALUES(?,?,?)",
                (id1, id2, sent_id),
            )

    def neighbors(self, word: str, now: float, graph_cfg: dict, limit: int) -> list[tuple[str, float, int]]:
        from ltm.components.strength import edge_effective_weight

        row = self.conn.execute("SELECT word_id FROM vocab WHERE word=?", (word,)).fetchone()
        if row is None:
            return []
        wid = int(row["word_id"])
        rows = self.conn.execute(
            """
            SELECT v.word AS other, e.weight, e.count, e.last_ts
            FROM word_edges e
            JOIN vocab v ON v.word_id = CASE WHEN e.w1=? THEN e.w2 ELSE e.w1 END
            WHERE e.w1=? OR e.w2=?
            """,
            (wid, wid, wid),
        ).fetchall()
        scored = []
        for item in rows:
            eff = edge_effective_weight(item["weight"], item["count"], item["last_ts"], now, graph_cfg)
            if eff >= graph_cfg["edge_min_weight"]:
                scored.append((item["other"], eff, int(item["count"])))
        scored.sort(key=lambda x: -x[1])
        return scored[:limit]

    def expand_words(self, token: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT word FROM vocab WHERE word=? OR instr(word, ?) > 0", (token, token)
        ).fetchall()
        return [r["word"] for r in rows if len(r["word"]) >= len(token)]

    def candidate_sentences(self, words: list[str], limit: int) -> list[dict[str, Any]]:
        if not words:
            return []
        ids = []
        for word in words:
            row = self.conn.execute("SELECT word_id FROM vocab WHERE word=?", (word,)).fetchone()
            if row:
                ids.append(int(row["word_id"]))
        if not ids:
            return []
        # 单个词走倒排：按 sent_id 从新到旧截断。句子按时间入库，sent_id 顺序和 ts 一致，
        # 截出来的集合与 ORDER BY ts DESC LIMIT 相同，但不用把该词全部热帖排一遍。
        if len(ids) == 1:
            rows = self.conn.execute(
                """
                SELECT s.* FROM word_sentence ws
                JOIN sentences s ON s.sent_id = ws.sent_id
                WHERE ws.word_id=? AND ws.tier='hot'
                ORDER BY ws.sent_id DESC
                LIMIT ?
                """,
                (ids[0], limit),
            ).fetchall()
            return [_sentence_dict(r) for r in rows]
        # 多个词：热句本身有上限，从最新的热句往前收，收满 limit 就停。
        # 这和「热句里含这些词、按时间取前 limit 条」是同一批。
        wanted = set(words)
        found: list[sqlite3.Row] = []
        for row in self.conn.execute(
            "SELECT * FROM sentences WHERE tier='hot' ORDER BY ts DESC"
        ):
            if wanted.intersection(json.loads(row["words"])):
                found.append(row)
                if len(found) >= limit:
                    break
        return [_sentence_dict(r) for r in found]

    def insert_fact(self, fact: dict) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO facts(text, owner_id, slot, words, importance, personal_importance,
              strength, created_ts, last_access_ts, mention_count, status, superseded_by, source_turns)
            VALUES(?,?,?,?,?,?,?,?,?,?, 'active', NULL, ?)
            """,
            (
                fact["text"], fact["owner_id"], fact["slot"], json.dumps(fact["words"], ensure_ascii=False),
                fact["importance"], fact["personal_importance"], fact["strength"], fact["ts"], fact["ts"],
                1, json.dumps(fact["turns"]),
            ),
        )
        return int(cur.lastrowid)

    def reinforce_fact(self, fact_id: int, strength: float, ts: float, turn: int | None) -> None:
        row = self.conn.execute("SELECT source_turns FROM facts WHERE fact_id=?", (fact_id,)).fetchone()
        turns = json.loads(row["source_turns"])
        if turn is not None:
            turns.append(turn)
        self.conn.execute(
            """
            UPDATE facts SET strength=?, last_access_ts=?, mention_count=mention_count+1,
              status='active', source_turns=? WHERE fact_id=?
            """,
            (strength, ts, json.dumps(turns), fact_id),
        )

    def supersede_fact(self, fact_id: int, new_id: int) -> None:
        self.conn.execute(
            "UPDATE facts SET status='superseded', superseded_by=? WHERE fact_id=?",
            (new_id, fact_id),
        )

    def facts_for_owner(self, owner_id: str, statuses: tuple[str, ...]) -> list[dict]:
        marks = ",".join("?" * len(statuses))
        rows = self.conn.execute(
            f"SELECT * FROM facts WHERE owner_id=? AND status IN ({marks})",
            (owner_id, *statuses),
        ).fetchall()
        return [_fact_dict(r) for r in rows]

    def all_facts(self) -> list[dict]:
        return [_fact_dict(r) for r in self.conn.execute("SELECT * FROM facts")]

    def set_fact_status(self, fact_id: int, status: str) -> None:
        self.conn.execute("UPDATE facts SET status=? WHERE fact_id=?", (status, fact_id))

    def set_fact_strength(self, fact_id: int, strength: float) -> None:
        self.conn.execute("UPDATE facts SET strength=? WHERE fact_id=?", (strength, fact_id))

    def bump_recall(self, sent_id: int) -> None:
        self.conn.execute(
            "UPDATE sentences SET recall_count = recall_count + 1 WHERE sent_id=?", (sent_id,)
        )

    def hot_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) AS n FROM sentences WHERE tier='hot'").fetchone()["n"])

    def cool_overflow(self, cap: int) -> int:
        hot = self.hot_count()
        if hot <= cap:
            return 0
        extra = hot - cap
        rows = self.conn.execute(
            "SELECT sent_id FROM sentences WHERE tier='hot' ORDER BY ts ASC LIMIT ?", (extra,)
        ).fetchall()
        for row in rows:
            self.conn.execute("UPDATE sentences SET tier='cold' WHERE sent_id=?", (row["sent_id"],))
            self.conn.execute("UPDATE word_sentence SET tier='cold' WHERE sent_id=?", (row["sent_id"],))
        return len(rows)

    def get_kv(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_kv(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def reset_memories(self) -> dict[str, int]:
        """清空全部记忆内容，保留成员表和 schema 版本。返回每张表清掉的条数。"""
        counts: dict[str, int] = {}
        with self.conn:
            for table in MEMORY_TABLES:
                row = self.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                counts[table] = int(row[0]) if row else 0
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.execute(
                "DELETE FROM sqlite_sequence WHERE name IN (%s)" % ",".join("?" * len(MEMORY_TABLES)),
                MEMORY_TABLES,
            )
        return counts

    def traits_for(self, owner_id: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM traits WHERE owner_id=? ORDER BY key", (owner_id,)
        )
        return [
            {
                "owner_id": row["owner_id"],
                "key": row["key"],
                "category": row["category"],
                "weight": float(row["weight"]),
                "baseline": float(row["baseline"]),
                "locked": bool(row["locked"]),
                "updated_ts": float(row["updated_ts"]),
            }
            for row in rows
        ]

    def upsert_trait(
        self, owner_id: str, key: str, category: str, weight: float, baseline: float, locked: bool, ts: float
    ) -> None:
        self.conn.execute(
            "INSERT INTO traits(owner_id, key, category, weight, baseline, locked, updated_ts) "
            "VALUES(?,?,?,?,?,?,?) ON CONFLICT(owner_id, key) DO UPDATE SET "
            "weight=excluded.weight, category=excluded.category, baseline=excluded.baseline, "
            "locked=excluded.locked, updated_ts=excluded.updated_ts",
            (owner_id, key, category, float(weight), float(baseline), 1 if locked else 0, ts),
        )

    def commit(self) -> None:
        self.conn.commit()


def _sentence_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "sent_id": int(row["sent_id"]),
        "msg_id": int(row["msg_id"]),
        "ts": float(row["ts"]),
        "session_id": row["session_id"],
        "speaker_id": row["speaker_id"],
        "text": row["text"],
        "words": json.loads(row["words"]),
        "tier": row["tier"],
    }


def _fact_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "fact_id": int(row["fact_id"]),
        "text": row["text"],
        "owner_id": row["owner_id"],
        "slot": row["slot"],
        "words": json.loads(row["words"]),
        "importance": int(row["importance"]),
        "personal_importance": float(row["personal_importance"]),
        "strength": float(row["strength"]),
        "created_ts": float(row["created_ts"]),
        "last_access_ts": float(row["last_access_ts"]),
        "mention_count": int(row["mention_count"]),
        "status": row["status"],
        "turns": json.loads(row["source_turns"]),
    }
