import grp
import importlib.util
import json
import os
import pwd
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("bulk_defaults", ROOT / "scripts/bulk-defaults.py")
bulk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bulk)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "xdg"))
    for name in ("XDG_CONFIG_HOME", "VIRTUAL_ENV", "PIP_CONFIG_FILE"):
        monkeypatch.delenv(name, raising=False)
    directory = tmp_path / "home"
    directory.mkdir()
    for root in ("cache", ".treehouse"):
        (tmp_path / "data" / root).mkdir(parents=True)
    return directory


def test_preview_does_not_create_native_files(home):
    assert bulk.configure(home, home.parent / "data", check=True)["changed"]
    assert list(home.iterdir()) == []


def test_native_defaults_are_idempotent_and_keep_credentials(home):
    npmrc = home / ".npmrc"
    credential = "//registry.example.invalid/:_authToken=${PACKAGE_TOKEN}\n"
    npmrc.write_text(credential)
    npmrc.chmod(0o640)
    data = home.parent / "data"

    assert bulk.configure(home, data)["changed"]
    assert not bulk.configure(home, data)["changed"]
    assert credential in npmrc.read_text()
    assert f"cache={data}/cache/npm" in npmrc.read_text().splitlines()
    assert npmrc.stat().st_mode & 0o777 == 0o640
    assert (home / ".config/treehouse/config.toml").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("relative,content", [
    (".config/treehouse/config.toml", '# Keep the limit.\nroot = "/custom/pools"\nmax_trees = 7\n'),
    (".npmrc", "cache=/custom/npm\n//registry.example.invalid/:_authToken=${TOKEN}\n"),
    (".config/pip/pip.conf", "[global]\ncache-dir=/custom/pip\nindex-url=https://example.invalid\n"),
    (".bunfig.toml", '[install.cache]\ndir = "/custom/bun"\n'),
    (".config/uv/uv.toml", 'cache-dir = "/custom/uv"\n'),
    (".config/pnpm/rc", "store-dir=/custom/pnpm\n"),
    (".config/go/env", "GOCACHE=/custom/go-build\nGOMODCACHE=/custom/go-mod\n"),
    (".config/user-dirs.dirs", 'XDG_DOWNLOAD_DIR="$HOME/Downloads"\n'),
])
def test_explicit_native_paths_remain_unchanged(home, relative, content):
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)

    bulk.configure(home, home.parent / "data")

    assert path.read_text() == content


def test_add_cache_key_to_existing_table_without_rewriting_other_keys(home):
    path = home / ".bunfig.toml"
    path.write_text('[install.cache] # operator settings\ndisable = false\n[run]\nshell = "system"\n')

    bulk.configure(home, home.parent / "data")

    config = bulk.tomllib.loads(path.read_text())
    assert config["install"]["cache"] == {
        "dir": str(home.parent / "data/cache/bun"), "disable": False,
    }
    assert config["run"]["shell"] == "system"


def test_unsupported_inline_table_fails_before_any_file_changes(home):
    path = home / ".bunfig.toml"
    content = "install = {cache = {disable = false}}\n"
    path.write_text(content)

    with pytest.raises(bulk.tomllib.TOMLDecodeError):
        bulk.configure(home, home.parent / "data")

    assert list(home.iterdir()) == [path]
    assert path.read_text() == content


def test_new_native_files_are_private_even_with_open_umask(home):
    previous = os.umask(0)
    try:
        bulk.configure(home, home.parent / "data")
    finally:
        os.umask(previous)
    assert (home / ".config/pip/pip.conf").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("relative,content,shadow", [
    (".npmrc", "store-dir=/custom/pnpm\n", ".config/pnpm/rc"),
])
def test_alternate_native_paths_do_not_gain_a_higher_priority_default(home, relative, content, shadow):
    legacy = home / relative
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(content)

    bulk.configure(home, home.parent / "data")

    assert not (home / shadow).exists()
    assert content in legacy.read_text()


