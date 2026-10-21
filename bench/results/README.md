# Benchmark results

What we measured, in the order it was done. Each page states its own limits. The short version
is that the redesigned skill finds more planted bugs than asking Claude alone on a sealed set
(83% against 70%), and precision has not been measured for either.

| Page | What it measures | Headline |
|---|---|---|
| [detector-only.md](detector-only.md) | The scan alone (no AI) on bugs planted in ten real repos | 2 of 9 removed FastAPI auth checks reported, 0 of 13 removed job timeouts |
| [condition-a-claude-alone.md](condition-a-claude-alone.md) | Claude reading the code with no help, same planted bugs | 65 of 126 found (52%) on the v0.2.0 re-run, 71 of 126 (56%) on the first run |
| [condition-b-skill.md](condition-b-skill.md) | Claude with the Deviant skill, same planted bugs | 15 of 126 (12%) as shipped in v0.2.0. Development runs on this same set rose to 25%, 41% and 65% after the inventory, file scope and a continue-on-error feature were added. That is tuned data |
| [judging.md](judging.md) | Labeling a flagged route as bug or intentional, on 12 constructed cases | Skill 36 of 36 right, plain Claude 35 of 36. The cases were too easy to separate them |
| [real-exceptions.md](real-exceptions.md) | Every exception the scan reports on 29 real repos, labeled by hand | After fixes: 14 items, 5 real gaps, 5 intentional, 3 unsure, 1 style |
| [unseen-repos.md](unseen-repos.md) | The same hand-labeling on 15 repos the detectors had never seen | 18 items, 0 real gaps, 6 false alarms from one project (fixed afterwards) |
| [heldout-baseline.md](heldout-baseline.md) | A second repo set for checking detector changes | Too small to guide changes yet: 3 plantable bugs, none reported |
| [fresh-set-benchmark.md](fresh-set-benchmark.md) | Claude alone and the skill on 99 bugs planted in 19 repos the skill was never tuned on | A 55% (163 of 297), B 35% (103 of 297) after a scorer fix (first published as A 45%). The pre-registered stop rule is met |
| [real-bugs.md](real-bugs.md) | The scan alone (no AI) on 35 real bugs from public fix commits, at the commit before each fix | 25 of 35 reported (71%), 22 of 35 before one limit was tuned. Timeouts 3 of 3, pins 13 of 13, permissions 8 of 12, auth 1 of 7 |
| [fresh-set-2-benchmark.md](fresh-set-2-benchmark.md) | Claude alone and the redesigned skill (it reviews the code after judging the leads) on 84 bugs planted in 16 sealed repos | B 83% (197 of 237), A 70% (176 of 252). Paired bootstrap +13.3 points, 95% interval +4.5 to +24.0. Provisional, 57 of 60 B runs |
| [fresh-set-deterministic.md](fresh-set-deterministic.md) | The scan alone, no AI, on the same 20 fresh repos | 13 strict rule exceptions in 5 repos, 111 inventory leads |

## How to read these

- The planted-bug runs measure **finding** bugs. The judging run measures **labeling** them,
  which is what the skill is for.
- Planted bugs are synthetic, three runs per repo, one model (Claude Haiku 5.5), and answers are
  matched to bugs mechanically. False alarms are not measured in the planted-bug runs.
- The scorer was fixed on 2026-10-21 (every line-reference form, one reference per bug, places
  cleared as INTENTIONAL not counted). On the fresh set this moved A from 45% to 55%. On the
  older ten-repo set nothing moved by more than one bug-run (A 65 to 66, the B development runs
  52 to 51 and 82 to 81), so those pages keep their first numbers.
- Per-item labels for real projects are not published, because some are possible security
  findings in other people's code. Only counts are here.

## Reproducing

The scripts are in [`bench/`](..): `mutations/plant.py` plants the bugs, `run_benchmark.py` and
`judging/run_judging.py` run Claude, `score_runs.py` and `judging/score_judging.py` score the
answers, and `detector_recall.py` measures the scan alone. The repos and their pinned commits
are in `repos.json` and `repos_heldout.json`. Running Claude needs the `claude` command-line
tool and uses your plan's usage.
