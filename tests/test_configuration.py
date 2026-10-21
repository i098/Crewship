import argparse
import getpass
import grp
import importlib.util
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
GROUP_VARS_FILES = sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))
GROUP_VARS_ARGS = [arg for f in GROUP_VARS_FILES for arg in ("-e", f"@{f}")]


def test_group_vars_files_define_disjoint_keys():
    seen: dict[str, str] = {}
    for f in GROUP_VARS_FILES:
        for key in yaml.safe_load(f.read_text()):
            assert key not in seen, f"{key} is in {seen[key]} and {f.name}"
            seen[key] = f.name
SPEC = importlib.util.spec_from_file_location("ship_config", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ship)


@pytest.fixture
def configuration():
    return yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())


def test_valid_configuration_is_accepted_by_real_schema(configuration):
    assert ship.validate_config(configuration) is configuration


def test_old_host_config_is_rewritten_once_with_private_backup(configuration, tmp_path, capsys):
    old_key, new_key = ship.OLD_ROOT, ship.NEW_ROOT
    original = "# Host settings\n" + yaml.safe_dump(
        {"schema_version": 1, old_key: configuration[new_key]}, sort_keys=False
    )
    host = tmp_path / "host.yml"
    host.write_text(original)
    host.chmod(0o600)
    assert ship.load_config(host) == configuration
    backup = host.with_name("host.yml.bak")
    assert backup.read_text() == original
    assert host.stat().st_mode & 0o777 == backup.stat().st_mode & 0o777 == 0o600
    assert yaml.safe_load(host.read_text()) == configuration
    assert len(capsys.readouterr().err.splitlines()) == 1
    first = host.read_bytes(), host.stat().st_mtime_ns, backup.stat().st_mtime_ns
    assert ship.load_config(host) == configuration
    assert (host.read_bytes(), host.stat().st_mtime_ns, backup.stat().st_mtime_ns) == first
    assert not capsys.readouterr().err


def test_config_rewrite_preserves_unknown_keys_and_values(tmp_path):
    old_key, new_key = ship.OLD_ROOT, ship.NEW_ROOT
    document = {
        old_key: {"custom": {"key": "keep"}, "workspace": "/srv/custom"},
        old_key + "_future": {"key": 7},
        "unknown": [False, "keep"],
    }
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump(document))
    expected = {new_key: document[old_key], **{k: v for k, v in document.items() if k != old_key}}
    assert ship.migrate_config(host, document) == expected
    assert yaml.safe_load(host.read_text()) == expected


@pytest.mark.parametrize("obstacle", ["conflicting_keys", "existing_backup"])
def test_config_rewrite_refuses_to_discard_config_or_backup(configuration, tmp_path, obstacle):
    old_key, new_key = ship.OLD_ROOT, ship.NEW_ROOT
    document = {"schema_version": 1, old_key: configuration[new_key]}
    if obstacle == "conflicting_keys":
        document[new_key] = {"custom": "keep"}
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump(document))
    original = host.read_bytes()
    backup = host.with_name("host.yml.bak")
    if obstacle == "existing_backup":
        backup.write_bytes(b"original backup")
    with pytest.raises(ValueError):
        ship.load_config(host)
    assert host.read_bytes() == original
    if backup.exists():
        assert backup.read_bytes() == b"original backup"


def test_failed_rewrite_keeps_original_and_backup(configuration, tmp_path, monkeypatch):
    old_key, new_key = ship.OLD_ROOT, ship.NEW_ROOT
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump({"schema_version": 1, old_key: configuration[new_key]}))
    original = host.read_bytes()
    monkeypatch.setattr(ship.yaml, "safe_dump", lambda *a, **k: (_ for _ in ()).throw(OSError("full")))
    with pytest.raises(OSError, match="full"):
        ship.load_config(host)
    assert host.read_bytes() == host.with_name("host.yml.bak").read_bytes() == original
    assert not list(tmp_path.glob(".host.yml.*"))


def test_legacy_obscura_keys_are_ignored_with_one_warning_and_apply_proceeds(
    configuration, tmp_path, monkeypatch, capsys
):
    legacy = tmp_path / "legacy.yml"
    current = tmp_path / "current.yml"
    current.write_text(yaml.safe_dump(configuration))
    configuration["crewship"]["browsers"].update(obscura_version="0.2.2", obscura_sha256="c" * 64)
    legacy.write_text(yaml.safe_dump(configuration))
    provisioned = []
    monkeypatch.setattr(
        ship, "provision", lambda document, check: provisioned.append(check) or 0
    )
    monkeypatch.setattr(ship, "questions", lambda document, config_path: 0)
    for host in (current, legacy):
        monkeypatch.setattr(ship.sys, "argv", ["ship.sh", "launch", "--config", str(host)])
        assert ship.main() == 0
    warning = capsys.readouterr().err
    assert provisioned == [False, False]
    assert warning.count("WARNING") == 1
    assert "obscura_version" in warning and "obscura_sha256" in warning
    assert "no longer used" in warning


@pytest.mark.parametrize(
    "workspace", ["/home/other/Dev", "/home/coder/../other/Dev", "/home/coder"]
)
def test_workspace_cannot_escape_operator_home(configuration, workspace):
    configuration["crewship"]["workspace"] = workspace
    with pytest.raises(ValueError, match="workspace"):
        ship.validate_config(configuration)


def test_invalid_secret_field_is_rejected_without_echoing_value(configuration):
    private_value = "PRIVATE_VALUE_MUST_NOT_APPEAR_IN_DIAGNOSTICS"
    configuration["crewship"]["api_key"] = private_value
    with pytest.raises(ValueError) as failure:
        ship.validate_config(configuration)
    assert private_value not in str(failure.value)


def test_firstmate_cannot_silently_omit_its_agent_dependencies(configuration):
    configuration["crewship"]["profiles"]["agents"] = False
    with pytest.raises(ValueError, match="Firstmate requires"):
        ship.validate_config(configuration)


def test_firstmate_revision_pin_is_rejected(configuration):
    # The checkout tracks upstream main; a sha pin would silently freeze a
    # host on an old Firstmate, so the schema refuses the key outright.
    configuration["crewship"]["firstmate"]["revision"] = "0" * 40
    with pytest.raises(ValueError):
        ship.validate_config(configuration)


def test_fleet_guards_require_docker_and_firstmate(configuration):
    configuration["crewship"]["profiles"]["fleet_guards"] = True
    configuration["crewship"]["profiles"]["docker"] = False
    with pytest.raises(ValueError, match="fleet guards require"):
        ship.validate_config(configuration)


def test_fleet_guards_accept_the_default_document_when_enabled(configuration):
    configuration["crewship"]["profiles"].update(fleet_guards=True, docker=True)
    assert ship.validate_config(configuration) is configuration


def test_browsers_valid_block_accepted(configuration):
    assert ship.validate_config(configuration) is configuration


def test_unknown_fleet_field_is_rejected(configuration):
    configuration["crewship"]["fleet"]["allow_migrations"] = True
    with pytest.raises(ValueError):
        ship.validate_config(configuration)


@pytest.mark.parametrize(
    "skills",
    [
        {"private_source": "/srv/private-skills"},
        {"private_source": "git@github.com:owner/skills.git", "private_ref": "main"},
        {"private_source": "https://github.com/owner/skills.git", "private_ref": "v1.2"},
        {"private_source": "ssh://git@example.com/owner/skills.git"},
        {"private_source": "file:///srv/skills.git"},
    ],
)
def test_private_skills_source_is_accepted(configuration, skills):
    configuration["crewship"]["skills"] = skills
    assert ship.validate_config(configuration) is configuration


