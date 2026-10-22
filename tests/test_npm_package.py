"""The crewship npm package ships only its installer launcher, never the rest of the repository."""

import importlib.util
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
        result = subprocess.run([str(bin_path), flag], capture_output=True, text=True, timeout=60)
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
        timeout=60,
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
            input=answers, capture_output=True, text=True, timeout=60,
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
    result = run_init("no\nno\n2\n2\nnone\n0\n0\n" + answer)
    assert "8 vCPU, 32 GB RAM, 200 GB disk, 16 GB swap" in result.stdout
    assert "Print a server command" not in result.stdout
    assert "SPAWN:" not in result.stdout


@pytest.mark.parametrize("light,ui,browsers,disk,ram,cpu,preset_ram,preset_disk", [
    (2, 2, 0, 0, 31, 6, 32, 200),
    (8, 4, 0, 0, 59, 16, 64, 300),
    (2, 0, 2, 0, 19, 2, 32, 200),
    (2, 0, 0, 200, 15, 2, 64, 300),
    (2, 2, 0, 100, 31, 6, 64, 300),
])
def test_load_formula_selects_the_smallest_documented_preset(
    run_init, light, ui, browsers, disk, ram, cpu, preset_ram, preset_disk,
):
    result = run_init(f"no\nno\n{light}\n{ui}\nboard\n{browsers}\n{disk}\nyes\na\n")
    assert result.returncode == 0, result.stderr
    assert f"Estimate: {ram} GB RAM and {cpu} vCPU" in result.stdout
    assert f"{preset_ram} GB RAM, {preset_disk} GB disk" in result.stdout
    assert "--with board,development" in result.stdout


def test_unknown_load_can_explicitly_use_two_light_lanes(run_init):
    result = run_init("no\nyes\nnone\n0\n0\nyes\na\n")
    assert result.returncode == 0, result.stderr
    assert "Estimate: 15 GB RAM and 2 vCPU" in result.stdout
    assert "4 vCPU, 16 GB RAM, 100 GB disk" in result.stdout
    assert "ON THE SERVER" in result.stdout


@pytest.mark.parametrize("answer", ["\n", "maybe\n", ""])
def test_starter_requires_an_explicit_choice(run_init, answer):
    result = run_init("no\n" + answer)
    assert result.returncode != 0
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout


def test_feature_names_and_dependencies_match_dock():
    spec = importlib.util.spec_from_file_location("ship", PACKAGE.parents[1] / "scripts/ship.py")
    ship = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ship)
    policy = ship.OPT_IN
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


@pytest.mark.skipif(not shutil.which("ssh"), reason="needs ssh")
@pytest.mark.parametrize("target,port,expected", [
    ("server\n", "", "2222"),
    ("server\n", "2223", "2223"),
    ("\nserver.example\nworker\n", "", "2222"),
])
def test_ssh_preserves_port_and_limits_authentication(run_init, tmp_path, target, port, expected):
    config = tmp_path / "ssh-config"
    config.write_text(
        "Host *\n  HostName server.invalid\n  User worker\n  Port 2222\n"
        "  GSSAPIAuthentication yes\n  PreferredAuthentications gssapi-with-mic,hostbased,publickey\n"
    )
    result = run_init(f"yes\n4\n16\n100\nnone\nb\n{target}{port}\nyes\n")
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line.removeprefix("SPAWN:")) for line in result.stdout.splitlines()
             if line.startswith("SPAWN:")]
    assert len(calls) == 2
    for call in calls:
        resolved = subprocess.run(
            ["ssh", "-G", "-F", str(config), *call["args"][:-1]],
            capture_output=True, text=True, check=True,
        )
        assert f"port {expected}" in resolved.stdout.splitlines()
        policy = dict(line.split(maxsplit=1) for line in resolved.stdout.splitlines())
        assert policy["preferredauthentications"] == "publickey"


