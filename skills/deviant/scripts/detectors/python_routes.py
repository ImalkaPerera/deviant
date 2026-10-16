"""Detector for FastAPI routes: auth, rate limits, response models, and mutation.

Reads Python source with the ast module only. Never imports or runs project code.
Auth can come from the route, its parameters, its router, any include_router call
that adds the router to the app, or the FastAPI app itself. Those levels are
followed across files by module name.
"""

import ast
import json
import os
import re
import sys
from pathlib import Path

DETECTOR = "python_routes"
PEER_GROUP = "fastapi_routes"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ROUTER_CALLS = {"APIRouter", "FastAPI"}
DEPENDENCY_CALLS = {"Depends", "Security"}
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
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}


def extract(repo_root: str) -> list[dict]:
    root = Path(repo_root).resolve()
    extra_auth = _extra_auth_words(root)
    trees = _parse_files(root)
    index = _module_index(trees)
    imports = {rel: _imports(tree, rel) for rel, tree in trees.items()}
    routers = _find_routers(trees)
    _add_include_edges(trees, index, imports, routers)
    aliases = _find_dependency_aliases(trees)
    items = []
    for rel, tree in trees.items():
        resolver = _AliasResolver(rel, imports[rel], index, aliases)
        items.extend(_routes_in_file(rel, tree, routers, resolver, extra_auth))
    return items


