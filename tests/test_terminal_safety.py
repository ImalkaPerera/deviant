"""Text output must not pass control characters from a scanned project to the terminal.

This file builds every control character and backslash with chr(), so the source holds none.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from deviant_scan import mine
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"
ESC, BEL, RLO, BS = chr(27), chr(7), chr(0x202E), chr(92)
HOSTILE = "/x" + ESC + "[31mRED" + ESC + "[0m" + BEL + "bell" + RLO + "rtl"


def run_cli(cwd, *args):
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "deviant_scan", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
    )


def make_repo(tmp_path):
    (tmp_path / "app").mkdir()
    lines = ["from fastapi import APIRouter, Depends", "router = APIRouter()"]
    for i in range(10):
        path = HOSTILE if i == 9 else f"/ok{i}"
        dep = "" if i == 9 else ", dependencies=[Depends(get_current_user)]"
        lines += [f"@router.post({path!r}{dep})", f"def h{i}():", "    return {}"]
    (tmp_path / "app" / "r.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_text_output_shows_control_characters_as_escapes(tmp_path):
    make_repo(tmp_path)

    out = run_cli(tmp_path, "--inventory", "--color", "never", ".").stdout

    assert ESC.encode() not in out and BEL.encode() not in out
    assert RLO.encode() not in out
    assert (BS + "x1b[31mRED").encode() in out
    assert (BS + "x07bell").encode() in out


def test_json_output_has_no_raw_control_characters_and_keeps_the_value(tmp_path):
    make_repo(tmp_path)

    raw = run_cli(tmp_path, "--json", "--inventory", ".").stdout

    assert ESC.encode() not in raw and BEL.encode() not in raw
    data = json.loads(raw)
    ids = [i["item_id"] for c in data["inventory"]["candidates"] for i in c["items"]]
    assert ids == ["POST " + HOSTILE]


def test_printable_escapes_nested_strings_and_leaves_other_values():
    value = {"a": ["x" + ESC + "y", 3, None], "b": {"c": "ok"}}

    expected = {"a": ["x" + BS + "x1by", 3, None], "b": {"c": "ok"}}
    assert mine._printable(value) == expected


def test_a_newline_in_a_name_cannot_forge_a_line():
    shown = mine._printable("a" + chr(10) + "BUG forged")

    assert chr(10) not in shown
    assert shown == "a" + BS + "x0aBUG forged"


def test_detector_warnings_escape_file_names(capsys):
    gha._skipped(Path("bad" + ESC + "[31mname.yml"), "could not be parsed")

    assert ESC not in capsys.readouterr().err
    assert pr._show("a" + BEL + "b") == "a" + BS + "x07b"
