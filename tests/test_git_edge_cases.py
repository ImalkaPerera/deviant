"""Edge cases for git evidence: unusual repositories, paths and failures."""

import os
import subprocess
from pathlib import Path

import pytest
from deviant_scan import git_forensics as gf
from deviant_scan.mine import _format_text, mine

ANN = ("Ann", "ann@example.com")


def git(repo: Path, *args: str, author=ANN) -> None:
    env = os.environ.copy()
    env.update(
        GIT_AUTHOR_NAME=author[0],
        GIT_AUTHOR_EMAIL=author[1],
        GIT_COMMITTER_NAME=author[0],
        GIT_COMMITTER_EMAIL=author[1],
    )
    subprocess.run(["git", "-C", str(repo), *args], check=True, env=env, capture_output=True)


def commit_all(repo: Path, message: str = "initial") -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    git(root, "init", "-q")
    return root


def items_for(path: str, lines, missing_line):
    return [
        {
            "detector": "d",
            "peer_group": "g",
            "item_id": f"r{line}",
            "file": path,
            "line": line,
            "features": {"has_auth": line != missing_line},
        }
        for line in lines
    ]


# --- repositories in unusual states -------------------------------------------------------


def test_a_repository_with_no_commits_gives_no_evidence_and_no_crash(tmp_path):
    root = make_repo(tmp_path)
    (root / "a.py").write_text("x = 1\ny = 2\nz = 3\n")
    evidence = gf.GitEvidence(root)
    assert evidence.available is True
    assert evidence.exception_evidence("a.py", 2, []) is None


def test_an_untracked_file_gives_no_evidence(tmp_path):
    root = make_repo(tmp_path)
    (root / "tracked.py").write_text("x = 1\n")
    commit_all(root)
    (root / "new.py").write_text("y = 2\n")
    assert gf.GitEvidence(root).exception_evidence("new.py", 1, []) is None


def test_a_line_beyond_the_end_of_the_file_gives_no_evidence(tmp_path):
    root = make_repo(tmp_path)
    (root / "a.py").write_text("x = 1\n")
    commit_all(root)
    assert gf.GitEvidence(root).exception_evidence("a.py", 99, []) is None


def test_scanning_a_subfolder_of_a_larger_repository(tmp_path):
    root = make_repo(tmp_path)
    (root / "services" / "api").mkdir(parents=True)
    (root / "services" / "api" / "routes.py").write_text("a\nb\nc\n")
    commit_all(root, "add api routes")
    evidence = gf.GitEvidence(root / "services" / "api").exception_evidence("routes.py", 2, [])
    assert evidence["subject"] == "add api routes"
    assert evidence["author"] == "ann@example.com"


def test_file_names_with_spaces_and_non_ascii_characters(tmp_path):
    root = make_repo(tmp_path)
    name = "my routes é 日本.py"
    (root / name).write_text("one\ntwo\n", encoding="utf-8")
    commit_all(root, "add odd name")
    assert gf.GitEvidence(root).exception_evidence(name, 2, [])["subject"] == "add odd name"


def test_line_numbers_are_right_in_files_with_windows_line_endings(tmp_path):
    root = make_repo(tmp_path)
    (root / "crlf.py").write_bytes(b"one\r\ntwo\r\nthree")  # no newline at the end
    commit_all(root, "crlf file")
    evidence = gf.GitEvidence(root)
    assert evidence.exception_evidence("crlf.py", 3, [])["subject"] == "crlf file"
    assert evidence.exception_evidence("crlf.py", 4, []) is None


# --- uncommitted and missing author details -----------------------------------------------


def test_an_uncommitted_line_has_no_author(tmp_path):
    root = make_repo(tmp_path)
    (root / "a.py").write_text("one\n")
    commit_all(root)
    (root / "a.py").write_text("one\ntwo\n")
    evidence = gf.GitEvidence(root).exception_evidence("a.py", 2, [])
    assert evidence["uncommitted"] is True
    assert evidence["author"] is None


def test_text_output_for_an_uncommitted_line_does_not_invent_an_author(tmp_path):
    root = make_repo(tmp_path)
    (root / "a.py").write_text("\n".join(f"line{i}" for i in range(30)) + "\n")
    commit_all(root)
    lines = (root / "a.py").read_text().splitlines()
    lines[7] = "edited"
    (root / "a.py").write_text("\n".join(lines) + "\n")
    rules = mine(
        items_for("a.py", range(1, 31), 8), min_items=1, min_confidence=0.0, repo_root=root
    )
    text = _format_text(rules)
    assert "uncommitted changes" in text
    assert "not.committed.yet" not in text
    assert "by None" not in text


def test_a_commit_with_an_empty_author_email_gives_no_author(tmp_path):
    parsed = gf._parse_blame(
        "a" * 40 + " 1 1 1\nauthor X\nauthor-mail <>\nauthor-time 0\nsummary s\n\tcode\n"
    )
    assert parsed[1]["email"] == ""
    root = make_repo(tmp_path)
    (root / "a.py").write_text("x\n")
    commit_all(root)
    evidence = gf.GitEvidence(root)
    evidence._blame["a.py"] = parsed
    assert evidence.exception_evidence("a.py", 1, [])["author"] is None


