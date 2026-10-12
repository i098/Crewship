import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]

spec = importlib.util.spec_from_file_location("ship_config_board", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ship)

BOARD = {"history": 128, "cap_mb": 32, "max_msg_kb": 16}


@pytest.fixture
def configuration():
    document = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    document["crewship"]["board"] = dict(BOARD)
    return document


def test_the_defaults_leave_the_board_off():
    assert "board" not in yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())["crewship"]


@pytest.mark.parametrize("block", [{}, BOARD])
def test_the_board_block_is_accepted(configuration, block):
    configuration["crewship"]["board"] = dict(block)
    assert ship.validate_config(configuration) is configuration


@pytest.mark.parametrize(
    "change", [{"history": 0}, {"cap_mb": "32"}, {"max_msg_kb": 2048}, {"socket": "/tmp/x"}]
)
def test_a_bad_board_block_is_rejected(configuration, change):
    configuration["crewship"]["board"].update(change)
    with pytest.raises(ValueError, match="board"):
        ship.validate_config(configuration)


@pytest.mark.parametrize("profile", ["firstmate", "development"])
def test_the_board_needs_firstmate_and_cargo(configuration, profile):
    configuration["crewship"]["profiles"][profile] = False
    with pytest.raises(ValueError, match="board requires the firstmate profile and the development"):
        ship.validate_config(configuration)


def test_dock_board_writes_the_block(tmp_path, monkeypatch):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / "blueprint" / path, tmp_path / "blueprint" / path)
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    ship.initialize(argparse.Namespace(user="coder", home="/home/coder", container=False, board=True))
    assert ship.load_config(tmp_path / ".local/host.yml")["crewship"]["board"] == {}


# A stand-in for cargo, so the test never compiles; CI builds the crate itself.
FAKE_CARGO = """#!/bin/sh
echo "$PWD $*" >> "$HOME/cargo.log"
mkdir -p "$5/release" && printf '#!/bin/sh\\n' > "$5/release/crewboard"
"""


def _apply(tmp_path, home, board, check=False):
    playbook = tmp_path / "playbook.yml"
    if not playbook.exists():
        (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
        playbook.write_text(yaml.safe_dump([{
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "environment": {"HOME": str(home)},
            "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/board.yml")}],
            "handlers": [{"name": name, "ansible.builtin.debug": {"msg": name}, "listen": name}
                         for name in ("reload user systemd", "restart crewboard")],
        }]))
    crewship_cfg = {"user": "coder", "home": str(home)}
    if board is not None:
        crewship_cfg["board"] = board
    variables = {
        "crewship_cfg": crewship_cfg,
        "crewship_local_bin": str(home / ".local/bin"),
        "crewship_user_units": str(home / ".config/systemd/user"),
        "crewship_board_dir": str(home / ".local/share/crewship/crewboard"),
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship_manage_services": False,
        "crewship_user_systemd_env": {},
    }
    result = subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps(variables), *(["--check"] if check else [])],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    return result.stdout


def test_apply_builds_once_and_removing_the_key_leaves_no_trace(tmp_path):
    home = tmp_path / "home"
    (home / ".cargo/bin").mkdir(parents=True)
    cargo = home / ".cargo/bin/cargo"
    cargo.write_text(FAKE_CARGO)
    cargo.chmod(0o755)
    units = home / ".config/systemd/user"
    build = home / ".local/share/crewship/crewboard"
    files = [
        units / "crewboard.service",
        units / "default.target.wants/crewboard.service",
        home / ".local/bin/crewboard",
        build,
    ]

    assert "would run `cargo build" in _apply(tmp_path, home, BOARD, check=True)
    assert not any(path.exists() for path in files)

    _apply(tmp_path, home, BOARD)
    assert all(path.exists() for path in files)
    assert (home / "cargo.log").read_text() == f"{build}/source build --release --locked --target-dir {build}/target\n"
    unit = (units / "crewboard.service").read_text()
    assert (
        f"ExecStart={home}/.local/bin/crewboard serve --socket %t/crewboard.sock"
        " --history 128 --cap-bytes 33554432 --max-msg 16384\n"
    ) in unit
    assert "Restart=always\n" in unit and "MemoryMax=96M\n" in unit

    assert "changed=0" in _apply(tmp_path, home, BOARD)
    assert "changed=0" in _apply(tmp_path, home, BOARD, check=True)
    assert len((home / "cargo.log").read_text().splitlines()) == 1

    _apply(tmp_path, home, None)
    assert not any(path.exists() or path.is_symlink() for path in files)
    assert "changed=0" in _apply(tmp_path, home, None)
