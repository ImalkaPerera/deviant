# Tested on real projects

Deviant has been run on real open-source code, and the results were read by hand. This
page says what we saw, including what the early versions got wrong, because that is how
you can judge how far to trust a finding.

We are grateful to the maintainers of these projects. Nothing here is a claim that their
code has bugs.

## What we ran it on

| Project | Check | Size |
|---|---|---|
| [full-stack-fastapi-template](https://github.com/fastapi/full-stack-fastapi-template) | FastAPI routes, GitHub Actions | 23 routes, 51 third-party steps |
| [Polar](https://github.com/polarsource/polar) | FastAPI routes, GitHub Actions | 450 routes, 206 third-party steps |
| [Douyin_TikTok_Download_API](https://github.com/Evil0ctal/Douyin_TikTok_Download_API) | FastAPI routes | 117 routes |
| [fastapi_mcp](https://github.com/tadata-org/fastapi_mcp) | FastAPI routes | 23 routes |
| [WhisperLiveKit](https://github.com/QuentinFuxa/WhisperLiveKit) | FastAPI routes | 5 routes |
| [ruff](https://github.com/astral-sh/ruff) | GitHub Actions | 323 third-party steps |
| [pydantic](https://github.com/pydantic/pydantic) | GitHub Actions | 171 third-party steps |

## What it found

At the default settings the scan reported **one candidate**: in Polar, `GET /{id}/payment-status`
is the only route without auth among 42 in its folder. We read the code. It is intentional:
Polar's own test `test_anonymous` asserts that the endpoint answers without auth, and its
service method is documented as being for anonymous users. A judge reading that test would
label the exception intentional, which is the kind of proof the planned judge step is meant
to look for.

So far we have **not** found a confirmed bug in someone else's project, and we have not
measured how often Deviant is right. A published benchmark is on the [roadmap](../README.md#roadmap).

## Why it reports so little

A rule needs a group of at least 20 similar items with only 1 to 3 exceptions. Real projects
rarely look like that across a whole repository: auth styles are mixed, and CI jobs differ
for good reasons. That is why FastAPI routes are compared within their own folder, where
one convention usually holds.

## What the early versions got wrong

Reading real results by hand, and then reviewing the code, found problems that tests on
small examples did not. All of these are fixed, and each has a regression test.

| What happened | Cause | Fix |
|---|---|---|
| Every one of the 23 routes in the FastAPI template was reported as having no auth | Auth came from `CurrentUser = Annotated[User, Depends(...)]`, an alias defined in a file that uses Python 3.14 syntax our Python could not read | Follow aliases across files, and read that syntax on older Pythons |
| Routes in Polar looked unprotected | Auth used `Authenticator`, `OrgPolicyGuard` and security schemes, names with no auth word | Recognise those styles and types named as an auth subject |
| 11 unpinned actions reported in ruff | Local reusable workflows written as `$/...` were treated as third-party | Treat them as local |
| Polar's Python 3.14 code could not be read | `except A, B:` without parentheses is new syntax | Read it on older Pythons too, and warn when a file cannot be parsed |
| Git showed an unrelated commit as the author | A shallow clone blames every old line on its newest commit | Mark that evidence as truncated |
| A Docker image pinned by digest was reported as unpinned (found in code review, not on a real project) | Only 40-character SHAs were accepted | Accept `sha256:` digests |

## Try it on your project

If Deviant flags something that is fine, or misses something it should catch,
[open an issue](https://github.com/ImalkaPerera/deviant/issues/new/choose). Reports from real
projects are the most useful thing you can contribute.
