"""Group detector output, find rules, filter them, and rank them.

Does the math only. Detectors extract facts; git_forensics adds the history of each
exception when --with-git is used.
"""

import argparse
import importlib.util
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from git_forensics import GitEvidence
from stats import (
    DEFAULT_MIN_CONFIDENCE,
    DEFAULT_MIN_ITEMS,
    passes_filter,
    wilson_lower_bound,
)

MIN_PREVALENCE = 0.5  # plan 6.6: features true for less than half the group are not patterns
# Features named is_* describe an item (is_mutating). They are only used as if-then
# conditions, never as something an item is required to have.
CONDITION_PREFIX = "is_"
EXAMPLES_PER_RULE = 3
REQUIRED_KEYS = ("detector", "peer_group", "item_id", "file", "line", "features")
DETECTORS_DIR = Path(__file__).resolve().parent / "detectors"


def group_items(items):
    groups = defaultdict(list)
    for item in items:
        groups[(item["detector"], item["peer_group"])].append(item)
    return groups


# Detector and feature names go into rule ids as detector.peer_group.feature. Keeping dots
# out of them is what lets parse_rule_id split a rule id back apart, even when the peer
# group holds a folder name such as "v1.2".
_NAME = re.compile(r"^[A-Za-z0-9_]+$")


def validate_items(items):
    """Raise ValueError unless every item follows the detector contract.

    A mistake here would otherwise change results silently: a truthy number counted as
    False, a string line number breaking the sort, or a feature missing from one item.
    """
    if not isinstance(items, list):
        raise ValueError(f"extract() must return a list, not {type(items).__name__}")
    names_by_group = {}
    for item in items:
        if not isinstance(item, dict):
            raise ValueError(f"item must be a dict, not {type(item).__name__}")
        missing = [k for k in REQUIRED_KEYS if k not in item]
        if missing:
            raise ValueError(f"detector item missing keys {missing}: {item.get('item_id')}")
        label = item["item_id"]
        if not isinstance(item["detector"], str) or not _NAME.match(item["detector"]):
            raise ValueError(f"detector must be letters, digits and underscores: {label!r}")
        if not isinstance(item["peer_group"], str) or not item["peer_group"]:
            raise ValueError(f"peer_group must be a non-empty string: {label!r}")
        if not isinstance(item["item_id"], str) or not item["item_id"]:
            raise ValueError("item_id must be a non-empty string")
        if not isinstance(item["file"], str) or not item["file"]:
            raise ValueError(f"file must be a non-empty string: {label!r}")
        line = item["line"]
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            raise ValueError(f"line must be an integer of at least 1: {label!r}")
        features = item["features"]
        if not isinstance(features, dict):
            raise ValueError(f"features must be a dict: {label!r}")
        for name, value in features.items():
            if not isinstance(name, str) or not _NAME.match(name) or "_implies_" in name:
                raise ValueError(
                    f"feature name must be letters, digits, underscores, without "
                    f"'_implies_': {name!r}"
                )
            if not isinstance(value, bool):
                raise ValueError(f"feature {name!r} must be a bool, not {value!r}: {label!r}")
        # A feature missing from one item would silently count as False, so every item in
        # a peer group must report the same feature names.
        group = (item["detector"], item["peer_group"])
        names_by_group.setdefault(group, set(features))
        if set(features) != names_by_group[group]:
            raise ValueError(f"inconsistent feature names in {group}: {label}")


_validate = validate_items


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
        "condition": cond,
        "feature": feature,
        "statement": statement,
        "n": n,
        "s": s,
        "v": n - s,
        "wlb95": round(wlb, 3),
        "exceptions": exceptions,
        "compliant_examples": examples,
        # Every compliant location, for git evidence. Removed before output.
        "_compliant": [(m["file"], m["line"]) for m in pool if _has(m, feature)],
    }


def _candidates(detector, peer, members, min_items, min_confidence):
    names = sorted({f for m in members for f in m["features"]})
    conditions = [f for f in names if f.startswith(CONDITION_PREFIX)]
    requirements = [f for f in names if not f.startswith(CONDITION_PREFIX)]
    for feature in requirements:
        pool = members
        s = sum(_has(m, feature) for m in pool)
        if s / len(pool) >= MIN_PREVALENCE and passes_filter(
            s, len(pool), min_items, min_confidence
        ):
            yield _make_rule(detector, peer, "plain", None, feature, pool, s, len(pool))
    for cond in conditions:
        pool = [m for m in members if _has(m, cond)]
        # A condition true for every item is the same as a plain rule.
        if not pool or len(pool) == len(members):
            continue
        for feature in requirements:
            s = sum(_has(m, feature) for m in pool)
            if s / len(pool) < MIN_PREVALENCE:
                continue
            if passes_filter(s, len(pool), min_items, min_confidence):
                yield _make_rule(detector, peer, "if_then", cond, feature, pool, s, len(pool))


def _sort_key(rule):
    return (-rule["wlb95"], -rule["n"], rule["v"], rule["kind"] != "plain", rule["rule_id"])


