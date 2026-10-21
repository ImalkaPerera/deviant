"""Regression tests for the reliability audit after 0.3.1: crashes, hangs and quiet misses."""

import ast
import os
import subprocess
import textwrap
import time
from pathlib import Path

import pytest
from deviant_scan import git_forensics as gf
from deviant_scan import mine
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr

ROUTES = (
    "from fastapi import APIRouter, Depends\n"
    "from .deps import get_current_user\n"
    "router = APIRouter()\n"
)


def routes_file(count, extra=""):
    text = ROUTES
    for i in range(count):
        text += f"\n@router.get('/r{i}')\n"
        text += f"def r{i}(user=Depends(get_current_user)):\n    return {i}\n"
    return text + extra


def project(tmp_path, routes_text, deps="def get_current_user(): pass\n", config=None):
    app = tmp_path / "app"
    app.mkdir(parents=True)
    (app / "deps.py").write_text(deps, encoding="utf-8")
    (app / "items.py").write_text(routes_text, encoding="utf-8")
    if config is not None:
        (tmp_path / ".deviant").mkdir()
        (tmp_path / ".deviant" / "config.json").write_text(config, encoding="utf-8")
    return tmp_path


def route(items, path):
    return next(i for i in items if i["item_id"] == f"GET {path}")


# --- python_routes ------------------------------------------------------------------------


def test_a_form_feed_does_not_shift_the_comment_above_a_route(tmp_path):
    # str.splitlines() breaks at a form feed but Python does not, so every later line moved
    # by one and the "public endpoint" comment was read from the wrong line.
    extra = "\n# a\x0c b\n# public endpoint\n@router.get('/open')\ndef open_():\n    return 1\n"
    items = pr.extract(str(project(tmp_path, routes_file(3, extra))))

    assert route(items, "/open")["features"]["has_auth"] is True


def test_source_lines_are_numbered_like_the_syntax_tree():
    text = "a = 1\x0c\nb = ' '\nc = 3  # \x1c\r\nd = 4\re = 5"
    tree = ast.parse(text)
    lines = pr._source_lines(text)

    for node in tree.body:
        assert lines[node.lineno - 1].lstrip().startswith(node.targets[0].id)


def test_auth_words_given_as_one_string_are_one_word(tmp_path):
    deps = "def get_current_user(): pass\ndef gatekeeper(): pass\n"
    extra = "\n@router.get('/open')\ndef open_(v=Depends(gatekeeper)):\n    return 1\n"
    text = routes_file(2, extra).replace(
        "import get_current_user", "import get_current_user, gatekeeper"
    )
    items = pr.extract(
        str(project(tmp_path, text, deps=deps, config='{"auth_words": "gatekeeper"}'))
    )

    assert route(items, "/open")["features"]["has_auth"] is True


@pytest.mark.parametrize(
    ("config", "reason"),
    [
        ("{auth", "is not valid JSON"),
        ('{"auth_words": 3}', 'needs "auth_words" to be a list'),
        ("[1, 2]", 'needs "auth_words" to be a list'),
    ],
)
def test_a_config_that_cannot_be_used_is_reported(tmp_path, capsys, config, reason):
    pr.extract(str(project(tmp_path, routes_file(1), config=config)))

    assert reason in capsys.readouterr().err


def test_no_config_says_nothing(tmp_path, capsys):
    pr.extract(str(project(tmp_path, routes_file(1))))

    assert "config.json" not in capsys.readouterr().err


def test_a_string_in_an_annotation_that_cannot_be_parsed_is_skipped():
    # Python 3.10 and 3.11 raise ValueError for a null byte, which used to end the detector.
    annotation = ast.parse("Annotated[str, Query(description='a\\x00b')]", mode="eval").body

    assert pr._nested_annotations(annotation) == []


def test_one_file_that_trips_the_detector_does_not_drop_the_others(tmp_path, monkeypatch, capsys):
    project(tmp_path, routes_file(2))
    (tmp_path / "app" / "other.py").write_text(routes_file(2), encoding="utf-8")
    real = pr._routes_in_file

    def flaky(rel, *args):
        if rel == "app/other.py":
            raise ValueError("boom")
        return real(rel, *args)

    monkeypatch.setattr(pr, "_routes_in_file", flaky)
    items = pr.extract(str(tmp_path))

    assert {i["file"] for i in items} == {"app/items.py"}
    assert "app/other.py could not be read for routes (ValueError)" in capsys.readouterr().err


