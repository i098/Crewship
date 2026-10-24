import getpass
import grp
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("subject,blocked", [
    ("/CN=emSign Root CA - G1/O=eMudhra Technologies Limited", True),
    ("/CN=Replacement Root/O=eMudhra Inc", True),
    ("/CN=Test Root/O=Test CA", False),
])
def test_chart_checks_ca_trust_without_updating_packages(tmp_path, subject, blocked):
    bundle = tmp_path / "ca.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
         "-nodes", "-keyout", str(tmp_path / "ca.key"), "-out", str(bundle),
         "-subj", subject, "-days", "1", "-addext", "basicConstraints=critical,CA:TRUE"],
        check=True, capture_output=True,
    )
    empty = tmp_path / "empty"
    empty.mkdir()
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/preflight.yml").read_text())
    start = next(i for i, task in enumerate(tasks)
                 if task["name"] == "Distrust the compromised emSign roots")
    end = next(i for i, task in enumerate(tasks)
               if task["name"] == "Resolve the latest tool releases")
    playbook = tmp_path / "trust.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"SSL_CERT_FILE": str(bundle), "SSL_CERT_DIR": str(empty)},
        "vars": {"crewship_installer": str(ROOT / "scripts/provisions.py"),
                 "crewship_cfg": {"home": str(tmp_path)}},
        "tasks": tasks[start:end],
    }]))
    before = bundle.read_bytes()
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
         str(playbook), "--check"],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    assert (result.returncode != 0) == blocked, output
    assert bundle.read_bytes() == before
    assert "changed=0" in output
    if blocked:
        assert "system CA bundle still trusts compromised eMudhra/emSign roots" in output
    else:
        assert "failed=0" in output


@pytest.mark.parametrize("interrupted", [False, True])
def test_emsign_distrust_rebuilds_the_bundle_and_is_idempotent(tmp_path, interrupted):
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/preflight.yml").read_text())
    start = next(i for i, task in enumerate(tasks)
                 if task["name"] == "Distrust the compromised emSign roots")
    end = next(i for i, task in enumerate(tasks)
               if task["name"] == "Refresh signed apt metadata before updating CA trust")
    tasks = tasks[start:end]
    root = tmp_path / "roots"
    (root / "mozilla").mkdir(parents=True)
    empty = tmp_path / "empty"
    empty.mkdir()
    store = tmp_path / "store"
    store.mkdir()
    blocked = tasks[0]["loop"]
    names = [*blocked, "mozilla/Unrelated_Root.crt"]
    for name in names:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
             "-nodes", "-keyout", str(tmp_path / "ca.key"), "-out", str(root / name),
             "-subj", "/CN=" + Path(name).stem, "-days", "1",
             "-addext", "basicConstraints=critical,CA:TRUE"],
            check=True, capture_output=True,
        )
    config = tmp_path / "ca-certificates.conf"
    config.write_text("\n".join(names) + "\n")
    updater = [
        "update-ca-certificates", "--fresh", "--certsconf", str(config),
        "--certsdir", str(root), "--localcertsdir", str(empty),
        "--etccertsdir", str(store), "--hooksdir", str(empty),
    ]
    subprocess.run(updater, check=True, capture_output=True)
    tasks[0]["ansible.builtin.lineinfile"]["path"] = str(config)
    rebuild = next(task for task in tasks
                   if task["name"] == "Rebuild system CA trust after distrusting emSign")
    rebuild["ansible.builtin.command"]["argv"] = updater
    for task in tasks:
        task["become"] = False
    playbook = tmp_path / "distrust.yml"
    play = {
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"SSL_CERT_FILE": str(store / "ca-certificates.crt"),
                        "SSL_CERT_DIR": str(empty)},
        "vars": {"crewship_installer": str(ROOT / "scripts/provisions.py"),
                 "crewship_cfg": {"home": str(tmp_path)}},
        "tasks": tasks,
    }
    command = [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
               str(playbook)]
    if interrupted:
        playbook.write_text(yaml.safe_dump([{
            **play, "tasks": [tasks[0], {"ansible.builtin.fail": {"msg": "interrupted"}}],
        }]))
        stopped = subprocess.run(command, capture_output=True, text=True)
        assert stopped.returncode != 0
        assert config.read_text().splitlines() == [*("!" + name for name in blocked), names[-1]]
        unsafe = subprocess.run(
            [sys.executable, str(ROOT / "scripts/provisions.py"), "--home", str(tmp_path),
             "--check-ca"],
            env={**os.environ, **play["environment"]}, capture_output=True, text=True,
        )
        assert unsafe.returncode != 0
        assert "still trusts compromised" in unsafe.stderr
    playbook.write_text(yaml.safe_dump([play]))
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    assert config.read_text().splitlines() == [*("!" + name for name in blocked), names[-1]]
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode == 0, second.stdout + second.stderr
    assert "changed=0" in second.stdout


