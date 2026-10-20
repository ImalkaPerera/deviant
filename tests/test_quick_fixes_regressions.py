"""Regression tests for the quick correctness fixes: negated public claims, zero timeouts,
uppercase SHAs and junctions that list one file twice."""

import subprocess
import sys
import textwrap

import pytest
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr

HEADER = "from fastapi import APIRouter\n\nrouter = APIRouter()\n\n"


def route_has_auth(tmp_path, route_source: str) -> bool:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "routes.py").write_text(
        HEADER + textwrap.dedent(route_source), encoding="utf-8"
    )
    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "app/routes.py"]
    assert len(items) == 1, items
    return items[0]["features"]["has_auth"]


def test_negated_public_docstring_is_not_treated_as_public(tmp_path):
    assert not route_has_auth(
        tmp_path,
        '''\
        @router.post("/items")
        def create():
            """Not intentionally public; requires login."""
            return {}
        ''',
    )


def test_positive_public_docstring_is_still_treated_as_public(tmp_path):
    assert route_has_auth(
        tmp_path,
        '''\
        @router.post("/items")
        def create():
            """Anyone can call this; it is intentionally public."""
            return {}
        ''',
    )


def test_negated_public_comment_above_route_is_not_treated_as_public(tmp_path):
    assert not route_has_auth(
        tmp_path,
        """\
        # Not open to everyone.
        @router.post("/items")
        def create():
            return {}
        """,
    )


def github_items(tmp_path, workflow: str):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "ci.yml").write_text(textwrap.dedent(workflow), encoding="utf-8")
    return gha.extract(str(tmp_path))


def job_timeout(tmp_path, value: str) -> bool:
    items = github_items(
        tmp_path,
        f"""\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: {value}
        """,
    )
    job = next(i for i in items if i["peer_group"] == "gha_jobs")
    return job["features"]["has_timeout_minutes"]


def test_zero_timeout_is_not_a_real_limit(tmp_path):
    assert not job_timeout(tmp_path, "0")


def test_real_timeout_still_counts(tmp_path):
    assert job_timeout(tmp_path, "10")


def test_expression_timeout_still_counts(tmp_path):
    assert job_timeout(tmp_path, "${{ inputs.minutes }}")


def uses_pinned(tmp_path, ref: str) -> bool:
    items = github_items(
        tmp_path,
        f"""\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: 5
            steps:
              - uses: actions/checkout@{ref}
        """,
    )
    step = next(i for i in items if i["peer_group"] == "gha_third_party_steps")
    return step["features"]["pinned_to_sha"]


def test_full_sha_is_pinned(tmp_path):
    assert uses_pinned(tmp_path, "a" * 40)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_junction_inside_repo_lists_each_action_once(tmp_path):
    root = tmp_path / "repo"
    real = root / ".github" / "actions" / "real"
    real.mkdir(parents=True)
    (real / "action.yml").write_text(
        "runs:\n  using: composite\n  steps:\n    - uses: actions/setup-node@v4\n",
        encoding="utf-8",
    )
    alias = root / ".github" / "actions" / "alias"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(alias), str(real)],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction on this system")

    items = gha.extract(str(root))
    steps = [i for i in items if i["peer_group"] == "gha_third_party_steps"]

    assert len(steps) == 1, [i["file"] for i in steps]
