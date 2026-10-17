"""The detectors must never crash on damaged input, only report less."""

import random
from pathlib import Path

from deviant_scan.detectors import github_actions as gha
from deviant_scan.detectors import python_routes as pr

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SEED = 20261017


def damaged_versions(data: bytes):
    """Truncations at many points, random byte changes, and random deleted chunks."""
    rng = random.Random(SEED)
    for cut in range(0, len(data), max(1, len(data) // 10)):
        yield data[:cut]
    for _ in range(8):
        mutated = bytearray(data)
        for _ in range(rng.randint(1, 8)):
            if mutated:
                mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        yield bytes(mutated)
    for _ in range(4):
        if len(data) > 4:
            start = rng.randrange(len(data) - 2)
            yield data[:start] + data[start + rng.randint(1, 20) :]


def test_damaged_python_sources_never_crash_the_routes_detector(tmp_path, capsys):
    sources = sorted((FIXTURES / "python_routes").rglob("*.py"))
    assert len(sources) > 10
    for number, source in enumerate(sources):
        for version, data in enumerate(damaged_versions(source.read_bytes())):
            folder = tmp_path / f"{number}_{version}"
            folder.mkdir()
            (folder / "module.py").write_bytes(data)
            items = pr.extract(str(folder))
            assert isinstance(items, list)
    capsys.readouterr()  # the parse warnings are expected here


def test_damaged_python_projects_never_crash_across_files(tmp_path, capsys):
    """Damage one file of a multi-file project and scan the whole project."""
    project = FIXTURES / "python_routes" / "nested_routers"
    originals = {p: p.read_bytes() for p in project.rglob("*.py")}
    rng = random.Random(SEED)
    for round_number in range(20):
        folder = tmp_path / f"round{round_number}"
        victim = rng.choice(sorted(originals))
        for path, data in originals.items():
            target = folder / path.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path == victim:
                data = data[: rng.randrange(len(data) + 1)]
            target.write_bytes(data)
        assert isinstance(pr.extract(str(folder)), list)
    capsys.readouterr()


def test_damaged_workflows_never_crash_the_actions_detector(tmp_path):
    sources = sorted((FIXTURES / "github_actions").rglob("*.y*ml"))
    assert sources
    for number, source in enumerate(sources):
        for version, data in enumerate(damaged_versions(source.read_bytes())):
            folder = tmp_path / f"{number}_{version}" / ".github" / "workflows"
            folder.mkdir(parents=True)
            (folder / "w.yml").write_bytes(data)
            assert isinstance(gha.extract(str(folder.parent.parent)), list)


def test_every_item_a_detector_returns_is_valid_even_for_damaged_input(tmp_path, capsys):
    from deviant_scan.mine import validate_items

    sources = sorted((FIXTURES / "python_routes").rglob("*.py"))
    for number, source in enumerate(sources):
        for version, data in enumerate(damaged_versions(source.read_bytes())):
            folder = tmp_path / f"{number}_{version}"
            folder.mkdir()
            (folder / "module.py").write_bytes(data)
            validate_items(pr.extract(str(folder)))
    capsys.readouterr()
