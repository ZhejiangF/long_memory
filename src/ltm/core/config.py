"""默认配置写在代码里，yaml 只做覆盖。不带配置文件也能当插件用。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

try:  # 默认配置写在代码里；没装 PyYAML 也能当插件用。
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

DEFAULTS: dict[str, Any] = {
    "schema_version": 3,
    "namespace": "default",
    "plugins": {
        "clock": "sim",
        "llm": "grounded",
        "embedder": "hash",
        "tokenizer": "jieba",
        "extractor": "rule",
        "importance_gate": "rule",
    },
    "identity": {"self_name": "助手", "session_id": "生活群"},
    "buffer": {
        "nap_sentences": 600,
        "max_sentences": 2000,
        "segment_max_sentences": 40,
        "buffer_top_k": 40,
        "buffer_token_budget": 1200,
    },
    "sleep": {"night_hour": 3},
    "memory": {
        "recent_messages": 8,
        "tau_days": 2.0,
        "s_init_base": 1.0,
        "reinforce_mention": 1.0,
        "reinforce_recall": 0.3,
        "s_max": 10.0,
        "longterm_strength": 3.0,
        "pinned_importance": 8,
        "dormant_retention": 0.05,
    },
    "graph": {
        "pair_window": 8,
        "speaker_edge_gain": 0.5,
        "self_edge_factor": 0.5,
        "tau_edge_days": 7.0,
        "edge_min_weight": 0.3,
        "max_neighbors": 10,
        "hops": 2,
        "hop_decay": 0.5,
        "max_active_words": 50,
    },
    "retrieval": {
        "top_sentences": 100,
        "pair_bonus": 0.5,
        "asker_bonus": 1.3,
        "self_sentence_factor": 0.5,
        "token_budget": 5000,
        "fact_top_k": 8,
    },
    "scale": {
        "posting_cap": 300,
        "cold_posting_cap": 300,
        "hot_sentence_cap": 20000,
        "candidate_cap": 3000,
        "edge_sources_cap": 20,
        "active_facts_per_owner": 300,
        "prompt_hard_cap_tokens": 7000,
    },
    "personality": {
        "gate_threshold": 3.0,
        "always_keep_importance": 8,
        "affinity_low": 0.6,
        "affinity_high": 1.4,
        "learning_rate": 0.03,
        "max_daily_delta": 0.02,
        "weight_bounds": [0.05, 0.95],
    },
    "profile": {"max_items_per_person": 8, "token_budget": 400},
    "members": [
        {"id": "zhanglei", "name": "张磊", "aliases": ["磊哥"]},
        {"id": "linxia", "name": "林夏", "aliases": ["夏夏"]},
        {"id": "laozhou", "name": "老周", "aliases": ["周哥"]},
        {"id": "zhangyue", "name": "张悦", "aliases": ["悦悦"]},
        {"id": "self", "name": "助手", "aliases": []},
    ],
}


def _merge(base: dict, extra: dict) -> dict:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings(path: str | Path | None = None, overrides: dict | None = None) -> dict[str, Any]:
    data = deepcopy(DEFAULTS)
    if path:
        if yaml is None:
            raise RuntimeError("读取 YAML 配置需要 PyYAML：pip install PyYAML")
        loaded = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        data = _merge(data, loaded)
    if overrides:
        data = _merge(data, overrides)
    return data
