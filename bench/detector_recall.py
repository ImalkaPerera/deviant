"""Measure the detectors alone (no AI) on a planted set: how many planted bugs are reported.

Usage: python detector_recall.py <planted dir>

<planted dir> is the output of mutations/plant.py. Only the "same kind" bugs are scored,
because those are the bugs the detectors check: a FastAPI route that lost its auth
dependency, and a job that lost its timeout. A planted bug counts as reported when the scan
lists it as an exception to the matching feature (has_auth or has_timeout_minutes) at the
route's def line or the job's key line, in the right file.
"""

import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"))

from deviant_scan import mine  # noqa: E402

FEATURE = {
    "fastapi_auth_dependency_removed": "has_auth",
    "gha_job_timeout_removed": "has_timeout_minutes",
}


def reported_exceptions(repo_dir):
    items = mine.collect_items(repo_dir, mine.DETECTORS_DIR)
    rules = mine.mine(items)
    return {(e["file"], e["line"], r["feature"]) for r in rules for e in r["exceptions"]}


def route_lines(repo_dir, bug):
    """Lines the detector may use for the route that lost its dependency."""
    tree = ast.parse((repo_dir / bug["file"]).read_bytes())
    lines = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == bug["function"]
            and node.lineno <= bug["line"] <= node.end_lineno
        ):
            lines.add(node.lineno)
            lines.update(d.lineno for d in node.decorator_list)
    return lines


def job_key_line(repo_dir, bug):
    """Line of the job key above the line where the timeout used to be."""
    lines = (repo_dir / bug["file"]).read_bytes().decode("utf-8").splitlines()
    jobs = next(i for i, text in enumerate(lines) if re.match(r"^['\"]?jobs['\"]?\s*:", text))
    child = next(
        text for text in lines[jobs + 1 :] if text.strip() and not text.lstrip().startswith("#")
    )
    indent = len(child) - len(child.lstrip(" "))
    for index in range(bug["line"] - 2, jobs, -1):
        text = lines[index]
        if text.strip() and len(text) - len(text.lstrip(" ")) == indent:
            return {index + 1}
    return set()


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    planted = Path(argv[1])
    manifest = json.loads((planted / "manifest.json").read_text(encoding="utf-8"))
    by_repo = defaultdict(list)
    for bug in manifest:
        if bug["category"] in FEATURE:
            by_repo[bug["repo"]].append(bug)
    totals = defaultdict(lambda: [0, 0])
    for repo, bugs in sorted(by_repo.items()):
        repo_dir = planted / repo.replace("/", "__")
        reported = reported_exceptions(repo_dir)
        for bug in bugs:
            feature = FEATURE[bug["category"]]
            if bug["category"] == "fastapi_auth_dependency_removed":
                where = route_lines(repo_dir, bug)
            else:
                where = job_key_line(repo_dir, bug)
            hit = any((bug["file"], line, feature) in reported for line in where)
            totals[bug["category"]][1] += 1
            totals[bug["category"]][0] += hit
            print(f"{'reported' if hit else 'missed  '}  {bug['id']}")
    print()
    for category, (hit, total) in sorted(totals.items()):
        print(f"{category}: {hit} of {total} reported")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
