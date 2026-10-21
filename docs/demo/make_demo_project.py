"""Build a small FastAPI project with real git history, for recording a Deviant demo.

Usage: python docs/demo/make_demo_project.py <empty folder>

The project has 48 routes in three files. Ann writes 47 of them, each with an auth dependency.
Dana then adds a CSV export route without one, in a commit named "add csv export". That is the
scene in docs/assets/demo.png. Two more bugs are planted for the Claude Code skill to find by
reading the code: an inverted `if` in one handler and a workflow step that ignores its failure.

Nothing here is imported or run by Deviant itself. The folder it writes is a scratch project.
"""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

ANN = ("Ann Lee", "ann@example.com")
DANA = ("Dana Fox", "dana@example.com")

HEADER = """\
from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.db import get_db

router = APIRouter()
"""

ROUTE = """

@router.{method}("/{path}")
def {name}(user=Depends(get_current_user), db=Depends(get_db)):
    return db.{action}("{table}", user=user)
"""

# A handler whose `if` is the wrong way round: it reports a missing item when the item exists.
INVERTED = """

@router.get("/items/{item_id}/owner")
def item_owner(item_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    item = db.get("items", item_id, user=user)
    if item:
        raise HTTPException(status_code=404, detail="item not found")
    return item.owner
"""

# The route Dana adds later: it reads every user's data and has no auth dependency.
EXPORT = '''

@router.get("/users/export")
def export_users_csv(db=Depends(get_db)):
    """Download every user as CSV for the monthly report."""
    return db.export_csv("users")
'''

WORKFLOW = """\
name: ci
on: [push, pull_request]
permissions:
  contents: read
jobs:
"""

JOB = """\
  {name}:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    steps:
      - uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955 # v4.3.0
      - run: {command}
"""


def git(root: Path, *args: str, author=ANN) -> None:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": author[0],
        "GIT_AUTHOR_EMAIL": author[1],
        "GIT_COMMITTER_NAME": author[0],
        "GIT_COMMITTER_EMAIL": author[1],
    }
    subprocess.run(["git", "-C", str(root), *args], check=True, env=env, capture_output=True)


def routes_file(prefix: str, count: int) -> str:
    text = HEADER
    for i in range(count):
        method = ("get", "post", "put", "delete")[i % 4]
        action = {"get": "read", "post": "create", "put": "update", "delete": "remove"}[method]
        text += ROUTE.format(
            method=method,
            path=f"{prefix}/{i}",
            name=f"{prefix}_{method}_{i}",
            action=action,
            table=prefix,
        )
    return text


def build(root: Path) -> None:
    app = root / "app" / "routes"
    app.mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (app / "__init__.py").write_text("")
    (root / "app" / "auth.py").write_text(
        textwrap.dedent(
            """\
            import jwt
            from fastapi import Header, HTTPException

            from app.settings import JWT_SECRET


            def get_current_user(authorization: str = Header(...)):
                token = authorization.removeprefix("Bearer ")
                try:
                    claims = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
                except jwt.PyJWTError:
                    raise HTTPException(status_code=401) from None
                if "sub" not in claims:
                    raise HTTPException(status_code=401)
                return claims["sub"]
            """
        )
    )
    settings = 'import os\n\nJWT_SECRET = os.environ["JWT_SECRET"]\n'
    (root / "app" / "settings.py").write_text(settings)
    (root / "app" / "db.py").write_text("def get_db():\n    return None\n")
    (app / "orders.py").write_text(routes_file("orders", 16))
    (app / "billing.py").write_text(routes_file("billing", 16))
    (app / "items.py").write_text(routes_file("items", 14) + INVERTED)

    jobs = [("lint", "make lint"), ("test", "make test"), ("build", "make build")]
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        WORKFLOW + "".join(JOB.format(name=n, command=c) for n, c in jobs)
    )
    (workflows / "release.yml").write_text(
        WORKFLOW.replace("name: ci", "name: release").replace(
            "on: [push, pull_request]", "on:\n  push:\n    tags: ['v*']"
        )
        + JOB.format(name="package", command="make package")
        + JOB.format(name="publish", command="make publish")
        + "        continue-on-error: true\n"
        + JOB.format(name="docs", command="make docs")
    )

    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "add orders, billing and items routes")

    with (app / "items.py").open("a") as f:
        f.write(EXPORT)
    git(root, "add", "-A", author=DANA)
    git(root, "commit", "-q", "-m", "add csv export", author=DANA)


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(argv[1])
    if root.exists() and any(root.iterdir()):
        print(f"error: {root} is not empty", file=sys.stderr)
        return 2
    root.mkdir(parents=True, exist_ok=True)
    build(root)
    print(f"demo project written to {root}")
    print(f"try: deviant-scan {root} --with-git")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
