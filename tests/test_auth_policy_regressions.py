"""Regression tests for the auth policy: guard decorators, role checkers, cookies and /public."""

import textwrap

from deviant_scan.detectors import python_routes as pr

HEADER = """\
from fastapi import APIRouter, Cookie, Depends

router = APIRouter()


def requires_login(role):
    def decorate(fn):
        return fn

    return decorate


class RoleChecker:
    def __init__(self, roles):
        self.roles = roles
"""


def has_auth(tmp_path, body: str) -> bool:
    (tmp_path / "app").mkdir(exist_ok=True)
    (tmp_path / "app" / "routes.py").write_text(
        HEADER + "\n" + textwrap.dedent(body), encoding="utf-8"
    )
    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "app/routes.py"]
    assert len(items) == 1, items
    return items[0]["features"]["has_auth"]


def test_guard_decorator_counts_as_auth(tmp_path):
    assert has_auth(
        tmp_path,
        """\
        @router.post("/items")
        @requires_login("admin")
        def create():
            return {}
        """,
    )


def test_role_checker_dependency_counts_as_auth(tmp_path):
    assert has_auth(
        tmp_path,
        """\
        @router.post("/items", dependencies=[Depends(RoleChecker(["admin"]))])
        def create():
            return {}
        """,
    )


def test_cookie_parameter_counts_as_credential_whatever_its_name(tmp_path):
    assert has_auth(
        tmp_path,
        """\
        @router.post("/items")
        def create(session_id: str = Cookie()):
            return {}
        """,
    )


def test_public_path_segment_is_not_reported(tmp_path):
    assert has_auth(
        tmp_path,
        """\
        @router.get("/public")
        def info():
            return {}
        """,
    )


def test_plain_unprotected_route_is_still_reported(tmp_path):
    assert not has_auth(
        tmp_path,
        """\
        @router.post("/items")
        def create():
            return {}
        """,
    )
