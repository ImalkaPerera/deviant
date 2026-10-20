"""Regression tests: a detector cannot end or corrupt the scan, and skipped files are reported.

Each test reproduces a problem from the deep edge-case run and checks the fix.
"""

import textwrap
from pathlib import Path

from deviant_scan import mine
from deviant_scan.detectors import github_actions as gha

GOOD_DETECTOR = """\
def extract(repo_root):
    return [{
        "detector": "good",
        "peer_group": "g",
        "item_id": "x",
        "file": "f.py",
        "line": 1,
        "features": {"has_x": True},
    }]
"""


def make_detectors(folder: Path, **detectors: str) -> Path:
    """Write a detectors folder holding a good detector plus the given detector sources."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "good.py").write_text(GOOD_DETECTOR, encoding="utf-8")
    for name, source in detectors.items():
        (folder / f"{name}.py").write_text(textwrap.dedent(source), encoding="utf-8")
    return folder


def write(root: Path, relative: str, content: bytes | str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


# --- A detector that calls sys.exit must not end the scan ---------------------------


def test_detector_calling_sys_exit_is_skipped_and_scan_continues(tmp_path, capsys):
    folder = make_detectors(
        tmp_path / "detectors",
        bad="""\
        import sys
        def extract(repo_root):
            sys.exit(3)
        """,
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    items = mine.collect_items(repo, folder)  # must not raise SystemExit

    assert [i["detector"] for i in items] == ["good"]
    assert "detector bad failed" in capsys.readouterr().err


def test_detector_that_exits_on_import_is_skipped(tmp_path, capsys):
    folder = make_detectors(
        tmp_path / "detectors",
        bad="""\
        import sys
        sys.exit(4)
        """,
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    loaded = mine.load_detectors(folder)

    assert [m.__name__ for m in loaded] == ["deviant_detector_good"]
    assert "could not load detector bad.py" in capsys.readouterr().err


# --- A detector's print() must not corrupt the report ------------------------------


def test_detector_print_goes_to_stderr_not_stdout(tmp_path, capsys):
    folder = make_detectors(
        tmp_path / "detectors",
        noisy="""\
        def extract(repo_root):
            print("debug: scanning")
            return []
        """,
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    mine.collect_items(repo, folder)

    captured = capsys.readouterr()
    assert "debug: scanning" not in captured.out
    assert "debug: scanning" in captured.err


# --- A malformed context must not crash the scan ------------------------------------


def _detector_returning(context_expr: str) -> str:
    return f"""\
    def extract(repo_root):
        return [{{
            "detector": "bad",
            "peer_group": "g",
            "item_id": "y",
            "file": "f.py",
            "line": 1,
            "features": {{"has_x": False}},
            "context": {context_expr},
        }}]
    """


def test_non_dict_context_skips_only_that_detector(tmp_path, capsys):
    folder = make_detectors(tmp_path / "detectors", bad=_detector_returning('"just text"'))
    repo = tmp_path / "repo"
    repo.mkdir()

    items = mine.collect_items(repo, folder)  # used to raise AttributeError later

    assert [i["detector"] for i in items] == ["good"]
    assert "context must be a dict or None" in capsys.readouterr().err


def test_string_dependencies_are_rejected_not_split_into_characters(tmp_path, capsys):
    folder = make_detectors(
        tmp_path / "detectors",
        bad=_detector_returning('{"dependencies": "get_user"}'),
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    items = mine.collect_items(repo, folder)

    assert [i["detector"] for i in items] == ["good"]
    assert "dependencies must be a list of strings" in capsys.readouterr().err


def test_valid_context_is_still_accepted(tmp_path):
    folder = make_detectors(
        tmp_path / "detectors",
        ok=_detector_returning('{"dependencies": ["get_user"]}'),
    )
    repo = tmp_path / "repo"
    repo.mkdir()

    detectors = {i["detector"] for i in mine.collect_items(repo, folder)}

    assert detectors == {"good", "bad"}


# --- Files that the GitHub Actions detector skips must say so ----------------------


def test_unparseable_workflow_is_reported_not_silently_dropped(tmp_path, capsys):
    # A tab inside a plain value is invalid YAML 1.1, so PyYAML rejects the whole file.
    write(tmp_path, ".github/workflows/bad.yml", "on: push\njobs:\n  b:\n    run: echo\ta\n")
    write(
        tmp_path,
        ".github/workflows/good.yml",
        "on: push\njobs:\n  b:\n    runs-on: ubuntu-latest\n    timeout-minutes: 5\n",
    )

    items = gha.extract(str(tmp_path))

    assert ".github/workflows/good.yml" in {i["file"] for i in items}
    err = capsys.readouterr().err
    assert "bad.yml could not be parsed" in err
    assert "and was skipped" in err


def test_oversized_workflow_is_reported(tmp_path, capsys):
    padding = b"# " + b"x" * (gha.MAX_BYTES + 1)
    write(tmp_path, ".github/workflows/huge.yml", padding)

    gha.extract(str(tmp_path))

    assert "huge.yml is larger than" in capsys.readouterr().err


def test_oversized_python_file_is_reported(tmp_path, capsys):
    from deviant_scan.detectors import python_routes as pr

    write(tmp_path, "big.py", b"# " + b"x" * (pr.MAX_BYTES + 1))

    pr.extract(str(tmp_path))

    assert "big.py is larger than" in capsys.readouterr().err
