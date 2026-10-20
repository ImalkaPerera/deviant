"""Tests for the --inventory view: every group, and the items that lack what most peers have."""

import json
import os
import subprocess
import sys
from pathlib import Path

from deviant_scan import mine

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"


def item(item_id, has_auth, group="g", line=1, **extra):
    features = {"has_auth": has_auth, "is_mutating": True}
    features.update(extra)
    return {
        "detector": "d",
        "peer_group": group,
        "item_id": item_id,
        "file": "app.py",
        "line": line,
        "features": features,
    }


def group(auth_flags, name="g"):
    return [item(f"r{i}", flag, name, line=i + 1) for i, flag in enumerate(auth_flags)]


def test_small_group_is_a_lead_in_the_inventory_but_not_a_rule():
    items = group([True] * 9 + [False])  # 10 routes: far below the 20-item floor

    assert mine.mine(items) == []
    survey = mine.inventory(items)

    assert len(survey["candidates"]) == 1
    candidate = survey["candidates"][0]
    assert (candidate["feature"], candidate["n"], candidate["have"], candidate["lack"]) == (
        "has_auth",
        10,
        9,
        1,
    )
    assert [i["item_id"] for i in candidate["items"]] == ["r9"]


def test_items_in_a_group_that_mostly_lacks_the_feature_are_not_leads():
    survey = mine.inventory(group([True] * 2 + [False] * 8))

    assert survey["candidates"] == []


def test_group_below_the_minimum_size_lists_no_candidates():
    survey = mine.inventory(group([True, True, False]))

    assert survey["candidates"] == []
    assert survey["groups"][0]["n"] == 3


def test_a_feature_missing_from_many_items_is_not_a_single_outlier():
    # 9 of 20 lack it: more than the per-feature limit, so no item is singled out.
    survey = mine.inventory(group([True] * 11 + [False] * 9))

    assert survey["candidates"] == []


def test_condition_features_are_not_requirements():
    survey = mine.inventory(group([True] * 10))

    assert "is_mutating" not in survey["groups"][0]["features"]


def test_hidden_features_are_left_out():
    items = [item(f"r{i}", True, line=i + 1, has_response_model=i != 0) for i in range(10)]

    survey = mine.inventory(items, hide=frozenset({("d", "has_response_model")}))

    assert survey["candidates"] == []
    assert "has_response_model" not in survey["groups"][0]["features"]


def test_total_listed_items_are_capped_and_the_rest_counted():
    items = []
    for name in ("a", "b", "c"):
        items += group([True] * 7 + [False] * 3, name)  # 3 lacking items in each group

    survey = mine.inventory(items, limit=5)

    listed = sum(len(c["items"]) for c in survey["candidates"])
    assert listed == 5
    assert survey["truncated"] == 4


def test_candidates_are_ordered_by_how_large_the_majority_is():
    items = group([True] * 9 + [False], "strong") + group([True] * 7 + [False] * 3, "weak")

    survey = mine.inventory(items)

    assert [c["peer_group"] for c in survey["candidates"]] == ["strong", "weak"]


def run_cli(tmp_path, *args):
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    return subprocess.run(
        [sys.executable, "-m", "deviant_scan", *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def make_routes(tmp_path, count=10):
    (tmp_path / "app").mkdir()
    lines = ["from fastapi import APIRouter, Depends", "router = APIRouter()"]
    for i in range(count):
        dep = "" if i == count - 1 else "dependencies=[Depends(get_current_user)]"
        lines += [f'@router.post("/r{i}", {dep})', f"def r{i}():", "    return {}"]
    (tmp_path / "app" / "routes.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_cli_json_includes_the_inventory_only_when_asked(tmp_path):
    make_routes(tmp_path)

    plain = json.loads(run_cli(tmp_path, "--json", ".").stdout)
    asked = json.loads(run_cli(tmp_path, "--json", "--inventory", ".").stdout)

    assert "inventory" not in plain
    assert plain["rules"] == asked["rules"] == []
    lacking = [item for c in asked["inventory"]["candidates"] for item in c["items"]]
    assert [i["item_id"] for i in lacking] == ["POST /r9"]


def test_cli_text_output_prints_the_inventory(tmp_path):
    make_routes(tmp_path)

    result = run_cli(tmp_path, "--inventory", ".")

    assert result.returncode == 0
    assert "inventory: " in result.stdout
    assert "lacks: app/routes.py" in result.stdout


def test_candidates_carry_the_nearest_peers_that_have_the_feature():
    items = [item(f"r{i}", i != 5, line=10 * (i + 1)) for i in range(10)]  # r5 lacks auth

    candidate = mine.inventory(items)["candidates"][0]

    assert [e["item_id"] for e in candidate["examples"]] == ["r4", "r6"]
    assert all(e["file"] == "app.py" for e in candidate["examples"])


def file_item(item_id, flag, file, line, group="g"):
    return {
        "detector": "d",
        "peer_group": group,
        "item_id": item_id,
        "file": file,
        "line": line,
        "features": {"has_auth": flag},
    }


def file_group(flags, file, prefix):
    return [file_item(f"{prefix}{i}", flag, file, i + 1) for i, flag in enumerate(flags)]


def test_item_that_differs_from_its_neighbours_in_one_file_is_a_file_scope_lead():
    # Across the group only 7 of 15 have the feature, so no group-wide lead exists. In a.py,
    # four of five do.
    items = file_group([True] * 4 + [False], "a.py", "a") + file_group(
        [True] * 3 + [False] * 7, "b.py", "b"
    )

    survey = mine.inventory(items)

    assert [(c["scope"], c.get("file")) for c in survey["candidates"]] == [("file", "a.py")]
    candidate = survey["candidates"][0]
    assert (candidate["n"], candidate["have"], candidate["lack"]) == (5, 4, 1)
    assert [i["item_id"] for i in candidate["items"]] == ["a4"]


def test_file_scope_needs_at_least_three_neighbours():
    items = file_group([True, False], "a.py", "a") + file_group([False] * 10, "b.py", "b")

    assert mine.inventory(items)["candidates"] == []


def test_a_whole_group_lead_wins_a_tie_and_the_item_is_listed_once():
    # Nineteen of twenty have the feature across two files. The group lead is stronger than
    # the file lead for a.py, which would list the same item.
    items = file_group([True] * 9 + [False], "a.py", "a") + file_group([True] * 10, "b.py", "b")

    survey = mine.inventory(items)

    assert [c["scope"] for c in survey["candidates"]] == ["group"]
    assert [i["item_id"] for c in survey["candidates"] for i in c["items"]] == ["a9"]


def test_a_stronger_file_lead_takes_the_item_and_the_group_lead_keeps_the_rest():
    # Group-wide 12 of 20 have the feature (0.6). In a.py four of five do (0.8), so the item
    # lacking it in a.py is listed under the file lead, not twice.
    items = file_group([True] * 4 + [False], "a.py", "a") + file_group(
        [True] * 8 + [False] * 7, "b.py", "b"
    )

    survey = mine.inventory(items)

    listed = [(c["scope"], i["item_id"]) for c in survey["candidates"] for i in c["items"]]
    assert listed[0] == ("file", "a4")
    assert len([1 for _, item_id in listed if item_id == "a4"]) == 1
    assert all(scope == "group" for scope, item_id in listed[1:])