@pytest.fixture
def server_environment(tmp_path):
    def configure(size, fault="none"):
        os_release = tmp_path / "os-release"
        os_release.write_text(f"ID={'debian' if fault == 'os' else 'ubuntu'}\nVERSION_ID=24.04\n")
        memory = tmp_path / "meminfo"
        ram_kib = int(size["ram"] * 0.9 * 1e9 / 1024)
        memory.write_text(f"MemTotal: {ram_kib + (-1 if fault == 'ram' else 1)} kB\n")
        systemd = tmp_path / "systemd"
        if fault != "systemd":
            systemd.mkdir()
        binaries = tmp_path / "bin"
        binaries.mkdir()
        log = tmp_path / "install-args"
        sudo_log = tmp_path / "sudo-args"
        curl = tmp_path / "curl"
        curl.write_text(
            "#!/bin/sh\n"
            f"""printf 'printf "%%s|%%s\\\\n" "${{CREWSHIP_REF:-latest}}" "$*" >> "{log}"\\n'\n"""
        )
        curl.chmod(0o755)
        disk_kib = int(size["disk"] * 0.9 * 1e9 / 1024)
        commands = {
            "id": f"echo {0 if fault == 'root' else 1000}",
            "nproc": f"echo {size['cpu'] - (1 if fault == 'cpu' else 0)}",
            "df": f"printf 'Filesystem 1024-blocks Used Available Capacity Mounted\\n"
                  f"root {disk_kib + (-1 if fault == 'disk' else 1)} 1 1 99%% /\\n'",
            "sudo": f'printf "%s\\n" "$*" >> "{sudo_log}"\n'
                    f"exit_status={1 if fault == 'sudo' else 0}\n"
                    '[ "$exit_status" = 0 ] || exit "$exit_status"\n'
                    f'[ "$*" != "apt-get install -y curl" ] || '
                    f'[ "{fault}" != "curl-install" ] || exit 1\n'
                    f'[ "$*" != "apt-get install -y curl" ] || '
                    f'"{shutil.which("cp")}" "{curl}" "{binaries / "curl"}"',
        }
        for name, body in commands.items():
            executable = binaries / name
            executable.write_text("#!/bin/sh\n" + body + "\n")
            executable.chmod(0o755)
        if fault not in ("curl", "curl-install"):
            (binaries / "curl").symlink_to(curl)
        for name in ("bash", "env", "awk"):
            (binaries / name).symlink_to(shutil.which(name))
        env = {
            **os.environ, "PATH": str(binaries), "HOME": str(tmp_path), "CREWSHIP_REF": "v0.0.1",
        }
        paths = {"/etc/os-release": os_release, "/proc/meminfo": memory, "/run/systemd/system": systemd}
        return env, paths, log, sudo_log

    return configure


@pytest.mark.parametrize("index,fault", [
    (0, fault) for fault in (
        "none", "os", "systemd", "root", "cpu", "ram", "disk", "sudo", "curl", "curl-install",
    )
] + [(index, fault) for index in (1, 2) for fault in ("none", "ram", "disk")])
def test_remote_checks_stop_before_install_and_preserve_existing_config(
    server_environment, tmp_path, fault, index,
):
    size = launcher_value(f"launcher.presets[{index}]")
    script = launcher_value(f"launcher.serverScript(launcher.presets[{index}], 'board,development')")
    env, paths, log, sudo_log = server_environment(size, fault)
    for original, replacement in paths.items():
        script = script.replace(original, str(replacement))
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    if fault not in ("none", "curl"):
        assert result.returncode != 0
        assert not log.exists()
        return
    assert result.returncode == 0, result.stderr
    version = json.loads((PACKAGE / "package.json").read_text())["version"]
    assert log.read_text() == f"v{version}|--with board,development\n"
    if fault == "curl":
        assert sudo_log.read_text().splitlines() == ["-v", "apt-get update", "apt-get install -y curl"]
    log.unlink()
    config = tmp_path / "Crewship/.local/host.yml"
    config.parent.mkdir(parents=True)
    config.write_text("keep existing config\n")
    result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "latest|\n"
    assert config.read_text() == "keep existing config\n"


