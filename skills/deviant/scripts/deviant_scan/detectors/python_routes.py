"""Detector for FastAPI routes: auth, rate limits, response models, and mutation.

Reads Python source with the ast module only. Never imports or runs project code.

Auth can come from the route, its parameters, its router, any include_router call that
adds the router to the app, or the FastAPI app itself. Those levels are followed across
files by module name, through imports, re-exports, aliases such as
`CurrentUser = Annotated[User, Depends(get_current_user)]`, and dependency lists kept in
variables. Routers may be created inside functions; each function has its own scope.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

DETECTOR = "python_routes"
PEER_GROUP = "fastapi_routes"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ROUTER_CALLS = {"APIRouter", "FastAPI"}
DEPENDENCY_CALLS = {"Depends", "Security"}
FASTAPI_PACKAGES = {"fastapi", "starlette"}
# Whole words that mark an auth dependency. Inflections are listed because matching
# is by whole word, so "auth" must not match "authors".
AUTH_WORDS = {
    "auth",
    "authn",
    "authz",
    "authenticate",
    "authenticated",
    "authentication",
    "authorize",
    "authorized",
    "authorization",
    "token",
    "verify",
    "verified",
    "require",
    "requires",
    "required",
    "permission",
    "permissions",
    "admin",
    "superuser",
    "oauth",
    "oauth2",
    "oidc",
    "jwt",
    "bearer",
    "login",
    "credentials",
    "authenticator",
    "authorizer",
    "guard",
    "scheme",
    "current_user",
    "api_key",
    "apikey",
}
# Type names that mark an auth subject, as in `subject: AuthSubject[User]`. Stricter than
# AUTH_WORDS on purpose: a type called TokenCreate is a request body, not auth.
AUTH_TYPE_WORDS = {
    "auth",
    "authn",
    "authz",
    "authenticate",
    "authenticated",
    "authenticator",
    "authentication",
    "authorize",
    "authorized",
    "authorizer",
    "authorization",
}
# Words that make a name auth when they appear together, as in get_current_active_user.
AUTH_WORD_PAIRS = {("current", "user"), ("web", "user")}
# "limit" is left out on purpose: pagination dependencies such as limit_offset are not rate limits.
RATE_WORDS = {"rate", "ratelimit", "limiter", "throttle"}
MAX_BYTES = 1_000_000
MAX_FOLLOW_DEPTH = 5
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "site-packages",
    "__pycache__",
    ".tox",
    ".nox",
    ".eggs",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}


def extract(repo_root: str) -> list[dict]:
    root = Path(repo_root).resolve()
    extra_auth = _extra_auth_words(root)
    trees, sources = _parse_files(root)
    found = {rel: _collect(tree) for rel, tree in trees.items()}
    symbols = _Symbols(trees, found)
    items = []
    for rel, info in found.items():
        items.extend(_routes_in_file(rel, info, symbols, extra_auth, sources[rel]))
    return items


def _extra_auth_words(root: Path) -> set[str]:
    """Words the user adds in .deviant/config.json under "auth_words"."""
    path = root / ".deviant" / "config.json"
    try:
        if path.is_symlink() or path.stat().st_size > MAX_BYTES:
            return set()
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    words = config.get("auth_words", []) if isinstance(config, dict) else []
    return {_normalise(w) for w in words if isinstance(w, str) and w.strip()}


# --- reading files ------------------------------------------------------------------------


def _parse_files(root: Path) -> tuple[dict[str, ast.Module], dict[str, list[str]]]:
    """(syntax trees, source lines) of every readable Python file, keyed by relative path."""
    trees = {}
    sources = {}
    failed = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                    continue
                source = path.read_bytes()
            except OSError:
                continue
            tree = _parse(source, rel)
            if tree is not None:
                trees[rel] = tree
                sources[rel] = source.decode("utf-8", errors="replace").splitlines()
            elif not _looks_like_template(source):
                failed.append(rel)
    if failed:
        # A skipped file can hide the auth helpers other files import, so say so.
        version = ".".join(map(str, sys.version_info[:2]))
        shown = ", ".join(failed[:3]) + (" ..." if len(failed) > 3 else "")
        print(
            f"python_routes: could not parse {len(failed)} file(s) with Python {version}: "
            f"{shown}. They have a syntax error or use syntax newer than this Python; "
            "results that depend on them can be wrong.",
            file=sys.stderr,
        )
    return trees, sources


# Python 3.14 allows `except A, B:` without parentheses. Older versions reject it, so a
# file that fails to parse is retried with the parentheses added.
_BARE_EXCEPT = re.compile(r"^(\s*except\s+)([^()#:\n]+,[^()#:\n]+?)(\s*:)", re.MULTILINE)


def _add_except_parentheses(match: re.Match) -> str:
    if re.search(r"\bas\b", match.group(2)):
        return match.group(0)
    return f"{match.group(1)}({match.group(2)}){match.group(3)}"


def _parse(source: bytes, filename: str) -> ast.Module | None:
    """Parse a file, or None if it cannot be parsed.

    Parsing bytes lets Python handle a byte order mark and a coding comment itself.
    """
    try:
        return ast.parse(source, filename=filename)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        pass
    try:
        text = source.decode("utf-8")
    except UnicodeDecodeError:
        return None
    patched = _BARE_EXCEPT.sub(_add_except_parentheses, text)
    if patched == text:
        return None
    try:
        return ast.parse(patched, filename=filename)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None


def _looks_like_template(source: bytes) -> bool:
    """Jinja and similar templates are not Python until rendered; skip them without a warning."""
    head = source[:20_000]
    return b"{%" in head or b"{{" in head


def _module_name(rel: str) -> str:
    parts = rel[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_index(files) -> dict[str, str | None]:
    """Map every dotted suffix of a module name to its file. Ambiguous suffixes map to None."""
    index: dict[str, str | None] = {}
    for rel in files:
        segments = _module_name(rel).split(".")
        for i in range(len(segments)):
            key = ".".join(segments[i:])
            if key in index and index[key] != rel:
                index[key] = None
            else:
                index.setdefault(key, rel)
    return index


# --- one pass over each syntax tree -------------------------------------------------------

_ASSIGNMENTS = (ast.Assign, ast.AnnAssign) + ((ast.TypeAlias,) if hasattr(ast, "TypeAlias") else ())


class _Found:
    """What one pass over a file's syntax tree finds, so the tree is walked only once.

    A scope is the tuple of ids of the functions enclosing a statement. The module itself
    is the empty tuple.
    """

    def __init__(self):
        self.assigned: list[tuple[tuple, str, ast.expr]] = []
        self.functions: list[tuple[tuple, ast.FunctionDef | ast.AsyncFunctionDef]] = []
        self.classes: list[ast.ClassDef] = []
        self.imports: list[ast.Import | ast.ImportFrom] = []
        self.include_calls: list[tuple[tuple, ast.Call]] = []
        self.api_route_calls: list[tuple[tuple, ast.Call]] = []
        # `self.router = APIRouter()` inside a class: (class id, "self.router", value).
        self.attr_assigned: list[tuple[int, str, ast.expr]] = []
        # The class a function or call sits in, by id of the node, for `self.` lookups.
        self.enclosing_class: dict[int, int] = {}


def _assigned_name(node):
    """(name, value) for `x = value`, `x: T = value` or `type x = value`, else None."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target = node.target
    elif hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
        # `type CurrentUser = Annotated[...]`, Python 3.12 and newer
        return (node.name.id, node.value) if isinstance(node.name, ast.Name) else None
    else:
        return None
    if isinstance(target, ast.Name):
        return target.id, node.value
    return None


