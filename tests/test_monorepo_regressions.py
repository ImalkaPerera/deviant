"""Regression tests: a monorepo with the same package name in two services resolves imports
to the service that owns the importing file."""

import textwrap

from deviant_scan.detectors import python_routes as pr

AUTH_WITH_ALIAS = """\
from typing import Annotated
from fastapi import Depends


def get_current_user():
    return {}


CurrentUser = Annotated[dict, Depends(get_current_user)]
"""

AUTH_WITHOUT_ALIAS = """\
def something_else():
    return {}
"""

ROUTES = """\
from fastapi import APIRouter
from app.auth import CurrentUser

router = APIRouter()


@router.post("/items")
def create(user: CurrentUser):
    return {}
"""


def write(root, rel, source):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def test_import_resolves_to_the_services_own_auth_module(tmp_path):
    write(tmp_path, "svc_a/app/auth.py", AUTH_WITH_ALIAS)
    write(tmp_path, "svc_a/app/routes.py", ROUTES)
    write(tmp_path, "svc_b/app/auth.py", AUTH_WITHOUT_ALIAS)

    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "svc_a/app/routes.py"]

    assert len(items) == 1
    assert items[0]["features"]["has_auth"] is True


def test_import_still_resolves_when_only_one_service_has_the_module(tmp_path):
    write(tmp_path, "svc_a/app/auth.py", AUTH_WITH_ALIAS)
    write(tmp_path, "svc_a/app/routes.py", ROUTES)

    items = [i for i in pr.extract(str(tmp_path)) if i["file"] == "svc_a/app/routes.py"]

    assert items[0]["features"]["has_auth"] is True
