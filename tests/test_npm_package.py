"""The crewship npm package ships only its installer launcher, never the rest of the repository."""

import ast
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

PACKAGE = Path(__file__).parents[1] / "tools/npm"


@pytest.mark.skipif(not shutil.which("npm"), reason="needs npm")
def test_tarball_holds_only_the_launcher():
    result = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=PACKAGE,
        capture_output=True,
        text=True,
        check=True,
    )
    files = {entry["path"] for entry in json.loads(result.stdout)[0]["files"]}
    assert files == {"package.json", "README.md", "crewship.js"}


@pytest.mark.skipif(not (shutil.which("npm") and shutil.which("node")), reason="needs npm and node")
@pytest.mark.parametrize("os_name", ["linux", "darwin"])
def test_packed_tarball_installs_and_runs_its_bin(tmp_path, os_name):
    subprocess.run(["npm", "pack", "--pack-destination", str(tmp_path)], cwd=PACKAGE, capture_output=True, check=True)
    (tarball,) = tmp_path.glob("crewship-*.tgz")
    # npm raises EBADPLATFORM for a package "os" field only when its own process.platform differs, so stub that.
    stub = tmp_path / "platform.js"
    stub.write_text(f"Object.defineProperty(process, 'platform', {{ value: '{os_name}' }});\n")
    env = {**os.environ, "NODE_OPTIONS": f"--require {stub}", "npm_config_cache": str(tmp_path / "cache")}
    subprocess.run(
        ["npm", "install", "-g", "--prefix", str(tmp_path / "prefix"), "--offline", str(tarball)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    bin_path = tmp_path / "prefix/bin/crewship"
    version = json.loads((PACKAGE / "package.json").read_text())["version"]
    for flag in ("--version", "--help"):
        result = subprocess.run([str(bin_path), flag], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Usage: crewship ")
    assert subprocess.run([str(bin_path), "--version"], capture_output=True, text=True).stdout == f"{version}\n"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_launcher_off_ubuntu_says_where_to_run_it_and_never_fetches(tmp_path):
    stub = tmp_path / "darwin.js"
    stub.write_text(
        "Object.defineProperty(process, 'platform', { value: 'darwin' });\n"
        "globalThis.fetch = () => { throw new Error('fetch called'); };\n"
    )
    run = lambda *args: subprocess.run(  # noqa: E731
        [shutil.which("node"), "--require", str(stub), str(PACKAGE / "crewship.js"), *args],
        capture_output=True,
        text=True,
        timeout=10,
    )
    for args in ([], ["update"]):
        result = run(*args)
        assert result.returncode == 1
        assert "installs on an Ubuntu 24.04 or 26.04 server, not on darwin" in result.stderr
    assert run("--version").returncode == 0
    assert run("--help").returncode == 0


def launcher_value(expression):
    result = subprocess.run(
        ["node", "-e", f"const launcher = require({json.dumps(str(PACKAGE / 'crewship.js'))});"
         f"console.log(JSON.stringify({expression}));"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(result.stdout)


@pytest.fixture
def run_init(tmp_path):
    stub = tmp_path / "launcher-stub.cjs"
    stub.write_text(
        "Object.defineProperty(process, 'platform', { value: process.env.TEST_PLATFORM || 'linux' });\n"
        "globalThis.fetch = () => { throw new Error('unexpected fetch'); };\n"
        "require('node:child_process').spawnSync = (command, args, options) => {\n"
        "  console.log('\\nSPAWN:' + JSON.stringify({command, args, options}));\n"
        "  return {status: Number(process.env.TEST_SSH_STATUS || 0)};\n"
        "};\n"
    )

    def run(answers, platform="linux", ssh_status=0):
        return subprocess.run(
            ["node", "--require", str(stub), str(PACKAGE / "crewship.js"), "init"],
            input=answers, capture_output=True, text=True, timeout=10,
            env={**os.environ, "TEST_PLATFORM": platform, "TEST_SSH_STATUS": str(ssh_status)},
        )

    return run


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
def test_init_runs_before_the_platform_guard_without_local_install(run_init, platform):
    result = run_init("yes\n4\n16\n100\nnone\na\n", platform)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Do you already have a server for Crewship?")
    assert "ON THE SERVER" in result.stdout
    assert "--with none" in result.stdout
    assert "SPAWN:" not in result.stdout


@pytest.mark.parametrize("answer", ["no\n", "\n", ""])
def test_purchase_requires_explicit_yes_before_any_setup(run_init, answer):
    result = run_init("no\n2\n2\nnone\n" + answer)
    assert "8 vCPU, 32 GB RAM, 200 GB disk, 16 GB swap" in result.stdout
    assert "Print a server command" not in result.stdout
    assert "SPAWN:" not in result.stdout


@pytest.mark.parametrize("light,ui,ram,cpu,preset", [(2, 2, 31, 6, 32), (8, 4, 59, 16, 64)])
def test_load_formula_selects_the_smallest_documented_preset(run_init, light, ui, ram, cpu, preset):
    result = run_init(f"no\n{light}\n{ui}\nboard\nyes\na\n")
    assert result.returncode == 0, result.stderr
    assert f"Estimate: {ram} GB RAM and {cpu} vCPU" in result.stdout
    assert f"{preset} GB RAM" in result.stdout
    assert "--with board,development" in result.stdout


def test_feature_names_and_dependencies_match_dock():
    tree = ast.parse((PACKAGE.parents[1] / "scripts/ship.py").read_text())
    policy = next(ast.literal_eval(node.value) for node in tree.body
                  if isinstance(node, ast.Assign) and any(
                      isinstance(target, ast.Name) and target.id == "OPT_IN" for target in node.targets))
    assert launcher_value("launcher.optIn") == {name: list(value[1]) for name, value in policy.items()}
    assert launcher_value("launcher.features('fleet_guards,project_databases,board')") == (
        "fleet_guards,docker,project_databases,board,development"
    )


@pytest.mark.parametrize("field,value", [
    ("alias", "-oProxyCommand=touch marker"), ("alias", "server;touch marker"),
    ("host", "$(touch marker)"), ("host", "host`id`"), ("host", "host\nid"),
    ("user", "user;id"), ("user", "root"), ("port", "22;id"), ("port", "65536"),
])
def test_ssh_target_rejects_shell_syntax(field, value):
    target = {"alias": "", "host": "server.example", "user": "worker", "port": "22"}
    target[field] = value
    result = subprocess.run(
        ["node", "-e", f"require({json.dumps(str(PACKAGE / 'crewship.js'))}).sshArgs({json.dumps(target)})"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


@pytest.mark.parametrize("answer", ["no\n", "\n", ""])
def test_ssh_consent_requires_explicit_yes(run_init, answer):
    result = run_init("yes\n4\n16\n100\nnone\nb\nserver\n\n" + answer)
    assert "SPAWN:" not in result.stdout


@pytest.mark.parametrize("ssh_status,count", [(0, 2), (255, 1)])
def test_ssh_uses_key_only_argument_arrays_and_a_native_terminal(run_init, ssh_status, count):
    result = run_init("yes\n4\n16\n100\nboard\nb\n\nserver.example\nworker\n2222\nyes\n",
                      ssh_status=ssh_status)
    calls = [json.loads(line.removeprefix("SPAWN:")) for line in result.stdout.splitlines()
             if line.startswith("SPAWN:")]
    assert result.returncode == 0, result.stderr
    assert len(calls) == count
    for call in calls:
        assert call["command"] == "ssh"
        assert call["args"][-3:-1] == ["--", "server.example"]
        assert ["-p", "2222", "-l", "worker"] == call["args"][-7:-3]
        for option in ("ForwardAgent=no", "BatchMode=yes", "StrictHostKeyChecking=ask",
                       "PasswordAuthentication=no", "KbdInteractiveAuthentication=no"):
            assert option in call["args"]
        assert "shell" not in call["options"]
    if ssh_status:
        assert "ON THE SERVER" in result.stdout
    else:
        assert calls[1]["args"][0] == "-t"
        assert calls[1]["options"]["stdio"] == "inherit"


@pytest.mark.parametrize("fault", ["none", "os", "systemd", "root", "cpu", "ram", "disk", "sudo"])
def test_remote_checks_stop_before_install_and_preserve_existing_config(tmp_path, fault):
    script = launcher_value("launcher.serverScript(launcher.presets[0], 'board,development')")
    os_release = tmp_path / "os-release"
    os_release.write_text(f"ID={'debian' if fault == 'os' else 'ubuntu'}\nVERSION_ID=24.04\n")
    memory = tmp_path / "meminfo"
    memory.write_text(f"MemTotal: {(8 if fault == 'ram' else 16) * 1024 * 1024} kB\n")
    systemd = tmp_path / "systemd"
    if fault != "systemd":
        systemd.mkdir()
    script = script.replace("/etc/os-release", str(os_release))
    script = script.replace("/proc/meminfo", str(memory)).replace("/run/systemd/system", str(systemd))
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "install-args"
    commands = {
        "id": f"echo {0 if fault == 'root' else 1000}",
        "nproc": f"echo {2 if fault == 'cpu' else 4}",
        "df": f"printf 'Available\\nroot 0 0 {50000000 if fault == 'disk' else 200000000}\\n'",
        "sudo": f"exit {1 if fault == 'sudo' else 0}",
        "curl": f"""printf 'printf "%%s\\\\n" "$*" >> "{log}"\\n'""",
    }
    for name, body in commands.items():
        executable = binaries / name
        executable.write_text("#!/bin/sh\n" + body + "\n")
        executable.chmod(0o755)
    env = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}", "HOME": str(tmp_path)}
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    if fault != "none":
        assert result.returncode != 0
        assert not log.exists()
        return
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "--with board,development\n"
    log.unlink()
    config = tmp_path / "Crewship/.local/host.yml"
    config.parent.mkdir(parents=True)
    config.write_text("keep existing config\n")
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "\n"
    assert config.read_text() == "keep existing config\n"


@pytest.mark.parametrize("answer", ["board;id", "$(id)", "__proto__"])
def test_invalid_features_never_reach_setup(run_init, answer):
    result = run_init(f"no\n2\n0\n{answer}\nyes\na\n")
    assert result.returncode == 1
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout


@pytest.mark.parametrize("specs", ["2\n16\n100", "4\n8\n100", "4\n16\n50"])
def test_small_existing_server_stops_before_setup(run_init, specs):
    result = run_init(f"yes\n{specs}\nnone\na\n")
    assert result.returncode == 1
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout


def test_load_above_presets_stops_at_recommendation(run_init):
    result = run_init("no\n32\n8\nnone\nyes\na\n")
    assert result.returncode == 0
    assert "107 GB RAM and 48 vCPU" in result.stdout
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout
