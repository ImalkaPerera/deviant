"""Git evidence for exceptions: who last changed the line, and why it might be intentional.

Reads git history only. Never changes the repository and never runs project code.
If git is missing, the folder is not a repository, or a call times out, the evidence
is left out and the scan still works.
"""

import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

GIT_TIMEOUT_SECONDS = 10
# All git lookups of one scan share this budget. Each call has its own timeout, but a
# repository with thousands of files could still keep a scan busy for many minutes.
GIT_BUDGET_SECONDS = 60
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
# Object ids are 40 hex digits in a SHA-1 repository and 64 in a SHA-256 one.
_SHA = re.compile(r"^([0-9a-f]{64}|[0-9a-f]{40}) \d+ (\d+)")
# The object id of git's empty tree, per hash. Used as an attribute source, it names no filters.
_EMPTY_TREES = {
    "sha1": "4b825dc642cb6eb9a060e54bf8d69288fbee4904",
    "sha256": "6ef19b41225c5369f1c104d45d8d85efa9b057b53b14b4b9b939dd74decc5321",
}
COMMENT_LOOKBACK = 3
# Python and git count lines at \n, \r\n and \r. str.splitlines() also breaks at a form feed
# and other separators, which would read the comments from the wrong lines.
_LINE_BREAK = re.compile(r"\r\n|\r|\n")
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


_object_formats: dict[str, str] = {}


def _empty_tree(repo: str) -> str:
    """The empty tree's id in this repository's hash. A SHA-1 id is refused by a SHA-256 one."""
    if repo not in _object_formats:
        answer = _run_git(repo, ["rev-parse", "--show-object-format"], attr_source=False)
        _object_formats[repo] = (answer or "").strip()
    return _EMPTY_TREES.get(_object_formats[repo], _EMPTY_TREES["sha1"])


def _run_git(
    repo: str, args: list[str], extra: tuple[str, ...] = (), attr_source: bool = True
) -> str | None:
    """Run git in repo with extra -c options, and return stdout or None if it failed."""
    env = {k: v for k, v in os.environ.items() if k not in _REPOSITORY_ENV}
    # Attributes come from an empty tree, so git applies no filter named by the repository's
    # .gitattributes. Blame would otherwise run a clean filter from .git/config, which is
    # code from the scanned repository. GIT_ATTR_SOURCE needs git 2.40 or newer. Only the
    # lookup of the hash itself runs without it; rev-parse reads no attributes.
    if attr_source:
        env["GIT_ATTR_SOURCE"] = _empty_tree(repo)
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
                *extra,
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


_filter_overrides_cache: dict[str, tuple[str, ...]] = {}
# Repositories with a filter that cannot be switched off. Blame is never run in them.
_filters_unsafe: set[str] = set()


def _filters_can_be_switched_off(repo: str) -> bool:
    """False if the repository defines a filter whose name -c cannot express."""
    _filter_overrides(repo)
    return repo not in _filters_unsafe


def _filter_overrides(repo: str) -> tuple[str, ...]:
    """-c options that switch off every filter named in the repository's configuration.

    A clean filter is a program that git runs on a working-tree file. A scanned repository can
    name one from .gitattributes, from .git/info/attributes or from core.attributesFile, and a
    .git file can redirect to a config of its own. Blocking each way of naming a filter would
    miss one, so this switches off the filters themselves: every filter the config defines gets
    an empty clean, smudge and process command. Listing the config only reads it.
    """
    if repo not in _filter_overrides_cache:
        names: set[str] = set()
        listing = _run_git(repo, ["config", "--list", "--name-only"])
        for key in (listing or "").splitlines():
            if key.startswith("filter.") and key.rsplit(".", 1)[-1] in {
                "clean",
                "smudge",
                "process",
            }:
                names.add(key[len("filter.") : key.rindex(".")])
        # `git -c name=value` splits at the first "=", so a filter whose name holds one cannot
        # be switched off that way. Nor can one whose name is not valid UTF-8, because the
        # listing is decoded with replacement and the override would name a different filter.
        if any("=" in name or chr(0xFFFD) in name for name in names):
            _filters_unsafe.add(repo)
        options: list[str] = []
        for name in sorted(names):
            for setting in ("clean", "smudge", "process"):
                options += ["-c", f"filter.{name}.{setting}="]
            options += ["-c", f"filter.{name}.required=false"]
        _filter_overrides_cache[repo] = tuple(options)
    return _filter_overrides_cache[repo]


def _git(repo: str, args: list[str]) -> str | None:
    """Run git in repo, with the repository's own filters switched off. None if it failed."""
    return _run_git(repo, args, _filter_overrides(repo))