@pytest.mark.parametrize("default_path", [False, True])
@pytest.mark.parametrize("blocked", [False, True])
def test_ca_guard_checks_directory_roots(tmp_path, default_path, blocked):
    store = tmp_path / "store"
    store.mkdir()
    root = store / "root.pem"
    subject = "/CN=emSign Root CA - G1" if blocked else "/CN=Unrelated Root"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256",
         "-nodes", "-keyout", str(tmp_path / "ca.key"), "-out", str(root),
         "-subj", subject, "-days", "1", "-addext", "basicConstraints=critical,CA:TRUE"],
        check=True, capture_output=True,
    )
    subprocess.run(["openssl", "rehash", str(store)], check=True, capture_output=True)
    subprocess.run(
        ["openssl", "verify", "-no-CAfile", "-no-CAstore", "-CApath", str(store), str(root)],
        check=True, capture_output=True,
    )
    environment = {**os.environ, "SSL_CERT_FILE": str(tmp_path / "absent.pem")}
    if default_path:
        environment.pop("SSL_CERT_DIR", None)
    else:
        environment["SSL_CERT_DIR"] = str(store)
    result = subprocess.run(
        [sys.executable, "-c",
         "import runpy, ssl, sys; "
         "paths = ssl.get_default_verify_paths()._replace("
         "capath=sys.argv[1], openssl_capath=sys.argv[1]); "
         "ssl.get_default_verify_paths = lambda: paths; "
         "context = ssl.create_default_context(); "
         "context.load_verify_locations(capath=sys.argv[1]); "
         "assert not context.get_ca_certs(); "
         "ssl.create_default_context = lambda: context; "
         "sys.argv = [sys.argv[2], '--home', sys.argv[1], '--check-ca']; "
         "runpy.run_path(sys.argv[0], run_name='__main__')",
         str(store), str(ROOT / "scripts/provisions.py")],
        env=environment, capture_output=True, text=True,
    )
    assert (result.returncode != 0) == blocked, result.stdout + result.stderr
    if blocked:
        assert "still trusts compromised" in result.stderr
    else:
        assert json.loads(result.stdout)["changed"] is False


