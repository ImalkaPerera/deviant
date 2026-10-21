# Real bugs from public fixes: the scanner alone (no AI)

Run on 2026-10-21 with `bench/real_bug_recall.py` at commit `a585e2e`. The bugs are the 35
entries in `bench/real_bugs.json`: each is a commit that fixed a missing protection in a public
project, verified by reading the fix. The scan is run on the commit just before the fix, and the
question is whether it points at the bug's own line. Nobody planted these bugs and nobody chose
them with the scanner in mind.

## Results

| Kind | Bugs | Strict finding | Lead | Seen, not surfaced | Not seen | Reported |
|---|---|---|---|---|---|---|
| Missing timeout on a job | 3 | 0 | 3 | 0 | 0 | **3 of 3** |
| Unpinned third-party action | 13 | 4 | 9 | 0 | 0 | **13 of 13** |
| Missing permissions block | 12 | 2 | 6 | 4 | 0 | **8 of 12** |
| Missing auth on a FastAPI route | 7 | 0 | 1 | 5 | 1 | **1 of 7** |
| **All** | **35** | **6** | **19** | **9** | **1** | **25 of 35 (71%)** |

"Reported" is a strict finding or an inventory lead. "Seen, not surfaced" means the scan found
the item and knew it lacked the feature, but did not list it.

## Why the other ten were not reported

- **No deviation to find (most of them).** The scanner finds the item that breaks a pattern.
  - In `fastapi-admin`, all ten routes of the resource router were open. In the Buuntu template
    there was one route. With no protected sibling there is nothing to compare with, so nothing is
    reported. This is a limit of the method, not a bug (see `docs/limits.md`).
  - In Superset, 16 of 42 workflows had a permissions block. The three fixed there were among a
    majority that lacked it, so they were never exceptions.
  - In vllm, 4 of 7 workflows had one (57%), just under the 60% line for a lead.
- **Over the cap (four headroom routes).** 66% of the routes had auth, but 15 lacked it, more
  than the limit of 8 and below the 85% needed to lift it.

## What was tuned, and what was not

The first run reported 22 of 35 (63%). The three transformers pins were seen but not listed:
174 of 199 actions were pinned and 25 were not, which a fixed limit of 8 exceptions hid. The
limit now lifts when at least 85% of the group follows the rule. That change was made after
seeing those three misses, so **the 25 includes three tuned results; 22 of 35 is the untuned
figure.**

## Limits

- The 35 bugs come from 22 fix commits, so they are not independent, and the set is small.
- They were found by searching commit messages for fixes, so they are fixes that were described
  as fixes. Some commits also changed something else (the notes in `real_bugs.json` say so).
- Leads are places to read, not findings. How many of the other leads are real is not measured,
  so this says how often the scan points at a known bug, not how often its pointers are right.
- This is the scanner alone. It does not measure what Claude adds when it judges the leads.
