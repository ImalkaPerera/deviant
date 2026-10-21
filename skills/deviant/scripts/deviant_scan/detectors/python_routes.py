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
# Features whose exceptions are reported only with --include-style: a missing response model
# is untidy, and a stream or a file download cannot have one.
STYLE_FEATURES = {"has_response_model"}
ROUTE_METHODS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
    "trace",
    "websocket",
}  # fmt: skip
# Starlette and FastAPI calls that register an endpoint without a decorator.
REGISTER_CALLS = {"add_api_route", "add_route", "add_websocket_route"}
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
    "http_basic",
    "http_digest",
    "o_auth2",
    "open_id_connect",
}
# Classes in fastapi.security. A dependency built from one is auth, whatever its variable is called.
SECURITY_CLASSES = {
    "HTTPBasic",
    "HTTPBearer",
    "HTTPDigest",
    "OAuth2",
    "OAuth2PasswordBearer",
    "OAuth2AuthorizationCodeBearer",
    "APIKeyHeader",
    "APIKeyQuery",
    "APIKeyCookie",
    "OpenIdConnect",
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
AUTH_WORD_PAIRS = {
    ("current", "user"),
    ("web", "user"),
    ("validate", "session"),
    ("validate", "identity"),
    # RoleChecker(["admin"]) and role_checker(...) are dependencies that check a role.
    ("role", "checker"),
}
# "limit" is left out on purpose: pagination dependencies such as limit_offset are not rate limits.
RATE_WORDS = {"rate", "ratelimit", "limiter", "throttle"}

# Control and bidirectional characters can come from a scanned project's file names. They are
# shown as escapes so a hostile name cannot recolour or rewrite what the reader sees.
_UNSAFE_RANGES = ((0x00, 0x1F), (0x7F, 0x9F), (0x2028, 0x2029), (0x202A, 0x202E), (0x2066, 0x2069))
_UNSAFE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _UNSAFE_RANGES) + "]")


def _show(text) -> str:
    """text with control and bidirectional characters replaced by visible escapes."""

    def escape(match):
        code = ord(match.group())
        return chr(92) + (f"x{code:02x}" if code < 0x100 else f"u{code:04x}")

    return _UNSAFE.sub(escape, str(text))


MAX_BYTES = 1_000_000
MAX_FOLLOW_DEPTH = 5
MAX_MOUNTS = 64
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
    "tests",
    "test",
}


def extract(repo_root: str) -> list[dict]:
    root = Path(repo_root).resolve()
    extra_auth = _extra_auth_words(root)
    trees, sources = _parse_files(root)
    found = {rel: _collect(tree) for rel, tree in trees.items()}
    symbols = _Symbols(trees, found, sources)
    items = []
    for rel, info in found.items():
        try:
            items.extend(_routes_in_file(rel, info, symbols, extra_auth, sources[rel]))
        except Exception as error:
            # One file that trips the detector must not drop the routes of every other file.
            print(
                f"python_routes: {_show(rel)} could not be read for routes "
                f"({type(error).__name__}) and was skipped",
                file=sys.stderr,
            )
    return items


def _inside(path: Path, root: Path) -> bool:
    """True if path, with links and junctions followed, is still inside root (root is resolved)."""
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def _cannot_resolve(path: Path) -> bool:
    """True if the system cannot resolve this path at all, as opposed to it leading outside."""
    try:
        path.resolve()
    except (OSError, RuntimeError):
        return True
    return False


def _extra_auth_words(root: Path) -> set[str]:
    """Words the user adds in .deviant/config.json under "auth_words"."""
    path = root / ".deviant" / "config.json"
    try:
        if not path.exists():
            return set()
        if path.is_symlink() or not _inside(path, root) or path.stat().st_size > MAX_BYTES:
            _config_ignored("is a link, outside the folder, or too large")
            return set()
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError:
        _config_ignored("could not be read")
        return set()
    except ValueError:
        _config_ignored("is not valid JSON")
        return set()
    words = config.get("auth_words", []) if isinstance(config, dict) else None
    # A single word written as a string, not a list, would otherwise be read letter by letter.
    if isinstance(words, str):
        words = [words]
    if not isinstance(words, list):
        _config_ignored('needs "auth_words" to be a list of names')
        return set()
    return {_normalise(w) for w in words if isinstance(w, str) and w.strip()}


