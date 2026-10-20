# Fresh held-out set: Claude alone (A) and the Deviant skill (B)

Run on 2026-10-20 against the sealed set in `bench/repos_fresh.json`. The commit under test was
frozen before the first scan in `bench/FROZEN.md` (commit `648a1e0`). The detectors and the
skill were not changed after that commit. Later commits changed only the planting caps in
`bench/mutations/plant.py` and the result pages.

Planted bugs: 99 on 19 repos (`slackapi/bolt-python` got none), made with `bench/mutations/plant.py`
at raised caps. Both arms used the same planted copies, the same model (`claude-haiku-5-5`), the
same audit prompt, and three runs per repo: 60 runs per arm, 297 bug-runs in all.

## Results

| Kind | Bugs | A: Claude alone | B: Deviant skill |
|---|---|---|---|
| Ignored step failure (`continue-on-error`) | 36 | 51% | **76%** |
| Inverted `if not` in a route | 36 | **54%** | 0% |
| Auth dependency removed | 9 | 56% | **67%** |
| Job timeout removed | 18 | **9%** | 6% |
| **All bug-runs** | **99** | **45%** (133 of 297) | **35%** (103 of 297) |

Cost: A $6.88, B $0.79 (API-equivalent). No run errored.

## What the numbers do and do not show

- **B is 10 points behind A overall.** The gap is almost all in the inverted-condition kind, which
  no detector checks. B found none of those.
- **B is ahead on the two kinds the scanner and the inventory reach:** ignored step failures by 25
  points and auth removals by 11. Both are small counts (36 and 9 bugs), so they are suggestive.
- **Job timeouts are low for both arms** (9% and 6%). In these repos the planted timeout bugs sit
  mostly in workflows with too few jobs for the statistics to pass.
- **The set is underpowered.** 99 bugs cannot reliably detect a 10-point difference
  (`bench/PREREGISTRATION.md` calls for about 410). The overall gap of 10 points sits at that
  threshold, so the result does not settle whether B is worse.
- **Precision is not measured.** No findings have been labelled by hand (see
  `bench/PRECISION-LABELLING.md`), so the false-alarm side of the comparison is missing.
- **The real-bug set was not used here.** Its fix commits come from these same repos, and scanning
  the current code cannot find bugs that were already fixed. Real-bug recall needs the parent
  commit of each fix and is not yet set up.

## Pre-registered rule

Under `bench/PREREGISTRATION.md`, a pass needs the recall difference (B minus A) to have a
lower bound above -5 points and precision to be met. The stop rule is a point estimate below
-10 points. The point estimate here is exactly -10 (35% minus 45%), which sits on that stop line.
The lower bound has not been computed, because it needs a repo-level bootstrap that is not yet
set up, and precision has not been measured at all. So the rule is **not met**, and the result is
neither a pass nor a clear stop.

## Development runs on the earlier planted set (for context)

On the older planted set, which the skill changes were tuned on, B rose from 12% to 65% (see
`condition-b-skill.md`). That is tuned data and does not stand in for this result.