def test_runtime_trust_environment_preserves_node_flags(tmp_path):
    generator = "/usr/lib/systemd/user-environment-generators/30-systemd-environment-d-generator"
    node = shutil.which("node")
    home = tmp_path / "home"
    (home / ".config/environment.d").mkdir(parents=True)
    variables = {}
    for name in ("base", "services"):
        variables.update(yaml.safe_load(
            (ROOT / f"blueprint/ansible/group_vars/all/{name}.yml").read_text()
        ))
    variables.update({
        "crewship_cfg": {"home": str(home), "user": getpass.getuser()},
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_account_ready": True, "crewship_become_target": False,
    })
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
    playbook = tmp_path / "runtime-trust.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": variables,
        "tasks": [task for task in tasks if task["name"] in (
            "Use system CA trust in shell profiles",
            "Use system CA trust for future user-manager processes",
        )],
        "handlers": [{"name": "reload user systemd", "ansible.builtin.debug": {"msg": "deferred"}}],
    }]))
    command = [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
               str(playbook)]
    for attempt in range(2):
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stdout + result.stderr
        if attempt:
            assert "changed=0" in result.stdout
    preload = tmp_path / "pre load/flag.js"
    preload.parent.mkdir()
    preload.write_text("")
    trust = {
        "SSL_CERT_FILE": "/etc/ssl/certs/ca-certificates.crt",
        "REQUESTS_CA_BUNDLE": "/etc/ssl/certs/ca-certificates.crt",
        "PIP_CERT": "/etc/ssl/certs/ca-certificates.crt",
        "PIP_USE_DEPRECATED": "legacy-certs",
    }
    probe = (
        'const o = require("internal/options"); console.log(JSON.stringify({'
        'require: o.getOptionValue("--require"), trace: o.getOptionValue("--trace-warnings"),'
        'openssl: o.getOptionValue("--use-openssl-ca"), system: o.getOptionValue("--use-system-ca"),'
        'bundled: o.getOptionValue("--use-bundled-ca"), env: process.env}))'
    )
    client = [node, "--expose-internals", "-e", probe] if node else [
        sys.executable, "-c",
        'import json, os; print(json.dumps({"env": dict(os.environ)}))',
    ]
    expected = {"require": [str(preload)], "trace": True,
                "openssl": True, "system": False, "bundled": False}
    for selector in ("", "--use-system-ca ", "--use-bundled-ca ", "--use-openssl-ca "):
        options = f'{selector}--trace-warnings --require "{preload}"'
        environment = {
            **os.environ, "HOME": str(home), "NODE_OPTIONS": options,
            "XDG_CONFIG_HOME": str(home / ".config"),
            "SSL_CERT_FILE": "/old/bundle", "REQUESTS_CA_BUNDLE": "/old/bundle",
            "PIP_CERT": "/old/bundle", "PIP_USE_DEPRECATED": "",
        }
        runs = [
            ["bash", "--noprofile", "--norc", "-c",
             '. "$1"; . "$1"; shift; exec "$@"',
             "trust-check", str(home / profile), *client]
            for profile in (".profile", ".bashrc")
        ]
        if os.access(generator, os.X_OK):
            # The user manager parses the generator's double-quoted output like a shell.
            manager = subprocess.run([generator], env=environment, capture_output=True,
                                     text=True, check=True).stdout.splitlines()
            runs.append(["bash", "--noprofile", "--norc", "-c",
                         'set -a; eval "$1"; shift; exec "$@"', "trust-check",
                         "\n".join(line for line in manager
                                   if line.split("=", 1)[0] in {"NODE_OPTIONS", *trust}), *client])
        for run in runs:
            result = subprocess.run(run, env=environment, capture_output=True, text=True)
            assert result.returncode == 0, (selector, run, result.stderr)
            actual = json.loads(result.stdout)
            env = actual.pop("env")
            if node:
                assert actual == expected, (selector, run)
            assert {key: env[key] for key in trust} == trust
            assert env["NODE_OPTIONS"] == (
                f"{options} --no-use-system-ca --no-use-bundled-ca --use-openssl-ca"
            )


def redirect_system_paths(tasks, root):
    for task in tasks:
        for module, key in (("ansible.builtin.file", "path"), ("ansible.builtin.copy", "dest")):
            options = task.get(module, {})
            path = options.get(key, "")
            if path.startswith("/etc/systemd/"):
                options[key] = str(root / path.lstrip("/"))


