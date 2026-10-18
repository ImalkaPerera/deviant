# Condition B: Claude with the Deviant skill, on planted bugs

Run on 2026-10-18 on the same 30 planted copies as condition A (`condition-a-claude-alone.md`):
10 repos, three runs each, Claude Haiku 5.5. The prompt was the same audit request, sent as
the argument to `/deviant:deviant` with the plugin loaded from this repository. The tools were
Read, Grep, Glob and Bash. PyYAML was made available so the GitHub Actions check could run.
Scored with `bench/score_runs.py`.

## Results

| Kind | Category | Found | Planted x runs | Recall |
|---|---|---|---|---|
| same | FastAPI auth dependency removed | 9 | 27 | 33% |
| same | GitHub Actions job timeout removed | 0 | 39 | 0% |
| other | Inverted `if not` in a route | 0 | 30 | 0% |
| other | Step ignores failure (`continue-on-error`) | 0 | 30 | 0% |
| | **All** | **9** | **126** | **7%** |

Claude alone found 71 of 126 (56%) on the same bugs. Cost was $0.17 for all 30 runs, against
$4.66 for condition A. No run errored.

## Why it scored this low

- The skill tells Claude to stop when the scan reports no rules, and not to read files to make
  up for it. On nine of the ten repos the scan reported nothing, so the run ended after one
  scan. Only transmute-app/transmute produced findings (3 per run).
- The detectors alone reported 2 of 9 removed auth dependencies and 0 of 13 removed timeouts,
  so a skill that works only from the scan can find no more than that.

## What this does and does not show

- As shipped, the skill finds far fewer planted bugs than Claude reading the code unaided,
  on these repos.
- It does not test what the skill is for. The skill judges exceptions the scan has already
  found (bug, intentional or unsure, with proof). This benchmark measures finding bugs, not
  judging them, and the planted copies have no git history, so the skill's git evidence was
  not used.
- The audit request was passed to the skill as its argument. The skill took it for a
  description and scanned the current directory, which was the right folder here.
- Same limits as condition A: three runs per repo, one model, synthetic bugs, and the matching
  of answers to planted bugs is mechanical.

## Second run: the skill falls back to a relaxed scan

The skill was changed so that, when the default scan finds nothing, it scans once more with
`--min-items 8 --min-confidence 0.5` and treats what it finds as weak leads. The same 30
planted copies were run again, three times each, with the same model and prompt.

| Kind | Category | First run | With fallback |
|---|---|---|---|
| same | FastAPI auth dependency removed | 9 of 27 (33%) | 14 of 27 (52%) |
| same | GitHub Actions job timeout removed | 0 of 39 | 0 of 39 |
| other | Inverted `if not` in a route | 0 of 30 | 0 of 30 |
| other | Step ignores failure | 0 of 30 | 0 of 30 |
| | **All** | **9 of 126 (7%)** | **14 of 126 (11%)** |

Cost was $0.21 for all 30 runs. Claude alone found 89% of the removed auth dependencies and
56% overall.

- The fallback helped only on FastAPI repos with groups of 8 to 19 routes. magicyuan876/
  mineru-tianshu went from 0 to 2 bugs per run, and transmute-app/transmute found about the
  same.
- It did nothing for job timeouts: in these repos the jobs that set a timeout are too few or
  too many exceptions share the gap for any relaxed setting to report them.
- The fallback was made after seeing the first result on this same set, so this number is
  tuned to it and is optimistic. It has not been checked on other repos.
- False alarms are still unmeasured. The skill pointed at 0 to 9 places per run that were not
  planted bugs, far fewer than Claude alone.
