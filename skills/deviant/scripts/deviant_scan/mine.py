"""Group detector output, find rules, filter them, and rank them.

Does the math only. Detectors extract facts; git_forensics adds the history of each
exception when --with-git is used.
"""

import argparse
import contextlib
import importlib.util
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

from .git_forensics import GitEvidence
from .stats import (
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
        span = item.get("span")
        if span is not None and not (
            isinstance(span, (list, tuple))
            and len(span) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in span)
            and 1 <= span[0] <= span[1]
        ):
            raise ValueError(f"span must be [first line, last line], first <= last: {label!r}")
        context = item.get("context")
        if context is not None and not isinstance(context, dict):
            raise ValueError(f"context must be a dict or None: {label!r}")
        if isinstance(context, dict) and "dependencies" in context:
            deps = context["dependencies"]
            if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
                raise ValueError(f"context dependencies must be a list of strings: {label!r}")
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


def _has(item, feature):
    return item["features"].get(feature) is True


def _dependencies_of(item):
    """{"dependencies": [...]} when the detector listed what the item depends on, else {}."""
    found = (item.get("context") or {}).get("dependencies")
    return {"dependencies": list(found)} if found else {}


def _make_rule(detector, peer, kind, cond, feature, pool, s, n):
    wlb = wilson_lower_bound(s, n)
    if kind == "plain":
        rule_id = f"{detector}.{peer}.{feature}"
        statement = f"In {peer}, {feature} is true"
    else:
        rule_id = f"{detector}.{peer}.{cond}_implies_{feature}"
        statement = f"When {cond}, {feature} is also true"
    exceptions = [
        {
            "item_id": m["item_id"],
            "file": m["file"],
            "line": m["line"],
            **_dependencies_of(m),
            "git": None,
            # Used for git evidence only. Removed before output.
            "_span": m.get("span"),
        }
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
        "_compliant": [(m["file"], m["line"], m.get("span")) for m in pool if _has(m, feature)],
    }


def _candidates(detector, peer, members, min_items, min_confidence, hide=frozenset()):
    names = sorted({f for m in members for f in m["features"]})
    conditions = [f for f in names if f.startswith(CONDITION_PREFIX)]
    requirements = [
        f for f in names if not f.startswith(CONDITION_PREFIX) and (detector, f) not in hide
    ]
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
    # Rank by the unrounded bound. The rounded wlb95 is for display only, and ranking by it
    # made nearly equal rules swap places depending on their size.
    exact = wilson_lower_bound(rule["s"], rule["n"])
    return (-exact, -rule["n"], rule["v"], rule["kind"] != "plain", rule["rule_id"])


def _unique_items(items):
    """One of each item, in an order that does not depend on how detectors returned them."""
    # Sort by everything, features included, before keeping one of each. Then a duplicate
    # with conflicting features is resolved the same way whatever order detectors return.
    ordered = sorted(
        items,
        key=lambda i: (
            i["file"],
            i["line"],
            i["item_id"],
            i["detector"],
            i["peer_group"],
            sorted(i["features"].items()),
        ),
    )
    # The same item reported twice would inflate the group, so keep one of each.
    unique = {}
    for entry in ordered:
        key = (
            entry["detector"],
            entry["peer_group"],
            entry["item_id"],
            entry["file"],
            entry["line"],
        )
        unique.setdefault(key, entry)
    return list(unique.values())


# The inventory lists every peer group, however small, and the items that lack something most
# of their peers have. It is not a rule: it does not apply the size floor or the confidence
# bound, so what it lists are leads to read, not findings.
INVENTORY_MIN_GROUP = 4
INVENTORY_MIN_LOCAL_GROUP = 3
INVENTORY_MIN_SHARE = 0.6
INVENTORY_MAX_PER_FEATURE = 8
# A group where nearly every item follows the rule can have many exceptions and still
# have a clear rule: 25 unpinned actions among 199. From this share up, the limit on how
# many items may lack the feature no longer applies.
INVENTORY_CLEAR_SHARE = 0.85
INVENTORY_LIMIT = 60
# Groups are listed largest first and only this many, so a project with thousands of small
# folders does not produce thousands of group entries. The count of all of them is kept.
INVENTORY_MAX_GROUPS = 100


def _peer_examples(members, feature, lacking, count=2):
    """Up to `count` items that have the feature, nearest to the item that lacks it.

    The same file comes first, then the closest line, so the example is the sibling a reader
    would compare the item with.
    """
    having = [m for m in members if _has(m, feature)]
    having.sort(key=lambda m: (m["file"] != lacking["file"], abs(m["line"] - lacking["line"])))
    return [{"item_id": m["item_id"], "file": m["file"], "line": m["line"]} for m in having[:count]]


