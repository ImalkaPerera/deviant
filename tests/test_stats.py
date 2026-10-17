import pytest
from deviant_scan.stats import passes_filter, wilson_lower_bound


# Values from plan section 6.4, checked against the formula.
@pytest.mark.parametrize(
    ("s", "n", "expected"),
    [
        (47, 48, 0.891),
        (19, 20, 0.764),
        (4, 5, 0.376),
    ],
)
def test_wilson_lower_bound_matches_plan_examples(s, n, expected):
    assert wilson_lower_bound(s, n) == pytest.approx(expected, abs=0.0005)


# Smallest group that passes, per number of exceptions (plan section 6.4).
@pytest.mark.parametrize(
    ("v", "min_confidence", "smallest_n"),
    [
        (1, 0.80, 25),
        (2, 0.80, 33),
        (3, 0.80, 40),
        (1, 0.75, 19),
        (2, 0.75, 25),
        (3, 0.75, 31),
    ],
)
def test_smallest_passing_group_size(v, min_confidence, smallest_n):
    # Use min_items=1 so only the confidence rule decides here.
    assert passes_filter(smallest_n - v, smallest_n, min_items=1, min_confidence=min_confidence)
    assert not passes_filter(
        smallest_n - 1 - v, smallest_n - 1, min_items=1, min_confidence=min_confidence
    )


def test_47_of_48_is_reported():
    assert passes_filter(47, 48)


def test_19_of_20_is_not_reported_at_default_confidence():
    assert not passes_filter(19, 20)


def test_group_below_min_items_is_not_reported():
    # 19 of 19 has no exceptions and is under the default minimum of 20.
    assert not passes_filter(19, 19)


def test_group_with_no_exceptions_is_not_reported():
    assert not passes_filter(20, 20)


def test_more_than_three_exceptions_is_not_reported():
    assert not passes_filter(96, 100)


def test_rejects_invalid_counts():
    with pytest.raises(ValueError):
        wilson_lower_bound(5, 4)
    with pytest.raises(ValueError):
        wilson_lower_bound(1, 0)
