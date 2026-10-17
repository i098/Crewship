"""Per-project database tests.

The unit tests stub Docker. CREWSHIP_POSTGRES_LAB=1 enables Ansible and real containers,
only inside a disposable Docker-in-Docker lab.
"""

import concurrent.futures
import copy
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "blueprint/fleet/bin/crewship-db"
SPEC = importlib.util.spec_from_file_location("ship_postgres", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ship)
lab = pytest.mark.skipif(os.environ.get("CREWSHIP_POSTGRES_LAB") != "1", reason="disposable Docker lab only")
POSTGRES = "services:\n  db:\n    image: postgres:16-alpine\n"
LAB_POSTGRES = "services:\n  db:\n    image: postgres:alpine\n"
LAB_REDIS = "services:\n  cache:\n    image: redis:alpine\n"


def cli(home, *args, check=True):
    return subprocess.run(
        [sys.executable, HELPER, *args], env={**os.environ, "HOME": str(home)},
        capture_output=True, text=True, check=check,
    )


def load(home, monkeypatch):
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TREEHOUSE_ROOT", raising=False)
    loader = importlib.machinery.SourceFileLoader("crewship_db_test", str(HELPER))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def checkout(home, pool, number, project, compose=None, name="compose.yml"):
    directory = home / ".treehouse" / pool / str(number) / project
    (directory / ".git").mkdir(parents=True)
    if compose is not None:
        (directory / name).write_text(compose)
    return directory


@pytest.fixture
def database(tmp_path, monkeypatch):
    """The helper with Docker stubbed: calls are recorded and the first bad image fails."""
    module = load(tmp_path, monkeypatch)
    module.calls = []

    def docker(*args, optional=False):
        module.calls.append(args)
        compose = json.loads(Path(args[2]).read_text())
        if "badimage" in json.dumps(compose):
            raise RuntimeError("Docker operation failed; check the project database service")

    monkeypatch.setattr(module, "docker", docker)
    return module


@pytest.mark.parametrize("enabled", [True, False, None])
def test_schema_and_legacy_profile(enabled):
    config = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    assert config["crewship"]["profiles"]["project_databases"] is False
    config["crewship"]["profiles"]["docker"] = True
    if enabled is None:
        config["crewship"]["profiles"].pop("project_databases")
    else:
        config["crewship"]["profiles"]["project_databases"] = enabled
    assert ship.validate_config(config) is config


@pytest.mark.parametrize("value", ["true", 1, None])
def test_schema_rejects_non_boolean(value):
    config = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    config["crewship"]["profiles"]["project_databases"] = value
    with pytest.raises(ValueError, match="profiles.project_databases"):
        ship.validate_config(config)


@pytest.mark.parametrize("dependency", ["docker", "firstmate"])
def test_runtime_dependencies(dependency):
    config = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    config["crewship"]["profiles"]["project_databases"] = True
    config["crewship"]["profiles"][dependency] = False
    with pytest.raises(ValueError, match="project databases require"):
        ship.validate_config(config)


def old_host(tmp_path, **profiles):
    """A host config that still names the profile shared_postgres, and the same config under the new name."""
    new = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    new["crewship"]["profiles"].update(docker=True, project_databases=True)
    old = copy.deepcopy(new)
    old["crewship"]["profiles"]["shared_postgres"] = old["crewship"]["profiles"].pop("project_databases")
    old["crewship"]["profiles"].update(profiles)
    host = tmp_path / "host.yml"
    host.write_text(yaml.safe_dump(old))
    return host, new


def test_old_profile_name_applies_as_project_databases(tmp_path, capsys):
    host, new = old_host(tmp_path)
    assert ship.load_config(host) == new
    assert "crewship.profiles.shared_postgres is now crewship.profiles.project_databases" in capsys.readouterr().err


def test_both_profile_names_must_agree(tmp_path):
    host, _ = old_host(tmp_path, project_databases=False)
    with pytest.raises(ValueError, match="another name of profiles.project_databases"):
        ship.load_config(host)


def test_preview_and_apply_record_only_the_projects_directory(tmp_path):
    assert "configure" in cli(tmp_path, "--apply", "--check").stdout
    assert list(tmp_path.iterdir()) == []
    assert "configure" in cli(tmp_path, "--apply").stdout
    state = tmp_path / ".local/state/code-factory/project-db"
    assert [p.name for p in state.iterdir()] == ["projects-dir"]
    assert (state / "projects-dir").read_text().strip() == str(tmp_path / "Dev/firstmate/projects")
    before = (state / "projects-dir").stat().st_mtime_ns
    assert cli(tmp_path, "--apply").stdout == ""
    assert cli(tmp_path, "--apply", "--check").stdout == ""
    assert (state / "projects-dir").stat().st_mtime_ns == before


