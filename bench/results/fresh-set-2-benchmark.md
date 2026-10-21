# Second fresh held-out set: Claude alone (A) and the Deviant skill (B)

Run on 2026-10-21 against the sealed set in `bench/repos_fresh2.json`. The commit under test was
frozen before the first scan in `bench/FROZEN-2.md` (commit `7939fd0`): the redesigned skill,
which judges the scanner's leads and then reviews the route and workflow files itself. The
skill, scanner and detectors were not changed after that commit.

Planted bugs: 84 on 16 of the 20 repos (four repos got none), made with
`bench/mutations/plant.py` as named in `FROZEN-2.md`. No repo had a route where an auth
dependency could be removed, so the set has no auth bugs. Both arms used the same planted
copies, the same model (`claude-haiku-5-5`), the same audit prompt (`bench/run_benchmark.py`)
and three runs per repo.

## Results

| Kind | Bugs | A: Claude alone | B: Deviant skill |
|---|---|---|---|
| Ignored step failure (`continue-on-error`) | 39 | 54% (63 of 117) | **83%** (97 of 117) |
| Inverted `if not` in a route | 37 | **94%** (104 of 111) | 93% (103 of 111) |
| Job timeout removed | 8 | **38%** (9 of 24) | 25% (6 of 24) |
| **All bug-runs** | **84** | 70% (176 of 252) | **82%** (206 of 252) |

Cost: A $8.82, B $5.70 for 60 runs each (API-equivalent). No run errored.

Repo-level paired bootstrap (`bench/paired_bootstrap.py`, 10,000 resamples, 16 repos):

| Bugs | B minus A | 95% interval |
|---|---|---|
| All | +11.9 points | +1.4 to +23.6 |
| Kinds no detector checks | +14.5 points | +2.8 to +25.5 |
| Kinds a detector checks (timeouts, one repo) | -12.5 points | one repo, no interval |

## The pre-registered question

`bench/PREREGISTRATION.md` ("Second fresh set") asked whether the skill finds more than Claude
alone, and decided the answer before the set was chosen: yes if B minus A is above 0 with a
repo-level paired bootstrap 95% lower bound above 0. The lower bound is +1.4 points, so on this
set **the skill finds more planted bugs than Claude alone**, at about two thirds of the cost.
The bound is close to 0, so the size of the gain is uncertain: anywhere from about 1 to 24
points.

## What the numbers do and do not show

- **The gain comes from the skill's review step, not from the scanner.** The scan alone reports
  0 of the 8 timeout bugs on this set, and its inventory reaches few of the others. The
  structure of the skill (scan, judge the leads, then compare every handler and job with its
  siblings) found more than Claude reading freely.
- **The largest gain is on ignored step failures** (83% against 54%), which the scanner's
  `fails_on_error` feature and the review step both reach.
- **A disclosed caveat on inverted conditions.** The skill's review step names an inverted
  condition as an example of what to look for, and the planted "other" kind includes inverted
  `if not` conditions. This was written down before the run. Both arms find almost all of them
  (94% and 93%), so this kind adds nothing to the gap. The whole gain is on ignored step
  failures (29 points).
- **B is behind on removed timeouts** (25% against 38%), on 8 bugs in one repo. That is too few
  to say much.
- **Precision is not measured.** The full pass rule in `PREREGISTRATION.md` also needs
  precision labelled by hand (`bench/PRECISION-LABELLING.md`), so this run answers the recall
  question only. It does not show that the skill makes fewer false alarms.
- **Limits.** Synthetic bugs, one model, three runs per repo, 16 repos with bugs, and mechanical
  matching of answers to bugs (`bench/score_runs.py`). The repo clones are shallow, so the
  skill's git evidence was thin.

## How it was run

The pinned commits were cloned at depth 1, planted with `plant.py <clones> <out>
bench/repos_fresh2.json`, and each run used the command in `bench/run_benchmark.py` for its
arm. To go faster, runs were launched one at a time in parallel with the same command, model,
tools and record format. Scored with `bench/score_runs.py` and `bench/paired_bootstrap.py`.
