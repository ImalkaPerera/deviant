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
| Ignored step failure (`continue-on-error`) | 36 | 56% | **74%** |
| Inverted `if not` in a route | 36 | **64%** | 2% |
| Auth dependency removed | 9 | **100%** | 67% |
| Job timeout removed | 18 | **13%** | 6% |
| **All bug-runs** | **99** | **55%** (163 of 297) | **35%** (103 of 297) |

Cost: A $6.88, B $0.79 (API-equivalent). No run errored.

### Correction (2026-10-21)

This page first gave A 45% (133 of 297) and B 35% (103 of 297). An audit of the scorer found it
read only the first line number in each mention, so it missed forms such as
`chatbot.py:40`, `:82`, `:152`, which name four routes on one line. It also let one mention
credit two nearby bugs, and counted a place the answer had cleared as INTENTIONAL as a find.
`bench/score_runs.py` was fixed, with tests in `tests/test_score_runs.py`, and both arms were
scored again from the same saved answers. A gained 30 bug-runs. B gained 4 and lost 4 (all three
runs on one LlamaFactory step had looked at it and called it INTENTIONAL).

The same audit found two faults in the planting tool, which affect both arms equally: 12 of the
36 `continue-on-error` lines were recorded one line off (3 on the wrong step), and 5 of the 9
auth bugs removed a dependency that is not auth (`get_user_manager`, `get_user_svc`). Both are
fixed in `bench/mutations/plant.py` for the next set. This set was not planted again, because
its bugs are already sealed in the saved answers.

## What the numbers do and do not show

- **B is 20 points behind A overall.** Most of the gap is the inverted-condition kind, which no
  detector checks: B found 2 of 108 bug-runs. The skill as frozen told Claude to judge the
  scanner's leads and nothing else, so it never read the rest of the code.
- **B is ahead only on ignored step failures** (74% against 56%), the kind the scanner and the
  inventory reach best.
- **A found every auth removal** (27 of 27), against 67% for B. Five of the nine auth bugs were
  not real auth (see the correction), and A flagged them anyway because the file looked wrong.
- **Job timeouts are low for both arms** (13% and 6%). In these repos the planted timeout bugs sit
  mostly in workflows with too few jobs for the statistics to pass.
- **The set is underpowered,** but a 20-point gap is past the stop line either way.
- **Precision is not measured.** No findings have been labelled by hand (see
  `bench/PRECISION-LABELLING.md`), so the false-alarm side of the comparison is missing.
- **The real-bug set was not used here.** Its fix commits come from these same repos, and scanning
  the current code cannot find bugs that were already fixed. Real-bug recall needs the parent
  commit of each fix and is not yet set up.

## Pre-registered rule

Under `bench/PREREGISTRATION.md`, a pass needs the recall difference (B minus A) to have a
lower bound above -5 points and precision to be met. The stop rule is a point estimate below
-10 points. The point estimate here is -20 (35% minus 55%), so **the stop rule is met**: the
skill as frozen at `648a1e0` is worse than Claude alone on this set. (The first scoring put the
estimate at exactly -10, on the line; the corrected scorer moves it well past it.)

The response is the redesign recorded in `bench/PREREGISTRATION.md` under "Second fresh set":
the skill now reviews the route and workflow files itself after judging the leads, and it is
tested on a second sealed set chosen before the redesign was run on it. That result is in
`fresh-set-2-benchmark.md`: there the skill found 82% against 70% for Claude alone.

## Development runs on the earlier planted set (for context)

On the older planted set, which the skill changes were tuned on, B rose from 12% to 65% (see
`condition-b-skill.md`). That is tuned data and does not stand in for this result.