@pytest.mark.parametrize("available", [False, True])
def test_docker_access_check_does_not_change_resources(tmp_path, available):
    binaries = tmp_path / "bin"
    binaries.mkdir()
    for name in ("docker", "sudo"):
        command = binaries / name
        command.write_text(f"#!/bin/sh\nexit {0 if available else 1}\n")
        command.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    result = subprocess.run(
        [sys.executable, HELPER, "--check-docker"],
        env={**os.environ, "HOME": str(home), "PATH": str(binaries)},
        capture_output=True, text=True,
    )
    assert result.returncode == (0 if available else 1)
    if not available:
        assert "need explicit Docker access" in result.stderr
        assert "does not grant Docker privileges" in result.stderr
    assert list(home.iterdir()) == []


@pytest.mark.parametrize("compose, expected", [
    ("image: postgres:16-alpine", ("postgres", "postgres:16-alpine")),
    ("image: library/postgres:16", ("postgres", "library/postgres:16")),
    ("image: docker.io/library/mysql:8.4", ("mysql", "docker.io/library/mysql:8.4")),
    ("image: 'ghcr.io/acme/postgis/postgis:16-3.4'", None),
    ("image: postgis/postgis:16-3.4", None),
    ("image: bitnami/mysql:8.4", None),
    ("image: pgvector/pgvector:pg18", ("postgres", "pgvector/pgvector:pg18")),
    ('image: "mysql:8.4"  # pinned', ("mysql", "mysql:8.4")),
    ("image: mariadb:11", ("mariadb", "mariadb:11")),
    ("image: redis:7@sha256:abc", ("redis", "redis:7@sha256:abc")),
    ("image: postgres:${PG_TAG:-16}", ("postgres", "postgres:latest")),
    ("# image: postgres:16\n    image: nginx", None),
    ("image: myorg/postgres-tools:1", None),
    ("build: .", None),
])
def test_engine_comes_from_the_compose_image(database, tmp_path, compose, expected):
    directory = tmp_path / "app"
    directory.mkdir()
    (directory / "docker-compose.yaml").write_text(f"services:\n  one:\n    {compose}\n")
    assert database.detect([directory]) == expected


def test_detection_prefers_a_database_over_a_cache_and_skips_unreadable_checkouts(database, tmp_path):
    bare, full = tmp_path / "bare", tmp_path / "full"
    bare.mkdir()
    full.mkdir()
    (full / "compose.yaml").write_text("services:\n  r:\n    image: redis:7\n  p:\n    image: postgres:17\n")
    assert database.detect([tmp_path / "gone", bare, full]) == ("postgres", "postgres:17")


@pytest.mark.parametrize("engine, image, program, argument", [
    ("redis", "redis:7", "redis-server", "command"),
    ("mysql", "mysql:8.4", "mysqladmin", "healthcheck"),
    ("mariadb", "mariadb:11", "mariadb-admin", "healthcheck"),
])
def test_the_password_never_reaches_a_process_argument(database, tmp_path, engine, image, program, argument):
    service = database.compose_document("app", {"engine": engine, "image": image, "port": 25440})["services"]["db"]
    script = service["command"][-1] if argument == "command" else service["healthcheck"]["test"][-1]
    secret = tmp_path / "secret"
    secret.write_text("s3cretvalue\n")
    script = script.replace("$$", "$").replace("/run/secrets/db_password", str(secret))
    script = script.replace("/tmp/redis.conf", str(tmp_path / "redis.conf"))
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / program).write_text(f'#!/bin/sh\necho "$@" > {tmp_path}/argv\necho "$MYSQL_PWD" > {tmp_path}/env\n')
    (stub / program).chmod(0o755)
    subprocess.run(["sh", "-c", script], env={"PATH": f"{stub}:/usr/bin:/bin"}, check=True)
    assert "s3cretvalue" not in (tmp_path / "argv").read_text()
    if engine == "redis":
        assert "requirepass s3cretvalue" in (tmp_path / "redis.conf").read_text()
    else:
        assert (tmp_path / "env").read_text().strip() == "s3cretvalue"


@pytest.mark.parametrize("image", ["bitnami/redis:7", "bitnami/postgresql:16", "postgis/postgis:16-3.4", "ghcr.io/acme/mysql:8"])
def test_unofficial_images_are_rejected_with_a_message_naming_the_image(database, tmp_path, capsys, image):
    directory = tmp_path / "app"
    directory.mkdir()
    (directory / "compose.yaml").write_text(f"services:\n  one:\n    image: {image}\n")
    assert database.detect([directory]) is None
    assert f"unsupported image {image}" in capsys.readouterr().err


