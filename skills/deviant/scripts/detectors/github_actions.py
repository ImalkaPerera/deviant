"""Detector for GitHub Actions workflows: pinned actions, timeouts, permissions, concurrency.

Reads YAML with yaml.safe_load only. Needs PyYAML; without it the detector prints a
message and returns nothing.
"""

import re
import sys
from pathlib import Path

DETECTOR = "github_actions"
MAX_BYTES = 1_000_000
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
        except (OSError, UnicodeDecodeError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        lines = text.splitlines()
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        items.append(_workflow_item(rel, data, jobs))
        jobs_line = _line_of(lines, r"^['\"]?jobs['\"]?\s*:", regex=True)
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            key = re.escape(str(job_id))
            job_line = _line_of(lines, rf"^\s+['\"]?{key}['\"]?\s*:", start=jobs_line, regex=True)
            if isinstance(job.get("uses"), str):
                # A call to a reusable workflow has no timeout or steps of its own,
                # but the workflow it calls should be pinned like any action.
                if not _is_local(job["uses"]):
                    line = _line_of(lines, job["uses"], start=job_line - 1)
                    items.append(_uses_item(rel, job["uses"], line, job.get("name")))
                continue
            items.append(_job_item(rel, data, str(job_id), job, job_line))
            items.extend(_step_items(rel, job, lines, job_line))
    return items


def _workflow_files(root: Path) -> list[Path]:
    folder = root / ".github" / "workflows"
    if not folder.is_dir():
        return []
    files = []
    for path in sorted(folder.iterdir()):
        if path.suffix not in (".yml", ".yaml") or path.is_symlink():
            continue
        if path.stat().st_size <= MAX_BYTES:
            files.append(path)
    return files


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
        "features": {"has_permissions_block": "permissions" in data or every_job_scoped},
        "context": {"name": data.get("name")},
    }


def _job_item(rel, data, job_id, job, line):
    return {
        "detector": DETECTOR,
        "peer_group": "gha_jobs",
        "item_id": job_id,
        "file": rel,
        "line": line,
        "features": {
            "has_timeout_minutes": "timeout-minutes" in job,
            # Workflow-level concurrency covers every job, like workflow-level permissions.
            "has_concurrency": "concurrency" in job or "concurrency" in data,
        },
        "context": {"runs_on": job.get("runs-on")},
    }


def _step_items(rel, job, lines, job_line):
    items = []
    steps = job.get("steps") if isinstance(job.get("steps"), list) else []
    cursor = job_line - 1  # search forward so repeated steps get their own lines
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("uses"), str):
            continue
        uses = step["uses"]
        if _is_local(uses):
            continue  # local actions live in this repo and are not pinned
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
        "context": {"step_name": name},
    }


def _is_local(uses: str) -> bool:
    """True for a workflow or action stored in this repo.

    "./" is the usual form. "$/" is what cargo-dist writes for the same thing.
    """
    return uses.startswith(("./", "$/"))


def _line_of(lines, needle, start=0, regex=False):
    """1-based line number of the first match at or after start; 1 if not found."""
    for index in range(max(start, 0), len(lines)):
        found = re.search(needle, lines[index]) if regex else needle in lines[index]
        if found:
            return index + 1
    return 1
