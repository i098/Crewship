import importlib.util
import json
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
