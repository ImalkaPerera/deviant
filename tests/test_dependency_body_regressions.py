"""Regression tests: auth done inside a dependency's body, or a class's __init__, counts."""

import textwrap

from deviant_scan.detectors import python_routes as pr

HEADER = """\
from fastapi import APIRouter, Depends, Header, HTTPException

router = APIRouter()
"""


def route_has_auth(tmp_path, body: str) -> bool:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "routes.py").write_text(HEADER + textwrap.dedent(body), encoding="utf-8")
    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "app/routes.py"]
    assert len(items) == 1, items
    return items[0]["features"]["has_auth"]


def test_dependency_that_raises_401_counts_as_auth(tmp_path):
    assert route_has_auth(
        tmp_path,
        """\
        def get_user(x: str = Header(None)):
            if x != "secret":
                raise HTTPException(status_code=401)
            return x

        @router.post("/items", dependencies=[Depends(get_user)])
        def create():
            return {}
        """,
    )


def test_dependency_without_a_check_does_not_count(tmp_path):
    assert not route_has_auth(
        tmp_path,
        """\
        def get_thing():
            return 1

        @router.post("/items", dependencies=[Depends(get_thing)])
        def create():
            return {}
        """,
    )


def test_class_whose_init_depends_on_auth_counts_as_auth(tmp_path):
    assert route_has_auth(
        tmp_path,
        """\
        class Service:
            def __init__(self, user=Depends(get_current_user)):
                self.user = user

        @router.post("/items")
        def create(svc: Service = Depends()):
            return {}
        """,
    )


def test_class_without_auth_does_not_count(tmp_path):
    assert not route_has_auth(
        tmp_path,
        """\
        class Service:
            def __init__(self):
                self.items = []

        @router.post("/items")
        def create(svc: Service = Depends()):
            return {}
        """,
    )


def test_route_body_calling_an_auth_class_does_not_count(tmp_path):
    assert not route_has_auth(
        tmp_path,
        """\
        class Service:
            def __init__(self, user=Depends(get_current_user)):
                self.user = user

        @router.post("/items")
        def create():
            Service()
            return {}
        """,
    )
