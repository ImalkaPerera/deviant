# Detector specification

A detector turns one kind of thing in a project into a list of **items**. Each item has
yes/no **features**. Deviant then counts the features, finds the patterns and reports the
rare exceptions. The detector only collects facts. It never does the counting.

A detector is one file in `skills/deviant/scripts/deviant_scan/detectors/`. The file name is its name.

```python
def extract(repo_root: str) -> list[dict]: ...
```

## An item

```python
{
    "detector": "python_routes",  # the detector's name
    "peer_group": "fastapi_routes:app/api",  # the set of items compared with each other
    "item_id": "POST /api/v1/users/export",  # readable name of this item
    "file": "app/api/users.py",  # relative to repo_root, with forward slashes
    "line": 142,  # 1-based
    "features": {"is_mutating": True, "has_auth": False},
    "context": {"function_name": "export_users"},  # optional, for the judge step
}
```

| Field | Rule |
|---|---|
| `detector` | Letters, digits and underscores. Same for every item from this detector. |
| `peer_group` | A non-empty string. Items with the same detector and peer group are compared. |
| `item_id` | A non-empty string. |
| `file` | A non-empty string, relative to `repo_root`. |
| `line` | An integer, 1 or more. |
| `span` | Optional. `[first line, last line]`, both 1 or more and first not after last. The lines where the item is written, when that is more than `line`. A route's decorators and its `def` line, for example. Git evidence uses the newest change in the span. |
| `features` | A dict of name to `True` or `False`. Nothing else (not `1`, not `None`). |
| `context` | Optional. Anything JSON can hold. |

Feature names use letters, digits and underscores, and must not contain `_implies_`.
Every item in a peer group must have the same feature names.

## Two kinds of feature

- **`has_*`**: something an item *should* have, such as `has_auth` or `has_timeout`.
  Deviant looks for groups where almost every item has it.
- **`is_*`**: something an item *is*, such as `is_mutating`. Deviant uses these as
  conditions: "when a route is mutating, it has auth".

## Choosing the peer group

The peer group is the set of items that should follow the same rules. Make it as small as
it can be while still holding enough items (at least 20 by default). FastAPI routes are
grouped by folder because one folder usually follows one convention, while a whole project
often mixes styles.

## Behaviour rules

A detector must:

- read only files inside `repo_root`, and skip symlinks;
- never import or run the project's code (use `ast` or a parser, never `exec` or `import`);
- skip files over 1 MB and folders such as `node_modules`, `.venv` and `site-packages`;
- never raise on a file it cannot read. Skip the file, and say so on stderr when skipping
  could hide results;
- be deterministic: the same files give the same items;
- do no counting and no git work. Deviant does both.

A detector that raises, or returns items that break the rules above, is skipped with a
warning and the other detectors still run.

## Testing a detector

Put a small fake project in `tests/fixtures/<detector>/` and write tests that check the
features of each item. Also test unusual input: an empty folder, a file with a syntax error,
a file in another encoding. The robustness tests in `tests/test_robustness.py` show how to
check that damaged input never crashes a detector.

See `CONTRIBUTING.md` for a complete example.
