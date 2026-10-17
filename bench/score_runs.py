"""Score Claude audit runs against the planted-bug manifest.

Usage: python score_runs.py <planted dir> <results dir> <condition> [--markdown FILE]

A planted bug counts as found in a run when the answer names its file and either points at
a line within LINE_WINDOW of the planted line, or names the function the bug sits in.

Everything else the answer points at is an unmatched claim. Unmatched claims are not all
false alarms: the model may have found a real problem that was not planted. They are the
list to read by hand.
"""

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LINE_WINDOW = 5
MIN_FUNCTION_NAME = 4
CLAIM = re.compile(
    r"([\w./-]+\.(?:py|ya?ml))[`'\"]?\s*(?:[:#(,]|\blines?\b)\s*[Ll]?(\d+)",
    re.IGNORECASE,
)


def claims(text):
    """(file name, line number) pairs the answer points at."""
    return [(name.rsplit("/", 1)[-1], int(line)) for name, line in CLAIM.findall(text)]


def found(text, bug):
    base = bug["file"].rsplit("/", 1)[-1]
    if base not in text:
        return False
    function = bug.get("function")
    if function and len(function) >= MIN_FUNCTION_NAME:
        if re.search(rf"\b{re.escape(function)}\b", text):
            return True
    return any(
        name == base and abs(line - bug["line"]) <= LINE_WINDOW for name, line in claims(text)
    )


def unmatched_claims(text, bugs):
    bases = {b["file"].rsplit("/", 1)[-1]: [] for b in bugs}
    for b in bugs:
        bases[b["file"].rsplit("/", 1)[-1]].append(b["line"])
    out = []
    for name, line in claims(text):
        near = bases.get(name, [])
        if not any(abs(line - planted) <= LINE_WINDOW for planted in near):
            out.append((name, line))
    return sorted(set(out))


def score(planted_dir, results_dir, condition):
    manifest = json.loads((planted_dir / "manifest.json").read_text(encoding="utf-8"))
    by_repo = defaultdict(list)
    for bug in manifest:
        by_repo[bug["repo"]].append(bug)
    runs = []
    for path in sorted((results_dir / condition).glob("*_run[0-9].json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        if "repo" not in run:
            continue
        repo = run["repo"].replace("__", "/", 1)
        text = run.get("result") or ""
        bugs = by_repo.get(repo, [])
        runs.append(
            {
                "repo": repo,
                "run": run.get("run"),
                "error": bool(run.get("is_error") or run.get("exit")),
                "cost": run.get("total_cost_usd") or 0.0,
                "found": [b for b in bugs if found(text, b)],
                "planted": bugs,
                "unmatched": unmatched_claims(text, bugs),
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