def _note_outside_git_dir(repo: str) -> None:
    """Say on stderr when the git history comes from outside the scanned folder.

    A .git file can redirect to another repository, and a legitimate worktree or submodule
    does the same. A scanned project that redirects to someone else's repository would make the
    report show that repository's authors and commit subjects, so the reader is told.
    """
    answer = _run_git(repo, ["rev-parse", "--absolute-git-dir"])
    top = _run_git(repo, ["rev-parse", "--show-toplevel"])
    if not answer or not top:
        return
    # The usual case is the .git folder at the top of the work tree that holds the scanned
    # folder, also when only a subfolder of the repository (a monorepo package) is scanned.
    try:
        usual = Path(answer.strip()).resolve() == (Path(top.strip()) / ".git").resolve()
    except (OSError, RuntimeError):
        return
    if not usual:
        print(
            "warning: git history comes from "
            f"{_show_path(answer.strip())}, which is outside the scanned folder "
            "(a worktree, a submodule, or a .git file that points elsewhere)",
            file=sys.stderr,
        )


_UNSAFE_RANGES = ((0x00, 0x1F), (0x7F, 0x9F), (0x2028, 0x2029), (0x202A, 0x202E), (0x2066, 0x2069))
_UNSAFE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _UNSAFE_RANGES) + "]")


def _show_path(text: str) -> str:
    """text with control and bidirectional characters replaced by visible escapes."""

    def escape(match):
        code = ord(match.group())
        return chr(92) + (f"x{code:02x}" if code < 0x100 else f"u{code:04x}")

    return _UNSAFE.sub(escape, text)


class GitEvidence:
    """Caches git lookups for one scan, so each file is blamed and each commit read once."""

    def __init__(self, repo_root: Path):
        self.repo = str(Path(repo_root).resolve())
        # Inside a .git folder git prints "false" and still exits 0, so read the answer.
        inside = _git(self.repo, ["rev-parse", "--is-inside-work-tree"])
        self.available = inside is not None and inside.strip() == "true"
        self._attr_source_ok = self.available and _attr_source_supported()
        if self._attr_source_ok and not _filters_can_be_switched_off(self.repo):
            # Fail closed: blaming here could run a program the repository names.
            self._attr_source_ok = False
            print(
                "warning: the repository defines a git filter whose name cannot be switched "
                "off safely, so blame evidence is skipped",
                file=sys.stderr,
            )
        if self.available:
            _note_outside_git_dir(self.repo)
        if self.available and not self._attr_source_ok:
            print(
                "warning: git 2.40 or newer is needed for blame evidence, so it is skipped",
                file=sys.stderr,
            )
        self._boundary = _shallow_boundary(self.repo) if self.available else set()
        self._blame: dict[str, dict[int, dict]] = {}
        self._commits: dict[str, dict] = {}
        self._deadline = time.monotonic() + GIT_BUDGET_SECONDS
        self._budget_warned = False

    def _over_budget(self) -> bool:
        """True once the scan has used its git time. Says so once on stderr."""
        if time.monotonic() <= self._deadline:
            return False
        if not self._budget_warned:
            self._budget_warned = True
            print(
                f"warning: git evidence stopped after {GIT_BUDGET_SECONDS}s, "
                "so the remaining exceptions have no history",
                file=sys.stderr,
            )
        return True

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
            if self._attr_source_ok and not self._over_budget():
                output = _git(self.repo, ["blame", "--line-porcelain", "--no-textconv", "--", rel])
            self._blame[rel] = _parse_blame(output, self._boundary) if output else {}
        return self._blame[rel]

    def _commit(self, sha: str) -> dict | None:
        if sha not in self._commits:
            if self._over_budget():
                return None
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
            text = (Path(self.repo) / rel).read_text(encoding="utf-8")
            lines = _LINE_BREAK.split(text)
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
                "commit": None if not sha.strip("0") else sha,
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
            current["time"], current["date"] = _when(raw[len("author-time ") :])
        elif raw.startswith("summary "):
            current["subject"] = raw[len("summary ") :]
    return result


def _when(text: str) -> tuple[int, str | None]:
    """(seconds, ISO date) of a commit time, or (0, None) for one that is not a usable date.

    A commit can carry any number as its time. One past the year 9999, or before the year 1,
    has no date, and must not end the scan.
    """
    try:
        stamp = int(text.strip())
        return stamp, datetime.fromtimestamp(stamp, timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError):
        try:
            return int(text.strip()), None
        except ValueError:
            return 0, None


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