@pytest.mark.parametrize("key", ["cache_dir", "cache-dir", "--cache-dir"])
@pytest.mark.parametrize("location", ["legacy", "global", "xdg-home", "env-file"])
def test_any_pip_cache_setting_blocks_the_user_default(home, monkeypatch, key, location):
    unavailable = home.parent / "unavailable-global/pip/pip.conf"
    unavailable.parent.mkdir(parents=True)
    unavailable.symlink_to(home.parent / "missing-global.conf")
    monkeypatch.setenv(
        "XDG_CONFIG_DIRS",
        f"{unavailable.parent.parent}:{os.environ['XDG_CONFIG_DIRS']}",
    )
    paths = {
        "legacy": home / ".pip/pip.conf",
        "global": home.parent / "xdg/pip/pip.conf",
        "xdg-home": home.parent / "xdg-home/pip/pip.conf",
        "env-file": home.parent / "operator.conf",
    }
    if location == "xdg-home":
        monkeypatch.setenv("XDG_CONFIG_HOME", str(home.parent / "xdg-home"))
    if location == "env-file":
        monkeypatch.setenv("PIP_CONFIG_FILE", str(paths["env-file"]))
    config = paths[location]
    config.parent.mkdir(parents=True, exist_ok=True)
    content = f"[global]\n{key}=/custom/pip\n"
    config.write_text(content)
    cli = [sys.executable, ROOT / "scripts/bulk-defaults.py", "--home", home, "--data-dir", home.parent / "data"]

    subprocess.run([*cli, "--check"], check=True, capture_output=True)
    assert not (home / ".config/pip/pip.conf").exists()
    subprocess.run(cli, check=True, capture_output=True)
    rerun = json.loads(subprocess.run(cli, check=True, capture_output=True).stdout)
    assert rerun == {"changed": False}
    assert not (home / ".config/pip/pip.conf").exists()
    assert config.read_text() == content
    if importlib.util.find_spec("pip") is None:
        return
    env = {**os.environ, "HOME": str(home)}
    env.pop("PIP_CACHE_DIR", None)
    env.pop("PIP_NO_CACHE_DIR", None)
    pip = subprocess.run(
        [sys.executable, "-m", "pip", "cache", "dir"],
        env=env, capture_output=True, text=True, check=True,
    )
    assert pip.stdout.strip() == "/custom/pip"


def test_failed_replace_does_not_truncate_credentials(home, monkeypatch):
    path = home / ".npmrc"
    credential = "//registry.example.invalid/:_authToken=${TOKEN}\n"
    path.write_text(credential)

    def fail_replace(*args):
        raise OSError("simulated filesystem failure")

    monkeypatch.setattr(bulk.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated filesystem failure"):
        bulk.write_native_file(path, credential + "cache=/data/cache/npm\n")

    assert path.read_text() == credential
    assert list(home.iterdir()) == [path]


def test_native_configuration_symlinks_keep_their_targets(home):
    target = home.parent / "operator-npmrc"
    credential = "//registry.example.invalid/:_authToken=${TOKEN}\n"
    target.write_text(credential)
    target.chmod(0o600)
    path = home / ".npmrc"
    path.symlink_to(target)

    bulk.configure(home, home.parent / "data")

    assert path.is_symlink() and path.resolve() == target
    assert credential in target.read_text()
    assert f"cache={home.parent}/data/cache/npm" in target.read_text().splitlines()
    assert target.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("layout", ["pnpm-to-npm", "npm-to-pnpm", "shared-target"])
def test_linked_native_defaults_accumulate_in_one_idempotent_apply(home, layout):
    npmrc = home / ".npmrc"
    pnpmrc = home / ".config/pnpm/rc"
    pnpmrc.parent.mkdir(parents=True)
    target = {
        "pnpm-to-npm": npmrc,
        "npm-to-pnpm": pnpmrc,
        "shared-target": home.parent / "shared-rc",
    }[layout]
    original = "# Operator settings.\n//registry.example.invalid/:_authToken=${TOKEN}\n"
    target.write_text(original)
    target.chmod(0o640)
    links = [path for path in (npmrc, pnpmrc) if path != target]
    for path in links:
        path.symlink_to(target)
    data = home.parent / "data"

    def run(*options):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/bulk-defaults.py"),
             "--home", str(home), "--data-dir", str(data), *options],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)

    assert run("--check") == {"changed": True}
    assert target.read_text() == original
    assert run() == {"changed": True}
    parser = bulk.configparser.RawConfigParser(delimiters=("=",))
    parser.read_string("[user]\n" + npmrc.read_text())
    assert parser.get("user", "cache") == str(data / "cache/npm")
    assert parser.get("user", "store-dir") == str(data / "cache/pnpm")
    assert original in target.read_text()
    applied = target.read_bytes()
    assert run("--check") == {"changed": False}
    assert run() == {"changed": False}
    assert target.read_bytes() == applied
    assert target.stat().st_mode & 0o777 == 0o640
    assert all(path.is_symlink() and path.resolve() == target for path in links)


def test_unavailable_native_symlink_does_not_create_a_replacement(home):
    target = home.parent / "unavailable" / "npmrc"
    path = home / ".npmrc"
    path.symlink_to(target)

    with pytest.raises(FileNotFoundError):
        bulk.configure(home, home.parent / "data")

    assert path.is_symlink() and not target.parent.exists()
    assert list(home.iterdir()) == [path]


@pytest.mark.parametrize("header", ["[global] # mirror", "  [global] ; mirror", "[global]"])
def test_commented_pip_sections_receive_a_cache_without_duplicate_sections(home, header):
    path = home / ".config/pip/pip.conf"
    path.parent.mkdir(parents=True)
    path.write_text(header + "\nindex-url=https://example.invalid/simple\n")

    bulk.configure(home, home.parent / "data")

    parser = bulk.configparser.RawConfigParser()
    parser.read(path)
    assert parser.get("global", "cache-dir") == str(home.parent / "data/cache/pip")
    assert parser.get("global", "index-url") == "https://example.invalid/simple"


