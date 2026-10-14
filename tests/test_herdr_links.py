"""blueprint/ansible/tasks/herdr_links.yml: an apply never takes over another account's host-wide links."""

import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def apply(tmp_path, home):
    playbook = tmp_path / "links.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "vars": {
            "ansible_become": False,
            "crewship_cfg": {"home": str(home)},
            "crewship_local_bin": str(home / ".local/bin"),
            "crewship_global_bin": str(tmp_path / "usr-local-bin"),
        },
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/herdr_links.yml")}],
    }]))
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook)],
        cwd=tmp_path, env={**os.environ, "ANSIBLE_STDOUT_CALLBACK": "default"}, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def account(tmp_path, name):
    home = tmp_path / name
    (home / ".local/bin").mkdir(parents=True)
    for command in ("herdr", "herdr-patch"):
        (home / ".local/bin" / command).write_text("#!/bin/sh\n")
    return home


def test_an_apply_for_a_second_account_leaves_the_owners_links_and_files(tmp_path):
    owner, sandbox = account(tmp_path, "owner"), account(tmp_path, "sandbox")
    links = tmp_path / "usr-local-bin"
    links.mkdir()
    (links / "herdr").symlink_to(owner / ".local/bin/herdr")
    (links / "herdr-patch").write_text("#!/bin/sh\n")  # an unmanaged file
    (links / "herdr-mosh").symlink_to(owner / ".local/bin/herdr")
    output = apply(tmp_path, sandbox)
    assert os.readlink(links / "herdr") == str(owner / ".local/bin/herdr")
    assert not (links / "herdr-patch").is_symlink()
    assert (links / "herdr-mosh").is_symlink()
    assert "Leaving" in output


def test_an_apply_creates_missing_links_and_replaces_dangling_ones(tmp_path):
    home = account(tmp_path, "owner")
    links = tmp_path / "usr-local-bin"
    links.mkdir()
    (links / "herdr").symlink_to(tmp_path / "gone/.local/bin/herdr")
    (links / "herdr-mosh").symlink_to(home / ".local/bin/herdr")
    apply(tmp_path, home)
    for command in ("herdr", "herdr-patch"):
        assert os.readlink(links / command) == str(home / ".local/bin" / command)
    assert not os.path.lexists(links / "herdr-mosh")
    # A second apply keeps the account's own links.
    apply(tmp_path, home)
    assert os.readlink(links / "herdr") == str(home / ".local/bin/herdr")
