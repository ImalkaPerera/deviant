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
from pathlib import Path

DETECTOR = "python_routes"
PEER_GROUP = "fastapi_routes"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ROUTER_CALLS = {"APIRouter", "FastAPI"}
DEPENDENCY_CALLS = {"Depends", "Security"}
AUTH_WORDS = {
    "auth",
    "authenticate",
    "authorize",
    "token",
    "verify",
    "require",
    "permission",
    "admin",
    "current_user",
}
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
    routers = _find_routers(trees)
    _add_include_dependencies(trees, index, routers)
    items = []
    for rel, tree in trees.items():
        items.extend(_routes_in_file(rel, tree, routers, extra_auth))
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
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            if not name.endswith(".py"):
                continue
            path = Path(dirpath) / name
            if path.is_symlink() or path.stat().st_size > MAX_BYTES:
                continue
            rel = path.relative_to(root).as_posix()
            try:
                trees[rel] = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
            except (SyntaxError, ValueError, UnicodeDecodeError):
                continue
    return trees


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


def _find_routers(trees):
    routers = {}
    for rel, tree in trees.items():
        for node in tree.body:
            if not (
                isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Call)
                and _last_name(node.value.func) in ROUTER_CALLS
            ):
                continue
            routers[(rel, node.targets[0].id)] = {
                "deps": _keyword_dependencies(node.value),
                "include": [],
            }
    return routers


def _add_include_dependencies(trees, index, routers):
    for rel, tree in trees.items():
        imports = _imports(tree, rel)
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "include_router"
                and node.args
            ):
                continue
            target = _resolve_router(node.args[0], rel, imports, index, routers)
            if target is not None:
                routers[target]["include"].extend(_keyword_dependencies(node))


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


def _routes_in_file(rel, tree, routers, extra_auth):
    items = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            route = _route_decorator(dec)
            if route is None:
                continue
            router_name, method, path = route
            info = routers.get((rel, router_name))
            if info is None:
                continue
            names = info["deps"] + info["include"] + _depends_names(dec)
            for default in node.args.defaults + [d for d in node.args.kw_defaults if d]:
                names += _depends_names(default)
            for arg in _all_args(node.args):
                if arg.annotation is not None:
                    names += _depends_names(arg.annotation)
            rate_decorator = any(
                _is_rate(_dotted(d.func if isinstance(d, ast.Call) else d) or "")
                for d in node.decorator_list
                if d is not dec
            )
            features = {
                "is_mutating": method in MUTATING,
                "has_auth": any(_is_auth(n, extra_auth) for n in names),
                "has_response_model": isinstance(dec, ast.Call)
                and any(kw.arg == "response_model" for kw in dec.keywords),
                "has_rate_limit": rate_decorator or any(_is_rate(n) for n in names),
            }
            items.append(
                {
                    "detector": DETECTOR,
                    "peer_group": PEER_GROUP,
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
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _matches(name: str, words) -> bool:
    """True if a word appears as whole words in the name, so "authors" does not match "auth"."""
    padded = f"_{_normalise(name)}_"
    return any(f"_{_normalise(w)}_" in padded for w in words)


def _is_auth(name: str, extra_auth: set[str]) -> bool:
    return _matches(name, AUTH_WORDS | extra_auth)


def _is_rate(name: str) -> bool:
    return _matches(name, RATE_WORDS)
