"""Build constructed cases for judging: a real repo, a route that lost its auth, a known answer.

Usage: python make_cases.py <clone of fastapi-best-architecture> <out dir> [cases]

Each case is a copy of the repo with its own git history: one commit with the original code,
then one commit that removes the auth dependency from a single route. The folder has 58 routes
that all check auth, so the scan reports that one route.

Two kinds of case, drawn from the same pool of read-only routes so a route's name gives
nothing away:
- BUG: the auth is removed and nothing else changes.
- INTENTIONAL: the auth is removed, a comment above the route says it is public on purpose,
  and a new test asserts it answers without a token.

The truth for each case is set here, by construction, not by reading the code.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

FOLDER = "backend/app/admin/api/v1/sys"
SKIP = {".git"}
DECORATOR = re.compile(r"^@router\.get\('([^']*)',.*dependencies=\[DependsJwtAuth\]\)\s*$")
AUTHOR = {
    "GIT_AUTHOR_NAME": "Dev",
    "GIT_AUTHOR_EMAIL": "dev@example.com",
    "GIT_COMMITTER_NAME": "Dev",
    "GIT_COMMITTER_EMAIL": "dev@example.com",
}


def pool(clone):
    """Read-only routes that use a single JWT dependency, except in user.py."""
    found = []
    for path in sorted((clone / FOLDER).glob("*.py")):
        if path.name in {"user.py", "__init__.py"}:
            continue
        lines = path.read_bytes().decode("utf-8").splitlines(keepends=True)
        for index, text in enumerate(lines):
            match = DECORATOR.match(text.rstrip("\r\n"))
            if not match or not match.group(1):
                continue
            name = next(
                m.group(1)
                for later in lines[index + 1 : index + 6]
                if (m := re.match(r"(?:async )?def (\w+)", later))
            )
            found.append(
                {
                    "file": f"{FOLDER}/{path.name}",
                    "index": index,
                    "path": match.group(1),
                    "function": name,
                }
            )
    return found


def spaced(items, count):
    step = len(items) / count
    return [items[int(i * step)] for i in range(count)]


def git(root, *args):
    env = {**os.environ, **AUTHOR}
    subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)


def build(clone, out, case, truth):
    root = out / case["id"]
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(clone, root, ignore=shutil.ignore_patterns(*SKIP))
    git(root, "init", "-q")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "initial commit")
    target = root / case["file"]
    lines = target.read_bytes().decode("utf-8").splitlines(keepends=True)
    original = lines[case["index"]]
    eol = original[len(original.rstrip("\r\n")) :]
    stripped = re.sub(r",\s*dependencies=\[DependsJwtAuth\]\)\s*$", ")", original.rstrip("\r\n"))
    lines[case["index"]] = stripped + eol
    if truth == "INTENTIONAL":
        note = "# Public on purpose: the anonymous landing page reads this, so it needs no login."
        lines.insert(case["index"], note + eol)
        tests = root / "backend" / "tests"
        tests.mkdir(parents=True, exist_ok=True)
        (tests / f"test_public_{case['function']}.py").write_text(
            f"def test_{case['function']}_is_public(client):\n"
            f"    # The landing page calls GET {case['path'] or '/'} without a token.\n"
            f"    assert client.get('{case['path'] or '/'}').status_code == 200\n",
            encoding="utf-8",
        )
    target.write_bytes("".join(lines).encode("utf-8"))
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"update {Path(case['file']).stem} routes")
    return root


def main(argv):
    if len(argv) not in (3, 4):
        print(__doc__)
        return 2
    clone, out = Path(argv[1]), Path(argv[2])
    count = int(argv[3]) if len(argv) == 4 else 12
    out.mkdir(parents=True, exist_ok=True)
    chosen = spaced(pool(clone), count)
    cases = []
    for number, route in enumerate(chosen, start=1):
        truth = "BUG" if number % 2 else "INTENTIONAL"
        case = {**route, "id": f"c{number:02d}"}
        build(clone, out, case, truth)
        cases.append(
            {
                "id": case["id"],
                "dir": str(out / case["id"]),
                "truth": truth,
                "file": case["file"],
                "function": case["function"],
                "route": f"GET {case['path'] or '/'}",
            }
        )
        print(case["id"], truth, case["file"], case["function"], case["path"])
    (out / "cases.json").write_text(json.dumps(cases, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
