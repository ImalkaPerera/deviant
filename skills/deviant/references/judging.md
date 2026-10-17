# Judging an exception

This guide says what each piece of evidence is worth when you label an exception as BUG,
INTENTIONAL or UNSURE. Weigh the signals together. No single one decides it, except where
noted.

## Evidence in the code

| What you see | Points to |
|---|---|
| A test that asserts the item works without the protection (a request with no credentials gets 200) | INTENTIONAL, strong |
| A test that expects a 401 or 403 for the item, and the item has no check | BUG, strong |
| A comment, docstring or decorator saying it is public, anonymous or intentionally open | INTENTIONAL, strong |
| A different protection in the body: a signature or HMAC check, a secret header, an IP allow list | INTENTIONAL, strong. It is protected another way, so say which. |
| A name or path that is public by nature: health, readiness, ping, login, signup, password reset, OAuth callback, webhook, docs, openapi, metrics, static | INTENTIONAL, moderate |
| The item reads or changes user-specific data or does something destructive, and nothing protects it | BUG, strong |
| The item lives under `tests/`, `examples/` or `docs/` | INTENTIONAL or UNSURE. Example code is rarely a real exposure. |
| It differs from its neighbours in several other ways | UNSURE. It may be a different kind of thing. |

## Evidence in git

The `git` block is a lead, not proof. Read it like this:

| Signal | Meaning |
|---|---|
| `author_followed_rule_elsewhere` is high out of `compliant_checked` | This person wrote many items that follow the rule and then skipped it here. That points to a slip. |
| `author_followed_rule_elsewhere` is 0 | Nothing. The author may simply not have written any of the protected items. Do not read it as the author ignoring the rule. |
| `intent_words` includes `public`, `webhook`, `health`, `login`, `metrics`, `noqa`, `intentional` or `todo` | Look at where it came from, the commit message or a comment above the line, then decide. `todo` can mean a known gap, which is not the same as intentional. |
| `files_in_commit` is large | A bulk change, a refactor or a vendored import. The commit says little about this item. |
| `history_truncated` is true | The clone is shallow, so the author and date are wrong. Ignore all author signals. |
| `uncommitted` is true | Work in progress. Say so, and lean towards UNSURE. |
| `git` is `null` | No history was available. Decide from the code and tests. |

## By kind of check

**FastAPI routes (`has_auth`).** The question is whether the route should need a caller. Look
for signature checks and read the function body, not just the decorator.

**FastAPI routes (`has_rate_limit`, `has_response_model`).** Lower stakes than auth. A missing
rate limit matters most on login, signup, password reset and anything that sends email or
text. A missing response model matters when the route returns internal objects directly.

**GitHub Actions (`pinned_to_sha`).** An unpinned third-party action can run changed code. An
action from the project's own organisation is lower risk than a stranger's. A comment such as
`# v4` next to a SHA means it is pinned and the detector should have counted it. Mention that
if you see it.

**GitHub Actions (`has_timeout_minutes`).** A missing timeout costs money and time when a job
hangs. It matters most for jobs that wait on something external.

**GitHub Actions (`has_permissions_block`).** A missing block gives the job the default token
permissions. It matters most for workflows that run on `pull_request_target` or handle
secrets.

**GitHub Actions (`has_concurrency`).** Mostly a convenience. It matters for deployment jobs.

## Writing the proof

One sentence. Name the file and line, or the commit. Say what you saw.

- Good: "Test `test_anonymous` in `tests/organization/test_endpoints.py` asserts this
  route returns 200 without credentials."
- Good: "No auth dependency and no test or comment says it is public; the same author wrote all
  47 protected routes."
- Too weak: "This looks suspicious."
- Too strong: "This is a critical vulnerability." Only say that if the code you read shows what
  an attacker could do.

## Three short examples

**BUG.** `POST /api/v1/users/export` has no auth, 47 of 48 routes have it, the function returns
every user's email, and the commit "add csv export" is by the author of the other 47. No test
mentions the route.

**INTENTIONAL.** `GET /{id}/payment-status` has no auth, but the test class `TestGetPaymentStatus`
contains `test_anonymous`, which asserts a 200 with no credentials, and the service method it
calls is documented as being for anonymous users.

**UNSURE.** A CI job has no `timeout-minutes`, the other 30 do, and the commit message is
"update CI". Nothing says whether this job is expected to be short. Say what would settle it.