def mine(
    items,
    min_items=DEFAULT_MIN_ITEMS,
    min_confidence=DEFAULT_MIN_CONFIDENCE,
    repo_root=None,
):
    """Return reported rules, strongest first.

    With repo_root, each exception also gets a "git" block from the history of its line.
    """
    validate_items(items)
    # The same item reported twice would inflate the group, so keep one of each.
    unique = {}
    for entry in items:
        key = (
            entry["detector"],
            entry["peer_group"],
            entry["item_id"],
            entry["file"],
            entry["line"],
        )
        unique.setdefault(key, entry)
    # Sort first so the output does not depend on the order detectors return items.
    items = sorted(unique.values(), key=lambda i: (i["file"], i["line"], i["item_id"]))
    best_by_exceptions = {}
    for (detector, peer), members in group_items(items).items():
        for rule in _candidates(detector, peer, members, min_items, min_confidence):
            # A plain rule and an if-then rule for the same feature with the same exceptions
            # say the same thing; keep the stronger. Different features stay separate, so an
            # item missing both auth and a response model gives two findings.
            key = (
                detector,
                peer,
                rule["feature"],
                tuple(sorted((e["item_id"], e["file"], e["line"]) for e in rule["exceptions"])),
            )
            current = best_by_exceptions.get(key)
            if current is None or _sort_key(rule) < _sort_key(current):
                best_by_exceptions[key] = rule
    rules = sorted(best_by_exceptions.values(), key=_sort_key)
    evidence = GitEvidence(Path(repo_root)) if repo_root is not None and rules else None
    for rule in rules:
        for exception in rule["exceptions"]:
            if evidence is not None:
                exception["git"] = evidence.exception_evidence(
                    exception["file"], exception["line"], rule["_compliant"]
                )
        del rule["_compliant"]
    return rules


def load_detectors(detectors_dir: Path):
    """Import every detector module in the folder, skipping names that start with _."""
    modules = []
    for path in sorted(Path(detectors_dir).glob("*.py")):
        if path.name.startswith("_"):
            continue
        spec = importlib.util.spec_from_file_location(f"deviant_detector_{path.stem}", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as error:  # one broken detector must not stop the scan
            print(f"warning: could not load detector {path.name}: {error}", file=sys.stderr)
            continue
        if callable(getattr(module, "extract", None)):
            modules.append(module)
    return modules


def collect_items(repo_root: Path, detectors_dir: Path):
    items = []
    for module in load_detectors(detectors_dir):
        name = module.__name__.removeprefix("deviant_detector_")
        try:
            found = module.extract(str(repo_root))
        except Exception as error:  # one broken detector must not stop the scan
            print(f"warning: detector {name} failed and was skipped: {error}", file=sys.stderr)
            continue
        try:
            validate_items(found)
        except ValueError as error:  # bad output from one detector must not poison the rest
            print(f"warning: detector {name} returned invalid items: {error}", file=sys.stderr)
            continue
        items.extend(found)
    return items


def parse_rule_id(rule_id: str) -> dict:
    """Split detector.peer_group.feature back into its parts.

    The detector and the feature never contain dots but the peer group can (a folder such
    as "v1.2"), so split once from the left and once from the right.
    """
    if rule_id.count(".") < 2:
        raise ValueError(f"not a rule id: {rule_id!r}")
    detector, rest = rule_id.split(".", 1)
    peer_group, name = rest.rsplit(".", 1)
    condition = None
    if "_implies_" in name:
        condition, name = name.split("_implies_", 1)
    return {
        "detector": detector,
        "peer_group": peer_group,
        "condition": condition,
        "feature": name,
    }


def _format_text(rules):
    lines = []
    for r in rules:
        lines.append(f"{r['rule_id']}  n={r['n']} s={r['s']} v={r['v']} wlb95={r['wlb95']:.3f}")
        lines.append(f"  {r['statement']}")
        for e in r["exceptions"]:
            lines.append(f"  exception: {e['file']}:{e['line']} ({e['item_id']})")
            git = e.get("git")
            if git:
                where = "uncommitted" if git["uncommitted"] else f"{git['commit']} {git['date']}"
                lines.append(f"    last changed: {where} by {git['author']}")
                lines.append(f"    commit: {git['subject']}")
                lines.append(
                    f"    same author followed the rule in {git['author_followed_rule_elsewhere']}"
                    f" of {git['compliant_checked']} checked compliant items"
                )
                if git["history_truncated"]:
                    lines.append("    history truncated: shallow clone, so the author may be wrong")
                if git["intent_words"]:
                    lines.append(f"    intent words: {', '.join(git['intent_words'])}")
    return "\n".join(lines)


def run(repo_root, detectors_dir, min_items, min_confidence, as_json, with_git=False):
    if not Path(repo_root).is_dir():
        print(f"error: {repo_root} is not a directory", file=sys.stderr)
        return 2
    items = collect_items(Path(repo_root), Path(detectors_dir))
    rules = mine(
        items,
        min_items=min_items,
        min_confidence=min_confidence,
        repo_root=Path(repo_root) if with_git else None,
    )
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


def _positive_int(text):
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _fraction(text):
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from None
    if not 0.0 <= value <= 1.0:  # also rejects nan
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find rules that similar items follow.")
    parser.add_argument("--repo", default=".", help="repository root to scan")
    parser.add_argument("--min-items", type=_positive_int, default=DEFAULT_MIN_ITEMS)
    parser.add_argument("--min-confidence", type=_fraction, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument(
        "--with-git", action="store_true", help="add the git history of each exception"
    )
    args = parser.parse_args(argv)
    # Commit subjects and author names can hold any character. A Windows console that
    # cannot print them must not crash the scan, so replace what it cannot show.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    try:
        return run(
            args.repo,
            DETECTORS_DIR,
            args.min_items,
            args.min_confidence,
            args.json,
            with_git=args.with_git,
        )
    except BrokenPipeError:
        # The reader went away (for example `| head`). Point stdout at the null device so
        # the interpreter does not fail again while flushing at exit.
        try:
            sys.stdout = open(os.devnull, "w")  # noqa: SIM115
        except OSError:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
