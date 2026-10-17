import os
import re
import subprocess
from pathlib import Path

import pytest
from deviant_scan import git_forensics as gf

ANN = ("Ann Example", "ann@example.com")
BOB = ("Bob Example", "bob@example.com")


def git(repo: Path, *args: str, author=ANN) -> None:
    env = os.environ.copy()
    env.update(
        GIT_AUTHOR_NAME=author[0],
        GIT_AUTHOR_EMAIL=author[1],
        GIT_COMMITTER_NAME=author[0],
        GIT_COMMITTER_EMAIL=author[1],
    )
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repo where Ann writes the protected routes and Bob adds an unprotected one."""
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    git(root, "init", "-q")
    (root / "app" / "routes.py").write_text(
        "from x import auth\n@router.post('/items')\n@router.post('/orders')\n",
        encoding="utf-8",
    )
    (root / "app" / "other.py").write_text("x = 1\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "add routes", author=ANN)

    (root / "app" / "routes.py").write_text(
        "from x import auth\n"
        "@router.post('/items')\n"
        "@router.post('/orders')\n"
        "# public webhook, called by the payment provider\n"
        "@router.post('/export')\n",
        encoding="utf-8",
    )
    (root / "app" / "other.py").write_text("x = 2\n", encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "add public webhook export", author=BOB)
    return root


def test_blame_names_the_commit_that_last_changed_the_line(repo):
    evidence = gf.GitEvidence(repo).exception_evidence("app/routes.py", 5, [])
    assert evidence["author"] == "bob@example.com"
    assert evidence["subject"] == "add public webhook export"
    assert re.fullmatch(r"[0-9a-f]{7}", evidence["commit"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", evidence["date"])
    assert evidence["uncommitted"] is False


def test_files_in_commit_counts_every_file_the_commit_touched(repo):
    evidence = gf.GitEvidence(repo).exception_evidence("app/routes.py", 5, [])
    assert evidence["files_in_commit"] == 2


def test_intent_words_come_from_the_commit_message_and_nearby_comments(repo):
    evidence = gf.GitEvidence(repo).exception_evidence("app/routes.py", 5, [])
    assert evidence["intent_words"] == ["public", "webhook"]


def test_followed_rule_elsewhere_counts_compliant_lines_by_the_same_author(repo):
    compliant = [("app/routes.py", 2), ("app/routes.py", 3)]  # both written by Ann
    gf_ann = gf.GitEvidence(repo)
    assert (
        gf_ann.exception_evidence("app/routes.py", 2, compliant)["author_followed_rule_elsewhere"]
        == 2
    )
    assert (
        gf_ann.exception_evidence("app/routes.py", 5, compliant)["author_followed_rule_elsewhere"]
        == 0
    )


def test_uncommitted_line_has_no_commit_but_still_reports(repo):
    (repo / "app" / "routes.py").write_text(
        "from x import auth\n@router.post('/items')\n@router.post('/orders')\n"
        "# public webhook, called by the payment provider\n"
        "@router.post('/export')\n@router.post('/draft')\n",
        encoding="utf-8",
    )
    evidence = gf.GitEvidence(repo).exception_evidence("app/routes.py", 6, [])
    assert evidence["uncommitted"] is True
    assert evidence["commit"] is None
    assert evidence["files_in_commit"] is None


def test_folder_that_is_not_a_repository_has_no_evidence(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "routes.py").write_text("x = 1\n", encoding="utf-8")
    evidence = gf.GitEvidence(plain)
    assert evidence.available is False
    assert evidence.exception_evidence("routes.py", 1, []) is None


def test_each_file_is_blamed_once_per_scan(repo, monkeypatch):
    calls = []
    real = gf._git

    def counting(repo_path, args):
        if args[:1] == ["blame"]:
            calls.append(args)
        return real(repo_path, args)

    monkeypatch.setattr(gf, "_git", counting)
    evidence = gf.GitEvidence(repo)
    for line in (2, 3, 5):
        evidence.exception_evidence("app/routes.py", line, [])
    assert len(calls) == 1


def test_mine_attaches_git_evidence_to_each_exception(repo):
    from deviant_scan.mine import mine

    items = [
        {
            "detector": "d",
            "peer_group": "g",
            "item_id": f"r{line}",
            "file": "app/routes.py",
            "line": line,
            "features": {"has_auth": line != 5},
        }
        for line in (2, 3, 5)
    ]
    rules = mine(items, min_items=1, min_confidence=0.0, repo_root=repo)
    (rule,) = rules
    assert "_compliant" not in rule
    (exception,) = rule["exceptions"]
    assert exception["git"]["author"] == "bob@example.com"
    assert exception["git"]["intent_words"] == ["public", "webhook"]


def test_text_output_shows_git_evidence(repo):
    from deviant_scan.mine import _format_text, mine

    items = [
        {
            "detector": "d",
            "peer_group": "g",
            "item_id": f"r{line}",
            "file": "app/routes.py",
            "line": line,
            "features": {"has_auth": line != 5},
        }
        for line in (2, 3, 5)
    ]
    text = _format_text(mine(items, min_items=1, min_confidence=0.0, repo_root=repo))
    assert "last changed:" in text
    assert "bob@example.com" in text
    assert "intent words: public, webhook" in text
    assert "same author wrote" in text
    assert "followed the rule" not in text  # that wording read as if the author had a clean record


def test_shallow_clone_marks_boundary_commits_as_truncated(repo, tmp_path: Path):
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo.as_posix()}", str(clone)],
        check=True,
        capture_output=True,
    )
    evidence = gf.GitEvidence(clone).exception_evidence("app/routes.py", 5, [])
    assert evidence["history_truncated"] is True


def test_full_history_is_not_marked_truncated(repo):
    evidence = gf.GitEvidence(repo).exception_evidence("app/routes.py", 5, [])
    assert evidence["history_truncated"] is False


def test_evenly_spaced_sample_spreads_across_the_list():
    items = list(range(1000))
    sample = gf._evenly_spaced(items, 50)
    assert len(sample) == 50
    assert sample[0] == 0 and sample[-1] >= 980
    assert gf._evenly_spaced(items[:10], 50) == items[:10]


def test_a_git_directory_is_not_a_work_tree(repo):
    assert gf.GitEvidence(repo / ".git").available is False
    assert gf.GitEvidence(repo).available is True


def test_git_calls_disable_fsmonitor_so_a_hostile_repo_config_cannot_run_programs(
    repo, monkeypatch
):
    seen = []
    real_run = subprocess.run

    def spy(command, **kwargs):
        seen.append(command)
        return real_run(command, **kwargs)

    monkeypatch.setattr(gf.subprocess, "run", spy)
    gf.GitEvidence(repo).exception_evidence("app/routes.py", 5, [])
    assert seen
    assert all(command[1:3] == ["-c", "core.fsmonitor=false"] for command in seen)


def test_no_git_calls_are_made_when_there_are_no_rules(repo, monkeypatch):
    from deviant_scan.mine import mine

    calls = []
    monkeypatch.setattr(gf, "_git", lambda *a, **k: calls.append(a) or None)
    assert mine([], repo_root=repo) == []
    assert calls == []