def test_routers_mounted_twice_at_every_level_are_read_in_linear_time(tmp_path):
    # Every level doubles the number of mount paths: 2**30 without a limit.
    levels = 30
    src = ["from fastapi import APIRouter, FastAPI", "app = FastAPI()"]
    src += [f"r{i} = APIRouter()" for i in range(levels)]
    for i in range(levels - 1):
        src += [
            f"r{i + 1}.include_router(r{i}, prefix='/a')",
            f"r{i + 1}.include_router(r{i}, prefix='/b')",
        ]
    src += [f"app.include_router(r{levels - 1})", "@r0.get('/x')", "def x():", "    return 1"]
    (tmp_path / "main.py").write_text("\n".join(src) + "\n", encoding="utf-8")

    start = time.monotonic()
    items = pr.extract(str(tmp_path))

    assert time.monotonic() - start < 10
    assert [i["item_id"] for i in items] == ["GET /x"]


def test_dropped_mounts_never_make_a_root_route_public():
    # Every mount it was given is public, but some were dropped, so it cannot be called public.
    mounts = [f"/v{i}/health" for i in range(pr.MAX_MOUNTS - 1)] + [""]

    assert pr._public_route("", mounts) is False


# --- github_actions -----------------------------------------------------------------------


def workflow(tmp_path, text, name="w.yml"):
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(textwrap.dedent(text), encoding="utf-8")
    return gha.extract(str(tmp_path))


@pytest.mark.parametrize(
    "value", ["true", "True", "${{ true }}", "${{true}}", "${{  TRUE  }}", "'${{true }}'"]
)
def test_every_spelling_of_true_ignores_the_failure(tmp_path, value):
    items = workflow(
        tmp_path,
        f"""\
        on: push
        jobs:
          a:
            runs-on: x
            steps:
              - run: make
                continue-on-error: {value}
        """,
    )

    step = next(i for i in items if i["peer_group"] == "gha_run_steps")
    assert step["features"]["fails_on_error"] is False


@pytest.mark.parametrize("value", ["false", "${{ matrix.experimental }}", "${{ true && false }}"])
def test_other_values_do_not_ignore_the_failure(tmp_path, value):
    items = workflow(
        tmp_path,
        f"""\
        on: push
        jobs:
          a:
            runs-on: x
            steps:
              - run: make
                continue-on-error: {value}
        """,
    )

    step = next(i for i in items if i["peer_group"] == "gha_run_steps")
    assert step["features"]["fails_on_error"] is True


def test_a_pinned_step_gets_its_own_line_when_earlier_text_names_the_action(tmp_path):
    items = workflow(
        tmp_path,
        """\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            steps:
              - run: echo "we use actions/setup-node@v4 below"
              - uses: actions/setup-node@v4
        """,
    )

    step = next(i for i in items if i["peer_group"] == "gha_third_party_steps")
    assert step["line"] == 7


def test_a_composite_action_step_gets_its_own_line(tmp_path):
    (tmp_path / "action.yml").write_text(
        textwrap.dedent(
            """\
            runs:
              using: composite
              steps:
                - run: echo actions/cache@v4
                  shell: bash
                - uses: actions/cache@v4
            """
        ),
        encoding="utf-8",
    )

    step = next(i for i in gha.extract(str(tmp_path)) if i["peer_group"] == "gha_third_party_steps")
    assert step["line"] == 6


def test_nested_merge_keys_are_refused_before_they_expand(tmp_path, capsys):
    # Each level merges the one below nine times: 9**8 keys from under 600 bytes.
    lines = ["a0: &a0 {k: v}"]
    for i in range(1, 9):
        lines.append(f"a{i}: &a{i} {{<<: [{', '.join([f'*a{i - 1}'] * 9)}]}}")
    lines += ["on: push", "jobs:", "  j:", "    <<: *a8", "    runs-on: x"]
    workflow(tmp_path, "\n".join(lines) + "\n", name="bomb.yml")
    workflow(tmp_path, "on: push\njobs:\n  ok:\n    runs-on: x\n", name="ok.yml")

    start = time.monotonic()
    items = gha.extract(str(tmp_path))

    assert time.monotonic() - start < 10
    assert {i["file"] for i in items} == {".github/workflows/ok.yml"}
    assert "bomb.yml merges more than" in capsys.readouterr().err


