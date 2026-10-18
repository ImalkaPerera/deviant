"""Our own workflows must follow the rules Deviant checks in other projects, and the CI checks."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
COMMIT = re.compile(r"^[0-9a-f]{40}$")
IDS = [p.name for p in WORKFLOWS]


def load(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def steps_of(workflow):
    for job in workflow["jobs"].values():
        yield from job.get("steps", [])


def test_the_workflows_are_found():
    assert {"ci.yml", "release.yml", "security.yml"} <= set(IDS)


@pytest.mark.parametrize("path", WORKFLOWS, ids=IDS)
def test_a_workflow_sets_its_token_permissions(path):
    assert "permissions" in load(path)


@pytest.mark.parametrize("path", WORKFLOWS, ids=IDS)
def test_every_job_has_a_timeout(path):
    for name, job in load(path)["jobs"].items():
        if "uses" not in job:  # a call to a reusable workflow has no timeout of its own
            assert "timeout-minutes" in job, name


@pytest.mark.parametrize("path", WORKFLOWS, ids=IDS)
def test_every_action_is_pinned_to_a_commit(path):
    for step in steps_of(load(path)):
        uses = step.get("uses")
        if uses and not uses.startswith("./"):
            assert COMMIT.match(uses.rsplit("@", 1)[1]), uses


@pytest.mark.parametrize("path", WORKFLOWS, ids=IDS)
def test_checkout_does_not_keep_the_token(path):
    for step in steps_of(load(path)):
        if step.get("uses", "").startswith("actions/checkout@"):
            assert step.get("with", {}).get("persist-credentials") is False


def test_the_security_workflow_runs_the_four_checks():
    jobs = load(ROOT / ".github" / "workflows" / "security.yml")["jobs"]
    assert set(jobs) == {"zizmor", "actionlint", "pip-audit", "gitleaks"}


def test_the_python_tools_are_pinned_exactly():
    lines = (ROOT / "requirements-security.txt").read_text(encoding="utf-8").split()
    assert {line.split("==")[0] for line in lines} == {"zizmor", "pip-audit"}
    assert all("==" in line for line in lines)