@pytest.mark.parametrize("image", ["postgres:16-alpine", "postgres:17", "postgres:latest", "pgvector/pgvector:pg16"])
def test_postgres_data_directory_is_inside_the_named_volume_for_any_major_version(database, image):
    service = database.compose_document("app", {"engine": "postgres", "image": image, "port": 25440})["services"]["db"]
    mount = service["volumes"][0].split(":")[1]
    pgdata = Path(service["environment"]["PGDATA"])
    assert pgdata != Path(mount) and Path(mount) in pgdata.parents


@pytest.mark.parametrize("engine, image, binding", [
    ("postgres", "postgres:16", "5432"), ("mysql", "mysql:8.4", "3306"),
    ("mariadb", "mariadb:11", "3306"), ("redis", "redis:7", "6379"),
])
def test_compose_document_binds_loopback_and_keeps_the_password_in_a_file(database, engine, image, binding):
    document = database.compose_document("example-app", {"engine": engine, "image": image, "port": 25440})
    service = document["services"]["db"]
    assert service["ports"] == [f"127.0.0.1:25440:{binding}"]
    assert service["restart"] == "unless-stopped"
    assert service["container_name"] == "crewship-db-example-app"
    assert document["volumes"]["data"]["name"] == "crewship-db-example-app-data"
    assert document["secrets"]["db_password"]["file"].endswith("secrets/project-db/example-app.password")
    assert all(value.endswith("_FILE") or "PASSWORD" not in key or value == "/run/secrets/db_password"
               for key, value in service["environment"].items())


@pytest.mark.parametrize("prefix", ["", "$CREWSHIP_TREEHOUSE_TEST_UNSET", "${CREWSHIP_TREEHOUSE_TEST_UNSET}"])
def test_seed_finds_native_root_without_a_shell_export(database, tmp_path, monkeypatch, prefix):
    native = tmp_path / "data"
    monkeypatch.delenv("CREWSHIP_TREEHOUSE_TEST_UNSET", raising=False)
    config = tmp_path / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f"root = {json.dumps(prefix + str(native))}\n")
    app = checkout(native, "app-abc", 1, "app", POSTGRES)

    database.seed()

    assert urlsplit(env_url(app)).scheme == "postgresql"


def test_explicit_root_overrides_native_config_and_keeps_legacy_projects(database, tmp_path, monkeypatch):
    config = tmp_path / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f"root = {json.dumps(str(tmp_path / 'ignored'))}\n")
    ignored = checkout(tmp_path / "ignored", "ignored-abc", 1, "ignored", POSTGRES)
    monkeypatch.setenv("TREEHOUSE_ROOT", "$HOME/data")
    native = checkout(tmp_path / "data", "app-abc", 1, "app", POSTGRES)
    (native / ".git").rmdir()
    (native / ".git").write_text("gitdir: unused-test-entry\n")
    legacy = checkout(tmp_path, "app-abc", 1, "app", POSTGRES)
    cache = tmp_path / "data/.treehouse/firstmate-abc/1/firstmate/projects/cache"
    (cache / ".git").mkdir(parents=True)
    (cache / "compose.yml").write_text(LAB_REDIS)
    registered = tmp_path / "workspace/projects/app"
    (registered / ".git").mkdir(parents=True)
    database.apply()
    database.PROJECTS.write_text(str(registered.parent))

    database.seed()

    assert env_url(native) == env_url(legacy) == env_url(registered)
    assert urlsplit(env_url(cache, "REDIS_URL")).scheme == "redis"
    assert not (ignored / ".env.local").exists()


def test_discovery_deduplicates_root_and_registered_checkout_aliases(database, tmp_path, monkeypatch):
    app = checkout(tmp_path, "app-abc", 1, "app", POSTGRES)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("TREEHOUSE_ROOT", str(alias))
    database.apply()
    database.PROJECTS.write_text(str(alias / ".treehouse/app-abc/1"))

    assert {name: [path.resolve() for path in paths] for name, paths in database.checkouts().items()} == {"app": [app]}