# Fields of a statement that hold more statements. Expressions never contain a function,
# class, import or assignment that matters here, so they are not visited.
_STATEMENT_LISTS = ("body", "orelse", "finalbody", "handlers", "cases")


def _self_attribute(node):
    """("self.name", value) for `self.name = value` or `self.name: T = value`, else None."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target = node.target
    else:
        return None
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Name)
        and target.value.id == "self"
    ):
        return f"self.{target.attr}", node.value
    return None


def _collect(tree: ast.Module) -> _Found:
    found = _Found()
    # Each entry is (node, scope, id of the enclosing class or None).
    stack: list[tuple[ast.AST, tuple, int | None]] = [(tree, (), None)]
    while stack:  # a loop, not recursion, so deeply nested code cannot overflow the stack
        node, scope, owner = stack.pop()
        inner, inner_owner = scope, owner
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.functions.append((scope, node))
            if owner is not None:
                found.enclosing_class[id(node)] = owner
            inner = scope + (id(node),)
        elif isinstance(node, ast.ClassDef):
            found.classes.append(node)
            inner_owner = id(node)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found.imports.append(node)
        elif isinstance(node, ast.Expr):
            call = node.value
            if isinstance(call, ast.Await):
                call = call.value
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                if call.func.attr == "include_router" and call.args:
                    found.include_calls.append((scope, call))
                elif call.func.attr == "add_api_route":
                    found.api_route_calls.append((scope, call))
                if owner is not None:
                    found.enclosing_class[id(call)] = owner
        elif isinstance(node, _ASSIGNMENTS):
            assigned = _assigned_name(node)
            if assigned is not None:
                found.assigned.append((scope, assigned[0], assigned[1]))
            attribute = _self_attribute(node) if owner is not None else None
            if attribute is not None:
                found.attr_assigned.append((owner, attribute[0], attribute[1]))
        for field in _STATEMENT_LISTS:
            children = getattr(node, field, None)
            if children:
                stack.extend((child, inner, inner_owner) for child in children)
    return found


def _imports(nodes, rel):
    """Import aliases of a file: alias -> {"full": dotted name, "from": (module, name) or None}.

    Imports anywhere in the file count, including inside functions and `if TYPE_CHECKING`.
    """
    package = _module_name(rel).split(".")
    if not rel.endswith("__init__.py"):
        package = package[:-1]
    out = {}
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = {
                    "full": alias.name,
                    "from": None,
                }
        else:
            # A relative import climbs node.level - 1 packages above the current one.
            base = package[: max(len(package) - (node.level - 1), 0)] if node.level else []
            module = ".".join(base + ([node.module] if node.module else []))
            for alias in node.names:
                if alias.name == "*":
                    continue
                full = f"{module}.{alias.name}" if module else alias.name
                out[alias.asname or alias.name] = {
                    "full": full,
                    "from": (module, alias.name),
                }
    return out


# --- symbols: routers, aliases and variables across files ---------------------------------


class _Symbols:
    """Everything needed to follow a name from one file to where it is defined."""

    def __init__(self, trees, found):
        self.found = found
        self.index = _module_index(trees)
        self.imports = {rel: _imports(info.imports, rel) for rel, info in found.items()}
        self.router_names = _router_class_names(found)
        self.dependency_calls = {}
        self.router_calls = {}
        for rel in found:
            deps, routers = set(DEPENDENCY_CALLS), set(self.router_names)
            for alias, imported in self.imports[rel].items():
                module, original = imported["from"] or ("", "")
                if module.split(".")[0] in FASTAPI_PACKAGES:
                    if original in DEPENDENCY_CALLS:
                        deps.add(alias)
                    if original in ROUTER_CALLS:
                        routers.add(alias)
            self.dependency_calls[rel], self.router_calls[rel] = deps, routers
        # Tables keyed (file, scope, name). Variables and aliases are module-level only.
        self.consts: dict[tuple, ast.expr] = {}
        self.aliases: dict[tuple, tuple[list[str], list[str]]] = {}
        self.functions: dict[tuple, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        self.routers: dict[tuple, dict] = {}
        self._build()
        # Functions that check credentials in their own body, so a route that calls one is guarded.
        # Calls are matched by name, so a name counts only if every function with it does auth.
        # Route handlers are left out: a handler is often named like the manager method it calls.
        definitions: dict[str, list] = {}
        for fn in self.functions.values():
            if not any(_route_decorator(d) for d in fn.decorator_list):
                definitions.setdefault(fn.name, []).append(fn)
        self.auth_helpers = {
            name for name, fns in definitions.items() if all(_body_does_auth(fn) for fn in fns)
        }

    def _build(self):
        for rel, info in self.found.items():
            for scope, name, value in info.assigned:
                if scope == ():
                    self.consts.setdefault((rel, (), name), value)
            for scope, node in info.functions:
                self.functions.setdefault((rel, scope, node.name), node)
        for (rel, _, name), value in list(self.consts.items()):
            if isinstance(value, ast.Subscript) and _last_name(value.value) == "Annotated":
                self.aliases[(rel, (), name)] = (
                    self.depends_names(value, rel),
                    _type_names(value),
                )
        for rel, info in self.found.items():
            for scope, name, value in info.assigned:
                if isinstance(value, ast.Call) and _last_name(value.func) in self.router_calls[rel]:
                    self.routers.setdefault(
                        (rel, scope, name),
                        {"deps": self.keyword_dependencies(value, rel), "parents": []},
                    )
        for rel, info in self.found.items():
            for owner, name, value in info.attr_assigned:
                if isinstance(value, ast.Call) and _last_name(value.func) in self.router_calls[rel]:
                    self.routers.setdefault(
                        (rel, (owner,), name),
                        {"deps": self.keyword_dependencies(value, rel), "parents": []},
                    )
        for rel, info in self.found.items():
            for scope, call in info.include_calls:
                owner = info.enclosing_class.get(id(call))
                child = self.find(call.args[0], rel, scope, self.routers, owner)
                if child is None:
                    continue
                parent = self.find(call.func.value, rel, scope, self.routers, owner)
                added = self.keyword_dependencies(call, rel)
                self.routers[child]["parents"].append((parent, added))

    # -- finding a name's definition --

    def find(self, expr, rel, scope, table, owner=None):
        """The key in table that a Name or dotted attribute refers to, or None.

        owner is the id of the class the expression sits in, used to resolve `self.name`.
        """
        if _is_self_attribute(expr):
            key = (rel, (owner,), f"self.{expr.attr}")
            return key if owner is not None and key in table else None
        if isinstance(expr, ast.Name):
            for depth in range(len(scope), -1, -1):
                key = (rel, scope[:depth], expr.id)
                if key in table:
                    return key
            imported = self.imports[rel].get(expr.id)
            if imported and imported["from"]:
                module, original = imported["from"]
                target = self.index.get(module)
                if target:
                    return self._exported(target, original, table, 0)
            return None
        dotted = _plain_dotted(expr)
        if dotted is None or "." not in dotted:
            return None
        parts = dotted.split(".")
        imported = self.imports[rel].get(parts[0])
        modules = []
        if imported:  # `import a.b as x` then x.c.thing, or `from a import b` then b.c.thing
            modules.append(".".join([imported["full"], *parts[1:-1]]))
        modules.append(".".join(parts[:-1]))  # `import a.b.c` then a.b.c.thing
        for module in modules:
            target = self.index.get(module)
            if target:
                key = self._exported(target, parts[-1], table, 0)
                if key:
                    return key
        return None

    def _exported(self, target, name, table, depth):
        """Key of `name` in file `target`, following `from .x import name` re-exports."""
        key = (target, (), name)
        if key in table:
            return key
        if depth >= MAX_FOLLOW_DEPTH:
            return None
        imported = self.imports[target].get(name)
        if imported and imported["from"]:
            module, original = imported["from"]
            next_target = self.index.get(module)
            if next_target and next_target != target:
                return self._exported(next_target, original, table, depth + 1)
        return None

    # -- dependencies --

    def depends_names(self, expr, rel, seen=None) -> list[str]:
        """Names of callables used in Depends(...) or Security(...) anywhere in expr.

        Calls to a factory named like `...Dependency` count too.

        A variable that holds dependencies, such as AUTH = [Depends(get_user)], is followed.
        """
        seen = set() if seen is None else seen
        names = []
        stack = [expr]
        while stack:
            node = stack.pop()
            if isinstance(node, ast.Call) and _last_name(node.func) in self.dependency_calls[rel]:
                target = node.args[0] if node.args else None
                if target is None:
                    target = next((k.value for k in node.keywords if k.arg == "dependency"), None)
                if isinstance(target, ast.Call):  # Depends(RoleChecker(["admin"])) -> RoleChecker
                    target = target.func
                name = _dotted(target) if target is not None else None
                if name:
                    names.append(name)
            elif isinstance(node, ast.Call) and _normalise(_last_name(node.func)).endswith(
                "_dependency"
            ):
                # A factory whose name says it builds a dependency, as in
                # dependencies=[UserInterfaceAuthDependency("job:edit")] or
                # Annotated[User, CurrentUserDependency()].
                names.append(_dotted(node.func))
            elif isinstance(node, (ast.Name, ast.Attribute)):
                key = self.find(node, rel, (), self.consts)
                if key is not None and key not in seen:
                    seen.add(key)
                    value = self.consts[key]
                    # A variable holding a router is not a list of dependencies, even
                    # though the router's own constructor mentions some.
                    is_router = (
                        isinstance(value, ast.Call)
                        and _last_name(value.func) in self.router_calls[key[0]]
                    )
                    if not is_router:
                        names += self.depends_names(value, key[0], seen)
            stack.extend(ast.iter_child_nodes(node))
        return names

    def keyword_dependencies(self, call, rel) -> list[str]:
        names = []
        for keyword in call.keywords:
            if keyword.arg == "dependencies":
                names += self.depends_names(keyword.value, rel)
        return names

    def alias_names(self, annotation, rel) -> tuple[list[str], list[str]]:
        """(dependency names, type names) behind any aliases used in the annotation."""
        deps, types = [], []
        for node in ast.walk(annotation):
            key = self.find(node, rel, (), self.aliases) if _is_name(node) else None
            if key is not None:
                alias_deps, alias_types = self.aliases[key]
                deps += alias_deps
                types += alias_types
        return deps, types

    def effective_dependencies(self, key, seen=None) -> list[str]:
        """Dependencies a router's routes get from the router and every router that includes it.

        A router included in several places gets the union of all of them.
        """
        seen = set() if seen is None else seen
        if key in seen:
            return []
        seen.add(key)
        info = self.routers[key]
        names = list(info["deps"])
        for parent, added in info["parents"]:
            names += added
            if parent is not None:
                names += self.effective_dependencies(parent, seen)
        return names


def _router_class_names(found) -> set[str]:
    """APIRouter, FastAPI, and every class that inherits from them (by name, repo-wide)."""
    names = set(ROUTER_CALLS)
    changed = True
    while changed:
        changed = False
        for info in found.values():
            for cls in info.classes:
                if cls.name not in names and any(_last_name(b) in names for b in cls.bases):
                    names.add(cls.name)
                    changed = True
    return names


def _is_name(node) -> bool:
    return isinstance(node, (ast.Name, ast.Attribute))


def _is_self_attribute(node) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


# --- routes -------------------------------------------------------------------------------


def _routes_in_file(rel, info, symbols, extra_auth, lines):
    items = []
    for scope, node in info.functions:
        for dec in node.decorator_list:
            route = _route_decorator(dec)
            if route is None:
                continue
            router, methods, path = route
            owner = info.enclosing_class.get(id(node))
            key = symbols.find(router, rel, scope, symbols.routers, owner)
            if key is None:
                continue
            names = symbols.effective_dependencies(key) + symbols.keyword_dependencies(dec, rel)
            more_names, types = _function_dependencies(node, rel, symbols)
            names += more_names
            rate_decorator = any(
                _is_rate(_dotted(d.func if isinstance(d, ast.Call) else d) or "")
                for d in node.decorator_list
                if d is not dec
            )
            context = {
                "function_name": node.name,
                "decorators": [ast.unparse(d) for d in node.decorator_list],
                "comments_near": [],
            }
            for method in methods:
                items.append(
                    _item(
                        rel, method, path, node.lineno, names, types, dec, rate_decorator,
                        context, extra_auth, node, lines, symbols.auth_helpers,
                        span=[min(d.lineno for d in node.decorator_list), node.lineno],
                    )
                )  # fmt: skip
    for scope, call in info.api_route_calls:
        owner = info.enclosing_class.get(id(call))
        key = symbols.find(call.func.value, rel, scope, symbols.routers, owner)
        if key is None:
            continue
        names = symbols.effective_dependencies(key) + symbols.keyword_dependencies(call, rel)
        types: list[str] = []
        endpoint = call.args[1] if len(call.args) > 1 else _keyword(call, "endpoint")
        function = _function_named(endpoint, rel, scope, symbols)
        if function is not None:
            more_names, types = _function_dependencies(function, rel, symbols)
            names += more_names
        path = _string(call.args[0] if call.args else _keyword(call, "path"))
        context = {
            "function_name": function.name if function is not None else _dotted(endpoint),
            "decorators": [],
            "comments_near": [],
        }
        for method in _methods(_keyword(call, "methods"), default=["GET"]):
            items.append(
                _item(
                    rel,
                    method,
                    path,
                    call.lineno,
                    names,
                    types,
                    call,
                    False,
                    context,
                    extra_auth,
                    function,
                    lines,
                    symbols.auth_helpers,
                    span=[call.lineno, call.end_lineno or call.lineno],
                )  # fmt: skip
            )
    return items


def _item(
    rel, method, path, line, names, types, call, rate_decorator, context, extra_auth,
    function=None, lines=(), helpers=frozenset(), span=None,
):  # fmt: skip
    features = {
        "is_mutating": method in MUTATING,
        "has_auth": any(_is_auth(n, extra_auth) for n in names)
        or any(_matches_auth_type(t) for t in types)
        or _auth_outside_dependencies(function, path, lines, helpers),
        "has_response_model": _has_response_model(call, function),
        "has_rate_limit": rate_decorator or any(_is_rate(n) for n in names),
    }
    return {
        "detector": DETECTOR,
        # Routes are compared within their own folder. A whole repo often mixes auth
        # styles, so a repo-wide rule rarely holds; a folder usually does.
        "peer_group": f"{PEER_GROUP}:{_folder(rel)}",
        "item_id": f"{method} {path}",
        "file": rel,
        "line": line,
        # First decorator line to the def line: where a route's auth is written and changed.
        "span": span,
        "features": features,
        "context": dict(context),
    }


# --- routes that handle auth themselves, or need none -------------------------------------

# Last path segments of routes that cannot require a session: they create it, report on the
# service, or serve its own docs.
_PUBLIC_SEGMENTS = {
    "login", "logout", "register", "signup", "sign_in", "signin", "sign_up", "signout",
    "sign_out", "session", "token", "refresh", "callback", "health", "healthz", "ping",
    "docs", "redoc", "openapi.json",
}  # fmt: skip
_CALL_PREFIXES = {"require", "verify", "authenticate", "authorize", "authorise"}
_CREDENTIAL_PARAMS = {
    "secret", "signature", "token", "api_key", "apikey", "authorization", "hmac", "auth",
    "password",
}  # fmt: skip
_CREDENTIAL_SOURCES = {"Header", "Query", "Cookie"}
# Words after get_current_ that mean the dependency is not about who is calling.
_NOT_AUTH_WORDS = {
    "time", "date", "datetime", "settings", "config", "version", "page", "db", "session",
    "locale", "language", "timestamp", "env", "logger", "request",
}  # fmt: skip
# A comment or docstring in which the author says the route is open on purpose.
_SAYS_PUBLIC = re.compile(
    r"\bno[ -]auth(?:entication|orization|orisation|n|z)?\b"
    r"|\bwithout (?:any )?auth"
    r"|\bintentionally\s+(?:un|non[- ]?)?(?:authenticated|public)\b"
    r"|\banonymous (?:access|users?|callers?|requests?)\b"
    r"|\bopen to (?:everyone|all|anyone)\b"
    r"|\bpublic (?:endpoint|route|api|access)\b"
    r"|无需(?:认证|登录|鉴权)|不需要(?:认证|登录|鉴权)",
    re.IGNORECASE,
)
COMMENT_LOOKBACK = 3


def _has_response_model(call, function) -> bool:
    """A response model, or something that makes one unnecessary or impossible."""
    returns = function.returns if function is not None else None
    if returns is not None and not (isinstance(returns, ast.Constant) and returns.value is None):
        return True
    if not isinstance(call, ast.Call):
        return False
    for kw in call.keywords:
        if kw.arg in ("response_model", "response_class"):
            return True
        if kw.arg == "include_in_schema" and _is_false(kw.value):
            return True
        if kw.arg == "status_code" and _is_204(kw.value):
            return True
    return False


def _is_false(node) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _is_204(node) -> bool:
    if isinstance(node, ast.Constant):
        return node.value == 204
    return "204" in (_dotted(node) or "")


def _auth_outside_dependencies(function, path, lines, helpers=frozenset()) -> bool:
    """Auth that is written in the route, announced by its docs, or unneeded by its path."""
    if _public_path(path):
        return True
    if function is None:
        return False
    return (
        _declared_public(function, lines)
        or _credential_params(function)
        or _body_does_auth(function, helpers)
    )


def _public_path(path: str) -> bool:
    segments = [s for s in path.lower().split("/") if s and not s.startswith("{")]
    return bool(segments) and segments[-1].replace("-", "_") in _PUBLIC_SEGMENTS


def _declared_public(function, lines) -> bool:
    if _SAYS_PUBLIC.search(ast.get_docstring(function) or ""):
        return True
    first = min([function.lineno] + [d.lineno for d in function.decorator_list])
    above = first - 2  # zero-based index of the line above the first decorator
    for index in range(above, max(above - COMMENT_LOOKBACK, -1), -1):
        if index >= len(lines) or not lines[index].lstrip().startswith("#"):
            break
        if _SAYS_PUBLIC.search(lines[index]):
            return True
    return False


def _credential_params(function) -> bool:
    """A secret, key, signature or token taken from a header, cookie or query parameter."""
    positional = function.args.posonlyargs + function.args.args
    defaults = [None] * (len(positional) - len(function.args.defaults)) + list(
        function.args.defaults
    )
    pairs = list(zip(positional, defaults, strict=True))
    pairs += zip(function.args.kwonlyargs, function.args.kw_defaults, strict=True)
    for arg, default in pairs:
        sources = [default] if default is not None else []
        if arg.annotation is not None:
            sources.append(_annotation(arg.annotation))
        for source in sources:
            for node in ast.walk(source):
                if isinstance(node, ast.Call) and _last_name(node.func) in _CREDENTIAL_SOURCES:
                    labels = [arg.arg] + [
                        k.value.value
                        for k in node.keywords
                        if k.arg == "alias"
                        and isinstance(k.value, ast.Constant)
                        and isinstance(k.value.value, str)
                    ]
                    if any(_matches(label, _CREDENTIAL_PARAMS) for label in labels):
                        return True
    return False


def _body_does_auth(function, helpers=frozenset()) -> bool:
    """The route checks credentials itself: raises 401/403, calls a verifier, compares a secret."""
    for node in ast.walk(function):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if _last_name(node.exc.func) == "HTTPException" and _denies(node.exc):
                return True
        elif isinstance(node, ast.Call):
            name = _dotted(node.func) or ""
            last = name.split(".")[-1]
            if last == "compare_digest" or name.endswith("jwt.decode") or last in helpers:
                return True
            if _normalise(last).split("_")[0] in _CALL_PREFIXES:
                return True
    return False


def _denies(call) -> bool:
    """True for HTTPException with a 401 or 403 status."""
    status = call.args[0] if call.args else _keyword(call, "status_code")
    if status is None:
        return False
    if isinstance(status, ast.Constant):
        return status.value in (401, 403)
    text = _dotted(status) or ""
    return any(word in text for word in ("401", "403", "UNAUTHORIZED", "FORBIDDEN"))


def _function_dependencies(node, rel, symbols):
    """(dependency names, type names) from a route function's defaults and annotations."""
    names: list[str] = []
    types: list[str] = []
    for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
        names += symbols.depends_names(default, rel)
    for arg in _all_args(node.args):
        if arg.annotation is None:
            continue
        annotation = _annotation(arg.annotation)
        alias_deps, alias_types = symbols.alias_names(annotation, rel)
        names += symbols.depends_names(annotation, rel) + alias_deps
        types += alias_types + _type_names(annotation)
    return names, types


