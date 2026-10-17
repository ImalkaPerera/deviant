<p align="center">
  <img src="docs/assets/banner.svg" alt="Deviant: catch the one route that forgot its auth check" width="100%">
</p>

<h3 align="center">Find the one thing in your code that breaks the pattern.</h3>

<p align="center">
  An open-source scanner that learns your project's own conventions, flags the exceptions,<br>
  and shows the git history you need to judge them.
</p>

<p align="center">
  <a href="https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml"><img src="https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%20to%203.14-blue" alt="Python 3.10 to 3.14">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/status-early%20development-orange" alt="Early development">
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/contributions-welcome-brightgreen" alt="Contributions welcome"></a>
</p>

<p align="center">
  <a href="#quick-start"><b>Quick start</b></a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#what-it-checks">What it checks</a> ·
  <a href="#honest-by-design">Proof</a> ·
  <a href="#contribute">Contribute</a>
</p>

---

## The problem

> **47 of your 48 API routes check who is calling. The 48th doesn't, and it exports every user's data.
> Nobody noticed.**

Every codebase runs on unwritten rules: every route checks auth, every CI job has a timeout,
every action is pinned to a commit. Nobody writes them down, so nobody checks them. Code review
catches what the reviewer remembers. AI coding agents write code that looks right and passes
tests, but quietly forgets the check every other route has.

**Deviant finds that route.** It counts what your code already does, picks out the rare item that
breaks the pattern, and shows the git history behind it. You write no rules.

<p align="center">
  <img src="docs/assets/demo.svg" alt="Terminal output of a Deviant scan. Callout 1: 47 of 48 routes check auth. Callout 2: the one that doesn't, app/routes/items.py line 244. Callout 3: who changed it, when and why. The same author wrote all 47 routes that do check auth." width="100%">
</p>

<sub>Built for teams that ship with AI coding agents, maintainers who review many pull requests,
and anyone who has found an unprotected route in production.</sub>

## Highlights

<table>
  <tr>
    <td width="33%" valign="top"><h4>🎯 Finds the odd one out</h4>It learns your project's own conventions by counting, so there are no rules to write.</td>
    <td width="33%" valign="top"><h4>🧮 Same code, same answer</h4>Finding the exceptions needs no AI, no API key, no network and no token bill.</td>
    <td width="33%" valign="top"><h4>🔎 Evidence, not guesses</h4>Every finding comes with git history: who changed it, when, why, and how many of the protected items that person wrote.</td>
  </tr>
  <tr>
    <td valign="top"><h4>🛡️ Safe on code you don't trust</h4>It reads and parses files and never runs them. Git evidence uses read-only commands.</td>
    <td valign="top"><h4>🧩 A check is one Python file</h4>Adding support for your framework means writing one file, and a template shows how.</td>
    <td valign="top"><h4>🧪 Tested on real projects</h4>Seven open-source projects, with the false alarms we found <a href="docs/tested-on-real-projects.md">written down</a>.</td>
  </tr>
</table>

## Quick start

Deviant is early, so install from source. You need Python 3.10 or newer and git.

```bash
git clone https://github.com/ImalkaPerera/deviant.git
cd deviant
pip install -e ".[yaml]"

python skills/deviant/scripts/mine.py --repo /path/to/your/project --with-git
```

Add `--json` for machine-readable output. A PyPI release (`uvx deviant-scan .`) is planned.

## How it works

<p align="center">
  <img src="docs/assets/how-it-works.svg" alt="Four steps: group similar things, count the pattern and the exceptions, show git evidence for each exception, and soon let Claude judge each one" width="100%">
</p>

A pattern is only reported when the evidence is strong: a group of at least 20 similar items
with one to three exceptions. Small projects will often show nothing, on purpose. The math is in
[how it works](docs/how-it-works.md) and the trade-offs are in [limits](docs/limits.md).

## What it checks

| Check | Compares | Finds |
|---|---|---|
| **FastAPI routes** | each route with the others in its folder | a route missing the auth, rate limit or response model its neighbours have |
| **GitHub Actions** | every workflow and composite action | an action not pinned to a commit, a job with no timeout, a workflow with no permissions block |

