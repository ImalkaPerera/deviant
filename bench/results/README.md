# Benchmark results

What we measured, in the order it was done. Each page states its own limits. The short version
is that Deviant does not yet beat asking Claude alone at finding bugs.

| Page | What it measures | Headline |
|---|---|---|
| [detector-only.md](detector-only.md) | The scan alone (no AI) on bugs planted in ten real repos | 2 of 9 removed FastAPI auth checks reported, 0 of 13 removed job timeouts |
| [condition-a-claude-alone.md](condition-a-claude-alone.md) | Claude reading the code with no help, same planted bugs | 71 of 126 found (56%) |
| [condition-b-skill.md](condition-b-skill.md) | Claude with the Deviant skill, same planted bugs | 9 of 126 (7%), then 14 of 126 (11%) with a relaxed second scan, tuned on this set |
| [judging.md](judging.md) | Labeling a flagged route as bug or intentional, on 12 constructed cases | Skill 36 of 36 right, plain Claude 35 of 36. The cases were too easy to separate them |
| [real-exceptions.md](real-exceptions.md) | Every exception the scan reports on 29 real repos, labeled by hand | After fixes: 14 items, 5 real gaps, 5 intentional, 3 unsure, 1 style |
| [unseen-repos.md](unseen-repos.md) | The same hand-labeling on 15 repos the detectors had never seen | 18 items, 0 real gaps, 6 false alarms from one project (fixed afterwards) |
| [heldout-baseline.md](heldout-baseline.md) | A second repo set for checking detector changes | Too small to guide changes yet: 3 plantable bugs, none reported |

## How to read these

- The planted-bug runs measure **finding** bugs. The judging run measures **labeling** them,
  which is what the skill is for.
- Planted bugs are synthetic, three runs per repo, one model (Claude Haiku 5.5), and answers are
  matched to bugs mechanically. False alarms are not measured in the planted-bug runs.
- Per-item labels for real projects are not published, because some are possible security
  findings in other people's code. Only counts are here.

## Reproducing

The scripts are in [`bench/`](..): `mutations/plant.py` plants the bugs, `run_benchmark.py` and
`judging/run_judging.py` run Claude, `score_runs.py` and `judging/score_judging.py` score the
answers, and `detector_recall.py` measures the scan alone. The repos and their pinned commits
are in `repos.json` and `repos_heldout.json`. Running Claude needs the `claude` command-line
tool and uses your plan's usage.
