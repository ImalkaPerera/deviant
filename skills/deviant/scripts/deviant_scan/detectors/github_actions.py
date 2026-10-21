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
            try:
                items.extend(
                    _workflow_items(
                        path.relative_to(root).as_posix(), data, text, _step_lines(yaml, text)
                    )
                )
            except (RecursionError, MemoryError):
                _skipped(path, "is too deeply nested to read")
    for path in _action_files(root):
        loaded = _load(yaml, path)
        if loaded is not None:
            text, data = loaded
            try:
                items.extend(
                    _action_items(
                        path.relative_to(root).as_posix(), data, text, _step_lines(yaml, text)
                    )
                )
            except (RecursionError, MemoryError):
                _skipped(path, "is too deeply nested to read")
    return items


def _load(yaml, path: Path):
    """(text, parsed YAML) for a mapping, or None for anything unreadable or not a mapping."""
    try:
        # utf-8-sig drops a byte order mark, which editors on Windows often add.
        text = path.read_text(encoding="utf-8-sig")
        data = yaml.load(text, Loader=_workflow_loader(yaml))
    except (
        OSError,
        UnicodeDecodeError,
        yaml.YAMLError,
        ValueError,
        # PyYAML fails with AttributeError on a malformed !!timestamp.
        AttributeError,
        RecursionError,
        MemoryError,
    ) as error:
        # ValueError: PyYAML raises it for dates that do not exist, such as 2021-02-30.
        _skipped(path, f"could not be parsed ({type(error).__name__})")
        return None  # one unreadable or hostile file must not stop the rest
    if not isinstance(data, dict):
        _skipped(path, "is not a YAML mapping")
        return None
    return (text, data)


def _workflow_loader(yaml):
    """A safe loader that reads true, false, on, yes, no and null as plain text.

    YAML 1.1 reads a bare `on:` key or a job named `yes` as a boolean, and `null` as nothing.
    Either loses the job's name and hides it from the checks. GitHub reads these words as text,
    so the loader does too.
    """

    class Loader(yaml.SafeLoader):
        pass

    plain_tags = {"tag:yaml.org,2002:bool", "tag:yaml.org,2002:null"}
    Loader.yaml_implicit_resolvers = {
        first: [(tag, pattern) for tag, pattern in resolvers if tag not in plain_tags]
        for first, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    return Loader


def _skipped(path: Path, reason: str) -> None:
    """Say on stderr that a file was left out, so a missing finding is never silent."""
    print(f"github_actions: {_show(path.name)} {reason} and was skipped", file=sys.stderr)


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
        if not (path.is_file() and not path.is_symlink() and _inside(path, root)):
            return False
        if path.stat().st_size > MAX_BYTES:
            _skipped(path, f"is larger than {MAX_BYTES} bytes")
            return False
        return True
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
    # A junction can lead to a folder already listed, so keep one path per real file.
    seen = set()
    unique = []
    for path in found:
        if not _usable(path, root):
            continue
        real = path.resolve()
        if real not in seen:
            seen.add(real)
            unique.append(path)
    return unique


_ACTION_NAMES = {f"action{suffix}" for suffix in YAML_SUFFIXES}


def _workflow_items(rel, data, text, step_lines=None):
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
        # The YAML position is exact and costs nothing per job. Searching the text for every
        # job would grow with the square of the number of jobs, so it is only the fallback.
        job_line = (step_lines or {}).get(("job", str(job_id)))
        if job_line is None:
            job_line = _line_of(
                lines, rf"^{indent}['\"]?{key}['\"]?\s*:", start=jobs_line, regex=True
            )
        if isinstance(job.get("uses"), str):
            # A call to a reusable workflow has no timeout or steps of its own,
            # but the workflow it calls should be pinned like any action.
            if _judgeable(job["uses"]):
                line = _line_of(lines, job["uses"], start=job_line - 1)
                items.append(_uses_item(rel, job["uses"], line, job.get("name")))
            continue
        items.append(_job_item(rel, data, str(job_id), job, job_line))
        items.extend(_step_items(rel, job.get("steps"), lines, job_line))
        items.extend(
            _run_step_items(rel, job.get("steps"), lines, job_line, str(job_id), step_lines)
        )
    return items


def _action_items(rel, data, text, step_lines=None):
    """Third-party steps of a composite action. Other kinds of action have no steps."""
    runs = data.get("runs")
    if not isinstance(runs, dict) or runs.get("using") != "composite":
        return []
    lines = text.splitlines()
    steps_line = _line_of(lines, r"^\s+['\"]?steps['\"]?\s*:", regex=True)
    return _step_items(rel, runs.get("steps"), lines, steps_line) + _run_step_items(
        rel, runs.get("steps"), lines, steps_line, "runs", step_lines
    )


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
            "has_timeout_minutes": _has_real_timeout(job) or _only_gathers_results(job),
            # Workflow-level concurrency covers every job, like workflow-level permissions.
            "has_concurrency": "concurrency" in job or "concurrency" in data,
        },
        "context": {"runs_on": _short_text(job.get("runs-on"))},
    }


