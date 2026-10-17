# Deviant

**Catch the one route that forgot its auth check.**

[![CI](https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml/badge.svg)](https://github.com/ImalkaPerera/deviant/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13%20%7C%203.14-blue)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
![Status](https://img.shields.io/badge/status-early%20development-orange)

Your API has 48 routes. 47 of them check that the user is allowed in. One doesn't,
and nobody noticed.

Deviant finds that one. It reads your code, learns what your project normally does,
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

In plain words: 47 of 48 routes check auth. This one, added in the commit "add csv export",
doesn't. The same person, Dana, wrote all 47 routes that do check auth, so Dana knew the
convention and this looks like a slip, not a choice. It is worth a look.

## Why you might want this

- **AI coding agents break unwritten rules.** They write code that looks right and
  passes tests, but forgets the check every other route has.
- **Code review catches what the reviewer remembers.** Deviant counts instead.
- **It gives the same answer every time.** It runs on your machine, reads your files and
  never runs your code.

## What it checks today

- **FastAPI routes:** auth, rate limits, response models. It follows auth through routers,
  shared dependencies and `include_router`, so it does not cry wolf on routes that are
  protected from above.
- **GitHub Actions:** actions pinned to a commit (in workflows and composite actions),
  job timeouts, token permissions and duplicate-run protection.

More checks are one Python file each, so adding one is a good first contribution.
See [Contributing](#contributing).

> [!NOTE]
> Early development. The scanner, both checks and git evidence work today. Coming next:
> a Claude Code skill that judges each finding, saved rules, and a hook that warns an AI
> agent the moment it breaks a rule. Not on PyPI yet, so install from source
> ([Quick start](#quick-start)).

[How it works](#how-it-works) · [Quick start](#quick-start) · [Example](#example) ·
[Detectors](#detectors) · [Limits](#limits) · [Roadmap](#roadmap) ·
[Contributing](#contributing)

The idea comes from Engler et al., *Bugs as Deviant Behavior* (2001), which showed that
rare exceptions to a common pattern often point to real bugs.

## How it works

| Step | What happens | Status |
|---|---|---|
| 1. Group | Detectors list similar items, such as all FastAPI routes or all CI jobs. | ✅ Built |
| 2. Count | Plain math finds patterns like "47 of 48 do X". Same input, same output. No AI. | ✅ Built |
| 3. Evidence | Each exception gets its git history: who last changed the line, when, why, and whether that author follows the rule elsewhere. | ✅ Built (`--with-git`) |
| 4. Judge | Claude reads the evidence, comments and tests, and labels each exception BUG, INTENTIONAL or UNSURE with proof. | 🚧 Planned |
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
| `--with-git` | off | Add the git history of each exception (needs a git repository) |

The scan is fully local. It reads files and never runs your code or sends it anywhere.
Git evidence runs read-only git commands, with `core.fsmonitor` switched off so a crafted
`.git/config` in a downloaded folder cannot make git run a program.

## Example

A FastAPI project with 48 routes that change data. 47 use `Depends(get_current_user)`,
one does not. Dana wrote the 47. Sam added the last route:

```text
$ python skills/deviant/scripts/mine.py --repo . --with-git
python_routes.fastapi_routes:app/routes.has_auth  n=48 s=47 v=1 wlb95=0.891
  In fastapi_routes:app/routes, has_auth is true
  exception: app/routes/items.py:244 (POST /api/v1/users/export)
    last changed: 52c027b 2026-10-17 by dana@example.com
    commit: add csv export
    same author wrote 47 of the 47 compliant items checked
```

`n` is the number of similar items, `s` how many follow the pattern, `v` how many do not,
and `wlb95` the Wilson lower bound. Routes are compared within their folder, so the rule
name includes it. The git lines are evidence, not a verdict. Dana wrote all 47 protected routes and then
added this one without the check, and nothing in the commit message says it is meant to
be public. If instead the author had written none of the protected routes, the count would
be 0 and would say nothing about whether they knew the convention.

With `--json`, each exception carries the same evidence for tools and the judge step:

```json
{
  "rule_id": "python_routes.fastapi_routes:app/routes.has_auth",
  "n": 48, "s": 47, "v": 1, "wlb95": 0.891,
  "exceptions": [{
    "item_id": "POST /api/v1/users/export",
    "file": "app/routes/items.py",
    "line": 244,
    "git": {
      "commit": "52c027b", "author": "dana@example.com", "date": "2026-10-17",
      "subject": "add csv export", "files_in_commit": 1,
      "author_followed_rule_elsewhere": 47, "compliant_checked": 47,
      "intent_words": [], "history_truncated": false, "uncommitted": false
    }
  }]
}
```

`intent_words` lists hints such as `public`, `health`, `webhook`, `login`, `metrics`,
`noqa`, `intentional` and `todo` found in the commit message or the comments just above
the line. `compliant_checked` is a sample of at most 50 compliant items, to keep scans fast, and
`author_followed_rule_elsewhere` is how many of those the same author wrote.

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
| `is_mutating` | The route uses POST, PUT, PATCH or DELETE. A route whose methods are given by a variable is reported as `ANY` and is not counted as mutating |
| `has_auth` | An auth dependency applies to the route |
| `has_response_model` | The route sets `response_model` |
| `has_rate_limit` | A rate-limit dependency or decorator applies |

Auth often comes from above the route, so the detector follows every level FastAPI uses:

- route parameters: `user = Depends(get_current_user)`, `Security(...)`, also written
  `Depends(dependency=...)` or imported under another name (`Depends as D`)
- `Annotated` aliases, including ones imported from other files, re-exported through a
  package, written as a string, or declared with a Python 3.12 `type` statement:
  `CurrentUser = Annotated[User, Depends(get_current_user)]`
- dependency lists and single dependencies kept in variables: `AUTH = [Depends(...)]`
- the route decorator: `@router.post(..., dependencies=[Depends(...)])`, and routes added
  with `@router.api_route(...)` or `router.add_api_route(...)`
- the router: `APIRouter(dependencies=[...])`, including subclasses of `APIRouter`
- every `include_router(..., dependencies=[...])` call, through nested routers
- the app: `FastAPI(dependencies=[...])`

Routers can be created inside functions: each function has its own scope, so two factory
functions that both name their router `router` do not mix. A router included in more than
one place gets the dependencies of all of them, so a gap in only one inclusion is not
reported.

A dependency counts as auth when its name contains words such as `auth`, `token`,
`verify`, `permission`, `admin`, `oauth2`, `jwt`, `bearer` or `current_user`. Whole words
are matched, so `get_authors` is not auth. You can add your own words; see
[Configuration](#configuration).

### GitHub Actions (`github_actions`)

Reads workflows in `.github/workflows/` and composite actions (`action.yml` files under
`.github/actions/` and at the repository root) with `yaml.safe_load`.

| Group | Feature | Why it matters |
|---|---|---|
| Third-party actions and reusable workflows | `pinned_to_sha` (a commit SHA or a Docker `sha256:` digest) | Supply-chain safety |
| Jobs | `has_timeout_minutes` | Stops runaway jobs |
| Jobs | `has_concurrency` | Avoids duplicate runs |
| Workflows | `has_permissions_block` | Least-privilege tokens |

Workflow-level `concurrency` counts for every job. A workflow whose jobs all set their
own `permissions` counts as having a permissions block. Local actions and workflows
(`./...`) are skipped, and so are references built from expressions
(`actions/checkout@${{ inputs.ref }}`), which are only known when the workflow runs.

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
- **Reads code, does not run it.** Routes are found from decorators and `add_api_route`
  calls. A router passed in as a function parameter, routes registered in a loop, and
  `include_router(get_router())` where the router comes from a call are not followed.
- **Parses with the Python it runs on.** Python 3.14's unparenthesised `except A, B:` is
  read on older versions too, but other new syntax cannot be. A file that cannot be parsed
  is reported on stderr, because it may hide auth helpers that other files import. Run
  Deviant with the same or a newer Python than your project.
- **Git evidence needs real history.** In a shallow clone git blames old lines on the oldest
  commit it fetched, so the author is wrong. Deviant marks that evidence as truncated.
  Use a full clone.
- **Exceptions are leads, not verdicts.** Some exceptions are intentional.

## Roadmap

- [x] Wilson filter, rule mining and ranking
- [x] FastAPI routes detector
- [x] GitHub Actions detector
- [x] Git evidence for each exception: who changed it, when, and why (`--with-git`)
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
