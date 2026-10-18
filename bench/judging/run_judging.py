"""Ask Claude to judge the flagged route in each constructed case.

Usage: python run_judging.py <cases dir> <results dir> <condition> [runs] [case id filter]

<condition>  skill: the Deviant skill runs its own scan and judges what it finds
             alone: Claude is told which route was flagged and that 57 of 58 routes in its
                    folder have auth, then searches the code, tests and git history itself

Both use the same model. One JSON file per run, <results>/<condition>/<case>_run<N>.json.
Existing files are skipped, so a stopped run can be resumed.
"""

import json
import subprocess
import sys
from pathlib import Path

MODEL = "claude-haiku-5-5"
PLUGIN_DIR = "e:/deviant"
ALONE = (
    "A scan of this repository flagged the route {route} in {file}. Every other route in its "
    "folder has an auth dependency (57 of 58 do) and this one does not. Decide whether it is a "
    "BUG (it should have the auth), INTENTIONAL (it is public on purpose) or UNSURE. Search the "
    "code, the tests and the git history for evidence. Do not change any files. Reply with one "
    "line, 'LABEL: BUG', 'LABEL: INTENTIONAL' or 'LABEL: UNSURE', then one sentence of proof."
)
CONDITIONS = {
    "skill": {"tools": "Read,Grep,Glob,Bash", "extra": ["--plugin-dir", PLUGIN_DIR]},
    "alone": {"tools": "Read,Grep,Glob,Bash", "extra": []},
}


def prompt_for(condition, case):
    if condition == "skill":
        return "/deviant:deviant"
    return ALONE.format(route=case["route"], file=case["file"])


def main(argv):
    if len(argv) not in (4, 5, 6):
        print(__doc__)
        return 2
    cases_dir, results, condition = Path(argv[1]), Path(argv[2]), argv[3]
    runs = int(argv[4]) if len(argv) >= 5 else 3
    only = argv[5] if len(argv) == 6 else None
    spec = CONDITIONS[condition]
    out_dir = results / condition
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = json.loads((cases_dir / "cases.json").read_text(encoding="utf-8"))
    for case in cases:
        if only and only not in case["id"]:
            continue
        for n in range(1, runs + 1):
            target = out_dir / f"{case['id']}_run{n}.json"
            if target.exists():
                continue
            cmd = [
                "claude", "-p", prompt_for(condition, case), "--model", MODEL,
                "--allowedTools", spec["tools"], "--output-format", "json", *spec["extra"],
            ]  # fmt: skip
            proc = subprocess.run(
                cmd, cwd=case["dir"], capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=900,
            )  # fmt: skip
            record = {"case": case["id"], "condition": condition, "run": n, "exit": proc.returncode}
            try:
                record.update(json.loads(proc.stdout))
            except ValueError:
                record["raw_stdout"] = proc.stdout[-2000:]
                record["stderr"] = proc.stderr[-2000:]
            target.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{condition} {case['id']} run {n}: exit {proc.returncode}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
