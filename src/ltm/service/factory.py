"""按配置把时钟、存储、记忆和回答器装到一起。"""

from __future__ import annotations

from pathlib import Path

from ltm.adapters.clock import SimClock
from ltm.adapters.embedding import HashEmbedder
from ltm.adapters.grounded import GroundedLLM
from ltm.adapters.sqlite_store import SqliteStore
from ltm.components.identity import IdentityBook
from ltm.components.text import Tokenizer
from ltm.core.config import load_settings
from ltm.service.agent import ChatAgent
from ltm.service.memory import MemoryService


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def build_agent(db_path: str = ":memory:", config_path: str | None = None, overrides: dict | None = None) -> ChatAgent:
    path = config_path
    if path is None:
        candidate = project_root() / "config" / "default.yaml"
        path = str(candidate) if candidate.exists() else None
    cfg = load_settings(path, overrides)
    store = SqliteStore(db_path)
    store.seed_members(cfg["members"])
    book = IdentityBook(cfg["members"])
    memory = MemoryService(store, SimClock(0), book, Tokenizer(), cfg)
    return ChatAgent(memory, GroundedLLM(), cfg)
