<p align="center">
  <img src="docs/assets/banner.svg" alt="Deviant: catch the one route that forgot its auth check" width="100%">
</p>

<p align="center">
  <a href="https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml"><img src="https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.10%20to%203.14-blue" alt="Python 3.10 to 3.14">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/status-early%20development-orange" alt="Early development">
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/contributions-welcome-brightgreen" alt="Contributions welcome"></a>
</p>

Your API has 48 routes. 47 of them check that the user is allowed in. One doesn't,
and nobody noticed.

**Deviant finds that one.** It reads your code, learns what your project normally does,
and points at the thing that breaks the pattern, with the numbers and the git history
behind it. You write no rules, and finding it needs no AI, no API key and no network.

```text
$ python skills/deviant/scripts/mine.py --repo . --with-git
python_routes.fastapi_routes:app/routes.has_auth  n=48 s=47 v=1 wlb95=0.891
  exception: app/routes/items.py:244 (POST /api/v1/users/export)
    last changed: 52c027b 2026-10-17 by dana@example.com
    commit: add csv export
    same author wrote 47 of the 47 compliant items checked
```

47 of 48 routes check auth. This one doesn't. The same person wrote all 47 that do, so
they knew the convention and this looks like a slip, not a choice. Worth a look.

## Why

AI coding agents write code that looks right and passes tests, but forgets the check
every other route has. Code review catches what the reviewer remembers. Deviant counts.

## How it works

1. **Group.** A check lists similar things: every FastAPI route, every CI job.
2. **Count.** Plain math finds the pattern ("47 of 48 do this") and the rare exceptions.
   Same code, same answer. No AI.
3. **Show the evidence.** Each exception comes with its git history: who changed it, when,
   and how many of the protected items that same person wrote.

Next: a Claude Code skill that judges each exception (bug, intentional or unsure) and a
hook that warns an AI agent the moment it breaks a rule. See the [roadmap](#roadmap).

## Install

Deviant is early, so install from source (Python 3.10 or newer, and git):

```bash
git clone https://github.com/ImalkaPerera/deviant.git
cd deviant
pip install -e ".[yaml]"

python skills/deviant/scripts/mine.py --repo /path/to/your/project --with-git
```

Everything runs on your machine. Deviant reads your files and never runs your code.
A PyPI release (`uvx deviant-scan .`) is planned.

## What it checks today

| Check | Looks at | Finds |
|---|---|---|
| **FastAPI routes** | every route, compared with the others in its folder | a route without auth, a rate limit or a response model that its neighbours have |
| **GitHub Actions** | workflows and composite actions | an action not pinned to a commit, a job with no timeout, a workflow with no permissions block |

FastAPI auth is followed through routers, shared dependencies and `include_router`, so
routes protected from above are not reported. Details: [detectors](docs/detectors.md).

Small projects will often show nothing, on purpose: a rule needs roughly 25 similar items
before one exception is strong evidence. See [limits](docs/limits.md).

## Tested on real projects

We ran it on seven open-source projects, read the results by hand, and fixed the false
alarms we found. We have not yet found a confirmed bug in someone else's project, and we
say so. The full story, including what the early versions got wrong, is in
[tested on real projects](docs/tested-on-real-projects.md).

## Roadmap

- [x] Count patterns and report the rare exceptions
- [x] FastAPI and GitHub Actions checks
- [x] Git evidence for each exception
- [ ] Claude Code skill that judges each exception
- [ ] Saved rules, and a hook that warns when an AI edit breaks one
- [ ] More checks: Dockerfiles, Flask, Express, Spring, Kubernetes, Terraform
- [ ] Published benchmark against asking Claude alone
- [ ] PyPI release

## Contribute

Deviant gets better with every check, and **a check is one Python file.** If you know a
framework well enough to say "every X should have a Y", you can add it in an afternoon.

- **Add a check.** Copy a [short template](skills/deviant/scripts/detectors/_template.py)
  and follow the [contributor guide](CONTRIBUTING.md). There are
  [starter ideas](CONTRIBUTING.md#where-to-help) with hints.
- **Report a false alarm.** If Deviant flags something that is fine, tell us. Those reports
  improve it faster than anything else.
- **Try it on your project** and share what it found or missed.

No API key is needed to run any test.

## Learn more

[How it works](docs/how-it-works.md) · [Reading the output](docs/reading-the-output.md) ·
[Detectors](docs/detectors.md) · [Configuration](docs/configuration.md) ·
[Limits](docs/limits.md) · [Security](SECURITY.md)

The idea comes from Engler et al., [*Bugs as Deviant Behavior*](https://www.cs.columbia.edu/~junfeng/09fa-e6998/papers/deviant.pdf)
(SOSP 2001), which showed that rare exceptions to a common pattern often point to real bugs.
Related tools: [Laravel `infer-conventions`](https://laravel.com/blog/extracting-ai-rules-from-an-existing-codebase),
[codebase-dna-guardian](https://github.com/mturac/codebase-dna-guardian),
[Trail of Bits `semgrep-rule-creator`](https://lobehub.com/skills/trailofbits-skills-semgrep-rule-creator).
We did not find a tool that combines statistical outliers, git evidence, saved checks and
an edit hook in one place.

[MIT license](LICENSE)