@pytest.mark.parametrize("existing_home", [False, True])
@pytest.mark.parametrize("profiles", [
    {},
    {"fleet_guards": True},
    {"fleet_browsers": True, "firstmate": True},
])
def test_chart_creates_only_missing_directories(tmp_path, existing_home, profiles):
    home = tmp_path / "home"
    home.mkdir()
    journald = tmp_path / "etc/systemd/journald.conf.d"
    journald.mkdir(parents=True)
    (tmp_path / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
    if existing_home:
        for path, mode in (
            (".local/bin", 0o750), (".acpx", 0o750), (".omp/agent/extensions", 0o700),
            (".config/systemd/user/no-mistakes-daemon-.service.d", 0o700),
            ("oss-fleet/doctor", 0o700), ("oss-fleet/browsers", 0o750),
            (".local/share/crewship/imessage", 0o700),
            (".local/share/crewship/instagram-desk", 0o750),
            (".local/share/crewship/cli", 0o750),
            (".local/share/crewship/schedules", 0o700),
        ):
            directory = home / path
            directory.mkdir(parents=True)
            directory.chmod(mode)
        (home / ".local/bin/ponytail-review").write_text("keep this existing file\n")
        (home / ".local/share/crewship/cli/crewship.js").write_text("keep this command\n")
        (home / ".local/share/crewship/schedules/main.ts").write_text("keep this schedule\n")
    before_files = {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                    for path in home.rglob("*") if path.is_file()}
    before_dirs = {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
                   for path in home.rglob("*") if path.is_dir()}
    account_tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/account.yml").read_text())
    layout = [task for task in account_tasks
              if task["name"] in ("Inspect the home layout", "Ensure the home layout")]
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
    end = next(i for i, task in enumerate(tasks) if task["name"] == "Point daemon-spawned omp at the overlay")
    tasks = [
        task for task in tasks[:end + 1]
        if any(key in task for key in ("ansible.builtin.file", "ansible.builtin.copy", "ansible.builtin.stat"))
        or task["name"] in (
            "Inspect the harness preference directories", "Check for existing harness preference files",
        )
    ]
    tool_tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/tools.yml").read_text())
    start = next(i for i, task in enumerate(tool_tasks) if task["name"] == "Ensure the Crewship command directory")
    end = next(i for i, task in enumerate(tool_tasks) if task["name"] == "Install the locked OpenTUI dependencies")
    tasks.extend(tool_tasks[start:end])
    site_tasks = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]["tasks"]
    for include in site_tasks:
        dynamic = include.get("ansible.builtin.include_tasks", {})
        task_file = include.get("ansible.builtin.import_tasks") or dynamic.get("file")
        if task_file not in {
            "tasks/fleet_guards.yml", "tasks/fleet_units.yml", "tasks/fleet-browsers.yml",
            "tasks/imessage.yml", "tasks/instagram_dm.yml",
        }:
            continue
        profile_tasks = yaml.safe_load((ROOT / "blueprint/ansible" / task_file).read_text())
        if task_file.startswith("tasks/fleet"):
            redirect_system_paths(profile_tasks, tmp_path)
        else:
            profile_tasks = [task for task in profile_tasks
                             if task.get("ansible.builtin.copy", {}).get("remote_src")
                             or task.get("ansible.builtin.file", {}).get("state") == "directory"]
        tasks.append({
            "block": profile_tasks,
            **dynamic.get("apply", {}),
            **{key: include[key] for key in ("when", "become", "become_user", "environment")
               if key in include},
        })
    playbook = tmp_path / "chart.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars_files": [str(path) for path in sorted((ROOT / "blueprint/ansible/group_vars/all").glob("*.yml"))],
        "tasks": layout + tasks,
        "handlers": [{"name": name, "ansible.builtin.debug": {"msg": "deferred"}}
                     for name in ("reload user systemd", "no-mistakes daemon restart required",
                                  "restart fm-imessage", "restart instagram-desk",
                                  "restart journald", "restart fleet timers",
                                  "restart fleet browser obscura", "restart fleet browser timers")],
    }]))
    variables = {
        "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
        "crewship": {
            "home": str(home), "workspace": str(home / "Dev"), "user": getpass.getuser(),
            "profiles": {"fleet_guards": False, "fleet_browsers": False, "firstmate": False,
                         **profiles},
            "start_services": False,
            "imessage": {"owner": "+15551234567"},
        },
        "crewship_instagram_dm_operator": "operator",
        "crewship_browser_obscura_dir": str(home / "oss-fleet/browsers/obscura-test"),
        "crewship_browser_obscura": {
            "url": (tmp_path / "absent.tar.gz").as_uri(), "sha256": "0" * 64,
        },
        "ansible_become": False, "crewship_become_target": False, "crewship_account_ready": True,
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
    }
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         "--check", "-e", json.dumps(variables)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert list(journald.iterdir()) == []
    if profiles.get("fleet_guards") or profiles.get("fleet_browsers"):
        assert "would download and extract Obscura" in result.stdout
    assert {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for path in home.rglob("*") if path.is_file()} == before_files
    assert {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
            for path in before_dirs} == before_dirs
    assert all((home / path).is_dir() for path in (
        ".local/bin", ".omp/agent/extensions", ".no-mistakes", ".acpx",
    ))
    assert all((home / ".local/share/crewship" / path).is_dir() for path in ("cli", "schedules"))
    for path, enabled in (
        ("oss-fleet/doctor", profiles.get("fleet_guards", False)),
        ("oss-fleet/browsers",
         profiles.get("fleet_guards", False) or profiles.get("fleet_browsers", False)),
        (".local/share/crewship/imessage", profiles.get("firstmate", False)),
        (".local/share/crewship/instagram-desk", profiles.get("firstmate", False)),
    ):
        assert (home / path).is_dir() == (existing_home or enabled)


