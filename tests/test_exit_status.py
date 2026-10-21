"""--fail-on-findings lets a CI job fail on a finding. Without it the exit status stays 0."""

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"


def run_cli(cwd, *args):
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(
        [sys.executable, "-m", "deviant_scan", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
    )


def make_routes(tmp_path, total: int, unprotected: int) -> None:
    (tmp_path / "app").mkdir(exist_ok=True)
    lines = ["from fastapi import APIRouter, Depends", "router = APIRouter()"]
    for i in range(total):
        dep = "" if i < unprotected else ", dependencies=[Depends(get_current_user)]"
        lines += [f'@router.post("/r{i}"{dep})', f"def h{i}():", "    return {}"]
    (tmp_path / "app" / "r.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_finding_does_not_change_the_exit_status_by_default(tmp_path):
    make_routes(tmp_path, total=30, unprotected=1)  # one exception among 30: a strict rule

    result = run_cli(tmp_path, "--json", ".")

    assert result.returncode == 0
    assert json.loads(result.stdout)["rules"], "the test project must produce a finding"


def test_a_finding_fails_the_run_with_the_flag(tmp_path):
    make_routes(tmp_path, total=30, unprotected=1)

    result = run_cli(tmp_path, "--fail-on-findings", ".")

    assert result.returncode == 1
    assert b"has_auth" in result.stdout  # the report is still printed


def test_json_is_still_printed_when_the_flag_fails_the_run(tmp_path):
    make_routes(tmp_path, total=30, unprotected=1)

    result = run_cli(tmp_path, "--json", "--fail-on-findings", ".")

    assert result.returncode == 1
    assert json.loads(result.stdout)["rules"]


def test_no_finding_passes_with_the_flag(tmp_path):
    make_routes(tmp_path, total=30, unprotected=0)  # every route is protected

    result = run_cli(tmp_path, "--fail-on-findings", ".")

    assert result.returncode == 0


def test_leads_alone_do_not_fail_the_run(tmp_path):
    # Ten routes, one unprotected: too few for a rule, so it is only a lead.
    make_routes(tmp_path, total=10, unprotected=1)

    result = run_cli(tmp_path, "--json", "--inventory", "--fail-on-findings", ".")

    data = json.loads(result.stdout)
    assert data["rules"] == []
    assert data["inventory"]["candidates"], "the test project must produce a lead"
    assert result.returncode == 0


def test_a_usage_error_still_exits_2(tmp_path):
    result = run_cli(tmp_path, "--fail-on-findings", "--min-items", "0", ".")

    assert result.returncode == 2
