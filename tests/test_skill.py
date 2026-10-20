"""The Claude Code skill and plugin files must stay in step with the scanner they drive.

These tests need no AI. They check the files that Claude reads: that they parse, that the
command they tell Claude to run really works, and that the output fields they describe exist.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "deviant"
SKILL = SKILL_DIR / "SKILL.md"
SCANNER = SKILL_DIR / "scripts" / "mine.py"

# The fields Claude Code documents for SKILL.md. An unknown one is silently ignored there,
# so a typo would never show up as an error.
KNOWN_FRONTMATTER = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "background",
    "hooks",
    "paths",
    "shell",
    "metadata",
    "license",
    "compatibility",
}


def read_skill():
    text = SKILL.read_text(encoding="utf-8")
    assert text.startswith("---\n"), "frontmatter must start on the first line"
    _, front, body = text.split("---\n", 2)
    return yaml.safe_load(front), body, text


# --- the skill file -----------------------------------------------------------------------


def test_frontmatter_uses_only_documented_fields():
    front, _, _ = read_skill()
    assert set(front) <= KNOWN_FRONTMATTER, set(front) - KNOWN_FRONTMATTER


def test_name_matches_the_folder_and_is_a_valid_command_name():
    front, _, _ = read_skill()
    assert front["name"] == SKILL_DIR.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", front["name"])


def test_description_says_what_it_does_and_fits_the_listing_limit():
    front, _, _ = read_skill()
    combined = front["description"] + front.get("when_to_use", "")
    assert len(combined) <= 1536  # Claude Code truncates the listing beyond this
    assert "BUG" in front["description"] and "UNSURE" in front["description"]


def test_skill_is_short_enough_to_stay_in_context():
    assert len(SKILL.read_text(encoding="utf-8").splitlines()) < 500


def test_pre_approval_matches_the_scanner_path():
    front, _, _ = read_skill()
    assert "${CLAUDE_SKILL_DIR}/scripts/mine.py" in front["allowed-tools"]
    assert SCANNER.is_file()


def test_every_relative_link_in_the_skill_exists():
    _, body, _ = read_skill()
    links = re.findall(r"\]\((?!https?:)([^)#]+)", body)
    assert links, "the skill should point at its reference file"
    for link in links:
        assert (SKILL_DIR / link).is_file(), link


# --- the command the skill tells Claude to run --------------------------------------------


def skill_commands():
    """The strict scan, then the relaxed scan the skill falls back to."""
    _, body, _ = read_skill()
    blocks = re.findall(r"```bash\n(.*?)```", body, flags=re.DOTALL)
    commands = [b.strip() for b in blocks if "mine.py" in b]
    assert len(commands) == 2
    return commands


def skill_command():
    return skill_commands()[0]


def test_every_command_is_in_the_exact_form_that_is_pre_approved():
    # A real run showed that quotes around the script path or a trailing 2>&1 stop the
    # pre-approval from matching, which makes Claude ask the user for permission.
    for command in skill_commands():
        assert '"' not in command and "'" not in command
        assert "2>" not in command and " > " not in command and " >> " not in command
        assert command.startswith("python3 ${CLAUDE_SKILL_DIR}/scripts/mine.py ")


def test_the_relaxed_command_is_the_strict_one_plus_lower_limits():
    strict, relaxed = skill_commands()
    # Only the first scan asks for the inventory, so the relaxed one does not repeat it.
    assert "--inventory" in strict and "--inventory" not in relaxed
    assert relaxed.startswith(strict.replace(" --inventory", ""))
    assert "--min-items" in relaxed and "--min-confidence" in relaxed


def make_project(root: Path, routes: int = 30) -> Path:
    (root / "app").mkdir(parents=True)
    for i in range(routes):
        body = "def h(u=Depends(get_current_user)):" if i != 7 else "def h():"
        (root / "app" / f"r{i}.py").write_text(
            "from fastapi import APIRouter, Depends\nrouter = APIRouter()\n\n\n"
            f"@router.post('/r{i}')\n{body}\n    return {{}}\n",
            encoding="utf-8",
        )
    env = {"GIT_AUTHOR_NAME": "Dana", "GIT_AUTHOR_EMAIL": "dana@example.com"}
    env.update(GIT_COMMITTER_NAME="Dana", GIT_COMMITTER_EMAIL="dana@example.com")
    import os

    full = {**os.environ, **env}
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "add routes"]):
        subprocess.run(["git", "-C", str(root), *args], check=True, env=full, capture_output=True)
    return root


def scan_with_the_skills_command(project: Path, which: int = 0) -> dict:
    command = skill_commands()[which].replace(
        "${CLAUDE_SKILL_DIR}", str(SKILL_DIR).replace("\\", "/")
    )
    command = command.replace("<target>", str(project).replace("\\", "/"))
    argv = command.split()
    argv[0] = sys.executable  # "python3" is not always on the path; the arguments are the point
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_running_the_skills_command_gives_json_with_the_fields_it_describes(tmp_path):
    data = scan_with_the_skills_command(make_project(tmp_path / "p"))
    (rule,) = data["rules"]
    assert {"statement", "n", "s", "v", "wlb95", "exceptions", "compliant_examples"} <= set(rule)
    (exception,) = rule["exceptions"]
    assert {"item_id", "file", "line", "git"} <= set(exception)
    assert {
        "commit",
        "author",
        "date",
        "subject",
        "files_in_commit",
        "author_followed_rule_elsewhere",
        "compliant_checked",
        "intent_words",
        "history_truncated",
        "uncommitted",
    } <= set(exception["git"])


def test_the_skill_describes_every_field_it_relies_on():
    _, body, _ = read_skill()
    for field in (
        "statement", "wlb95", "exceptions", "compliant_examples", "item_id", "file", "line",
        "commit", "author", "date", "subject", "files_in_commit",
        "author_followed_rule_elsewhere", "compliant_checked", "intent_words",
        "history_truncated", "uncommitted",
    ):  # fmt: skip
        assert f"`{field}`" in body, field


def test_every_flag_the_skill_mentions_exists_in_the_scanner():
    _, body, _ = read_skill()
    help_text = subprocess.run(
        [sys.executable, str(SCANNER), "--help"], capture_output=True, text=True
    ).stdout
    flags = set(re.findall(r"`(--[a-z-]+)`", body))
    for command in skill_commands():
        flags |= set(re.findall(r" (--[a-z-]+)", command))
    for flag in flags:
        assert flag in help_text, flag


def test_a_small_group_is_found_by_the_relaxed_command_but_not_the_strict_one(tmp_path):
    project = make_project(tmp_path / "p", routes=12)
    assert scan_with_the_skills_command(project, which=0)["rules"] == []
    (rule,) = scan_with_the_skills_command(project, which=1)["rules"]
    assert (rule["n"], rule["v"]) == (12, 1)


def test_the_stderr_messages_the_skill_tells_claude_to_expect_are_real():
    _, body, _ = read_skill()
    sources = "".join(
        p.read_text(encoding="utf-8")
        for p in [SCANNER, *SKILL_DIR.joinpath("scripts").rglob("*.py")]
    )
    for phrase in ("could not parse", "PyYAML is not installed", "no git evidence added"):
        assert phrase in body
        assert phrase in sources


# --- the plugin and marketplace manifests -------------------------------------------------


def load(name):
    return json.loads((ROOT / ".claude-plugin" / name).read_text(encoding="utf-8"))


def test_plugin_name_is_kebab_case_and_not_reserved():
    name = load("plugin.json")["name"]
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name)
    reserved = ("claude-", "anthropic-", "anthropics-", "cc-plugin-")
    assert not name.startswith(reserved)
    assert name not in {"claude", "anthropic", "anthropics", "claude-code", "claude-mods"}


def test_plugin_version_matches_the_package_version():
    # Read the version with a pattern: tomllib only exists from Python 3.11, and 3.10 is supported.
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, flags=re.MULTILINE)
    assert match, "pyproject.toml has no version"
    assert load("plugin.json")["version"] == match.group(1)


def test_marketplace_lists_the_plugin_with_the_same_name():
    plugin, market = load("plugin.json"), load("marketplace.json")
    assert market["owner"]["name"]
    (entry,) = market["plugins"]
    assert entry["name"] == plugin["name"]  # a mismatch breaks installing by name
    assert entry["source"].startswith("./")


def test_the_plugin_ships_the_skill_in_the_standard_place():
    assert (ROOT / "skills" / load("plugin.json")["name"] / "SKILL.md").is_file()


@pytest.mark.skipif(shutil.which("claude") is None, reason="the claude command is not installed")
def test_the_official_validator_accepts_the_plugin_and_marketplace():
    result = subprocess.run(
        ["claude", "plugin", "validate", str(ROOT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Validation passed" in result.stdout
