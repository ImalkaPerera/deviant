import sys
from pathlib import Path

import github_actions as gha
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "github_actions"


def by_key(case):
    return {(i["peer_group"], i["item_id"]): i for i in gha.extract(str(FIXTURES / case))}


def test_workflow_permissions_block():
    items = by_key("mixed")
    assert items[("gha_workflows", ".github/workflows/ci.yml")]["features"] == {
        "has_permissions_block": True
    }


def test_job_timeouts_and_workflow_level_concurrency():
    items = by_key("mixed")
    test_job = items[("gha_jobs", "test")]
    assert test_job["features"] == {"has_timeout_minutes": True, "has_concurrency": True}
    deploy_job = items[("gha_jobs", "deploy")]
    assert deploy_job["features"] == {"has_timeout_minutes": False, "has_concurrency": True}


def test_reusable_workflow_call_job_is_skipped():
    assert ("gha_jobs", "reuse") not in by_key("mixed")


def test_third_party_steps_pinned_only_when_sha_pinned():
    items = by_key("mixed")
    checkout = items[
        ("gha_third_party_steps", "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1")
    ]
    assert checkout["features"]["pinned_to_sha"] is True
    assert checkout["file"] == ".github/workflows/ci.yml"
    assert checkout["line"] == 12
    assert items[("gha_third_party_steps", "actions/setup-python@v5")]["features"] == {
        "pinned_to_sha": False
    }
    assert items[("gha_third_party_steps", "docker://alpine:3.20")]["features"] == {
        "pinned_to_sha": False
    }


def test_local_actions_are_not_third_party_steps():
    items = by_key("mixed")
    assert not [k for k in items if "./.github/actions/local" in k[1]]


def test_broken_yaml_is_skipped_without_crashing():
    assert gha.extract(str(FIXTURES / "bad")) == []


def test_missing_pyyaml_skips_the_detector(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "yaml", None)
    assert gha.extract(str(FIXTURES / "mixed")) == []
    assert "PyYAML is not installed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("needle", "expected_line"),
    [("jobs:", 7), ("deploy:", 15)],
)
def test_line_numbers_point_at_the_right_line(needle, expected_line):
    lines = (FIXTURES / "mixed" / ".github" / "workflows" / "ci.yml").read_text().splitlines()
    assert gha._line_of(lines, needle) == expected_line


def edge_items():
    return gha.extract(str(FIXTURES / "edge"))


def test_permissions_on_every_job_count_as_a_permissions_block():
    workflow = [i for i in edge_items() if i["peer_group"] == "gha_workflows"][0]
    assert workflow["features"] == {"has_permissions_block": True}


def test_job_line_skips_same_named_keys_above_jobs():
    build = [i for i in edge_items() if i["peer_group"] == "gha_jobs"][0]
    assert (build["item_id"], build["line"]) == ("build", 8)


def test_uppercase_sha_counts_as_pinned():
    steps = [i for i in edge_items() if i["item_id"].startswith("actions/checkout@")]
    assert steps[0]["features"] == {"pinned_to_sha": True}


def test_repeated_steps_get_their_own_lines():
    cache_lines = [i["line"] for i in edge_items() if i["item_id"] == "actions/cache@v4"]
    assert cache_lines == [14, 15]


def test_reusable_workflow_call_must_be_pinned_too():
    calls = [i for i in edge_items() if i["item_id"].startswith("octo-org/shared/")]
    assert len(calls) == 1
    assert calls[0]["peer_group"] == "gha_third_party_steps"
    assert calls[0]["features"] == {"pinned_to_sha": False}
    assert calls[0]["line"] == 19
    assert not [
        i for i in edge_items() if i["peer_group"] == "gha_jobs" and i["item_id"] == "release"
    ]
