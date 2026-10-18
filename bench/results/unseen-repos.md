# Do the fixes hold on repos the detectors had never seen?

Run on 2026-10-18 on 15 repos from `bench/repos_unseen.json`, none used before. The rule for
choosing them is in that file and does not look at what the scan reports. The scan ran at the
default settings and at the relaxed settings the skill falls back to (a group of 8, confidence
0.5). Every reported item was read in the code and given one label, as in
[real-exceptions.md](real-exceptions.md). Per-item labels are not published, only counts.

## Results

18 distinct items at the relaxed settings, 5 of them also at the default settings.

| Label | Items | Share |
|---|---|---|
| Real gap | 0 | 0% |
| Intentional | 5 | 28% |
| Style only | 6 | 33% |
| False alarm | 6 | 33% |
| Unsure | 1 | 6% |

- **No real gap in 15 projects.** At the default settings the scan reported 5 items: 3 were a
  missing response model and 2 were routes that are public on purpose (a first-run setup route
  and a status flag).
- **All 6 false alarms came from one project.** Its auth dependencies are named
  `validate_dashboard_session` and `validate_codex_provider_usage_identity`, which contain no
  word the detector reads as auth. The routes were protected, either by that dependency on the
  route or by the router.
- **The five intentional items** were a first-run setup route, a public status flag, a
  registration route, and two release workflows triggered by unique tags.
- **Style-only items are a third of the output.** Most are responses that cannot have a response
  model, such as streams.

## Do the earlier fixes generalize?

Partly, and it is hard to say from this. The conventions added after the first labeling
(security scheme classes, account-recovery routes, test folders, results-gathering jobs,
reusable workflows) caused no harm here, and a rescan of the earlier 29 repos after the new
change below gave the same 18 items. But the unseen repos mostly failed in a new way, a
dependency name with no auth word in it, so those fixes were barely exercised.

## The change this led to

A dependency named `validate_…session` or `validate_…identity` now counts as auth, while a plain
`validate_pagination` does not. Rescanning the same 15 repos removed exactly those 6 false
alarms and added none, leaving 12 items: 6 style, 5 intentional, 1 unsure, no false alarm.

That second column is fitted: the change was made after reading these repos, so it says the fix
works on these cases and nothing more. A name-based rule will keep missing auth that is named
without a recognized word. Router-level checks and settings the user can add (see
[configuration](../../docs/configuration.md)) are the way out, and the scan cannot guess them.

## Two more changes: hide style by default, and show the dependencies

The names cannot all be guessed, and style-only items were a third of the output. So:

- A missing response model is now reported only with `--include-style`. The scan counts what it
  hid. On these repos that hides all 6 style items, leaving 6 items at the relaxed settings
  (5 intentional, 1 unsure) and 2 at the default settings (both intentional). On the earlier 29
  repos it hides 1 more, leaving 13 items, 5 of them real.
- An auth exception now lists the dependencies on that route, leaving out plain plumbing such as
  `get_db`, with a note to name a dependency in `.deviant/config.json` if it checks who is
  calling. This turns a false alarm into something a user can fix in one line.

These are counted from the labels above, not remeasured, and the same caveat holds: they were
chosen after reading these repos.

## What this adds up to

Across the 44 repos read so far, the default scan has found nothing worth fixing. The only real
gaps are 5 from the earlier 29 repos, 4 of them low-severity CI hygiene, and none from these 15.
Most of what the scan reports is intentional or style-only. Whether it finds real bugs at a rate
worth the noise is still not shown.

## Limits

- One reader labeled everything from the code, and no maintainer confirmed any label.
- 18 items is a small sample, and 6 of them come from a single project, so the false-alarm share
  would be 0% or 33% depending on whether that project is in the sample.
- The 15 repos are not a random sample: they were chosen to be large enough for the scan to
  report on, and ordered by stars.
