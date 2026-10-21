# Limits

What Deviant does not do, so you can judge how far to trust a result.

- **Needs enough similar items.** See [why small projects show nothing](how-it-works.md#why-small-projects-show-nothing).
- **Finds only what a detector looks for.** Today that is FastAPI routes and GitHub
  Actions workflows.
- **Reads code, does not run it.** Routes are found from decorators, `add_api_route`,
  `add_route`, `add_websocket_route` and the call form `router.get("/x")(handler)`. A router
  passed in as a function parameter, routes registered in a loop, and
  `include_router(get_router())` where the router comes from a call are not followed. A
  router stored on `self` is followed only inside its own class.
- **A dependency is read only if it is in the repository.** Auth inside a dependency's body
  is seen when that dependency is defined in the scanned code. A dependency imported from
  an installed package is judged by its name alone.
- **Star imports and aliases are followed only inside the repository.** A name that comes
  from a module outside the scanned folder is judged by its name alone.
- **Auth helpers are matched by name.** A route counts as protected if it calls a function
  named like one that checks credentials in its body. If several functions share that name,
  all of them must check credentials, otherwise the name is not trusted. Route handlers are
  left out of that comparison.
- **Parses with the Python it runs on.** Python 3.14's unparenthesised `except A, B:` is
  read on older versions too, but other new syntax cannot be. A file that cannot be parsed
  is reported on stderr, because it may hide auth helpers that other files import. Run
  Deviant with the same or a newer Python than your project.
- **Some files are skipped to keep a scan bounded.** A workflow whose merge keys (`<<:`) would
  expand to more than 100,000 keys, or a Python file over 1 MB, is skipped with a message on
  stderr. A router mounted under more than 64 different prefixes is checked against the first
  63, and never counted as public because of the rest.
- **Git evidence needs real history.** In a shallow clone git blames old lines on the oldest
  commit it fetched, so the author is wrong. Deviant marks that evidence as truncated.
  Use a full clone.
- **A bug that every similar item shares is invisible.** Deviant finds the item that breaks a
  pattern. If a whole router has no auth, or every workflow lacks a permissions block, there
  is no protected sibling to compare with, so it reports nothing. Of 7 real missing-auth
  fixes, the scan reported 1: two had no protected sibling at all, and four sat among many
  open routes (15 open of 44), which is more exceptions than a lead lists.
- **A note can silence a finding.** A docstring or comment that says a route is public, or
  that it needs no auth, takes the route out of the report, because the author's note is
  evidence that the gap is on purpose. It also means the same note, added to hide a missing
  check, hides it from the scan. This matters most when an AI coding agent or an unreviewed
  change adds the note. Read what a note says in a review; the scan cannot tell a true note
  from a convenient one.
- **Exceptions are leads, not verdicts.** Some exceptions are intentional.