# --- git missing or slow ------------------------------------------------------------------


def test_missing_git_is_reported_once_and_the_scan_still_works(tmp_path, monkeypatch, capsys):
    def no_git(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(gf.subprocess, "run", no_git)
    rules = mine(
        items_for("a.py", range(1, 31), 8), min_items=1, min_confidence=0.0, repo_root=tmp_path
    )
    assert rules
    assert rules[0]["exceptions"][0]["git"] is None
    assert capsys.readouterr().err.count("no git evidence") == 1


def test_a_folder_that_is_not_a_repository_warns_and_continues(tmp_path, capsys):
    rules = mine(
        items_for("a.py", range(1, 31), 8), min_items=1, min_confidence=0.0, repo_root=tmp_path
    )
    assert rules
    assert "no git evidence" in capsys.readouterr().err


def test_a_slow_git_call_is_reported_and_skipped(tmp_path, monkeypatch, capsys):
    root = make_repo(tmp_path)
    (root / "a.py").write_text("x\n")
    commit_all(root)
    real_run = subprocess.run

    def slow_blame(command, **kwargs):
        if "blame" in command:
            raise subprocess.TimeoutExpired(command, 10)
        return real_run(command, **kwargs)

    monkeypatch.setattr(gf.subprocess, "run", slow_blame)
    gf._warned_timeouts.clear()
    evidence = gf.GitEvidence(root)
    assert evidence.exception_evidence("a.py", 1, []) is None
    assert evidence.exception_evidence("a.py", 1, []) is None
    assert capsys.readouterr().err.count("timed out") == 1


# --- intent words -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Public endpoint", ["public"]),
        ("publication date", []),
        ("unhealthy", []),
        ("health-check route", ["health"]),
        ("TODO: add auth later", ["todo"]),
        ("# noqa: S104", ["noqa"]),
        ("INTENTIONAL: webhook from Stripe", ["intentional", "webhook"]),
        ("metrics, login and public", ["login", "metrics", "public"]),
        ("", []),
    ],
)
def test_intent_words_match_whole_words_only(text, expected):
    assert gf._intent_words(text) == expected


def test_comments_just_above_the_line_count_as_intent(tmp_path):
    root = make_repo(tmp_path)
    (root / "a.py").write_text("x = 1\n# this route is public on purpose\n@router.get('/x')\n")
    commit_all(root, "add route")
    evidence = gf.GitEvidence(root).exception_evidence("a.py", 3, [])
    assert evidence["intent_words"] == ["public"]


def test_comments_far_above_the_line_do_not_count(tmp_path):
    root = make_repo(tmp_path)
    lines = ["# public"] + ["x = 1"] * 10 + ["@router.get('/x')"]
    (root / "a.py").write_text("\n".join(lines) + "\n")
    commit_all(root, "add route")
    assert gf.GitEvidence(root).exception_evidence("a.py", 12, [])["intent_words"] == []


# --- sampling -----------------------------------------------------------------------------


@pytest.mark.parametrize("total", [0, 1, 49, 50, 51, 100, 1000])
def test_the_compliant_sample_never_exceeds_the_limit_and_keeps_order(total):
    items = list(range(total))
    sample = gf._evenly_spaced(items, 50)
    assert len(sample) == min(total, 50)
    assert sample == sorted(sample)
    assert len(set(sample)) == len(sample)


def test_blame_never_runs_a_textconv_program_from_the_repository(tmp_path):
    root = make_repo(tmp_path)
    (root / "f.txt").write_text("x = 1\n")
    (root / ".gitattributes").write_text("f.txt diff=pwn\n")
    git(root, "config", "diff.pwn.textconv", "sh -c 'echo ran > ran.txt; cat'")
    commit_all(root)
    gf.GitEvidence(root)._blame_file("f.txt")
    assert not (root / "ran.txt").exists()


def test_a_config_file_that_is_a_symlink_is_ignored(tmp_path):
    from deviant_scan.detectors import python_routes as pr

    outside = tmp_path / "outside.json"
    outside.write_text('{"auth_words": ["secret"]}')
    root = tmp_path / "repo"
    (root / ".deviant").mkdir(parents=True)
    try:
        (root / ".deviant" / "config.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks need extra rights on this system")
    assert pr._extra_auth_words(root) == set()


def test_an_inherited_git_dir_does_not_redirect_evidence_to_another_repository(
    tmp_path, monkeypatch
):
    scanned = make_repo(tmp_path, "scanned")
    (scanned / "a.py").write_text("x = 1\ny = 2\n")
    commit_all(scanned, "scanned work")
    other = make_repo(tmp_path, "other")
    (other / "a.py").write_text("x = 1\ny = 2\n")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "other work", author=("Bob", "bob@example.com"))
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    info = gf.GitEvidence(scanned).line_author("a.py", 1)
    assert info is not None and info["email"] == ANN[1]