@pytest.mark.parametrize(
    "skills",
    [
        {},
        {"private_source": ""},
        {"private_source": "relative/skills"},
        {"private_source": "--upload-pack=touch /tmp/x"},
        {"private_source": "https://token@github.com/owner/skills.git"},
        {"private_source": "https://user:token@github.com/owner/skills.git"},
        {"private_source": "git@github.com:owner/skills.git", "private_ref": "-main"},
        {"private_source": "/srv/skills", "token": "x"},
    ],
)
def test_bad_private_skills_source_is_rejected(configuration, skills):
    configuration["crewship"]["skills"] = skills
    with pytest.raises(ValueError):
        ship.validate_config(configuration)


def test_private_ref_with_local_path_is_rejected(configuration):
    configuration["crewship"]["skills"] = {"private_source": "/srv/skills", "private_ref": "main"}
    with pytest.raises(ValueError, match="private_ref"):
        ship.validate_config(configuration)


@pytest.mark.parametrize("data_dir", ["data", "/", "/srv/../root", "/srv/data/"])
def test_data_dir_must_be_a_plain_absolute_path(configuration, data_dir):
    configuration["crewship"]["data_dir"] = data_dir
    with pytest.raises(ValueError):
        ship.validate_config(configuration)


def test_bad_polling_window_cannot_disable_idle_accrual(configuration):
    configuration["crewship"]["browser_prune"]["max_gap_seconds"] = 120
    with pytest.raises(ValueError, match="observation intervals"):
        ship.validate_config(configuration)


def test_init_preserves_existing_local_configuration(tmp_path, monkeypatch):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / "blueprint" / path, tmp_path / "blueprint" / path)
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    args = argparse.Namespace(user="coder", home="/home/coder", container=True, with_=None)
    ship.initialize(args)
    local = tmp_path / ".local/host.yml"
    first = local.read_bytes()
    config = ship.load_config(local)["crewship"]
    assert not config["start_services"] and not config["profiles"]["docker"]
    assert config["profiles"]["agents"]
    with pytest.raises(FileExistsError):
        ship.initialize(args)
    assert local.read_bytes() == first


def test_root_operator_is_rejected_before_config_is_written(tmp_path, monkeypatch):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / "blueprint" / path, tmp_path / "blueprint" / path)
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="non-root"):
        ship.initialize(
            argparse.Namespace(user="root", home="/home/root", container=False, with_=None)
        )
    assert not (tmp_path / ".local/host.yml").exists()


def dock(tmp_path, monkeypatch, **options):
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / "blueprint" / path, tmp_path / "blueprint" / path)
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    options = {"container": False, "with_": None, **options}
    ship.initialize(argparse.Namespace(user="coder", home="/home/coder", **options))
    return ship.load_config(tmp_path / ".local/host.yml")["crewship"]


def on(config):
    return {name for name, enabled in config["profiles"].items() if enabled} | ({"board"} & config.keys())


def test_dock_writes_the_core_only_unless_a_choice_is_given(tmp_path, monkeypatch):
    config = dock(tmp_path, monkeypatch)
    assert on(config) == {"agents", "firstmate"}
    assert config["profiles"]["public_skills"] is False


def test_dock_with_turns_on_the_choices_and_what_they_need(tmp_path, monkeypatch):
    config = dock(tmp_path, monkeypatch, with_=["fleet_guards,board", "public_skills"])
    assert on(config) == {"agents", "firstmate", "fleet_guards", "docker", "board", "development", "public_skills"}
    assert on(dock(tmp_path / "all", monkeypatch, with_=["all"])) == {*ship.OPT_IN, "agents", "firstmate"}


def test_dock_with_still_takes_the_old_profile_name(tmp_path, monkeypatch):
    assert on(dock(tmp_path, monkeypatch, with_=["shared_postgres"])) == {"agents", "firstmate", "project_databases", "docker"}


@pytest.mark.parametrize("with_", [[""], ["none"]])
def test_dock_with_nothing_keeps_the_core(tmp_path, monkeypatch, with_):
    assert on(dock(tmp_path, monkeypatch, with_=with_)) == {"agents", "firstmate"}


@pytest.mark.parametrize("container, with_", [(False, ["bogus"]), (True, ["docker"]), (True, ["all,gateway"])])
def test_dock_rejects_an_unknown_choice_and_one_a_container_cannot_have(tmp_path, monkeypatch, container, with_):
    with pytest.raises(ValueError):
        dock(tmp_path, monkeypatch, container=container, with_=with_)
    assert not (tmp_path / ".local/host.yml").exists()


def test_dock_in_a_container_offers_what_a_container_can_run(tmp_path, monkeypatch):
    assert on(dock(tmp_path, monkeypatch, container=True, with_=["all"])) == {
        "agents",
        "public_skills",
        "agent_instructions",
        "development",
        "jj",
        "fdu",
        "fleet_browsers",
    }


def test_the_checklist_asks_until_the_answer_is_valid(tmp_path, monkeypatch, capsys):
    answers = iter(["bogus", "1 docker 99", f"1 4 {list(ship.OPT_IN).index('board') + 1}"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    config = dock(tmp_path, monkeypatch)
    assert on(config) == {"agents", "firstmate", "public_skills", "docker", "board", "development"}
    out = capsys.readouterr().out
    assert "unknown choice 'bogus'" in out and " 1. public_skills" in out and f"{list(ship.OPT_IN).index('board') + 1}. board" in out


def checklist(tmp_path, monkeypatch, answers, existing=()):
    # An absolute path wins the join with the home, so the files can live in tmp_path.
    files = [str(tmp_path / "files" / rel) for rel in ship.INSTRUCTION_FILES]
    monkeypatch.setattr(ship, "INSTRUCTION_FILES", files)
    for rel in existing:
        (tmp_path / "files" / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "files" / rel).write_text("mine\n")
    answers = iter(answers)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    for path in ("config", "schemas"):
        shutil.copytree(ROOT / "blueprint" / path, tmp_path / "blueprint" / path)
    ship.initialize(argparse.Namespace(user="coder", home="/home/coder", container=False, with_=None))
    return yaml.safe_load((tmp_path / ".local/host.yml").read_text())["crewship"]


@pytest.mark.parametrize("answer, mode", [("skip", "skip"), ("OVERWRITE", "overwrite"), ("", "append"), ("bogus", "append")])
def test_the_checklist_asks_the_mode_only_when_an_instructions_file_exists(tmp_path, monkeypatch, answer, mode):
    config = checklist(tmp_path, monkeypatch, ["agent_instructions", answer, "append"], [ship.INSTRUCTION_FILES[1]])
    assert config["profiles"]["agent_instructions"] is True and config["instructions_mode"] == mode


def test_the_checklist_does_not_ask_the_mode_without_a_file_or_a_choice(tmp_path, monkeypatch):
    config = checklist(tmp_path, monkeypatch, ["agent_instructions"])  # a third answer would raise StopIteration
    assert config["profiles"]["agent_instructions"] is True and "instructions_mode" not in config
    config = checklist(tmp_path / "other", monkeypatch, ["none"], ship.INSTRUCTION_FILES)
    assert config["profiles"]["agent_instructions"] is False and "instructions_mode" not in config


def test_instruction_files_match_the_installer():
    spec = importlib.util.spec_from_file_location("instructions", ROOT / "scripts/instructions.py")
    instructions = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(instructions)
    assert ship.INSTRUCTION_FILES == instructions.TARGETS


def fake_omp(launches, models=json.dumps({"models": [{"id": "model"}]}), exits=lambda n: 0):
    def run(command, **kwargs):
        if command[1:] == ["models", "--json"]:
            return subprocess.CompletedProcess(command, 0, models)
        launches.append(command)
        return subprocess.CompletedProcess(command, exits(len(launches)))

    return run


@pytest.mark.parametrize(
    "tty,ci,launched", [(False, "", False), (True, "true", False), (True, "", True)]
)
def test_questions_launch_only_on_an_interactive_terminal_outside_ci(
    configuration, tmp_path, monkeypatch, capsys, tty, ci, launched
):
    configuration["crewship"].update(
        user=ship.pwd.getpwuid(ship.os.getuid()).pw_name,
        home=str(tmp_path),
        workspace=str(tmp_path / "Dev"),
    )
    configuration["crewship"]["firstmate"].pop("checklist", None)
    launches = []
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: tty)
    monkeypatch.setenv("CI", ci)
    monkeypatch.setattr(ship.subprocess, "run", fake_omp(launches))
    assert ship.questions(configuration, tmp_path / "host.yml") == 0
    assert [command[0] for command in launches] == [tmp_path / ".local/bin/omp"] * launched
    skipped = capsys.readouterr().out.count("rerun ./ship.sh launch interactively")
    assert skipped == (0 if launched else 1)


@pytest.mark.parametrize("config_source", ["default", "absolute", "relative", "symlink"])
def test_second_apply_does_not_reopen_the_questions(
    configuration, tmp_path, monkeypatch, capsys, config_source
):
    configuration["crewship"].update(
        user=ship.pwd.getpwuid(ship.os.getuid()).pw_name,
        home=str(tmp_path),
        workspace=str(tmp_path / "Dev"),
    )
    configuration["crewship"]["firstmate"].pop("checklist", None)
    launches = []
    monkeypatch.setattr(ship, "ROOT", tmp_path)
    monkeypatch.setattr(ship, "load_config", lambda path: yaml.safe_load(path.read_text()))
    host = tmp_path / ".local/host.yml" if config_source == "default" else tmp_path / "selected.yml"
    host.parent.mkdir(parents=True, exist_ok=True)
    host.write_text(yaml.safe_dump(configuration))
    selected = host
    if config_source == "symlink":
        selected = tmp_path / "linked.yml"
        selected.symlink_to(host)
    monkeypatch.chdir(tmp_path)
    if config_source == "relative":
        selected = selected.relative_to(tmp_path)
    monkeypatch.setattr(ship, "provision", lambda document, check: 0)
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        ship.subprocess, "run", fake_omp(launches, exits=lambda n: 0 if n > 1 else 1)
    )
    args = [] if config_source == "default" else ["--config", str(selected)]
    monkeypatch.setattr(ship.sys, "argv", ["ship.sh", "launch", *args])
    marker = tmp_path / ".local/share/crewship/new-host-questions-done"
    assert ship.main() == 0
    assert not marker.exists()
    assert "New-host questions did not complete (omp exited 1)" in capsys.readouterr().out
    assert f"crewship.profiles.project_databases to true in {host.resolve()} " in launches[0][1]
    assert ship.main() == 0
    assert [command[0] for command in launches] == [tmp_path / ".local/bin/omp"] * 2
    assert marker.is_file()
    capsys.readouterr()
    assert ship.main() == 0
    assert len(launches) == 2
    assert f"{marker} exists); delete it and rerun" in capsys.readouterr().out


