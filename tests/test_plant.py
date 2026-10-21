"""Tests for the bug-planting tool: each manifest entry must point at the line it changed."""

import ast
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bench" / "mutations"))

import plant  # noqa: E402


def workflow(root, text):
    folder = root / ".github" / "workflows"
    folder.mkdir(parents=True)
    path = folder / "ci.yml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_every_inserted_continue_on_error_is_where_the_manifest_says(tmp_path, monkeypatch):
    steps = "".join(f"      - name: t{i}\n        run: make t{i}\n" for i in range(6))
    path = workflow(tmp_path, "on: push\njobs:\n  a:\n    runs-on: x\n    steps:\n" + steps)
    monkeypatch.setitem(plant.PER_REPO, "other_gha", 6)
    manifest = []

    plant.plant_gha_other(tmp_path, manifest, "r")

    lines = path.read_text(encoding="utf-8").split("\n")
    assert len(manifest) == 6
    for entry in manifest:
        assert lines[entry["line"] - 1].strip() == "continue-on-error: true"
        assert lines[entry["line"] - 2].strip() == entry["original"]
        assert entry["original"].startswith("run: make t")
    assert sorted(e["original"] for e in manifest) == [f"run: make t{i}" for i in range(6)]


def test_every_deleted_timeout_is_recorded_at_its_own_job(tmp_path, monkeypatch):
    jobs = "".join(f"  j{i}:\n    runs-on: x\n    timeout-minutes: {i + 1}\n" for i in range(4))
    path = workflow(tmp_path, "on: push\njobs:\n" + jobs)
    monkeypatch.setitem(plant.PER_REPO, "same_gha", 4)
    manifest = []

    plant.plant_gha_same(tmp_path, manifest, "r")

    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    assert len(manifest) == 4
    assert "timeout-minutes" not in text
    for entry in manifest:
        # The line after the deleted one is the next job, or the end of the file.
        assert lines[entry["line"] - 2].strip() == "runs-on: x"


def routes(root, dependency):
    app = root / "app"
    app.mkdir()
    (app / "r.py").write_text(
        "from fastapi import APIRouter, Depends\n"
        "router = APIRouter()\n"
        "@router.get('/a')\n"
        f"def a(x=Depends({dependency})):\n"
        "    return {}\n",
        encoding="utf-8",
    )


def test_resource_providers_are_not_auth_candidates(tmp_path):
    for name in ("get_user_manager", "get_user_svc", "get_user_service", "get_user_db"):
        root = tmp_path / name
        root.mkdir()
        routes(root, name)
        assert plant.fastapi_candidates(root) == [], name


def test_auth_dependencies_are_candidates(tmp_path):
    routes(tmp_path, "get_current_user")
    found = plant.fastapi_candidates(tmp_path)
    assert [node.name for _path, node, _dep in found] == ["a"]
    assert isinstance(found[0][2], ast.Call)
