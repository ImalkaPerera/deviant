"""The demo project used for the README clips still shows what the clips show."""

import subprocess
import sys
from pathlib import Path

from deviant_scan import mine

ROOT = Path(__file__).resolve().parent.parent
MAKE = ROOT / "docs" / "demo" / "make_demo_project.py"


def test_the_demo_project_has_one_route_without_auth_and_one_ignored_step(tmp_path):
    project = tmp_path / "demo"
    subprocess.run([sys.executable, str(MAKE), str(project)], check=True, capture_output=True)

    items = mine.collect_items(project, mine.DETECTORS_DIR)
    rules = mine.mine(items)
    leads = mine.inventory(items)["candidates"]

    assert [(r["feature"], r["n"], r["s"]) for r in rules] == [("has_auth", 48, 47)]
    assert [e["item_id"] for e in rules[0]["exceptions"]] == ["GET /users/export"]
    assert any(
        c["feature"] == "fails_on_error" and c["items"][0]["file"].endswith("release.yml")
        for c in leads
    )


def test_the_demo_refuses_a_folder_that_is_not_empty(tmp_path):
    (tmp_path / "keep.txt").write_text("x")

    result = subprocess.run(
        [sys.executable, str(MAKE), str(tmp_path)], capture_output=True, text=True
    )

    assert result.returncode == 2
    assert (tmp_path / "keep.txt").read_text() == "x"