def _has_real_timeout(job) -> bool:
    """True if the job sets timeout-minutes to something other than zero.

    Zero is not a limit: GitHub reads it as no time at all, so the check must not count it.
    """
    if "timeout-minutes" not in job:
        return False
    value = job["timeout-minutes"]
    # A mapping or list is not a number or an expression, and str() on one built from shared
    # anchors takes exponential time, so it is not read: it is no usable limit.
    if isinstance(value, (dict, list, tuple, set)):
        return False
    # An empty value (null) sets nothing, so it is not a limit.
    # The loader reads null as the text "null", and "~" is the same null, so both are no limit.
    if value is None or str(value).strip() in ("", "null", "~"):
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value > 0
    text = str(value).strip()
    # An expression is decided when the workflow runs, so it is taken as a limit.
    if "${{" in text:
        return True
    try:
        return float(text) > 0
    except ValueError:
        return True


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


def _run_step_items(rel, steps, lines, start_line, owner="", step_lines=None):
    """One item per shell step (`run:`), for whether it lets its failure pass.

    A step with continue-on-error: true ignores its own failure, so it is reported as lacking
    fails_on_error. Most run steps in a project fail on error, so a few that do not are leads.

    A step is named by its job and position ("build step 3"), so two steps never share an id
    even when their text is the same. Its line comes from the YAML positions in step_lines, and
    only falls back to a text search when those are missing.
    """
    items = []
    if not isinstance(steps, list):
        return items
    cursor = start_line - 1
    for index, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("run"), str):
            continue
        first = next((ln.strip() for ln in step["run"].splitlines() if ln.strip()), "")
        if not first:
            continue
        line = (step_lines or {}).get((owner, index))
        if line is None:
            line = _line_of(lines, first, start=cursor)
        cursor = line
        items.append(
            {
                "detector": DETECTOR,
                "peer_group": "gha_run_steps",
                "item_id": f"{owner} step {index + 1}" if owner else f"step {index + 1}",
                "file": rel,
                "line": line,
                "features": {"fails_on_error": not _continues_on_error(step)},
                "context": {"step_name": _short_text(step.get("name"))},
            }
        )
    return items


def _step_lines(yaml, text) -> dict:
    """{(job id or "runs", step index): line} for every step, from the YAML node positions.

    Reading positions from the parsed nodes is exact for folded blocks, escaped strings and
    aliases, where searching the source text for a step's first line is not.
    """
    positions = {}
    try:
        root = yaml.compose(text, Loader=_workflow_loader(yaml))
    except (yaml.YAMLError, ValueError, AttributeError, RecursionError, MemoryError):
        return positions
    if not isinstance(root, yaml.MappingNode):
        return positions

    def child(node, key):
        for k, v in node.value:
            if getattr(k, "value", None) == key:
                return v
        return None

    def record(owner, steps):
        if isinstance(steps, yaml.SequenceNode):
            for index, step in enumerate(steps.value):
                positions[(owner, index)] = step.start_mark.line + 1

    jobs = child(root, "jobs")
    if isinstance(jobs, yaml.MappingNode):
        for key, job in jobs.value:
            if isinstance(job, yaml.MappingNode) and hasattr(key, "value"):
                positions[("job", str(key.value))] = key.start_mark.line + 1
                record(str(key.value), child(job, "steps"))
    runs = child(root, "runs")
    if isinstance(runs, yaml.MappingNode):
        record("runs", child(runs, "steps"))
    return positions


def _continues_on_error(step) -> bool:
    """True when the step sets continue-on-error to true, so its failure is ignored."""
    value = step.get("continue-on-error")
    if isinstance(value, bool):
        return value
    return isinstance(value, str) and value.strip().lower() in ("true", "${{ true }}")


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
_MAX_DEPTH = 12


def _short_text(value) -> str:
    """str() of a parsed YAML value, with a size limit.

    YAML aliases make one object appear in many places, so a value can expand to an
    exponential number of nodes. str() would walk all of them, so this stops after a fixed
    number of nodes and shortens the text.
    """
    budget = [_NODE_BUDGET]

    def walk(node, nested: bool, depth: int = 0) -> str:
        if budget[0] <= 0 or depth > _MAX_DEPTH:
            return "..."
        budget[0] -= 1
        if isinstance(node, dict):
            inner = ", ".join(
                f"{walk(k, True, depth + 1)}: {walk(v, True, depth + 1)}" for k, v in node.items()
            )
            return "{" + inner + "}"
        if isinstance(node, list):
            return "[" + ", ".join(walk(v, True, depth + 1) for v in node) + "]"
        return repr(node) if nested else str(node)

    return walk(value, False)[:_SHOWN_CHARS]


def _judgeable(uses: str) -> bool:
    """False for local references and for references built from expressions.

    A local action lives in this repository, so there is nothing to pin. A reference such
    as actions/checkout@${{ inputs.ref }} is decided at run time and cannot be judged here.
    """
    # A blank reference names nothing, so there is nothing to judge.
    return bool(uses.strip()) and not _is_local(uses) and "${{" not in uses


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
        # A comment can repeat the text being searched for, so comment lines never match.
        if lines[index].lstrip().startswith("#"):
            continue
        found = re.search(needle, lines[index]) if regex else needle in lines[index]
        if found:
            return index + 1
    return 1