@pytest.mark.parametrize("first_write", [False, True])
def test_batched_checks_preserve_existing_preferences_and_respect_firstmate_mode(tmp_path, first_write):
    sources = tmp_path / "sources"
    (sources / "config/nested").mkdir(parents=True)
    (sources / "agent.conf").write_text("managed agent settings\n")
    (sources / "config/settings.conf").write_text("managed Firstmate settings\n")
    (sources / "config/nested/managed.conf").write_text("managed nested settings\n")
    (sources / "config/crew-dispatch.json").write_bytes(
        (ROOT / "blueprint/config/crew-dispatch.json").read_bytes()
    )
    home = tmp_path / "home"
    existing = home / "preferences/existing.conf"
    existing.parent.mkdir(parents=True)
    existing.write_text("private provider settings\n")
    existing.chmod(0o640)
    missing = home / "new-preferences/new.conf"
    destination = home / "firstmate/config"
    (destination / "nested").mkdir(parents=True)
    (destination / "settings.conf").write_text("operator Firstmate settings\n")
    (destination / "nested/operator.conf").write_text("operator nested settings\n")
    agents = yaml.safe_load((ROOT / "blueprint/ansible/tasks/agents.yml").read_text())
    names = {
        "Inspect the harness preference directories", "Ensure the harness preference directories",
        "Check for existing harness preference files", "Write harness preferences that are absent",
        "Report harness preferences left untouched",
    }
    tasks = [task for task in agents if task["name"] in names]
    tasks.append(next(
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/tasks/firstmate.yml").read_text())
        if task["name"] == "Deploy Firstmate dispatch settings"
    ))
    variables = {
        "crewship_repo": str(tmp_path), "crewship_blueprint": str(sources),
        "crewship_path_checker": str(ROOT / "scripts/check_paths.py"),
        "crewship_cfg": {"user": getpass.getuser()},
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_agent_config_files": [
            {"src": "sources/agent.conf", "dest": str(path), "dir_mode": "0700",
             "mode": "0600", "first_write": True}
            for path in (existing, missing)
        ],
        "crewship_firstmate_dir": str(home / "firstmate"),
        "crewship_firstmate_config_names": ["settings.conf", "nested", "crew-dispatch.json"],
        "crewship_firstmate_config_first_write": first_write,
        "crewship_fm_git": {"stat": {"exists": True}},
        "ansible_become": False,
    }
    playbook = tmp_path / "preferences.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": variables, "tasks": tasks,
    }]))
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert existing.read_text() == "private provider settings\n"
    assert existing.stat().st_mode & 0o777 == 0o640
    assert missing.stat().st_mode & 0o777 == 0o600
    expected = "operator Firstmate settings\n" if first_write else "managed Firstmate settings\n"
    assert (destination / "settings.conf").read_text() == expected
    assert (destination / "nested/operator.conf").read_text() == "operator nested settings\n"
    assert (destination / "nested/managed.conf").exists() is not first_write
    dispatch = json.loads((destination / "crew-dispatch.json").read_text())
    choices = {choice["model"]: choice for rule in dispatch["rules"] for choice in rule["use"]}
    assert choices["inception/mercury-3"]["effort"] == "high"
    assert choices["anthropic/claude-opus-5-5"]["effort"] == "high"
    assert all("fable" not in model for model in choices)


@pytest.mark.parametrize("enabled,options", [
    (True, ["--tags", "chat"]),
    (False, ["--tags", "chat"]),
    (True, ["--tags", "all", "--skip-tags", "chat"]),
])
def test_profile_selection_and_tags_preserve_chat_configuration(tmp_path, enabled, options):
    home = tmp_path / "home"
    home.mkdir()
    include = next(
        task for task in yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]["tasks"]
        if task["name"] == "Terminal chat client configs"
    )
    source = str(ROOT / "blueprint/ansible/tasks/chat.yml")
    if "ansible.builtin.import_tasks" in include:
        include["ansible.builtin.import_tasks"] = source
    else:
        include["ansible.builtin.include_tasks"]["file"] = source
    playbook = tmp_path / "profile.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "crewship_cfg": {"home": str(home), "user": getpass.getuser(),
                             "profiles": {"chat": enabled}},
            "crewship_blueprint": str(ROOT / "blueprint"),
            "crewship_account_ready": True, "crewship_become_target": False,
            "crewship_user_env": {"HOME": str(home)}, "ansible_become": False,
        },
        "tasks": [include],
    }]))
    command = [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
               str(playbook), *options]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    if not enabled or "--skip-tags" in options:
        assert not (home / ".config").exists()
        return
    configuration = home / ".config/concord/config.toml"
    assert configuration.is_file()
    assert (home / ".config/slk/config.toml").is_file()
    configuration.write_text("operator configuration\n")
    repeated = subprocess.run(command, capture_output=True, text=True)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert configuration.read_text() == "operator configuration\n"


