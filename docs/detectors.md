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
| `has_auth` | An auth dependency applies to the route |
| `has_response_model` | The route sets `response_model`. Style only, so it is reported only with `--include-style` |
| `has_rate_limit` | A rate-limit dependency or decorator applies |

Auth often comes from above the route, so the detector follows every level FastAPI uses:

- route parameters: `user = Depends(get_current_user)`, `Security(...)`, also written
  `Depends(dependency=...)` or imported under another name (`Depends as D`)
- `Annotated` aliases, including ones imported from other files, re-exported through a
  package, written as a string, or declared with a Python 3.12 `type` statement:
  `CurrentUser = Annotated[User, Depends(get_current_user)]`
- dependency lists and single dependencies kept in variables: `AUTH = [Depends(...)]`
- the route decorator: `@router.post(..., dependencies=[Depends(...)])`, and routes added
  with `@router.api_route(...)` or `router.add_api_route(...)`
- the router: `APIRouter(dependencies=[...])`, including subclasses of `APIRouter` and a
  router stored on `self` inside a class
- every `include_router(..., dependencies=[...])` call, through nested routers
- the app: `FastAPI(dependencies=[...])`

Routers can be created inside functions: each function has its own scope, so two factory
functions that both name their router `router` do not mix. A router included in more than
one place gets the dependencies of all of them, so a gap in only one inclusion is not
reported.

A dependency counts as auth when its name contains words such as `auth`, `token`,
`verify`, `permission`, `admin`, `oauth2`, `jwt`, `bearer` or `current_user`, or a pair such as
`validate` with `session` or `identity`. Whole words are matched, so `get_authors` is not auth,
and a plain `validate_pagination` is not either. A name with none of these words is missed, and
you can add your own. A dependency built from a class in
`fastapi.security` (`HTTPBasic`, `HTTPBearer`, `OAuth2PasswordBearer`, `APIKeyHeader` and the
rest) is auth whatever its variable is called. You can add your own words; see
[Configuration](configuration.md).

Routes that cannot require a session are not reported: login, register, sign-in, token,
refresh, callback, health, forgot-password, reset-password, request-verify-token, verify and
authorize routes, and routes whose docstring or comment says they are public. Folders named
`tests` or `test` are not scanned.

### GitHub Actions (`github_actions`)

Reads workflows in `.github/workflows/` and composite actions (`action.yml` files under
`.github/actions/` and at the repository root) with `yaml.safe_load`.

| Group | Feature | Why it matters |
|---|---|---|
| Third-party actions and reusable workflows | `pinned_to_sha` (a commit SHA or a Docker `sha256:` digest) | Supply-chain safety |
| Jobs | `has_timeout_minutes` | Stops runaway jobs |
| Jobs | `has_concurrency` | Avoids duplicate runs |
| Workflows | `has_permissions_block` | Least-privilege tokens |

A job whose only steps run `re-actors/alls-green` needs no timeout, because it finishes at
once. A workflow that is only called by others (`on: workflow_call`) takes its permissions
from the caller, so it needs no permissions block. Workflow-level `concurrency` counts for
every job. A workflow whose jobs all set their own `permissions` counts as having a
permissions block. Local actions and workflows
(`./...`) are skipped, and so are references built from expressions
(`actions/checkout@${{ inputs.ref }}`), which are only known when the workflow runs.