def test_ordinary_merge_keys_still_load(tmp_path):
    items = workflow(
        tmp_path,
        """\
        defaults: &defaults
          runs-on: x
          timeout-minutes: 5
        on: push
        jobs:
          a:
            <<: *defaults
          b:
            <<: *defaults
        """,
    )

    jobs = [i for i in items if i["peer_group"] == "gha_jobs"]
    assert [j["features"]["has_timeout_minutes"] for j in jobs] == [True, True]


# --- git evidence -------------------------------------------------------------------------


def git(repo: Path, *args: str, date=None) -> None:
    env = os.environ.copy()
    env.update(
        GIT_AUTHOR_NAME="Ann",
        GIT_AUTHOR_EMAIL="ann@example.com",
        GIT_COMMITTER_NAME="Ann",
        GIT_COMMITTER_EMAIL="ann@example.com",
    )
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def scan_items(lines, missing):
    return [
        {
            "detector": "d",
            "peer_group": "g",
            "item_id": f"r{n}",
            "file": "a.py",
            "line": n,
            "features": {"has_x": n != missing},
        }
        for n in lines
    ]


def needs_attr_source():
    if not gf._attr_source_supported():
        pytest.skip("git 2.40 or newer is needed for blame evidence")


def test_a_commit_dated_past_the_year_9999_does_not_end_the_scan(tmp_path):
    needs_attr_source()
    (tmp_path / "a.py").write_text("x = 1\n" * 30, encoding="utf-8")
    git(tmp_path, "init", "-q")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "far", date="@999999999999 +0000")
    blame = subprocess.run(
        ["git", "-C", str(tmp_path), "blame", "--line-porcelain", "-L1,1", "--", "a.py"],
        capture_output=True,
        text=True,
    ).stdout
    if "author-time 999999999999" not in blame:
        # Git for Windows keeps the date but blame reports it in 32 bits, as 2106, so this
        # git never hands the scan the far date. The blame parser test covers it there.
        pytest.skip("this git's blame does not report the far date")

    rules = mine.mine(scan_items(range(1, 31), 5), repo_root=tmp_path)

    block = rules[0]["exceptions"][0]["git"]
    assert block["commit"] and block["date"] is None
    assert "last changed:" in mine._format_text(rules)
    assert "None" not in mine._format_text(rules)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("0", (0, "1970-01-01")), ("999999999999", (999999999999, None)), ("x", (0, None))],
)
def test_commit_times_that_are_not_dates_have_no_date(text, expected):
    assert gf._when(text) == expected


def test_blame_with_a_far_future_time_is_parsed_without_a_date():
    # The same input as above, without needing a git that can store it.
    output = "a" * 40 + " 1 1 1\nauthor-mail <ann@example.com>\nauthor-time 999999999999\n\tx\n"

    parsed = gf._parse_blame(output)[1]

    assert parsed["time"] == 999999999999 and parsed["date"] is None


def test_a_sha256_repository_gets_git_evidence(tmp_path):
    needs_attr_source()
    try:
        git(tmp_path, "init", "-q", "--object-format=sha256")
    except subprocess.CalledProcessError:
        pytest.skip("this git cannot make a SHA-256 repository")
    (tmp_path / "a.py").write_text("x = 1\n" * 30, encoding="utf-8")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "add a")

    rules = mine.mine(scan_items(range(1, 31), 5), repo_root=tmp_path)

    block = rules[0]["exceptions"][0]["git"]
    assert block is not None
    assert block["subject"] == "add a"
    assert block["author"] == "ann@example.com"


def test_an_uncommitted_line_in_a_sha256_repository_has_no_commit():
    output = "0" * 64 + " 1 1 1\nauthor-mail <not.committed.yet>\nauthor-time 0\n\tx\n"

    assert gf._parse_blame(output)[1]["commit"] is None


def test_nearby_comments_count_lines_like_git(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\x0c\n# public\ny = 2\n", encoding="utf-8")
    evidence = gf.GitEvidence.__new__(gf.GitEvidence)
    evidence.repo = str(tmp_path)

    # Line 2 is the comment. Split at the form feed, line 2 would be the empty text after it.
    assert evidence._nearby_comments("a.py", 2) == "# public"
