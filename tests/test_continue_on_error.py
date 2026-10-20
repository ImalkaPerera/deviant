"""Tests for the run-step feature fails_on_error: a shell step that lets its failure pass."""

import textwrap

from deviant_scan import mine
from deviant_scan.detectors import github_actions as gha


def workflow(tmp_path, steps_yaml: str, name="ci.yml"):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    body = textwrap.dedent(
        """\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: 5
            steps:
        """
    ) + textwrap.indent(textwrap.dedent(steps_yaml), "      ")
    (folder / name).write_text(body, encoding="utf-8")


def run_items(tmp_path):
    return [i for i in gha.extract(str(tmp_path)) if i["peer_group"] == "gha_run_steps"]


def test_a_run_step_with_continue_on_error_lacks_fails_on_error(tmp_path):
    workflow(
        tmp_path,
        """\
        - run: echo one
        - run: echo two
          continue-on-error: true
        - run: echo three
        """,
    )

    items = run_items(tmp_path)

    assert [i["features"]["fails_on_error"] for i in items] == [True, False, True]
    assert [i["line"] for i in items] == [7, 8, 10]


def test_continue_on_error_false_still_fails_on_error(tmp_path):
    workflow(
        tmp_path,
        """\
        - run: echo one
          continue-on-error: false
        """,
    )

    assert run_items(tmp_path)[0]["features"]["fails_on_error"] is True


def test_expression_continue_on_error_is_not_read_as_ignoring_failure(tmp_path):
    workflow(
        tmp_path,
        """\
        - run: echo one
          continue-on-error: ${{ inputs.soft }}
        """,
    )

    assert run_items(tmp_path)[0]["features"]["fails_on_error"] is True


def test_uses_steps_are_unchanged_and_not_run_items(tmp_path):
    workflow(
        tmp_path,
        """\
        - uses: actions/checkout@v4
        - run: echo one
          continue-on-error: true
        """,
    )

    items = gha.extract(str(tmp_path))
    uses = [i for i in items if i["peer_group"] == "gha_third_party_steps"]

    assert [i["item_id"] for i in uses] == ["actions/checkout@v4"]
    assert "fails_on_error" not in uses[0]["features"]


def test_composite_action_run_steps_are_checked(tmp_path):
    folder = tmp_path / ".github" / "actions" / "setup"
    folder.mkdir(parents=True)
    (folder / "action.yml").write_text(
        textwrap.dedent(
            """\
            runs:
              using: composite
              steps:
                - run: echo one
                  shell: bash
                  continue-on-error: true
                - run: echo two
                  shell: bash
            """
        ),
        encoding="utf-8",
    )

    items = [i for i in gha.extract(str(tmp_path)) if i["peer_group"] == "gha_run_steps"]

    assert [i["features"]["fails_on_error"] for i in items] == [False, True]


def test_most_run_steps_fail_on_error_so_the_one_that_does_not_is_a_lead(tmp_path):
    steps = "".join(f"- run: echo {i}\n" for i in range(9))
    steps += "- run: echo soft\n  continue-on-error: true\n"
    workflow(tmp_path, steps)

    survey = mine.inventory(gha.extract(str(tmp_path)))
    leads = [
        (c["peer_group"], c["feature"], i["item_id"])
        for c in survey["candidates"]
        for i in c["items"]
    ]

    assert [lead[:2] for lead in leads] == [("gha_run_steps", "fails_on_error")]
    assert leads[0][2] == "build step 10"


def test_run_step_lines_come_from_the_yaml_positions(tmp_path):
    # A folded block, an escaped string and a step whose text sits inside an earlier block
    # all defeat a search of the source text. The parser knows where each step starts.
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "w.yml").write_text(
        textwrap.dedent(
            """\
            on: push
            jobs:
              a:
                runs-on: ubuntu-latest
                timeout-minutes: 5
                steps:
                  - run: |
                      make build
                      make test
                  - run: make
                  - run: >
                      echo a
                      echo b
                    continue-on-error: true
                  - run: "echo \\"z\\""
            """
        ),
        encoding="utf-8",
    )

    items = run_items(tmp_path)

    assert [(i["item_id"], i["line"]) for i in items] == [
        ("a step 1", 7),
        ("a step 2", 10),
        ("a step 3", 11),
        ("a step 4", 15),
    ]
    assert [i["features"]["fails_on_error"] for i in items] == [True, True, False, True]


def test_run_steps_with_the_same_text_keep_separate_items(tmp_path):
    workflow(
        tmp_path,
        """\
        - run: make
        - run: make
          continue-on-error: true
        - run: make
        """,
    )

    items = mine._unique_items(run_items(tmp_path))

    assert len(items) == 3
    assert len({i["item_id"] for i in items}) == 3