@pytest.mark.parametrize("operation", ["--seed", "app"])
@pytest.mark.parametrize("source, relative, engine, image", [
    ("registered", "Dev/firstmate/projects/app", "postgres", "postgres:16-alpine"),
    ("registered", "!projects/app", "redis", "redis:alpine"),
    ("pool", ".treehouse/firstmate-abc/1/firstmate/projects/app", "postgres", "postgres:16-alpine"),
    ("pool", "data/.treehouse/app-abc/1/app", "postgres", "postgres:16-alpine"),
])
def test_checkout_aliases_keep_sorted_engine_detection_order(
    database, tmp_path, monkeypatch, capsys, operation, source, relative, engine, image,
):
    first = checkout(tmp_path, "app-abc", 1, "app", POSTGRES)
    second = checkout(tmp_path, "app-abc", 2, "app", LAB_REDIS)
    alias = tmp_path / relative
    alias.parent.mkdir(parents=True)
    alias.symlink_to(first if engine == "postgres" else second, target_is_directory=True)
    monkeypatch.setenv("TREEHOUSE_ROOT", "$HOME/data")
    if source == "registered":
        database.apply()
        database.PROJECTS.write_text(str(alias.parent))
    capsys.readouterr()

    database.main([operation])

    meta = json.loads((database.STATE / "app/meta.json").read_text())
    assert (meta["engine"], meta["image"]) == (engine, image)
    variable = "DATABASE_URL" if engine == "postgres" else "REDIS_URL"
    scheme = "postgresql" if engine == "postgres" else "redis"
    if operation == "--seed":
        assert env_url(first, variable) == env_url(second, variable) == env_url(alias, variable)
        assert urlsplit(env_url(first, variable)).scheme == scheme
    else:
        path = Path(capsys.readouterr().out.strip())
        assert path == database.SECRETS / "app.env"
        key, url = path.read_text().strip().split("=", 1)
        assert key == variable
        assert urlsplit(url).scheme == scheme


@pytest.mark.parametrize("target", ["123", "storage-app"])
def test_registered_links_keep_their_project_name(database, tmp_path, target):
    directory = tmp_path / "storage" / target
    (directory / ".git").mkdir(parents=True)
    (directory / "compose.yml").write_text(POSTGRES)
    registered = tmp_path / "workspace/projects/app"
    registered.parent.mkdir(parents=True)
    registered.symlink_to(directory, target_is_directory=True)
    database.apply()
    database.PROJECTS.write_text(str(registered.parent))

    database.seed()

    assert urlsplit(env_url(registered)).scheme == "postgresql"
    assert (database.STATE / "app/meta.json").exists()
    assert not (database.STATE / target).exists()


@pytest.mark.parametrize("relative", [
    ".treehouse/app-abc/1/app",
    "data/.treehouse/app-abc/1/app",
    "data/.treehouse/firstmate-abc/1/firstmate/projects/app",
])
def test_named_lookup_keeps_pool_and_registered_project_names(database, tmp_path, monkeypatch, capsys, relative):
    monkeypatch.setenv("TREEHOUSE_ROOT", "$HOME/data")
    directory = tmp_path / relative
    (directory / ".git").mkdir(parents=True)
    (directory / "compose.yml").write_text(POSTGRES)
    projects = tmp_path / "workspace/projects"
    projects.mkdir(parents=True)
    for name in ("shop", "store"):
        (projects / name).symlink_to(directory, target_is_directory=True)
    database.apply()
    database.PROJECTS.write_text(str(projects))
    capsys.readouterr()

    urls = []
    for name in ("app", "shop", "store"):
        database.main([name])
        path = Path(capsys.readouterr().out.strip())
        assert path == database.SECRETS / (name + ".env")
        urls.append(path.read_text().strip().split("=", 1)[1])

    assert all(urlsplit(url).scheme == "postgresql" for url in urls)
    assert len(set(urls)) == 3


@pytest.mark.parametrize("name", ["123", "bad.name", "a" * 49])
def test_invalid_registered_alias_does_not_hide_an_eligible_pool_project(database, tmp_path, name):
    app = checkout(tmp_path, "app-abc", 1, "app", POSTGRES)
    projects = tmp_path / "workspace/projects"
    projects.mkdir(parents=True)
    (projects / name).symlink_to(app, target_is_directory=True)
    database.apply()
    database.PROJECTS.write_text(str(projects))

    database.seed()

    assert urlsplit(env_url(app)).scheme == "postgresql"
    assert (database.STATE / "app/meta.json").exists()
    assert not (database.STATE / name).exists()


