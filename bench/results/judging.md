# Judging: can Claude tell a bug from an intentional exception?

Run on 2026-10-18 with `bench/judging/`. This tests the step the Deviant skill is built for:
given one route that lacks the auth its siblings have, label it BUG or INTENTIONAL. The
benchmark in `condition-a-claude-alone.md` tested finding bugs, which is a different job.

## Cases

Twelve constructed cases, all from one real project, `fastapi-practices/fastapi-best-
architecture` at commit `514211d`. Its folder `backend/app/admin/api/v1/sys` has 58 routes
that all check auth. Each case is a copy with its own git history: one commit with the
original code, then one commit that removes the auth dependency from a single route. The scan
reports exactly that route in all 12 cases (`bench/judging/validate_cases.py`).

- 6 **BUG** cases: the auth is removed and nothing else changes.
- 6 **INTENTIONAL** cases: the auth is removed, a comment above the route says it is public
  on purpose, and a new test asserts it answers without a token.

All 12 routes are read-only GETs from the same pool, so the route name gives nothing away.
The truth is set by construction, not by anyone's reading of the code.

## Results

Claude Haiku 5.5, three runs per case (36 runs per condition).

| Condition | Right | Wrong | Unsure |
|---|---|---|---|
| Deviant skill (runs its own scan) | 36 | 0 | 0 |
| Claude alone (told which route was flagged, and that 57 of 58 siblings have auth) | 35 | 0 | 1 |

Both labeled all 18 intentional runs INTENTIONAL, and neither called an intentional route a
BUG. The only difference is one run of plain Claude that said UNSURE on a bug case. The skill
cost $0.25 for the 36 runs and plain Claude $0.21.

## What this does and does not show

- **It does not separate the two.** A difference of one run in 36 is noise. The cases are
  easy: the intentional ones carry explicit evidence (a comment and a test), and the bug
  ones carry none, so either condition can read the answer off the code.
- It shows the skill does not cry wolf when the evidence of intent is explicit, and that it
  labels a plain removal as a bug.
- It does not show how either condition handles ambiguous cases, where the evidence is
  missing, weak or conflicting. Those are the cases that matter, and they need real labeled
  exceptions from real projects. We have none: the hand-labeled 577-project results were not
  kept.
- One project, 12 cases, one model, and constructed evidence. The evidence for intent was
  written by us, so the setup flatters any reader who looks for a comment or a test.
- All commits in a case have one author, so the git signal "the same author wrote the
  protected routes" is present in every case and tells the two kinds apart not at all.

## A flaw this found in the tool, now fixed

The scan reported a route at its `def` line, and git evidence was taken from the commit that
last changed that line. In FastAPI the auth usually sits in the decorator above it, so when
the decorator was edited the evidence pointed at the older commit. One answer noticed this
itself: "The scanner attributed the exception to the initial commit. The actual removal is
in the latest commit." Detectors can now report a span, and for a route it runs from the
first decorator to the `def` line. Git evidence uses the newest change in the span. The runs
above were made before the fix, so they used the older evidence.
