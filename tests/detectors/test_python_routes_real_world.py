"""False alarms found by scanning 549 real FastAPI projects, each turned into a test.

Every positive case here is a pattern seen in real code, and every negative case checks that
the fix did not become so broad that it hides a real gap.
"""

import textwrap

import pytest
from deviant_scan.detectors import python_routes as pr

HEAD = "from fastapi import APIRouter, Depends, Header, Query, HTTPException, status\n"


def scan(tmp_path, body, head=HEAD):
    source = head + "router = APIRouter()\n" + textwrap.dedent(body)
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    return {i["item_id"]: i["features"] for i in pr.extract(str(tmp_path))}


def has(tmp_path, body, feature):
    return {k: v[feature] for k, v in scan(tmp_path, body).items()}


# --- a response model is declared by a return annotation, a status code or a response class --


def test_a_return_annotation_is_the_response_model(tmp_path):
    result = has(
        tmp_path,
        """
        @router.get("/a")
        def a() -> dict:
            return {}

        @router.get("/b")
        def b():
            return {}

        @router.get("/c", response_model=None)
        def c():
            return {}
        """,
        "has_response_model",
    )
    assert result == {"GET /a": True, "GET /b": False, "GET /c": True}


@pytest.mark.parametrize(
    "decorator",
    [
        '@router.delete("/x", status_code=204)',
        '@router.delete("/x", status_code=status.HTTP_204_NO_CONTENT)',
        '@router.get("/x", response_class=HTMLResponse)',
        '@router.get("/x", response_class=StreamingResponse)',
        '@router.get("/x", include_in_schema=False)',
    ],
)
def test_routes_that_cannot_have_a_response_model_are_not_exceptions(tmp_path, decorator):
    result = has(tmp_path, f"{decorator}\ndef x():\n    return None\n", "has_response_model")
    assert result == {next(iter(result)): True}


def test_a_route_with_nothing_declared_still_lacks_a_response_model(tmp_path):
    assert has(tmp_path, '@router.get("/x")\ndef x():\n    return {}\n', "has_response_model") == {
        "GET /x": False
    }


# --- dependency names -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("get_current_context", True),
        ("get_current_tenant", True),
        ("get_current_active_member", True),
        ("get_current_user", True),
        ("get_current_time", False),
        ("get_current_settings", False),
        ("get_current_version", False),
        ("get_current_page", False),
        ("get_db", False),
    ],
)
def test_get_current_dependencies_are_auth_unless_they_are_plainly_not(name, expected):
    assert pr._is_auth(name, set()) is expected


# --- authentication written as code in the route, not as a dependency -------------------


def test_a_route_that_raises_401_or_403_itself_does_its_own_auth(tmp_path):
    result = has(
        tmp_path,
        """
        @router.post("/a")
        def a(token: str = None):
            if not token:
                raise HTTPException(status_code=401, detail="no")

        @router.post("/b")
        def b():
            raise HTTPException(status.HTTP_403_FORBIDDEN)

        @router.post("/c")
        def c():
            raise HTTPException(status_code=404)

        @router.post("/d")
        def d():
            return {}
        """,
        "has_auth",
    )
    assert result == {"POST /a": True, "POST /b": True, "POST /c": False, "POST /d": False}


def test_a_route_that_calls_a_require_or_verify_function_does_its_own_auth(tmp_path):
    result = has(
        tmp_path,
        """
        @router.post("/a")
        def a(request):
            session = require_setup_access(request)

        @router.post("/b")
        def b(request):
            verify_signature(request)

        @router.post("/c")
        def c(request):
            authenticate(request)

        @router.post("/d")
        def d(request):
            load_data(request)
        """,
        "has_auth",
    )
    assert result == {"POST /a": True, "POST /b": True, "POST /c": True, "POST /d": False}


def test_verifying_a_jwt_or_comparing_a_secret_is_authentication(tmp_path):
    result = has(
        tmp_path,
        """
        @router.post("/a")
        def a(t: str):
            claims = jwt.decode(t, SECRET, algorithms=["HS256"])

        @router.post("/b")
        def b(key: str):
            if not secrets.compare_digest(key, EXPECTED):
                return None

        @router.post("/c")
        def c(key: str):
            hmac.compare_digest(key, EXPECTED)

        @router.post("/d")
        def d(value: str):
            if value == "x":
                return None
        """,
        "has_auth",
    )
    assert result == {"POST /a": True, "POST /b": True, "POST /c": True, "POST /d": False}


# --- credentials passed as a header, cookie or query parameter --------------------------


