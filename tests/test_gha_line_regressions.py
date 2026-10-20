"""Regression tests: GitHub Actions job names and line numbers match the workflow file."""

import textwrap

from deviant_scan.detectors import github_actions as gha


def extract_workflow(tmp_path, text: str):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "ci.yml").write_text(textwrap.dedent(text), encoding="utf-8")
    return gha.extract(str(tmp_path))


def job_items(items):
    return {i["item_id"]: i for i in items if i["peer_group"] == "gha_jobs"}


def test_jobs_named_like_yaml_booleans_keep_their_names_and_lines(tmp_path):
    items = extract_workflow(
        tmp_path,
        """\
        on: push
        jobs:
          on:
            runs-on: ubuntu-latest
            timeout-minutes: 5
          yes:
            runs-on: ubuntu-latest
          null:
            runs-on: ubuntu-latest
            timeout-minutes: 5
        """,
    )

    jobs = job_items(items)

    assert set(jobs) == {"on", "yes", "null"}
    assert jobs["on"]["line"] == 3
    assert jobs["yes"]["line"] == 6
    assert jobs["null"]["line"] == 8
    # The job named yes has no timeout, so it must be reported, not hidden.
    assert jobs["yes"]["features"]["has_timeout_minutes"] is False


def test_on_key_still_marks_a_reusable_only_workflow(tmp_path):
    items = extract_workflow(
        tmp_path,
        """\
        on:
          workflow_call:
        permissions:
          contents: read
        jobs:
          build:
            runs-on: ubuntu-latest
        """,
    )

    workflow = next(i for i in items if i["peer_group"] == "gha_workflows")

    assert workflow["features"]["has_permissions_block"] is True


def test_comment_repeating_a_step_does_not_move_its_line(tmp_path):
    items = extract_workflow(
        tmp_path,
        """\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: 5
            steps:
              # replaced actions/checkout@v4 with the pinned commit
              - uses: actions/checkout@v4
              - uses: actions/setup-python@v5
        """,
    )

    steps = {i["item_id"]: i for i in items if i["peer_group"] == "gha_third_party_steps"}

    assert steps["actions/checkout@v4"]["line"] == 8
    assert steps["actions/setup-python@v5"]["line"] == 9
