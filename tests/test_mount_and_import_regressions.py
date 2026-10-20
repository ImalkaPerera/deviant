"""Regression tests: mount prefixes decide public paths, nested string annotations and star
imports are followed, and a junction does not scan the same file twice."""

import subprocess
import sys
import textwrap

import pytest
from deviant_scan.detectors import python_routes as pr

HEADER = """\
from typing import Annotated, Optional
from fastapi import APIRouter, Depends

router = APIRouter()
"""


def routes_in(root, rel="app/routes.py"):
    return {
        i["item_id"]: i["features"]["has_auth"] for i in pr.extract(str(root)) if i["file"] == rel
    }


def write(root, rel, source, header=""):
    """Write a file: the header is written as-is, and the body is dedented on its own."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + textwrap.dedent(source), encoding="utf-8")


def test_include_prefix_makes_a_root_route_public(tmp_path):
    write(
        tmp_path,
        "app/routes.py",
        """\
        from fastapi import APIRouter, FastAPI

        health = APIRouter()

        @health.get("/")
        def check():
            return {}

        app = FastAPI()
        app.include_router(health, prefix="/health")
        """,
    )

    assert routes_in(tmp_path) == {"GET /": True}


def test_router_prefix_makes_an_empty_path_public(tmp_path):
    write(
        tmp_path,
        "app/routes.py",
        """\
        from fastapi import APIRouter
        login = APIRouter(prefix="/login")

        @login.post("")
        def sign_in():
            return {}
        """,
    )

    assert routes_in(tmp_path) == {"POST ": True}


def test_route_without_a_public_prefix_is_still_reported(tmp_path):
    write(
        tmp_path,
        "app/routes.py",
        """\
        from fastapi import APIRouter, FastAPI
        items = APIRouter(prefix="/items")
        app = FastAPI()

        @items.post("/")
        def create():
            return {}

        app.include_router(items, prefix="/v1")
        """,
    )

    assert routes_in(tmp_path) == {"POST /": False}


def test_alias_inside_a_string_in_an_annotation_counts(tmp_path):
    write(
        tmp_path,
        "app/routes.py",
        """\
        CurrentUser = Annotated[dict, Depends(get_current_user)]

        @router.post("/items")
        def create(user: Optional["CurrentUser"] = None):
            return {}
        """,
        header=HEADER,
    )

    assert routes_in(tmp_path) == {"POST /items": True}


def test_alias_brought_in_by_a_star_import_counts(tmp_path):
    write(
        tmp_path,
        "app/auth.py",
        """\
        from typing import Annotated
        from fastapi import Depends
        CurrentUser = Annotated[dict, Depends(get_current_user)]
        """,
    )
    write(
        tmp_path,
        "app/routes.py",
        """\
        from app.auth import *

        @router.post("/items")
        def create(user: CurrentUser):
            return {}
        """,
        header=HEADER,
    )

    assert routes_in(tmp_path) == {"POST /items": True}


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_junction_does_not_scan_the_same_file_twice(tmp_path):
    root = tmp_path / "repo"
    write(
        root,
        "real/routes.py",
        """\
        @router.post("/items")
        def create():
            return {}
        """,
        header=HEADER,
    )
    link = root / "linked"
    made = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(root / "real")],
        capture_output=True,
        check=False,
    )
    if made.returncode != 0:
        pytest.skip("could not create a junction on this system")

    files = [i["file"] for i in pr.extract(str(root))]

    assert files.count("real/routes.py") + files.count("linked/routes.py") == 1
