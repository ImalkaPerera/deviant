"""Regression tests for the findings from the independent review of the auth changes."""

import textwrap

from deviant_scan.detectors import python_routes as pr


def routes_in(tmp_path, source: str) -> dict:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "routes.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return {
        i["item_id"]: i["features"]["has_auth"]
        for i in pr.extract(str(tmp_path))
        if i["file"] == "app/routes.py"
    }


def test_mount_prefix_does_not_make_a_routes_own_path_public(tmp_path):
    found = routes_in(
        tmp_path,
        """\
        from fastapi import APIRouter
        router = APIRouter(prefix="/docs")

        @router.delete("/{doc_id}")
        def delete_doc(doc_id: int):
            return {}
        """,
    )

    assert found == {"DELETE /{doc_id}": False}


def test_root_route_under_a_public_mount_is_still_public(tmp_path):
    found = routes_in(
        tmp_path,
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

    assert found == {"GET /": True}


def test_class_calling_a_verify_helper_is_not_an_auth_dependency(tmp_path):
    found = routes_in(
        tmp_path,
        """\
        from fastapi import APIRouter, Depends
        router = APIRouter()

        class PageParams:
            def __init__(self, page: int = 1):
                self.verify_range(page)

            def verify_range(self, page):
                return page

        @router.get("/items")
        def list_items(p: PageParams = Depends()):
            return []
        """,
    )

    assert found == {"GET /items": False}


def test_class_that_denies_a_bad_token_is_an_auth_dependency(tmp_path):
    found = routes_in(
        tmp_path,
        """\
        from fastapi import APIRouter, Depends, HTTPException
        router = APIRouter()

        class Session:
            def __init__(self, token: str = ""):
                if token != "ok":
                    raise HTTPException(status_code=401)

        @router.get("/items")
        def list_items(s: Session = Depends()):
            return []
        """,
    )

    assert found == {"GET /items": True}
