"""A group that is clearly one way keeps its exceptions as leads, however many there are.

Found on a real project: 174 of 199 third-party actions were pinned, and the 25 that were not
were hidden by a fixed limit of 8 exceptions.
"""

from deviant_scan import mine


def group(flags, name="g"):
    return [
        {
            "detector": "d",
            "peer_group": name,
            "item_id": f"r{i}",
            "file": f"f{i // 50}.py",  # spread over files, so file scope cannot explain a lead
            "line": i + 1,
            "features": {"has_x": flag},
        }
        for i, flag in enumerate(flags)
    ]


def leads(items):
    survey = mine.inventory(items, limit=1000)
    return [(c["scope"], len(c["items"])) for c in survey["candidates"] if c["scope"] == "group"]


def test_many_exceptions_are_leads_when_the_group_is_clearly_one_way():
    # 87% follow the rule, 25 do not: more than the fixed limit of 8.
    items = group([True] * 174 + [False] * 25)

    assert leads(items) == [("group", 25)]


def test_many_exceptions_are_not_leads_when_the_group_is_mixed():
    # 75% follow the rule and 25 do not: above the limit, and not clear enough to lift it.
    items = group([True] * 75 + [False] * 25)

    assert leads(items) == []


def test_few_exceptions_are_leads_even_when_the_share_is_below_the_clear_line():
    # 70% follow the rule, and only 6 do not.
    items = group([True] * 14 + [False] * 6)

    assert leads(items) == [("group", 6)]


def test_the_clear_line_is_inclusive():
    # Exactly 85%: 85 of 100, 15 exceptions.
    items = group([True] * 85 + [False] * 15)

    assert leads(items) == [("group", 15)]


def test_just_under_the_clear_line_with_many_exceptions_is_not_a_lead():
    # 84 of 100, 16 exceptions: over the limit of 8 and just under 85%.
    items = group([True] * 84 + [False] * 16)

    assert leads(items) == []


def test_the_output_limit_still_bounds_a_large_clear_group():
    items = group([True] * 970 + [False] * 30)

    survey = mine.inventory(items, limit=10)

    assert sum(len(c["items"]) for c in survey["candidates"]) == 10
    assert survey["truncated"] == 20
