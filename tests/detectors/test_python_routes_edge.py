"""Edge cases for the FastAPI routes detector, each built as a tiny project."""

import sys
import textwrap

import pytest
from deviant_scan.detectors import python_routes as pr


def project(tmp_path, files):
    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    return tmp_path


def features(tmp_path, files):
    """{item_id: features} for a project. Item ids must be unique within the project."""
    items = pr.extract(str(project(tmp_path, files)))
    by_id = {i["item_id"]: i["features"] for i in items}
    assert len(by_id) == len(items), "test project has duplicate item ids"
    return by_id


def auth(tmp_path, files):
    return {k: v["has_auth"] for k, v in features(tmp_path, files).items()}


# --- routers created inside functions -----------------------------------------------------


def test_two_factory_functions_each_with_their_own_router(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            def build_public():
                router = APIRouter()

                @router.post("/open")
                def open_route():
                    return {}

                return router

            def build_private():
                router = APIRouter(dependencies=[Depends(get_current_user)])

                @router.post("/closed")
                def closed_route():
                    return {}

                return router
            """
        },
    )
    assert result == {"POST /open": False, "POST /closed": True}


def test_a_route_registered_in_an_inner_function_uses_the_outer_router(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import verify_token

            def make():
                router = APIRouter(dependencies=[Depends(verify_token)])

                def register():
                    @router.get("/x")
                    def x():
                        return {}

                register()
                return router
            """
        },
    )
    assert result == {"GET /x": True}


def test_include_router_inside_a_factory_function(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends, FastAPI
            from app.auth import get_current_user

            def create_app():
                app = FastAPI()
                r = APIRouter()

                @r.post("/x")
                def x():
                    return {}

                app.include_router(r, dependencies=[Depends(get_current_user)])
                return app
            """
        },
    )
    assert result == {"POST /x": True}


def test_a_module_router_is_shadowed_by_a_local_one_inside_a_function(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter(dependencies=[Depends(get_current_user)])

            @router.get("/module")
            def module_route():
                return {}

            def other():
                router = APIRouter()

                @router.get("/local")
                def local_route():
                    return {}
            """
        },
    )
    assert result == {"GET /module": True, "GET /local": False}


# --- finding routers and dependencies across modules --------------------------------------


def test_plain_import_with_a_deep_dotted_reference(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/routes/items.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/items")
            def create():
                return {}
            """,
            "main.py": """
            import app.routes.items
            from fastapi import Depends, FastAPI
            from app.auth import get_current_user

            main_app = FastAPI()
            main_app.include_router(
                app.routes.items.router, dependencies=[Depends(get_current_user)]
            )
            """,
        },
    )
    assert result == {"POST /items": True}


def test_import_as_alias_and_package_attribute_chain(tmp_path):
    files = {
        "app/routes/items.py": """
        from fastapi import APIRouter
        router = APIRouter()

        @router.post("/items")
        def create():
            return {}
        """,
        "app/routes/__init__.py": "",
        "app/__init__.py": "",
    }
    for source, expected in (
        ("import app.routes.items as it\nmain.include_router(it.router, dependencies=AUTH)", True),
        (
            "from app import routes\nmain.include_router(routes.items.router, dependencies=AUTH)",
            True,
        ),
        ("from app.routes import items\nmain.include_router(items.router)", False),
    ):
        root = tmp_path / f"case{len(list(tmp_path.iterdir()))}"
        files["main.py"] = (
            "from fastapi import Depends, FastAPI\n"
            "from app.auth import get_current_user\n"
            "AUTH = [Depends(get_current_user)]\n"
            "main = FastAPI()\n" + source + "\n"
        )
        assert auth(root, files) == {"POST /items": expected}


def test_dependency_alias_re_exported_through_a_package(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/deps/current.py": """
            from typing import Annotated
            from fastapi import Depends
            from app.auth import get_current_user

            CurrentUser = Annotated[dict, Depends(get_current_user)]
            """,
            "app/deps/__init__.py": "from .current import CurrentUser\n",
            "app/routes.py": """
            from fastapi import APIRouter
            from app.deps import CurrentUser

            router = APIRouter()

            @router.post("/x")
            def x(user: CurrentUser):
                return {}
            """,
        },
    )
    assert result == {"POST /x": True}


def test_a_router_imported_from_another_module_is_still_a_router(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/base.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter(dependencies=[Depends(get_current_user)])
            """,
            "app/users.py": """
            from app.base import router

            @router.get("/users")
            def users():
                return []
            """,
        },
    )
    assert result == {"GET /users": True}


