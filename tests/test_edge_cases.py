"""Edge cases for the mining step, the CLI and the statistics."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from deviant_scan import mine as mine_module
from deviant_scan.mine import collect_items, main, mine, parse_rule_id, run, validate_items
from deviant_scan.stats import passes_filter, wilson_lower_bound

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts" / "mine.py"


def item(**overrides):
    base = {
        "detector": "d",
        "peer_group": "g",
        "item_id": "x",
        "file": "a.py",
        "line": 1,
        "features": {"has_auth": True},
    }
    base.update(overrides)
    return base


# --- malformed detector output ------------------------------------------------------------


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (item(line="5"), "line"),
        (item(line=0), "line"),
        (item(line=True), "line"),
        (item(file=3), "file"),
        (item(item_id=""), "item_id"),
        (item(features=[]), "features"),
        (item(features={"has_auth": 1}), "bool"),
        (item(features={"has.auth": True}), "feature name"),
        (item(detector="my.detector"), "detector"),
        (item(peer_group=None), "peer_group"),
        ("not a dict", "dict"),
    ],
)
def test_malformed_items_are_rejected_with_a_clear_message(bad, message):
    with pytest.raises(ValueError, match=message):
        validate_items([bad])


def test_a_detector_with_malformed_output_is_skipped_and_the_rest_are_kept(tmp_path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    (detectors / "bad.py").write_text(
        "def extract(root):\n    return [{'detector': 'bad', 'line': 'x'}]\n"
    )
    (detectors / "good.py").write_text(
        "def extract(root):\n"
        "    return [{'detector': 'good', 'peer_group': 'g', 'item_id': 'i', "
        "'file': 'f.py', 'line': 1, 'features': {'a': True}}]\n"
    )
    items = collect_items(tmp_path, detectors)
    assert [i["detector"] for i in items] == ["good"]
    assert "detector bad returned invalid items" in capsys.readouterr().err


def test_a_detector_that_returns_a_non_list_is_skipped(tmp_path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    (detectors / "odd.py").write_text("def extract(root):\n    return None\n")
    assert collect_items(tmp_path, detectors) == []
    assert "odd" in capsys.readouterr().err


def test_exact_duplicate_items_are_counted_once():
    items = [item(item_id=f"r{i}", line=i + 1) for i in range(30)]
    assert len(mine(items + items, min_items=1, min_confidence=0.0)) == len(
        mine(items, min_items=1, min_confidence=0.0)
    )


def test_duplicates_do_not_inflate_the_group_size():
    one_exception = [item(item_id=f"r{i}", line=i + 1) for i in range(24)]
    one_exception.append(item(item_id="bad", line=99, features={"has_auth": False}))
    doubled = one_exception + one_exception  # 25 distinct items, 50 rows
    assert mine(doubled, min_items=1)[0]["n"] == 25


# --- rule ids -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule_id", "expected"),
    [
        (
            "python_routes.fastapi_routes:app/routes.has_auth",
            ("python_routes", "fastapi_routes:app/routes", None, "has_auth"),
        ),
        (
            "python_routes.fastapi_routes:app/v1.2/api.routes.has_auth",
            ("python_routes", "fastapi_routes:app/v1.2/api.routes", None, "has_auth"),
        ),
        (
            "d.g.is_mutating_implies_has_auth",
            ("d", "g", "is_mutating", "has_auth"),
        ),
    ],
)
def test_rule_ids_parse_back_even_when_folder_names_contain_dots(rule_id, expected):
    parsed = parse_rule_id(rule_id)
    assert (
        parsed["detector"],
        parsed["peer_group"],
        parsed["condition"],
        parsed["feature"],
    ) == expected


def test_every_rule_id_round_trips_through_parse_rule_id():
    items = [
        item(
            item_id=f"r{i}",
            line=i + 1,
            peer_group="grp:src/v1.2/x",
            features={"has_auth": i != 3},
        )
        for i in range(40)
    ]
    rules = mine(items)
    assert rules
    for rule in rules:
        parsed = parse_rule_id(rule["rule_id"])
        assert parsed["feature"] == rule["feature"]
        assert parsed["condition"] == rule["condition"]
        assert parsed["peer_group"] == "grp:src/v1.2/x"


def test_parse_rule_id_rejects_garbage():
    with pytest.raises(ValueError):
        parse_rule_id("nodots")


# --- command line -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        ["--min-items", "0"],
        ["--min-items", "-3"],
        ["--min-items", "abc"],
        ["--min-confidence", "1.5"],
        ["--min-confidence", "-0.1"],
        ["--min-confidence", "high"],
    ],
)
def test_bad_numbers_are_rejected_with_exit_code_2(args, tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(tmp_path), *args],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr


def test_a_file_is_rejected_as_the_repo(tmp_path):
    a_file = tmp_path / "x.py"
    a_file.write_text("x = 1\n")
    assert run(a_file, tmp_path, 20, 0.8, False) == 2


def test_a_missing_directory_is_rejected(tmp_path):
    assert run(tmp_path / "nope", tmp_path, 20, 0.8, False) == 2


def test_an_empty_directory_reports_no_rules(tmp_path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    repo = tmp_path / "empty"
    repo.mkdir()
    assert run(repo, detectors, 20, 0.8, False) == 0
    assert "no rules found" in capsys.readouterr().out


def test_paths_with_spaces_and_non_ascii_names_work(tmp_path):
    repo = tmp_path / "my project é 日本"
    routes = repo / "app" / "routes é"
    routes.mkdir(parents=True)
    for i in range(30):
        auth = "def h(u=Depends(get_current_user)):" if i != 4 else "def h():"
        (routes / f"r{i}.py").write_text(
            "from fastapi import APIRouter, Depends\nrouter = APIRouter()\n\n\n"
            f"@router.post('/r{i}')\n{auth}\n    return {{}}\n",
            encoding="utf-8",
        )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "--json"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    rules = json.loads(result.stdout.decode("utf-8"))["rules"]
    assert rules
    assert rules[0]["exceptions"][0]["file"] == "app/routes é/r4.py"


def test_a_closed_pipe_ends_quietly(monkeypatch):
    def broken_pipe(*args, **kwargs):
        raise BrokenPipeError

    monkeypatch.setattr(mine_module, "run", broken_pipe)
    assert main(["--repo", "."]) == 0


# --- statistics ---------------------------------------------------------------------------


def test_wilson_bound_is_a_probability_below_the_observed_share():
    for n in range(1, 120):
        previous = -1.0
        for s in range(n + 1):
            bound = wilson_lower_bound(s, n)
            assert 0.0 <= bound <= 1.0
            assert bound <= s / n + 1e-12
            assert bound >= previous - 1e-12  # more successes never lower the bound
            previous = bound


def test_a_bigger_group_with_the_same_share_gives_a_higher_bound():
    assert wilson_lower_bound(96, 100) > wilson_lower_bound(24, 25)


def test_the_confidence_threshold_is_inclusive():
    bound = wilson_lower_bound(24, 25)
    assert passes_filter(24, 25, min_items=1, min_confidence=bound)
    assert not passes_filter(24, 25, min_items=1, min_confidence=bound + 1e-9)


def test_the_size_floor_is_inclusive():
    assert passes_filter(39, 40, min_items=40, min_confidence=0.5)
    assert not passes_filter(39, 40, min_items=41, min_confidence=0.5)


@pytest.mark.parametrize(("s", "n"), [(0, 1), (1, 1), (0, 100), (100, 100), (1, 2)])
def test_extreme_counts_do_not_raise(s, n):
    assert 0.0 <= wilson_lower_bound(s, n) <= 1.0


# --- the installed command ---------------------------------------------------------------


def run_script(*args):
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)


def test_a_plain_path_works_like_repo(tmp_path):
    result = run_script(str(tmp_path))
    assert result.returncode == 0
    assert "no rules found" in result.stdout


def test_the_path_and_repo_cannot_disagree(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    result = run_script(str(tmp_path), "--repo", str(other))
    assert result.returncode == 2
    assert "once" in result.stderr


def test_the_same_folder_given_twice_is_fine(tmp_path):
    assert run_script(str(tmp_path), "--repo", str(tmp_path)).returncode == 0


def test_no_path_scans_the_current_folder(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, cwd=tmp_path
    )
    assert result.returncode == 0
    assert "no rules found" in result.stdout


def test_version_flag_prints_the_name_and_a_version():
    result = run_script("--version")
    assert result.returncode == 0
    assert re.fullmatch(r"deviant-scan \S+", result.stdout.strip())


def test_python_m_deviant_scan_runs_the_same_command(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "deviant_scan", str(tmp_path)],
        capture_output=True,
        text=True,
        cwd=SCRIPT.parent,  # the package sits next to the launcher
    )
    assert result.returncode == 0
    assert "no rules found" in result.stdout
