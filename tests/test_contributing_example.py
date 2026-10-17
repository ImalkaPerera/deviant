"""The example detector in CONTRIBUTING.md must work exactly as written."""

import re
from pathlib import Path

from deviant_scan.mine import run

ROOT = Path(__file__).resolve().parent.parent


def example_source() -> str:
    text = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    blocks = re.findall(r"```python\n(.*?)```", text, flags=re.DOTALL)
    (source,) = [b for b in blocks if b.startswith('"""Example detector')]
    return source


def make_project(root: Path, total: int, root_users: set[int]) -> None:
    for number in range(total):
        folder = root / f"service{number}"
        folder.mkdir(parents=True)
        user = "root" if number in root_users else "app"
        (folder / "Dockerfile").write_text(f"FROM python:3.12\nUSER {user}\n", encoding="utf-8")


def test_the_example_detector_finds_the_one_dockerfile_that_runs_as_root(tmp_path, capsys):
    detectors = tmp_path / "detectors"
    detectors.mkdir()
    (detectors / "dockerfiles.py").write_text(example_source(), encoding="utf-8")
    project = tmp_path / "project"
    make_project(project, total=25, root_users={7})

    assert run(project, detectors, min_items=20, min_confidence=0.80, as_json=True) == 0

    import json

    (rule,) = json.loads(capsys.readouterr().out)["rules"]
    assert (rule["n"], rule["s"], rule["v"]) == (25, 24, 1)
    assert [e["file"] for e in rule["exceptions"]] == ["service7/Dockerfile"]


def test_the_example_detector_handles_dockerfiles_it_cannot_read(tmp_path):
    namespace: dict = {}
    exec(compile(example_source(), "dockerfiles.py", "exec"), namespace)  # noqa: S102
    project = tmp_path / "project"
    project.mkdir()
    (project / "Dockerfile").write_bytes(b"\xff\xfe not utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "Dockerfile").write_text("USER app\n")
    assert namespace["extract"](str(project)) == []
