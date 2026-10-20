# Detectors

A detector turns one kind of thing in your code into a list of items with yes/no features.

### FastAPI routes (`python_routes`)

Reads Python with the standard `ast` module.

Routes are compared with the other routes in the same folder. A whole project often mixes
auth styles, so a project-wide rule rarely holds, while one folder usually follows one
convention. Each folder needs enough routes to pass the size floor, so small folders show
nothing.

| Feature | True when |
|---|---|
| `is_mutating` | The route uses POST, PUT, PATCH or DELETE. A route whose methods are given by a variable is reported as `ANY` and is not counted as mutating |
| `has_auth` | An auth dependency applies to the route, or the route checks credentials itself |
| `has_response_model` | The route sets `response_model`. Style only, so it is reported only with `--include-style` |
| `has_rate_limit` | A rate-limit dependency or decorator applies |

#### Which routes are found

- the decorators `@router.get`, `post`, `put`, `patch`, `delete`, `head`, `options`, `trace`,
  `api_route` and `websocket`, on a function
- the call forms `router.add_api_route(...)`, `router.add_route(...)` and
  `router.add_websocket_route(...)`
- the call form of a decorator, `router.get("/x")(handler)`, which is the same route as the
  decorator form

A websocket route is reported as `WEBSOCKET /path`.

#### Where auth can come from

Auth often comes from above the route, so the detector follows every level FastAPI uses:

- route parameters: `user = Depends(get_current_user)`, `Security(...)`, also written
  `Depends(dependency=...)` or imported under another name (`Depends as D`)
- a bare `Depends()` takes its dependency from the parameter's annotation:
  `user: get_current_user = Depends()`
- `Annotated` aliases, including ones imported from other files, re-exported through a
  package, imported with `from module import *`, written as a string, nested inside a string
  such as `Optional["CurrentUser"]`, or declared with a Python 3.12 `type` statement:
  `CurrentUser = Annotated[User, Depends(get_current_user)]`
- an import with an alias (`from app.deps import get_current_user as gcu`) is followed to the
  name it was imported as
- dependency lists and single dependencies kept in variables: `AUTH = [Depends(...)]`
- a lambda endpoint's default: `lambda user=Depends(get_current_user): ...`
- the route decorator: `@router.post(..., dependencies=[Depends(...)])`, and routes added
  with `add_api_route` or `add_route`
- the router: `APIRouter(dependencies=[...])`, including subclasses of `APIRouter` and a
  router stored on `self` inside a class
- every `include_router(..., dependencies=[...])` call, through nested routers, whether the
  router is passed by position or as `router=`
- the app: `FastAPI(dependencies=[...])`
- other decorators on the route, such as `@requires_login("admin")`, when their name counts as
  auth
- a dependency defined in the repository whose body raises a 401 or 403 (`HTTPException`), so
  `Depends(get_user)` counts when `get_user` checks the caller
- a class used as a dependency whose `__init__` depends on auth, or raises a 401 or 403. A
  class whose `__init__` only calls a helper named like `verify_*` does not count

Routers can be created inside functions: each function has its own scope, so two factory
functions that both name their router `router` do not mix. A router included in more than
one place gets the dependencies of all of them, so a gap in only one inclusion is not
reported.

Imports resolve to the right file in a monorepo. When two services each have an
`app/auth.py`, a route in one service follows the auth module of its own service.

#### What counts as an auth name

A dependency counts as auth when its name contains words such as `auth`, `token`,
`verify`, `permission`, `admin`, `oauth2`, `jwt`, `bearer`, `current_user`, or `role` with
`checker` (as in `RoleChecker(["admin"])`), or a pair such as `validate` with `session` or
`identity`. Whole words are matched, so `get_authors` is not auth,
and a plain `validate_pagination` is not either. A name with none of these words is missed,
unless its body checks credentials as described above, and you can add your own. A dependency
built from a class in `fastapi.security` (`HTTPBasic`, `HTTPBearer`, `OAuth2PasswordBearer`,
`APIKeyHeader` and the rest) is auth whatever its variable is called. You can add your own
words; see [Configuration](configuration.md).

A parameter that takes a value from a `Cookie()` is a session credential, whatever it is
named, so `session_id: str = Cookie()` counts as auth.

#### Public routes

Routes that cannot require a session are not reported: login, register, sign-in, token,
refresh, callback, health, forgot-password, reset-password, request-verify-token, verify,
authorize and public routes, and routes whose docstring or comment says they are public.

- A public word counts only when the claim is not negated in its sentence. "Not intentionally
  public; requires login." is not public.
- A word in a route's own path counts. `/public/hook` is public only if its last segment is
  one of the public words.
- A root route (`/`, or an empty path) takes the name of the prefix it is mounted under. So
  `include_router(health, prefix="/health")` makes its `/` route public, and
  `APIRouter(prefix="/login")` with `@router.post("")` is public.
- A mount prefix does not make a route with its own path public. Under `/docs`, the route
  `DELETE /{doc_id}` is still checked.

Folders named `tests` or `test` are not scanned.

#### Files that are skipped

A file that cannot be parsed, or is larger than 1 MB, is reported on stderr, because a route
inside it would be missed. Plain Jinja templates are skipped silently. A broken file that
imports `APIRouter` or `FastAPI` is reported.

### GitHub Actions (`github_actions`)

Reads workflows in `.github/workflows/` and composite actions (`action.yml` files under
`.github/actions/` and at the repository root) with a YAML loader. The loader reads `true`,
`false`, `on`, `yes`, `no` and `null` as text, as GitHub does, so a job named `on` or `yes` keeps
its name and is checked like any other job.

| Group | Feature | Why it matters |
|---|---|---|
| Third-party actions and reusable workflows | `pinned_to_sha` (a commit SHA or a Docker `sha256:` digest) | Supply-chain safety |
| Jobs | `has_timeout_minutes` | Stops runaway jobs. `timeout-minutes: 0` does not count as a timeout |
| Jobs | `has_concurrency` | Avoids duplicate runs |
| Workflows | `has_permissions_block` | Least-privilege tokens |

A job whose only steps run `re-actors/alls-green` needs no timeout, because it finishes at
once. A workflow that is only called by others (`on: workflow_call`) takes its permissions
from the caller, so it needs no permissions block. Workflow-level `concurrency` counts for
every job. A workflow whose jobs all set their own `permissions` counts as having a
permissions block. Local actions and workflows
(`./...`) are skipped, and so are references built from expressions
(`actions/checkout@${{ inputs.ref }}`), which are only known when the workflow runs.

A comment that repeats a step's text does not move that step's line number. A file that
cannot be parsed, is not a mapping, or is larger than 1 MB is reported on stderr and skipped.
A junction that leads to a folder already scanned does not make an action count twice.
