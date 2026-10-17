# Detector only, on planted bugs (condition D, no AI)

Run on 2026-10-17 with the detectors as of commit `46238f5`, the last detector change.
Planted copies were made with `bench/mutations/plant.py` from the pinned SHAs in
`bench/repos.json`. Nothing here uses Claude or any API key.

## Results

| Kind | Planted | Reported by the scan | Notes |
|---|---|---|---|
| FastAPI auth dependency removed | 9 | **2** (22%) | Both in one rule (`is_mutating_implies_has_auth`, transmute). The rest are in groups with more than 3 exceptions, a group too small, or a GET route outside the mutating rule. |
| GitHub Actions job timeout removed | 13 | **0** (0%) | Job timeouts are set in less than 80% of jobs in every repo here, so the plain rule never passes its confidence bound. |
| Other kind (inverted `if not`, step ignores failure) | 19 | not checked | No detector looks for these, so they are not expected to be reported. |

The planted bugs themselves are not hand-checked yet. The other-kind bugs in particular need a
check that the flipped condition still changes behaviour.

## Why the numbers are low

1. Real projects have natural exceptions (health checks, login, webhooks). Three planted bugs
   on top of them push a group over the limit of 3 exceptions.
2. A GitHub Actions rule about timeouts needs most jobs to have one. In these repos, most do not.
3. Route-level auth that appears only in some folders is invisible to a folder-level rule.

## How it was measured

- A planted route counts as reported only if the scan lists it as an exception in the same file,
  on the route's decorator or `def` line. (An earlier pass matched the parameter line and gave
  a wrong answer. That is fixed.)
- A planted GitHub Actions job counts as reported only if the scan lists the job's key line.

## Limits

- One planted bug per run. Several bugs in one folder interact, which this does not measure.
- Repos were chosen by keyword rules before this measurement, not by the detector's output.
