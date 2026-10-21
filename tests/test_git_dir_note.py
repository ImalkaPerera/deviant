"""The scan says where its git history comes from when that is outside the scanned folder."""

import os
import subprocess
from pathlib import Path

from deviant_scan import git_forensics as gf


def git(repo, *args):
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "a",
        "GIT_AUTHOR_EMAIL": "a@example.com",
        "GIT_COMMITTER_NAME": "a",
        "GIT_COMMITTER_EMAIL": "a@example.com",
    }
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def make_repo(root: Path, name: str = "repo") -> Path:
    repo = root / name
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    return repo


def test_a_normal_repository_prints_no_note(tmp_path, capsys):
    repo = make_repo(tmp_path)

    gf.GitEvidence(repo)

    assert "outside the scanned folder" not in capsys.readouterr().err


def test_a_git_file_pointing_at_another_repository_is_called_out(tmp_path, capsys):
    other = make_repo(tmp_path, "other")
    scanned = tmp_path / "scanned"
    scanned.mkdir()
    (scanned / ".git").write_text(f"gitdir: {other / '.git'}\n", encoding="utf-8")
    (scanned / "app.py").write_text("x = 1\n", encoding="utf-8")

    evidence = gf.GitEvidence(scanned)

    err = capsys.readouterr().err
    assert evidence.available  # the history is still used, but the reader is told where from
    assert "outside the scanned folder" in err
    assert "other" in err


def test_a_worktree_is_noted_too(tmp_path, capsys):
    main = make_repo(tmp_path, "main")
    work = tmp_path / "work"
    git(main, "worktree", "add", "-q", str(work))

    gf.GitEvidence(work)

    assert "outside the scanned folder" in capsys.readouterr().err
