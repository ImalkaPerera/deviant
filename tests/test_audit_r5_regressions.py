"""Regression tests for the edge errors found by the audit of release 0.3.1."""

import json
import os
import subprocess
import textwrap
from pathlib import Path

from deviant_scan import git_forensics as gf
from deviant_scan import mine
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr


def item(item_id, flag, file, line):
    return {
        "detector": "d",
        "peer_group": "g",
        "item_id": item_id,
        "file": file,
        "line": line,
        "features": {"has_x": flag},
    }


def test_lead_examples_are_peers_of_the_items_still_listed():
    # a.py: one of six lacks x. b.py: one of four lacks x. The a.py file lead (5 of 6) is
    # stronger than the group lead (8 of 10), so it takes a.py:10, and the group lead lists only
    # b.py:10. Its examples must be b.py's neighbours, not a.py's.
    items = [item(f"a{i}", i != 0, "a.py", 10 * (i + 1)) for i in range(6)]
    items += [item(f"b{i}", i != 0, "b.py", 10 * (i + 1)) for i in range(4)]

    survey = mine.inventory(items)
    group = next(c for c in survey["candidates"] if c["scope"] == "group")

    assert [i["file"] for i in group["items"]] == ["b.py"]
    assert {e["file"] for e in group["examples"]} == {"b.py"}
    assert all("_members" not in c for c in survey["candidates"])


def workflow(tmp_path, text):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "w.yml").write_text(textwrap.dedent(text), encoding="utf-8")
    return gha.extract(str(tmp_path))


def test_numeric_job_keys_get_their_real_lines(tmp_path):
    items = workflow(
        tmp_path,
        """\
        on: push
        jobs:
          010:
            runs-on: x
          0x1f:
            runs-on: x
            steps:
              - run: echo b
        """,
    )

    jobs = [i["line"] for i in items if i["peer_group"] == "gha_jobs"]
    steps = [i["line"] for i in items if i["peer_group"] == "gha_run_steps"]
    assert jobs == [3, 5]
    assert steps == [8]


def test_a_repeated_steps_key_uses_the_one_the_loader_keeps(tmp_path):
    items = workflow(
        tmp_path,
        """\
        on: push
        jobs:
          a:
            runs-on: x
            steps:
              - run: one
              - run: two
            steps:
              - run: three
        """,
    )

    steps = [(i["item_id"], i["line"]) for i in items if i["peer_group"] == "gha_run_steps"]
    assert steps == [("a step 1", 9)]


def test_jobs_and_steps_from_a_merge_key_get_the_anchor_lines(tmp_path):
    items = workflow(
        tmp_path,
        """\
        on: push
        x-base: &base
          build:
            runs-on: x
        x-steps: &steps
          steps:
            - run: make
        jobs:
          <<: *base
          test:
            runs-on: x
            <<: *steps
        """,
    )

    jobs = {i["item_id"]: i["line"] for i in items if i["peer_group"] == "gha_jobs"}
    steps = [i["line"] for i in items if i["peer_group"] == "gha_run_steps"]
    assert jobs == {"build": 3, "test": 10}
    assert steps == [7]


def git(repo, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "a",
        "GIT_AUTHOR_EMAIL": "a@example.com",
        "GIT_COMMITTER_NAME": "a",
        "GIT_COMMITTER_EMAIL": "a@example.com",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def test_scanning_a_subfolder_of_a_repository_gives_no_outside_warning(tmp_path, capsys):
    repo = tmp_path / "repo"
    (repo / "packages" / "api").mkdir(parents=True)
    git(repo, "init", "-q")
    (repo / "packages" / "api" / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")

    gf.GitEvidence(repo / "packages" / "api")

    assert "outside the scanned folder" not in capsys.readouterr().err


def test_wording_that_means_the_opposite_is_not_a_public_claim():
    for text in (
        "No anonymous access.",
        "Rejects requests without auth.",
        "Not, e.g. a public endpoint",
    ):
        assert not pr._says_public(text), text
    for text in ("Requires no auth.", "Anyone can call this; it is intentionally public."):
        assert pr._says_public(text), text


def make_findings_repo(root: Path) -> Path:
    (root / "app").mkdir(parents=True)
    lines = ["from fastapi import APIRouter, Depends", "router = APIRouter()"]
    for i in range(30):
        dep = "" if i == 0 else ", dependencies=[Depends(get_current_user)]"
        lines += [f'@router.post("/r{i}"{dep})', f"def h{i}():", "    return {}"]
    (root / "app" / "r.py").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_a_failed_detector_fails_the_run_under_fail_on_findings(tmp_path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    (detectors / "broken.py").write_text(
        "def extract(repo_root):\n    raise RuntimeError('boom')\n", encoding="utf-8"
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    status = mine.run(str(repo), detectors, 20, 0.8, True, fail_on_findings=True)
    plain = mine.run(str(repo), detectors, 20, 0.8, True, fail_on_findings=False)

    assert status == 1
    assert plain == 0
    assert "detector(s) failed" in capsys.readouterr().err


class _ClosedPipe:
    def write(self, _text):
        raise BrokenPipeError

    def flush(self):
        raise BrokenPipeError


def test_a_closed_pipe_does_not_hide_a_finding(tmp_path, monkeypatch):
    repo = make_findings_repo(tmp_path / "repo")
    monkeypatch.setattr("sys.stdout", _ClosedPipe())

    status = mine.main(["--fail-on-findings", str(repo)])

    assert status == 1


def test_json_still_reports_rules_for_the_findings_repo(tmp_path, capsys):
    repo = make_findings_repo(tmp_path / "repo")

    mine.main(["--json", str(repo)])

    assert json.loads(capsys.readouterr().out)["rules"]


def test_colour_detection_survives_a_stream_without_isatty():
    assert mine.should_color("auto", None, environ={}) is False
    assert mine.should_color("auto", _ClosedPipe(), environ={}) is False
