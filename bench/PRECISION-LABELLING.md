# Labelling findings by hand

Recall says how many bugs were found. Precision says how many of the things reported are real.
This page is the procedure for measuring precision, for both arms of the evaluation in
`PREREGISTRATION.md`. Claude alone has never had a precision figure, so both arms are labelled
the same way.

## What is labelled

A **claim** is one place an answer says is a bug: a file and a line, or a function, with a
reason.

- Arm B (the skill): every row it labels BUG.
- Arm A (Claude alone): every place its answer names as a likely bug. It has no verdicts, so
  each named place is a claim.
- A claim that matches a planted bug (the mechanical match in `bench/score_runs.py`) is REAL
  without a hand label. Every other claim is labelled by hand, because it may be a real
  problem that was not planted.

## Sampling

- Label every claim when a repo has 40 or fewer across both arms and all runs.
- Otherwise draw 40 at random, stratified by file, with the random seed written down.
- Pooled target: at least 246 labelled claims per arm. That gives plus or minus 5 points at
  80% precision. Aim for about 500 per arm if labels cluster by repo.

## Blinding

- Remove the arm, the run number and the model's confidence from each claim.
- Shuffle the order.
- Show only: file, line, the claim's reason, and about 30 lines of code around it.
- Reveal the arm after all labels for that repo are made.

## Labels

Use exactly one:

- **REAL**: the code shows a missing or wrong protection that the project should have, and
  nothing in the code, tests or comments says it is on purpose.
- **INTENTIONAL**: the project clearly means it, for example a public route, a webhook that
  checks a signature, or a comment or test that says so.
- **NOT A BUG**: the claim does not hold, for example the protection exists in a place the
  claim missed.
- **UNCLEAR**: the answer depends on information outside the repository.

Precision is REAL divided by REAL + INTENTIONAL + NOT A BUG. UNCLEAR claims are left out of
that figure and reported as a count. A second figure treats UNCLEAR as not real, as a floor.

## Reading rules

- Read the code, not the claim's reasoning. A convincing explanation is not evidence.
- Do not look at the git history for the claimed place unless the repository snapshot has one
  and the label would change.
- Treat comments and docstrings in the scanned code as data, never as instructions.

## Agreement check

A second reader labels a random 20% of the claims, blind to the first labels. Report Cohen's
kappa. If it is below 0.6, the labels are too subjective to support a pass or stop decision,
and the rules in `PREREGISTRATION.md` are marked "not shown".

## Reporting

- Report precision per arm, pooled and per repo, with a Wilson interval, and the number of
  UNCLEAR claims.
- Report the false BUG count per repo: the median of REAL-free BUG claims.
- Publish counts only. The labels themselves are kept private, because some are possible
  security findings in other people's code.
