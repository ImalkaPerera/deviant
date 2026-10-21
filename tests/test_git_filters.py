"""A scanned repository must not be able to run a program through a git filter.

Each test names a filter in a different way and checks that git blame, run by the scanner on
a working-tree file that differs from HEAD, does not start it. A marker file is the probe.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
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


def make_repo(root: Path) -> Path:
    repo = root / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "one")
    return repo


def helper_script(root: Path, marker: Path) -> Path:
    helper = root / "probe.py"
    helper.write_text(
        "import sys\n"
        f"open({str(marker)!r}, 'w').write('ran')\n"
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    return helper


def probe(repo: Path, marker: Path) -> bool:
    """Blame a modified file through the scanner. True if the marker was written."""
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    marker.unlink(missing_ok=True)
    evidence = gf.GitEvidence(repo)
    assert evidence.available
    evidence.line_author("app.py", 1)
    return marker.exists()


@pytest.fixture
def setup(tmp_path):
    repo = make_repo(tmp_path)
    marker = tmp_path / "ran.txt"
    helper = helper_script(tmp_path, marker)
    command = f'"{sys.executable}" "{helper}"'
    return repo, marker, command, tmp_path


def test_filter_named_in_gitattributes_does_not_run(setup):
    repo, marker, command, _ = setup
    git(repo, "config", "filter.evil.clean", command)
    (repo / ".gitattributes").write_text("*.py filter=evil\n", encoding="utf-8")

    assert not probe(repo, marker)


def test_filter_named_in_info_attributes_does_not_run(setup):
    repo, marker, command, _ = setup
    git(repo, "config", "filter.evil.clean", command)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.py filter=evil\n", encoding="utf-8")

    assert not probe(repo, marker)


def test_filter_named_in_core_attributes_file_does_not_run(setup):
    repo, marker, command, root = setup
    git(repo, "config", "filter.evil.clean", command)
    attributes = root / "attrs"
    attributes.write_text("*.py filter=evil\n", encoding="utf-8")
    git(repo, "config", "core.attributesFile", str(attributes))

    assert not probe(repo, marker)


def test_process_filter_does_not_run(setup):
    repo, marker, command, _ = setup
    git(repo, "config", "filter.evil.process", command)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.py filter=evil\n", encoding="utf-8")

    assert not probe(repo, marker)


def test_git_file_redirect_to_a_config_with_a_filter_does_not_run(setup):
    repo, marker, command, root = setup
    git(repo, "config", "filter.evil.clean", command)
    (repo / ".git" / "info").mkdir(exist_ok=True)
    (repo / ".git" / "info" / "attributes").write_text("*.py filter=evil\n", encoding="utf-8")
    scanned = root / "scanned"
    scanned.mkdir()
    (scanned / ".git").write_text(f"gitdir: {repo / '.git'}\n", encoding="utf-8")

    assert not probe_redirected(scanned, marker)


def probe_redirected(scanned: Path, marker: Path) -> bool:
    (scanned / "app.py").write_text("x = 2\n", encoding="utf-8")
    marker.unlink(missing_ok=True)
    evidence = gf.GitEvidence(scanned)
    if evidence.available:
        evidence.line_author("app.py", 1)
    return marker.exists()


def test_the_probe_does_fire_without_the_protection(setup):
    # Control: plain git blame, outside the scanner, does run the filter. Without this the
    # tests above could pass only because the probe never works.
    repo, marker, command, _ = setup
    git(repo, "config", "filter.evil.clean", command)
    (repo / ".gitattributes").write_text("*.py filter=evil\n", encoding="utf-8")
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")
    marker.unlink(missing_ok=True)

    subprocess.run(
        ["git", "-C", str(repo), "blame", "--line-porcelain", "--", "app.py"],
        capture_output=True,
        check=False,
    )

    assert marker.exists()


def test_overrides_cover_exactly_the_filters_the_repo_defines(setup):
    repo, _marker, command, _ = setup
    other = repo.parent / "other"
    other.mkdir()
    git(other, "init", "-q")
    git(repo, "config", "filter.evil.clean", command)
    gf._filter_overrides_cache.pop(str(repo), None)
    gf._filter_overrides_cache.pop(str(other), None)

    options = gf._filter_overrides(str(repo))
    unrelated = gf._filter_overrides(str(other))

    # Every setting of the repo's filter is switched off, and a repo without it is untouched.
    for setting in ("clean", "smudge", "process"):
        assert f"filter.evil.{setting}=" in options
    assert "filter.evil.required=false" in options
    assert not any("evil" in option for option in unrelated)
