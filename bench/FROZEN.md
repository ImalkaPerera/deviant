# Frozen inputs for the fresh held-out set

Frozen on 2026-10-20 before the first scan of `bench/repos_fresh.json`.

- Commit under test: `9e3b367e14b6e5bbb527bce729731184c709bf00` (the skill, the scanner, the detectors and their feature set).
- Any change to detectors, scanner or skill after this commit makes the fresh set tuning data.
  A change means freezing a new set, not rescanning this one.

Detector features in this commit: auth dependency and mutating routes (with mounts, dependency
bodies, classes), GitHub Actions timeouts, concurrency, permissions, pinned third-party steps,
and continue-on-error on shell steps. Inventory scopes: group and file.