@pytest.mark.parametrize("task_file,unit,handler", [
    ("herdr.yml", "herdr.service", False),
    ("herdr.yml", "herdr-spaces.timer", False),
    ("browser_prune.yml", "chrome-autoprune.timer", False),
    ("stall_nudge.yml", "fm-main-stall-nudge.timer", False),
    ("herdr.yml", "herdr.service", True),
    ("browser_prune.yml", "chrome-autoprune.timer", True),
])
@pytest.mark.parametrize("check_mode,installed", [(True, False), (True, True), (False, False)])
def test_service_preview_skips_only_absent_units(tmp_path, task_file, unit, handler, check_mode, installed):
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks" / task_file).read_text())
    probes = [
        task for task in tasks
        if any(task.get(module, {}).get(key) == "{{ crewship_user_units }}/" + unit
               for module, key in (("ansible.builtin.stat", "path"), ("ansible.builtin.slurp", "src")))
    ]
    if handler:
        tasks = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]["handlers"]
    start = next(task for task in tasks
                 if task.get("ansible.builtin.systemd_service", {}).get("name") == unit)
    start.pop("listen", None)
    if installed:
        (tmp_path / unit).write_text("[Unit]\nDescription=Preview test\n")
    systemctl = tmp_path / "systemctl"
    systemctl.write_text("#!/bin/sh\necho 'systemd probe failed' >&2\nexit 1\n")
    systemctl.chmod(0o755)
    playbook = tmp_path / "preview.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "crewship_user_units": str(tmp_path), "crewship_manage_services": True,
            "crewship_become_target": False, "crewship_cfg": {"user": getpass.getuser()},
            "crewship_user_systemd_env": {"PATH": f"{tmp_path}:{os.environ['PATH']}"},
        },
        "tasks": probes + [start],
    }]))
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         *(["--check"] if check_mode else [])],
        capture_output=True, text=True,
    )
    output = result.stdout + result.stderr
    if check_mode and not installed:
        assert result.returncode == 0, output
        assert "skipping: [localhost]" in output
    else:
        assert result.returncode != 0, output
        assert "systemd probe failed" in output


