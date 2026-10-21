"""Hostile files must not make the scanner slow, and must not drop other findings.

Each timing test uses an input that took tens of seconds before the fix. The limits are
generous, so a slow machine does not fail them; the old code is far over every limit.
"""

import time
from pathlib import Path

from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr


def timed(fn):
    start = time.monotonic()
    result = fn()
    return result, time.monotonic() - start


def workflow(tmp_path: Path, text: str, name="w.yml") -> None:
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_bare_except_retry_is_not_quadratic_on_a_long_line(tmp_path):
    # A file that fails to parse is retried with the bare-except fix. A long comma list on one
    # line made that retry take 18 seconds at 50 KB.
    (tmp_path / "a.py").write_text("except " + "a," * 25000 + "\n", encoding="utf-8")

    _, seconds = timed(lambda: pr.extract(str(tmp_path)))

    assert seconds < 8, seconds


def test_bare_except_retry_is_not_quadratic_on_many_blank_lines(tmp_path):
    (tmp_path / "a.py").write_text("\n" * 100_000 + "x = (\n", encoding="utf-8")

    _, seconds = timed(lambda: pr.extract(str(tmp_path)))

    assert seconds < 8, seconds


def test_public_claim_check_is_not_quadratic_in_the_docstring_size():
    text = "not no auth " * 40000

    _, seconds = timed(lambda: pr._says_public(text))

    assert seconds < 8, seconds


def test_negation_still_voids_a_nearby_public_claim():
    assert not pr._says_public("Not intentionally public; requires login.")
    assert pr._says_public("Anyone can call this; it is intentionally public.")


def test_thousands_of_one_line_jobs_are_read_in_linear_time(tmp_path):
    jobs = "".join(f"  j{i}: {{runs-on: x}}\n" for i in range(3000))
    workflow(tmp_path, "on: push\njobs:\n" + jobs)

    items, seconds = timed(lambda: gha.extract(str(tmp_path)))

    assert seconds < 8, seconds
    assert len([i for i in items if i["peer_group"] == "gha_jobs"]) == 3000


def test_job_lines_are_exact_whatever_the_layout(tmp_path):
    workflow(
        tmp_path,
        "# header\n"
        "on: push\n"
        "jobs:\n"
        "  # first\n"
        "  build:\n"
        "    runs-on: x\n"
        "    timeout-minutes: 5\n"
        '  "quoted job":\n'
        "    runs-on: x\n"
        "  test: {runs-on: x}\n",
    )

    jobs = {
        i["item_id"]: i["line"] for i in gha.extract(str(tmp_path)) if i["peer_group"] == "gha_jobs"
    }

    assert jobs == {"build": 5, "quoted job": 8, "test": 10}


def test_alias_bomb_in_timeout_minutes_is_not_expanded(tmp_path):
    lines = ["on: push", "jobs:", "  a:", "    runs-on: x", "    steps: []", "    x0: &b0 [z]"]
    for i in range(1, 12):
        lines.append(f"    x{i}: &b{i} [" + ", ".join([f"*b{i - 1}"] * 9) + "]")
    lines.append("    timeout-minutes: *b11")
    workflow(tmp_path, "\n".join(lines) + "\n")

    items, seconds = timed(lambda: gha.extract(str(tmp_path)))

    assert seconds < 8, seconds
    job = next(i for i in items if i["peer_group"] == "gha_jobs")
    assert job["features"]["has_timeout_minutes"] is False


def test_recursive_anchor_does_not_drop_other_workflows(tmp_path):
    workflow(
        tmp_path,
        "on: push\njobs:\n  a:\n    x: &a [*a]\n    runs-on: *a\n    steps: []\n",
        name="loop.yml",
    )
    workflow(
        tmp_path,
        "on: push\njobs:\n  ok:\n    runs-on: x\n    timeout-minutes: 5\n",
        name="good.yml",
    )

    items = gha.extract(str(tmp_path))  # must not raise RecursionError

    files = {i["file"] for i in items}
    assert ".github/workflows/good.yml" in files
