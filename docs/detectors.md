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
| `has_response_model` | The route sets `response_model` |
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
- the router: `APIRouter(dependencies=[...])`, including subclasses of `APIRouter`
- every `include_router(..., dependencies=[...])` call, through nested routers
- the app: `FastAPI(dependencies=[...])`

Routers can be created inside functions: each function has its own scope, so two factory
functions that both name their router `router` do not mix. A router included in more than
one place gets the dependencies of all of them, so a gap in only one inclusion is not
reported.

A dependency counts as auth when its name contains words such as `auth`, `token`,
`verify`, `permission`, `admin`, `oauth2`, `jwt`, `bearer` or `current_user`. Whole words
are matched, so `get_authors` is not auth. You can add your own words; see
[Configuration](configuration.md).

### GitHub Actions (`github_actions`)

Reads workflows in `.github/workflows/` and composite actions (`action.yml` files under
`.github/actions/` and at the repository root) with `yaml.safe_load`.

| Group | Feature | Why it matters |
|---|---|---|
| Third-party actions and reusable workflows | `pinned_to_sha` (a commit SHA or a Docker `sha256:` digest) | Supply-chain safety |
| Jobs | `has_timeout_minutes` | Stops runaway jobs |
| Jobs | `has_concurrency` | Avoids duplicate runs |
| Workflows | `has_permissions_block` | Least-privilege tokens |

Workflow-level `concurrency` counts for every job. A workflow whose jobs all set their
own `permissions` counts as having a permissions block. Local actions and workflows
(`./...`) are skipped, and so are references built from expressions
(`actions/checkout@${{ inputs.ref }}`), which are only known when the workflow runs.