@pytest.mark.parametrize("check_mode", [True, False])
@pytest.mark.parametrize("release_state", ["absent", "empty", "installed"])
def test_obscura_release_preview_and_install(tmp_path, check_mode, release_state):
    browsers = tmp_path / "home/oss-fleet/browsers"
    browsers.mkdir(parents=True)
    release = browsers / "obscura-test"
    binaries = ("obscura", "obscura-worker")
    if release_state != "absent":
        release.mkdir(mode=0o700)
    if release_state == "installed":
        for binary in binaries:
            (release / binary).write_bytes(b"existing release\n")
    archive = tmp_path / "release.tar.gz"
    if not check_mode and release_state != "installed":
        source = tmp_path / "source"
        source.mkdir()
        with tarfile.open(archive, "w:gz") as bundle:
            for binary in binaries:
                (source / binary).write_bytes(b"archive release\n")
                bundle.add(source / binary, arcname=binary)
    before_files = {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                    for path in browsers.rglob("*") if path.is_file()}
    before_dirs = {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
                   for path in browsers.rglob("*") if path.is_dir()}
    tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/fleet-browsers.yml").read_text())
    start = next(i for i, task in enumerate(tasks)
                 if task["name"] == "Stat the resolved Obscura release")
    end = next(i for i, task in enumerate(tasks)
               if task["name"] == "Inject the shared-browser env into shell profiles")
    playbook = tmp_path / "obscura.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "tasks": tasks[start:end],
    }]))
    variables = {
        "crewship_cfg": {"user": getpass.getuser()},
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_fleet_browsers_dir": str(browsers),
        "crewship_browser_obscura_dir": str(release),
        "crewship_browser_obscura": {
            "url": archive.as_uri(),
            "sha256": hashlib.sha256(archive.read_bytes()).hexdigest() if archive.exists() else "0" * 64,
        },
        "ansible_become": False,
    }
    result = subprocess.run(
        [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,", str(playbook),
         *(["--check"] if check_mode else []), "-e", json.dumps(variables)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not release.with_suffix(".tar.gz").exists()
    if check_mode:
        assert {path: (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
                for path in browsers.rglob("*") if path.is_file()} == before_files
        assert {path: (path.stat().st_mode, path.stat().st_uid, path.stat().st_gid)
                for path in browsers.rglob("*") if path.is_dir()} == before_dirs
        assert (f"would download and extract Obscura into {release}." in result.stdout) == (
            release_state != "installed"
        )
    else:
        expected = b"existing release\n" if release_state == "installed" else b"archive release\n"
        for binary in binaries:
            assert (release / binary).read_bytes() == expected
            assert (browsers / binary).is_symlink()
            assert (browsers / binary).resolve() == release / binary


@pytest.mark.parametrize("mode", ["fresh", "existing", "disabled", "deferred", "check", "preexisting", "all"])
def test_default_schedules_tab_preserves_existing_layout(tmp_path, mode):
    home = tmp_path / "home with spaces"
    local_bin = home / ".local/bin"
    local_bin.mkdir(parents=True)
    (home / ".local/share/crewship/cli").mkdir(parents=True)
    state = tmp_path / "herdr.json"
    initial = {"workspaces": [{"workspace_id": "w9", "label": "other"}],
               "tabs": [], "runs": []}
    if mode == "existing":
        initial["workspaces"].append({"workspace_id": "w1", "label": "machine"})
        initial["tabs"].append({"tab_id": "w1:t1", "label": "custom"})
    if mode == "preexisting":
        initial["workspaces"].append({"workspace_id": "w1", "label": "machine"})
        initial["tabs"].append({"tab_id": "w1:t2", "label": "schedules"})
    state.write_text(json.dumps(initial))
    herdr = tmp_path / "herdr"
    herdr.write_text(f"""#!{sys.executable}
import json, os, subprocess, sys
from pathlib import Path
p = Path({str(state)!r})
s = json.loads(p.read_text())
a = sys.argv[1:]
if a[:2] == ["workspace", "list"]:
    result = {{"workspaces": s["workspaces"]}}
elif a[:2] == ["workspace", "create"]:
    assert "--no-focus" in a
    workspace = {{"workspace_id": "w1", "label": a[a.index("--label") + 1]}}
    s["workspaces"].append(workspace)
    result = {{"workspace": workspace}}
elif a[:2] == ["tab", "list"]:
    assert a[a.index("--workspace") + 1] == "w1"
    result = {{"tabs": s["tabs"]}}
elif a[:2] == ["tab", "create"]:
    assert "--no-focus" in a
    tab = {{"tab_id": "w1:t2", "label": a[a.index("--label") + 1]}}
    s["tabs"].append(tab)
    result = {{"tab": tab, "root_pane": {{"pane_id": "w1:p2"}}}}
elif a[:2] == ["pane", "run"]:
    assert a[2] == "w1:p2"
    subprocess.run(a[3], shell=True, check=True)
    s["runs"].append(a[3])
    result = {{}}
else:
    raise AssertionError(a)
p.write_text(json.dumps(s))
print(json.dumps({{"result": result}}))
""")
    herdr.chmod(0o755)
    viewer_call = tmp_path / "viewer.json"
    pane_commands = ["usage-tui", "crewboard-tui", "fleet-health-tui"]
    pane_log = tmp_path / "panes.log"
    for name in pane_commands:
        stub = local_bin / name
        stub.write_text(f"#!/bin/sh\necho {name} >> {pane_log}\n")
        stub.chmod(0o755)
    bun = local_bin / "bun"
    bun.write_text(f"#!{sys.executable}\nimport json, sys\n"
                   f"from pathlib import Path\nPath({str(viewer_call)!r}).write_text(json.dumps(sys.argv[1:]))\n")
    bun.chmod(0o755)
    tool_tasks = yaml.safe_load((ROOT / "blueprint/ansible/tasks/tools.yml").read_text())
    start = next(i for i, task in enumerate(tool_tasks) if task["name"] == "Ensure the Crewship command directory")
    end = next(i for i, task in enumerate(tool_tasks) if task["name"] == "Ensure the OpenTUI schedule directory")
    site = yaml.safe_load((ROOT / "blueprint/ansible/site.yml").read_text())[0]
    # Run the real post-task sequence: the viewer must start after notified restarts.
    post_tasks = [task for task in site["post_tasks"]
                  if task.get("ansible.builtin.import_tasks") != "tasks/verify.yml"]
    for task in post_tasks:
        if path := task.get("ansible.builtin.import_tasks"):
            task["ansible.builtin.import_tasks"] = str(ROOT / "blueprint/ansible" / path)
    playbook = tmp_path / "schedules.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "environment": {"HOME": str(home), "PATH": f"{local_bin}:{os.environ['PATH']}"},
        "tasks": tool_tasks[start:end],
        "post_tasks": post_tasks,
    }]))
    base = yaml.safe_load((ROOT / "blueprint/ansible/group_vars/all/base.yml").read_text())
    variables = {
        **{k: base[k] for k in ("crewship_tuis", "crewship_herdr_tabs", "crewship_herdr_open_tabs")},
        "crewship_cfg": {"user": getpass.getuser(), "home": str(home),
                         "herdr": {"schedules_tab": mode != "disabled",
                                  **({} if mode == "all" else {k: False for k in (
                                      "usage_tab", "crewboard_tab", "fleet_health_tab")})}},
        "crewship_group": grp.getgrgid(os.getgid()).gr_name,
        "crewship_repo": str(ROOT), "crewship_local_bin": str(local_bin),
        "crewship_share_dir": str(home / ".local/share/crewship"),
        "crewship_herdr_bin": str(herdr), "crewship_manage_services": mode != "deferred",
        "crewship_account_ready": True, "crewship_become_target": False,
        "crewship_user_env": {"HOME": str(home), "PATH": f"{local_bin}:{os.environ['PATH']}"},
    }
    command = [str(Path(sys.executable).parent / "ansible-playbook"), "-i", "localhost,",
               str(playbook), "-e", json.dumps(variables), *(["--check"] if mode == "check" else [])]
    for attempt in range(2):
        before = json.loads(state.read_text())
        result = subprocess.run(command, capture_output=True, text=True)
        output = result.stdout + result.stderr
        assert result.returncode == 0, output
        if mode == "preexisting" or (attempt == 1 and mode not in ("disabled", "deferred", "check")):
            assert "run crewship schedules in the schedules tab" in output
            assert json.loads(state.read_text()) == before
    actual = json.loads(state.read_text())
    if mode in ("disabled", "deferred", "check", "preexisting"):
        assert actual == initial
        assert not viewer_call.exists()
    elif mode == "all":
        assert [t["label"] for t in actual["tabs"]] == ["schedules", *pane_commands]
        assert len(actual["runs"]) == 4
        assert pane_log.read_text().split() == pane_commands
        assert "changed=0" in result.stdout
    else:
        assert actual["workspaces"] == [
            {"workspace_id": "w9", "label": "other"}, {"workspace_id": "w1", "label": "machine"},
        ]
        assert actual["tabs"] == initial["tabs"] + [{"tab_id": "w1:t2", "label": "schedules"}]
        assert len(actual["runs"]) == 1
        assert json.loads(viewer_call.read_text()) == [str(home / ".local/share/crewship/schedules/main.ts")]
        assert "changed=0" in result.stdout


