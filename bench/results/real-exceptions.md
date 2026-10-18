# What the scan reports on real projects, labeled by hand

Run on 2026-10-18 on 29 real, unmodified repos kept locally: 19 FastAPI projects and CI-heavy
repos from the benchmark and held-out lists, plus ten more. Nothing was planted. The scan ran
at the default settings (a group of 20 items) and at the relaxed settings the skill falls back
to (a group of 8, confidence 0.5). Every exception it reported was read in the code and given
one label.

The per-item labels are not published. Some are possible security findings in other people's
projects, and those are for the owner to report privately or not at all. Only counts are here.

## Labels

- **Intentional:** public on purpose, such as a login step, a status page or a job that does
  nothing.
- **Real:** a gap worth fixing. Most are low-severity CI hygiene (a job with no timeout).
- **Unsure:** the code does not settle it.
- **False alarm:** the tool missed auth that is there, or the item is not product code.
- **Style:** a missing response model and nothing else.

## Results

| | Before | After the changes below |
|---|---|---|
| Exceptions at relaxed settings | 23 | 14 |
| Intentional | 10 (43%) | 5 (36%) |
| Real | 5 (22%) | 5 (36%) |
| Unsure | 4 | 3 |
| False alarm | 3 (13%) | 0 |
| Style | 1 | 1 |

Of the 5 real ones, 4 are CI hygiene (a missing timeout or permissions block) and 1 is a route
with no auth where its siblings have it.

At the default settings the scan reported 5 exceptions before the changes and 4 after. None
was a real gap: two were intentional and the rest unsure. On these 29 repos the strict scan
finds nothing worth fixing, which is what the 577-project scan also found.

## Changes made after reading the 23

Each is a convention the labeled items showed, and each has tests:

- A dependency built from a `fastapi.security` class is auth, whatever the variable is called.
  This removed two false alarms.
- Account-recovery and OAuth routes (forgot-password, reset-password, request-verify-token,
  verify, authorize) are public by nature.
- Folders named `tests` or `test` are not scanned. This removed a route that was only in a
  test file.
- A job whose only steps run `re-actors/alls-green` needs no timeout, and a workflow that is
  only called by others takes its permissions from the caller.

The rescan removed 9 of the 23 items. All 9 were intentional, unsure or false alarms, none was
a real gap, and no new item appeared.

## Limits

- **The "after" column is fitted.** The changes were made after reading these exact items on
  these exact repos, so the improvement says the fixes work on these cases, not that the tool
  generalizes. It needs checking on projects not used here.
- One reader labeled everything, from the code, and no maintainer confirmed any label.
  "Intentional" and "unsure" are judgement calls.
- 23 items is a small sample. The percentages move by several points with one item.
- The repos are not a random sample. Most were chosen because they are large enough for the
  scan to report on.