def _config_ignored(reason: str) -> None:
    """Say on stderr that the auth words were not used, because a route can then look unguarded."""
    print(
        f"python_routes: .deviant/config.json {reason}, so its auth_words are not used",
        file=sys.stderr,
    )


# --- reading files ------------------------------------------------------------------------


def _parse_files(root: Path) -> tuple[dict[str, ast.Module], dict[str, list[str]]]:
    """(syntax trees, source lines) of every readable Python file, keyed by relative path."""
    trees = {}
    sources = {}
    failed = []
    # A junction can lead to a file already read under another path. Read each file once.
    seen_real: set[Path] = set()
    # Folders already walked, by real path. os.walk follows Windows junctions, and a junction
    # that points back up the tree would be walked again at every level, which grows
    # exponentially with how many levels the path length allows. Each real folder is walked once.
    seen_dirs: set[Path] = set()
    unreadable: list[str] = []

    def note_unreadable(error: OSError) -> None:
        # os.walk drops a folder it cannot list without a word unless it is given a handler.
        name = getattr(error, "filename", None)
        try:
            unreadable.append(Path(name).relative_to(root).as_posix())
        except (TypeError, ValueError):
            unreadable.append(str(name))

    for dirpath, dirnames, filenames in os.walk(root, onerror=note_unreadable):
        here = Path(dirpath)
        try:
            real_dir = here.resolve()
        except (OSError, RuntimeError):
            real_dir = None
        if real_dir is not None:
            if real_dir in seen_dirs:
                dirnames[:] = []
                continue
            seen_dirs.add(real_dir)
        # A folder that leads outside the repository is dropped here. One that cannot be
        # resolved at all, such as a path longer than the system allows, is dropped and reported.
        kept = []
        for d in sorted(dirnames):
            if d in SKIP_DIRS:
                continue
            child = here / d
            if _inside(child, root):
                kept.append(d)
            elif _cannot_resolve(child):
                unreadable.append(child.relative_to(root).as_posix())
        dirnames[:] = kept
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            try:
                if path.is_symlink():
                    continue
                if not _inside(path, root):
                    if _cannot_resolve(path):
                        unreadable.append(rel)
                    continue
                if path.stat().st_size > MAX_BYTES:
                    print(
                        f"python_routes: {_show(rel)} is larger than {MAX_BYTES} bytes "
                        "and was skipped",
                        file=sys.stderr,
                    )
                    continue
                real = path.resolve()
                if real in seen_real:
                    continue
                seen_real.add(real)
                source = path.read_bytes()
            except OSError:
                unreadable.append(rel)
                continue
            tree = _parse(source, rel)
            if tree is not None:
                trees[rel] = tree
                sources[rel] = _source_lines(source.decode("utf-8", errors="replace"))
            elif not _looks_like_template(source):
                failed.append(rel)
            elif b"APIRouter" in source or b"FastAPI" in source:
                # Plain Jinja templates are expected here and stay quiet. A broken file that
                # defines routes is different: its routes are missed, so say so.
                print(
                    f"python_routes: {_show(rel)} defines routes but could not be parsed "
                    "and was skipped",
                    file=sys.stderr,
                )
    if unreadable:
        shown = ", ".join(unreadable[:3]) + (" ..." if len(unreadable) > 3 else "")
        print(
            f"python_routes: {len(unreadable)} path(s) could not be read and were skipped, "
            "for example a path longer than the system allows, or a name the system cannot "
            f"open such as one ending in a space or a dot on Windows: {_show(shown)}",
            file=sys.stderr,
        )
    if failed:
        # A skipped file can hide the auth helpers other files import, so say so.
        version = ".".join(map(str, sys.version_info[:2]))
        shown = ", ".join(failed[:3]) + (" ..." if len(failed) > 3 else "")
        print(
            f"python_routes: could not parse {len(failed)} file(s) with Python {version}: "
            f"{_show(shown)}. They have a syntax error or use syntax newer than this Python; "
            "results that depend on them can be wrong.",
            file=sys.stderr,
        )
    return trees, sources


