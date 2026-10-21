"""Score Claude audit runs against the planted-bug manifest.

Usage: python score_runs.py <planted dir> <results dir> <condition> [--markdown FILE]

A planted bug counts as found in a run when the answer points at it: a reference to its file
with a line within LINE_WINDOW of the planted line, or the name of the function it sits in.

How references are read:

- Every way an answer writes a line counts: `file.py:40`, a later `:82` that refers back to the
  last file named, `file.py:30-45`, `file.py, line 40`, "lines 34 and 50", "line 40 of file.py",
  and a table row `| file.py | 40 |`.
- One reference credits at most one planted bug, the nearest. Two bugs planted a few lines
  apart are not both found by one mention between them.
- A reference on a line the answer labels INTENTIONAL (and not BUG) is not a find: the answer
  cleared that place rather than flagging it.
- A path with folders must match the end of the bug's path. A bare file name matches any file
  of that name, because answers often give only the name.
- A function name counts only as a whole word that is not part of a file name, and only when
  the answer also names the bug's file.

Everything else the answer points at is an unmatched claim. Unmatched claims are not all false
alarms: the model may have found a real problem that was not planted. They are the list to read
by hand.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE_WINDOW = 5
MIN_FUNCTION_NAME = 4
FILE = r"[\w./\\-]+\.(?:py|ya?ml)"
FILE_MENTION = re.compile(rf"({FILE})", re.IGNORECASE)
# Line numbers after a file mention, before the next one.
NEAR_LINE = re.compile(
    r"(?:^[`'\"*]*\s*(?:[:#(,]\s*)?(?:\blines?\b\s*)?L?|(?<![\w/.]):|\blines?\s+)"
    r"(\d+)(?:\s*(?:-|–|to)\s*(\d+))?",
    re.IGNORECASE,
)
# "lines 34 and 50", "lines 34, 50 and 61": every number after the word.
LINE_LIST = re.compile(r"\blines?\s+((?:\d+\s*(?:,|and|&)\s*)+\d+)", re.IGNORECASE)
TABLE_CELL = re.compile(r"\|\s*(\d+)\s*\|")
LINE_OF_FILE = re.compile(rf"\blines?\s+(\d+)\s+(?:of|in)\s+[`'\"]?({FILE})", re.IGNORECASE)


def _norm(path: str) -> str:
    path = path.replace("\\", "/").strip("`'\"*")
    while path.startswith("./"):
        path = path[2:]
    return path.lower()


def references(text):
    """(path, first line, last line, source line) for every place the answer points at."""
    refs = []
    for source in text.splitlines():
        mentions = list(FILE_MENTION.finditer(source))
        for index, mention in enumerate(mentions):
            path = _norm(mention.group(1))
            end = mentions[index + 1].start() if index + 1 < len(mentions) else len(source)
            tail = source[mention.end() : end]
            found_here = []
            for match in NEAR_LINE.finditer(tail):
                first = int(match.group(1))
                last = int(match.group(2)) if match.group(2) else first
                found_here.append((min(first, last), max(first, last)))
            for match in LINE_LIST.finditer(tail):
                for number in re.findall(r"\d+", match.group(1)):
                    found_here.append((int(number), int(number)))
            for match in TABLE_CELL.finditer(tail):
                found_here.append((int(match.group(1)), int(match.group(1))))
            for first, last in sorted(set(found_here)):
                refs.append((path, first, last, source))
        for match in LINE_OF_FILE.finditer(source):
            refs.append((_norm(match.group(2)), int(match.group(1)), int(match.group(1)), source))
    # A shorthand ":82" on a line with no file refers back to the last file named before it.
    last_path = None
    for source in text.splitlines():
        mentions = list(FILE_MENTION.finditer(source))
        if mentions:
            last_path = _norm(mentions[-1].group(1))
            continue
        if last_path is None:
            continue
        for match in re.finditer(r"(?<![\w/.]):(\d+)(?:\s*(?:-|–)\s*(\d+))?", source):
            first = int(match.group(1))
            last = int(match.group(2)) if match.group(2) else first
            refs.append((last_path, min(first, last), max(first, last), source))
    return sorted(set(refs), key=lambda r: (r[0], r[1], r[2], r[3]))


def _cleared(source: str) -> bool:
    """True if the answer labels this line INTENTIONAL and not BUG."""
    return "INTENTIONAL" in source and "BUG" not in source


def _same_file(ref_path: str, bug_file: str) -> bool:
    bug = _norm(bug_file)
    if ref_path.rsplit("/", 1)[-1] != bug.rsplit("/", 1)[-1]:
        return False
    return "/" not in ref_path or bug.endswith(ref_path)


def match(text, bugs):
    """(found bugs, unmatched references): each reference credits at most one bug."""
    # The same place named twice (in a summary and again in detail) is still one reference.
    places = {}
    for path, first, last, source in references(text):
        places[(path, first, last)] = places.get((path, first, last), False) or not _cleared(source)
    refs = sorted(place for place, flagged in places.items() if flagged)
    pairs = []
    for ref_index, (path, first, last) in enumerate(refs):
        for bug_index, bug in enumerate(bugs):
            if not _same_file(path, bug["file"]):
                continue
            if first - LINE_WINDOW <= bug["line"] <= last + LINE_WINDOW:
                distance = (
                    0
                    if first <= bug["line"] <= last
                    else min(abs(bug["line"] - first), abs(bug["line"] - last))
                )
                pairs.append((distance, ref_index, bug_index))
    used_refs, found = set(), set()
    for _distance, ref_index, bug_index in sorted(pairs):
        if ref_index in used_refs or bug_index in found:
            continue
        used_refs.add(ref_index)
        found.add(bug_index)
    lowered = text.lower()
    for bug_index, bug in enumerate(bugs):
        if bug_index in found:
            continue
        function = bug.get("function")
        base = _norm(bug["file"]).rsplit("/", 1)[-1]
        if not function or len(function) < MIN_FUNCTION_NAME or base not in lowered:
            continue
        for occurrence in re.finditer(rf"\b{re.escape(function)}\b(?!\.(?:py|ya?ml)\b)", text):
            end = text.find("\n", occurrence.end())
            line = text[text.rfind("\n", 0, occurrence.start()) + 1 : end if end != -1 else None]
            if not _cleared(line):
                found.add(bug_index)
                break
    unmatched = sorted(
        {(path, first) for i, (path, first, _last) in enumerate(refs) if i not in used_refs}
    )
    return [bugs[i] for i in sorted(found)], unmatched


def score(planted_dir, results_dir, condition):
    manifest = json.loads((planted_dir / "manifest.json").read_text(encoding="utf-8"))
    by_repo = defaultdict(list)
    for bug in manifest:
        by_repo[bug["repo"]].append(bug)
    runs = []
    for path in sorted((results_dir / condition).glob("*_run*.json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if "repo" not in run:
            continue
        repo = run["repo"].replace("__", "/", 1)
        text = run.get("result") or ""
        bugs = by_repo.get(repo, [])
        found, unmatched = match(text, bugs)
        runs.append(
            {
                "repo": repo,
                "run": run.get("run"),
                "error": bool(run.get("is_error") or run.get("exit")),
                "cost": run.get("total_cost_usd") or 0.0,
                "found": found,
                "planted": bugs,
                "unmatched": unmatched,
            }
        )
    return runs


def summarize(runs):
    lines = []
    per_repo = defaultdict(list)
    for r in runs:
        per_repo[r["repo"]].append(r)
    lines.append("| Repo | Planted | Found per run | Unmatched claims per run |")
    lines.append("|---|---|---|---|")
    for repo, rs in sorted(per_repo.items()):
        lines.append(
            f"| {repo} | {len(rs[0]['planted'])} | {[len(r['found']) for r in rs]} "
            f"| {[len(r['unmatched']) for r in rs]} |"
        )
    by_category = defaultdict(lambda: [0, 0])
    for r in runs:
        for bug in r["planted"]:
            by_category[(bug["kind"], bug["category"])][1] += 1
        for bug in r["found"]:
            by_category[(bug["kind"], bug["category"])][0] += 1
    lines.append("")
    lines.append("| Kind | Category | Found | Planted x runs | Recall |")
    lines.append("|---|---|---|---|---|")
    for (kind, category), (hit, total) in sorted(by_category.items()):
        lines.append(f"| {kind} | {category} | {hit} | {total} | {hit / total:.0%} |")
    hit = sum(len(r["found"]) for r in runs)
    total = sum(len(r["planted"]) for r in runs)
    errors = sum(r["error"] for r in runs)
    cost = sum(r["cost"] for r in runs)
    lines.append("")
    lines.append(
        f"Overall: {hit} of {total} planted bugs found ({hit / total:.0%}) over {len(runs)} runs; "
        f"{errors} errored; API-equivalent cost ${cost:.2f}."
    )
    return "\n".join(lines)


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--markdown")]
    markdown = None
    if "--markdown" in argv:
        markdown = Path(argv[argv.index("--markdown") + 1])
        args = [a for a in args if a != str(markdown)]
    if len(args) != 3:
        print(__doc__)
        return 2
    runs = score(Path(args[0]), Path(args[1]), args[2])
    if not runs:
        print("no runs found")
        return 1
    report = summarize(runs)
    print(report)
    if markdown is not None:
        markdown.write_text(report + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