def _extra_auth_words(root: Path) -> set[str]:
    """Words the user adds in .deviant/config.json under "auth_words"."""
    try:
        config = json.loads((root / ".deviant" / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    words = config.get("auth_words", []) if isinstance(config, dict) else []
    return {_normalise(w) for w in words if isinstance(w, str) and w.strip()}


def _parse_files(root: Path) -> dict[str, ast.Module]:
    trees = {}
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
                # Parse bytes so a UTF-8 BOM or a coding cookie is handled like Python does.
                trees[rel] = ast.parse(path.read_bytes(), filename=rel)
            except OSError:
                continue
            except (SyntaxError, ValueError):
                if not _looks_like_template(path):
                    failed.append(rel)
    if failed:
        # A skipped file can hide the auth helpers other files import, so say so.
        version = ".".join(map(str, sys.version_info[:2]))
        shown = ", ".join(failed[:3]) + (" ..." if len(failed) > 3 else "")
        print(
            f"python_routes: could not parse {len(failed)} file(s) with Python {version}: "
            f"{shown}. They may use newer syntax; results that depend on them can be wrong.",
            file=sys.stderr,
        )
    return trees


def _looks_like_template(path: Path) -> bool:
    """Jinja and similar templates are not Python until rendered; skip them without a warning."""
    try:
        head = path.read_bytes()[:20_000]
    except OSError:
        return False
    return b"{%" in head or b"{{" in head


def _module_name(rel: str) -> str:
    parts = rel[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_index(trees) -> dict[str, str | None]:
    """Map every dotted suffix of a module name to its file. Ambiguous suffixes map to None."""
    index: dict[str, str | None] = {}
    for rel in trees:
        segments = _module_name(rel).split(".")
        for i in range(len(segments)):
            key = ".".join(segments[i:])
            if key in index and index[key] != rel:
                index[key] = None
            else:
                index.setdefault(key, rel)
    return index


def _assigned_name(node):
    """(name, value) for `x = value` or `x: T = value`, else None."""
    if isinstance(node, ast.Assign) and len(node.targets) == 1:
        target = node.targets[0]
    elif isinstance(node, ast.AnnAssign) and node.value is not None:
        target = node.target
    else:
        return None
    if isinstance(target, ast.Name):
        return target.id, node.value
    return None


def _find_routers(trees):
    """Routers and apps by (file, variable). Module-level names win over ones in functions."""
    routers = {}
    for rel, tree in trees.items():
        top_level = {id(n) for n in tree.body}
        nested = [n for n in ast.walk(tree) if id(n) not in top_level]
        for node in list(tree.body) + nested:
            assigned = _assigned_name(node)
            if assigned is None:
                continue
            name, value = assigned
            if not (isinstance(value, ast.Call) and _last_name(value.func) in ROUTER_CALLS):
                continue
            routers.setdefault((rel, name), {"deps": _keyword_dependencies(value), "parents": []})
    return routers


def _add_include_edges(trees, index, imports, routers):
    """Record each include_router call as (parent router, dependencies added) on the child."""
    for rel, tree in trees.items():
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"
                and node.args
            ):
                continue
            child = _resolve_router(node.args[0], rel, imports[rel], index, routers)
            if child is None:
                continue
            parent = _resolve_router(node.func.value, rel, imports[rel], index, routers)
            routers[child]["parents"].append((parent, _keyword_dependencies(node)))


def _effective_dependencies(key, routers, seen=None):
    """Dependencies a router's routes get from the router and every router that includes it.

    A router included in several places gets the union of all of them.
    """
    seen = set() if seen is None else seen
    if key in seen:
        return []
    seen.add(key)
    info = routers[key]
    names = list(info["deps"])
    for parent, added in info["parents"]:
        names += added
        if parent is not None:
            names += _effective_dependencies(parent, routers, seen)
    return names


def _find_dependency_aliases(trees):
    """Module-level aliases like CurrentUser = Annotated[User, Depends(get_current_user)].

    Maps (file, name) to (dependency names, type names). Type names are every name in the
    alias, so `Annotated[AuthSubject[User], Depends(check)]` also records AuthSubject.
    """
    aliases = {}
    for rel, tree in trees.items():
        for node in tree.body:
            assigned = _assigned_name(node)
            if assigned is None:
                continue
            name, value = assigned
            if isinstance(value, ast.Subscript) and _last_name(value.value) == "Annotated":
                deps = _depends_names(value)
                types = _type_names(value)
                if deps or types:
                    aliases[(rel, name)] = (deps, types)
    return aliases


def _type_names(expr) -> list[str]:
    """Dotted names of every Name and Attribute in an annotation."""
    names = []
    for node in ast.walk(expr):
        if isinstance(node, (ast.Name, ast.Attribute)):
            dotted = _dotted(node)
            if dotted:
                names.append(dotted)
    return names


class _AliasResolver:
    """Finds the dependencies behind an alias used in a route parameter annotation."""

    def __init__(self, rel, imports, index, aliases):
        self.rel, self.imports, self.index, self.aliases = rel, imports, index, aliases

    def names_in(self, annotation) -> tuple[list[str], list[str]]:
        """(dependency names, type names) behind any aliases used in the annotation."""
        deps, types = [], []
        for node in ast.walk(annotation):
            key = self._alias_key(node)
            if key is not None:
                alias_deps, alias_types = self.aliases[key]
                deps += alias_deps
                types += alias_types
        return deps, types

    def _alias_key(self, node):
        if isinstance(node, ast.Name):
            if (self.rel, node.id) in self.aliases:
                return (self.rel, node.id)
            imported = self.imports.get(node.id)
            if imported and imported["from"]:
                module, name = imported["from"]
                target = self.index.get(module)
                if target and (target, name) in self.aliases:
                    return (target, name)
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            imported = self.imports.get(node.value.id)
            if imported:
                target = self.index.get(imported["full"])
                if target and (target, node.attr) in self.aliases:
                    return (target, node.attr)
        return None


def _imports(tree, rel):
    """Top-level import aliases: alias -> {"full": dotted name, "from": (module, name) or None}."""
    package = _module_name(rel).split(".")
    if not rel.endswith("__init__.py"):
        package = package[:-1]
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                out[alias.asname or alias.name.split(".")[0]] = {
                    "full": alias.name,
                    "from": None,
                }
        elif isinstance(node, ast.ImportFrom):
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


def _resolve_router(expr, rel, imports, index, routers):
    """Find the (file, variable) a router expression refers to, or None."""
    if isinstance(expr, ast.Name):
        if (rel, expr.id) in routers:
            return (rel, expr.id)
        imported = imports.get(expr.id)
        if imported and imported["from"]:
            module, name = imported["from"]
            target = index.get(module)
            if target and (target, name) in routers:
                return (target, name)
        return None
    if isinstance(expr, ast.Attribute) and isinstance(expr.value, ast.Name):
        imported = imports.get(expr.value.id)
        if imported:
            target = index.get(imported["full"])
            if target and (target, expr.attr) in routers:
                return (target, expr.attr)
    return None


def _routes_in_file(rel, tree, routers, resolver, extra_auth):
    items = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            route = _route_decorator(dec)
            if route is None:
                continue
            router_name, method, path = route
            if (rel, router_name) not in routers:
                continue
            names = _effective_dependencies((rel, router_name), routers) + _depends_names(dec)
            types: list[str] = []
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
                names += _depends_names(default)
            for arg in _all_args(node.args):
                if arg.annotation is not None:
                    alias_deps, alias_types = resolver.names_in(arg.annotation)
                    names += _depends_names(arg.annotation) + alias_deps
                    types += alias_types + _type_names(arg.annotation)
            rate_decorator = any(
                _is_rate(_dotted(d.func if isinstance(d, ast.Call) else d) or "")
                for d in node.decorator_list
                if d is not dec
            )
            features = {
                "is_mutating": method in MUTATING,
                "has_auth": any(_is_auth(n, extra_auth) for n in names)
                or any(_matches(t, AUTH_TYPE_WORDS) for t in types),
                "has_response_model": isinstance(dec, ast.Call)
                and any(kw.arg == "response_model" for kw in dec.keywords),
                "has_rate_limit": rate_decorator or any(_is_rate(n) for n in names),
            }
            items.append(
                {
                    "detector": DETECTOR,
                    # Routes are compared within their own folder. A whole repo often mixes
                    # auth styles, so a repo-wide rule rarely holds; a folder usually does.
                    "peer_group": f"{PEER_GROUP}:{_folder(rel)}",
                    "item_id": f"{method} {path}",
                    "file": rel,
                    "line": node.lineno,
                    "features": features,
                    "context": {
                        "function_name": node.name,
                        "decorators": [ast.unparse(d) for d in node.decorator_list],
                        "comments_near": [],
                    },
                }
            )
    return items


def _folder(rel: str) -> str:
    """Folder of a file, relative to the scanned root. Files at the root give "."."""
    folder = rel.rsplit("/", 1)[0] if "/" in rel else "."
    return folder


def _route_decorator(dec):
    """Return (router variable, HTTP method, path) for @router.get("/x") style decorators."""
    if not (
        isinstance(dec, ast.Call)
        and isinstance(dec.func, ast.Attribute)
        and dec.func.attr in ROUTE_METHODS
        and isinstance(dec.func.value, ast.Name)
    ):
        return None
    path = "<dynamic>"
    if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
        path = dec.args[0].value
    return dec.func.value.id, dec.func.attr.upper(), path


def _all_args(args: ast.arguments):
    return list(args.posonlyargs) + list(args.args) + list(args.kwonlyargs)


def _keyword_dependencies(call: ast.Call) -> list[str]:
    names = []
    for kw in call.keywords:
        if kw.arg == "dependencies":
            names += _depends_names(kw.value)
    return names


def _depends_names(expr) -> list[str]:
    """Names of callables used in Depends(...) or Security(...) anywhere in expr."""
    names = []
    for node in ast.walk(expr):
        if not isinstance(node, ast.Call) or _last_name(node.func) not in DEPENDENCY_CALLS:
            continue
        if not node.args:
            continue
        target = node.args[0]
        if isinstance(target, ast.Call):  # Depends(RoleChecker(["admin"])) -> RoleChecker
            target = target.func
        name = _dotted(target)
        if name:
            names.append(name)
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
    return any(set(pair) <= words for pair in AUTH_WORD_PAIRS)


def _matches_auth_type(name: str) -> bool:
    return _matches(name, AUTH_TYPE_WORDS)


def _is_rate(name: str) -> bool:
    return _matches(name, RATE_WORDS)
