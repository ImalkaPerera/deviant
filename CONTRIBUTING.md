# Contributing to Deviant

Thanks for wanting to help. Deviant is early, so a good contribution can shape where it goes.

The fastest way to help is one of these:

1. **Report a false alarm.** Deviant flagged something that is fine. Open an
   [issue](https://github.com/ImalkaPerera/deviant/issues/new/choose) with the output and why
   it is fine. These reports make Deviant better faster than anything else.
2. **Add a check.** A check ("detector") is one Python file.
3. **Try it on your own project** and tell us what it found or missed.

## Set up

You need Python 3.10 or newer and git. No API key is needed for anything.

```bash
git clone https://github.com/ImalkaPerera/deviant.git
cd deviant
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

pytest                           # run the tests
ruff check . && ruff format --check .
```

## Add a detector in one file

A detector turns one kind of thing in a project into **items** with yes/no **features**.
Deviant does the counting. You only collect facts. The full contract is in
[DETECTOR-SPEC.md](skills/deviant/references/DETECTOR-SPEC.md).

Here is a complete one. It checks whether each Dockerfile ends up running as a non-root user.
Save it as `skills/deviant/scripts/deviant_scan/detectors/dockerfiles.py` and it is picked up
automatically.

```python
"""Example detector: does each Dockerfile switch to a non-root user?"""

import os
import re
from pathlib import Path

DETECTOR = "dockerfiles"
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "site-packages"}
MAX_BYTES = 1_000_000
USER_LINE = re.compile(r"^\s*USER\s+(\S+)", re.IGNORECASE | re.MULTILINE)


def extract(repo_root: str) -> list[dict]:
    root = Path(repo_root).resolve()
    items = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            path = Path(dirpath) / name
            if name != "Dockerfile" or path.is_symlink():
                continue
            try:
                if path.stat().st_size > MAX_BYTES:
                    continue
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue  # skip what we cannot read
            users = USER_LINE.findall(text)
            relative = path.relative_to(root).as_posix()
            items.append(
                {
                    "detector": DETECTOR,
                    "peer_group": "dockerfiles",
                    "item_id": relative,
                    "file": relative,
                    "line": 1,
                    "features": {
                        "runs_as_non_root": bool(users) and users[-1] not in ("root", "0"),
                    },
                }
            )
    return items
```

If 24 of 25 Dockerfiles in a project switch to a non-root user, Deviant reports the 25th.

Then:

1. **Add a fixture.** A tiny fake project in `tests/fixtures/<detector>/`.
2. **Test it.** Check the features of each item, and unusual input: an empty folder, a file
   with an odd encoding, a file that is too big. See `tests/detectors/` for examples.
3. **Open a pull request.** One detector per pull request.

The rules for detectors, in short: read only inside the project, never run its code, never
crash on a bad file, do no counting and no git work. The spec has the details.

## Where to help

Each of these is a self-contained place to start. If you want one, say so in an issue first
so nobody duplicates it.

**New checks (detectors)**

| Idea | What it would check | Difficulty |
|---|---|---|
| Dockerfiles | A non-root `USER`, a pinned base image, a `HEALTHCHECK`. Start from the example above | Easy |
| Kubernetes manifests | Resource limits, probes, `runAsNonRoot`, pinned image tags | Medium |
| Flask routes | Auth decorators, in the same way the FastAPI check works | Medium |
| Express and NestJS | Route guards and validation middleware | Medium |
| Spring Boot controllers | `@PreAuthorize`, `@Secured`, `@Valid` | Medium |
| Terraform | Required tags, encryption settings | Medium |
| SQL migrations | A reversible `down` step, `CREATE INDEX CONCURRENTLY` | Medium |

**Tool features**

| Idea | Why |
|---|---|
| SARIF output (`--format sarif`) | Show findings in GitHub code scanning |
| An ignore file for known intentional exceptions | So accepted findings stay quiet |
| A non-zero exit code when there are findings | So it can fail a CI job |
| A GitHub Action and a pre-commit hook | Run it where people already work |
| A JSON schema for the output | Stable output for other tools |

**Testing and docs**

- Run Deviant on a project you know and add what it found, or got wrong, to
  [tested on real projects](docs/tested-on-real-projects.md).
- Improve the explanations in `docs/` where something was unclear to you.

## Pull requests

- Keep each one focused.
- Add or update tests. `pytest` and `ruff check . && ruff format --check .` must pass.
- Use [conventional commits](https://www.conventionalcommits.org/) for messages:
  `feat: add Dockerfile detector`, `fix: handle empty workflow files`, `docs: ...`.
- If your change affects what Deviant reports, say what it did on a real project before
  and after.

## Security

If Deviant helps you find a vulnerability in someone else's project, report it privately to
that project, not in a public issue or pull request. To report a problem in Deviant itself,
see [SECURITY.md](SECURITY.md).