def test_a_secret_or_key_header_counts_as_auth(tmp_path):
    result = has(
        tmp_path,
        """
        @router.delete("/a")
        def a(x_machine_secret: str = Header(..., alias="X-Machine-Secret")):
            ...

        @router.delete("/b")
        def b(signature: str | None = Header(default=None, alias="X-Beever-Signature")):
            ...

        @router.delete("/c")
        def c(key: str = Header(None, alias="X-Api-Key")):
            ...

        @router.delete("/d")
        def d(token: str = Query(...)):
            ...

        @router.delete("/e")
        def e(user_agent: str = Header(None)):
            ...

        @router.delete("/f")
        def f(page: int = Query(1)):
            ...
        """,
        "has_auth",
    )
    assert result == {
        "DELETE /a": True,
        "DELETE /b": True,
        "DELETE /c": True,
        "DELETE /d": True,
        "DELETE /e": False,
        "DELETE /f": False,
    }


# --- routes that cannot require a session -----------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/login",
        "/auth/login",
        "/auth/logout",
        "/register",
        "/signup",
        "/sign-in",
        "/session",
        "/token",
        "/refresh",
        "/oauth/callback",
        "/health",
        "/healthz",
        "/api/v1/ping",
        "/docs",
        "/openapi.json",
    ],
)
def test_login_and_health_routes_cannot_require_auth(tmp_path, path):
    result = has(tmp_path, f'@router.post("{path}")\ndef x():\n    return 1\n', "has_auth")
    assert list(result.values()) == [True]


@pytest.mark.parametrize(
    "path", ["/users", "/login-history", "/users/{id}", "/admin/health-report", "/loginas"]
)
def test_other_routes_are_not_exempt_just_because_a_word_appears_in_the_path(tmp_path, path):
    result = has(tmp_path, f'@router.post("{path}")\ndef x():\n    return 1\n', "has_auth")
    assert list(result.values()) == [False]


# --- the author said so -----------------------------------------------------------------


@pytest.mark.parametrize(
    "docstring",
    [
        "Public data, no authentication needed.",
        "Intentionally unauthenticated: the page may not be signed in yet.",
        "Anonymous access is fine here.",
        "Open to everyone, no auth.",
        "获取主要市场指数（公共数据，无需认证）",
    ],
)
def test_a_docstring_that_says_the_route_is_public_is_taken_at_its_word(tmp_path, docstring):
    body = f'@router.get("/data")\ndef data():\n    """{docstring}"""\n    return 1\n'
    assert list(has(tmp_path, body, "has_auth").values()) == [True]


def test_a_comment_above_the_route_that_says_it_is_public_counts(tmp_path):
    body = '# public endpoint: no auth on purpose\n@router.get("/data")\ndef data(): ...\n'
    assert list(has(tmp_path, body, "has_auth").values()) == [True]


@pytest.mark.parametrize(
    "docstring",
    [
        "Return the public profile of a user.",
        "List all users.",
        "Publicly visible fields are returned.",
        "Requires authentication.",
        "Not public.",
    ],
)
def test_words_that_merely_contain_public_do_not_exempt_a_route(tmp_path, docstring):
    body = f'@router.get("/data")\ndef data():\n    """{docstring}"""\n    return 1\n'
    assert list(has(tmp_path, body, "has_auth").values()) == [False]


def test_a_declaration_of_publicness_far_from_the_route_does_not_count(tmp_path):
    body = (
        "# this file serves public data, no authentication needed\n"
        + "x = 1\n" * 12
        + '@router.get("/data")\ndef data():\n    return 1\n'
    )
    assert list(has(tmp_path, body, "has_auth").values()) == [False]


def test_the_real_gap_is_still_reported_next_to_all_of_these(tmp_path):
    """One route with no protection and no reason, among routes that have each kind of reason."""
    result = has(
        tmp_path,
        """
        @router.get("/a")
        def a(user=Depends(get_current_user)): ...

        @router.get("/b")
        def b(user=Depends(get_current_context)): ...

        @router.post("/login")
        def login(): ...

        @router.get("/c")
        def c(x_api_key: str = Header(None)): ...

        @router.get("/orders")
        def orders():
            return []
        """,
        "has_auth",
    )
    assert result["GET /orders"] is False
    assert [k for k, v in result.items() if not v] == ["GET /orders"]


# --- auth done by a helper the route calls ----------------------------------------------


def test_a_route_that_calls_a_helper_which_checks_credentials_is_guarded(tmp_path):
    result = has(
        tmp_path,
        """
        def _account_for(request):
            if request.headers.get("x") != "ok":
                raise HTTPException(status_code=401)
            return 1

        def _lookup(request):
            return 1

        @router.post("/a")
        def a(request):
            account = _account_for(request)

        @router.post("/b")
        def b(request):
            account = _lookup(request)
        """,
        "has_auth",
    )
    assert result == {"POST /a": True, "POST /b": False}


