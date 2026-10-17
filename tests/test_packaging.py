"""The PyPI package must contain what the code needs, and its description must render there."""

import importlib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "skills" / "deviant" / "scripts"
PYPROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def declared_packages():
    match = re.search(r"^packages = \[(.*?)\]", PYPROJECT, flags=re.MULTILINE)
    assert match, "pyproject.toml lists no packages"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def packages_on_disk():
    found = set()
    for init in SCRIPTS.rglob("__init__.py"):
        if "__pycache__" in init.parts:
            continue
        found.add(".".join(init.parent.relative_to(SCRIPTS).parts))
    return found


def test_every_package_folder_is_listed_for_the_wheel():
    # A folder missing from this list is silently left out of the published package.
    assert declared_packages() == packages_on_disk()


def test_the_command_entry_point_resolves_to_a_callable():
    match = re.search(r'^deviant-scan = "([^"]+)"', PYPROJECT, flags=re.MULTILINE)
    assert match, "no deviant-scan entry point"
    module, _, function = match.group(1).partition(":")
    assert callable(getattr(importlib.import_module(module), function))


def test_every_detector_module_is_part_of_the_package():
    detectors = SCRIPTS / "deviant_scan" / "detectors"
    modules = {p.stem for p in detectors.glob("*.py") if not p.name.startswith("__")}
    assert {"python_routes", "github_actions"} <= modules
    for name in modules:
        importlib.import_module(f"deviant_scan.detectors.{name}")


def test_the_pypi_description_uses_only_absolute_links():
    # PyPI does not know where relative paths point, so they would show as broken images and links.
    text = (ROOT / "README-pypi.md").read_text(encoding="utf-8")
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        assert target.startswith("https://"), target


def test_the_pypi_description_file_is_the_one_the_package_declares():
    assert 'readme = "README-pypi.md"' in PYPROJECT
    assert (ROOT / "README-pypi.md").is_file()


def test_the_release_workflow_and_the_guide_agree_on_the_names_pypi_must_trust():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    guide = (ROOT / "RELEASING.md").read_text(encoding="utf-8")
    assert "environment: pypi" in workflow and "`pypi`" in guide
    assert "id-token: write" in workflow
    assert "`release.yml`" in guide
    assert "`deviant-scan`" in guide