def test_questions_wait_for_an_omp_sign_in(configuration, tmp_path, monkeypatch, capsys):
    configuration["crewship"].update(
        user=ship.pwd.getpwuid(ship.os.getuid()).pw_name,
        home=str(tmp_path),
        workspace=str(tmp_path / "Dev"),
    )
    launches = []
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(
        ship.subprocess, "run", fake_omp(launches, models=json.dumps({"models": []}))
    )
    assert ship.questions(configuration, tmp_path / "host.yml") == 0
    assert launches == []
    assert not (tmp_path / ".local/share/crewship/new-host-questions-done").exists()
    assert "sign in to omp with /login" in capsys.readouterr().out


def test_another_accounts_apply_skips_questions_without_reading_the_unreadable_home(
    configuration, tmp_path, monkeypatch, capsys
):
    home = tmp_path / "coder"
    home.mkdir(mode=0o000)
    configuration["crewship"].update(user="another-account", home=str(home))
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: True)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr(ship.subprocess, "run", lambda *a, **k: pytest.fail("launched"))
    try:
        assert ship.questions(configuration, tmp_path / "host.yml") == 0
    finally:
        home.chmod(0o700)
    assert "rerun ./ship.sh launch interactively as another-account" in capsys.readouterr().out


@pytest.mark.parametrize(
    "github,models,questions_done,service,expected",
    [
        (1, '{"models":[]}', True, 0, "Sign-ins: pending"),
        (0, '{"models":[]}', True, 0, "Sign-ins: pending"),
        (1, '{"models":[{}]}', True, 0, "Sign-ins: pending"),
        (0, 'not json', True, 0, "Sign-ins: pending"),
        (0, '{"models":"invalid"}', True, 0, "Sign-ins: pending"),
        (0, '{"models":[{}]}', False, 0, "new-host questions"),
        (0, '{"models":[{}]}', True, 1, "Herdr service"),
        (0, '{"models":[{}]}', True, 0, "Fleet ready: setup checks passed"),
    ],
)
def test_setup_resumes_without_claiming_readiness_before_sign_in(
    configuration, tmp_path, monkeypatch, capsys, github, models, questions_done, service, expected
):
    configuration["crewship"].update(
        user=ship.pwd.getpwuid(ship.os.getuid()).pw_name,
        home=str(tmp_path), workspace=str(tmp_path / "Dev"),
    )
    firstmate = tmp_path / "Dev/firstmate/bin"
    firstmate.mkdir(parents=True)
    (firstmate / "fm-home-seed.sh").touch()
    if questions_done:
        marker = tmp_path / ".local/share/crewship/new-host-questions-done"
        marker.parent.mkdir(parents=True)
        marker.touch()
    host = tmp_path / "host config.yml"
    host.write_text(yaml.safe_dump(configuration))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ship, "tool_checks", lambda *_: [("omp", True, "OK omp")])
    monkeypatch.setattr(ship, "load_config", lambda path: yaml.safe_load(path.read_text()))
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)

    def run(command, **kwargs):
        if command[0] == "gh":
            return subprocess.CompletedProcess(command, github)
        if command[0] == "omp":
            return subprocess.CompletedProcess(command, 0, models)
        if command[0] == "systemctl":
            runtime = f"/run/user/{os.getuid()}"
            connected = (
                kwargs["env"].get("XDG_RUNTIME_DIR") == runtime
                and kwargs["env"].get("DBUS_SESSION_BUS_ADDRESS") == f"unix:path={runtime}/bus"
            )
            return subprocess.CompletedProcess(command, service if connected else 1)
        pytest.fail(f"unexpected provisioning or interactive command: {command}")

    monkeypatch.setattr(ship.subprocess, "run", run)
    monkeypatch.setattr(ship.sys, "argv", ["ship.sh", "setup", "--config", str(host)])
    ready = github == 0 and models == '{"models":[{}]}' and questions_done and service == 0
    assert ship.main() == (0 if ready else 1)
    output = capsys.readouterr().out
    assert output.startswith("Software: ready\n")
    assert len(output.splitlines()) == 3
    assert expected in output
    if not ready:
        assert "Fleet ready: no" in output
        assert "setup checks passed" not in output
        assert shlex.quote(str(host)) in output


def test_setup_preserves_a_missing_explicit_config_path(tmp_path, monkeypatch, capsys):
    selected = tmp_path / "selected host.yml"
    monkeypatch.setattr(ship.sys, "argv", ["ship.sh", "setup", "--config", str(selected)])
    assert ship.main() == 1
    output = capsys.readouterr().out
    assert f"${{EDITOR:-nano}} {shlex.quote(str(selected))}" in output
    assert "dock" not in output


