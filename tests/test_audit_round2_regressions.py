"""Regression tests for the errors found by the round-two audit of a11210d."""

import textwrap

import pytest
from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr


def write(root, rel, source):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")


def test_handler_defined_inside_a_method_keeps_its_auth(tmp_path):
    write(
        tmp_path,
        "app/routes.py",
        """\
        from fastapi import APIRouter, Depends, Header
        router = APIRouter()

        def verify(authorization: str = Header(...)):
            return authorization

        class Svc:
            def build(self):
                def handler(_=Depends(verify)):
                    return {}
                router.add_api_route("/nested", handler, methods=["DELETE"])
        """,
    )

    items = {
        i["item_id"]: i["features"]["has_auth"]
        for i in pr.extract(str(tmp_path))
        if i["file"] == "app/routes.py"
    }

    assert items == {"DELETE /nested": True}


@pytest.mark.parametrize("value", ["null", "~"])
def test_null_timeout_is_no_limit(tmp_path, value):
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

    assert job["features"]["has_timeout_minutes"] is False