def test_pool_links_keep_distinct_project_names(database, tmp_path, monkeypatch):
    directory = tmp_path / "storage"
    (directory / ".git").mkdir(parents=True)
    (directory / "compose.yml").write_text(POSTGRES)
    monkeypatch.setenv("TREEHOUSE_ROOT", "$HOME/data")
    paths = {
        "app": tmp_path / ".treehouse/app-abc/1/app",
        "shop": tmp_path / "data/.treehouse/shop-abc/1/shop",
        "store": tmp_path / "data/.treehouse/firstmate-abc/1/firstmate/projects/store",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(directory, target_is_directory=True)

    database.seed()

    assert {path.parent.name for path in database.STATE.glob("*/meta.json")} == set(paths)
    assert urlsplit(env_url(directory)).scheme == "postgresql"


@pytest.mark.parametrize("root", ["42", "[]"])
def test_native_root_rejects_non_path_values(database, tmp_path, root):
    config = tmp_path / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(f"root = {root}\n")

    with pytest.raises(ValueError, match="Treehouse root"):
        database.seed()


def test_relative_native_root_does_not_hide_home_or_registered_projects(database, tmp_path, monkeypatch):
    config = tmp_path / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('root = "."\n')
    legacy = checkout(tmp_path, "app-abc", 1, "app", POSTGRES)
    registered = tmp_path / "workspace/projects/app"
    (registered / ".git").mkdir(parents=True)
    database.apply()
    database.PROJECTS.write_text(str(registered.parent))
    elsewhere = tmp_path / "elsewhere"
    ignored = checkout(elsewhere, "ignored-abc", 1, "ignored", POSTGRES)
    monkeypatch.chdir(elsewhere)

    database.seed()

    assert env_url(legacy) == env_url(registered)
    assert not (ignored / ".env.local").exists()


def test_seed_gives_each_project_one_stable_container_and_url_for_all_worktrees(database, tmp_path):
    first = checkout(tmp_path, "shop-abc", 1, "shop", POSTGRES)
    second = checkout(tmp_path, "shop-abc", 2, "shop", name="docker-compose.yml", compose=POSTGRES)
    blog = checkout(tmp_path, "blog-abc", 1, "blog", "services:\n  d:\n    image: mysql:8.4\n")
    plain = checkout(tmp_path, "plain-abc", 1, "plain", "services:\n  web:\n    image: nginx\n")
    (first / ".env.local").write_text("OTHER=keep\nexport DATABASE_URL=old\n# crewship-shared-postgres\n")
    database.seed()
    shop_env = (first / ".env.local").read_text()
    assert shop_env.splitlines()[:2] == ["OTHER=keep", "# crewship-project-db"]
    assert (second / ".env.local").read_text().splitlines() == shop_env.splitlines()[1:]
    shop_url = urlsplit(shop_env.split("DATABASE_URL=")[1].strip())
    blog_url = urlsplit((blog / ".env.local").read_text().split("DATABASE_URL=")[1].strip())
    assert (shop_url.scheme, blog_url.scheme) == ("postgresql", "mysql")
    assert shop_url.port != blog_url.port and min(shop_url.port, blog_url.port) >= database.FIRST_PORT
    assert not (plain / ".env.local").exists()
    assert {call[2].split("/")[-2] for call in database.calls} == {"shop", "blog"}
    secrets = tmp_path / ".local/state/code-factory/secrets/project-db"
    assert shop_url.password == (secrets / "shop.password").read_text().strip()
    assert (secrets / "shop.password").stat().st_mode & 0o777 == 0o600
    # A second pass keeps port, password and every file.
    mtimes = {p: p.stat().st_mtime_ns for p in (first / ".env.local", second / ".env.local", blog / ".env.local")}
    database.seed()
    assert mtimes == {p: p.stat().st_mtime_ns for p in mtimes}
    assert urlsplit((first / ".env.local").read_text().split("DATABASE_URL=")[1].strip()).port == shop_url.port


def test_legacy_database_url_is_dropped_for_a_redis_project(database, tmp_path):
    cache = checkout(tmp_path, "cache-abc", 1, "cache", "services:\n  c:\n    image: redis:7\n")
    (cache / ".env.local").write_text("OTHER=keep\n# crewship-shared-postgres\nDATABASE_URL=postgresql://old@127.0.0.1:25432/x\nKEEP=1\n")
    database.seed()
    lines = (cache / ".env.local").read_text().splitlines()
    assert lines[:2] == ["OTHER=keep", "KEEP=1"] and lines[2] == "# crewship-project-db"
    assert lines[3].startswith("REDIS_URL=redis://") and len(lines) == 4


def test_engine_choice_sticks_after_the_compose_file_changes(database, tmp_path):
    app = checkout(tmp_path, "app-abc", 1, "app", POSTGRES)
    database.seed()
    port = json.loads((tmp_path / ".local/state/code-factory/project-db/app/meta.json").read_text())["port"]
    (app / "compose.yml").write_text("services:\n  d:\n    image: mysql:8.4\n")
    database.seed()
    meta = json.loads((tmp_path / ".local/state/code-factory/project-db/app/meta.json").read_text())
    assert meta == {"engine": "postgres", "image": "postgres:16-alpine", "port": port}


def test_cli_name_uses_a_given_checkout_and_rejects_bad_names(tmp_path):
    directory = tmp_path / "elsewhere"
    directory.mkdir()
    assert cli(tmp_path, "example-app", directory, check=False).returncode != 0
    for name in ("bad';DROP ROLE postgres;--", "../traverse", "1abc"):
        result = cli(tmp_path, name, directory, check=False)
        assert result.returncode != 0 and "Project must be" in result.stderr
    assert not (tmp_path / ".local/state/code-factory/project-db/example-app").exists()


def test_one_failing_project_does_not_block_the_others(database, tmp_path):
    checkout(tmp_path, "a-abc", 1, "a-bad", "services:\n  d:\n    image: postgres:badimage\n")
    good = checkout(tmp_path, "z-abc", 1, "z-good", POSTGRES)
    with pytest.raises(RuntimeError, match="Docker operation failed"):
        database.seed()
    assert "DATABASE_URL=" in (good / ".env.local").read_text()
    assert not (tmp_path / ".treehouse/a-abc/1/a-bad/.env.local").exists()


@pytest.mark.parametrize("operation", ["discovery", "read_text", "stat", "temporary", "replace"])
def test_seed_skips_checkouts_removed_at_file_boundaries(database, tmp_path, monkeypatch, operation):
    victim = checkout(tmp_path, "a-abc", 1, "a-removed", POSTGRES)
    survivor = checkout(tmp_path, "z-abc", 1, "z-survivor", POSTGRES)
    destination = victim / ".env.local"
    if operation == "stat":
        database.seed()  # an up-to-date file reaches the final mode check, where stat runs
    else:
        destination.write_text("OTHER=keep\n")
        destination.chmod(0o600)
    fired = []

    def remove():
        if not fired:
            fired.append(True)
            shutil.rmtree(victim)

    if operation == "discovery":
        real_detect = database.detect

        def detect(directories):
            remove()
            return real_detect(directories)

        monkeypatch.setattr(database, "detect", detect)
    elif operation == "temporary":
        real_temporary = database.tempfile.NamedTemporaryFile

        def temporary(*args, **kwargs):
            if Path(kwargs["dir"]) == victim:
                remove()
            return real_temporary(*args, **kwargs)

        monkeypatch.setattr(database.tempfile, "NamedTemporaryFile", temporary)
    else:
        real_method = getattr(Path, operation)

        def file_operation(path, *args, **kwargs):
            target = Path(args[0]) if operation == "replace" else path
            if target == destination:
                remove()
            return real_method(path, *args, **kwargs)

        monkeypatch.setattr(Path, operation, file_operation)
    database.seed()
    assert fired and not victim.exists()
    assert (survivor / ".env.local").read_text().startswith("# crewship-project-db\nDATABASE_URL=postgresql://app:")


@pytest.fixture
def service(tmp_path, monkeypatch):
    if os.environ.get("CREWSHIP_POSTGRES_LAB") != "1":
        pytest.skip("disposable Docker lab only")
    monkeypatch.delenv("TREEHOUSE_ROOT", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    cli(home, "--apply")
    yield home
    for compose in (home / ".local/state/code-factory/project-db").glob("*/compose.json"):
        subprocess.run(["docker", "compose", "-f", str(compose), "down", "-v"], check=True, capture_output=True)


def env_url(worktree, variable="DATABASE_URL"):
    return (worktree / ".env.local").read_text().split(variable + "=", 1)[1].strip()


def query(url, sql):
    connection = urlsplit(url)
    return subprocess.run([
        "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-h", connection.hostname, "-p", str(connection.port),
        "-U", connection.username, "-d", connection.path.removeprefix("/"), "-c", sql,
    ], env={**os.environ, "PGPASSWORD": connection.password}, capture_output=True, text=True)


@lab
def test_projects_get_their_own_containers_shared_by_their_worktrees(service):
    shop = [checkout(service, "shop-abc", n, "shop", LAB_POSTGRES) for n in (1, 2)]
    blog = checkout(service, "blog-abc", 1, "blog", LAB_POSTGRES)
    cache = checkout(service, "cache-abc", 1, "cache", LAB_REDIS)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: cli(service, "--seed"), range(3)))
    url = env_url(shop[0])
    assert env_url(shop[1]) == url
    assert query(url, "CREATE TABLE proof (n integer); INSERT INTO proof VALUES (42)").returncode == 0
    assert query(env_url(shop[1]), "SELECT n FROM proof").stdout.strip() == "42"
    assert query(env_url(blog), "SELECT to_regclass('proof')").stdout.strip() == ""
    assert query(url.replace(urlsplit(url).password, "wrong-password"), "SELECT 1").returncode != 0
    assert urlsplit(url).port != urlsplit(env_url(blog)).port
    redis_url = env_url(cache, "REDIS_URL")
    ping = subprocess.run(
        ["docker", "exec", "crewship-db-cache", "redis-cli", "-a", urlsplit(redis_url).password,
         "--no-auth-warning", "ping"], capture_output=True, text=True)
    assert ping.stdout.strip() == "PONG"
    assert cli(service, "--seed").stdout == ""
    assert env_url(shop[0]) == url
    container = json.loads(subprocess.run(
        ["docker", "inspect", "crewship-db-shop"], capture_output=True, text=True, check=True).stdout)[0]
    assert container["HostConfig"]["RestartPolicy"]["Name"] == "unless-stopped"
    assert container["NetworkSettings"]["Ports"]["5432/tcp"] == [
        {"HostIp": "127.0.0.1", "HostPort": str(urlsplit(url).port)}]
    printed = cli(service, "shop").stdout.strip()
    assert Path(printed).read_text() == f"DATABASE_URL={url}\n"
    assert urlsplit(url).password not in printed