def test_apply_warns_when_firstmate_still_tracks_the_stale_fork(
    configuration, tmp_path, monkeypatch, capsys
):
    configuration["crewship"]["firstmate"]["url"] = ship.STALE_FIRSTMATE_URL
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump(configuration))
    monkeypatch.setattr(ship, "provision", lambda document, check: 0)
    monkeypatch.setattr(ship.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(ship.sys, "argv", ["ship.sh", "launch", "--config", str(host)])
    assert ship.main() == 0
    output = capsys.readouterr()
    assert output.err.startswith("WARNING: firstmate.url is the stale fork")
    assert "rerun ./ship.sh launch interactively" in output.out


def _verify_firstmate(tmp_path, origin, configured):
    checkout = tmp_path / "firstmate"
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-C", str(checkout)]
    subprocess.run(["git", "init", "-q", "-b", "main", str(checkout)], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "c"], check=True)
    subprocess.run([*git, "remote", "add", "origin", origin], check=True)
    head = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    playbook = tmp_path / "verify.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/verify.yml")}
                    ],
                }
            ]
        )
    )
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship_account_ready": True,
        "crewship_become_target": False,
        "crewship_user_env": {},
        "crewship_manage_services": False,
        "crewship_user_units": str(tmp_path),
        "crewship_docker_group_users": [],
        "crewship_firstmate_dir": str(checkout),
        # No patches: the expected head is origin/main itself.
        "crewship_firstmate_patch_dir": str(tmp_path),
        "crewship_firstmate_target": head,
        "crewship_cfg": {
            "user": "coder",
            "profiles": {
                "agents": False,
                "firstmate": True,
                "docker": False,
                "tailscale": False,
                "desktop": False,
                "gateway": False,
            },
            "firstmate": {"url": configured},
        },
    }
    return subprocess.run(
        [
            Path(sys.executable).parent / "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "--start-at-task",
            "Read the Firstmate origin URL",
            "--extra-vars",
            json.dumps(variables),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_verify_fails_when_firstmate_origin_is_not_the_configured_url(tmp_path):
    upstream = "https://github.com/kunchenguid/firstmate.git"
    result = _verify_firstmate(tmp_path, ship.STALE_FIRSTMATE_URL, upstream)
    assert result.returncode != 0
    assert "updated the wrong repository" in result.stdout


def test_verify_passes_when_firstmate_origin_is_the_configured_url(tmp_path):
    upstream = "https://github.com/kunchenguid/firstmate.git"
    result = _verify_firstmate(tmp_path, upstream, upstream)
    assert result.returncode == 0, result.stdout


def _run_agents(tmp_path, start_at, **variables):
    playbook = tmp_path / "agents.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/agents.yml")}
                    ],
                    "handlers": [
                        {
                            "name": "no-mistakes daemon restart required",
                            "ansible.builtin.debug": {"msg": "restart reported"},
                        }
                    ],
                }
            ]
        )
    )
    result = subprocess.run(
        [
            Path(sys.executable).parent / "ansible-playbook",
            "-i",
            "localhost,",
            str(playbook),
            "--start-at-task",
            start_at,
            "--extra-vars",
            json.dumps({"ansible_become": False, **variables}),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return int(result.stdout.rsplit("changed=", 1)[1].split()[0])


def _ensure_status_row(tmp_path, config):
    return _run_agents(
        tmp_path,
        "Read the omp config for the status row keys",
        crewship_omp_config=str(config),
        crewship_acpx_config=str(tmp_path / "absent-acpx.json"),
    )


def _ensure_acpx_default(tmp_path, config):
    return _run_agents(
        tmp_path, "Read the acpx config for the default agent", crewship_acpx_config=str(config)
    )


def test_existing_omp_config_gets_the_status_row_keys_once(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(
        "# the account's own\n"
        "theme: {dark: titanium}\n"
        "statusLine:\n"
        "  preset: custom\n"
        "  leftSegments: [path, git]\n"
        "  showHookStatus: true\n"
        "  separator: plain\n"
        "providers:\n"
        "  anthropic: {serverSideFallback: false}\n"
    )
    config.chmod(0o600)
    assert _ensure_status_row(tmp_path, config) == 1
    assert yaml.safe_load(config.read_text()) == {
        "theme": {"dark": "titanium"},
        "statusLine": {
            "preset": "custom",
            "leftSegments": ["path", "git", "status"],
            "showHookStatus": False,
            "separator": "plain",
        },
        "providers": {"anthropic": {"serverSideFallback": False}},
    }
    assert config.stat().st_mode & 0o777 == 0o600
    written = config.read_text()
    assert _ensure_status_row(tmp_path, config) == 0
    assert config.read_text() == written


def test_omp_config_that_has_the_status_row_keys_is_left_alone(tmp_path):
    config = tmp_path / "config.yml"
    seed = (ROOT / "blueprint/config/omp.yml").read_text()
    config.write_text(seed)
    assert _ensure_status_row(tmp_path, config) == 0
    assert config.read_text() == seed


@pytest.mark.parametrize(
    "text",
    [
        "theme: {dark: titanium}\n",
        "statusLine:\n  preset: default\n  showHookStatus: true\n",
        "statusLine:\n  leftSegments: [path, git]\n  showHookStatus: true\n",
    ],
)
def test_omp_config_without_the_custom_preset_is_left_alone(tmp_path, text):
    config = tmp_path / "config.yml"
    config.write_text(text)
    assert _ensure_status_row(tmp_path, config) == 0
    assert config.read_text() == text


def test_absent_omp_config_is_not_created_by_the_status_row_step(tmp_path):
    config = tmp_path / "config.yml"
    assert _ensure_status_row(tmp_path, config) == 0
    assert not config.exists()


def test_acpx_config_that_still_defaults_to_codex_gets_omp_once(tmp_path):
    config = tmp_path / "config.json"
    seed = json.loads((ROOT / "blueprint/config/acpx.json").read_text())
    config.write_text(json.dumps({**seed, "defaultAgent": "codex", "ttl": 900}))
    config.chmod(0o600)
    assert _ensure_acpx_default(tmp_path, config) == 1
    assert json.loads(config.read_text()) == {**seed, "ttl": 900}
    assert config.stat().st_mode & 0o777 == 0o600
    written = config.read_text()
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert config.read_text() == written


@pytest.mark.parametrize("text", ['{"defaultAgent": "claude"}\n', '{"ttl": 300}\n'])
def test_acpx_config_with_another_default_is_left_alone(tmp_path, text):
    config = tmp_path / "config.json"
    config.write_text(text)
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert config.read_text() == text


def test_seeded_acpx_config_defaults_to_omp_and_absent_one_is_not_created(tmp_path):
    config = tmp_path / "config.json"
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert not config.exists()
    seed = (ROOT / "blueprint/config/acpx.json").read_text()
    config.write_text(seed)
    assert _ensure_acpx_default(tmp_path, config) == 0
    assert config.read_text() == seed


PI_AGENT = {
    "agent": "pi",
    "agent_config": {"pi": {"model": "anthropic/claude-sonnet-5-5", "effort": "high"}},
}


def _set_pipeline_agent(tmp_path, rc):
    """Runs the agent step with the adapter check's exit code; returns the changed count."""
    return _run_agents(
        tmp_path,
        "Read the no-mistakes config for the pipeline agent",
        crewship_cfg={"home": str(tmp_path)},
        crewship_omp_as_pi_dir="/w",
        crewship_pi_adapter={"rc": rc, "stdout": "pi.go changed"},
        crewship_omp_config=str(tmp_path / "absent-omp.yml"),
        crewship_acpx_config=str(tmp_path / "absent-acpx.json"),
    )


def test_verified_pi_adapter_moves_the_seeded_agent_to_pi_once(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text((ROOT / "blueprint/config/no-mistakes.yaml").read_text() + "log_level: info\n")
    assert _set_pipeline_agent(tmp_path, rc=0) == 1
    assert yaml.safe_load(config.read_text()) == {
        **PI_AGENT,
        "agent_path_override": {"pi": "/w/omp-as-pi"},
        "log_level": "info",
    }
    written = config.read_text()
    assert _set_pipeline_agent(tmp_path, rc=0) == 0
    assert config.read_text() == written


def test_a_host_already_on_pi_moves_from_xhigh_to_high_once(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    previous = {
        **PI_AGENT,
        "agent_config": {"pi": {"model": "anthropic/claude-sonnet-5-5", "effort": "xhigh"}},
        "agent_path_override": {"pi": "/w/omp-as-pi"},
    }
    config.write_text(yaml.safe_dump(previous))
    assert _set_pipeline_agent(tmp_path, rc=0) == 1
    assert yaml.safe_load(config.read_text())["agent_config"] == PI_AGENT["agent_config"]
    assert _set_pipeline_agent(tmp_path, rc=0) == 0


def test_previous_pi_acp_list_moves_to_pi_only(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump({
        **PI_AGENT,
        "agent": ["pi", "acp:omp"],
        "agent_path_override": {"pi": "/w/omp-as-pi"},
    }))
    assert _set_pipeline_agent(tmp_path, rc=0) == 1
    assert yaml.safe_load(config.read_text())["agent"] == "pi"
    assert _set_pipeline_agent(tmp_path, rc=0) == 0


def test_a_pin_mismatch_moves_the_agent_to_acp_omp_alone(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text(yaml.safe_dump({**PI_AGENT, "agent_path_override": {"pi": "/w/omp-as-pi"}}))
    assert _set_pipeline_agent(tmp_path, rc=1) == 1
    assert yaml.safe_load(config.read_text())["agent"] == ["acp:omp"]
    seed = (ROOT / "blueprint/config/no-mistakes.yaml").read_text()
    config.write_text(seed)
    assert _set_pipeline_agent(tmp_path, rc=1) == 0
    assert config.read_text() == seed


@pytest.mark.parametrize("rc", [2, 127])
def test_an_inconclusive_adapter_check_leaves_the_agent_setting_alone(tmp_path, rc):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    for text in (
        yaml.safe_dump({**PI_AGENT, "agent_path_override": {"pi": "/w/omp-as-pi"}}),
        (ROOT / "blueprint/config/no-mistakes.yaml").read_text(),
    ):
        config.write_text(text)
        assert _set_pipeline_agent(tmp_path, rc=rc) == 0
        assert config.read_text() == text


def test_operator_chosen_agent_is_left_alone(tmp_path):
    config = tmp_path / ".no-mistakes/config.yaml"
    config.parent.mkdir()
    config.write_text("agent: [claude]\n")
    assert _set_pipeline_agent(tmp_path, rc=0) == 0
    assert config.read_text() == "agent: [claude]\n"


def _managed_environment(tmp_path, fleet_guards, release="1.0.0"):
    variables = {
        "crewship_cfg": {"home": str(tmp_path), "profiles": {"fleet_guards": fleet_guards}},
        "crewship_latest": {"chrome-devtools-mcp": release},
    }
    result = subprocess.run(
        [
            Path(sys.executable).parent / "ansible",
            "localhost",
            "-i",
            "localhost,",
            "-c",
            "local",
            "-m",
            "ansible.builtin.debug",
            "-a",
            "var=crewship_managed_shell_env",
            *GROUP_VARS_ARGS,
            "-e",
            json.dumps(variables),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout
    return json.loads(result.stdout.split("=>", 1)[1])["crewship_managed_shell_env"]


@pytest.mark.parametrize("fleet_guards", [False, True])
def test_the_managed_environment_never_carries_a_process_wide_runtime_limit(tmp_path, fleet_guards):
    assert set(_managed_environment(tmp_path, fleet_guards)) == {"CHROME_DEVTOOLS_AXI_MCP_PATH"}


def test_a_new_chrome_devtools_mcp_release_leaves_the_managed_environment_unchanged(tmp_path):
    before = _managed_environment(tmp_path, True, "1.0.0")
    assert _managed_environment(tmp_path, True, "1.1.0") == before
    assert before["CHROME_DEVTOOLS_AXI_MCP_PATH"].endswith(
        "/chrome-devtools-mcp/current/node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js"
    )


def test_board_environment_reaches_new_shells_and_agents_and_is_removed_on_opt_out(tmp_path):
    profile_task = next(
        task["ansible.builtin.blockinfile"]
        for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
        if "block" in task.get("ansible.builtin.blockinfile", {})
    )
    profile = tmp_path / ".profile"
    unit = tmp_path / "herdr.service"
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship_cfg": {
            "home": str(tmp_path),
            "workspace": str(tmp_path),
            "data_dir": str(tmp_path / "data"),
            "profiles": {"agents": True},
        },
        "crewship_user_uid": 12345,
        "crewship_platform": "linux-x86_64",
        "crewship_latest": {"herdr": {"version": "1.0.0"}},
        "crewship_fleet_browsers_enabled": False,
        "ansible_managed": "Managed by Crewship",
    }
    modules = [
        ("ansible.builtin.template", {
            "src": str(ROOT / "blueprint/ansible/templates/herdr.service.j2"), "dest": str(unit),
        }),
        ("ansible.builtin.blockinfile", {
            **{key: profile_task[key] for key in ("block", "marker", "create")},
            "path": str(profile),
        }),
    ]
    for board in (None, {}, None):
        if board is None:
            variables["crewship_cfg"].pop("board", None)
        else:
            variables["crewship_cfg"]["board"] = board
        for repeat in range(2):
            for module, arguments in modules:
                result = _ansible(
                    tmp_path, "ansible", "localhost", "-i", "localhost,", "-c", "local",
                    "-m", module, "-a", json.dumps(arguments),
                    *GROUP_VARS_ARGS,
                    "-e", json.dumps(variables),
                )
                assert result.returncode == 0, result.stdout + result.stderr
                if repeat:
                    assert '"changed": false' in result.stdout, result.stdout
        socket = "/run/user/12345/crewboard.sock"
        assert (f'Environment="CREWBOARD_SOCKET={socket}"' in unit.read_text()) is (
            board is not None
        )
        shell = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c",
             'source "$1"; printf "%s\\n%s\\n" "${CREWBOARD_SOCKET-unset}" '
             '"$CHROME_DEVTOOLS_AXI_MCP_PATH"', "bash", str(profile)],
            env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
            capture_output=True, text=True, check=True,
        )
        assert shell.stdout.splitlines() == [
            socket if board is not None else "unset",
            f"{tmp_path}/.local/share/crewship/chrome-devtools-mcp/current/"
            "node_modules/chrome-devtools-mcp/build/src/bin/chrome-devtools-mcp.js",
        ]


BULK_UNIT_LINES = (
    'Environment="npm_config_cache=/data/cache/npm"\n'
    'Environment="PIP_CACHE_DIR=/data/cache/pip"\n'
    'Environment="TMPDIR=/data/tmp"\n'
    'Environment="DENO_DIR=/data/cache/deno"\n'
    'Environment="BUN_RUNTIME_TRANSPILER_CACHE_PATH=/data/cache/bun-transpiler"\n'
    'Environment="TMP=/data/tmp"\n'
    'Environment="TEMP=/data/tmp"\n'
)


@pytest.mark.parametrize(
    ("seed", "check", "restart"),
    [
        (None, False, True),
        ("", False, False),
        (BULK_UNIT_LINES, False, False),
        (BULK_UNIT_LINES, True, False),
        ("ExecStart=/old/herdr server\n", False, True),
        (BULK_UNIT_LINES + "ExecStart=/old/herdr server\n", True, True),
    ],
    ids=["first-install", "unchanged", "bulk-only", "bulk-only-check", "ordinary", "combined-check"],
)
def test_herdr_restarts_only_for_a_unit_change_beyond_the_data_disk_environment(
    tmp_path, seed, check, restart
):
    names = {
        "Read the installed Herdr user unit",
        "Render the Herdr user unit",
        "Restart Herdr for a unit change beyond the data-disk environment",
    }
    tasks = [
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/herdr.yml").read_text())
        if task.get("name") in names
    ]
    assert len(tasks) == len(names)
    playbook = tmp_path / "herdr.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False, "tasks": tasks,
        "handlers": [
            {"name": name, "ansible.builtin.debug": {"msg": name}}
            for name in ("reload user systemd", "restart herdr")
        ],
    }]))
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    unit = tmp_path / ".config/systemd/user/herdr.service"
    unit.parent.mkdir(parents=True)
    variables = {
        "ansible_become": False,
        "crewship_cfg": {
            "user": getpass.getuser(),
            "home": str(tmp_path),
            "workspace": str(tmp_path),
            "profiles": {"agents": True},
        },
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_user_uid": 12345,
        "crewship_platform": "linux-x86_64",
        "crewship_latest": {"herdr": {"version": "1.0.0"}},
        "crewship_fleet_browsers_enabled": False,
        "ansible_managed": "Managed by Crewship",
    }

    def apply(*options):
        result = _ansible(
            tmp_path, "ansible-playbook", "-i", "localhost,", str(playbook), *options,
            *GROUP_VARS_ARGS, "-e", json.dumps(variables),
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    if seed is not None:
        apply()
        unit.write_text(unit.read_text().replace("[Service]\n", "[Service]\n" + seed))
    seeded = unit.read_text() if unit.exists() else None
    output = apply(*(["--check"] if check else []))
    assert ("RUNNING HANDLER [restart herdr]" in output) is restart, output
    assert ("RUNNING HANDLER [reload user systemd]" in output) is (seed != ""), output
    if check:
        assert unit.read_text() == seeded
    else:
        assert "=/data/" not in unit.read_text()
        assert "RUNNING HANDLER" not in apply()


def _ansible(tmp_path, *argv, wrapper=()):
    return subprocess.run(
        [*wrapper, Path(sys.executable).parent / argv[0], *argv[1:]],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def _installer_also(
    tmp_path, start_services=True, fleet_guards=False, fleet_browsers=False, koncreet=None
):
    variables = {
        "crewship_cfg": {
            "start_services": start_services,
            "profiles": {
                "agents": False,
                "fleet_guards": fleet_guards,
                "fleet_browsers": fleet_browsers,
                **({} if koncreet is None else {"koncreet": koncreet}),
            },
            "browser_prune": {"enabled": False},
        }
    }
    result = _ansible(
        tmp_path,
        "ansible",
        "localhost",
        "-i",
        "localhost,",
        "-c",
        "local",
        "-m",
        "ansible.builtin.debug",
        "-a",
        "var=crewship_installer_also",
        *GROUP_VARS_ARGS,
        "-e",
        json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout
    return json.loads(result.stdout.split("=>", 1)[1])["crewship_installer_also"]


@pytest.mark.parametrize("start_services", [True, False])
def test_koncreet_is_resolved_only_on_hosts_that_start_services(tmp_path, start_services):
    assert ("koncreet" in _installer_also(tmp_path, start_services)) is start_services


@pytest.mark.parametrize("koncreet, resolved", [(None, True), (True, True), (False, False)])
def test_koncreet_follows_its_profile_and_an_absent_key_keeps_it(tmp_path, koncreet, resolved):
    assert ("koncreet" in _installer_also(tmp_path, koncreet=koncreet)) is resolved


@pytest.mark.parametrize("fleet_guards", [False, True])
@pytest.mark.parametrize("fleet_browsers", [False, True])
def test_each_fleet_profile_resolves_only_its_own_release(
    tmp_path, fleet_guards, fleet_browsers
):
    also = _installer_also(
        tmp_path,
        fleet_guards=fleet_guards,
        fleet_browsers=fleet_browsers,
    )
    assert ("obscura" in also) is (fleet_guards or fleet_browsers)


def _koncreet_settings(tmp_path, tailscale, apply_user):
    destination = tmp_path / "koncreet.conf"
    variables = {
        "ansible_user_id": apply_user,
        "ansible_user_dir": "/root" if apply_user == "root" else f"/home/{apply_user}",
        "crewship_cfg": {"user": "coder", "profiles": {"tailscale": tailscale}},
        "crewship_koncreet_config": "/etc/koncreet.conf",
    }
    result = _ansible(
        tmp_path,
        "ansible",
        "localhost",
        "-i",
        "localhost,",
        "-c",
        "local",
        "-m",
        "ansible.builtin.template",
        "-a",
        f"src={ROOT / 'blueprint/ansible/templates/koncreet.conf.j2'} dest={destination}",
        "-e",
        json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout
    return dict(
        line.split("=", 1)
        for line in destination.read_text().splitlines()
        if line and not line.startswith("#")
    )


@pytest.mark.parametrize(
    ("tailscale", "apply_user", "ports", "sudo_user"),
    [
        (True, "operator", "41641/udp", "operator"),
        (False, "operator", None, "operator"),
        (True, "coder", "41641/udp", None),
        (False, "root", None, None),
    ],
)
def test_koncreet_config_follows_the_tailscale_profile_and_never_makes_the_crewship_user_sudo(
    tmp_path, tailscale, apply_user, ports, sudo_user
):
    settings = _koncreet_settings(tmp_path, tailscale, apply_user)
    assert settings["modules"] == "baseline,firewall,fail2ban,updates"
    assert settings.get("firewall_ports") == ports
    assert settings.get("user") == sudo_user
    assert settings.get("pubkey_file") == (
        f"/home/{sudo_user}/.ssh/authorized_keys" if sudo_user else None
    )


def _run_koncreet_tasks(tmp_path, digest, *flags):
    payload = tmp_path / "payload"
    payload.write_text("#!/bin/sh\n")
    source = tmp_path / "koncreet.tar.gz"
    with tarfile.open(source, "w:gz") as archive:
        archive.add(payload, arcname="koncreet/koncreet")
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": False,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/koncreet.yml")},
                        {
                            "name": "A later task",
                            "ansible.builtin.file": {
                                "path": str(tmp_path / "later"),
                                "state": "touch",
                            },
                        },
                    ],
                }
            ]
        )
    )
    variables = {
        "ansible_become": False,
        "ansible_user_id": "operator",
        "ansible_user_dir": "/home/operator",
        "crewship_cfg": {"user": "coder", "profiles": {"tailscale": False}},
        "crewship_latest": {"koncreet": {"version": "9.9.9"}},
        "crewship_koncreet": {"url": source.as_uri(), "sha256": digest},
        "crewship_koncreet_patch": str(ROOT / "blueprint/patches/koncreet/ubuntu-26.04.patch"),
        "crewship_koncreet_prefix": str(tmp_path / "prefix"),
        "crewship_koncreet_config": str(tmp_path / "koncreet.conf"),
    }
    # koncreet.yml hands its files to root. Unprivileged, the chown fails before the
    # download is ever checked, so a digest test would pass for the wrong reason.
    # Plan mode (--check) creates nothing and needs no root.
    wrapper = () if os.geteuid() == 0 or "--check" in flags else ("fakeroot",)
    if wrapper and not shutil.which("fakeroot"):
        pytest.skip("koncreet.yml chowns to root: run as root or install fakeroot")
    return _ansible(
        tmp_path,
        "ansible-playbook",
        "-i",
        "localhost,",
        str(playbook),
        "--extra-vars",
        json.dumps(variables),
        *flags,
        wrapper=wrapper,
    )


