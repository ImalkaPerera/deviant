"""Group detector output, find rules, filter them, and rank them.

Does the math only. Detectors extract facts; git evidence is added later.
"""

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

from stats import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_ITEMS,
    passes_filter,
    wilson_lower_bound,
)

MIN_PREVALENCE = 0.5  # plan 6.6: features true for less than half the group are not patterns
EXAMPLES_PER_RULE = 3
REQUIRED_KEYS = ("detector", "peer_group", "item_id", "file", "line", "features")
DETECTORS_DIR = Path(__file__).resolve().parent / "detectors"


def group_items(items):
    groups = defaultdict(list)
    for item in items:
        groups[(item["detector"], item["peer_group"])].append(item)
    return groups


def _validate(items):
    for item in items:
        missing = [k for k in REQUIRED_KEYS if k not in item]
        if missing:
            raise ValueError(f"detector item missing keys {missing}: {item.get('item_id')}")
    # A feature missing from one item would silently count as False, so every item in a
    # peer group must report the same feature names.
    names_by_group = {}
    for item in items:
        group = (item["detector"], item["peer_group"])
        names_by_group.setdefault(group, set(item["features"]))
        if set(item["features"]) != names_by_group[group]:
            raise ValueError(f"inconsistent feature names in {group}: {item['item_id']}")


def _has(item, feature):
    return item["features"].get(feature) is True


def _make_rule(detector, peer, kind, cond, feature, pool, s, n):
    wlb = wilson_lower_bound(s, n)
    if kind == "plain":
        rule_id = f"{detector}.{peer}.{feature}"
        statement = f"In {peer}, {feature} is true"
    else:
        rule_id = f"{detector}.{peer}.{cond}_implies_{feature}"
        statement = f"When {cond}, {feature} is also true"
    exceptions = [
        {"item_id": m["item_id"], "file": m["file"], "line": m["line"], "git": None}
        for m in pool
        if not _has(m, feature)
    ]
    examples = [{"file": m["file"], "line": m["line"]} for m in pool if _has(m, feature)][
        :EXAMPLES_PER_RULE
    ]
    return {
        "rule_id": rule_id,
        "kind": kind,
        "statement": statement,
        "n": n,
        "s": s,
        "v": n - s,
        "wlb95": round(wlb, 3),
        "exceptions": exceptions,
        "compliant_examples": examples,
    }


def _candidates(detector, peer, members, min_items, min_confidence):
    features = sorted({f for m in members for f in m["features"]})
    for feature in features:
        pool = members
        s = sum(_has(m, feature) for m in pool)
        if s / len(pool) >= MIN_PREVALENCE and passes_filter(
            s, len(pool), min_items, min_confidence
        ):
            yield _make_rule(detector, peer, "plain", None, feature, pool, s, len(pool))
    for cond in features:
        pool = [m for m in members if _has(m, cond)]
        # A condition true for every item is the same as a plain rule.
        if not pool or len(pool) == len(members):
            continue
        for feature in features:
            if feature == cond:
                continue
            s = sum(_has(m, feature) for m in pool)
            if s / len(pool) < MIN_PREVALENCE:
                continue
            if passes_filter(s, len(pool), min_items, min_confidence):
                yield _make_rule(detector, peer, "if_then", cond, feature, pool, s, len(pool))


def _sort_key(rule):
    return (-rule["wlb95"], -rule["n"], rule["v"], rule["kind"] != "plain", rule["rule_id"])


def mine(items, min_items=DEFAULT_MIN_ITEMS, min_confidence=DEFAULT_MIN_CONFIDENCE):
    """Return reported rules, strongest first."""
    _validate(items)
    # Sort first so the output does not depend on the order detectors return items.
    items = sorted(items, key=lambda i: (i["file"], i["line"], i["item_id"]))
    best_by_exceptions = {}
    for (detector, peer), members in group_items(items).items():
        for rule in _candidates(detector, peer, members, min_items, min_confidence):
            # Rules with the same exceptions say the same thing; keep the strongest.
            key = (
                detector,
                peer,
                tuple(sorted((e["item_id"], e["file"], e["line"]) for e in rule["exceptions"])),
            )
            current = best_by_exceptions.get(key)
            if current is None or _sort_key(rule) < _sort_key(current):
                best_by_exceptions[key] = rule
    return sorted(best_by_exceptions.values(), key=_sort_key)


def load_detectors(detectors_dir: Path):
    """Import every detector module in the folder, skipping names that start with _."""
    modules = []
    for path in sorted(Path(detectors_dir).glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"deviant_detector_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if callable(getattr(module, "extract", None)):
            modules.append(module)
    return modules


def collect_items(repo_root: Path, detectors_dir: Path):
    items = []
    for module in load_detectors(detectors_dir):
        items.extend(module.extract(str(repo_root)))
    return items


def _format_text(rules):
    lines = []
    for r in rules:
        lines.append(f"{r['rule_id']}  n={r['n']} s={r['s']} v={r['v']} wlb95={r['wlb95']:.3f}")
        lines.append(f"  {r['statement']}")
        for e in r["exceptions"]:
            lines.append(f"  exception: {e['file']}:{e['line']} ({e['item_id']})")
    return "\n".join(lines)


def run(repo_root, detectors_dir, min_items, min_confidence, as_json):
    items = collect_items(Path(repo_root), Path(detectors_dir))
    rules = mine(items, min_items=min_items, min_confidence=min_confidence)
    if as_json:
        print(json.dumps({"version": 1, "rules": rules}, indent=2))
    elif not rules:
        print(
            "no rules found. Groups may be too small: a group needs at least "
            f"{min_items} similar items, and one exception needs about 25 "
            "at the default 0.80 confidence."
        )
    else:
        print(_format_text(rules))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find rules that similar items follow.")
    parser.add_argument("--repo", default=".", help="repository root to scan")
    parser.add_argument("--min-items", type=int, default=DEFAULT_MIN_ITEMS)
    parser.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument("--with-git", action="store_true", help="add git evidence (Phase 3)")
    args = parser.parse_args(argv)
    if args.with_git:
        print("warning: git evidence is not built yet; ignoring --with-git", file=sys.stderr)
    return run(args.repo, DETECTORS_DIR, args.min_items, args.min_confidence, args.json)


if __name__ == "__main__":
    sys.exit(main())