def _annotation(expr):
    """The expression behind an annotation. A string annotation such as "CurrentUser" is parsed."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            return ast.parse(expr.value.strip(), mode="eval").body
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return ast.Constant(value=None)
    return expr


def _function_named(expr, rel, scope, symbols):
    if expr is None or not _is_name(expr):
        return None
    key = symbols.find(expr, rel, scope, symbols.functions)
    return symbols.functions[key] if key is not None else None


def _folder(rel: str) -> str:
    """Folder of a file, relative to the scanned root. Files at the root give "."."""
    return rel.rsplit("/", 1)[0] if "/" in rel else "."


def _route_decorator(dec):
    """Return (router expression, HTTP methods, path) for @router.get("/x") style decorators.

    The router is a plain name, or `self.router` inside a class.
    """
    if not (
        isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and (isinstance(dec.func.value, ast.Name) or _is_self_attribute(dec.func.value))
    ):
        return None
    attr = dec.func.attr
    if attr in ROUTE_METHODS:
        methods = [attr.upper()]
    elif attr == "api_route":
        methods = _methods(_keyword(dec, "methods"), default=["GET"])
    else:
        return None
    path = _string(dec.args[0] if dec.args else _keyword(dec, "path"))
    return dec.func.value, methods, path


def _methods(expr, default):
    """HTTP methods from a literal list such as ["GET", "POST"].

    No methods argument gives the default. An argument that is not a literal list, such as
    a variable, gives ["ANY"]: the methods are real but cannot be read from the source.
    """
    if expr is None:
        return list(default)
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        found = [
            e.value.upper()
            for e in expr.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)
        ]
        if found and len(found) == len(expr.elts):
            return found
    return ["ANY"]


def _keyword(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


def _string(expr) -> str:
    """A literal string, or "<dynamic>" for anything computed."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    return "<dynamic>"


