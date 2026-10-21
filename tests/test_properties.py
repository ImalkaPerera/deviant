"""Property-based tests: invariants that must hold for any input, not just chosen examples.

Hypothesis generates many inputs and shrinks a failing one to a minimal case.
"""

import random
import tempfile
from pathlib import Path

from deviant_scan import mine
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr
from deviant_scan.stats import MAX_EXCEPTIONS, passes_filter, wilson_lower_bound
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

FAST = settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
SLOW = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


# --- the statistics ------------------------------------------------------------------------


@FAST
@given(st.integers(min_value=1, max_value=100_000), st.data())
def test_wilson_bound_is_between_zero_and_the_observed_rate(n, data):
    s = data.draw(st.integers(min_value=0, max_value=n))

    bound = wilson_lower_bound(s, n)

    assert 0.0 <= bound <= 1.0
    assert bound <= s / n + 1e-12


@FAST
@given(st.integers(min_value=2, max_value=5_000), st.data())
def test_wilson_bound_never_falls_when_more_items_follow_the_rule(n, data):
    s = data.draw(st.integers(min_value=0, max_value=n - 1))

    assert wilson_lower_bound(s, n) <= wilson_lower_bound(s + 1, n) + 1e-12


@FAST
@given(
    st.integers(min_value=1, max_value=500),
    st.data(),
    st.integers(min_value=1, max_value=60),
    st.floats(min_value=0.0, max_value=1.0),
)
def test_a_reported_rule_respects_every_limit(n, data, min_items, confidence):
    s = data.draw(st.integers(min_value=0, max_value=n))

    if passes_filter(s, n, min_items, confidence):
        assert n >= min_items
        assert 1 <= n - s <= MAX_EXCEPTIONS
        assert wilson_lower_bound(s, n) >= confidence


# --- mining and the inventory --------------------------------------------------------------

item_strategy = st.builds(
    lambda group, name, file, line, a, b, c: {
        "detector": "d",
        "peer_group": group,
        "item_id": name,
        "file": file,
        "line": line,
        "features": {"has_a": a, "has_b": b, "is_c": c},
    },
    st.sampled_from(["g1", "g2", "g3"]),
    st.sampled_from(["r1", "r2", "r3", "r4", "r5", "r6"]),
    st.sampled_from(["a.py", "b.py", "c.py"]),
    st.integers(min_value=1, max_value=8),
    st.booleans(),
    st.booleans(),
    st.booleans(),
)
items_strategy = st.lists(item_strategy, min_size=0, max_size=80)


@FAST
@given(items_strategy, st.integers(min_value=0, max_value=10_000))
def test_results_do_not_depend_on_the_order_items_arrive_in(items, seed):
    shuffled = list(items)
    random.Random(seed).shuffle(shuffled)

    assert mine.mine(items, min_items=2, min_confidence=0.0) == mine.mine(
        shuffled, min_items=2, min_confidence=0.0
    )
    assert mine.inventory(items) == mine.inventory(shuffled)


@FAST
@given(items_strategy)
def test_removing_duplicates_is_idempotent_and_keeps_every_distinct_item(items):
    once = mine._unique_items(items)

    assert mine._unique_items(once) == once
    keys = {(i["detector"], i["peer_group"], i["item_id"], i["file"], i["line"]) for i in items}
    assert len(once) == len(keys)


@FAST
@given(items_strategy, st.integers(min_value=1, max_value=30))
def test_every_inventory_lead_names_an_item_that_really_lacks_the_feature(items, limit):
    survey = mine.inventory(items, limit=limit)
    by_key = {}
    for entry in mine._unique_items(items):
        by_key[(entry["peer_group"], entry["item_id"], entry["file"], entry["line"])] = entry

    listed = 0
    seen = set()
    for candidate in survey["candidates"]:
        assert candidate["share"] >= mine.INVENTORY_MIN_SHARE
        assert candidate["lack"] >= 1
        assert (
            candidate["lack"] <= mine.INVENTORY_MAX_PER_FEATURE
            or candidate["share"] >= mine.INVENTORY_CLEAR_SHARE
        )
        assert candidate["have"] + candidate["lack"] == candidate["n"]
        for lead in candidate["items"]:
            entry = by_key[(candidate["peer_group"], lead["item_id"], lead["file"], lead["line"])]
            assert entry["features"][candidate["feature"]] is False
            key = (
                candidate["peer_group"],
                candidate["feature"],
                lead["item_id"],
                lead["file"],
                lead["line"],
            )
            assert key not in seen, "an item was listed twice for one feature"
            seen.add(key)
            listed += 1
    assert listed <= limit
    assert survey["group_count"] >= len(survey["groups"])


# --- text safety ---------------------------------------------------------------------------


@FAST
@given(st.text())
def test_printable_leaves_no_control_or_bidirectional_characters(text):
    shown = mine._printable(text)

    for char in shown:
        code = ord(char)
        assert not (code < 0x20 or 0x7F <= code <= 0x9F)
        assert not (
            0x2028 <= code <= 0x2029 or 0x202A <= code <= 0x202E or 0x2066 <= code <= 0x2069
        )
    assert mine._printable(shown) == shown  # escaping twice changes nothing


@FAST
@given(st.text(min_size=0, max_size=2000))
def test_bounded_never_exceeds_the_limit_and_keeps_short_strings(text):
    cut = mine._bounded(text)

    assert len(cut) <= mine.MAX_OUTPUT_STRING
    if len(text) <= mine.MAX_OUTPUT_STRING:
        assert cut == text


# --- hostile files never crash a detector --------------------------------------------------


@SLOW
@given(st.binary(max_size=4000))
def test_python_routes_survives_arbitrary_bytes(data):
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "a.py").write_bytes(data)

        pr.extract(tmp)  # must not raise


@SLOW
@given(st.text(max_size=3000))
def test_github_actions_survives_arbitrary_text(text):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / ".github" / "workflows"
        folder.mkdir(parents=True)
        (folder / "w.yml").write_text(text, encoding="utf-8", errors="replace")

        gha.extract(tmp)  # must not raise


@SLOW
@given(
    st.lists(
        st.sampled_from(
            [
                "on: push",
                "jobs:",
                "  a:",
                "    runs-on: x",
                "    timeout-minutes: 5",
                "    steps:",
                "      - run: echo hi",
                "      - uses: actions/checkout@v4",
                "        continue-on-error: true",
                "  b: {runs-on: y}",
                "    x: &r [*r]",
                "# comment",
                "",
            ]
        ),
        max_size=25,
    )
)
def test_github_actions_survives_shuffled_workflow_lines(lines):
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp) / ".github" / "workflows"
        folder.mkdir(parents=True)
        (folder / "w.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")

        items = gha.extract(tmp)  # must not raise

        for entry in items:
            assert entry["line"] >= 1
