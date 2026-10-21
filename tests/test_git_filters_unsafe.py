"""A filter whose name git -c cannot express makes the scan skip blame, so it cannot run.

Two such names were found by an audit: one containing "=" (git -c splits at the first one) and
one in bytes that are not valid UTF-8 (the decoded override names a different filter).
"""

import os
import subprocess
import sys
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


def make_repo(root: Path):
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    marker = root / "ran.txt"
    helper = root / "probe.py"
    helper.write_text(
        "import sys\n"
        f"open({str(marker)!r}, 'w').write('ran')\n"
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    command = f'"{sys.executable}" "{helper}"'
    return repo, marker, command


def add_filter(repo: Path, name: bytes, command: str) -> None:
    config = repo / ".git" / "config"
    config.write_bytes(
        config.read_bytes()
        + b'[filter "'
        + name
        + b'"]\n\tclean = '
        + command.replace("\\", "/").encode()
        + b"\n"
    )
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_bytes(b"*.py filter=" + name + b"\n")


def blame_modified_file(repo: Path, marker: Path):
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    marker.unlink(missing_ok=True)
    gf._filter_overrides_cache.pop(str(repo.resolve()), None)
    evidence = gf.GitEvidence(repo)
    info = evidence.line_author("app.py", 1)
    return marker.exists(), info


def test_a_filter_name_with_an_equals_sign_does_not_run(tmp_path, capsys):
    repo, marker, command = make_repo(tmp_path)
    add_filter(repo, b"a=b", command)

    ran, info = blame_modified_file(repo, marker)

    assert not ran
    assert info is None  # blame was skipped, not run unprotected
    assert "cannot be switched off safely" in capsys.readouterr().err


def test_a_filter_name_that_is_not_utf8_does_not_run(tmp_path, capsys):
    repo, marker, command = make_repo(tmp_path)
    add_filter(repo, b"\xe9vil", command)

    ran, _info = blame_modified_file(repo, marker)

    assert not ran
    assert "cannot be switched off safely" in capsys.readouterr().err


def test_an_ordinary_filter_is_switched_off_and_blame_still_works(tmp_path, capsys):
    repo, marker, command = make_repo(tmp_path)
    add_filter(repo, b"evil", command)

    ran, info = blame_modified_file(repo, marker)

    assert not ran
    assert info is not None and info["commit"] is None  # the uncommitted line is still seen
    assert "cannot be switched off safely" not in capsys.readouterr().err
