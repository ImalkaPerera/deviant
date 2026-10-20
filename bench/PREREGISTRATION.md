# Pre-registration for the next evaluation

Written on 2026-10-20, before any repo in the fresh set was chosen or scanned. These rules do
not change after the first scan of that set. If a rule must change, the set is spent and a new
one is drawn.

## Question

Does the Deviant skill, after the protocol change described in `deviant-plan.md` and the
improvement plan, find as many real bugs as Claude alone, with higher precision and a lower
cost?

This replaces the old Gate A rule ("recall at least 2x Claude alone"), which cannot be met:
Claude alone found about 55% of the planted bugs, and 2x would be over 100%.

## Arms

- **A**: Claude alone. Tools: Read, Grep, Glob. The audit prompt in `bench/run_benchmark.py`.
- **B**: Claude with the Deviant skill loaded from the commit named in `FROZEN.md`. The same
  prompt and model.
- Model for both: `claude-haiku-5-5`. Three runs per arm per repo.

## Bug sets

1. **Planted bugs**: made by `bench/mutations/plant.py` with its keyword rules, on the fresh
   repos, at about 20 per repo. Paired: the same bugs for both arms.
2. **Real bugs**: fixes found in git history (a commit that adds an auth dependency to a route,
   or a timeout to a job). The commit before the fix holds the bug. Each is verified by reading
   the diff. See `bench/real_bugs.json`. A real bug is the stronger test, because nobody chose
   it with the detector in mind.

## Fresh repo set

Chosen by this rule, which looks at no scan output:

- On GitHub, language Python, with FastAPI as a topic or dependency, or a repository with at
  least 5 workflow files.
- MIT or Apache-2.0 licence.
- Last pushed on or after 2026-07-01, and at least 50 stars.
- Not in `bench/repos.json`, `bench/repos_heldout.json`, `bench/repos_unseen.json` or
  `docs/tested-on-real-projects.md`.
- Taken in star order, about 12 FastAPI and 8 workflow-heavy repos, commits pinned.
- The detector's size floor is not a condition. Most projects fail that floor, and a set that
  required it would measure only the projects the scanner already suits.

### Amendment 1 (2026-10-20, before any scan)

The first draft of the selection returned libraries tagged `fastapi` (an ORM, a GraphQL
library) that define no routes, so no auth bug can be planted in them. The rule now also
requires, for the FastAPI kind, at least 10 lines in `.py` files that match the plain
text pattern `@<name>.get(`, `.post(`, `.put(`, `.patch(` or `.delete(`. This is a text match
counted by a script outside the scanner, and it is the only addition. The exclusion list is
also read from the repository links in `docs/tested-on-real-projects.md`, which the first
draft missed, so Polar, Douyin_TikTok_Download_API and WhisperLiveKit are excluded.

## Measures

- **Recall** (primary): found planted and real bugs over all of them, paired by bug. The unit
  is the bug, not the run. The interval is a paired bootstrap resampled by repo, 10,000
  resamples, 95%.
- **Precision**: of the findings labelled BUG, the share a person confirms as real. Labels are
  made by hand, blind to the arm, using `bench/PRECISION-LABELLING.md`. Pooled target is at
  least 246 labelled findings per arm.
- **False BUG per repo**: the median number of BUG findings per repo that are not real.
- **Cost**: API-equivalent dollars per run, from the run output.
- Every run is reported, including failed ones.

## Pass and stop rules

Pass, all of these:

1. Recall of B minus recall of A has a 95% lower bound above -5 points.
2. Precision of B has a Wilson lower bound of at least 70% and a point estimate of at least 80%.
3. B has higher precision than A by at least 10 points, or costs at most half as much per run.

Stop (do not launch the bug-finding claim), any of these:

1. Recall of B minus recall of A has a point estimate below -10 points.
2. Precision of B has a Wilson upper bound below 60% on at least 100 labelled findings.
3. The median false BUG count per repo is above 2.

Between the two lists, the result is "not shown", and the README says so.

## Frozen inputs

Before the first scan of the fresh set, the commit of the detectors and the skill is written to
`bench/FROZEN.md`. A change to either after that point makes the set tuning data.

## Sample sizes

- To detect a 10 point change in recall (56% against 66%, two-sided 0.05, power 0.80): 372
  bugs per arm unpaired. Paired with a correlation of 0.5, about 186. Clustered by repo with
  25 bugs per repo and an intra-repo correlation of 0.05 (design effect 2.2), about 410.
- Pooled precision at 80% with plus or minus 5 points: 246 labelled findings, and about twice
  that if labels cluster by repo.
