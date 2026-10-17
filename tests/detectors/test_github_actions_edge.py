"""Edge cases for the GitHub Actions detector."""

import os

import pytest
from deviant_scan.detectors import github_actions as gha


def write(root, relative, content, binary=False):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if binary:
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def extract(root):
    return gha.extract(str(root))


def by_group(items, group):
    return [i for i in items if i["peer_group"] == group]


WORKFLOW = "name: w\njobs:\n  b:\n    runs-on: x\n    steps:\n      - uses: a/b@v1\n"


# --- file formats -------------------------------------------------------------------------


def test_a_byte_order_mark_does_not_hide_the_workflow(tmp_path):
    write(tmp_path, ".github/workflows/w.yml", b"\xef\xbb\xbf" + WORKFLOW.encode(), binary=True)
    assert [i["item_id"] for i in by_group(extract(tmp_path), "gha_third_party_steps")] == [
        "a/b@v1"
    ]


def test_windows_line_endings_keep_line_numbers_right(tmp_path):
    write(tmp_path, ".github/workflows/w.yml", WORKFLOW.replace("\n", "\r\n").encode(), binary=True)
    (step,) = by_group(extract(tmp_path), "gha_third_party_steps")
    assert step["line"] == 6


def test_an_empty_file_and_a_comment_only_file_are_ignored(tmp_path):
    write(tmp_path, ".github/workflows/empty.yml", "")
    write(tmp_path, ".github/workflows/comment.yml", "# nothing here\n")
    write(tmp_path, ".github/workflows/list.yml", "- a\n- b\n")
    assert extract(tmp_path) == []


def test_a_file_in_latin_1_is_skipped_without_stopping_the_rest(tmp_path):
    write(tmp_path, ".github/workflows/old.yml", "name: caf\xe9\n".encode("latin-1"), binary=True)
    write(tmp_path, ".github/workflows/ok.yml", WORKFLOW)
    assert by_group(extract(tmp_path), "gha_third_party_steps")


def test_a_file_over_the_size_limit_is_skipped(tmp_path):
    write(tmp_path, ".github/workflows/big.yml", WORKFLOW + "# " + "x" * 1_100_000 + "\n")
    assert extract(tmp_path) == []


def test_a_directory_named_like_a_workflow_is_ignored(tmp_path):
    (tmp_path / ".github" / "workflows" / "dir.yml").mkdir(parents=True)
    write(tmp_path, ".github/workflows/ok.yml", WORKFLOW)
    assert by_group(extract(tmp_path), "gha_third_party_steps")


def test_a_symlinked_workflow_is_not_followed(tmp_path):
    outside = write(tmp_path, "outside.yml", WORKFLOW)
    folder = tmp_path / "repo" / ".github" / "workflows"
    folder.mkdir(parents=True)
    try:
        os.symlink(outside, folder / "link.yml")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks need extra privileges on this system")
    assert extract(tmp_path / "repo") == []


def test_workflows_in_subfolders_are_not_workflows(tmp_path):
    write(tmp_path, ".github/workflows/nested/w.yml", WORKFLOW)
    assert extract(tmp_path) == []


def test_no_github_folder_at_all(tmp_path):
    assert extract(tmp_path) == []


# --- job and step shapes ------------------------------------------------------------------


def test_numeric_and_quoted_job_ids(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        'name: w\njobs:\n  1:\n    runs-on: x\n  "two":\n    runs-on: x\n    timeout-minutes: 5\n',
    )
    jobs = {i["item_id"]: i for i in by_group(extract(tmp_path), "gha_jobs")}
    assert set(jobs) == {"1", "two"}
    assert jobs["two"]["features"]["has_timeout_minutes"] is True
    assert jobs["two"]["line"] == 5


def test_yaml_anchors_and_merge_keys_are_resolved(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\n"
        "x-defaults: &defaults\n"
        "  runs-on: x\n"
        "  timeout-minutes: 10\n"
        "jobs:\n"
        "  a:\n"
        "    <<: *defaults\n"
        "  b:\n"
        "    runs-on: y\n",
    )
    jobs = {i["item_id"]: i for i in by_group(extract(tmp_path), "gha_jobs")}
    assert jobs["a"]["features"]["has_timeout_minutes"] is True
    assert jobs["b"]["features"]["has_timeout_minutes"] is False


def test_jobs_that_are_not_a_mapping_still_give_a_workflow_item(tmp_path):
    write(tmp_path, ".github/workflows/w.yml", "name: w\njobs: []\n")
    items = extract(tmp_path)
    assert [i["peer_group"] for i in items] == ["gha_workflows"]


def test_a_job_that_is_null_is_skipped(tmp_path):
    write(tmp_path, ".github/workflows/w.yml", "name: w\njobs:\n  a:\n  b:\n    runs-on: x\n")
    assert [i["item_id"] for i in by_group(extract(tmp_path), "gha_jobs")] == ["b"]


def test_an_empty_permissions_block_counts_as_a_permissions_block(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\npermissions: {}\njobs:\n  a:\n    runs-on: x\n",
    )
    (workflow,) = by_group(extract(tmp_path), "gha_workflows")
    assert workflow["features"]["has_permissions_block"] is True


