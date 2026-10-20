# Condition A: Claude alone, on planted bugs

Re-run on 2026-10-20 with v0.2.0 (commit `cdab846`). Each of the 10 pinned repos in
`bench/repos.json` was copied with `bench/mutations/plant.py`, which plants 42 known bugs.
Claude Haiku 5.5 then read each copy with the tools Read, Grep and Glob and no other help,
three times per repo (30 runs). The prompt asked for places where almost every similar item
follows a pattern but one or two break it, with a file, line and reason for each. See
`bench/run_benchmark.py`. Scored with `bench/score_runs.py`.

The earlier run of 2026-10-17 is kept below for comparison.

## Results (2026-10-20)

| Kind | Category | Found | Planted x runs | Recall |
|---|---|---|---|---|
| same | FastAPI auth dependency removed | 21 | 27 | 78% |
| same | GitHub Actions job timeout removed | 12 | 39 | 31% |
| other | Inverted `if not` in a route | 12 | 30 | 40% |
| other | Step ignores failure (`continue-on-error`) | 20 | 30 | 67% |
| | **All** | **65** | **126** | **52%** |

"Same" means a bug of the kind the detectors check. "Other" means a kind no detector checks.
For comparison, the detectors alone (no AI) reported 2 of 9 removed FastAPI auth
dependencies and 0 of 13 removed job timeouts: see `detector-only.md`.

Cost: $3.78 API-equivalent for all 30 runs, no run errored. Results vary between runs of the
same repo.

## Earlier run (2026-10-17, detectors before v0.2.0)

| Kind | Category | Found | Planted x runs | Recall |
|---|---|---|---|---|
| same | FastAPI auth dependency removed | 24 | 27 | 89% |
| same | GitHub Actions job timeout removed | 15 | 39 | 38% |
| other | Inverted `if not` in a route | 14 | 30 | 47% |
| other | Step ignores failure (`continue-on-error`) | 18 | 30 | 60% |
| | **All** | **71** | **126** | **56%** |

Cost was $4.66. The gap between the two runs is the same model on the same bugs, so it shows
how much a single run of 30 can move.

## What this does and does not show

- Claude alone finds most removed auth dependencies, so the detector has to add something
  beyond what the model finds unaided to be worth using.
- **False alarms are not measured.** The scorer lists every file and line the answer points
  at that is not a planted bug. These are leads, not errors, and need to be read by hand
  before any precision figure exists.
- A planted bug counts as found when the answer names its file and a line within 5 of it, or
  names its function. This is mechanical and can over- or under-count.
- Three runs per repo, one model, and synthetic bugs.