# Python 3.14 allows `except A, B:` without parentheses. Older versions reject it, so a
# file that fails to parse is retried with the parentheses added.
# The pattern stays on one line and each part has a length limit, because a file that fails to
# parse can be hostile, and an open-ended match over it grows with the square of its size.
_BARE_EXCEPT = re.compile(
    r"^([ \t]*except[ \t]+)([^()#:\r\n]{1,200},[^()#:\r\n]{1,200}?)([ \t]*:)", re.MULTILINE
)


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


# Python counts lines at \n, \r\n and \r only. str.splitlines() also breaks at a form feed,
# \x1c to \x1e, \x85 and \u2028, which would shift every line after one of them, so a
# comment above a route would be read from the wrong line.
_LINE_BREAK = re.compile(r"\r\n|\r|\n")


def _source_lines(text: str) -> list[str]:
    """The lines of a source file, numbered as the syntax tree numbers them."""
    return _LINE_BREAK.split(text)


def _looks_like_template(source: bytes) -> bool:
    """Jinja and similar templates are not Python until rendered; skip them without a warning."""
    head = source[:20_000]
    return b"{%" in head or b"{{" in head


def _module_name(rel: str) -> str:
    parts = rel[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_candidates(files) -> dict[str, list[str]]:
    """Map every dotted suffix of a module name to the files that have it.

    A monorepo can hold app/auth.py twice, once per service, so a suffix can have several files.
    """
    index: dict[str, list[str]] = {}
    for rel in files:
        segments = _module_name(rel).split(".")
        for i in range(len(segments)):
            files_for_key = index.setdefault(".".join(segments[i:]), [])
            if rel not in files_for_key:
                files_for_key.append(rel)
    return index


def _folder_index(candidates: dict[str, list[str]]) -> dict[tuple, list[str]]:
    """Map (module, folder path) to the files of that module under that folder.

    A file is listed under every folder above it. Looking an importer's folders up from the
    deepest one then finds the nearest candidate in one step, instead of comparing every file.
    """
    index: dict[tuple, list[str]] = {}
    for module, rels in candidates.items():
        for rel in rels:
            folders = rel.split("/")[:-1]
            for depth in range(len(folders) + 1):
                index.setdefault((module, tuple(folders[:depth])), []).append(rel)
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
        # `router.get("/x")(handler)`: the decorator is applied to a call, not written above a def.
        self.call_routes: list[tuple[tuple, ast.Call]] = []
        # `self.router = APIRouter()` inside a class: (class id, "self.router", value).
        self.attr_assigned: list[tuple[int, str, ast.expr]] = []
        # The class a function or call sits in, by id of the node, for `self.` lookups.
        self.enclosing_class: dict[int, int] = {}
        # Functions written directly in a class body, as opposed to functions nested in a method.
        self.class_members: set[int] = set()


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
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    found.class_members.add(id(child))
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            found.imports.append(node)
        elif isinstance(node, ast.Expr):
            call = node.value
            if isinstance(call, ast.Await):
                call = call.value
            if (
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Call)
                and _route_decorator(call.func) is not None
            ):
                found.call_routes.append((scope, call))
                if owner is not None:
                    found.enclosing_class[id(call)] = owner
            elif isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute):
                if call.func.attr == "include_router" and (call.args or _keyword(call, "router")):
                    found.include_calls.append((scope, call))
                elif call.func.attr in REGISTER_CALLS:
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
    name = _module_name(rel)
    # A root-level __init__.py has an empty name, so it has no package parts at all.
    package = name.split(".") if name else []
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
                    # Names from a star import are looked up in that module when used.
                    out[f"*{module}"] = {"full": module, "from": None, "star": True}
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

    def __init__(self, trees, found, sources):
        self.found = found
        self.sources = sources
        # Which file each function lives in, so a comment is read from the endpoint's own file.
        self.function_file = {
            id(node): rel for rel, info in found.items() for _scope, node in info.functions
        }
        self.candidates = _module_candidates(trees)
        self.by_folder = _folder_index(self.candidates)
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
        self._prefix_cache: dict[tuple, list[str]] = {}
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
        # Dependencies that check credentials: a function whose body does, or a class whose
        # __init__ does or depends on auth. A route that depends on one is guarded. Kept apart
        # from auth_helpers, so a route that merely calls such a class in its body is not.
        self.auth_classes = {
            cls.name
            for rel, info in self.found.items()
            for cls in info.classes
            if self._class_is_auth(cls, rel)
        }
        self.dependency_helpers = self.auth_helpers | self.auth_classes

    def _build(self):
        for rel, info in self.found.items():
            for scope, name, value in info.assigned:
                if scope == ():
                    self.consts.setdefault((rel, (), name), value)
            for scope, node in info.functions:
                # A method is keyed by its class, so it cannot be mistaken for a module function.
                # Only a method is keyed by its class. A function nested inside a method keeps
                # the scope it is defined in, so a route can still find it there.
                owner = info.enclosing_class.get(id(node))
                is_method = id(node) in info.class_members and owner is not None
                key_scope = (owner,) if is_method else scope
                self.functions.setdefault((rel, key_scope, node.name), node)
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
                        {
                            "deps": self.keyword_dependencies(value, rel),
                            "parents": [],
                            "prefix": _literal_prefix(_keyword(value, "prefix")),
                        },
                    )
        for rel, info in self.found.items():
            for owner, name, value in info.attr_assigned:
                if isinstance(value, ast.Call) and _last_name(value.func) in self.router_calls[rel]:
                    self.routers.setdefault(
                        (rel, (owner,), name),
                        {
                            "deps": self.keyword_dependencies(value, rel),
                            "parents": [],
                            "prefix": _literal_prefix(_keyword(value, "prefix")),
                        },
                    )
        for rel, info in self.found.items():
            for scope, call in info.include_calls:
                owner = info.enclosing_class.get(id(call))
                child_expr = call.args[0] if call.args else _keyword(call, "router")
                child = self.find(child_expr, rel, scope, self.routers, owner)
                if child is None:
                    continue
                parent = self.find(call.func.value, rel, scope, self.routers, owner)
                added = self.keyword_dependencies(call, rel)
                self.routers[child]["parents"].append(
                    (parent, added, _literal_prefix(_keyword(call, "prefix")))
                )

    # -- finding a name's definition --

    def find(self, expr, rel, scope, table, owner=None):
        """The key in table that a Name or dotted attribute refers to, or None.

        owner is the id of the class the expression sits in, used to resolve `self.name`.
        """
        if _is_self_attribute(expr):
            key = (rel, (owner,), f"self.{expr.attr}")
            if owner is not None and key in table:
                return key
            # self.handler names a method of the class, which the function table keys by class.
            method = (rel, (owner,), expr.attr)
            return method if owner is not None and method in table else None
        if isinstance(expr, ast.Name):
            for depth in range(len(scope), -1, -1):
                key = (rel, scope[:depth], expr.id)
                if key in table:
                    return key
            imported = self.imports[rel].get(expr.id)
            if imported and imported["from"]:
                module, original = imported["from"]
                target = self._target(module, rel)
                if target:
                    return self._exported(target, original, table, 0)
            return self._star_key(expr.id, rel, table)
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
            target = self._target(module, rel)
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
            next_target = self._target(module, target)
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
                    # An alias such as `from app.deps import get_user as gu` also names get_user.
                    imported = self.imports[rel].get(name)
                    if imported and imported["from"]:
                        names.append(imported["from"][1])
            elif isinstance(node, ast.Call) and _normalise(_last_name(node.func)).endswith(
                "_dependency"
            ):
                # A factory whose name says it builds a dependency, as in
                # dependencies=[UserInterfaceAuthDependency("job:edit")] or
                # Annotated[User, CurrentUserDependency()].
                names.append(_dotted(node.func))
            elif isinstance(node, ast.Call) and _last_name(node.func) in SECURITY_CLASSES:
                names.append(_last_name(node.func))
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

    def _target(self, module: str, importer: str) -> str | None:
        """The file a dotted module name refers to, seen from the file that imports it."""
        candidates = self.candidates.get(module)
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        # An import that names a file's full module path (app.routers.items) is that file.
        exact = [rel for rel in candidates if _module_name(rel) == module]
        if len(exact) == 1:
            return exact[0]
        # The deepest folder shared with the importer holds the nearest candidates. Two of them
        # at that depth tie, and a tie is not guessed.
        folders = importer.split("/")[:-1]
        for depth in range(len(folders), -1, -1):
            hits = self.by_folder.get((module, tuple(folders[:depth])))
            if hits:
                return hits[0] if len(hits) == 1 else None
        return None

    def _class_is_auth(self, cls, rel) -> bool:
        """True if a class's __init__ depends on auth or checks credentials itself."""
        init = next(
            (
                node
                for node in cls.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__init__"
            ),
            None,
        )
        if init is None:
            return False
        names, _ = _function_dependencies(init, rel, self)
        return any(_is_auth(n, set()) for n in names) or _raises_denial(init)

    def lines_for(self, function, default):
        """The source lines of the file a function is defined in, or default if unknown."""
        if function is None:
            return default
        rel = self.function_file.get(id(function))
        return self.sources.get(rel, default) if rel is not None else default

    def prefixes(self, key, seen=None) -> list[str]:
        """Every URL prefix a router's routes can be mounted under, from its own prefix and
        each include_router call up the chain. A router with no mount has just its own prefix.
        """
        # Cached per router, so a router reached by two include paths (a diamond) keeps the
        # prefixes of every path. `seen` holds the routers on the current path, to stop cycles.
        if key in self._prefix_cache:
            return self._prefix_cache[key]
        seen = set() if seen is None else seen
        info = self.routers[key]
        if key in seen or not info["parents"]:
            return [info["prefix"]]
        seen.add(key)
        out = []
        for parent, _added, mount in info["parents"]:
            bases = self.prefixes(parent, seen) if parent is not None else [""]
            out += [base + mount + info["prefix"] for base in bases]
        # A router included twice at each level of a chain has twice as many mounts per level.
        # Distinct mounts are kept, up to a limit, so a crafted chain cannot take exponential time.
        # When some are dropped, an empty mount stands for them: it is not public, so a route
        # is never taken as public because of the mounts that were not looked at.
        out = list(dict.fromkeys(out))
        if len(out) > MAX_MOUNTS:
            out = out[: MAX_MOUNTS - 1] + [""]
        seen.discard(key)
        self._prefix_cache[key] = out
        return out

    def _star_key(self, name, rel, table):
        """The key of a name that a `from module import *` in this file brings in."""
        for imported in self.imports[rel].values():
            if imported.get("star"):
                target = self._target(imported["full"], rel)
                key = self._exported(target, name, table, 0) if target else None
                if key:
                    return key
        return None

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
        for parent, added, _prefix in info["parents"]:
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
            # Other decorators such as @requires_login("admin") are guards: their names count.
            names += [
                guard
                for d in node.decorator_list
                if d is not dec
                and (guard := _dotted(d.func if isinstance(d, ast.Call) else d))
                and _is_auth(guard, extra_auth)
            ]
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
                        context, extra_auth, node, symbols.lines_for(node, lines),
                        symbols.auth_helpers,
                        dependency_helpers=symbols.dependency_helpers,
                        mounts=symbols.prefixes(key),
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
        function = _function_named(endpoint, rel, scope, symbols, owner)
        if function is not None:
            more_names, types = _function_dependencies(function, rel, symbols)
            names += more_names
        elif isinstance(endpoint, ast.Lambda):
            names += _lambda_dependencies(endpoint, rel, symbols)
        path = _string(call.args[0] if call.args else _keyword(call, "path"))
        context = {
            "function_name": function.name if function is not None else _dotted(endpoint),
            "decorators": [],
            "comments_near": [],
        }
        if call.func.attr == "add_websocket_route":
            methods = ["WEBSOCKET"]
        else:
            # add_route(path, endpoint, methods) takes methods positionally as well.
            if call.func.attr == "add_route" and len(call.args) > 2:
                methods_expr = call.args[2]
            else:
                methods_expr = _keyword(call, "methods")
            methods = _methods(methods_expr, default=["GET"])
        for method in methods:
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
                    symbols.lines_for(function, lines),
                    symbols.auth_helpers,
                    dependency_helpers=symbols.dependency_helpers,
                    mounts=symbols.prefixes(key),
                    span=[call.lineno, call.end_lineno or call.lineno],
                )
            )
    # `router.get("/x")(handler)`: the same route as a decorator, applied to a call.
    for scope, call in info.call_routes:
        router, methods, path = _route_decorator(call.func)
        owner = info.enclosing_class.get(id(call))
        key = symbols.find(router, rel, scope, symbols.routers, owner)
        if key is None or not call.args:
            continue
        endpoint = call.args[0]
        function = _function_named(endpoint, rel, scope, symbols, owner)
        names = symbols.effective_dependencies(key) + symbols.keyword_dependencies(call.func, rel)
        types: list[str] = []
        if function is not None:
            more_names, types = _function_dependencies(function, rel, symbols)
            names += more_names
        elif isinstance(endpoint, ast.Lambda):
            names += _lambda_dependencies(endpoint, rel, symbols)
        context = {
            "function_name": function.name if function is not None else _dotted(endpoint),
            "decorators": [],
            "comments_near": [],
        }
        for method in methods:
            items.append(
                _item(
                    rel,
                    method,
                    path,
                    call.lineno,
                    names,
                    types,
                    call.func,
                    False,
                    context,
                    extra_auth,
                    function,
                    symbols.lines_for(function, lines),
                    symbols.auth_helpers,
                    dependency_helpers=symbols.dependency_helpers,
                    mounts=symbols.prefixes(key),
                    span=[call.lineno, call.end_lineno or call.lineno],
                )
            )
    return items


