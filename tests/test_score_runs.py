"""Tests for the benchmark scorer: which answers count as finding a planted bug."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench"))

import score_runs  # noqa: E402


def bug(line, file="app/routers/items.py", function=None):
    return {"file": file, "line": line, "function": function, "kind": "k", "category": "c"}


def found_lines(text, bugs):
    return [b["line"] for b in score_runs.match(text, bugs)[0]]


def test_plain_colon_reference():
    assert found_lines("BUG app/routers/items.py:40 has no auth", [bug(40)]) == [40]


def test_shorthand_refers_back_to_the_last_file():
    text = "BUG items.py:40 missing auth\nBUG also :82 has the same problem"
    assert found_lines(text, [bug(40), bug(82)]) == [40, 82]


def test_ranges_lists_and_line_words():
    assert found_lines("BUG items.py:30-45", [bug(38)]) == [38]
    assert found_lines("BUG items.py, lines 34 and 50", [bug(34), bug(50)]) == [34, 50]
    assert found_lines("BUG line 61 of items.py", [bug(61)]) == [61]
    assert found_lines("BUG `items.py` (line 12)", [bug(12)]) == [12]


def test_table_rows():
    text = "| File | Line | Verdict |\n|---|---|---|\n| items.py | 40 | BUG |"
    assert found_lines(text, [bug(40)]) == [40]


def test_one_reference_credits_one_bug():
    text = "BUG items.py:40"
    assert found_lines(text, [bug(38), bug(42)]) == [38]


def test_the_same_place_twice_is_still_one_reference():
    text = "Summary: BUG items.py:40\n\nDetail: BUG items.py:40 lacks auth"
    assert found_lines(text, [bug(38), bug(42)]) == [38]


def test_intentional_rows_are_not_finds():
    assert found_lines("INTENTIONAL items.py:40 is a health check", [bug(40)]) == []
    text = "INTENTIONAL items.py:40 health check\nBUG items.py:40 actually missing auth"
    assert found_lines(text, [bug(40)]) == [40]


def test_paths_with_folders_must_match_the_bug_path():
    assert found_lines("BUG other/items.py:40", [bug(40)]) == []
    assert found_lines("BUG routers/items.py:40", [bug(40)]) == [40]
    assert found_lines("BUG App\\Routers\\Items.py:40", [bug(40)]) == [40]


def test_function_names_count_only_as_whole_words_with_the_file_named():
    target = [bug(90, function="delete_item")]
    assert found_lines("BUG delete_item in items.py skips auth", target) == [90]
    assert found_lines("BUG delete_item skips auth", target) == []
    assert found_lines("BUG items.py: delete_items_bulk", target) == []
    assert found_lines("items.py\nINTENTIONAL delete_item is admin only", target) == []


def test_function_name_is_not_matched_inside_a_file_name():
    target = [bug(90, file="app/auth.py", function="users")]
    assert found_lines("BUG app/auth.py and users.py look fine", target) == []


def test_unmatched_references_are_listed():
    found, unmatched = score_runs.match("BUG items.py:40\nBUG items.py:200", [bug(40)])
    assert [b["line"] for b in found] == [40]
    assert unmatched == [("items.py", 200)]
