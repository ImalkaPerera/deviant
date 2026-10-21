"""The file walk visits each real folder once, reports paths it cannot read, and the inventory
lists a bounded number of groups.

Backslashes are built with chr(92), so the source holds none.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from deviant_scan import mine
from deviant_scan.detectors import python_routes as pr

BS = chr(92)
ROUTE_FILE = (
    "from fastapi import APIRouter\n"
    "router = APIRouter()\n"
    "\n"
    "@router.post('/items')\n"
    "def create():\n"
    "    return {}\n"
)


def junction(link: Path, target: Path) -> None:
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction on this system")


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_a_junction_loop_is_walked_once_and_finishes_quickly(tmp_path):
    root = tmp_path / "f"
    (root / "app").mkdir(parents=True)
    (root / "app" / "routes.py").write_text(ROUTE_FILE, encoding="utf-8")
    junction(root / "app" / "loop", root)  # points back up the tree
    junction(root / "loop2", root / "app")  # points sideways into a folder that loops

    start = time.monotonic()
    items = pr.extract(str(root))
    seconds = time.monotonic() - start

    assert seconds < 20, seconds  # the unfixed walk took over four minutes
    assert [i["file"] for i in items] == ["app/routes.py"]


@pytest.mark.skipif(sys.platform != "win32", reason="long paths are a Windows limit")
def test_a_path_the_system_cannot_read_is_reported_not_skipped_silently(tmp_path, capsys):
    deep = tmp_path / "d"
    for _ in range(120):
        deep = deep / "nn"
    prefix = BS + BS + "?" + BS
    try:
        os.makedirs(prefix + str(deep), exist_ok=True)
        (Path(prefix + str(deep)) / "app.py").write_text(ROUTE_FILE, encoding="utf-8")
    except OSError:
        pytest.skip("could not create a path this long")
    (tmp_path / "d" / "main.py").write_text("x = 1\n", encoding="utf-8")

    items = pr.extract(str(tmp_path))
    err = capsys.readouterr().err

    found = any(i["file"].endswith("app.py") for i in items)
    assert found or "could not be read" in err, "the deep file was dropped without a word"


def make_group(name: str, size: int) -> list[dict]:
    return [
        {
            "detector": "d",
            "peer_group": name,
            "item_id": f"r{i}",
            "file": f"{name}.py",
            "line": i + 1,
            "features": {"has_auth": True},
        }
        for i in range(size)
    ]


def test_inventory_lists_a_bounded_number_of_groups_largest_first():
    items = []
    for n in range(150):
        items += make_group(f"g{n:03d}", 2)
    items += make_group("big", 9)

    survey = mine.inventory(items)

    assert survey["group_count"] == 151
    assert len(survey["groups"]) == mine.INVENTORY_MAX_GROUPS
    assert survey["groups_omitted"] == 151 - mine.INVENTORY_MAX_GROUPS
    assert survey["groups"][0]["peer_group"] == "big"


def test_inventory_under_the_group_limit_omits_nothing():
    survey = mine.inventory(make_group("a", 5) + make_group("b", 3))

    assert survey["group_count"] == 2 and survey["groups_omitted"] == 0
    assert [g["peer_group"] for g in survey["groups"]] == ["a", "b"]


def test_text_output_reports_the_total_number_of_groups():
    items = []
    for n in range(150):
        items += make_group(f"g{n:03d}", 2)

    text = mine._format_inventory(mine.inventory(items))

    assert text.startswith("inventory: 150 group(s)")
