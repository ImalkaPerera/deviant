"""Git evidence for exceptions: who last changed the line, and why it might be intentional.

Reads git history only. Never changes the repository and never runs project code.
If git is missing, the folder is not a repository, or a call times out, the evidence
is left out and the scan still works.
"""

import os
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
# The object id of git's empty tree. Used as an attribute source, it names no filters.
_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
COMMENT_LOOKBACK = 3
_SHA = re.compile(r"^([0-9a-f]{40}) \d+ (\d+)")
_warned_timeouts: set[str] = set()


# Set by git itself for hooks and scripts. Inherited, they would point git at another repository.
_REPOSITORY_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_NAMESPACE",
)


def _git(repo: str, args: list[str]) -> str | None:
    """Run git in repo and return stdout, or None if it failed for any reason."""
    env = {k: v for k, v in os.environ.items() if k not in _REPOSITORY_ENV}
    # Attributes come from an empty tree, so git applies no filter named by the repository's
    # .gitattributes. Blame would otherwise run a clean filter from .git/config, which is
    # code from the scanned repository. GIT_ATTR_SOURCE needs git 2.40 or newer.
    env["GIT_ATTR_SOURCE"] = _EMPTY_TREE
    try:
        result = subprocess.run(
            # The scanned repository is untrusted input. A crafted .git/config can name a
            # program for git to run (core.fsmonitor), and a crafted config or signed commit
            # can name a program for log to run (gpg.program), so switch both off.
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "-c",
                "log.showSignature=false",
                "-C",
                repo,
                *args,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=GIT_TIMEOUT_SECONDS,
            check=False,
            env=env,
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
        self._attr_source_ok = self.available and _attr_source_supported()
        if self.available and not self._attr_source_ok:
            print(
                "warning: git 2.40 or newer is needed for blame evidence, so it is skipped",
                file=sys.stderr,
            )
        self._boundary = _shallow_boundary(self.repo) if self.available else set()
        self._blame: dict[str, dict[int, dict]] = {}
        self._commits: dict[str, dict] = {}

    def line_author(self, rel: str, line: int, span: tuple[int, int] | None = None) -> dict | None:
        """The commit that last changed this line, or None if git cannot say.

        With a span (first line, last line), the newest change anywhere in it counts. A route
        keeps its auth in the decorator above the def line, so the def line alone can point at
        an older commit than the one that removed the auth.
        """
        if not self.available:
            return None
        blame = self._blame_file(rel)
        if not span:
            return blame.get(line)
        found = [blame[n] for n in range(span[0], span[1] + 1) if n in blame]
        if not found:
            return None
        # An uncommitted line is newer than any commit.
        return max(found, key=lambda info: (info["commit"] is None, info["time"]))

    def exception_evidence(
        self, rel: str, line: int, compliant: list[tuple], span: tuple[int, int] | None = None
    ) -> dict | None:
        """The git block from plan section 7.2 for one exception.

        Each compliant item is (file, line) or (file, line, span).
        """
        info = self.line_author(rel, line, span)
        if info is None:
            return None
        commit = self._commit(info["commit"]) if info["commit"] else None
        # An uncommitted line has no author: git reports a placeholder address for it.
        author_email = info["email"] if info["commit"] and info["email"] else None
        sample = _evenly_spaced(compliant, MAX_COMPLIANT_CHECKED)
        followed = (
            sum(
                1
                for c_file, c_line, *c_span in sample
                if (self.line_author(c_file, c_line, *c_span) or {}).get("email") == author_email
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
            output = None
            if self._attr_source_ok:
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


def _attr_source_supported() -> bool:
    """True if this git reads attributes from GIT_ATTR_SOURCE (git 2.40 or newer).

    Without it the empty-tree guard in _git does nothing, so blame must not run at all.
    """
    try:
        out = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "--version"],
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    match = re.search(r"(\d+)\.(\d+)", out)
    return bool(match) and (int(match.group(1)), int(match.group(2))) >= (2, 40)


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
                "time": 0,
                "subject": "",
            }
            result[int(match.group(2))] = current
        elif current is None or raw.startswith("\t"):
            continue
        elif raw.startswith("author-mail "):
            current["email"] = raw[len("author-mail ") :].strip().strip("<>")
        elif raw.startswith("author-time "):
            stamp = int(raw.split()[1])
            current["time"] = stamp
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
