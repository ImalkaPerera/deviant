"""Regression tests for the security and crash fixes found by the edge-case audit.

Each test reproduces one problem from the audit and checks that it no longer happens.
"""

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from deviant_scan import git_forensics as gf
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr

ANN = ("Ann Example", "ann@example.com")


def git(repo: Path, *args: str) -> None:
    env = os.environ.copy()
    env.update(
        GIT_AUTHOR_NAME=ANN[0],
        GIT_AUTHOR_EMAIL=ANN[1],
        GIT_COMMITTER_NAME=ANN[0],
        GIT_COMMITTER_EMAIL=ANN[1],
    )
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")


# --- 1. A repository's clean filter must not run during git blame ----------------------


def test_blame_does_not_run_the_clean_filter_of_the_scanned_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    write(root, "a.py", "x = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "add a")

    # A filter from the scanned repo: a helper script that records that it ran.
    marker = tmp_path / "filter-ran.txt"
    helper = tmp_path / "clean.py"
    helper.write_text(
        "import sys\n"
        f"open(r'{marker}', 'w').write('ran')\n"
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    git(root, "config", "filter.evil.clean", f'"{sys.executable}" "{helper}"')
    write(root, ".gitattributes", "*.py filter=evil\n")
    git(root, "add", ".gitattributes")
    git(root, "commit", "-q", "-m", "add attributes")
    # Modify the file so it differs from HEAD. This is the case where git blame would
    # otherwise run the filter on the working-tree file.
    write(root, "a.py", "x = 2\n")
    # Git's own add and commit above may already run the filter. Clear the marker so that
    # only the scanner's calls are checked.
    marker.unlink(missing_ok=True)

    evidence = gf.GitEvidence(root)
    assert evidence.available
    info = evidence.line_author("a.py", 1)

    assert not marker.exists(), "git blame ran the repository's clean filter"
    # The uncommitted change is still reported, so the fix does not drop evidence.
    assert info is not None and info["commit"] is None


# --- 2. A small YAML file must not make the scan hang -------------------------------


def test_yaml_alias_expansion_is_bounded(tmp_path):
    # Each level holds two references to the level before it, so a plain str() of the
    # last level would print 2**30 items. The scan must finish quickly anyway.
    levels = 30
    lines = [
        "on: push",
        "jobs:",
        "  build:",
        "    runs-on: &a0 [ubuntu-latest]",
    ]
    for i in range(1, levels + 1):
        lines.append(f"    pad{i}: &a{i} [*a{i - 1}, *a{i - 1}]")
    lines.append(f"    runs-on: *a{levels}")
    lines.append("    steps:")
    lines.append("      - uses: actions/checkout@v4")
    write(tmp_path, ".github/workflows/ci.yml", "\n".join(lines) + "\n")

    started = time.monotonic()
    items = gha.extract(str(tmp_path))
    elapsed = time.monotonic() - started

    assert elapsed < 5, f"scan took {elapsed:.1f}s on an aliased file"
    job = next(i for i in items if i["peer_group"] == "gha_jobs")
    assert len(job["context"]["runs_on"]) <= 200


# --- 3. An impossible date in a workflow must not crash the scan -------------------


def test_invalid_date_skips_only_that_file(tmp_path):
    write(
        tmp_path,
        ".github/workflows/bad.yml",
        """\
        on: push
        env:
          RELEASE: 2021-02-30
        jobs:
          build:
            runs-on: ubuntu-latest
        """,
    )
    write(
        tmp_path,
        ".github/workflows/good.yml",
        """\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: 10
        """,
    )

    items = gha.extract(str(tmp_path))  # must not raise ValueError

    files = {item["file"] for item in items}
    assert ".github/workflows/good.yml" in files
    assert ".github/workflows/bad.yml" not in files


# --- 4. A Windows junction must not lead the scan outside the repository -----------


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_junction_to_outside_folder_is_not_scanned(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    write(
        outside,
        "secret.py",
        """\
        from fastapi import APIRouter
        router = APIRouter()

        @router.post("/leak")
        def leak():
            return {}
        """,
    )
    root.mkdir()
    link = root / "linked"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction on this system")

    items = pr.extract(str(root))
    files = {item["file"] for item in items}

    assert not any(f.startswith("linked") for f in files), files
    assert not any("secret" in f for f in files), files
