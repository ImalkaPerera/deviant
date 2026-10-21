# Frozen inputs for the second fresh held-out set

Frozen on 2026-10-21, before any repo of `bench/repos_fresh2.json` was scanned or planted.

- Commit under test: `7939fd0005612274540019780edaf38f981b8fb8` (the redesigned skill, which
  reviews route and workflow files after judging the scanner's leads; the scanner and detectors
  as at `1dddadc`).
- Any change to the skill, scanner or detectors after this commit makes this set tuning data.
  A change means freezing a third set, not rescanning this one.
- Set chosen by the rule in `bench/PREREGISTRATION.md` ("Second fresh set"). Excluded: every
  repo in `repos_fresh.json` and `repos_mined.json`.
- Planting: `bench/mutations/plant.py` as at `7c45df3` (line offsets and non-auth dependency
  fixes applied).
- Run on 2026-10-21 at this commit. Results: `bench/results/fresh-set-2-benchmark.md`. The set
  is now spent: any later change to the skill, scanner or detectors needs a third set.
