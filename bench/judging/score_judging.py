"""Score the labels Claude gave in the judging runs against the known answers.

Usage: python score_judging.py <cases dir> <results dir> <condition>

A run's label is read from the table row that names the flagged route (the skill's format),
or from the 'LABEL:' line (the plain prompt). NONE means the answer gave no label for the case.
"""

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

LABELS = ("BUG", "INTENTIONAL", "UNSURE")
WORD = re.compile(r"\b(BUG|INTENTIONAL|UNSURE)\b")


def label_of(text, case):
    plain = re.search(r"LABEL:\s*\**\s*(BUG|INTENTIONAL|UNSURE)\b", text)
    if plain:
        return plain.group(1)
    # The skill may write the route with its URL prefix, so the file name also identifies it.
    base = case["file"].rsplit("/", 1)[-1]
    for line in text.splitlines():
        if case["function"] in line or case["route"] in line or base in line:
            found = WORD.search(line)
            if found:
                return found.group(1)
    return "NONE"


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    cases_dir, results, condition = Path(argv[1]), Path(argv[2]), argv[3]
    cases = {c["id"]: c for c in json.loads((cases_dir / "cases.json").read_text(encoding="utf-8"))}
    table = defaultdict(Counter)
    cost = 0.0
    runs = 0
    for path in sorted((results / condition).glob("c*_run[0-9].json")):
        run = json.loads(path.read_text(encoding="utf-8"))
        case = cases[run["case"]]
        label = label_of(run.get("result") or "", case)
        table[case["truth"]][label] += 1
        cost += run.get("total_cost_usd") or 0.0
        runs += 1
        print(f"{run['case']} run {run['run']}  truth {case['truth']:<11} label {label}")
    print()
    print(f"condition {condition}: {runs} runs, API-equivalent cost ${cost:.2f}")
    print(f"{'truth':<12}" + "".join(f"{label:>13}" for label in (*LABELS, "NONE")))
    for truth in ("BUG", "INTENTIONAL"):
        counts = table[truth]
        print(f"{truth:<12}" + "".join(f"{counts[label]:>13}" for label in (*LABELS, "NONE")))
    right = table["BUG"]["BUG"] + table["INTENTIONAL"]["INTENTIONAL"]
    wrong = table["BUG"]["INTENTIONAL"] + table["INTENTIONAL"]["BUG"]
    total = sum(sum(c.values()) for c in table.values())
    print(f"right {right}, wrong {wrong}, unsure or none {total - right - wrong}, of {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