@lab
@pytest.mark.parametrize("selection", ["config", "override"])
def test_native_legacy_and_registered_checkouts_receive_working_services(service, tmp_path, monkeypatch, selection):
    native = tmp_path / "data"
    config = service / ".config/treehouse/config.toml"
    config.parent.mkdir(parents=True)
    monkeypatch.delenv("CREWSHIP_TREEHOUSE_TEST_UNSET", raising=False)
    configured = "${CREWSHIP_TREEHOUSE_TEST_UNSET}" + str(native if selection == "config" else tmp_path / "ignored")
    config.write_text(f"root = {json.dumps(configured)}\n")
    if selection == "override":
        monkeypatch.setenv("TREEHOUSE_ROOT", str(native))
    app = checkout(native, "app-abc", 1, "app", LAB_POSTGRES)
    legacy = checkout(service, "app-abc", 1, "app", LAB_POSTGRES)
    cache = checkout(native, "cache-abc", 1, "cache", LAB_REDIS)
    registered = tmp_path / "workspace/projects/app"
    storage = tmp_path / "storage/123"
    (storage / ".git").mkdir(parents=True)
    registered.parent.mkdir(parents=True)
    registered.symlink_to(storage, target_is_directory=True)
    (service / ".local/state/code-factory/project-db/projects-dir").write_text(str(registered.parent))

    cli(service, "--seed")

    assert env_url(app) == env_url(legacy) == env_url(registered)
    assert query(env_url(app), "CREATE TABLE proof (n integer); INSERT INTO proof VALUES (42)").returncode == 0
    assert query(env_url(legacy), "SELECT n FROM proof").stdout.strip() == "42"
    assert query(env_url(registered), "SELECT n FROM proof").stdout.strip() == "42"
    authenticated = subprocess.run(
        ["docker", "exec", "-e", "REDISCLI_AUTH", "crewship-db-cache", "redis-cli", "--no-auth-warning", "ping"],
        env={**os.environ, "REDISCLI_AUTH": urlsplit(env_url(cache, "REDIS_URL")).password},
        capture_output=True, text=True, check=True,
    )
    assert authenticated.stdout.strip() == "PONG"
    files = [path / ".env.local" for path in (app, legacy, cache, registered)]
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}
    cli(service, "--seed")
    assert before == {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in files}


