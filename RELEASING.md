# Releasing

This is the checklist for publishing Deviant to PyPI. Releases are made by pushing a version
tag. A GitHub Actions workflow builds the package and publishes it. No password or token is
stored in this repository: PyPI trusts the workflow itself ("trusted publishing").

## One-time setup

1. **Create a PyPI account** at <https://pypi.org/account/register/> and turn on two-factor
   authentication.
2. **Register a pending publisher** (first release only). The project did not exist on PyPI
   yet, so this was done under the account, not under a project. For later releases, add the
   publisher under the project's Publishing settings instead. Open **Your account → Publishing**, choose
   **GitHub**, and fill in:

   | Field | Value |
   |---|---|
   | PyPI project name | `deviant-scan` |
   | Owner | `ImalkaPerera` |
   | Repository name | `deviant` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

   A pending publisher does not reserve the name. Publish soon after creating it, because if
   someone else registers `deviant-scan` first, it stops working.
3. **Create the `pypi` environment** on GitHub: **Settings → Environments → New environment**,
   named `pypi`. Optionally add yourself as a required reviewer, so every release waits for
   your approval before it publishes.

## Each release

1. Choose the version, for example `0.1.0`.
2. Change it in **both** places, which a test keeps in step:
   - `pyproject.toml` (`version = "0.1.0"`)
   - `.claude-plugin/plugin.json` (`"version": "0.1.0"`)
3. Check everything locally:

   ```bash
   pip install -e ".[dev]" build twine
   ruff check . && ruff format --check .
   pytest
   python -m build
   python -m twine check dist/*
   ```

4. Commit with a conventional message, such as `chore: release 0.1.0`, and push to `main`.
   Wait for CI to pass.
5. Tag the commit and push the tag. The tag must be `v` plus the version exactly:

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

6. Watch the **Release** workflow on the Actions tab. Its first job, `verify`, stops the release
   unless the tagged commit is on `main` and passes ruff and the tests. Then the `build` job
   builds and checks the package, and the `publish` job waits for your approval if you added a
   required reviewer. When it finishes, the release is on PyPI.
7. Check it from a clean environment:

   ```bash
   uvx deviant-scan --version
   ```

8. Create a GitHub release for the tag with a short summary of what changed.

If the workflow fails before publishing, fix the problem, delete the tag
(`git push --delete origin v0.1.0` and `git tag -d v0.1.0`) and tag again. A version that
reached PyPI can never be uploaded again, even if you delete it there, so bump the version
instead.