@pytest.mark.parametrize("fault", ["none", "curl", "curl-install"])
def test_manual_command_installs_prerequisites_and_preserves_release(
    run_init, server_environment, tmp_path, fault,
):
    result = run_init("yes\n4\n16\n100\nboard\na\n")
    assert result.returncode == 0, result.stderr
    command = result.stdout[result.stdout.index("if ! command -v curl"):]
    command = command.split("\nAfter installation,", 1)[0]
    env, _, log, sudo_log = server_environment({"cpu": 4, "ram": 16, "disk": 100}, fault)
    result = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    if fault == "curl-install":
        assert result.returncode != 0
        assert not log.exists()
        return
    assert result.returncode == 0, result.stderr
    version = json.loads((PACKAGE / "package.json").read_text())["version"]
    assert log.read_text() == f"v{version}|--with board,development\n"
    if fault == "curl":
        assert sudo_log.read_text().splitlines() == ["apt-get update", "apt-get install -y curl"]
    log.unlink()
    config = tmp_path / "Crewship/.local/host.yml"
    config.parent.mkdir(parents=True)
    config.write_text("keep existing config\n")
    result = subprocess.run(["bash", "-c", command], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert log.read_text() == "latest|\n"
    assert config.read_text() == "keep existing config\n"


@pytest.mark.parametrize("answer", ["board;id", "$(id)", "__proto__"])
def test_invalid_features_never_reach_setup(run_init, answer):
    result = run_init(f"no\nno\n2\n0\n{answer}\n0\n0\nyes\na\n")
    assert result.returncode == 1
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout


@pytest.mark.parametrize("specs", [
    "2\n16\n100", "4\n8\n100", "4\n16\n50", "4\n14.39\n100", "4\n16\n89.99",
])
def test_small_existing_server_stops_before_setup(run_init, specs):
    result = run_init(f"yes\n{specs}\nnone\na\n")
    assert result.returncode == 1
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout


@pytest.mark.parametrize("cpu,ram,disk,preset", [
    (4, 14.4, 90, 16), (8, 31.3, 180, 32), (16, 57.6, 270, 64),
])
def test_existing_server_accepts_nominal_capacity_tolerance(run_init, cpu, ram, disk, preset):
    result = run_init(f"yes\n{cpu}\n{ram}\n{disk}\nnone\na\n")
    assert result.returncode == 0, result.stderr
    assert f"The server meets the {cpu} vCPU / {preset} GB RAM" in result.stdout
    assert "ON THE SERVER" in result.stdout


@pytest.mark.parametrize("light,ui,browsers,disk,ram,cpu,estimate", [
    (32, 8, 0, 0, 139, 48, "139 GB RAM and 48 vCPU"),
    (2, 0, 25, 0, 65, 2, "65 GB RAM and 2 vCPU"),
    (2, 0, 0, 201, 15, 2, "301 GB disk"),
])
def test_load_above_presets_stops_at_recommendation(run_init, light, ui, browsers, disk, ram, cpu, estimate):
    result = run_init(f"no\nno\n{light}\n{ui}\nnone\n{browsers}\n{disk}\nyes\na\n")
    assert result.returncode == 0
    assert estimate in result.stdout
    ram_formula = (
        "RAM_GB = 11 + 2L + 8U + 2 x extra browsers = "
        f"11 + 2 x {light} + 8 x {ui} + 2 x {browsers} = {ram}"
    )
    cpu_formula = f"vCPU = L + 2U = {light} + 2 x {ui} = {cpu}"
    quote = result.stdout.index("Obtain a larger server quote")
    assert result.stdout.index(ram_formula) < result.stdout.index(cpu_formula) < quote
    assert "SPAWN:" not in result.stdout
    assert "ON THE SERVER" not in result.stdout
