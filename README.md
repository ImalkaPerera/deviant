# Deviant

**Find the one route that forgot its auth check.**

[![CI](https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml/badge.svg)](https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-early%20development-orange)

Deviant finds likely bugs by spotting code that breaks your own project's patterns.
If 47 of your 48 API routes check the user's permission, the 48th is worth a look.
Deviant finds it, shows you the numbers, and points to the file and line.

> [!NOTE]
> Deviant is in early development. The scanner and two detectors work today.
> The Claude Code skill, git evidence, saved rules and edit hooks are planned.
> See [Roadmap](#roadmap). There is no PyPI release yet.

---

## Contents

- [Why](#why)
- [How it works](#how-it-works)
- [Quick start](#quick-start)
- [Example](#example)
- [Detectors](#detectors)
- [Why small projects show nothing](#why-small-projects-show-nothing)
- [Configuration](#configuration)
- [Limits](#limits)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [Credits and related work](#credits-and-related-work)
- [License](#license)

---

## Why

Every project has unwritten rules: every route that changes data checks auth, every
CI job has a timeout, every third-party action is pinned to a commit. Nobody writes these
rules down, so nobody checks them. Code written by people in a hurry, or by AI agents,
can look right and still break them.

Deviant does not ask you to write the rules. It counts what your code already does and
reports the rare items that do something different.

The idea comes from Engler et al., *Bugs as Deviant Behavior* (2001), which showed that
rare exceptions to a common pattern often point to real bugs.

## How it works

| Step | What happens | Status |
|---|---|---|
| 1. Group | Detectors list similar items, such as all FastAPI routes or all CI jobs. | ✅ Built |
| 2. Count | Plain math finds patterns like "47 of 48 do X". Same input, same output. No AI. | ✅ Built |
| 3. Judge | Claude checks each exception against git history, comments and tests, and labels it BUG, INTENTIONAL or UNSURE with proof. | 🚧 Planned |
| 4. Approve | You choose which rules to keep. | 🚧 Planned |
| 5. Enforce | Approved rules become permanent checks. | 🚧 Planned |
| 6. Guard | A Claude Code hook checks each AI edit and warns when a rule is broken. | 🚧 Planned |

A pattern is only reported when the evidence is strong. All of these must hold:

- the group has at least **20** items (`--min-items`),
- there are **1 to 3** exceptions,
- the [Wilson score](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval)
  lower bound of the share that follows the pattern is at least **0.80** (`--min-confidence`).

The Wilson bound asks: "How sure can we be that this really is the norm, given how
few items we have?" 47 of 48 gives 0.891 and is reported. 19 of 20 gives 0.764 and is not.

## Quick start

Requirements: Python 3.10 or newer. PyYAML is needed for the GitHub Actions detector.

```bash
git clone https://github.com/ImalkaPerera/deviant.git
cd deviant
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[yaml]"
```

Scan a project:

```bash
python skills/deviant/scripts/mine.py --repo /path/to/your/project
```

| Flag | Default | Meaning |
|---|---|---|
| `--repo` | `.` | Folder to scan |
| `--min-items` | `20` | Smallest group that can produce a rule |
| `--min-confidence` | `0.80` | Smallest Wilson lower bound that is reported |
| `--json` | off | Print JSON for tools and for the judge step |

The scan is fully local. It reads files and never runs your code or sends it anywhere.

## Example

A FastAPI project with 48 routes that change data. 47 use `Depends(get_current_user)`,
one does not:

```text
$ python skills/deviant/scripts/mine.py --repo .
python_routes.fastapi_routes.has_auth  n=48 s=47 v=1 wlb95=0.891
  In fastapi_routes, has_auth is true
  exception: app/routes/items.py:163 (POST /api/v1/users/export)
```

`n` is the number of similar items, `s` how many follow the pattern, `v` how many do not,
and `wlb95` the Wilson lower bound. With `--json`, each rule also lists the exceptions
and a few compliant examples to compare against (trimmed):

```json
{
  "rule_id": "python_routes.fastapi_routes.has_auth",
  "kind": "plain",
  "feature": "has_auth",
  "n": 48, "s": 47, "v": 1, "wlb95": 0.891,
  "exceptions": [
    {"item_id": "POST /api/v1/users/export", "file": "app/routes/items.py", "line": 163}
  ],
  "compliant_examples": [{"file": "app/routes/items.py", "line": 8}]
}
```

An exception is a lead, not a verdict. A login or health-check route is supposed to be
public. Deciding which exceptions are real bugs is the job of the planned judge step,
or yours today.

## Detectors

### FastAPI routes (`python_routes`)

Reads Python with the standard `ast` module.

Routes are compared with the other routes in the same folder. A whole project often mixes
auth styles, so a project-wide rule rarely holds, while one folder usually follows one
convention. Each folder needs enough routes to pass the size floor, so small folders show
nothing.

| Feature | True when |
|---|---|
| `is_mutating` | The route uses POST, PUT, PATCH or DELETE |
| `has_auth` | An auth dependency applies to the route |
| `has_response_model` | The route sets `response_model` |
| `has_rate_limit` | A rate-limit dependency or decorator applies |

Auth often comes from above the route, so the detector follows every level FastAPI uses:

- route parameters: `user = Depends(get_current_user)`, `Security(...)`
- `Annotated` aliases, including ones imported from other files:
  `CurrentUser = Annotated[User, Depends(get_current_user)]`
- the route decorator: `@router.post(..., dependencies=[Depends(...)])`
- the router: `APIRouter(dependencies=[...])`
- every `include_router(..., dependencies=[...])` call, through nested routers
- the app: `FastAPI(dependencies=[...])`, including apps built in factory functions

A dependency counts as auth when its name contains words such as `auth`, `token`,
`verify`, `permission`, `admin`, `oauth2`, `jwt`, `bearer` or `current_user`. Whole words
are matched, so `get_authors` is not auth. You can add your own words; see
[Configuration](#configuration).

### GitHub Actions (`github_actions`)

Reads workflows in `.github/workflows/` with `yaml.safe_load`.

| Group | Feature | Why it matters |
|---|---|---|
| Third-party actions and reusable workflows | `pinned_to_sha` | Supply-chain safety |
| Jobs | `has_timeout_minutes` | Stops runaway jobs |
| Jobs | `has_concurrency` | Avoids duplicate runs |
| Workflows | `has_permissions_block` | Least-privilege tokens |

Workflow-level `concurrency` counts for every job. A workflow whose jobs all set their
own `permissions` counts as having a permissions block. Local actions (`./...`) are skipped.

## Why small projects show nothing

The Wilson bound is strict on purpose. The smallest group that can be reported:

| Exceptions | At 0.80 (default) | At 0.75 |
|---|---|---|
| 1 | 25 items | 19 items |
| 2 | 33 items | 25 items |
| 3 | 40 items | 31 items |

A project with 15 routes will not get route findings. That is by design: with so few
items, "14 of 15" is not strong evidence of a rule.

## Configuration

Optional. Create `.deviant/config.json` in the scanned project:

```json
{
  "auth_words": ["tenant_access", "require_org_member"]
}
```

`auth_words` adds names that should count as auth dependencies.

## Limits

- **Needs enough similar items.** See the table above.
- **Finds only what a detector looks for.** Today that is FastAPI routes and GitHub
  Actions workflows.
- **Reads code, does not run it.** Only decorator routes such as `@router.post(...)` are
  seen. Routes added with `add_api_route` or built dynamically are not.
- **Parses with the Python it runs on.** Files using newer syntax, such as Python 3.14's
  unparenthesised `except A, B:`, cannot be read by an older interpreter. Deviant warns
  when it skips a file. Run it with the same or a newer Python than your project.
- **Exceptions are leads, not verdicts.** Some exceptions are intentional.

## Roadmap

- [x] Wilson filter, rule mining and ranking
- [x] FastAPI routes detector
- [x] GitHub Actions detector
- [ ] Git evidence for each exception: who changed it, when, and why (`--with-git`)
- [ ] Claude Code skill that judges each exception as BUG, INTENTIONAL or UNSURE
- [ ] Saved rules in `.deviant/rules.json` with exemptions
- [ ] Claude Code hook that warns when an edit breaks an approved rule
- [ ] Spring Boot controllers detector
- [ ] Public benchmark against Claude alone, with raw results
- [ ] `uvx deviant-scan .` release on PyPI

Results will be published with the benchmark, including runs where Deviant does not help.

## Contributing

Contributions are welcome, especially new detectors. A detector is one Python file
with one function:

```python
def extract(repo_root: str) -> list[dict]: ...
```

Copy [`skills/deviant/scripts/detectors/_template.py`](skills/deviant/scripts/detectors/_template.py),
fill in `extract()`, and add a small fixture repo under `tests/fixtures/<detector>/`.
The template explains the rules: read files only, never run project code, no math,
no git, and features are `True` or `False`.

Run the checks before opening a pull request:

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest
```

No API key is needed for any test.

## Security

If Deviant helps you find a security issue in someone else's project, report it
privately through that project's security policy. Please do not open a public issue
or pull request for it.

## Credits and related work

- Dawson Engler, David Yu Chen, Seth Hallem, Andy Chou and Benjamin Chelf,
  [*Bugs as Deviant Behavior: A General Approach to Inferring Errors in Systems Code*](https://www.cs.columbia.edu/~junfeng/09fa-e6998/papers/deviant.pdf), SOSP 2001.

Nearby tools that work on parts of this problem:

- [Laravel `infer-conventions`](https://laravel.com/blog/extracting-ai-rules-from-an-existing-codebase): mines conventions into written rules
- [codebase-dna-guardian](https://github.com/mturac/codebase-dna-guardian): mines codebase conventions
- [Bug Corpus](https://pypi.org/project/bugcorpus/): turns known bugs into detectors
- [Trail of Bits `semgrep-rule-creator`](https://lobehub.com/skills/trailofbits-skills-semgrep-rule-creator): writes Semgrep rules

We did not find a tool that combines statistical outliers, git triage, compiled checks
and an edit hook in one place. That combination is what Deviant aims to be.

## License

[MIT](LICENSE)
