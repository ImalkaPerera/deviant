"""Run the audit prompt on planted copies with Claude, one condition at a time.

Usage: python run_benchmark.py <planted dir> <results dir> <condition> [runs] [repo filter]

<planted dir>   the output of plant.py (one folder per repo, plus manifest.json)
<results dir>   receives one JSON file per run, named <condition>/<repo>_run<N>.json
<condition>     A: Claude alone with the audit prompt
                B: Claude with the Deviant skill loaded, same prompt
                C: Claude alone, told to write its own counting script first

Every run uses the same model. Runs are read-only apart from scratch scripts that condition C
writes into the planted copy, which is itself a scratch folder.
"""

import json
import subprocess
import sys
from pathlib import Path

MODEL = "claude-haiku-5-5"
AUDIT = (
    "Audit this repository for places where almost every similar item follows a pattern, but "
    "one or two items break it. Focus on API routes and GitHub Actions workflows. For each "
    "likely bug, give the file, line, and your reason."
)
COUNTING = (
    " Before you answer, write a short Python script that groups similar items (API routes, "
    "GitHub Actions jobs and steps) and counts how many follow each pattern. Run it and use its "
    "output in your answer."
)
PLUGIN_DIR = Path(__file__).resolve().parent.parent
CONDITIONS = {
    "A": {"prompt": AUDIT, "tools": "Read,Grep,Glob", "extra": []},
    "B": {
        "prompt": "/deviant:deviant " + AUDIT,
        "tools": "Read,Grep,Glob,Bash",
        "extra": ["--plugin-dir", str(PLUGIN_DIR)],
    },
    "C": {"prompt": AUDIT + COUNTING, "tools": "Read,Grep,Glob,Write,Bash", "extra": []},
}


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    planted, results, condition = Path(argv[1]), Path(argv[2]), argv[3]
    runs = int(argv[4]) if len(argv) > 4 else 3
    only = argv[5] if len(argv) > 5 else None
    spec = CONDITIONS[condition]
    out_dir = results / condition
    out_dir.mkdir(parents=True, exist_ok=True)
    repos = sorted(p for p in planted.iterdir() if p.is_dir())
    for repo in repos:
        if only and only not in repo.name:
            continue
        for n in range(1, runs + 1):
            target = out_dir / f"{repo.name}_run{n}.json"
            if target.exists():
                continue
            cmd = [
                "claude",
                "-p",
                spec["prompt"],
                "--model",
                MODEL,
                "--allowedTools",
                spec["tools"],
                "--output-format",
                "json",
                *spec["extra"],
            ]
            proc = subprocess.run(
                cmd,
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=1800,
            )
            record = {"repo": repo.name, "condition": condition, "run": n, "exit": proc.returncode}
            try:
                record.update(json.loads(proc.stdout))
            except ValueError:
                record["raw_stdout"] = proc.stdout[-2000:]
                record["stderr"] = proc.stderr[-2000:]
            target.write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"{condition} {repo.name} run {n}: exit {proc.returncode}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
