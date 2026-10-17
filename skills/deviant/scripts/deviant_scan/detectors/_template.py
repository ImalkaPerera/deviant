"""Template for a new detector. Copy this file, rename it, and fill in extract().

Rules for every detector (see CONTRIBUTING.md):
- Only read files under repo_root. Never follow symlinks out of it.
- Never import or run project code. Use ast or a parser, not exec.
- Skip files larger than 1 MB, unparseable files, and folders like node_modules.
- Never do math and never call git. The mining step does the math.
- Every feature is True or False, and every item in a peer group has the same features.
- Name features that describe an item is_* (is_mutating). They are only used as
  if-then conditions. Name features an item should have has_* (has_auth).
- If a file cannot be parsed, skip it and say so on stderr.

Files whose names start with "_" are skipped by the loader, so this template
never runs during a scan.
"""

DETECTOR = "my_detector"  # must match the file name, e.g. my_detector.py
PEER_GROUP = "my_peer_group"  # the set of similar items this detector compares


def extract(repo_root: str) -> list[dict]:
    """Return one item per thing in the peer group.

    Each item:
      detector   - DETECTOR above
      peer_group - PEER_GROUP above
      item_id    - human-readable id, e.g. "POST /api/users"
      file       - path relative to repo_root, with forward slashes
      line       - 1-based line number
      features   - {name: bool}; every item must have the same feature names
      context    - optional extra facts for the judge step
    """
    items: list[dict] = []
    return items
