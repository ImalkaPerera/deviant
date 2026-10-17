# How Deviant works

Deviant counts what your code already does and reports the rare items that differ.

| Step | What happens | Status |
|---|---|---|
| 1. Group | Detectors list similar items, such as all FastAPI routes or all CI jobs. | ✅ Built |
| 2. Count | Plain math finds patterns like "47 of 48 do X". Same input, same output. No AI. | ✅ Built |
| 3. Evidence | Each exception gets its git history: who last changed the line, when, why, and how many of the protected items that same author wrote. | ✅ Built (`--with-git`) |
| 4. Judge | Claude reads the evidence, comments and tests, and labels each exception BUG, INTENTIONAL or UNSURE with proof. | ✅ Built ([Claude Code skill](claude-code-skill.md)) |
| 5. Approve | You choose which rules to keep. | 🚧 Planned |
| 6. Enforce | Approved rules become permanent checks. | 🚧 Planned |
| 7. Guard | A Claude Code hook checks each AI edit and warns when a rule is broken. | 🚧 Planned |

<details>
<summary><strong>How strong must the evidence be?</strong></summary>

A pattern is only reported when the evidence is strong. All of these must hold:

- the group has at least **20** items (`--min-items`),
- there are **1 to 3** exceptions,
- the [Wilson score](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval)
  lower bound of the share that follows the pattern is at least **0.80** (`--min-confidence`).

The Wilson bound asks: "How sure can we be that this really is the norm, given how
few items we have?" 47 of 48 gives 0.891 and is reported. 19 of 20 gives 0.764 and is not.

</details>

## Why small projects show nothing

The Wilson bound is strict on purpose. The smallest group that can be reported:

| Exceptions | At 0.80 (default) | At 0.75 |
|---|---|---|
| 1 | 25 items | 19 items |
| 2 | 33 items | 25 items |
| 3 | 40 items | 31 items |

A project with 15 routes will not get route findings. That is by design: with so few
items, "14 of 15" is not strong evidence of a rule.
