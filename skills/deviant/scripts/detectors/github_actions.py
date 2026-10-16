"""Detector for GitHub Actions workflows: pinned actions, timeouts, permissions, concurrency.

Reads YAML with yaml.safe_load only. Needs PyYAML; without it the detector prints a
message and returns nothing.
"""

import re
import sys
from pathlib import Path

DETECTOR = "github_actions"
MAX_BYTES = 1_000_000
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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
        items.append(_workflow_item(rel, data))
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        for job_id, job in jobs.items():
            if not isinstance(job, dict) or "uses" in job:
                continue  # a call to a reusable workflow has no timeout or steps of its own
            job_line = _line_of(lines, rf"^\s*{re.escape(str(job_id))}:", regex=True)
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


def _workflow_item(rel, data):
    return {
        "detector": DETECTOR,
        "peer_group": "gha_workflows",
        "item_id": rel,
        "file": rel,
        "line": 1,
        "features": {"has_permissions_block": "permissions" in data},
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
    for step in steps:
        if not isinstance(step, dict) or not isinstance(step.get("uses"), str):
            continue
        uses = step["uses"]
        if uses.startswith("./"):
            continue  # local actions live in this repo and are not pinned
        ref = uses.rsplit("@", 1)[1] if "@" in uses else ""
        items.append(
            {
                "detector": DETECTOR,
                "peer_group": "gha_third_party_steps",
                "item_id": uses,
                "file": rel,
                "line": _line_of(lines, uses, start=job_line - 1),
                "features": {"pinned_to_sha": bool(SHA_RE.match(ref))},
                "context": {"step_name": step.get("name")},
            }
        )
    return items


def _line_of(lines, needle, start=0, regex=False):
    """1-based line number of the first match at or after start; 1 if not found."""
    for index in range(max(start, 0), len(lines)):
        found = re.search(needle, lines[index]) if regex else needle in lines[index]
        if found:
            return index + 1
    return 1
