"""Detector for GitHub Actions: pinned actions, timeouts, permissions, concurrency.

Reads workflows in .github/workflows and composite actions (action.yml files under
.github/actions and at the repository root) with yaml.safe_load only. Needs PyYAML;
without it the detector prints a message and returns nothing.
"""

import os
import re
import sys
from pathlib import Path

DETECTOR = "github_actions"
MAX_BYTES = 1_000_000
MAX_ACTION_DEPTH = 6
# A git commit SHA, or a Docker image digest. Both name exactly one immutable thing.
SHA_RE = re.compile(r"^([0-9a-fA-F]{40}|sha256:[0-9a-fA-F]{64})$")
YAML_SUFFIXES = (".yml", ".yaml")


def extract(repo_root: str) -> list[dict]:
    try:
        import yaml
    except ImportError:
        print(
            "github_actions: PyYAML is not installed, so this detector is skipped. "
            "Install it with: pip install PyYAML",
            file=sys.stderr,
        )
        return []

    root = Path(repo_root).resolve()
    items = []
    for path in _workflow_files(root):
        loaded = _load(yaml, path)
        if loaded is not None:
            text, data = loaded
            items.extend(_workflow_items(path.relative_to(root).as_posix(), data, text))
    for path in _action_files(root):
        loaded = _load(yaml, path)
        if loaded is not None:
            text, data = loaded
            items.extend(_action_items(path.relative_to(root).as_posix(), data, text))
    return items


def _load(yaml, path: Path):
    """(text, parsed YAML) for a mapping, or None for anything unreadable or not a mapping."""
    try:
        # utf-8-sig drops a byte order mark, which editors on Windows often add.
        text = path.read_text(encoding="utf-8-sig")
        data = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError, ValueError, RecursionError, MemoryError):
        # ValueError: PyYAML raises it for dates that do not exist, such as 2021-02-30.
        return None  # one unreadable or hostile file must not stop the rest
    return (text, data) if isinstance(data, dict) else None


def _inside(path: Path, root: Path) -> bool:
    """True if path, with links and junctions followed, is still inside root.

    Windows junctions are not symlinks, so is_symlink() does not catch them.
    """
    try:
        return path.resolve().is_relative_to(root)
    except (OSError, RuntimeError):
        return False


def _usable(path: Path, root: Path) -> bool:
    """A regular file of a sensible size, inside the repository.

    Symlinks and junctions could point outside the repository, so they are skipped.
    """
    try:
        return (
            path.is_file()
            and not path.is_symlink()
            and _inside(path, root)
            and path.stat().st_size <= MAX_BYTES
        )
    except OSError:
        return False


def _workflow_files(root: Path) -> list[Path]:
    folder = root / ".github" / "workflows"
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return []
    return [p for p in entries if p.suffix in YAML_SUFFIXES and _usable(p, root)]


def _action_files(root: Path) -> list[Path]:
    """action.yml files: the repository's own, and those in .github/actions."""
    found = [root / f"action{suffix}" for suffix in YAML_SUFFIXES]
    base = root / ".github" / "actions"
    if base.is_dir() and not base.is_symlink() and _inside(base, root):
        for dirpath, dirnames, filenames in os.walk(base):
            depth = len(Path(dirpath).relative_to(base).parts)
            dirnames[:] = (
                sorted(d for d in dirnames if _inside(Path(dirpath) / d, root))
                if depth < MAX_ACTION_DEPTH
                else []
            )
            found.extend(
                Path(dirpath) / name for name in sorted(filenames) if name in _ACTION_NAMES
            )
    return [p for p in found if _usable(p, root)]


_ACTION_NAMES = {f"action{suffix}" for suffix in YAML_SUFFIXES}


def _workflow_items(rel, data, text):
    lines = text.splitlines()
    jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
    items = [_workflow_item(rel, data, jobs)]
    jobs_line = _line_of(lines, r"^['\"]?jobs['\"]?\s*:", regex=True)
    # Job ids sit at one indent. Matching only that indent keeps a nested key with the same
    # name, such as a matrix variable, from being taken for the job.
    indent = _first_child_indent(lines, jobs_line)
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        key = re.escape(str(job_id))
        job_line = _line_of(lines, rf"^{indent}['\"]?{key}['\"]?\s*:", start=jobs_line, regex=True)
        if isinstance(job.get("uses"), str):
            # A call to a reusable workflow has no timeout or steps of its own,
            # but the workflow it calls should be pinned like any action.
            if _judgeable(job["uses"]):
                line = _line_of(lines, job["uses"], start=job_line - 1)
                items.append(_uses_item(rel, job["uses"], line, job.get("name")))
            continue
        items.append(_job_item(rel, data, str(job_id), job, job_line))
        items.extend(_step_items(rel, job.get("steps"), lines, job_line))
    return items


def _action_items(rel, data, text):
    """Third-party steps of a composite action. Other kinds of action have no steps."""
    runs = data.get("runs")
    if not isinstance(runs, dict) or runs.get("using") != "composite":
        return []
    lines = text.splitlines()
    steps_line = _line_of(lines, r"^\s+['\"]?steps['\"]?\s*:", regex=True)
    return _step_items(rel, runs.get("steps"), lines, steps_line)


