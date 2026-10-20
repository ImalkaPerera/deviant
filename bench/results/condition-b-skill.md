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

## Development run: the skill with `--inventory` (2026-10-20, commit `d3322f6`)

The skill was changed so that it no longer stops on an empty scan. It asks the scanner for an
inventory of every peer group and judges the items that lack something most of their peers have
(see `docs/claude-code-skill.md`). The same 30 planted copies were run again, three times each,
with the same model and prompt.

| Kind | Category | v0.2.0 skill | With inventory |
|---|---|---|---|
| same | FastAPI auth dependency removed | 15 of 27 (56%) | 17 of 27 (63%) |
| same | GitHub Actions job timeout removed | 0 of 39 (0%) | 15 of 39 (38%) |
| other | Inverted `if not` in a route | 0 of 30 | 0 of 30 |
| other | Step ignores failure | 0 of 30 | 0 of 30 |
| | **All** | **15 of 126 (12%)** | **32 of 126 (25%)** |

Cost was $0.37 for all 30 runs, against $3.78 for Claude alone, which found 65 of 126 (52%).
No run errored.

**This is a development result, not a measurement.** The inventory was designed after reading
why this set scored low, and this set was used to look at its output (the inventory alone lists
5 of the 9 auth bugs and 6 of the 13 timeout bugs as leads). It shows the direction of the
change. It does not show how the skill performs on repos it has not been tuned on. That test is
set up in `bench/PREREGISTRATION.md` and has not been run.

- The timeout gain is the clearest effect: the strict scan can never report these bugs in these
  repos, but the inventory lists them.
- The two kinds with no detector are still at 0%.
- Precision is not measured. The scorer counted 0 to 11 unmatched claims per run, and these have
  not been read. Repos where the skill reported nothing (AgentChat, uv, pytest) show 0 found
  and 0 claimed.

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
