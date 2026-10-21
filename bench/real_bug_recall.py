"""Check whether the scanner alone points at each real bug in bench/real_bugs.json.

Usage: python real_bug_recall.py <work dir>

For each bug it fetches the commit just before the fix (the parent commit), scans that
snapshot with no AI, and says whether the bug's line appears as a strict finding (STRICT),
as an inventory lead (LEAD), as an item the scan saw but did not surface (ITEM-NO-LEAD), or
not at all (NOT-SEEN). Snapshots are cached in <work dir>/snapshots, so a rerun is quick.

The bugs are fixes from public history, so nobody planted them and nobody chose them with the
scanner in mind. They were verified by reading each fix. See real_bugs.json.

A bug can only be a deviation if some of its peers have the protection. Where every similar item
lacks it (a whole router with no auth), the scanner has nothing to compare with and reports
nothing, by design.
"""

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "skills" / "deviant" / "scripts"))

from deviant_scan import mine  # noqa: E402

BUGS = Path(__file__).resolve().parent / "real_bugs.json"
FEATURE = {
    "auth": "has_auth",
    "timeout": "has_timeout_minutes",
    "permissions": "has_permissions_block",
    "pin": "pinned_to_sha",
}
# How far from the recorded line an item may be and still count as the bug's own.
WINDOW = {"auth": 6, "timeout": 1, "pin": 1}


def snapshot_name(bug):
    suffix = "_a" if bug["kind"] == "auth" else "_g"
    return bug["repo"].replace("/", "__") + "@" + bug["parent_commit"][:10] + suffix


def export(bug, snapshots):
    """The files of the commit before the fix: the whole tree for auth, .github for the rest."""
    dest = snapshots / snapshot_name(bug)
    if dest.exists() and any(dest.iterdir()):
        return dest
    work = Path(tempfile.mkdtemp())
    try:
        url = f"https://github.com/{bug['repo']}.git"
        subprocess.run(["git", "init", "-q", str(work)], check=True)
        subprocess.run(["git", "-C", str(work), "remote", "add", "origin", url], check=True)
        fetch = ["git", "-C", str(work), "fetch", "-q", "--depth", "1"]
        if bug["kind"] != "auth":
            fetch.append("--filter=blob:none")  # only .github is read, so skip the other files
        subprocess.run([*fetch, "origin", bug["parent_commit"]], check=True, timeout=900)
        archive = ["git", "-C", str(work), "archive", "FETCH_HEAD"]
        if bug["kind"] != "auth":
            archive += ["--", ".github"]
        dest.mkdir(parents=True, exist_ok=True)
        proc = subprocess.Popen(archive, stdout=subprocess.PIPE)
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if member.issym() or member.islnk():
                    continue
                try:
                    tar.extract(member, dest, filter="data")
                except (OSError, tarfile.TarError):
                    pass
        proc.wait()
    except (subprocess.SubprocessError, OSError, tarfile.TarError) as error:
        print(f"  could not fetch {snapshot_name(bug)}: {type(error).__name__}", file=sys.stderr)
        shutil.rmtree(dest, ignore_errors=True)
        return None
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest


def status(bug, items, rules, survey):
    feature = FEATURE[bug["kind"]]
    window = WINDOW.get(bug["kind"])

    def is_the_bug(entry_file, entry_line):
        if entry_file != bug["file"]:
            return False
        # A workflow-level item sits at line 1, so only the file can be compared.
        return window is None or abs(entry_line - bug["parent_line"]) <= window

    if any(
        is_the_bug(e["file"], e["line"])
        for r in rules
        if r["feature"] == feature
        for e in r["exceptions"]
    ):
        return "STRICT"
    if any(
        is_the_bug(i["file"], i["line"])
        for c in survey["candidates"]
        if c["feature"] == feature
        for i in c["items"]
    ):
        return "LEAD"
    if any(is_the_bug(i["file"], i["line"]) and i["features"].get(feature) is False for i in items):
        return "ITEM-NO-LEAD"
    return "NOT-SEEN"


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 2
    snapshots = Path(argv[1]) / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    bugs = json.loads(BUGS.read_text(encoding="utf-8"))["bugs"]
    scanned = {}
    results = []
    for bug in bugs:
        snap = export(bug, snapshots)
        if snap is None:
            results.append((bug["id"], bug["kind"], "NO-SNAPSHOT"))
            continue
        if snap not in scanned:
            items = mine.collect_items(snap, mine.DETECTORS_DIR)
            scanned[snap] = (
                items,
                mine.mine(items),
                mine.inventory(items, limit=100_000),
            )
        items, rules, survey = scanned[snap]
        result = status(bug, items, rules, survey)
        results.append((bug["id"], bug["kind"], result))
        print(f"{bug['id']} {bug['kind']:12s} {bug['repo']:34s} {result}", flush=True)
    print()
    for kind in FEATURE:
        counts = Counter(r[2] for r in results if r[1] == kind)
        print(f"{kind:12s} {dict(counts)}")
    total = Counter(r[2] for r in results)
    found = total["STRICT"] + total["LEAD"]
    print(f"\nreported by the scan alone: {found} of {len(results)}  {dict(total)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