def test_a_koncreet_tarball_that_fails_its_digest_is_skipped_and_apply_continues(tmp_path):
    result = _run_koncreet_tasks(tmp_path, "0" * 64)
    assert result.returncode == 0, result.stdout
    assert "WARNING: koncreet skipped" in result.stdout
    assert "Fetch the koncreet tarball: The checksum for" in result.stdout
    assert (tmp_path / "later").exists()
    assert not list((tmp_path / "prefix").rglob("patch-outcome"))
    assert not list((tmp_path / "prefix").rglob("*.tar.gz"))
    assert not (tmp_path / "koncreet.conf").exists()


def test_planning_koncreet_installs_nothing_and_warns_of_nothing(tmp_path):
    result = _run_koncreet_tasks(tmp_path, "0" * 64, "--check")
    assert result.returncode == 0, result.stdout
    assert "WARNING" not in result.stdout
    assert not (tmp_path / "prefix").exists()


def test_mac_ssh_keeps_the_existing_key_and_other_host_entries(tmp_path):
    home = tmp_path / "home"
    (home / ".ssh").mkdir(parents=True)
    other = "Host build\n  HostName build.example\n"
    (home / ".ssh/config").write_text(other)
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(
        yaml.safe_dump(
            [
                {
                    "hosts": "localhost",
                    "connection": "local",
                    "gather_facts": True,
                    "tasks": [
                        {"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/mac_ssh.yml")}
                    ],
                }
            ]
        )
    )
    variables = {
        "crewship_cfg": {
            "user": "coder",
            "home": str(home),
            "mac_ssh": {"host": "mac.example", "user": "operator"},
        },
        "crewship_mac_ssh_key": str(home / ".ssh/id_ed25519_mac"),
    }

    def apply():
        result = _ansible(
            tmp_path, "ansible-playbook", "-i", "localhost,", str(playbook),
            "--extra-vars", json.dumps(variables),
        )
        assert result.returncode == 0, result.stdout
        return result.stdout

    first = apply()
    key = (home / ".ssh/id_ed25519_mac").read_bytes()
    public = (home / ".ssh/id_ed25519_mac.pub").read_text().strip()
    config = (home / ".ssh/config").read_text()
    line = (home / ".ssh/id_ed25519_mac.authorized_keys").read_text()
    assert line.startswith('from="') and line.endswith(f'" {public}\n')
    assert public in first and "PRIVATE KEY" not in first
    assert config.endswith(other) and config.splitlines().count("Host mac") == 1
    assert "IdentitiesOnly yes" in config

    second = apply()
    assert "changed=0" in second
    assert (home / ".ssh/id_ed25519_mac").read_bytes() == key
    assert (home / ".ssh/config").read_text() == config


