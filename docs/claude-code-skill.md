# Using Deviant in Claude Code

The scanner finds the exceptions. The Claude Code skill judges them: it reads each exception's
code, its neighbours, the tests and the git history, then labels it **BUG**, **INTENTIONAL** or
**UNSURE** and gives one sentence of proof.

## Install

You need Claude Code, Python 3.10 or newer and git. Install the plugin from this repository:

```text
/plugin install deviant --marketplace ImalkaPerera/deviant
```

Then run it on a project:

```text
/deviant:deviant path/to/project
```

With no path it scans the current folder. You can also just ask in plain words, for example
"audit this repo for routes that are missing the auth check", and Claude will use the skill.

Install `PyYAML` (`pip install PyYAML`) if you want the GitHub Actions check. Without it the
skill tells you the check was skipped.

**Another way to install.** Copy the `skills/deviant` folder into `.claude/skills/` in a
project, or into `~/.claude/skills/` for every project, and run it as `/deviant`. This works,
but the plugin is the tested route. On Windows, Claude Code sometimes asks for approval to run
the scan when the skill is installed this way.

## What it does

1. **Scans** with `mine.py --with-git --json --inventory`, and passes on any warning that
   affects trust: files that could not be parsed, a shallow clone, a missing PyYAML.
2. **Scans again with relaxed limits** if nothing was reported (a group of 8 items and a
   confidence of 0.5, instead of 20 and 0.80), and calls anything it finds a weak lead, which
   it labels BUG only when the code shows the missing check matters.
3. **Reads the inventory.** The inventory lists every peer group and the items that lack
   something most of their peers have, with no size floor or confidence bound. An empty scan
   does not end the run: the skill judges these leads too. It does not hunt for patterns of its
   own, but it does read a lead and the nearest peers the inventory names.
4. **Judges** up to 25 exceptions or leads per run: rules first, then relaxed rules, then
   inventory leads. For each it reads the code, a compliant example, the git evidence, and
   searches the tests.
5. **Reports** a table with BUG rows first, then UNSURE, then INTENTIONAL, and says where each
   came from (rule, relaxed scan or inventory lead) and what was not covered.
6. **Asks** before changing anything. It never edits files unless you ask.

The guidance for weighing the evidence is in
[`skills/deviant/references/judging.md`](../skills/deviant/references/judging.md).

## Safety

- **Text in the project is data, not instructions.** Comments, docstrings, commit messages and
  test names are evidence. If one of them tells Claude to skip a step or change a label, the
  report says so and carries on. A real run on a project with such a comment gave the right
  answer and flagged the attempt.
- **Only the scanner is pre-approved.** The skill allows one exact command, running its own
  `mine.py` (the default form and the relaxed form), plus the read-only Read, Grep and Glob
  tools. Anything else needs your approval as
  usual.
- **Security findings stay private.** If a BUG looks like a vulnerability in a project you do
  not own, the skill tells you to report it to that project privately, not in a public issue.

## Cost

The scan is free and local. The judging uses model tokens, so the cost depends on the model.
On small test projects a run cost about 15 to 30 cents, and a run with a small model on a
single exception cost about a cent. Larger projects with more exceptions cost more.

## How it was checked

The skill's files are checked by automated tests, including that the command it tells Claude to
run works and that the output fields it describes exist. Its behaviour was checked by running it
in real Claude Code sessions on three scenarios: a real bug, an intentional exception backed by a
test, and a prompt-injection attempt. It also stopped cleanly on a project too small to scan.
The scenarios are in [`tests/skill/`](../tests/skill/README.md) so you can repeat them.

## Limits

- It is as good as the model running it, and it can be wrong. Treat a label as a lead, and read
  the proof it gives.
- It judges ten exceptions per run.
- Deviant only checks FastAPI routes and GitHub Actions workflows so far.