def _group_candidates(members, detector, peer, requirements, min_group, scope, path=None):
    """Leads for one set of peers: the items that lack a feature most of the set has."""
    n = len(members)
    if n < min_group:
        return []
    found = []
    for feature in requirements:
        have = sum(1 for m in members if _has(m, feature))
        lacking = n - have
        share = have / n
        if share < INVENTORY_MIN_SHARE or lacking < 1:
            continue
        # Few exceptions in a mixed group, or any number in a group that is clearly one way.
        if lacking > INVENTORY_MAX_PER_FEATURE and share < INVENTORY_CLEAR_SHARE:
            continue
        lacking_items = [m for m in members if not _has(m, feature)]
        candidate = {
            "detector": detector,
            "peer_group": peer,
            "scope": scope,
            "feature": feature,
            "n": n,
            "have": have,
            "lack": lacking,
            "share": round(share, 3),
            "items": [
                {
                    "item_id": m["item_id"],
                    "file": m["file"],
                    "line": m["line"],
                    **_dependencies_of(m),
                }
                for m in lacking_items
            ],
            "examples": _peer_examples(members, feature, lacking_items[0]),
        }
        if path is not None:
            candidate["file"] = path
        found.append(candidate)
    return found


def _lead_key(candidate, item):
    """What makes a lead the same lead: the item, the feature it lacks and its peer group."""
    return (
        candidate["detector"],
        candidate["peer_group"],
        candidate["feature"],
        item["item_id"],
        item["file"],
        item["line"],
    )


def inventory(items, hide=frozenset(), limit=INVENTORY_LIMIT):
    """{"groups": [...], "candidates": [...], "truncated": n}: how every group splits.

    A group is every item of one detector in one peer group. For each feature an item should
    have, a candidate is the set of items that lack it when at least INVENTORY_MIN_SHARE of
    the peers have it and either no more than INVENTORY_MAX_PER_FEATURE items lack it or
    at least INVENTORY_CLEAR_SHARE of the peers have it.

    Peers are looked at twice: the whole group (scope "group"), and the part of the group that
    sits in one file (scope "file"). The second catches an item that differs from its
    neighbours in the same file even when the project as a whole is mixed, for example one job
    with no timeout among four that have one. An item is listed once, under the candidate with
    the larger share, then the larger group, and the whole group wins a tie.

    Candidates are ordered the same way, and at most `limit` items are listed in total, so the
    output stays small on a large project.
    """
    validate_items(items)
    groups, candidates = [], []
    for (detector, peer), members in sorted(group_items(_unique_items(items)).items()):
        n = len(members)
        names = sorted({f for m in members for f in m["features"]})
        requirements = [
            f for f in names if not f.startswith(CONDITION_PREFIX) and (detector, f) not in hide
        ]
        split = {}
        for feature in requirements:
            have = sum(1 for m in members if _has(m, feature))
            split[feature] = {"true": have, "false": n - have}
        groups.append({"detector": detector, "peer_group": peer, "n": n, "features": split})
        candidates += _group_candidates(
            members, detector, peer, requirements, INVENTORY_MIN_GROUP, "group"
        )
        by_file = defaultdict(list)
        for m in members:
            by_file[m["file"]].append(m)
        for path, local in sorted(by_file.items()):
            if len(local) < n:  # a file that holds the whole group adds nothing
                candidates += _group_candidates(
                    local, detector, peer, requirements, INVENTORY_MIN_LOCAL_GROUP, "file", path
                )
    candidates.sort(
        key=lambda c: (
            -c["share"],
            -c["n"],
            c["scope"] != "group",
            c["detector"],
            c["peer_group"],
            c["feature"],
            c.get("file", ""),
        )
    )
    claimed, distinct = set(), []
    for candidate in candidates:
        fresh = [i for i in candidate["items"] if _lead_key(candidate, i) not in claimed]
        if not fresh:
            continue
        claimed.update(_lead_key(candidate, i) for i in fresh)
        distinct.append({**candidate, "items": fresh})
    listed, truncated = [], 0
    for candidate in distinct:
        room = limit - sum(len(c["items"]) for c in listed)
        if room <= 0:
            truncated += len(candidate["items"])
        elif len(candidate["items"]) > room:
            truncated += len(candidate["items"]) - room
            listed.append({**candidate, "items": candidate["items"][:room]})
        else:
            listed.append(candidate)
    group_count = len(groups)
    groups.sort(key=lambda g: (-g["n"], g["detector"], g["peer_group"]))
    return {
        "groups": groups[:INVENTORY_MAX_GROUPS],
        "group_count": group_count,
        "groups_omitted": max(group_count - INVENTORY_MAX_GROUPS, 0),
        "candidates": listed,
        "truncated": truncated,
    }


