"""Repo-level paired bootstrap for the pre-registered comparison of arm B against arm A.

Usage: python paired_bootstrap.py <planted dir> <results A dir> <results B dir> [draws]

Each repo is one unit. For each repo the recall of A and of B is the bugs found over all runs
divided by bugs planted times runs. Repos are resampled with replacement, the difference
(B minus A) is taken on each resample, and the 2.5th and 97.5th percentiles give the 95%
interval. The seed is fixed, so a rerun gives the same interval.

Repos with no planted bugs are left out, because they carry no information about recall.
"""

import random
import sys
from pathlib import Path

import score_runs

KINDS = ("all", "other", "same")


def per_repo(planted, results, condition, kind):
    runs = score_runs.score(planted, results, condition)
    totals = {}
    for r in runs:
        planted_bugs = [b for b in r["planted"] if kind == "all" or b["kind"] == kind]
        found = [b for b in r["found"] if kind == "all" or b["kind"] == kind]
        t = totals.setdefault(r["repo"], [0, 0])
        t[0] += len(found)
        t[1] += len(planted_bugs)
    return {repo: (hit, n) for repo, (hit, n) in totals.items() if n > 0}


def interval(planted, a_dir, b_dir, kind, draws, seed=20261021):
    a = per_repo(planted, a_dir, "A", kind)
    b = per_repo(planted, b_dir, "B", kind)
    repos = sorted(set(a) & set(b))
    if not repos:
        return None
    point = sum(b[r][0] for r in repos) / sum(b[r][1] for r in repos) - sum(
        a[r][0] for r in repos
    ) / sum(a[r][1] for r in repos)
    rng = random.Random(seed)
    diffs = []
    for _ in range(draws):
        pick = [repos[rng.randrange(len(repos))] for _ in repos]
        b_hit = sum(b[r][0] for r in pick)
        b_n = sum(b[r][1] for r in pick)
        a_hit = sum(a[r][0] for r in pick)
        a_n = sum(a[r][1] for r in pick)
        diffs.append(b_hit / b_n - a_hit / a_n)
    diffs.sort()
    low = diffs[int(0.025 * draws)]
    high = diffs[int(0.975 * draws) - 1]
    return len(repos), point, low, high


def main(argv):
    if len(argv) not in (4, 5):
        print(__doc__)
        return 2
    planted, a_dir, b_dir = Path(argv[1]), Path(argv[2]), Path(argv[3])
    draws = int(argv[4]) if len(argv) == 5 else 10000
    for kind in KINDS:
        result = interval(planted, a_dir, b_dir, kind, draws)
        if result is None:
            print(f"{kind}: no repos in both arms")
            continue
        n, point, low, high = result
        print(
            f"{kind:6} repos={n:2d}  B minus A = {point:+.1%}  "
            f"95% interval [{low:+.1%}, {high:+.1%}]"
        )
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.exit(main(sys.argv))