def test_imports_inside_functions_are_followed(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/routes/users.py": """
            from fastapi import APIRouter

            router = APIRouter()

            @router.post("/users")
            def create():
                return {}
            """,
            "main.py": """
            from fastapi import Depends, FastAPI
            from app.auth import get_current_user

            def create_app():
                from app.routes import users

                app = FastAPI()
                app.include_router(users.router, dependencies=[Depends(get_current_user)])
                return app
            """,
        },
    )
    assert result == {"POST /users": True}


def test_imports_under_type_checking_blocks_are_followed(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/deps.py": """
            from typing import Annotated
            from fastapi import Depends
            from app.auth import get_current_user

            CurrentUser = Annotated[dict, Depends(get_current_user)]
            """,
            "app/routes.py": """
            from typing import TYPE_CHECKING
            from fastapi import APIRouter

            if TYPE_CHECKING:
                from app.deps import CurrentUser

            router = APIRouter()

            @router.post("/x")
            def x(user: "CurrentUser"):
                return {}
            """,
        },
    )
    assert result == {"POST /x": True}


# --- dependencies kept in variables -------------------------------------------------------


def test_dependency_list_stored_in_a_variable(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            AUTH = [Depends(get_current_user)]
            router = APIRouter(dependencies=AUTH)

            @router.get("/a")
            def a():
                return {}
            """
        },
    )
    assert result == {"GET /a": True}


def test_route_level_dependency_list_in_a_variable_and_a_single_depends_default(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            AUTH = (Depends(get_current_user),)
            USER = Depends(get_current_user)
            router = APIRouter()

            @router.get("/a", dependencies=AUTH)
            def a():
                return {}

            @router.get("/b")
            def b(user=USER):
                return {}

            @router.get("/c")
            def c():
                return {}
            """
        },
    )
    assert result == {"GET /a": True, "GET /b": True, "GET /c": False}


def test_dependency_variable_imported_from_another_module(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/security.py": """
            from fastapi import Depends
            from app.auth import verify_token

            PROTECTED = [Depends(verify_token)]
            """,
            "app/routes.py": """
            from fastapi import APIRouter
            from app.security import PROTECTED

            router = APIRouter(dependencies=PROTECTED)

            @router.get("/a")
            def a():
                return {}
            """,
        },
    )
    assert result == {"GET /a": True}


def test_a_variable_that_is_not_a_dependency_is_ignored(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.db import get_db

            TAGS = ["items"]
            DEPS = [Depends(get_db)]
            router = APIRouter(dependencies=DEPS, tags=TAGS)

            @router.get("/a")
            def a():
                return {}
            """
        },
    )
    assert result == {"GET /a": False}


def test_a_self_referencing_variable_does_not_loop_forever(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter

            A = B
            B = A
            router = APIRouter(dependencies=A)

            @router.get("/a")
            def a():
                return {}
            """
        },
    )
    assert result == {"GET /a": False}


# --- other ways of declaring routes -------------------------------------------------------


def test_add_api_route_and_api_route(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter()

            def handler_a():
                return {}

            def handler_b(user=Depends(get_current_user)):
                return {}

            router.add_api_route("/a", handler_a, methods=["POST"],
                                 dependencies=[Depends(get_current_user)])
            router.add_api_route("/b", handler_b, methods=["POST"])
            router.add_api_route("/open", handler_a, methods=["POST"])

            @router.api_route("/c", methods=["GET", "POST"])
            def c(user=Depends(get_current_user)):
                return {}
            """
        },
    )
    assert result == {
        "POST /a": True,
        "POST /b": True,
        "POST /open": False,
        "GET /c": True,
        "POST /c": True,
    }


def test_add_api_route_defaults_to_get_and_reads_the_endpoint_keyword(tmp_path):
    items = pr.extract(
        str(
            project(
                tmp_path,
                {
                    "a.py": """
                    from fastapi import APIRouter
                    router = APIRouter()

                    def handler():
                        return {}

                    router.add_api_route("/x", endpoint=handler, response_model=dict)
                    """
                },
            )
        )
    )
    assert [(i["item_id"], i["features"]["is_mutating"]) for i in items] == [("GET /x", False)]
    assert items[0]["features"]["has_response_model"] is True


