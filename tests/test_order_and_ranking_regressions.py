"""Regression tests: mine() gives the same answer whatever order detectors return items in,
and ranks rules by their exact bound."""

import random

from deviant_scan import mine as mine_module
from deviant_scan.mine import mine
from deviant_scan.stats import wilson_lower_bound


def item(item_id, has_auth, line=1, file="app.py"):
    return {
        "detector": "d",
        "peer_group": "g",
        "item_id": item_id,
        "file": file,
        "line": line,
        "features": {"has_auth": has_auth},
    }


def test_duplicate_with_conflicting_features_gives_the_same_result_in_any_order():
    # Twenty compliant items, and one exception reported twice with different features.
    base = [item(f"ok{i}", True, line=i + 1) for i in range(20)]
    conflicting = [item("bad", False, line=50), item("bad", True, line=50)]
    forward = base + conflicting
    backward = list(reversed(forward))

    shuffled = list(forward)
    random.Random(7).shuffle(shuffled)

    expected = mine(forward)
    assert mine(backward) == expected
    assert mine(shuffled) == expected


def test_rules_are_ranked_by_the_exact_bound_not_the_rounded_one():
    # Two rules whose bounds differ by less than 0.0005 round to the same 3 decimals.
    # The one with the higher exact bound must come first, whatever its size.
    small = (31, 1)  # 31 items, 1 exception
    large = (50, 3)  # 50 items, 3 exceptions
    rounded_equal = round(wilson_lower_bound(*_s_n(small)), 3) == round(
        wilson_lower_bound(*_s_n(large)), 3
    )
    assert rounded_equal, "the test needs two rules that round to the same value"

    exact_small = wilson_lower_bound(*_s_n(small))
    exact_large = wilson_lower_bound(*_s_n(large))
    stronger, weaker = (small, large) if exact_small > exact_large else (large, small)

    assert mine_module._sort_key(_rule(*stronger)) < mine_module._sort_key(_rule(*weaker))


def _s_n(pair):
    """(s, n) for a (n, v) pair: s good items out of n, v of them exceptions."""
    n, v = pair
    return n - v, n


def _rule(n, v):
    s, nn = _s_n((n, v))
    return {"s": s, "n": nn, "v": v, "kind": "plain", "rule_id": f"x{n}_{v}"}
