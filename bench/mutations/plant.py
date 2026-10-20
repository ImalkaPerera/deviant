"""Plant known bugs in pinned copies of the benchmark repos, and record each one.

Usage: python plant.py <clones dir> <out dir> [repos file]

<clones dir> holds one shallow clone per repo, named owner__repo, at the commit in repos.json.
<out dir> receives a mutated copy per repo, plus manifest.json. Nothing is written to the
clones, so they can be reused.

Two kinds of planted bug:
- same kind: the bug is something a detector checks (a route missing its auth dependency,
  a job missing timeout-minutes). The detector should flag it.
- other kind: the bug is something no detector checks (an inverted `if not`, a step that
  ignores its failure). Used to see what the tool cannot find.

Every mutation is random-free: candidates are sorted, then picked at even spacing, so a
rerun gives the same bugs. A mutation is kept only if the file still parses.

Candidates are chosen with keyword rules written here, not with the detector. The detector
is measured afterwards. Choosing bugs with the tool under test would inflate its score.
Candidates are skipped if the route checks credentials in its own body, because removing a
dependency from such a route does not remove all its auth.
"""

import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace", "api_route"}
DEPENDENCY_CALLS = {"Depends", "Security"}
PER_REPO = {"same_fastapi": 8, "other_fastapi": 6, "same_gha": 8, "other_gha": 6}


def spaced(items, count):
    """Pick `count` items spread evenly through a sorted list. Deterministic."""
    if len(items) <= count:
        return list(items)
    step = len(items) / count
    return [items[int(i * step)] for i in range(count)]


def read_source(path):
    """Read a file without changing its line endings."""
    return path.read_bytes().decode("utf-8")


def write_source(path, text):
    path.write_bytes(text.encode("utf-8"))


def sha_of(repo_dir):
    return subprocess.run(
        ["git", "-C", str(repo_dir), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def copy_tree(src, dst):
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git"))


def call_name(node):
    if isinstance(node, ast.Call):
        node = node.func
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


# --- FastAPI ------------------------------------------------------------------------------


# Names of auth-like dependencies, written here on purpose and NOT taken from the detector,
# so the planted bugs are not chosen by the tool they test.
AUTH_NAME = re.compile(
    r"auth|user|current|token|require|permission|admin|verify|security|login|"
    r"api_?key|jwt|oauth|role|scope|guard",
    re.IGNORECASE,
)


# A route body that checks credentials itself still has auth after its dependency is removed,
# so such routes are not valid planted bugs.
BODY_AUTH = re.compile(
    r"require|verify|authenticat|authoriz|permission|scope|guard|compare_digest|jwt|csrf|"
    r"\b40[13]\b",
    re.IGNORECASE,
)


# Names that contain an auth word but are not auth: ID resolvers and lookups such as
# resolve_triggered_by_user_id, which only read a value from the request.
NOT_AUTH = re.compile(r"resolve|_id\b|_ids\b|lookup|fetch|get_by|filter", re.IGNORECASE)


def dependency_target(call):
    target = call.args[0] if call.args else None
    if isinstance(target, ast.Call):
        target = target.func
    if isinstance(target, ast.Attribute):
        return target.attr
    if isinstance(target, ast.Name):
        return target.id
    return ""


def fastapi_candidates(root):
    """Routes whose only dependency is one auth-named Depends, in files with no router-level deps.

    Removing that dependency removes the route's only auth. Files with dependencies= are skipped
    so that auth set above the route cannot hide the planted bug.
    """
    found = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".venv", "venv", "node_modules", "tests", "test"} for part in path.parts):
            continue
        try:
            source = read_source(path)
            tree = ast.parse(source)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        if "dependencies=" in source:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            is_route = any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in ROUTE_METHODS
                for d in node.decorator_list
            )
            if not is_route:
                continue
            deps = [
                d
                for d in node.args.defaults + [k for k in node.args.kw_defaults if k is not None]
                if isinstance(d, ast.Call) and call_name(d) in DEPENDENCY_CALLS
            ]
            if len(deps) == 1 and deps[0].lineno == deps[0].end_lineno:
                body = ast.get_source_segment(source, node) or ""
                name = dependency_target(deps[0])
                if (
                    AUTH_NAME.search(name)
                    and not NOT_AUTH.search(name)
                    and not BODY_AUTH.search(body)
                ):
                    found.append((path, node, deps[0]))
    return found


