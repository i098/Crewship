"""Exercise the first-write configuration through Ansible in a disposable home."""

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


def apply(tmp_path, home, check=False):
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost",
        "connection": "local",
        "gather_facts": False,
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "ansible/tasks/nvim.yml")}],
    }]))
    result = subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps({"crewship_cfg": {"home": str(home)},
                                    "crewship_repo": str(ROOT)}),
         *(["--check"] if check else [])],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


@pytest.mark.parametrize("private_parent", [False, True])
@pytest.mark.parametrize("empty_directory", [False, True])
def test_seed_and_repeat_preserve_user_changes(tmp_path, private_parent, empty_directory):
    home = tmp_path / "home"
    home.mkdir()
    config = home / ".config/nvim"
    if private_parent:
        config.parent.mkdir(mode=0o700)
    if empty_directory:
        config.mkdir(parents=True)
    apply(tmp_path, home, check=True)
    assert config.is_dir() if empty_directory else not config.exists()
    if empty_directory:
        assert list(config.iterdir()) == []
    apply(tmp_path, home)
    if private_parent:
        assert config.parent.stat().st_mode & 0o777 == 0o700
    assert (config / "init.lua").read_bytes() == (ROOT / "config/nvim/init.lua").read_bytes()
    assert (config / "lua/plugins/pyrefly.lua").read_bytes() == (
        ROOT / "config/nvim/lua/plugins/pyrefly.lua"
    ).read_bytes()
    assert not (home / ".local/share/nvim").exists()  # No plugin sync during apply.
    (config / "init.lua").write_text("-- user configuration\n")
    (config / "lua/plugins/pyrefly.lua").unlink()
    assert "changed=0" in apply(tmp_path, home)
    assert (config / "init.lua").read_text() == "-- user configuration\n"
    assert not (config / "lua/plugins/pyrefly.lua").exists()


@pytest.mark.parametrize("kind", [
    "directory", "hidden_entry", "nested_directory", "file", "symlink", "dangling_symlink",
])
def test_existing_configuration_is_never_merged_or_replaced(tmp_path, kind):
    home = tmp_path / "home"
    config = home / ".config/nvim"
    config.parent.mkdir(parents=True)
    target = tmp_path / "custom"
    if kind == "directory":
        config.mkdir()
        (config / "init.lua").write_text("user config")
    elif kind == "hidden_entry":
        config.mkdir()
        (config / ".keep").touch()
    elif kind == "nested_directory":
        (config / "lua").mkdir(parents=True)
    elif kind == "file":
        config.write_text("user config")
    else:
        if kind == "symlink":
            target.mkdir()
        config.symlink_to(target)
    before = config.lstat()
    assert "changed=0" in apply(tmp_path, home)
    after = config.lstat()
    assert (after.st_ino, after.st_mode, after.st_mtime_ns) == (
        before.st_ino, before.st_mode, before.st_mtime_ns
    )
    if kind == "directory":
        assert (config / "init.lua").read_text() == "user config"
        assert list(config.iterdir()) == [config / "init.lua"]
    elif kind == "hidden_entry":
        assert list(config.iterdir()) == [config / ".keep"]
    elif kind == "nested_directory":
        assert list(config.iterdir()) == [config / "lua"]
        assert list((config / "lua").iterdir()) == []
    elif kind == "file":
        assert config.read_text() == "user config"
    elif kind == "symlink":
        assert list(target.iterdir()) == []
    else:
        assert not target.exists()
