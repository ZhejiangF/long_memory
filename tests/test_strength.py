import math

from ltm.components.strength import edge_effective_weight, initial_strength, retention, should_sleep

MEM = {
    "s_init_base": 1.0,
    "tau_days": 2.0,
    "s_max": 10.0,
    "longterm_strength": 3.0,
    "pinned_importance": 8,
    "dormant_retention": 0.05,
    "reinforce_mention": 1.0,
    "reinforce_recall": 0.3,
}
GRAPH = {"tau_edge_days": 7.0, "edge_min_weight": 0.3}


def test_retention_matches_design_numbers():
    strength = initial_strength(5, MEM)
    assert strength == 1.5
    keep = retention(strength, 0, 86400, MEM)
    assert keep == math.exp(-1 / 3)
    assert should_sleep(strength, 5, retention(strength, 0, 10 * 86400, MEM), MEM)


def test_strong_memory_does_not_sleep():
    keep = retention(4, 0, 10 * 86400, MEM)
    assert abs(keep - math.exp(-1.25)) < 1e-9
    assert not should_sleep(4, 5, keep, MEM)


def test_important_fact_never_sleeps():
    assert not should_sleep(1.0, 9, 0.01, MEM)


def test_edge_weight_decay():
    once_10 = edge_effective_weight(1, 1, 0, 10 * 86400, GRAPH)
    once_20 = edge_effective_weight(1, 1, 0, 20 * 86400, GRAPH)
    often_20 = edge_effective_weight(1, 4, 0, 20 * 86400, GRAPH)
    assert abs(once_10 - 0.43) < 0.02
    assert abs(once_20 - 0.18) < 0.02
    assert abs(often_20 - 0.33) < 0.02
    assert once_10 >= GRAPH["edge_min_weight"]
    assert once_20 < GRAPH["edge_min_weight"]
