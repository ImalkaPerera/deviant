# deviant-scan

**Find the one thing in your code that breaks the pattern.**

Deviant learns your project's own conventions, flags the exceptions, and shows the git history
you need to judge them. You write no rules, and finding the exceptions needs no AI, no API key
and no network.

![A Deviant scan: 47 of 48 routes check auth, and the one that does not is shown with who last changed it and why](https://raw.githubusercontent.com/ImalkaPerera/deviant/main/docs/assets/demo.png)

Picture a project with 48 API routes. 47 of them check who is calling. The 48th doesn't, and it
exports every user's data. Nobody noticed. Deviant counts what your code already does, picks out
the rare item that breaks the pattern, and shows the git history behind it.

## Use it

```bash
pip install deviant-scan
deviant-scan path/to/your/project --with-git
```

Or without installing it: `uvx deviant-scan path/to/your/project --with-git`.

It checks FastAPI routes and GitHub Actions workflows today. Add `--json` for machine-readable
output. Everything runs on your machine. It reads your files and never runs your code.

## In Claude Code

A plugin judges each exception as a bug, intentional or unsure, with proof, then reviews the
code around it. On 84 bugs planted in 16 sealed repos, Claude with the plugin found 82% against
70% for Claude alone, at about two thirds of the cost
([benchmark](https://github.com/ImalkaPerera/deviant/blob/main/bench/results/fresh-set-2-benchmark.md)):

```text
/plugin install deviant --marketplace ImalkaPerera/deviant
```

## Learn more

- [Source and README](https://github.com/ImalkaPerera/deviant)
- [How it works](https://github.com/ImalkaPerera/deviant/blob/main/docs/how-it-works.md)
- [What it found and got wrong on real projects](https://github.com/ImalkaPerera/deviant/blob/main/docs/tested-on-real-projects.md)
- [Contribute](https://github.com/ImalkaPerera/deviant/blob/main/CONTRIBUTING.md)

Licensed under either the MIT license or the Apache License 2.0, at your option.