def test_a_dependency_factory_called_in_the_route_counts(tmp_path):
    result = has(
        tmp_path,
        """
        from typing import Annotated

        @router.post("/a", dependencies=[UserInterfaceAuthDependency("job:edit")])
        def a(): ...

        @router.post("/b")
        def b(user: Annotated[User, CurrentUserDependency()]): ...

        @router.post("/c")
        def c(db: Annotated[Session, DBSessionDependency()]): ...
        """,
        "has_auth",
    )
    assert result == {"POST /a": True, "POST /b": True, "POST /c": False}


def test_a_helper_name_shared_with_a_function_that_checks_nothing_is_not_trusted(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "helpers/a.py": """
            def check(request):
                raise HTTPException(status_code=401)
            """,
            "helpers/b.py": """
            def check(request):
                return 1
            """,
            "routes.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/a")
            def a(request):
                check(request)
            """,
        },
    )
    assert result == {"POST /a": False}


def test_a_helper_name_defined_twice_that_always_checks_credentials_is_trusted(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "helpers/a.py": """
            def check(request):
                raise HTTPException(status_code=401)
            """,
            "helpers/b.py": """
            def check(request):
                raise HTTPException(status_code=403)
            """,
            "routes.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/a")
            def a(request):
                check(request)
            """,
        },
    )
    assert result == {"POST /a": True}


def test_a_router_stored_on_self_is_followed_and_classes_do_not_mix(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends
            from app.auth import get_current_user

            class Users:
                def __init__(self):
                    self.router = APIRouter(dependencies=[Depends(get_current_user)])
                    self.router.add_api_route("/a", self.a, methods=["POST"])

                def a(self): ...

            class Open:
                def __init__(self):
                    self.router = APIRouter()

                def routes(self):
                    @self.router.post("/b")
                    def b(): ...
            """
        },
    )
    assert result == {"POST /a": True, "POST /b": False}


def auth_in_project(tmp_path, files):
    import textwrap

    for relative, source in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(source), encoding="utf-8")
    items = pr.extract(str(tmp_path))
    return {i["item_id"]: i["features"]["has_auth"] for i in items}


def test_a_route_handler_named_like_the_manager_method_it_calls_still_counts_as_guarded(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "manager.py": """
            class Manager:
                async def reset_password(self, token):
                    jwt.decode(token)
            """,
            "router.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/reset-password")
            async def reset_password(token: str, manager):
                await manager.reset_password(token)
            """,
        },
    )
    assert result == {"POST /reset-password": True}


def test_a_fastapi_security_scheme_counts_as_auth_whatever_the_variable_is_called(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "a.py": """
            from fastapi import Depends, FastAPI
            from fastapi.security import HTTPBasic, HTTPBearer

            app = FastAPI()
            security = HTTPBasic()

            @app.get("/basic")
            def basic(credentials=Depends(security)): ...

            @app.get("/bearer")
            def bearer(credentials=Depends(HTTPBearer())): ...

            @app.get("/open")
            def open_route(): ...
            """
        },
    )
    assert result == {"GET /basic": True, "GET /bearer": True, "GET /open": False}


def test_account_recovery_and_oauth_routes_are_public_by_nature(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter
            router = APIRouter()

            @router.post("/forgot-password")
            def forgot(): ...

            @router.post("/reset-password")
            def reset(): ...

            @router.post("/request-verify-token")
            def request_verify(): ...

            @router.get("/authorize")
            def authorize(): ...

            @router.get("/orders")
            def orders(): ...
            """
        },
    )
    assert result == {
        "POST /forgot-password": True,
        "POST /reset-password": True,
        "POST /request-verify-token": True,
        "GET /authorize": True,
        "GET /orders": False,
    }


def test_routes_inside_a_tests_folder_are_not_scanned(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "tests/test_app.py": """
            from fastapi import FastAPI
            app = FastAPI()

            @app.delete("/users/me")
            def delete_me(): ...
            """,
            "app/main.py": """
            from fastapi import FastAPI
            app = FastAPI()

            @app.get("/real")
            def real(): ...
            """,
        },
    )
    assert result == {"GET /real": False}


def test_a_validate_session_or_identity_dependency_is_auth_but_a_plain_validator_is_not(tmp_path):
    result = auth_in_project(
        tmp_path,
        {
            "a.py": """
            from fastapi import APIRouter, Depends

            guard = [Depends(validate_dashboard_session)]
            router = APIRouter(prefix="/api/accounts", dependencies=guard)

            @router.get("/list")
            def listing(): ...

            open_router = APIRouter()

            @open_router.get("/usage")
            def usage(api_key=Depends(validate_provider_usage_identity)): ...

            @open_router.get("/page")
            def page(p=Depends(validate_pagination)): ...
            """
        },
    )
    assert result == {"GET /list": True, "GET /usage": True, "GET /page": False}