def _workflow_item(rel, data, jobs):
    job_dicts = [j for j in jobs.values() if isinstance(j, dict)]
    # Permissions set on every job limit the token as well as a workflow-level block does.
    every_job_scoped = bool(job_dicts) and all("permissions" in j for j in job_dicts)
    return {
        "detector": DETECTOR,
        "peer_group": "gha_workflows",
        "item_id": rel,
        "file": rel,
        "line": 1,
        "features": {
            "has_permissions_block": "permissions" in data
            or every_job_scoped
            or _only_reusable(data)
        },
        "context": {"name": _short_text(data.get("name"))},
    }


def _job_item(rel, data, job_id, job, line):
    return {
        "detector": DETECTOR,
        "peer_group": "gha_jobs",
        "item_id": job_id,
        "file": rel,
        "line": line,
        "features": {
            "has_timeout_minutes": "timeout-minutes" in job or _only_gathers_results(job),
            # Workflow-level concurrency covers every job, like workflow-level permissions.
            "has_concurrency": "concurrency" in job or "concurrency" in data,
        },
        "context": {"runs_on": _short_text(job.get("runs-on"))},
    }


def _only_reusable(data) -> bool:
    """True for a workflow that is only called by others. It runs with the caller's permissions."""
    events = data.get("on", data.get(True))  # YAML reads a bare `on:` key as True
    if isinstance(events, dict):
        return set(events) == {"workflow_call"}
    if isinstance(events, list):
        return events == ["workflow_call"]
    return events == "workflow_call"


def _only_gathers_results(job) -> bool:
    """True for a job whose steps only run alls-green, which exists to gather other jobs' results.

    Such a job finishes at once, so a timeout on it protects nothing.
    """
    steps = job.get("steps")
    return (
        isinstance(steps, list)
        and bool(steps)
        and all(
            isinstance(s, dict)
            and isinstance(s.get("uses"), str)
            and s["uses"].lower().startswith("re-actors/alls-green")
            for s in steps
        )
    )


def _step_items(rel, steps, lines, start_line):
    items = []
    if not isinstance(steps, list):
        return items
    cursor = start_line - 1  # search forward so repeated steps get their own lines
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("uses"), str):
            continue
        uses = step["uses"].strip()
        if not _judgeable(uses):
            continue
        line = _line_of(lines, uses, start=cursor)
        cursor = line
        items.append(_uses_item(rel, uses, line, step.get("name")))
    return items


def _uses_item(rel, uses, line, name):
    ref = uses.rsplit("@", 1)[1] if "@" in uses else ""
    return {
        "detector": DETECTOR,
        "peer_group": "gha_third_party_steps",
        "item_id": uses,
        "file": rel,
        "line": line,
        "features": {"pinned_to_sha": bool(SHA_RE.match(ref))},
        "context": {"step_name": None if name is None else _short_text(name)},
    }


_SHOWN_CHARS = 200
_NODE_BUDGET = 500


def _short_text(value) -> str:
    """str() of a parsed YAML value, with a size limit.

    YAML aliases make one object appear in many places, so a value can expand to an
    exponential number of nodes. str() would walk all of them, so this stops after a fixed
    number of nodes and shortens the text.
    """
    budget = [_NODE_BUDGET]

    def walk(node, nested: bool) -> str:
        if budget[0] <= 0:
            return "..."
        budget[0] -= 1
        if isinstance(node, dict):
            inner = ", ".join(f"{walk(k, True)}: {walk(v, True)}" for k, v in node.items())
            return "{" + inner + "}"
        if isinstance(node, list):
            return "[" + ", ".join(walk(v, True) for v in node) + "]"
        return repr(node) if nested else str(node)

    return walk(value, False)[:_SHOWN_CHARS]


def _judgeable(uses: str) -> bool:
    """False for local references and for references built from expressions.

    A local action lives in this repository, so there is nothing to pin. A reference such
    as actions/checkout@${{ inputs.ref }} is decided at run time and cannot be judged here.
    """
    return not _is_local(uses) and "${{" not in uses


def _is_local(uses: str) -> bool:
    """True for a workflow or action stored in this repo.

    "./" is the usual form. "$/" is what cargo-dist writes for the same thing.
    """
    return uses.startswith(("./", "$/"))


def _first_child_indent(lines, parent_line):
    """Regex for the indent of the first line under a key; any indent if there is none."""
    for text in lines[parent_line:]:
        stripped = text.strip()
        if stripped and not stripped.startswith("#"):
            return f" {{{len(text) - len(text.lstrip(' '))}}}"
    return r"\s+"


def _line_of(lines, needle, start=0, regex=False):
    """1-based line number of the first match at or after start; 1 if not found."""
    for index in range(max(start, 0), len(lines)):
        found = re.search(needle, lines[index]) if regex else needle in lines[index]
        if found:
            return index + 1
    return 1