FastAPI auth is followed through routers, shared dependencies and `include_router`, so routes
that are protected from above are not reported. See [detectors](docs/detectors.md).

## How is this different?

| | Linters and Semgrep | Asking an AI to review the code | **Deviant** |
|---|---|---|---|
| Needs rules written first | Yes, or uses rules someone else wrote | No | **No**, it learns from your code |
| Notices "47 do this, one doesn't" | Only if a rule describes it | Can miss it when it only shows up across hundreds of files | **Yes**, it counts |
| Same answer every run | Yes | Not guaranteed | **Yes** |
| Cost per scan | Free | Tokens | **Free**, and local |
| Why it flagged something | A rule message | An explanation in prose | **Numbers and git history** |

Deviant does not replace your linter or your reviewers. It finds what only counting can see.

## Honest by design

Most tools show you their wins. We publish our misses too.

- **Seven real projects scanned,** and the results read by hand.
- **One candidate at the default settings.** It turned out to be intentional: the project's own
  test asserts that the route is public.
- **Six problems found and fixed** while reading real results and reviewing the code, each with a
  regression test. The early version flagged all 23 routes of the FastAPI template as unprotected.
- **No confirmed bug in someone else's project yet,** and no accuracy number yet. A published
  benchmark is on the roadmap.

The full story is in [tested on real projects](docs/tested-on-real-projects.md).

## Roadmap

- [x] Count patterns and report the rare exceptions
- [x] FastAPI and GitHub Actions checks, with git evidence
- [ ] A Claude Code skill that judges each finding: bug, intentional or unsure
- [ ] Saved rules, and a hook that warns an AI agent the moment it breaks one
- [ ] More checks: Dockerfiles, Flask, Express, Spring, Kubernetes, Terraform
- [ ] A published benchmark against asking Claude alone
- [ ] A PyPI release

## Contribute

Deviant is early, and early contributors shape what it becomes. **A check is one Python file.**
If you know a framework well enough to say "every X should have a Y", you can add it.

<table>
  <tr>
    <td width="33%" valign="top"><h4>🧩 Add a check</h4>Copy the <a href="skills/deviant/scripts/detectors/_template.py">short template</a>. The <a href="CONTRIBUTING.md">guide</a> has a complete example and <a href="CONTRIBUTING.md#where-to-help">starter ideas</a>.</td>
    <td width="33%" valign="top"><h4>🐞 Report a false alarm</h4>Deviant flagged something that is fine? These reports improve it fastest. <a href="https://github.com/ImalkaPerera/deviant/issues/new/choose">Open one</a>.</td>
    <td width="33%" valign="top"><h4>🧪 Try it on your project</h4>Run it and tell us what it found or missed. Add it to <a href="docs/tested-on-real-projects.md">tested on real projects</a>.</td>
  </tr>
</table>

No API key is needed to run any test.

## Learn more

[How it works](docs/how-it-works.md) · [Reading the output](docs/reading-the-output.md) ·
[Detectors](docs/detectors.md) · [Configuration](docs/configuration.md) ·
[Limits](docs/limits.md) · [Security](SECURITY.md)

The idea comes from Engler et al., [*Bugs as Deviant Behavior*](https://www.cs.columbia.edu/~junfeng/09fa-e6998/papers/deviant.pdf)
(SOSP 2001), which showed that rare exceptions to a common pattern often point to real bugs.
Related work: [Laravel `infer-conventions`](https://laravel.com/blog/extracting-ai-rules-from-an-existing-codebase),
[codebase-dna-guardian](https://github.com/mturac/codebase-dna-guardian),
[Trail of Bits `semgrep-rule-creator`](https://lobehub.com/skills/trailofbits-skills-semgrep-rule-creator).

<p align="center">
  <sub>If Deviant would have caught a bug for you, a ⭐ helps others find it. · <a href="LICENSE">MIT license</a></sub>
</p>
