from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class Message:
    ts: float
    session_id: str
    speaker_id: str
    text: str
    addressee_ids: tuple[str, ...] = ()
    reply_to: str | None = None
    msg_id: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class Query:
    text: str
    asker_id: str
    session_id: str
    ts: float
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class RetrievedItem:
    source: str
    ref_id: str
    text: str
    score: float
    rendered: str
    tokens: int
    speaker_id: str = ""
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    items: tuple[RetrievedItem, ...] = ()
    debug: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class SleepReport:
    kind: str
    started_ts: float
    duration_ms: float
    stage_stats: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class TurnResult:
    reply: str | None
    prompt_tokens: int
    completion_tokens: int
    retrieval_ms: float
    prompt_build_ms: float
    llm_ms: float
    sleep_ms: float
    total_ms: float
    debug: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True, slots=True)
class LLMResponse:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
