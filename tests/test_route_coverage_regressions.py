"""Regression tests: the scanner sees every registration form and reads auth from each one."""

import textwrap

from deviant_scan.detectors import python_routes as pr

HEADER = """\
from fastapi import APIRouter, Depends, FastAPI

router = APIRouter()
app = FastAPI()
"""


def routes(tmp_path, body: str) -> dict:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "routes.py").write_text(HEADER + textwrap.dedent(body), encoding="utf-8")
    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "app/routes.py"]
    return {i["item_id"]: i["features"]["has_auth"] for i in items}


def test_websocket_route_is_collected_and_protected(tmp_path):
    found = routes(
        tmp_path,
        """\
        @router.websocket("/ws")
        async def stream(user=Depends(get_current_user)):
            pass
        """,
    )
    assert found == {"WEBSOCKET /ws": True}


def test_unprotected_websocket_route_is_reported(tmp_path):
    found = routes(
        tmp_path,
        """\
        @router.websocket("/ws")
        async def stream():
            pass
        """,
    )
    assert found == {"WEBSOCKET /ws": False}


def test_add_route_is_collected(tmp_path):
    found = routes(
        tmp_path,
        """\
        async def export(request):
            pass

        router.add_route("/export", export, methods=["POST"])
        """,
    )
    assert found == {"POST /export": False}


def test_call_form_registration_is_collected_and_protected(tmp_path):
    found = routes(
        tmp_path,
        """\
        def fetch(user=Depends(get_current_user)):
            return {}

        router.get("/x")(fetch)
        """,
    )
    assert found == {"GET /x": True}


def test_call_form_registration_without_auth_is_reported(tmp_path):
    found = routes(
        tmp_path,
        """\
        def fetch():
            return {}

        router.get("/x")(fetch)
        """,
    )
    assert found == {"GET /x": False}


def test_keyword_router_in_include_router_is_followed(tmp_path):
    found = routes(
        tmp_path,
        """\
        sub = APIRouter()

        @sub.post("/items")
        def create():
            return {}

        app.include_router(router=sub, dependencies=[Depends(get_current_user)])
        """,
    )
    assert found == {"POST /items": True}


def test_bare_depends_takes_its_dependency_from_the_annotation(tmp_path):
    found = routes(
        tmp_path,
        """\
        @router.post("/items")
        def create(user: get_current_user = Depends()):
            return {}
        """,
    )
    assert found == {"POST /items": True}


def test_lambda_endpoint_reads_its_default_dependency(tmp_path):
    found = routes(
        tmp_path,
        """\
        router.add_api_route("/l", lambda u=Depends(get_current_user): {}, methods=["GET"])
        """,
    )
    assert found == {"GET /l": True}


def test_aliased_import_of_a_dependency_is_resolved(tmp_path):
    found = routes(
        tmp_path,
        """\
        from app.deps import get_current_user as gcu

        @router.post("/a", dependencies=[Depends(gcu)])
        def create():
            return {}
        """,
    )
    assert found == {"POST /a": True}


def test_template_like_file_is_reported_not_silently_skipped(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n"
        "@router.post('/x')\ndef x():\n    return {{ value }\n",
        encoding="utf-8",
    )

    pr.extract(str(tmp_path))

    assert "app/page.py defines routes but could not be parsed" in capsys.readouterr().err


def test_plain_template_without_routes_stays_quiet(tmp_path, capsys):
    (tmp_path / "gen.py").write_text("from {{ module }} import x\n{% for a in b %}\n")

    assert pr.extract(str(tmp_path)) == []
    assert capsys.readouterr().err == ""
