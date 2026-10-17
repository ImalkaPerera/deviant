import sys
from pathlib import Path

import pytest
import python_routes as pr

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "python_routes"


def items_for(case):
    return {i["item_id"]: i for i in pr.extract(str(FIXTURES / case))}


def features_for(case, item_id):
    return items_for(case)[item_id]["features"]


def test_route_level_and_param_auth_basic_case():
    assert features_for("basic", "GET /users") == {
        "is_mutating": False,
        "has_auth": False,
        "has_response_model": False,
        "has_rate_limit": False,
    }
    post = features_for("basic", "POST /users")
    assert post["is_mutating"] and post["has_auth"] and post["has_response_model"]
    delete = features_for("basic", "DELETE /users/{user_id}")
    assert delete["is_mutating"] and not delete["has_auth"]


def test_router_level_dependencies_cover_every_route():
    assert features_for("router_level", "POST /items")["has_auth"]
    assert features_for("router_level", "GET /items")["has_auth"]


def test_include_router_dependencies_in_another_file_are_followed():
    item = items_for("include_level")["PUT /reports/{report_id}"]
    assert item["file"] == "app/routes/reports.py"
    assert item["features"]["has_auth"]
    assert features_for("include_level", "GET /reports")["has_auth"]


def test_app_level_dependencies_cover_routes_on_app():
    assert features_for("app_level", "POST /orders")["has_auth"]


def test_security_and_annotated_depends_count_as_auth():
    assert features_for("security_and_annotated", "POST /invoices")["has_auth"]
    assert features_for("security_and_annotated", "PATCH /invoices/{invoice_id}")["has_auth"]


def test_non_auth_dependencies_do_not_count_as_auth():
    feedback = features_for("non_auth", "POST /feedback")
    assert not feedback["has_auth"]
    assert feedback["has_rate_limit"]
    health = features_for("non_auth", "GET /health")
    assert not health["has_auth"] and not health["has_rate_limit"]


def test_broken_files_and_skipped_folders_are_ignored_without_crashing():
    assert pr.extract(str(FIXTURES / "broken")) == []


def test_item_shape_matches_the_data_contract():
    item = items_for("basic")["POST /users"]
    assert item["detector"] == "python_routes"
    # Routes are compared within their own folder, so the peer group names that folder.
    assert item["peer_group"] == "fastapi_routes:app/routes"
    assert item["file"] == "app/routes/users.py"
    assert item["line"] == 14
    assert item["context"]["function_name"] == "create_user"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("get_current_user", True),
        ("verify_token", True),
        ("require_admin", True),
        ("check_permission", True),
        ("get_authors", False),  # "auth" inside "authors" must not match
        ("get_db", False),
    ],
)
def test_auth_names_match_whole_words(name, expected):
    assert pr._is_auth(name, set()) is expected


def test_user_can_add_auth_words():
    assert pr._is_auth("check_tenant_access", {"tenant_access"})
    assert not pr._is_auth("check_tenant_access", set())


def test_pagination_limit_is_not_a_rate_limit():
    assert not pr._is_rate("limit_offset")
    assert pr._is_rate("rate_limiter")
    assert pr._is_rate("limiter.limit")


def test_annotated_aliases_imported_from_another_module_count_as_auth():
    items = items_for("template_style")
    assert items["POST /"]["features"]["has_auth"]  # current_user: CurrentUser
    assert items["PUT /{item_id}"]["features"]["has_auth"]  # deps.CurrentUser
    assert items["DELETE /{item_id}"]["features"]["has_auth"]  # get_current_active_superuser


def test_alias_without_auth_does_not_count_as_auth():
    assert not features_for("template_style", "POST /public")["has_auth"]  # SessionDep only


def test_router_declared_with_a_type_annotation_is_found():
    assert items_for("template_style")["POST /"]["file"] == "app/api/routes/items.py"


def test_auth_on_an_outer_router_reaches_routes_on_nested_routers():
    # create_app() -> application.include_router(api_router, deps) -> api_router -> admin.router
    assert features_for("nested_routers", "PUT /settings")["has_auth"]


def test_app_level_dependencies_reach_included_routers():
    assert features_for("nested_routers", "POST /reports")["has_auth"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("oauth2_scheme", True),
        ("reusable_oauth2", True),
        ("JWTBearer", True),
        ("HTTPBearer", True),
        ("APIKeyHeader", True),
        ("GetCurrentUser", True),
        ("get_current_active_user", True),
        ("get_current_active_superuser", True),
        ("get_authenticated_user", True),
        ("check_permissions", True),
        ("get_session", False),
        ("get_current_time", False),
        ("limit_offset", False),
    ],
)
def test_auth_names_cover_common_fastapi_styles(name, expected):
    assert pr._is_auth(name, set()) is expected


def test_file_with_utf8_bom_is_parsed(tmp_path):
    source = (FIXTURES / "basic" / "app" / "routes" / "users.py").read_bytes()
    (tmp_path / "users.py").write_bytes(b"\xef\xbb\xbf" + source)
    assert {i["item_id"] for i in pr.extract(str(tmp_path))} == {
        "GET /users",
        "POST /users",
        "DELETE /users/{user_id}",
    }


def test_unparseable_files_are_reported_on_stderr(capsys):
    pr.extract(str(FIXTURES / "broken"))
    assert "could not parse 1 file(s)" in capsys.readouterr().err


def test_auth_subject_type_counts_as_auth_even_without_an_auth_named_dependency():
    assert features_for("auth_types", "POST /me/payment")["has_auth"]
    assert not features_for("auth_types", "POST /public/hook")["has_auth"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Authenticator", True),
        ("WebUserAuthorizer", True),
        ("OrgPolicyGuard", True),
        ("oidc_scheme", True),
        ("_web_user", True),
    ],
)
def test_auth_dependency_names_seen_in_real_projects(name, expected):
    assert pr._is_auth(name, set()) is expected


@pytest.mark.parametrize(("name", "expected"), [("AuthSubject", True), ("TokenCreate", False)])
def test_auth_type_names_are_strict(name, expected):
    assert pr._matches_auth_type(name) is expected


def test_jinja_templates_are_skipped_without_a_warning(tmp_path, capsys):
    (tmp_path / "gen.py").write_text("from {{ module }} import x\n{% for a in b %}\n")
    assert pr.extract(str(tmp_path)) == []
    assert capsys.readouterr().err == ""


@pytest.mark.skipif(sys.version_info < (3, 12), reason="`type` statements need Python 3.12")
def test_type_statement_aliases_count_as_dependency_aliases(tmp_path):
    (tmp_path / "r.py").write_text(
        "from typing import Annotated\n"
        "from fastapi import APIRouter, Depends\n"
        "from app.auth import get_current_user\n"
        "type CurrentUser = Annotated[dict, Depends(get_current_user)]\n"
        "router = APIRouter()\n"
        "@router.post('/x')\n"
        "def x(user: CurrentUser):\n    return {}\n"
    )
    assert pr.extract(str(tmp_path))[0]["features"]["has_auth"]


def test_a_hostile_nested_file_does_not_stop_the_other_files(tmp_path):
    (tmp_path / "nest.py").write_text("x = " + "[" * 200000 + "]" * 200000 + "\n")
    (tmp_path / "ok.py").write_text(
        "from fastapi import APIRouter\nrouter = APIRouter()\n@router.post('/a')\ndef a(): pass\n"
    )
    assert [i["item_id"] for i in pr.extract(str(tmp_path))] == ["POST /a"]