@pytest.mark.parametrize("location", ["default", "relative", "absolute"])
def test_onboarding_uses_the_uv_project_environment(tmp_path, location):
    project = tmp_path / "project"
    (project / "scripts").mkdir(parents=True)
    shutil.copy2(ROOT / "onboard.sh", project / "onboard.sh")
    shutil.copy2(ROOT / "scripts/provisions.py", project / "scripts/provisions.py")
    (project / "pyproject.toml").write_text(
        '[project]\nname = "onboard-regression"\nversion = "0.0.0"\n'
        'requires-python = ">=3.12"\ndependencies = []\n[tool.uv]\npackage = false\n'
    )
    home = tmp_path / "home"
    commands = home / ".local/bin"
    commands.mkdir(parents=True)
    (commands / "uv").symlink_to(shutil.which("uv"))
    python = commands / "python3"
    python.write_text(
        '#!/bin/sh\n'
        'if [ "${4-}" = "--tools" ] && [ "${5-}" = "uv" ]; then exit 0; fi\n'
        f'exec {shlex.quote(sys.executable)} "$@"\n'
    )
    python.chmod(0o755)
    environment = {
        **os.environ, "HOME": str(home),
        "PATH": str(commands) + os.pathsep + os.environ["PATH"],
        "UV_PYTHON": sys.executable, "UV_OFFLINE": "1",
        "UV_PYTHON_DOWNLOADS": "never", "UV_CACHE_DIR": str(tmp_path / "cache"),
    }
    for key in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_NO_PROJECT", "PYTHONPATH"):
        environment.pop(key, None)
    selected = project / ".venv"
    if location != "default":
        selected = project / "custom-env" if location == "relative" else tmp_path / "external-env"
        environment["UV_PROJECT_ENVIRONMENT"] = (
            "custom-env" if location == "relative" else str(selected)
        )
    subprocess.run(
        [str(commands / "uv"), "lock", "--project", str(project)],
        env=environment, check=True, capture_output=True,
    )
    for _ in range(2):
        result = subprocess.run(
            ["bash", str(project / "onboard.sh")], cwd=tmp_path, env=environment,
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert (selected / "bin/python").exists()
        if location != "default":
            assert not (project / ".venv").exists()
