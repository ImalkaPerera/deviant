import json
from pathlib import Path

from mine import DETECTORS_DIR, run


def write_routes_repo(root: Path, total: int, missing_auth: int) -> None:
    """A FastAPI repo with `total` mutating routes; the first `missing_auth` have no auth."""
    routes = root / "app" / "routes"
    routes.mkdir(parents=True)
    lines = ["from fastapi import APIRouter, Depends", "from app.auth import get_current_user", ""]
    lines.append("router = APIRouter()")
    for i in range(total):
        lines.append("")
        lines.append("")
        lines.append(f'@router.post("/items/{i}")')
        if i < missing_auth:
            lines.append(f"def create_{i}():")
        else:
            lines.append(f"def create_{i}(user=Depends(get_current_user)):")
        lines.append("    return {}")
    (routes / "items.py").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_47_of_48_routes_with_auth_reports_the_missing_one(tmp_path: Path, capsys):
    write_routes_repo(tmp_path, total=48, missing_auth=1)
    code = run(tmp_path, DETECTORS_DIR, min_items=20, min_confidence=0.80, as_json=True)
    rules = json.loads(capsys.readouterr().out)["rules"]
    assert code == 0
    auth_rules = [r for r in rules if "has_auth" in r["rule_id"]]
    assert len(auth_rules) == 1
    rule = auth_rules[0]
    assert (rule["n"], rule["s"], rule["v"]) == (48, 47, 1)
    assert rule["exceptions"][0]["item_id"] == "POST /items/0"
    assert rule["exceptions"][0]["file"] == "app/routes/items.py"


def test_19_of_20_routes_with_auth_reports_nothing(tmp_path: Path, capsys):
    write_routes_repo(tmp_path, total=20, missing_auth=1)
    run(tmp_path, DETECTORS_DIR, min_items=20, min_confidence=0.80, as_json=True)
    assert json.loads(capsys.readouterr().out)["rules"] == []
