# Held-out set: baseline for the detectors alone

Run on 2026-10-17 with `bench/detector_recall.py` on bugs planted by `bench/mutations/plant.py`
in the repos listed in `bench/repos_heldout.json`. No Claude and no API key.

## Check that the script is right

On the benchmark set (`bench/repos.json`) it reports 2 of 9 removed FastAPI auth dependencies
and 0 of 13 removed job timeouts. Those are the figures in `detector-only.md`, which came from
an earlier scratch script, so the two agree.

## Result on the held-out set

| Planted bug | Planted | Reported |
|---|---|---|
| FastAPI auth dependency removed | 1 | 0 |
| GitHub Actions job timeout removed | 2 | 0 |

## Why this set cannot guide detector changes yet

- It is too small. The planter needs a route whose only dependency is an auth-named one, in a
  file with no router-level dependencies, and a job with a job-level timeout line. These repos
  give 3 such bugs in total. A result of 0 of 3 says almost nothing.
- Finding repos was hard because of the detector's own floor. Of 19 permissively licensed
  candidates, three have a folder with 20 or more routes, and two have 20 or more CI jobs.

## What would make it useful

- Add many more repos, which means loosening the floor for choosing them or widening the
  search. Or
- Measure on real projects instead of planted bugs, as the 577-project scan did: read every
  candidate by hand and track the false alarms and the real gaps, which is also the number
  users care about.
