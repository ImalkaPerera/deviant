# Condition A: Claude alone, on planted bugs

Run on 2026-10-17. Each of the 10 pinned repos in `bench/repos.json` was copied with
`bench/mutations/plant.py`, which plants 42 known bugs. Claude Haiku 5.5 then read each copy
with the tools Read, Grep and Glob and no other help, three times per repo (30 runs). The
prompt asked for places where almost every similar item follows a pattern but one or two
break it, with a file, line and reason for each. See `bench/run_benchmark.py`. Scored with
`bench/score_runs.py`.

## Results

| Kind | Category | Found | Planted x runs | Recall |
|---|---|---|---|---|
| same | FastAPI auth dependency removed | 24 | 27 | 89% |
| same | GitHub Actions job timeout removed | 15 | 39 | 38% |
| other | Inverted `if not` in a route | 14 | 30 | 47% |
| other | Step ignores failure (`continue-on-error`) | 18 | 30 | 60% |
| | **All** | **71** | **126** | **56%** |

"Same" means a bug of the kind the detectors check. "Other" means a kind no detector checks.
For comparison, the detectors alone (no AI) reported 2 of 9 removed FastAPI auth
dependencies and 0 of 13 removed job timeouts: see `detector-only.md`.

Cost: $4.66 API-equivalent for all 30 runs, no run errored. Results vary a lot between runs
of the same repo. For astral-sh/uv, one run found 3 of 5 planted bugs and two found none.

## What this does and does not show

- Claude alone finds most removed auth dependencies, so the detector has to add something
  beyond what the model finds unaided to be worth using.
- **False alarms are not measured.** The scorer lists every file and line the answer points
  at that is not a planted bug (5 to 46 per run). These are leads, not errors: in the one
  answer read closely, the model reported plausible real problems that were not planted.
  They need to be read by hand before any precision figure exists.
- A planted bug counts as found when the answer names its file and a line within 5 of it, or
  names its function. This is mechanical and can over- or under-count.
- Three runs per repo, one model, and synthetic bugs. Conditions B (with the Deviant skill)
  and C (with a self-written counting script) have not been run, so this does not yet say
  whether Deviant helps.
