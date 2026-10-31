import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/check_paths.py"
SPEC = importlib.util.spec_from_file_location("check_paths", SCRIPT)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_paths_are_classified_without_following_or_changing_links(tmp_path):
    file = tmp_path / "file"
    file.write_text("keep")
    directory = tmp_path / "directory"
    directory.mkdir()
    link = tmp_path / "link"
    link.symlink_to(file)
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent-target")
    missing = tmp_path / "missing"
    paths = [missing, file, dangling, directory, link]

    result = subprocess.run(
        [sys.executable, str(SCRIPT), json.dumps([str(path) for path in paths])],
        capture_output=True, text=True, check=True,
    )

    assert json.loads(result.stdout) == {
        "existing": [str(file), str(dangling), str(directory), str(link)],
        "missing": [str(missing)],
    }
    assert file.read_text() == "keep"
    assert link.readlink() == file
    assert dangling.readlink() == tmp_path / "absent-target"


def test_directory_details_do_not_follow_links(tmp_path):
    directory = tmp_path / "directory"
    directory.mkdir()
    linked_directory = tmp_path / "linked-directory"
    linked_directory.symlink_to(directory, target_is_directory=True)
    file = tmp_path / "file"
    file.write_text("keep")
    dangling = tmp_path / "dangling"
    dangling.symlink_to(tmp_path / "absent-target")
    missing = tmp_path / "missing"
    paths = [linked_directory, file, directory, dangling, missing]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--directories", json.dumps([str(path) for path in paths])],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout) == {
        "existing": [str(path) for path in paths[:-1]],
        "missing": [str(missing)],
        "directories": [str(directory)],
    }
    assert linked_directory.readlink() == directory
    assert dangling.readlink() == tmp_path / "absent-target"
    assert file.read_text() == "keep"


@pytest.mark.parametrize("uid_offset,gid_offset", [(0, 0), (1, 0), (0, 1)])
def test_owned_directories_require_matching_ids_and_do_not_follow_links(tmp_path, uid_offset, gid_offset):
    directory = tmp_path / "directory"
    directory.mkdir(mode=0o710)
    linked = tmp_path / "linked"
    linked.symlink_to(directory, target_is_directory=True)
    file = tmp_path / "file"
    file.write_text("keep")
    paths = [str(path) for path in (directory, linked, file, tmp_path / "missing")]

    result = checker.classify_paths(
        paths, ownership=(os.getuid() + uid_offset, os.getgid() + gid_offset),
    )

    assert result["owned_directories"] == ([] if uid_offset or gid_offset else [str(directory)])
    assert directory.stat().st_mode & 0o777 == 0o710
    assert linked.readlink() == directory
    assert file.read_text() == "keep"


@pytest.mark.parametrize("error_type", [PermissionError, NotADirectoryError])
def test_inspection_errors_are_not_reported_as_missing(monkeypatch, error_type):
    def fail(path):
        raise error_type(path)

    monkeypatch.setattr(checker.os, "lstat", fail)
    with pytest.raises(error_type):
        checker.classify_paths(["/unreadable"])


@pytest.mark.parametrize("value", ["{}", "[1]", "invalid json"])
def test_invalid_path_lists_fail_without_a_report(value):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), value], capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""


def test_containing_reports_only_readable_files_that_hold_the_text(tmp_path):
    marked = tmp_path / "marked"
    marked.write_text("a\n# BEGIN x\nb\n")
    plain = tmp_path / "plain"
    plain.write_text("a\n")
    linked = tmp_path / "linked"
    linked.symlink_to(marked)
    directory = tmp_path / "directory"
    directory.mkdir()
    paths = [marked, plain, linked, directory, tmp_path / "missing"]
    result = subprocess.run(
        [sys.executable, str(SCRIPT), json.dumps([str(path) for path in paths]),
         "--containing", "# BEGIN x"],
        capture_output=True, text=True, check=True,
    )
    assert json.loads(result.stdout)["containing"] == [str(marked), str(linked)]
