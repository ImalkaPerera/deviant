<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/logo-dark.svg">
    <img src="docs/assets/logo-light.svg" alt="Deviant" height="76">
  </picture>
</p>

<p align="center">
  <b>Find the one thing in your code that breaks the pattern.</b>
</p>

<p align="center">
  Deviant learns your project's own conventions, flags the exceptions,<br>
  and shows the git history you need to judge them.
</p>

<p align="center">
  <a href="https://pypi.org/project/deviant-scan/"><img src="https://img.shields.io/pypi/v/deviant-scan" alt="PyPI version"></a>
  <a href="https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml"><img src="https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%20to%203.14-blue" alt="Python 3.10 to 3.14">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT%20OR%20Apache--2.0-green.svg" alt="MIT or Apache-2.0 license"></a>
  <img src="https://img.shields.io/badge/status-early%20development-orange" alt="Early development">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#what-it-checks">What it checks</a> ·
  <a href="docs/tested-on-real-projects.md">Tested on real projects</a> ·
  <a href="#contribute">Contribute</a>
</p>

---

Picture a project with 48 API routes. 47 of them check who is calling. The 48th doesn't, and it
exports every user's data. Nobody noticed.

Every codebase runs on unwritten rules: every route checks auth, every CI job has a timeout,
every action is pinned to a commit. Nobody writes them down, so nobody checks them. Code review
catches what the reviewer remembers. AI coding agents write code that looks right and passes
tests, but can quietly forget the check every other route has.

Deviant counts what your code already does, picks out the rare item that breaks the pattern, and
shows the git history behind it. You write no rules.

<p align="center">
  <img src="docs/assets/demo.png" alt="Terminal output. The scan reports 48 routes, 47 of which follow the has_auth pattern. The exception is app/routes/items.py line 244, last changed by dana@example.com in the commit add csv export. The same author wrote 47 of the 47 compliant routes." width="100%">
</p>

Reading the output: `n=48 s=47 v=1` means 48 similar routes, 47 that check auth and 1 that doesn't.
The exception is at `app/routes/items.py:244`. The last two lines are the evidence: the same
person wrote all 47 routes that do check auth, so this looks like a slip, not a choice.

## Highlights

- **Finds the odd one out.** It learns your project's own conventions by counting, so there are
  no rules to write.
- **Deterministic.** The same code gives the same answer. Finding the exceptions needs no AI, no
  API key and no network.
- **Evidence, not guesses.** With `--with-git`, each finding comes with git history: who changed
  it, when, why, and how many of the protected items that person wrote.
- **Safe to run on code you don't trust.** It reads and parses files and never runs them. Git
  evidence uses read-only commands. Use 0.1.1 or newer; see [SECURITY.md](SECURITY.md).
- **Extensible.** A check is one Python file.
- **Tested on real projects,** with the false alarms we found [written down](docs/tested-on-real-projects.md).

## Quick start

You need Python 3.10 or newer and git.

```bash
pip install deviant-scan
deviant-scan path/to/your/project --with-git
```

To run it once without installing anything, use `uvx deviant-scan path/to/your/project --with-git`.

To have Claude judge each exception, install the plugin in Claude Code and run it on a project:

```text
/plugin install deviant --marketplace ImalkaPerera/deviant
/deviant:deviant path/to/project
```

It labels each exception as a bug, intentional or unsure, with proof. See
[using Deviant in Claude Code](docs/claude-code-skill.md). The plugin runs the Python on your
path, so run `pip install PyYAML` first if you want it to check GitHub Actions workflows.

Add `--json` for machine-readable output. Output is colored in a terminal and plain when piped
(`--color never` and the `NO_COLOR` variable turn it off). To work on Deviant itself, see the
[contributor guide](CONTRIBUTING.md).

## How it works

1. **Group.** A check lists similar things: every FastAPI route, every CI job.
2. **Count.** Plain math finds the pattern ("47 of 48 do this") and the rare exceptions. There
   is no AI in this step.
3. **Show the evidence.** Each exception comes with its git history.
4. **Judge.** The [Claude Code skill](docs/claude-code-skill.md) reads the evidence and labels
   each exception as a bug, intentional or unsure, with proof.

A pattern is only reported when the evidence is strong: a group of at least 20 similar items with
one to three exceptions. Small projects will often show nothing, on purpose. When that finds
nothing, the Claude Code skill scans again with looser limits (8 items) and calls what it finds a
weak lead. It also reads an inventory of every peer group (`--inventory`) and judges the items that
lack something most of their peers have. The math is in [how it works](docs/how-it-works.md) and the trade-offs are in
[limits](docs/limits.md).

## What it checks

| Check | Compares | Finds |
|---|---|---|
| **FastAPI routes** | each route with the others in its folder | a route missing the auth or rate limit its neighbours have (a missing response model shows with `--include-style`) |
| **GitHub Actions** | every workflow and composite action | an action not pinned to a commit, a job with no timeout, a workflow with no permissions block, a shell step that ignores its own failure (shown with `--inventory`) |

FastAPI auth is followed through routers, shared dependencies and `include_router`, so routes
that are protected from above are not reported. See [detectors](docs/detectors.md).

