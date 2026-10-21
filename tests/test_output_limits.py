"""Output and git work have limits, so one hostile value or repository cannot flood a reader."""

import json
import os
import subprocess
import sys
from pathlib import Path

from deviant_scan import git_forensics as gf
from deviant_scan import mine

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"


def run_cli(cwd, *args):
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "deviant_scan", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
    )


def make_routes(tmp_path, path):
    (tmp_path / "app").mkdir()
    lines = ["from fastapi import APIRouter, Depends", "router = APIRouter()"]
    for i in range(10):
        route = path if i == 9 else f"/ok{i}"
        dep = "" if i == 9 else ", dependencies=[Depends(get_current_user)]"
        lines += [f"@router.post({route!r}{dep})", f"def h{i}():", "    return {}"]
    (tmp_path / "app" / "r.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_very_long_string_is_cut_in_json_output(tmp_path):
    make_routes(tmp_path, "/" + "x" * 300_000)

    out = run_cli(tmp_path, "--json", "--inventory", ".").stdout

    assert len(out) < 20_000
    data = json.loads(out)
    ids = [i["item_id"] for c in data["inventory"]["candidates"] for i in c["items"]]
    assert len(ids) == 1
    assert len(ids[0]) == mine.MAX_OUTPUT_STRING and ids[0].endswith("...")


def test_a_very_long_string_is_cut_in_text_output(tmp_path):
    make_routes(tmp_path, "/" + "y" * 300_000)

    out = run_cli(tmp_path, "--inventory", "--color", "never", ".").stdout

    assert len(out) < 20_000


def test_strings_within_the_limit_are_untouched():
    value = {"a": ["x" * mine.MAX_OUTPUT_STRING, 5], "b": {"c": "short"}}

    assert mine._bounded(value) == value


def test_bounded_marks_only_what_it_cuts():
    cut = mine._bounded("z" * (mine.MAX_OUTPUT_STRING + 1))

    assert len(cut) == mine.MAX_OUTPUT_STRING and cut.endswith("...")


def make_repo(root):
    repo = root / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "a",
        "GIT_AUTHOR_EMAIL": "a@example.com",
        "GIT_COMMITTER_NAME": "a",
        "GIT_COMMITTER_EMAIL": "a@example.com",
    }
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "."], ["commit", "-q", "-m", "one"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)
    return repo


def test_git_evidence_stops_when_its_time_budget_is_used(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path)
    monkeypatch.setattr(gf, "GIT_BUDGET_SECONDS", -1)  # already over budget
    evidence = gf.GitEvidence(repo)

    assert evidence.available
    assert evidence.line_author("app.py", 1) is None
    assert evidence.line_author("app.py", 1) is None
    err = capsys.readouterr().err
    assert err.count("git evidence stopped") == 1  # said once, not per file


def test_git_evidence_works_within_its_budget(tmp_path):
    repo = make_repo(tmp_path)

    info = gf.GitEvidence(repo).line_author("app.py", 1)

    assert info is not None and info["commit"] is not None
