import importlib.util
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("bulk_defaults", ROOT / "scripts/bulk-defaults.py")
bulk = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bulk)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    directory = tmp_path / "home"
    directory.mkdir()
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
    (".pip/pip.conf", "[global]\ncache-dir=/custom/legacy-pip\n", ".config/pip/pip.conf"),
    (".npmrc", "store-dir=/custom/pnpm\n", ".config/pnpm/rc"),
])
def test_alternate_native_paths_do_not_gain_a_higher_priority_default(home, relative, content, shadow):
    legacy = home / relative
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(content)

    bulk.configure(home, home.parent / "data")

    assert not (home / shadow).exists()
    assert content in legacy.read_text()


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