## How is this different?

| | Linters and Semgrep | Asking an AI to review the code | **Deviant** |
|---|---|---|---|
| Needs rules written first | Yes, or uses rules someone else wrote | No | **No**, it learns from your code |
| Notices "47 do this, one doesn't" | Only if a rule describes it | Often, but it varies from run to run | **Yes**, it counts, once a group has enough items |
| Same answer every run | Yes | Not guaranteed | **Yes** |
| Cost per scan | Free | Tokens | **Free**, and local |
| Why it flagged something | A rule message | An explanation in prose | **Numbers and git history** |

Deviant does not replace your linter or your reviewers. It finds what only counting can see.

## Honest by design

We publish what Deviant got wrong, not only what it got right.

- **547 real projects scanned** (from 577 found on GitHub), and every candidate read by hand.
- **On the first seven projects tried, one candidate at the default settings.** It turned out to
  be intentional: the project's own test asserts that the route is public.
- **Every problem found in real results has been fixed,** each with a regression test, and the
  early ones are [listed](docs/tested-on-real-projects.md#what-the-early-versions-got-wrong). The
  early version flagged all 23 routes of the FastAPI template as unprotected.
- **A hand-labeled check on 29 real repos.** After fixing the false alarms it found, the looser
  scan reported 14 items: 5 real gaps (4 of them low-severity CI hygiene), 5 intentional, 3 unsure
  and 1 style. The default scan found nothing worth fixing. The fixes were made on those same
  repos, so the numbers are optimistic. See [the results](bench/results/real-exceptions.md).
- **A second check on 15 repos the detectors had never seen** found no real gap. Six of its 18
  items were false alarms, all from one project whose auth dependencies have names with no auth
  word in them. A fix handles that case, and the fix is, again, fitted to those repos. See
  [the results](bench/results/unseen-repos.md).
- **The Claude Code skill was run in real sessions** on a real bug, an intentional exception and
  a prompt-injection attempt, and handled all three.
- **No bug confirmed by a maintainer in someone else's project yet.**
- **Benchmarks are published, and they are not flattering.** On a sealed fresh set of 99 bugs
  planted in 19 repos the scan had never seen, Claude reading the code alone found 45% and Claude
  with the Deviant skill found 35%. The skill is ahead on ignored step failures (76% against 51%)
  and removed auth checks (67% against 56%), and it finds none of the inverted conditions that no
  detector checks. On the older ten-repo set the skill was tuned up to 65% (against 52% for
  Claude alone), but that set is tuned data. Precision is not measured. On 12 constructed cases
  for judging, the skill and plain Claude both labeled nearly every case correctly, so those
  cases did not separate them. See [the results](bench/results/).

The full story is in [tested on real projects](docs/tested-on-real-projects.md).

## Roadmap

- [x] Count patterns and report the rare exceptions
- [x] FastAPI and GitHub Actions checks, with git evidence
- [x] A Claude Code skill that judges each finding: bug, intentional or unsure
- [ ] Saved rules, and a hook that warns an AI agent the moment it breaks one
- [ ] More checks: Dockerfiles, Flask, Express, Spring, Kubernetes, Terraform
- [ ] A benchmark that shows Deviant beating asking Claude alone (not yet: 35% against 45% on the
      fresh set, see `bench/results/fresh-set-benchmark.md`)
- [x] A PyPI release

## Contribute

Deviant is early, and early contributors shape what it becomes. A check is one Python file. If
you know a framework well enough to say "every X should have a Y", you can add it.

- **Add a check.** Copy the [short template](skills/deviant/scripts/deviant_scan/detectors/_template.py). The
  [contributor guide](CONTRIBUTING.md) has a complete example and [starter ideas](CONTRIBUTING.md#where-to-help).
- **Report a false alarm.** If Deviant flags something that is fine,
  [open an issue](https://github.com/ImalkaPerera/deviant/issues/new/choose). These reports improve
  it fastest.
- **Try it on your project** and tell us what it found or missed.

No API key is needed to run any test.

## Learn more

[How it works](docs/how-it-works.md) · [Claude Code skill](docs/claude-code-skill.md) ·
[Reading the output](docs/reading-the-output.md) ·
[Detectors](docs/detectors.md) · [Configuration](docs/configuration.md) ·
[Limits](docs/limits.md) · [Benchmarks](bench/results/) · [Security](SECURITY.md)

The idea comes from Engler et al., [*Bugs as Deviant Behavior*](https://www.cs.columbia.edu/~junfeng/09fa-e6998/papers/deviant.pdf)
(SOSP 2001), which showed that rare exceptions to a common pattern often point to real bugs.
Related work: [Laravel `infer-conventions`](https://laravel.com/blog/extracting-ai-rules-from-an-existing-codebase),
[codebase-dna-guardian](https://github.com/mturac/codebase-dna-guardian),
[Trail of Bits `semgrep-rule-creator`](https://lobehub.com/skills/trailofbits-skills-semgrep-rule-creator).

Licensed under either of the [MIT license](LICENSE) or the [Apache License 2.0](LICENSE-APACHE), at your option.