def mine(
    items,
    min_items=DEFAULT_MIN_ITEMS,
    min_confidence=DEFAULT_MIN_CONFIDENCE,
    repo_root=None,
    hide=frozenset(),
):
    """Return reported rules, strongest first.

    With repo_root, each exception also gets a "git" block from the history of its line.
    hide is a set of (detector, feature) pairs that are not reported.
    """
    validate_items(items)
    items = _unique_items(items)
    best_by_exceptions = {}
    for (detector, peer), members in group_items(items).items():
        for rule in _candidates(detector, peer, members, min_items, min_confidence, hide):
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
    if evidence is not None and not evidence.available:
        print(
            "warning: no git evidence added: git is missing or "
            f"{repo_root} is not inside a git repository",
            file=sys.stderr,
        )
        evidence = None
    for rule in rules:
        for exception in rule["exceptions"]:
            span = exception.pop("_span")
            if evidence is not None:
                exception["git"] = evidence.exception_evidence(
                    exception["file"], exception["line"], rule["_compliant"], span
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
            # A detector's stray print() would land in the report, and under --json would
            # corrupt it, so its stdout goes to stderr.
            with contextlib.redirect_stdout(sys.stderr):
                spec.loader.exec_module(module)
        except (
            Exception,
            SystemExit,
        ) as error:  # a detector calling sys.exit must not end the scan
            print(f"warning: could not load detector {path.name}: {error}", file=sys.stderr)
            continue
        if callable(getattr(module, "extract", None)):
            modules.append(module)
    return modules


def style_features(modules) -> frozenset:
    """(detector, feature) pairs the detectors mark as style only, with STYLE_FEATURES."""
    return frozenset(
        (module.DETECTOR, feature)
        for module in modules
        for feature in getattr(module, "STYLE_FEATURES", ())
        if hasattr(module, "DETECTOR")
    )


def collect_items(repo_root: Path, detectors_dir: Path):
    return _collect(load_detectors(detectors_dir), repo_root)


def _collect(modules, repo_root: Path):
    items = []
    for module in modules:
        name = module.__name__.removeprefix("deviant_detector_")
        try:
            with contextlib.redirect_stdout(sys.stderr):
                found = module.extract(str(repo_root))
        except (Exception, SystemExit) as error:  # one broken detector must not stop the scan
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


class _Style:
    """Wraps text in ANSI codes when colour is on, and returns it unchanged when it is off."""

    def __init__(self, on):
        self.on = on

    def _wrap(self, code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if self.on else str(text)

    def bold(self, text):
        return self._wrap("1", text)

    def dim(self, text):
        return self._wrap("2", text)

    def red(self, text):
        return self._wrap("1;31", text)

    def green(self, text):
        return self._wrap("32", text)

    def yellow(self, text):
        return self._wrap("33", text)


def should_color(mode, stream, environ=None):
    """Whether to colour output: "always", "never", or "auto" (a terminal, and NO_COLOR unset)."""
    env = os.environ if environ is None else environ
    if mode == "always":
        return True
    if mode == "never":
        return False
    return bool(stream.isatty()) and "NO_COLOR" not in env and env.get("TERM") != "dumb"


def _enable_windows_ansi():
    """Turn on ANSI escape codes in a Windows console. False if it cannot be done."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


AUTH_HINT = (
    "note: a dependency listed above may check who is calling even though its name does not "
    'say so. If one does, add its name to .deviant/config.json under "auth_words" and scan again.'
)
MAX_DEPENDENCIES_SHOWN = 6


def _format_text(rules, color=False):
    c = _Style(color)
    lines = []
    needs_hint = False
    for r in rules:
        lines.append(
            f"{c.bold(r['rule_id'])}  {c.dim('n=')}{r['n']} {c.dim('s=')}{c.green(r['s'])} "
            f"{c.dim('v=')}{c.yellow(r['v'])} {c.dim('wlb95=')}{r['wlb95']:.3f}"
        )
        lines.append(f"  {r['statement']}")
        for e in r["exceptions"]:
            where = c.red(f"{e['file']}:{e['line']}")
            lines.append(f"  {c.dim('exception:')} {where} ({e['item_id']})")
            deps = e.get("dependencies")
            if deps:
                shown = ", ".join(deps[:MAX_DEPENDENCIES_SHOWN])
                more = len(deps) - MAX_DEPENDENCIES_SHOWN
                extra = f" and {more} more" if more > 0 else ""
                lines.append(f"    {c.dim('dependencies:')} {shown}{extra}")
                if r["feature"] == "has_auth":
                    needs_hint = True
            git = e.get("git")
            if git:
                if git["uncommitted"]:
                    lines.append(f"    {c.dim('last changed:')} uncommitted changes")
                else:
                    who = f" by {git['author']}" if git["author"] else ""
                    lines.append(f"    {c.dim('last changed:')} {git['commit']} {git['date']}{who}")
                lines.append(f"    {c.dim('commit:')} {git['subject']}")
                wrote = c.green(git["author_followed_rule_elsewhere"])
                checked = git["compliant_checked"]
                lines.append(
                    f"    {c.dim('same author wrote')} {wrote} {c.dim('of the')} {checked} "
                    f"{c.dim('compliant items checked')}"
                )
                if git["history_truncated"]:
                    lines.append(
                        "    "
                        + c.yellow("history truncated: shallow clone, so the author may be wrong")
                    )
                if git["intent_words"]:
                    lines.append(f"    {c.dim('intent words:')} {', '.join(git['intent_words'])}")
    if needs_hint:
        lines.append("")
        lines.append(c.dim(AUTH_HINT))
    return "\n".join(lines)


def _hidden_note(count):
    plural = count != 1
    return (
        f"{count} style-only finding{'s' if plural else ''} hidden (a missing response model). "
        f"Add --include-style to show {'them' if plural else 'it'}."
    )


def run(
    repo_root,
    detectors_dir,
    min_items,
    min_confidence,
    as_json,
    with_git=False,
    color=False,
    include_style=False,
    with_inventory=False,
    fail_on_findings=False,
):
    if not Path(repo_root).is_dir():
        print(f"error: {repo_root} is not a directory", file=sys.stderr)
        return 2
    modules = load_detectors(Path(detectors_dir))
    items = _collect(modules, Path(repo_root))
    hide = frozenset() if include_style else style_features(modules)
    rules = mine(
        items,
        min_items=min_items,
        min_confidence=min_confidence,
        repo_root=Path(repo_root) if with_git else None,
        hide=hide,
    )
    hidden = 0
    if hide:
        everything = mine(items, min_items=min_items, min_confidence=min_confidence)
        hidden = sum(
            len(r["exceptions"])
            for r in everything
            if (r["rule_id"].split(".", 1)[0], r["feature"]) in hide
        )
    rules = _bounded(rules)
    survey = _bounded(inventory(items, hide)) if with_inventory else None
    if as_json:
        payload = {"version": 1, "rules": rules, "style_hidden": hidden}
        if survey is not None:
            payload["inventory"] = survey
        print(json.dumps(payload, indent=2))
    elif not rules:
        needed = next(
            (
                n
                for n in range(max(min_items, 2), 2000)
                if passes_filter(n - 1, n, 1, min_confidence)
            ),
            None,
        )
        reach = (
            f"one exception needs about {needed} at {min_confidence:.2f} confidence."
            if needed
            else f"no group size gives {min_confidence:.2f} confidence with an exception."
        )
        print(
            "no rules found. Groups may be too small: a group needs at least "
            f"{min_items} similar items, and {reach}"
        )
    else:
        print(_format_text(_printable(rules), color=color))
    if hidden and not as_json:
        print(("\n" if rules else "") + _hidden_note(hidden))
    if survey is not None and not as_json:
        print("\n" + _format_inventory(_printable(survey)))
    # Leads from --inventory are places to look, not findings, so only rules count here.
    return 1 if fail_on_findings and rules else 0


# Text printed to a terminal comes from a scanned project: route paths, file names, job ids,
# dependency names and commit subjects. Control and bidirectional characters in them could
# recolour the screen, rewrite earlier lines or forge report lines, so the text output shows
# them as escapes. JSON output needs nothing: json.dumps already escapes them.
_UNSAFE_RANGES = ((0x00, 0x1F), (0x7F, 0x9F), (0x2028, 0x2029), (0x202A, 0x202E), (0x2066, 0x2069))
_UNSAFE = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _UNSAFE_RANGES) + "]")


# Strings copied from a scanned project (a route path, a dependency name, a commit subject)
# have no length limit of their own. One very long value would be repeated in several places
# in the output and flood whatever reads it, so every string is cut to this length.
MAX_OUTPUT_STRING = 500


def _bounded(value):
    """A copy of value with every string longer than MAX_OUTPUT_STRING cut and marked."""
    if isinstance(value, str):
        if len(value) <= MAX_OUTPUT_STRING:
            return value
        return value[: MAX_OUTPUT_STRING - 3] + "..."
    if isinstance(value, list):
        return [_bounded(v) for v in value]
    if isinstance(value, dict):
        return {k: _bounded(v) for k, v in value.items()}
    return value


def _printable(value):
    """A copy of value, with control and bidirectional characters in every string escaped."""
    if isinstance(value, str):

        def escape(match):
            code = ord(match.group())
            return chr(92) + (f"x{code:02x}" if code < 0x100 else f"u{code:04x}")

        return _UNSAFE.sub(escape, value)
    if isinstance(value, list):
        return [_printable(v) for v in value]
    if isinstance(value, dict):
        return {k: _printable(v) for k, v in value.items()}
    return value


def _format_inventory(survey) -> str:
    """Plain text for --inventory: one line per candidate, then the items that lack the feature."""
    lines = [f"inventory: {survey['group_count']} group(s), leads to read, not findings"]
    for c in survey["candidates"]:
        lines.append(
            f"{c['detector']}.{c['peer_group']}.{c['feature']}  "
            f"{c['have']} of {c['n']} have it, {c['lack']} lack it"
        )
        for item in c["items"]:
            lines.append(f"  lacks: {item['file']}:{item['line']} ({item['item_id']})")
    if not survey["candidates"]:
        lines.append("no group has a feature that most of it has and a few items lack")
    if survey["truncated"]:
        lines.append(f"{survey['truncated']} more item(s) not listed")
    return "\n".join(lines)


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


def _version():
    """The installed version, or a note that this is a source checkout."""
    try:
        from importlib.metadata import PackageNotFoundError, version

        return version("deviant-scan")
    except PackageNotFoundError:
        return "0.0.0 (running from source)"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="deviant-scan", description="Find rules that similar items follow."
    )
    parser.add_argument("path", nargs="?", help="project folder to scan (default: the current one)")
    parser.add_argument("--repo", default=None, help="the same as the path argument")
    parser.add_argument("--version", action="version", version=f"deviant-scan {_version()}")
    parser.add_argument("--min-items", type=_positive_int, default=DEFAULT_MIN_ITEMS)
    parser.add_argument("--min-confidence", type=_fraction, default=DEFAULT_MIN_CONFIDENCE)
    parser.add_argument("--json", action="store_true", help="print JSON")
    parser.add_argument(
        "--color",
        choices=["auto", "always", "never"],
        default="auto",
        help="colour the text output (default: auto, on for a terminal; NO_COLOR turns it off)",
    )
    parser.add_argument(
        "--with-git", action="store_true", help="add the git history of each exception"
    )
    parser.add_argument(
        "--include-style",
        action="store_true",
        help="also report style-only findings, such as a route with no response model",
    )
    parser.add_argument(
        "--inventory",
        action="store_true",
        help=(
            "also list every peer group and the items that lack something most of their peers "
            "have. These are leads to read, not findings: no size floor or confidence bound applies"
        ),
    )
    parser.add_argument(
        "--fail-on-findings",
        action="store_true",
        help=(
            "exit with status 1 when the scan reports a finding, so a CI job can fail on it. "
            "Leads from --inventory do not count. Without this flag the exit status is 0"
        ),
    )
    args = parser.parse_args(argv)
    if args.path and args.repo and args.path != args.repo:
        parser.error("give the folder once: as a path or with --repo, not both")
    # An explicit empty --repo is an error, not a request to scan the current folder.
    if args.repo == "" or args.path == "":
        parser.error("the folder to scan cannot be empty")
    repo = args.repo if args.repo is not None else (args.path if args.path is not None else ".")
    # Commit subjects and author names can hold any character. A Windows console that
    # cannot print them must not crash the scan, so replace what it cannot show.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    color = not args.json and should_color(args.color, sys.stdout)
    if color and args.color == "auto" and not _enable_windows_ansi():
        color = False
    try:
        return run(
            repo,
            DETECTORS_DIR,
            args.min_items,
            args.min_confidence,
            args.json,
            with_git=args.with_git,
            include_style=args.include_style,
            with_inventory=args.inventory,
            fail_on_findings=args.fail_on_findings,
            color=color,
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