def test_indented_npm_cache_is_an_explicit_native_choice(home):
    path = home / ".npmrc"
    content = "registry=https://registry.npmjs.org/\n  cache=/custom/npm\n"
    path.write_text(content)

    bulk.configure(home, home.parent / "data")

    assert path.read_text() == content


def test_bare_npm_flags_survive_a_new_cache_default(home):
    path = home / ".npmrc"
    path.write_text("# Operator choice.\njson\n")

    bulk.configure(home, home.parent / "data")

    assert "json" in path.read_text().splitlines()
    assert f"cache={home.parent}/data/cache/npm" in path.read_text().splitlines()


@pytest.mark.parametrize("cache", ['"/custom/bun"', "false", "true"])
def test_plain_bun_cache_values_remain_explicit_choices(home, cache):
    path = home / ".bunfig.toml"
    content = f"[install]\ncache = {cache}\n"
    path.write_text(content)

    bulk.configure(home, home.parent / "data")

    assert path.read_text() == content


@pytest.mark.parametrize("relative", [".config", ".config/pip", ".config/pnpm", ".config/go"])
def test_unavailable_configuration_directory_links_are_not_recreated(home, relative):
    target = home.parent / "unavailable-directory"
    path = home / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target, target_is_directory=True)

    with pytest.raises(FileNotFoundError):
        bulk.configure(home, home.parent / "data")

    assert path.is_symlink() and not target.exists()


def test_native_writer_rejects_an_unavailable_linked_parent(home):
    target = home.parent / "unavailable-directory"
    link = home / ".config"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(FileNotFoundError):
        bulk.write_native_file(link / "pip/pip.conf", "[global]\n")

    assert link.is_symlink() and not target.exists()


def test_new_bulk_directories_are_private_and_existing_modes_stay(home):
    data = home.parent / "data"
    (data / ".treehouse").rmdir()
    (data / "cache").chmod(0o755)
    tasks = [task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
             if "account's bulk directories" in task["name"]]
    play = home.parent / "play.yml"
    play.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {"crewship_data_dir": str(data), "crewship_account_ready": True,
                 "crewship_cfg": {"user": pwd.getpwuid(os.getuid()).pw_name},
                 "crewship_group": grp.getgrgid(os.getgid()).gr_name,
                 "ansible_become": False, "ansible_python_interpreter": sys.executable},
        "tasks": tasks,
    }]))
    environment = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(home.parent),
                   "LANG": "C.UTF-8", "ANSIBLE_LOCAL_TEMP": str(home.parent / "ansible-tmp")}
    previous = os.umask(0)
    try:
        for check in (True, False):
            result = subprocess.run(
                [Path(sys.executable).parent / "ansible-playbook", "-i", "localhost,", str(play),
                 *(["--check"] if check else [])],
                env=environment, capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stdout + result.stderr
            assert bulk.configure(home, data, check=check)["changed"]
            if check:
                assert sorted(path.name for path in data.iterdir()) == ["cache"]
                assert list((data / "cache").iterdir()) == []
                (data / "cache/uv").mkdir(mode=0o750)
        assert not bulk.configure(home, data)["changed"]
    finally:
        os.umask(previous)
    assert (data / "cache").stat().st_mode & 0o777 == 0o755
    assert (data / "cache/uv").stat().st_mode & 0o777 == 0o750
    for relative in (
        ".treehouse", "tmp", "downloads", "cache/npm", "cache/pip", "cache/bun",
        "cache/pnpm", "cache/go-build", "cache/go-mod", "cache/deno", "cache/bun-transpiler",
    ):
        assert (data / relative).stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("check", [True, False])
@pytest.mark.parametrize("link", ["pnpm", "pnpm/config.yaml"])
@pytest.mark.parametrize("config_root", ["default", "absolute", "relative"])
def test_unavailable_pnpm_yaml_config_stops_before_any_change(
    home, monkeypatch, check, link, config_root
):
    bin_dir = home.parent / "bin"
    bin_dir.mkdir()
    log = home.parent / "pnpm.log"
    pnpm = bin_dir / "pnpm"
    pnpm.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
    pnpm.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))
    config_home = {
        "default": home / ".config", "absolute": home.parent / "xdg", "relative": home / "xdg",
    }[config_root]
    (config_home / link).parent.mkdir(parents=True)
    target = home.parent / "unavailable"
    (config_home / link).symlink_to(target)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    if config_root != "default":
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home) if config_root == "absolute" else "xdg")
    before = list(home.iterdir())

    with pytest.raises(FileNotFoundError):
        bulk.configure(home, home.parent / "data", check=check)

    assert list(home.iterdir()) == before
    assert all(not list(path.iterdir()) for path in (home.parent / "data").iterdir())
    assert (config_home / link).is_symlink() and not target.exists()
    assert not log.exists()
