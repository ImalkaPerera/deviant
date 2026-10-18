"""Style-only findings are hidden by default, and an auth exception lists its dependencies."""

import json

from deviant_scan.mine import DETECTORS_DIR, mine, run


def write_routes(root, count=30, odd=7, odd_has_auth=True, odd_has_model=True):
    """A folder of routes that all have auth and a response model, except route `odd`."""
    (root / "app").mkdir(parents=True)
    for i in range(count):
        auth = "Depends(get_current_user)" if i != odd or odd_has_auth else "Depends(get_tenant)"
        model = ", response_model=Out" if i != odd or odd_has_model else ""
        (root / "app" / f"r{i}.py").write_text(
            "from fastapi import APIRouter, Depends\n"
            "router = APIRouter()\n\n\n"
            f"@router.get('/r{i}'{model})\n"
            f"def h(u={auth}):\n    return {{}}\n",
            encoding="utf-8",
        )


def scan(root, capsys, **kwargs):
    run(root, DETECTORS_DIR, 20, 0.80, False, **kwargs)
    return capsys.readouterr().out


def test_a_missing_response_model_is_hidden_and_counted_by_default(tmp_path, capsys):
    write_routes(tmp_path, odd_has_model=False)
    out = scan(tmp_path, capsys)
    assert "has_response_model" not in out
    assert "1 style-only finding hidden" in out and "--include-style" in out


def test_include_style_reports_the_missing_response_model(tmp_path, capsys):
    write_routes(tmp_path, odd_has_model=False)
    out = scan(tmp_path, capsys, include_style=True)
    assert "has_response_model" in out
    assert "hidden" not in out


def test_json_says_how_many_style_findings_were_hidden(tmp_path, capsys):
    write_routes(tmp_path, odd_has_model=False)
    run(tmp_path, DETECTORS_DIR, 20, 0.80, True)
    data = json.loads(capsys.readouterr().out)
    assert data["rules"] == [] and data["style_hidden"] == 1


def test_hidden_findings_do_not_hide_the_other_kinds(tmp_path, capsys):
    write_routes(tmp_path, odd_has_auth=False, odd_has_model=False)
    out = scan(tmp_path, capsys)
    assert "has_auth" in out and "has_response_model" not in out
    assert "1 style-only finding hidden" in out


def test_an_auth_exception_lists_its_dependencies_and_a_hint(tmp_path, capsys):
    write_routes(tmp_path, odd_has_auth=False)
    out = scan(tmp_path, capsys)
    assert "dependencies: get_tenant" in out
    assert '"auth_words"' in out


def test_json_exceptions_carry_their_dependencies(tmp_path, capsys):
    write_routes(tmp_path, odd_has_auth=False)
    run(tmp_path, DETECTORS_DIR, 20, 0.80, True)
    rules = json.loads(capsys.readouterr().out)["rules"]
    (exception,) = [e for r in rules if r["feature"] == "has_auth" for e in r["exceptions"]]
    assert exception["dependencies"] == ["get_tenant"]


def item(i, features, **extra):
    return {
        "detector": "d",
        "peer_group": "g",
        "item_id": f"i{i}",
        "file": "a.py",
        "line": i + 1,
        "features": features,
        **extra,
    }


def test_mine_leaves_out_hidden_features_only():
    items = [item(i, {"keeps": i != 3, "tidy": i != 5}) for i in range(30)]
    shown = {r["feature"] for r in mine(items)}
    hidden = {r["feature"] for r in mine(items, hide=frozenset({("d", "tidy")}))}
    assert shown == {"keeps", "tidy"} and hidden == {"keeps"}


def test_a_detector_can_mark_features_as_style_only():
    from deviant_scan.detectors import python_routes

    assert python_routes.STYLE_FEATURES == {"has_response_model"}


def test_plain_plumbing_dependencies_are_not_listed_or_hinted(tmp_path, capsys):
    (tmp_path / "app").mkdir()
    for i in range(30):
        dep = "Depends(get_current_user)" if i != 7 else "Depends(get_db)"
        (tmp_path / "app" / f"r{i}.py").write_text(
            "from fastapi import APIRouter, Depends\n"
            "router = APIRouter()\n\n\n"
            f"@router.get('/r{i}')\n"
            f"def h(u={dep}):\n    return {{}}\n",
            encoding="utf-8",
        )
    out = scan(tmp_path, capsys)
    assert "has_auth" in out
    assert "dependencies:" not in out and "auth_words" not in out
