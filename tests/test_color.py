"""Coloured output: only a presentation layer, off unless a person is reading a terminal."""

import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from deviant_scan.mine import _format_text, main, mine, should_color

SCRIPT = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts" / "mine.py"
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def rules_with_git_like_data():
    items = [
        {
            "detector": "d",
            "peer_group": "g",
            "item_id": f"POST /r{i}",
            "file": f"app/r{i}.py",
            "line": 5,
            "features": {"has_auth": i != 3},
        }
        for i in range(40)
    ]
    rules = mine(items)
    assert rules
    for exception in rules[0]["exceptions"]:
        exception["git"] = {
            "history_truncated": True,
            "commit": "abc1234",
            "author": "dana@example.com",
            "date": "2026-10-17",
            "subject": "add csv export",
            "files_in_commit": 1,
            "author_followed_rule_elsewhere": 39,
            "compliant_checked": 39,
            "intent_words": ["public"],
            "uncommitted": False,
        }
    return rules


def test_plain_output_has_no_escape_codes():
    assert "\x1b" not in _format_text(rules_with_git_like_data())


def test_colour_never_changes_the_words_only_adds_codes():
    rules = rules_with_git_like_data()
    plain = _format_text(rules, color=False)
    coloured = _format_text(rules, color=True)
    assert coloured != plain
    assert ANSI.sub("", coloured) == plain


def test_every_code_that_is_opened_is_closed():
    coloured = _format_text(rules_with_git_like_data(), color=True)
    for line in coloured.splitlines():
        opened = len(re.findall(r"\x1b\[(?!0m)[0-9;]+m", line))
        closed = line.count("\x1b[0m")
        assert opened == closed, line


class FakeStream:
    def __init__(self, tty):
        self._tty = tty

    def isatty(self):
        return self._tty


@pytest.mark.parametrize(
    ("mode", "tty", "env", "expected"),
    [
        ("always", False, {}, True),
        ("always", False, {"NO_COLOR": "1"}, True),  # an explicit request wins
        ("never", True, {}, False),
        ("auto", True, {}, True),
        ("auto", False, {}, False),
        ("auto", True, {"NO_COLOR": "1"}, False),
        ("auto", True, {"NO_COLOR": ""}, False),  # the NO_COLOR convention: present means off
        ("auto", True, {"TERM": "dumb"}, False),
    ],
)
def test_when_colour_is_used(mode, tty, env, expected):
    assert should_color(mode, FakeStream(tty), env) is expected


def run_cli(tmp_path, *args):
    repo = tmp_path / "repo"
    routes = repo / "app"
    routes.mkdir(parents=True, exist_ok=True)
    for i in range(30):
        body = "def h(u=Depends(get_current_user)):" if i != 4 else "def h():"
        (routes / f"r{i}.py").write_text(
            "from fastapi import APIRouter, Depends\nrouter = APIRouter()\n\n\n"
            f"@router.post('/r{i}')\n{body}\n    return {{}}\n"
        )
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), *args], capture_output=True, text=True
    )


def test_piped_output_is_plain_by_default(tmp_path):
    result = run_cli(tmp_path)
    assert result.returncode == 0
    assert "exception:" in result.stdout
    assert "\x1b" not in result.stdout


def test_color_always_colours_piped_output(tmp_path):
    result = run_cli(tmp_path, "--color", "always")
    assert "\x1b[" in result.stdout
    assert ANSI.sub("", result.stdout).strip() == run_cli(tmp_path).stdout.strip()


def test_color_never_and_json_are_never_coloured(tmp_path):
    assert "\x1b" not in run_cli(tmp_path, "--color", "never").stdout
    as_json = run_cli(tmp_path, "--color", "always", "--json").stdout
    assert "\x1b" not in as_json
    assert json.loads(as_json)["rules"]


def test_an_unknown_colour_mode_is_rejected(tmp_path):
    assert run_cli(tmp_path, "--color", "rainbow").returncode == 2


def test_main_accepts_the_flag_in_process(monkeypatch, tmp_path):
    out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    assert main(["--repo", str(tmp_path), "--color", "always"]) == 0