def test_herdr_config_does_not_resume_agents_on_restore():
    import tomllib

    import jinja2

    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    env.filters.update(comment=lambda text: "", bool=bool)
    source = (ROOT / "blueprint/ansible/templates/herdr.toml.j2").read_text()
    class Anything(dict):
        def __getattr__(self, name):
            return Anything()

        def __int__(self):
            return 1

        def __str__(self):
            return "1"

    config = tomllib.loads(env.from_string(source).render(crewship_cfg=Anything()))
    assert config["session"] == {"resume_agents_on_restore": False}


@pytest.mark.parametrize("state", ["unset", "empty", "inherited", "task"])
def test_bulk_environment_defaults_preserve_explicit_values_across_consumers(
    tmp_path, monkeypatch, state
):
    home = tmp_path / "home"
    units = home / ".config/systemd/user"
    (units / "no-mistakes-daemon-.service.d").mkdir(parents=True)
    (home / ".config/environment.d").mkdir()
    data = tmp_path / "data"
    defaults = {
        "DENO_DIR": str(data / "cache/deno"),
        "BUN_RUNTIME_TRANSPILER_CACHE_PATH": str(data / "cache/bun-transpiler"),
        "TMPDIR": str(data / "tmp"), "TMP": str(data / "tmp"), "TEMP": str(data / "tmp"),
    }
    for key in defaults:
        monkeypatch.delenv(key, raising=False)
        if state != "unset":
            monkeypatch.setenv(key, "/operator/scratch" if state == "inherited" else "")
    observed = tmp_path / "installer.json"
    observer = tmp_path / "installer probe.py"
    observer.write_text(
        "import json, os, pathlib, sys\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps("
        "{key: os.environ.get(key) for key in sys.argv[2:]}))\n"
        "print(json.dumps({'changed': False}))\n"
    )
    account = yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
    tasks = [
        task for task in account
        if task["name"] in {
            "Write bulk defaults for future user-manager processes",
            "Keep the managed bin directory and environment on the interactive shell",
        }
    ]
    tasks.append(next(
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/tools.yml").read_text())
        if task["name"] == "Install the toolchain as the target user"
    ))
    tasks.append({
        "ansible.builtin.template": {
            "src": str(ROOT / "blueprint/ansible/templates/herdr.service.j2"),
            "dest": str(units / "herdr.service"),
        },
    })
    tasks.append(next(
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
        if task.get("ansible.builtin.copy", {}).get("dest", "").endswith(
            "/no-mistakes-daemon-.service.d/crewship.conf"
        )
    ))
    playbook = tmp_path / "environment.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "tasks": tasks,
        "handlers": [
            {"name": name, "ansible.builtin.debug": {"msg": name}}
            for name in ("reload user systemd", "no-mistakes daemon restart required")
        ],
    }]))
    variables = {
        "ansible_become": False,
        "crewship_repo": str(ROOT),
        "crewship_cfg": {
            "user": getpass.getuser(), "home": str(home), "workspace": str(home),
            "data_dir": str(data), "profiles": {"agents": True},
        },
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_account_ready": True, "crewship_become_target": False,
        "crewship_platform": "linux-x86_64",
        "crewship_latest": {"herdr": {"version": "1.0.0"}},
        "crewship_fleet_browsers_enabled": False,
        "crewship_installer_argv": [sys.executable, str(observer), str(observed), *defaults],
        "crewship_user_env": {
            "HOME": str(home), "PATH": os.environ["PATH"],
            **({key: "/task/scratch" for key in defaults} if state == "task" else {}),
        },
    }
    result = _ansible(
        tmp_path, "ansible-playbook", "-i", "localhost,", str(playbook),
        *GROUP_VARS_ARGS, "-e", json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    inherited = (
        {key: "/operator/scratch" for key in defaults} if state == "inherited" else defaults
    )
    assert json.loads(observed.read_text()) == (
        {key: "/task/scratch" for key in defaults} if state == "task" else inherited
    )
    reader = [
        sys.executable, "-c",
        "import json, os, sys; print(json.dumps({key: os.environ.get(key) for key in sys.argv[1:]}))",
        *defaults,
    ]
    for path in (
        home / ".profile", home / ".bashrc",
        home / ".config/environment.d/60-crewship-bulk.conf",
    ):
        shell = subprocess.run(
            ["/bin/sh", "-c", 'set -a; . "$1"; shift; exec "$@"', "sh", str(path), *reader],
            capture_output=True, text=True, check=True,
        )
        assert json.loads(shell.stdout) == inherited
    for path in (units / "herdr.service", units / "no-mistakes-daemon-.service.d/crewship.conf"):
        environment = dict(
            entry.split("=", 1)
            for line in path.read_text().splitlines() if line.startswith("Environment=")
            for entry in shlex.split(line.partition("=")[2])
        )
        assert {key: (inherited | environment)[key] for key in defaults} == inherited


def _account_play(tmp_path, names, variables, *options, tasks=(), handlers=()):
    selected = [
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
        if task["name"] in names
    ]
    assert len(selected) == len(names)
    playbook = tmp_path / "account.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "tasks": [*selected, *tasks], "handlers": list(handlers),
    }]))
    result = _ansible(
        tmp_path, "ansible-playbook", "-i", "localhost,", str(playbook), *options,
        *GROUP_VARS_ARGS, "-e", json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_legacy_bash_block_removal_tolerates_a_missing_bashrc_and_keeps_other_lines(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    bashrc = home / ".bashrc"
    names = {"Remove the retired managed Bash environment block"}
    variables = {
        "crewship_cfg": {"user": getpass.getuser(), "home": str(home), "data_dir": ""},
        "crewship_account_ready": True, "crewship_become_target": False,
    }
    for options in (["--check"], []):
        _account_play(tmp_path, names, variables, *options)
        assert not bashrc.exists()
    seeded = (
        "alias ll='ls -l'\n# BEGIN crewship managed environment\nexport TMPDIR=/old/tmp\n"
        "# END crewship managed environment\nexport EDITOR=vi\n"
    )
    bashrc.write_text(seeded)
    for options, expected in ((["--check"], seeded), ([], "alias ll='ls -l'\nexport EDITOR=vi\n")):
        _account_play(tmp_path, names, variables, *options)
        assert bashrc.read_text() == expected


@pytest.mark.parametrize(
    ("active", "manage", "check", "write", "fresh_unit", "ordinary"),
    [
        (False, True, False, True, False, False),
        (True, True, False, True, False, False),
        (False, False, False, True, False, False),
        (False, True, True, True, False, False),
        (False, True, False, True, True, False),
        (False, True, False, False, False, False),
        (True, True, False, False, False, False),
        (True, True, False, True, False, True),
    ],
    ids=["stopped", "active", "disabled", "preview", "fresh-disk-stale-cache",
         "remove-stopped", "remove-active", "ordinary-restart"],
)
def test_herdr_start_uses_reloaded_manager_and_unit_without_bulk_restart(
    tmp_path, active, manage, check, write, fresh_unit, ordinary
):
    home = tmp_path / "home"
    conf = home / ".config/environment.d/60-crewship-bulk.conf"
    conf.parent.mkdir(parents=True)
    unit = home / ".config/systemd/user/herdr.service"
    unit.parent.mkdir(parents=True)
    data = tmp_path / "data"
    defaults = {
        "DENO_DIR": f"{data}/cache/deno",
        "BUN_RUNTIME_TRANSPILER_CACHE_PATH": f"{data}/cache/bun-transpiler",
        "TMPDIR": f"{data}/tmp", "TMP": f"{data}/tmp", "TEMP": f"{data}/tmp",
    }
    stale = {key: f"/old/{key}" for key in defaults}
    retired = {"npm_config_cache": "/old/npm", "PIP_CACHE_DIR": "/old/pip"}
    conf.write_text("".join(f"{key}={value}\n" for key, value in stale.items()))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    probe = binaries / "service-probe"
    probe.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(600)\n")
    probe.chmod(0o755)
    systemctl = binaries / "systemctl"
    systemctl.write_text(
        f"#!{sys.executable}\n"
        "import json, os, pathlib, shlex, signal, subprocess, sys\n"
        "root = pathlib.Path(os.environ['CREWSHIP_TEST_MANAGER'])\n"
        "home = root / 'home'\n"
        "config = home / '.config/environment.d/60-crewship-bulk.conf'\n"
        "unit = home / '.config/systemd/user/herdr.service'\n"
        "state = root / 'manager.json'\n"
        "pid = root / 'service.pid'\n"
        "assert sys.argv[1] == '--user'\n"
        "action = sys.argv[2]\n"
        "if action == 'daemon-reload':\n"
        "    environment = json.loads(subprocess.run(\n"
        "        ['/bin/sh', '-c', 'set -a; [ ! -e \"$1\" ] || . \"$1\"; shift; exec \"$@\"',\n"
        "         'sh', str(config), sys.executable, '-c',\n"
        "         'import json, os; print(json.dumps(dict(os.environ)))'],\n"
        "        env={}, capture_output=True, text=True, check=True,\n"
        "    ).stdout)\n"
        "    arguments = []\n"
        "    for line in unit.read_text().splitlines():\n"
        "        key, _, value = line.partition('=')\n"
        "        if key == 'Environment':\n"
        "            environment.update(item.split('=', 1) for item in shlex.split(value))\n"
        "        elif key == 'ExecStart':\n"
        "            arguments = shlex.split(value)\n"
        "    state.write_text(json.dumps({'environment': environment, 'arguments': arguments}))\n"
        "elif action == 'show':\n"
        "    print('LoadState=loaded\\nActiveState=' + ('active' if pid.exists() else 'inactive'))\n"
        "elif action == 'is-enabled':\n"
        "    print('enabled')\n"
        "elif action in ('start', 'restart'):\n"
        "    if action == 'restart' and pid.exists():\n"
        "        os.kill(int(pid.read_text()), signal.SIGKILL)\n"
        "        pid.unlink()\n"
        "    if not pid.exists():\n"
        "        cached = json.loads(state.read_text())\n"
        "        child = subprocess.Popen(cached['arguments'], env=cached['environment'],\n"
        "            start_new_session=True, stdin=subprocess.DEVNULL,\n"
        "            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "        pid.write_text(str(child.pid))\n"
        "else:\n"
        "    raise AssertionError(sys.argv)\n"
    )
    systemctl.chmod(0o755)
    manager_env = {
        "PATH": f"{binaries}:{os.environ['PATH']}",
        "CREWSHIP_TEST_MANAGER": str(tmp_path),
    }
    variables = {
        "ansible_become": False,
        "crewship_cfg": {
            "user": getpass.getuser(), "home": str(home), "workspace": str(home),
            "data_dir": str(data) if write else "", "start_services": manage,
            "profiles": {"agents": True},
        },
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_account_ready": True, "crewship_become_target": False,
        "crewship_herdr_bin": str(probe),
        "crewship_user_systemd_env": manager_env,
        "crewship_platform": "linux-x86_64",
        "crewship_latest": {"herdr": {"version": "1.0.0"}},
        "crewship_fleet_browsers_enabled": False,
        "ansible_managed": "Managed by Crewship",
    }
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    result = _ansible(
        tmp_path, "ansible", "localhost", "-i", "localhost,", "-c", "local",
        "-m", "ansible.builtin.template", "-a", json.dumps({
            "src": str(ROOT / "blueprint/ansible/templates/herdr.service.j2"), "dest": str(unit),
        }), *GROUP_VARS_ARGS, "-e", json.dumps(variables),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    current_unit = unit.read_text()
    old_unit = current_unit.replace(
        "[Service]\n", "[Service]\n" + "".join(
            f'Environment="{key}={value}"\n' for key, value in (stale | retired).items()
        ),
    )
    if ordinary:
        old_unit = old_unit.replace("Description=", "Description=Old ")
    unit.write_text(old_unit)
    command = [str(systemctl), "--user"]
    subprocess.run([*command, "daemon-reload"], env={**os.environ, **manager_env}, check=True)
    if active:
        subprocess.run([*command, "start", "herdr.service"], env={**os.environ, **manager_env}, check=True)
    if fresh_unit:
        unit.write_text(current_unit)
        copy = next(
            task["ansible.builtin.copy"]
            for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
            if task["name"] == "Write bulk defaults for future user-manager processes"
        )
        result = _ansible(
            tmp_path, "ansible", "localhost", "-i", "localhost,", "-c", "local",
            "-m", "ansible.builtin.copy", "-a", json.dumps(copy),
            *GROUP_VARS_ARGS, "-e", json.dumps(variables),
        )
        assert result.returncode == 0, result.stdout + result.stderr
    pid_file = tmp_path / "service.pid"

    def service():
        pid = int(pid_file.read_text())
        entries = (
            entry.partition("=")
            for entry in Path("/proc", str(pid), "environ").read_text().split("\0")
        )
        return pid, {key: value for key, _, value in entries if key in (defaults | retired)}

    before = service() if active else None
    herdr_names = {
        "Read the installed Herdr user unit", "Render the Herdr user unit",
        "Restart Herdr for a unit change beyond the data-disk environment",
        "Check for the installed Herdr user service",
        "Enable and start the Herdr user service",
    }
    herdr_tasks = [
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/herdr.yml").read_text())
        if task["name"] in herdr_names
    ]
    handlers = [
        handler
        for play in yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())
        for handler in play.get("handlers", [])
        if handler.get("listen") in ("reload user systemd", "restart herdr")
    ]
    try:
        _account_play(
            tmp_path,
            {
                "Write bulk defaults for future user-manager processes",
                "Remove retired managed user-manager bulk defaults",
                "Load pending user-manager defaults before starting services",
            },
            variables, *(["--check"] if check else []), tasks=herdr_tasks, handlers=handlers,
        )
        if not manage or check:
            assert not pid_file.exists()
            cached = json.loads((tmp_path / "manager.json").read_text())["environment"]
            assert {key: cached[key] for key in (stale | retired)} == (stale | retired)
            if check:
                assert conf.read_text() == "".join(f"{key}={value}\n" for key, value in stale.items())
                assert unit.read_text() == old_unit
        elif active and not ordinary:
            assert service() == before
        else:
            assert service()[1] == (defaults if write else {})
            if ordinary:
                assert service()[0] != before[0]
    finally:
        if pid_file.exists():
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
