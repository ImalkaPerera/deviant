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
    assert item["peer_group"] == "fastapi_routes"
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
    assert pr._is_auth("check_api_key", {"api_key"})
    assert not pr._is_auth("check_api_key", set())
