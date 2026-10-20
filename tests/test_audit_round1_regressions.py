"""Regression tests for the errors found by the audit of HEAD cd9f7b4."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr

SCRIPTS = Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"


def write(root, rel, source):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def routes_in(root, rel):
    return {
        i["item_id"]: i["features"]["has_auth"] for i in pr.extract(str(root)) if i["file"] == rel
    }


# --- python_routes -----------------------------------------------------------------------


def test_router_reached_by_two_include_paths_keeps_its_mount(tmp_path):
    # leaf is included by a and by b; both paths sit under the public mount "/docs".
    write(
        tmp_path,
        "leaf.py",
        """\
        from fastapi import APIRouter
        leaf = APIRouter()

        @leaf.get("/")
        def check():
            return {}
        """,
    )
    write(
        tmp_path,
        "a.py",
        """\
        from fastapi import APIRouter
        from leaf import leaf
        router = APIRouter()
        router.include_router(leaf)
        """,
    )
    write(
        tmp_path,
        "b.py",
        """\
        from fastapi import APIRouter
        from leaf import leaf
        router = APIRouter()
        router.include_router(leaf)
        """,
    )
    write(
        tmp_path,
        "m.py",
        """\
        from fastapi import APIRouter
        from a import router as a_router
        from b import router as b_router
        router = APIRouter()
        router.include_router(a_router)
        router.include_router(b_router)
        """,
    )
    write(
        tmp_path,
        "main.py",
        """\
        from fastapi import FastAPI
        from m import router as m_router
        app = FastAPI()
        app.include_router(m_router, prefix="/docs")
        """,
    )

    assert routes_in(tmp_path, "leaf.py") == {"GET /": True}


def test_import_of_a_full_module_path_picks_that_file_in_a_monorepo(tmp_path):
    write(tmp_path, "app/auth.py", "def require_login():\n    raise_it()\n")
    write(
        tmp_path,
        "app/routers/items.py",
        """\
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/x")
        def x():
            return {}
        """,
    )
    write(
        tmp_path,
        "svc/app/routers/items.py",
        """\
        from fastapi import APIRouter
        router = APIRouter()
        """,
    )
    write(
        tmp_path,
        "main.py",
        """\
        from fastapi import Depends, FastAPI
        from app.auth import require_login
        from app.routers import items
        app = FastAPI()
        app.include_router(items.router, dependencies=[Depends(require_login)])
        """,
    )

    assert routes_in(tmp_path, "app/routers/items.py") == {"GET /x": True}


def test_relative_import_inside_a_root_init_resolves(tmp_path):
    write(
        tmp_path,
        "__init__.py",
        "from .routes import router\n",
    )
    write(
        tmp_path,
        "routes.py",
        """\
        from fastapi import APIRouter
        router = APIRouter()

        @router.get("/items")
        def items():
            return {}
        """,
    )
    write(
        tmp_path,
        "server.py",
        """\
        from fastapi import Depends, FastAPI
        from app import require_login
        from . import router
        app = FastAPI()
        app.include_router(router, dependencies=[Depends(require_login)])
        """,
    )

    assert routes_in(tmp_path, "routes.py") == {"GET /items": True}


def test_add_route_reads_positional_methods(tmp_path):
    write(
        tmp_path,
        "app.py",
        """\
        from fastapi import FastAPI
        app = FastAPI()

        async def handler(request):
            return None

        app.add_route("/x", handler, ["POST"])
        """,
    )

    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "app.py"]

    assert [i["item_id"] for i in items] == ["POST /x"]
    assert items[0]["features"]["is_mutating"] is True


def test_call_form_route_resolves_a_method_endpoint(tmp_path):
    write(
        tmp_path,
        "app/svc.py",
        """\
        from fastapi import APIRouter, Depends

        class Svc:
            def __init__(self):
                self.router = APIRouter()
                self.router.get("/x")(self.handler)

            def handler(self, user=Depends(require_login)):
                return {}
        """,
    )

    assert routes_in(tmp_path, "app/svc.py") == {"GET /x": True}


def test_declared_public_comment_is_read_from_the_endpoints_own_file(tmp_path):
    write(
        tmp_path,
        "handlers.py",
        """\
        # public endpoint
        def secret():
            return {}
        """,
    )
    write(
        tmp_path,
        "main.py",
        """\
        from fastapi import APIRouter
        from handlers import secret
        router = APIRouter()
        router.get("/s")(secret)
        """,
    )

    assert routes_in(tmp_path, "main.py") == {"GET /s": True}


def test_module_function_is_not_replaced_by_a_method_of_the_same_name(tmp_path):
    write(
        tmp_path,
        "app.py",
        """\
        from fastapi import APIRouter, Depends
        router = APIRouter()

        def handler(user=Depends(require_login)):
            return {}

        class Old:
            def handler(self):
                return {}

        router.get("/x")(handler)
        """,
    )

    assert routes_in(tmp_path, "app.py") == {"GET /x": True}


# --- github_actions ----------------------------------------------------------------------


def test_blank_uses_is_skipped_and_other_findings_survive(tmp_path):
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        """\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: 5
            steps:
              - uses: ""
              - uses: actions/checkout@v4
        """,
    )

    items = gha.extract(str(tmp_path))
    steps = [i for i in items if i["peer_group"] == "gha_third_party_steps"]

    assert [i["item_id"] for i in steps] == ["actions/checkout@v4"]


def test_malformed_timestamp_skips_the_file(tmp_path, capsys):
    write(
        tmp_path,
        ".github/workflows/bad.yml",
        "x: !!timestamp '9999-12-31 99:99'\njobs: {}\n",
    )

    items = gha.extract(str(tmp_path))  # must not raise AttributeError

    assert items == []
    assert "bad.yml could not be parsed" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ('"0"', False),
        ("0", False),
        ("", False),
        ("10", True),
        ('"10"', True),
        ("${{ inputs.minutes }}", True),
    ],
)
def test_timeout_values(tmp_path, value, expected):
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        f"""\
        on: push
        jobs:
          build:
            runs-on: ubuntu-latest
            timeout-minutes: {value}
        """,
    )

    job = next(i for i in gha.extract(str(tmp_path)) if i["peer_group"] == "gha_jobs")

    assert job["features"]["has_timeout_minutes"] is expected


# --- CLI ---------------------------------------------------------------------------------


def test_explicit_empty_repo_argument_is_an_error(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(SCRIPTS)}
    result = subprocess.run(
        [sys.executable, "-m", "deviant_scan", "--repo", ""],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