def plant_fastapi_same(root, manifest, repo):
    cands = fastapi_candidates(root)
    chosen = spaced(cands, PER_REPO["same_fastapi"])
    for path, node, dep in chosen:
        lines = read_source(path).split("\n")
        i = dep.lineno - 1
        original = lines[i]
        segment = ast.get_source_segment("\n".join(lines), dep)
        if segment is None or segment not in original:
            continue
        lines[i] = original.replace(segment, "None", 1)
        text = "\n".join(lines)
        try:
            ast.parse(text)
        except SyntaxError:
            continue
        write_source(path, text)
        manifest.append(
            {
                "id": f"{repo}:same_fastapi:{path.relative_to(root).as_posix()}:{dep.lineno}",
                "repo": repo,
                "kind": "same",
                "category": "fastapi_auth_dependency_removed",
                "file": path.relative_to(root).as_posix(),
                "line": dep.lineno,
                "function": node.name,
                "original": original.strip(),
                "mutated": lines[i].strip(),
            }
        )


def plant_fastapi_other(root, manifest, repo):
    """Invert an `if not X:` in a route body. Syntax stays valid, no detector checks it."""
    sites = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".venv", "venv", "node_modules", "tests", "test"} for part in path.parts):
            continue
        try:
            text = read_source(path)
            tree = ast.parse(text)
        except (SyntaxError, UnicodeDecodeError, ValueError):
            continue
        lines = text.split("\n")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(d, ast.Call)
                and isinstance(d.func, ast.Attribute)
                and d.func.attr in ROUTE_METHODS
                for d in node.decorator_list
            ):
                continue
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.If)
                    and isinstance(sub.test, ast.UnaryOp)
                    and isinstance(sub.test.op, ast.Not)
                ):
                    line = lines[sub.lineno - 1]
                    if re.search(r"\bif not\b", line):
                        sites.append((path, sub.lineno, line))
                        break
    for path, lineno, original in spaced(sites, PER_REPO["other_fastapi"]):
        lines = read_source(path).split("\n")
        lines[lineno - 1] = original.replace("if not ", "if ", 1)
        text = "\n".join(lines)
        try:
            ast.parse(text)
        except SyntaxError:
            continue
        write_source(path, text)
        manifest.append(
            {
                "id": f"{repo}:other_fastapi:{path.relative_to(root).as_posix()}:{lineno}",
                "repo": repo,
                "kind": "other",
                "category": "inverted_condition_in_route",
                "file": path.relative_to(root).as_posix(),
                "line": lineno,
                "original": original.strip(),
                "mutated": lines[lineno - 1].strip(),
            }
        )


# --- GitHub Actions -----------------------------------------------------------------------


def workflow_files(root):
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return []
    return sorted(p for p in wf.iterdir() if p.suffix in {".yml", ".yaml"})


def plant_gha_same(root, manifest, repo):
    """Delete one job-level timeout-minutes line."""
    sites = []
    for path in workflow_files(root):
        lines = read_source(path).split("\n")
        for i, line in enumerate(lines):
            m = re.match(r"^(\s{4})timeout-minutes:\s*\S+\s*$", line)
            if m:
                sites.append((path, i, line))
    for path, i, line in spaced(sites, PER_REPO["same_gha"]):
        lines = read_source(path).split("\n")
        if lines[i] != line:
            continue
        del lines[i]
        text = "\n".join(lines)
        try:
            import yaml

            yaml.safe_load(text)
        except Exception:
            continue
        write_source(path, text)
        manifest.append(
            {
                "id": f"{repo}:same_gha:{path.relative_to(root).as_posix()}:{i + 1}",
                "repo": repo,
                "kind": "same",
                "category": "gha_job_timeout_removed",
                "file": path.relative_to(root).as_posix(),
                "line": i + 1,
                "original": line.strip(),
                "mutated": None,
            }
        )