def test_head_options_and_trace_routes_are_not_mutating(tmp_path):
    result = features(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.head("/h")
            def h(): ...

            @router.options("/o")
            def o(): ...

            @router.trace("/t")
            def t(): ...
            """
        },
    )
    assert set(result) == {"HEAD /h", "OPTIONS /o", "TRACE /t"}
    assert not any(f["is_mutating"] for f in result.values())


def test_dynamic_and_formatted_paths(tmp_path):
    items = pr.extract(
        str(
            project(
                tmp_path,
                {
                    "a.py": """
                    from fastapi import APIRouter
                    router = APIRouter()
                    PREFIX = "/x"

                    @router.get(PREFIX + "/a")
                    def a(): ...

                    @router.get(f"{PREFIX}/b")
                    def b(): ...
                    """
                },
            )
        )
    )
    assert [i["item_id"] for i in items] == ["GET <dynamic>", "GET <dynamic>"]
    assert sorted(i["line"] for i in items) == [7, 10]  # the def lines, below their decorators


# --- naming variations --------------------------------------------------------------------


def test_depends_and_apirouter_imported_under_other_names(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter as Router, Depends as D, Security as S
            from app.auth import get_current_user, verify_scope

            router = Router(dependencies=[D(get_current_user)])

            @router.get("/a")
            def a():
                return {}

            plain = Router()

            @plain.get("/b")
            def b(scope=S(verify_scope)):
                return {}

            @plain.get("/c")
            def c():
                return {}
            """
        },
    )
    assert result == {"GET /a": True, "GET /b": True, "GET /c": False}


def test_fastapi_module_attribute_style(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            import fastapi
            from app.auth import get_current_user

            router = fastapi.APIRouter(dependencies=[fastapi.Depends(get_current_user)])

            @router.get("/a")
            def a():
                return {}
            """
        },
    )
    assert result == {"GET /a": True}


def test_a_subclass_of_apirouter_is_a_router(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/routing.py": """
            from fastapi import APIRouter

            class BaseRouter(APIRouter):
                pass

            class MyRouter(BaseRouter):
                pass
            """,
            "app/routes.py": """
            from fastapi import Depends
            from app.auth import get_current_user
            from app.routing import MyRouter

            router = MyRouter(dependencies=[Depends(get_current_user)])
            open_router = MyRouter()

            @router.get("/a")
            def a(): ...

            @open_router.get("/b")
            def b(): ...
            """,
        },
    )
    assert result == {"GET /a": True, "GET /b": False}


def test_depends_with_the_dependency_keyword(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter()

            @router.get("/a")
            def a(user=Depends(dependency=get_current_user)):
                return {}
            """
        },
    )
    assert result == {"GET /a": True}


def test_string_annotations_are_read(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from typing import Annotated
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter()
            Current = Annotated[dict, Depends(get_current_user)]

            @router.get("/a")
            def a(user: "Current"):
                return {}

            @router.get("/b")
            def b(user: "Annotated[dict, Depends(get_current_user)]"):
                return {}

            @router.get("/c")
            def c(user: "not valid python ("):
                return {}
            """
        },
    )
    assert result == {"GET /a": True, "GET /b": True, "GET /c": False}


def test_future_annotations_import_does_not_change_results(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from __future__ import annotations
            from typing import Annotated
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter()
            Current = Annotated[dict, Depends(get_current_user)]

            @router.get("/a")
            def a(user: Current):
                return {}
            """
        },
    )
    assert result == {"GET /a": True}


def test_async_routes_and_methods_inside_classes(tmp_path):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter()

            @router.get("/a")
            async def a(user=Depends(get_current_user)):
                return {}

            class Views:
                @router.get("/b")
                async def b(self):
                    return {}
            """
        },
    )
    assert result == {"GET /a": True, "GET /b": False}


# --- files and syntax ---------------------------------------------------------------------


def test_python_314_except_without_parentheses_is_read_on_any_version(tmp_path, capsys):
    result = auth(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            router = APIRouter()

            def risky():
                try:
                    return 1
                except ValueError, TypeError:
                    return 2

            @router.get("/a")
            def a(user=Depends(get_current_user)):
                return {}
            """
        },
    )
    assert result == {"GET /a": True}
    assert capsys.readouterr().err == ""