@lab
def test_ansible_on_off_and_idempotence(service, tmp_path):
    home = service
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"), "crewship_local_bin": str(home / ".local/bin"),
        "crewship_user_units": str(home / ".config/systemd/user"),
        "crewship_firstmate_dir": str(home / "custom-workspace/firstmate"),
        "crewship_cfg": {"home": str(home), "user": "root", "profiles": {"project_databases": True}},
        "crewship_group": "root", "crewship_manage_services": False,
        "crewship_become_target": False, "crewship_user_systemd_env": {},
    }
    (home / ".local/bin").mkdir(parents=True)
    # Use the real task consumer, but never start host services.
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    playbook = tmp_path / "playbook.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": variables,
        "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/project_databases.yml"),
                   "when": "crewship_cfg.profiles.project_databases | bool"}],
        "handlers": [{"name": "reload user systemd", "ansible.builtin.debug": {"msg": "deferred"}}],
    }]))
    command = ["ansible-playbook", "-i", "localhost,", str(playbook)]
    denied = tmp_path / "denied"
    denied.mkdir()
    for name in ("docker", "sudo"):
        executable = denied / name
        executable.write_text("#!/bin/sh\nexit 1\n")
        executable.chmod(0o755)
    denied_playbook = yaml.safe_load(playbook.read_text())
    denied_playbook[0]["vars"]["crewship_user_systemd_env"] = {"PATH": str(denied)}
    playbook.write_text(yaml.safe_dump(denied_playbook))
    rejected = subprocess.run(command, capture_output=True, text=True)
    assert rejected.returncode != 0
    assert "need explicit Docker access" in rejected.stdout
    assert not (home / ".local/bin/crewship-db").exists()
    projects_dir = home / ".local/state/code-factory/project-db/projects-dir"
    assert projects_dir.read_text().strip() == str(home / "Dev/firstmate/projects")
    denied_playbook[0]["vars"]["crewship_user_systemd_env"] = {}
    playbook.write_text(yaml.safe_dump(denied_playbook))
    first = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "changed=0" not in first.stdout.split("PLAY RECAP")[-1]
    second = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "changed=0" in second.stdout.split("PLAY RECAP")[-1]
    assert projects_dir.read_text().strip() == str(home / "custom-workspace/firstmate/projects")
    primary = home / "custom-workspace/firstmate/projects/main-project"
    (primary / ".git").mkdir(parents=True)
    (primary / "compose.yaml").write_text(LAB_POSTGRES)
    cli(home, "--seed")
    assert query(env_url(primary), "SELECT current_database()").stdout.strip() == "app"
    before = {str(p.relative_to(home)): (p.read_bytes(), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}
    playbook_data = yaml.safe_load(playbook.read_text())
    playbook_data[0]["vars"]["crewship_cfg"]["profiles"]["project_databases"] = False
    playbook.write_text(yaml.safe_dump(playbook_data))
    off = subprocess.run(command, capture_output=True, text=True, check=True)
    assert "changed=0" in off.stdout.split("PLAY RECAP")[-1]
    assert before == {str(p.relative_to(home)): (p.read_bytes(), p.stat().st_mtime_ns) for p in home.rglob("*") if p.is_file()}
    volume = subprocess.run(["docker", "volume", "inspect", "crewship-db-main-project-data"], capture_output=True, text=True, check=True)
    assert json.loads(volume.stdout)[0]["Name"] == "crewship-db-main-project-data"
    assert query(env_url(primary), "SELECT 1").stdout.strip() == "1"


@lab
def test_readiness_waits_for_final_tcp_server(tmp_path, monkeypatch):
    module = load(tmp_path, monkeypatch)
    module.SECRETS.mkdir(parents=True)
    document = module.compose_document("hold", {"engine": "postgres", "image": "postgres:alpine", "port": 25499})
    module.password(module.SECRETS / "hold.password")
    gate = tmp_path / "initialization-gate"
    gate.mkdir(mode=0o777)
    gate.chmod(0o777)
    initialize = tmp_path / "initialize.sh"
    initialize.write_text("touch /gate/ready\nwhile [ ! -e /gate/release ]; do sleep 0.1; done\n")
    document["services"]["db"]["volumes"] += [
        f"{initialize}:/docker-entrypoint-initdb.d/hold.sh:ro",
        f"{gate}:/gate",
    ]
    config = tmp_path / "hold.json"
    config.write_text(json.dumps(document))
    compose = ["docker", "compose", "-f", str(config)]
    try:
        subprocess.run([*compose, "up", "-d"], capture_output=True, check=True)
        deadline = time.monotonic() + 60
        while not (gate / "ready").exists():
            assert time.monotonic() < deadline, "Postgres did not reach initialization"
            time.sleep(0.1)
        probe = subprocess.run(
            ["docker", "exec", "crewship-db-hold", *document["services"]["db"]["healthcheck"]["test"][1:]],
            capture_output=True, text=True,
        )
        assert probe.returncode != 0, "Temporary initialization server must not count as ready"
        (gate / "release").touch()
        subprocess.run([*compose, "up", "-d", "--wait"], capture_output=True, check=True)
    finally:
        (gate / "release").touch()
        subprocess.run([*compose, "down", "-v"], capture_output=True, check=True)
