# Using Deviant in CI

Deviant can fail a pull request when it finds a pattern that something breaks. It needs no API
key and no network once it is installed, and it runs in seconds on most projects.

## The exit status

```bash
deviant-scan --fail-on-findings .
```

| Status | Meaning |
|---|---|
| 0 | The scan ran and reported no finding, or you did not pass `--fail-on-findings` |
| 1 | `--fail-on-findings` was given and the scan reported at least one finding |
| 2 | A usage error, such as a folder that does not exist or `--min-items 0` |

A **finding** is an exception to a rule that passed the size floor and the confidence bound.
Leads from `--inventory` do not count: they are places to read, not findings, so they never
fail a build. Without the flag the status is always 0, so adding Deviant to a job cannot break
it by surprise.

Small projects often report nothing, on purpose. A project needs about 25 similar items for
one exception to be strong evidence. A job that passes does not mean the project is free of
bugs, only that no strong pattern was broken.

## A GitHub Actions job

This workflow uses actions pinned to a full commit, as Deviant itself recommends.

```yaml
name: Deviant
on: pull_request

permissions:
  contents: read

jobs:
  deviant:
    timeout-minutes: 10
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
          fetch-depth: 0 # git history for --with-git; leave it out to scan faster
      - uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: "3.12"
      - run: python -m pip install deviant-scan==0.3.1
      - run: deviant-scan --with-git --fail-on-findings .
```

Check the pinned commits against the current releases before you copy them.

## Tips

- **Pin the version** (`pip install deviant-scan==0.3.1`) so a new release does not change what
  fails your build.
- **A false alarm** can be an auth dependency with an unusual name. Name it once in
  [`.deviant/config.json`](configuration.md) and it counts from then on.
- **A pull request from a fork** runs your workflow on code you did not write. Deviant reads
  that code without running it, and stops the repository's own git filters and similar
  settings from starting programs, but keep the job's permissions at `contents: read` as above.
- **Read the report,** not just the status. The text output shows each exception with the git
  author and message that last changed it, which is usually enough to judge it.