def test_a_real_syntax_error_is_still_reported(tmp_path, capsys):
    project(tmp_path, {"bad.py": "def broken(:\n    pass\n"})
    assert pr.extract(str(tmp_path)) == []
    assert "could not parse 1 file" in capsys.readouterr().err


def test_python_2_style_code_is_reported_not_crashed(tmp_path, capsys):
    project(tmp_path, {"old.py": "print 'hello'\nexcept_this = 1\n"})
    assert pr.extract(str(tmp_path)) == []
    assert "could not parse" in capsys.readouterr().err


def test_an_empty_project_and_a_project_without_routes(tmp_path):
    assert pr.extract(str(tmp_path)) == []
    project(tmp_path, {"a.py": "x = 1\n", "b/__init__.py": ""})
    assert pr.extract(str(tmp_path)) == []


def test_vendored_environments_are_skipped(tmp_path):
    result = features(
        tmp_path,
        {
            "site-packages/lib/r.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/vendored")
            def v(): ...
            """,
            ".nox/py/r.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/nox")
            def v(): ...
            """,
            "real.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.get("/real")
            def v(): ...
            """,
        },
    )
    assert set(result) == {"GET /real"}


@pytest.mark.skipif(sys.version_info < (3, 12), reason="`type` statements need Python 3.12")
def test_type_statement_alias_through_an_import(tmp_path):
    result = auth(
        tmp_path,
        {
            "app/deps.py": """
            from typing import Annotated
            from fastapi import Depends
            from app.auth import get_current_user

            type CurrentUser = Annotated[dict, Depends(get_current_user)]
            """,
            "app/routes.py": """
            from fastapi import APIRouter
            from app.deps import CurrentUser

            router = APIRouter()

            @router.post("/x")
            def x(user: CurrentUser):
                return {}
            """,
        },
    )
    assert result == {"POST /x": True}


def test_methods_given_as_a_variable_are_not_guessed(tmp_path):
    items = pr.extract(
        str(
            project(
                tmp_path,
                {
                    "a.py": """
                    from fastapi import APIRouter
                    router = APIRouter()
                    METHOD = "POST"

                    @router.api_route("/x", methods=[METHOD])
                    def x(): ...

                    @router.api_route("/y", methods=["get", "POST"])
                    def y(): ...

                    @router.api_route("/z")
                    def z(): ...
                    """
                },
            )
        )
    )
    assert sorted(i["item_id"] for i in items) == ["ANY /x", "GET /y", "GET /z", "POST /y"]
    assert not {i["item_id"]: i["features"]["is_mutating"] for i in items}["ANY /x"]


def test_routes_in_statements_nested_in_blocks_are_found(tmp_path):
    items = pr.extract(
        str(
            project(
                tmp_path,
                {
                    "a.py": """
                    import os
                    from fastapi import APIRouter, Depends
                    from app.auth import get_current_user

                    router = APIRouter(dependencies=[Depends(get_current_user)])

                    if os.environ.get("DEBUG"):
                        @router.get("/debug")
                        def debug(): ...
                    else:
                        @router.get("/prod")
                        def prod(): ...

                    try:
                        @router.get("/try")
                        def a(): ...
                    except Exception:
                        @router.get("/except")
                        def b(): ...
                    finally:
                        @router.get("/finally")
                        def c(): ...

                    with open("f") as handle:
                        @router.get("/with")
                        def d(): ...

                    for _ in range(1):
                        @router.get("/for")
                        def e(): ...
                    """
                },
            )
        )
    )
    assert sorted(i["item_id"] for i in items) == sorted(
        f"GET /{name}" for name in ("debug", "prod", "try", "except", "finally", "with", "for")
    )
    assert all(i["features"]["has_auth"] for i in items)


def test_a_route_reports_the_span_from_its_first_decorator_to_its_def(tmp_path):
    items = pr.extract(
        str(
            project(
                tmp_path,
                {
                    "a.py": """
                    from fastapi import APIRouter
                    router = APIRouter()

                    @router.get(
                        '/a',
                        summary='x',
                    )
                    async def a():
                        return 1
                    """
                },
            )
        )
    )
    (item,) = items
    assert item["span"] == [5, 9] and item["line"] == 9