def test_a_string_permissions_value_counts(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\npermissions: read-all\njobs:\n  a:\n    runs-on: x\n",
    )
    (workflow,) = by_group(extract(tmp_path), "gha_workflows")
    assert workflow["features"]["has_permissions_block"] is True


def test_steps_that_are_not_mappings_are_skipped(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\njobs:\n  a:\n    runs-on: x\n    steps:\n      - just a string\n      - 7\n"
        "      - uses: 5\n      - uses: a/b@v1\n",
    )
    assert [i["item_id"] for i in by_group(extract(tmp_path), "gha_third_party_steps")] == [
        "a/b@v1"
    ]


def test_quoted_references_with_comments_and_spaces(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\njobs:\n  a:\n    runs-on: x\n    steps:\n"
        '      - uses: "a/b@v1"   # a comment\n      - uses: "  c/d@v2  "\n',
    )
    ids = [i["item_id"] for i in by_group(extract(tmp_path), "gha_third_party_steps")]
    assert ids == ["a/b@v1", "c/d@v2"]


def test_references_built_from_expressions_are_not_judged(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\njobs:\n  a:\n    runs-on: x\n    steps:\n"
        "      - uses: actions/checkout@${{ inputs.ref }}\n      - uses: a/b@v1\n",
    )
    assert [i["item_id"] for i in by_group(extract(tmp_path), "gha_third_party_steps")] == [
        "a/b@v1"
    ]


def test_an_action_with_no_reference_is_unpinned(tmp_path):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        "name: w\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: owner/repo\n",
    )
    (step,) = by_group(extract(tmp_path), "gha_third_party_steps")
    assert step["features"]["pinned_to_sha"] is False


@pytest.mark.parametrize(
    ("ref", "pinned"),
    [
        ("a" * 40, True),
        ("A" * 40, True),
        ("a" * 39, False),
        ("a" * 41, False),
        ("g" * 40, False),
        ("v1", False),
        ("main", False),
        ("sha256:" + "b" * 64, True),
        ("sha256:" + "b" * 63, False),
    ],
)
def test_only_full_length_hex_references_count_as_pinned(tmp_path, ref, pinned):
    write(
        tmp_path,
        ".github/workflows/w.yml",
        f"name: w\njobs:\n  a:\n    runs-on: x\n    steps:\n      - uses: o/r@{ref}\n",
    )
    (step,) = by_group(extract(tmp_path), "gha_third_party_steps")
    assert step["features"]["pinned_to_sha"] is pinned


# --- composite actions --------------------------------------------------------------------


COMPOSITE = (
    "name: setup\nruns:\n  using: composite\n  steps:\n"
    "    - uses: actions/cache@v4\n    - run: echo hi\n      shell: bash\n"
    "    - uses: ./.github/actions/other\n"
)


def test_composite_actions_are_checked_for_unpinned_steps(tmp_path):
    write(tmp_path, ".github/actions/setup/action.yml", COMPOSITE)
    (step,) = by_group(extract(tmp_path), "gha_third_party_steps")
    assert step["item_id"] == "actions/cache@v4"
    assert step["file"] == ".github/actions/setup/action.yml"
    assert step["line"] == 5
    assert step["features"]["pinned_to_sha"] is False


def test_a_repository_that_is_itself_an_action(tmp_path):
    write(tmp_path, "action.yaml", COMPOSITE)
    (step,) = by_group(extract(tmp_path), "gha_third_party_steps")
    assert step["file"] == "action.yaml"


def test_javascript_and_docker_actions_have_no_steps(tmp_path):
    write(
        tmp_path,
        ".github/actions/js/action.yml",
        "name: js\nruns:\n  using: node20\n  main: index.js\n",
    )
    write(
        tmp_path,
        ".github/actions/dk/action.yml",
        "name: dk\nruns:\n  using: docker\n  image: Dockerfile\n",
    )
    assert extract(tmp_path) == []


def test_nested_composite_actions_are_found(tmp_path):
    write(tmp_path, ".github/actions/a/b/c/action.yml", COMPOSITE)
    assert len(by_group(extract(tmp_path), "gha_third_party_steps")) == 1


def test_composite_and_workflow_steps_share_one_group(tmp_path):
    write(tmp_path, ".github/actions/setup/action.yml", COMPOSITE)
    write(tmp_path, ".github/workflows/w.yml", WORKFLOW)
    files = {i["file"] for i in by_group(extract(tmp_path), "gha_third_party_steps")}
    assert files == {".github/actions/setup/action.yml", ".github/workflows/w.yml"}


def test_a_job_named_like_an_earlier_nested_key_gets_its_own_line(tmp_path):
    text = (
        "name: w\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: x\n"
        "    strategy:\n"
        "      matrix:\n"
        "        build: [a, b]\n"
        "    steps:\n"
        "      - run: echo hi\n"
        "  build:\n"
        "    runs-on: x\n"
        "    steps:\n"
        "      - run: echo build\n"
    )
    write(tmp_path, ".github/workflows/w.yml", text)
    lines = {i["item_id"]: i["line"] for i in by_group(extract(tmp_path), "gha_jobs")}
    assert lines == {"test": 3, "build": 10}