def _lambda_dependencies(node, rel, symbols):
    """Dependencies in a lambda endpoint's defaults, as in lambda user=Depends(get_user): ..."""
    names: list[str] = []
    for default in node.args.defaults + [d for d in node.args.kw_defaults if d is not None]:
        names += symbols.depends_names(default, rel)
    return names


def _item(
    rel, method, path, line, names, types, call, rate_decorator, context, extra_auth,
    function=None, lines=(), helpers=frozenset(), span=None, dependency_helpers=frozenset(),
    mounts=None,
):  # fmt: skip
    features = {
        "is_mutating": method in MUTATING,
        "has_auth": any(_is_auth(n, extra_auth) for n in names)
        or any(_last_segment(n) in dependency_helpers for n in names)
        or any(_matches_auth_type(t) for t in types)
        or _auth_outside_dependencies(function, _public_route(path, mounts or []), lines, helpers),
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
        "context": {
            **context,
            "dependencies": [n for n in sorted(set(names)) if not _is_plumbing(n)],
        },
    }


# --- routes that handle auth themselves, or need none -------------------------------------

# Last path segments of routes that cannot require a session: they create it, report on the
# service, or serve its own docs.
_PUBLIC_SEGMENTS = {
    "login", "logout", "register", "signup", "sign_in", "signin", "sign_up", "signout",
    "sign_out", "session", "token", "refresh", "callback", "health", "healthz", "ping",
    "docs", "redoc", "openapi.json", "forgot_password", "reset_password", "request_verify_token",
    "verify", "authorize", "public",
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
# A claim of public access is void when the same sentence negates it, as in "Not open to everyone".
# "No anonymous access" and "rejects requests without auth" negate the claim that follows.
# "requires" is left out on purpose: "requires no auth" is a claim of public access.
_NEGATION = re.compile(
    r"\b(?:not|never|no longer|no|rejects?|rejected|denies|deny|denied|refuses?|refused"
    r"|blocks?|blocked|forbids?|forbidden)\b|n't\b",
    re.IGNORECASE,
)
# Abbreviations end in a dot that is not the end of a sentence.
_ABBREVIATION = re.compile(r"\b(e\.g|i\.e|etc|vs)\.", re.IGNORECASE)
_NEGATION_LOOKBACK = 300


def _says_public(text: str) -> bool:
    for match in _SAYS_PUBLIC.finditer(text):
        # Only the text just before the match can negate it, so look back a fixed distance.
        # Splitting all the text before it, for every match, grows with the square of the size.
        window = text[max(0, match.start() - _NEGATION_LOOKBACK) : match.start()]
        window = _ABBREVIATION.sub(lambda m: m.group(1).replace(".", ""), window)
        sentence = re.split(r"[.;!?\n]", window)[-1]
        if not _NEGATION.search(sentence):
            return True
    return False


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


def _auth_outside_dependencies(function, public, lines, helpers=frozenset()) -> bool:
    """Auth that is written in the route, announced by its docs, or unneeded by its path."""
    if public:
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
    if _says_public(ast.get_docstring(function) or ""):
        return True
    first = min([function.lineno] + [d.lineno for d in function.decorator_list])
    above = first - 2  # zero-based index of the line above the first decorator
    for index in range(above, max(above - COMMENT_LOOKBACK, -1), -1):
        if index >= len(lines) or not lines[index].lstrip().startswith("#"):
            break
        if _says_public(lines[index]):
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
                    # A cookie is a session credential whatever the parameter is called.
                    if _last_name(node.func) == "Cookie":
                        return True
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


def _raises_denial(function) -> bool:
    """True if the function itself raises HTTPException with a 401 or 403 status.

    Narrower than _body_does_auth: a class's __init__ calling a helper named verify_* is
    usually just validation, so only an explicit denial counts for a dependency class.
    """
    for node in ast.walk(function):
        if isinstance(node, ast.Raise) and isinstance(node.exc, ast.Call):
            if _last_name(node.exc.func) == "HTTPException" and _denies(node.exc):
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
    # A bare Depends() takes its dependency from the annotation, as in `user: get_user = Depends()`.
    positional = node.args.posonlyargs + node.args.args
    tail = positional[len(positional) - len(node.args.defaults) :]
    pairs = list(zip(tail, node.args.defaults, strict=True))
    pairs += [
        (a, d)
        for a, d in zip(node.args.kwonlyargs, node.args.kw_defaults, strict=True)
        if d is not None
    ]
    for arg, default in pairs:
        if arg.annotation is None or not _is_bare_depends(default, rel, symbols):
            continue
        dotted = _dotted(_annotation(arg.annotation))
        if dotted:
            names.append(dotted)
    for arg in _all_args(node.args):
        if arg.annotation is None:
            continue
        annotation = _annotation(arg.annotation)
        alias_deps, alias_types = symbols.alias_names(annotation, rel)
        names += symbols.depends_names(annotation, rel) + alias_deps
        types += alias_types + _type_names(annotation)
        # Optional["CurrentUser"] names an alias inside a string, which must be read too.
        for inner in _nested_annotations(annotation):
            inner_deps, inner_types = symbols.alias_names(inner, rel)
            names += symbols.depends_names(inner, rel) + inner_deps
            types += inner_types
    return names, types


def _is_bare_depends(default, rel, symbols) -> bool:
    """True for Depends() or Security() with no argument."""
    return (
        isinstance(default, ast.Call)
        and not default.args
        and not default.keywords
        and _last_name(default.func) in symbols.dependency_calls[rel]
    )


def _annotation(expr):
    """The expression behind an annotation. A string annotation such as "CurrentUser" is parsed."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        try:
            return ast.parse(expr.value.strip(), mode="eval").body
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            return ast.Constant(value=None)
    return expr


def _function_named(expr, rel, scope, symbols, owner=None):
    if expr is None or not _is_name(expr):
        return None
    key = symbols.find(expr, rel, scope, symbols.functions, owner)
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


def _literal_prefix(expr) -> str:
    """A router or include prefix written as a plain string, else "" (unknown or none)."""
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    return ""


def _public_route(path: str, mounts: list[str]) -> bool:
    """True if the route is public by its own path, or is a root route under a public mount.

    A mount prefix alone says nothing about a route with its own path: under prefix "/docs",
    DELETE "/{doc_id}" is still unprotected. Only a route at the root takes its mount's name.
    """
    if _public_path(path):
        return True
    has_own_path = any(segment for segment in path.split("/"))
    if has_own_path:
        return False
    return bool(mounts) and all(_public_path(mount) for mount in mounts)


def _nested_annotations(expr) -> list[ast.expr]:
    """Expressions written as strings inside an annotation, such as Optional["CurrentUser"]."""
    found = []
    for node in ast.walk(expr):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                found.append(ast.parse(node.value, mode="eval").body)
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                pass  # a string that is not an expression, such as a description
    return found


def _last_segment(name: str) -> str:
    """The last part of a dotted name: "deps.get_user" -> "get_user"."""
    return name.split(".")[-1]


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


# Words in the names of dependencies that only hand over a database session, settings or a client.
_PLUMBING_WORDS = {
    "get", "async", "sync", "db", "database", "session", "sessions", "settings", "config",
    "logger", "redis", "cache", "context", "engine", "client", "request",
}  # fmt: skip


def _is_plumbing(name: str) -> bool:
    return set(_normalise(name.split(".")[-1]).split("_")) <= _PLUMBING_WORDS
