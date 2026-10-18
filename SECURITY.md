# Security

## Reporting a problem in Deviant

Please report security problems **privately**, not in a public issue.

Use GitHub's private reporting: open the repository's **Security** tab and choose
**Report a vulnerability**. Include what you did, what happened, and what you expected.

Things we especially want to hear about, because Deviant is meant to be safe to run on code
you do not trust:

- any way a scanned project can make Deviant run code, run a command, or read or write a
  file outside the project;
- any way a crafted file can make a scan hang or use unbounded memory;
- any way the output can be made to mislead a person or an AI agent reading it.

## How Deviant protects you when scanning untrusted code

- Detectors read files and parse them. They never import or run the project's code.
- YAML is read with `safe_load`. Files over 1 MB and symbolic links are skipped.
- Git evidence runs read-only git commands. A crafted `.git/config` can make git run a program
  of the attacker's choosing, so `core.fsmonitor` is switched off and `git blame` runs with
  `--no-textconv`. Variables such as `GIT_DIR` that point git at another repository are
  ignored. Versions before 0.1.1 did not disable textconv, so use 0.1.1 or newer when
  scanning code you do not trust with `--with-git`.
- Files that cannot be parsed are skipped, and the scan carries on.

## If Deviant helps you find a vulnerability in someone else's project

Do not open a public issue or pull request for it. Follow that project's security policy and
report it privately. Give the maintainers time to fix it before you say anything in public.
