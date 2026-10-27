import argparse
import configparser
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
    configuration["crewship"]["profiles"]["development"] = True
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


@pytest.mark.parametrize("sink", [
    {"repo": "owner/board", "issue": 7},
    {"repo": "owner/board", "issue": 7, "topics": ["fleet", "task/*", "*", "-ops"], "interval": 60},
    {"repo": "owner/board", "issue": 7.0, "interval": 60.0},
])
def test_the_github_sink_block_is_accepted(configuration, sink):
    configuration["crewship"]["profiles"]["development"] = True
    configuration["crewship"]["board"]["github_sink"] = sink
    assert ship.validate_config(configuration) is configuration


@pytest.mark.parametrize("change", [
    {"repo": "no-owner"}, {"repo": "../board"}, {"repo": "owner/.."},
    {"issue": 0}, {"issue": "7"}, {"interval": 59}, {"interval": "300"},
    {"topics": []}, {"topics": "fleet"}, {"topics": ["Bad"]},
    {"topics": ["fleet\n"]}, {"topics": ["task/*/x"]}, {"topics": ["a" * 65]},
    {"token": "secret"},
])
def test_a_bad_github_sink_block_is_rejected(configuration, change):
    configuration["crewship"]["profiles"]["development"] = True
    configuration["crewship"]["board"]["github_sink"] = {"repo": "owner/board", "issue": 7, **change}
    with pytest.raises(ValueError, match="github_sink"):
        ship.validate_config(configuration)


@pytest.mark.parametrize("sink", [{}, {"repo": "owner/board"}, {"issue": 7}])
def test_the_github_sink_needs_a_repository_and_issue(configuration, sink):
    configuration["crewship"]["board"]["github_sink"] = sink
    with pytest.raises(ValueError, match="github_sink"):
        ship.validate_config(configuration)


def test_the_github_sink_cannot_exist_without_the_board(configuration):
    configuration["crewship"]["github_sink"] = {"repo": "owner/board", "issue": 7}
    del configuration["crewship"]["board"]
    with pytest.raises(ValueError):
        ship.validate_config(configuration)


def test_dock_board_writes_the_block(tmp_path, monkeypatch):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / "blueprint" / path, tmp_path / "blueprint" / path)
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    ship.initialize(argparse.Namespace(user="coder", home="/home/coder", container=False, with_=["board"]))
    assert ship.load_config(tmp_path / ".local/host.yml")["crewship"]["board"] == {}


# A stand-in for cargo, so the test never compiles; CI builds the crate itself.
FAKE_CARGO = """#!/bin/sh
echo "$PWD $*" >> "$HOME/cargo.log"
mkdir -p "$5/release" && printf '#!/bin/sh\\n' > "$5/release/crewboard"
"""


def _apply(tmp_path, home, board, check=False, manage_services=False):
    playbook = tmp_path / "playbook.yml"
    if not playbook.exists():
        (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
        handlers = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]["handlers"]
        playbook.write_text(yaml.safe_dump([{
            "hosts": "localhost",
            "connection": "local",
            "gather_facts": False,
            "environment": {"HOME": str(home)},
            "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/board.yml")}],
            "handlers": [
                {"name": "reload user systemd", "ansible.builtin.debug": {"msg": "reload"}},
                *(handler for handler in handlers
                  if handler.get("listen") in ("restart crewboard", "restart crewboard github sink")),
            ],
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
        "crewship_manage_services": manage_services,
        "crewship_path_checker": str(ROOT / "scripts/check_paths.py"),
        "crewship_become_target": False,
        "crewship_user_systemd_env": {},
    }
    result = subprocess.run(
        [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(playbook),
         "--extra-vars", json.dumps(variables), *(["--check"] if check else [])],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    return result.stdout


def _service_settings(path):
    unit = configparser.ConfigParser(strict=False, interpolation=None, delimiters=("=",))
    unit.optionxform = str
    unit.read_string(path.read_text())
    return unit["Service"]


def test_first_preview_does_not_contact_systemd(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    board = {**BOARD, "github_sink": {"repo": "owner/board", "issue": 7}}
    assert "would run `cargo build" in _apply(
        tmp_path, home, board, check=True, manage_services=True,
    )
    assert not (home / ".config/systemd/user/crewboard-github-sink.service").exists()


@pytest.mark.parametrize("sink", [
    None,
    {"repo": "owner/board", "issue": 7},
    {"repo": "owner/board", "issue": 7.0, "topics": ["fleet", "task/*", "-ops"], "interval": 60.0},
])
def test_apply_builds_once_and_removing_the_key_leaves_no_trace(tmp_path, sink):
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
    board = {**BOARD, **({"github_sink": sink} if sink is not None else {})}
    sink_files = [
        units / "crewboard-github-sink.service",
        units / "default.target.wants/crewboard-github-sink.service",
    ]

    assert "would run `cargo build" in _apply(tmp_path, home, board, check=True)
    assert not any(path.exists() for path in [*files, *sink_files])

    _apply(tmp_path, home, board)
    assert all(path.exists() for path in files)
    assert all(path.exists() == (sink is not None) for path in sink_files)
    if sink is not None:
        sink_unit = _service_settings(sink_files[0])
        arguments = '--interval 60 -- "fleet" "task/*" "-ops"' if "topics" in sink else '--interval 300 -- "fleet"'
        assert sink_unit["ExecStart"] == f"{home}/.local/bin/crewboard github-sink --repo owner/board --issue 7 {arguments}"
        assert sink_unit["Restart"] == "on-failure"
        assert sink_files[1].resolve() == sink_files[0]
    assert (home / "cargo.log").read_text() == f"{build}/source build --release --locked --target-dir {build}/target\n"
    unit = _service_settings(units / "crewboard.service")
    assert unit["ExecStart"] == (
        f"{home}/.local/bin/crewboard serve --socket %t/crewboard.sock"
        " --history 128 --cap-bytes 33554432 --max-msg 16384"
    )
    assert unit["Restart"] == "always"
    assert unit["MemoryMax"] == "96M"

    assert "changed=0" in _apply(tmp_path, home, board)
    assert "changed=0" in _apply(tmp_path, home, board, check=True)
    assert len((home / "cargo.log").read_text().splitlines()) == 1
    if sink is not None:
        _apply(tmp_path, home, BOARD)
        assert not any(path.exists() or path.is_symlink() for path in sink_files)
        assert all(path.exists() for path in files)
        assert "changed=0" in _apply(tmp_path, home, BOARD)
        _apply(tmp_path, home, board)

    _apply(tmp_path, home, None)
    assert not any(path.exists() or path.is_symlink() for path in [*files, *sink_files])
    assert "changed=0" in _apply(tmp_path, home, None)
