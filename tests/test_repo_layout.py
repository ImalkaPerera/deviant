from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_skill_folder_exists():
    assert (ROOT / "skills" / "deviant").is_dir()


def test_plugin_hooks_folder_exists():
    assert (ROOT / "hooks").is_dir()
