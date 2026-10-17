"""Git evidence for exceptions: who last changed the line, and why it might be intentional.

Reads git history only. Never changes the repository and never runs project code.
If git is missing, the folder is not a repository, or a call times out, the evidence
is left out and the scan still works.
"""

import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

GIT_TIMEOUT_SECONDS = 10
# Blaming every compliant file costs one git call per file. Large rules would take
# seconds, so only an evenly spaced sample of this many compliant items is checked.
MAX_COMPLIANT_CHECKED = 50
INTENT_WORDS = (
    "public",
    "health",
    "webhook",
    "login",
    "metrics",
    "noqa",
    "intentional",
    "todo",
)
UNCOMMITTED = "0" * 40
COMMENT_LOOKBACK = 3
_SHA = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")
_warned_timeouts: set[str] = set()


def _git(repo: str, args: list[str]) -> str | None:
    """Run git in repo and return stdout, or None if it failed for any reason."""
    try:
        result = subprocess.run(
            # The scanned repository is untrusted input. A crafted .git/config can name a
            # program for git to run (core.fsmonitor), so switch that off for every call.
            ["git", "-c", "core.fsmonitor=false", "-C", repo, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        # Say so once per kind of command, so a slow disk does not bury the output.
        if args[0] not in _warned_timeouts:
            _warned_timeouts.add(args[0])
            print(
                f"warning: git {args[0]} timed out after {GIT_TIMEOUT_SECONDS}s, "
                "so that evidence is skipped",
                file=sys.stderr,
            )
        return None
    except OSError:
        return None
    return result.stdout if result.returncode == 0 else None


class GitEvidence:
    """Caches git lookups for one scan, so each file is blamed and each commit read once."""

    def __init__(self, repo_root: Path):
        self.repo = str(Path(repo_root).resolve())
        # Inside a .git folder git prints "false" and still exits 0, so read the answer.
        inside = _git(self.repo, ["rev-parse", "--is-inside-work-tree"])
        self.available = inside is not None and inside.strip() == "true"
        self._boundary = _shallow_boundary(self.repo) if self.available else set()
        self._blame: dict[str, dict[int, dict]] = {}
        self._commits: dict[str, dict] = {}

    def line_author(self, rel: str, line: int) -> dict | None:
        """The commit that last changed this line, or None if git cannot say."""
        if not self.available:
            return None
        return self._blame_file(rel).get(line)

    def exception_evidence(
        self, rel: str, line: int, compliant: list[tuple[str, int]]
    ) -> dict | None:
        """The git block from plan section 7.2 for one exception."""
        info = self.line_author(rel, line)
        if info is None:
            return None
        commit = self._commit(info["commit"]) if info["commit"] else None
        # An uncommitted line has no author: git reports a placeholder address for it.
        author_email = info["email"] if info["commit"] and info["email"] else None
        sample = _evenly_spaced(compliant, MAX_COMPLIANT_CHECKED)
        followed = (
            sum(
                1
                for c_file, c_line in sample
                if (self.line_author(c_file, c_line) or {}).get("email") == author_email
            )
            if author_email
            else 0
        )
        return {
            # In a shallow clone, git blames old lines on the oldest fetched commit. That
            # commit is not the real author, so mark the evidence as truncated.
            "history_truncated": info["boundary"],
            "commit": info["commit"][:7] if info["commit"] else None,
            "author": author_email,
            "date": info["date"],
            "subject": info["subject"],
            "files_in_commit": commit["files"] if commit else None,
            "author_followed_rule_elsewhere": followed,
            "compliant_checked": len(sample),
            "intent_words": _intent_words(
                (commit["message"] if commit else "") + "\n" + self._nearby_comments(rel, line)
            ),
            "uncommitted": info["commit"] is None,
        }

    def _blame_file(self, rel: str) -> dict[int, dict]:
        if rel not in self._blame:
            output = _git(self.repo, ["blame", "--line-porcelain", "--no-textconv", "--", rel])
            self._blame[rel] = _parse_blame(output, self._boundary) if output else {}
        return self._blame[rel]

    def _commit(self, sha: str) -> dict | None:
        if sha not in self._commits:
            message = _git(self.repo, ["log", "-1", "--format=%B", sha])
            files = _git(self.repo, ["show", "--name-only", "--format=", sha])
            if message is None or files is None:
                return None
            self._commits[sha] = {
                "message": message,
                "files": len([f for f in files.splitlines() if f.strip()]),
            }
        return self._commits[sha]

    def _nearby_comments(self, rel: str, line: int) -> str:
        try:
            lines = (Path(self.repo) / rel).read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            return ""
        start = max(line - 1 - COMMENT_LOOKBACK, 0)
        window = lines[start:line]
        return "\n".join(
            text.strip() for text in window if text.strip().startswith(("#", "//", "/*"))
        )


def _shallow_boundary(repo: str) -> set[str]:
    """Commits at the edge of a shallow clone. Their parents were not fetched."""
    path = _git(repo, ["rev-parse", "--git-path", "shallow"])
    if path is None:
        return set()
    try:
        lines = (Path(repo) / path.strip()).read_text(encoding="utf-8").splitlines()
    except OSError:
        return set()
    return {line.strip() for line in lines if line.strip()}


def _parse_blame(output: str, boundary: set[str] = frozenset()) -> dict[int, dict]:
    """Parse `git blame --line-porcelain` into {final line number: commit info}."""
    result: dict[int, dict] = {}
    current: dict | None = None
    for raw in output.splitlines():
        match = _SHA.match(raw)
        if match:
            sha = match.group(1)
            current = {
                "commit": None if sha == UNCOMMITTED else sha,
                "boundary": sha in boundary,
                "email": "",
                "date": None,
                "subject": "",
            }
            result[int(match.group(2))] = current
        elif current is None or raw.startswith("\t"):
            continue
        elif raw.startswith("author-mail "):
            current["email"] = raw[len("author-mail ") :].strip().strip("<>")
        elif raw.startswith("author-time "):
            stamp = int(raw.split()[1])
            current["date"] = datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
        elif raw.startswith("summary "):
            current["subject"] = raw[len("summary ") :]
    return result


def _evenly_spaced(items: list, limit: int) -> list:
    """At most limit items, spread across the whole list so no single folder dominates."""
    if len(items) <= limit:
        return list(items)
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)]


def _intent_words(text: str) -> list[str]:
    found = {
        word
        for word in INTENT_WORDS
        if re.search(rf"\b{re.escape(word)}\b", text, flags=re.IGNORECASE)
    }
    return sorted(found)
