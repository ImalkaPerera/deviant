# Condition B: Claude with the Deviant skill, on planted bugs

Re-run on 2026-10-20 with v0.2.0 (commit `cdab846`) on the same 30 planted copies as condition
A (`condition-a-claude-alone.md`): 10 repos, three runs each, Claude Haiku 5.5. The prompt was
the same audit request, sent as the argument to `/deviant:deviant` with the plugin loaded from
this repository. The tools were Read, Grep, Glob and Bash. Scored with `bench/score_runs.py`.

The earlier runs of 2026-10-18 (before v0.2.0) are kept below for comparison.

## Results (2026-10-20, v0.2.0)

| Kind | Category | Found | Planted x runs | Recall |
|---|---|---|---|---|
| same | FastAPI auth dependency removed | 15 | 27 | 56% |
| same | GitHub Actions job timeout removed | 0 | 39 | 0% |
| other | Inverted `if not` in a route | 0 | 30 | 0% |
| other | Step ignores failure (`continue-on-error`) | 0 | 30 | 0% |
| | **All** | **15** | **126** | **12%** |

Claude alone found 65 of 126 (52%) on the same bugs. Cost was $0.21 for all 30 runs, against
$3.78 for condition A. No run errored.

## Why it scored this low

- The skill reports what the scan reports. The detectors alone found 2 of 9 removed auth
  dependencies and 0 of 13 removed job timeouts (`detector-only.md`), so the skill cannot find
  more than that.
- The skill found auth removals in the FastAPI repos where the scan reports a group, and
  nothing in the repos where it reports no rules.

## What this does and does not show

- As shipped, the skill finds far fewer planted bugs than Claude reading the code unaided,
  on these repos.
- It does not test what the skill is for. The skill judges exceptions the scan has already
  found. This benchmark measures finding bugs, not judging them.
- The planted copies have no git history, so the skill's git evidence was not used.
- Same limits as condition A: three runs per repo, one model, synthetic bugs, and mechanical
  matching of answers to planted bugs.

## Earlier runs (2026-10-18, before v0.2.0)

| Kind | Category | First run | With relaxed-scan fallback |
|---|---|---|---|
| same | FastAPI auth dependency removed | 9 of 27 (33%) | 14 of 27 (52%) |
| same | GitHub Actions job timeout removed | 0 of 39 | 0 of 39 |
| other | Inverted `if not` in a route | 0 of 30 | 0 of 30 |
| other | Step ignores failure | 0 of 30 | 0 of 30 |
| | **All** | **9 of 126 (7%)** | **14 of 126 (11%)** |

The relaxed fallback was tuned on this same set, so its number is optimistic. The v0.2.0 run
above is the current result: 15 of 126, which is slightly above the earlier 9 and 14, on
auth removals only.