def _all_args(args: ast.arguments):
    return list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)


# --- names --------------------------------------------------------------------------------


def _type_names(expr) -> list[str]:
    """Dotted names of every Name and Attribute in an annotation."""
    names = []
    for node in ast.walk(expr):
        if isinstance(node, (ast.Name, ast.Attribute)):
            dotted = _dotted(node)
            if dotted:
                names.append(dotted)
    return names


def _dotted(node) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return None


def _plain_dotted(node) -> str | None:
    """A dotted name made only of names and attributes, with no calls in it."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _plain_dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _last_name(node) -> str:
    name = _dotted(node)
    return name.split(".")[-1] if name else ""


def _normalise(name: str) -> str:
    """snake_case words: "JWTBearer" -> "jwt_bearer", "GetCurrentUser" -> "get_current_user"."""
    split = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name)
    return re.sub(r"[^a-z0-9]+", "_", split.lower()).strip("_")


def _matches(name: str, words) -> bool:
    """True if a word appears as whole words in the name, so "authors" does not match "auth"."""
    padded = f"_{_normalise(name)}_"
    return any(f"_{_normalise(w)}_" in padded for w in words)


def _is_auth(name: str, extra_auth: set[str]) -> bool:
    if _matches(name, AUTH_WORDS | extra_auth):
        return True
    words = set(_normalise(name).split("_"))
    # get_current_context, get_current_tenant: whoever is calling, unless plainly not that
    if _normalise(name.split(".")[-1]).startswith("get_current_") and not words & _NOT_AUTH_WORDS:
        return True
    return any(set(pair) <= words for pair in AUTH_WORD_PAIRS)


def _matches_auth_type(name: str) -> bool:
    return _matches(name, AUTH_TYPE_WORDS)


def _is_rate(name: str) -> bool:
    return _matches(name, RATE_WORDS)
