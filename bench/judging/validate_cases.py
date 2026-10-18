"""Check that the scan reports exactly the planted route in every case.

Usage: python validate_cases.py <cases dir>
"""

import json
import sys
from pathlib import Path

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "skills" / "deviant" / "scripts")
)

from deviant_scan import mine  # noqa: E402


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    cases = json.loads((Path(argv[1]) / "cases.json").read_text(encoding="utf-8"))
    bad = 0
    for case in cases:
        root = Path(case["dir"])
        rules = mine.mine(mine.collect_items(root, mine.DETECTORS_DIR), repo_root=root)
        found = [
            (e["file"], e["item_id"], r["n"], r["s"])
            for r in rules
            if r["feature"] == "has_auth"
            for e in r["exceptions"]
        ]
        ok = [f for f in found if f[0] == case["file"] and f[1] == case["route"]]
        status = "ok " if len(found) == 1 and len(ok) == 1 else "BAD"
        bad += status == "BAD"
        print(status, case["id"], case["truth"], found)
    print(f"{len(cases) - bad} of {len(cases)} cases are reported exactly")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