# Commands that cannot fail in a way that matters. Planting "ignore failure" on these changes
# nothing, so they are not valid planted bugs.
NEVER_FAILS = re.compile(r"^(echo|printf|exit 0|true|chmod)\b")


def _indent(text):
    return len(text) - len(text.lstrip())


def step_sets_continue_on_error(lines, run_index):
    """True if the step that holds this run: line already sets continue-on-error.

    A step starts at a "- " item marker. Its block runs until the next item marker at the same
    or a lower indent.
    """
    run_indent = _indent(lines[run_index])
    start = run_index
    while start > 0:
        text = lines[start]
        if text.lstrip().startswith("- ") and _indent(text) < run_indent:
            break
        start -= 1
    item_indent = _indent(lines[start])
    end = run_index + 1
    while end < len(lines):
        text = lines[end]
        if text.strip() and text.lstrip().startswith("- ") and _indent(text) <= item_indent:
            break
        end += 1
    return any("continue-on-error" in lines[k] for k in range(start, end))


def plant_gha_other(root, manifest, repo):
    """Add `continue-on-error: true` after a single-line `run:`. No detector checks it."""
    sites = []
    for path in workflow_files(root):
        lines = read_source(path).split("\n")
        for i, line in enumerate(lines):
            m = re.match(r"^(\s+)run:\s+([^|>\s].*)$", line)
            if not m or NEVER_FAILS.match(m.group(2)):
                continue
            if step_sets_continue_on_error(lines, i):
                continue
            sites.append((path, i, m.group(1)))
    for path, i, indent in spaced(sites, PER_REPO["other_gha"]):
        lines = read_source(path).split("\n")
        original = lines[i]
        eol = "\r" if original.endswith("\r") else ""
        lines.insert(i + 1, f"{indent}continue-on-error: true{eol}")
        text = "\n".join(lines)
        try:
            import yaml

            yaml.safe_load(text)
        except Exception:
            continue
        write_source(path, text)
        manifest.append(
            {
                "id": f"{repo}:other_gha:{path.relative_to(root).as_posix()}:{i + 1}",
                "repo": repo,
                "kind": "other",
                "category": "gha_step_ignores_failure",
                "file": path.relative_to(root).as_posix(),
                "line": i + 2,
                "original": original.strip(),
                "mutated": "continue-on-error: true",
            }
        )


# --- driver -------------------------------------------------------------------------------


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    clones, out = Path(argv[1]), Path(argv[2])
    repos_file = Path(argv[3]) if len(argv) == 4 else HERE.parent / "repos.json"
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(repos_file.read_text(encoding="utf-8"))
    manifest, problems = [], []
    for repo in data["repos"]:
        name = repo["name"]
        src = clones / name.replace("/", "__")
        if not src.is_dir():
            problems.append(f"{name}: clone missing")
            continue
        head = sha_of(src)
        if head != repo["commit"]:
            problems.append(f"{name}: clone is {head[:10]}, pinned is {repo['commit'][:10]}")
            continue
        dst = out / name.replace("/", "__")
        copy_tree(src, dst)
        if repo["kind"] == "fastapi":
            plant_fastapi_same(dst, manifest, name)
            plant_fastapi_other(dst, manifest, name)
        else:
            plant_gha_same(dst, manifest, name)
            plant_gha_other(dst, manifest, name)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    counts = {}
    for m in manifest:
        counts[(m["kind"], m["category"])] = counts.get((m["kind"], m["category"]), 0) + 1
    for key, n in sorted(counts.items()):
        print(f"{key[0]:6} {key[1]:34} {n}")
    for p in problems:
        print("PROBLEM:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
