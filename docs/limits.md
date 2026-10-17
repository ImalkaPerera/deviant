# Limits

What Deviant does not do, so you can judge how far to trust a result.

- **Needs enough similar items.** See [why small projects show nothing](how-it-works.md#why-small-projects-show-nothing).
- **Finds only what a detector looks for.** Today that is FastAPI routes and GitHub
  Actions workflows.
- **Reads code, does not run it.** Routes are found from decorators and `add_api_route`
  calls. A router passed in as a function parameter, a router stored on an object
  (`self.router = APIRouter()`), routes registered in a loop, and
  `include_router(get_router())` where the router comes from a call are not followed.
- **Auth helpers are matched by name.** A route counts as protected if it calls a function
  named like one that checks credentials in its body. If two functions share a name, a
  route may be treated as protected when it is not.
- **Parses with the Python it runs on.** Python 3.14's unparenthesised `except A, B:` is
  read on older versions too, but other new syntax cannot be. A file that cannot be parsed
  is reported on stderr, because it may hide auth helpers that other files import. Run
  Deviant with the same or a newer Python than your project.
- **Git evidence needs real history.** In a shallow clone git blames old lines on the oldest
  commit it fetched, so the author is wrong. Deviant marks that evidence as truncated.
  Use a full clone.
- **Exceptions are leads, not verdicts.** Some exceptions are intentional.
