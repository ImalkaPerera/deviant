# Reading the output

What a finding looks like, and what each number means.

A FastAPI project with 48 routes that change data. 47 use `Depends(get_current_user)`,
one does not. Dana wrote all of them, including the last one:

```text
$ deviant-scan . --with-git
python_routes.fastapi_routes:app/routes.has_auth  n=48 s=47 v=1 wlb95=0.891
  In fastapi_routes:app/routes, has_auth is true
  exception: app/routes/items.py:244 (POST /api/v1/users/export)
    last changed: 52c027b 2026-10-17 by dana@example.com
    commit: add csv export
    same author wrote 47 of the 47 compliant items checked
```

`n` is the number of similar items, `s` how many follow the pattern, `v` how many do not,
and `wlb95` the Wilson lower bound. Routes are compared within their folder, so the rule
name includes it. The git lines are evidence, not a verdict. Dana wrote all 47 protected routes
and then added this one without the check, and nothing in the commit message says it is meant
to be public. If instead the author had written none of the protected routes, the count would
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
public. Deciding which exceptions are real bugs is the job of the
[Claude Code skill](claude-code-skill.md), or yours.
