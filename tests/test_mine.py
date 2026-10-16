import json
from pathlib import Path

import pytest
from mine import group_items, load_detectors, mine, run


def make_items(
    total, auth_missing_ids=(), detector="python_routes", peer="fastapi_mutating_routes"
):
    """Build `total` items that are all mutating; those in auth_missing_ids lack auth."""
    items = []
    for i in range(total):
        item_id = f"POST /route/{i}"
        items.append(
            {
                "detector": detector,
                "peer_group": peer,
                "item_id": item_id,
                "file": f"app/routes/r{i}.py",
                "line": 10 + i,
                "features": {
                    "is_mutating": True,
                    "has_auth": item_id not in auth_missing_ids,
                },
            }
        )
    return items


def rule_ids(rules):
    return [r["rule_id"] for r in rules]


def test_47_of_48_reports_the_one_exception():
    items = make_items(48, auth_missing_ids={"POST /route/0"})
    rules = mine(items)
    # The plain "has_auth" rule and the if-then rule cover the same exception,
    # so only one of them is kept.
    auth_rules = [r for r in rules if "has_auth" in r["rule_id"]]
    assert len(auth_rules) == 1
    rule = auth_rules[0]
    assert (rule["n"], rule["s"], rule["v"]) == (48, 47, 1)
    assert [e["item_id"] for e in rule["exceptions"]] == ["POST /route/0"]


def test_19_of_20_reports_nothing():
    items = make_items(20, auth_missing_ids={"POST /route/0"})
    assert mine(items) == []


def test_small_group_reports_nothing_even_with_one_exception():
    items = make_items(10, auth_missing_ids={"POST /route/0"})
    assert mine(items) == []


def test_min_items_flag_lowers_the_size_floor():
    items = make_items(10, auth_missing_ids={"POST /route/0"})
    rules = mine(items, min_items=5, min_confidence=0.0)
    assert rules  # reported once the floor is lowered


def test_feature_true_for_everyone_is_not_reported():
    # is_mutating is 100% true, so it has no exceptions to show.
    items = make_items(30)
    assert all("is_mutating" not in r["rule_id"] for r in mine(items))
    assert mine(items) == []


def test_feature_true_for_under_half_is_not_reported():
    items = []
    for i in range(30):
        items.append(
            {
                "detector": "d",
                "peer_group": "g",
                "item_id": f"x{i}",
                "file": "f.py",
                "line": i + 1,
                "features": {"rare": i < 10, "other": True},
            }
        )
    assert all(r["rule_id"] != "d.g.rare" for r in mine(items))


def test_ranking_puts_higher_confidence_first():
    items = make_items(48, auth_missing_ids={"POST /route/0"})
    rules = mine(items)
    keys = [(r["wlb95"], r["n"], -r["v"]) for r in rules]
    assert keys == sorted(keys, reverse=True)


def test_output_is_deterministic():
    items = make_items(48, auth_missing_ids={"POST /route/0"})
    assert mine(items) == mine(list(reversed(items)))


def test_group_items_splits_by_detector_and_peer_group():
    items = make_items(3) + make_items(3, peer="other")
    groups = group_items(items)
    assert set(groups) == {
        ("python_routes", "fastapi_mutating_routes"),
        ("python_routes", "other"),
    }


def test_invalid_item_is_rejected():
    with pytest.raises(ValueError):
        mine([{"detector": "d", "peer_group": "g"}])


def test_load_detectors_skips_template_and_private_files(tmp_path: Path):
    (tmp_path / "_template.py").write_text("def extract(repo_root):\n    return []\n")
    (tmp_path / "fake.py").write_text(
        "def extract(repo_root):\n    return [{'detector': 'fake', 'peer_group': 'g',"
        " 'item_id': 'a', 'file': 'a.py', 'line': 1, 'features': {}}]\n"
    )
    modules = load_detectors(tmp_path)
    assert [m.__name__ for m in modules] == ["deviant_detector_fake"]


def test_run_writes_json_and_text(tmp_path: Path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    items = make_items(48, auth_missing_ids={"POST /route/0"})
    (detectors / "fake.py").write_text(
        "import json\nITEMS = json.loads(" + repr(json.dumps(items)) + ")\n"
        "def extract(repo_root):\n    return ITEMS\n"
    )
    code = run(tmp_path, detectors, min_items=20, min_confidence=0.80, as_json=True)
    out = json.loads(capsys.readouterr().out)
    assert code == 0
    assert any("has_auth" in r["rule_id"] for r in out["rules"])


def test_run_with_no_detectors_says_no_rules(tmp_path: Path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    assert run(tmp_path, detectors, min_items=20, min_confidence=0.80, as_json=False) == 0
    assert "no rules found" in capsys.readouterr().out
