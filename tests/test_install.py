"""install.sh and the npm launcher print the usage before any install step."""

import errno
import getpass
import importlib.util
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
BASH = shutil.which("bash")
SHIP = importlib.util.spec_from_file_location("ship", ROOT / "scripts/ship.py")
ship = importlib.util.module_from_spec(SHIP)
SHIP.loader.exec_module(ship)


def sandbox(tmp_path):
    """An empty PATH (no apt-get, git or sudo) and a read-only HOME: any install step fails."""
    (tmp_path / "bin").mkdir()
    home = tmp_path / "home"
    home.mkdir(mode=0o500)
    return {"PATH": str(tmp_path / "bin"), "HOME": str(home)}


def install(env, *args):
    # Script on stdin, the way `curl | bash` and the launcher run it.
    return subprocess.run(
        [BASH, "-s", "--", *args],
        input=(ROOT / "install.sh").read_text(),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


def install_log(result):
    for line in (result.stdout + result.stderr).splitlines():
        if line.startswith("Full install log: "):
            return Path(line.removeprefix("Full install log: "))
    pytest.fail("The installer did not print its log path")


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["--container", "--help"], ["--user", "--help"]])
def test_help_prints_usage_and_changes_nothing(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout.startswith("Usage: crewship ")
    assert not any((tmp_path / "home").iterdir())


def test_usage_names_every_opt_in_feature(tmp_path):
    usage = install(sandbox(tmp_path), "--help").stdout
    assert all(name in usage.split() for name in ship.OPT_IN)


@pytest.mark.parametrize("args", [["--bogus"], ["--user"], ["--with"], ["--container", "extra"]])
def test_bad_option_prints_usage_and_fails(tmp_path, args):
    result = install(sandbox(tmp_path), *args)
    assert result.returncode == 2
    assert f"bad option: {args[-1]}" in result.stderr
    assert "Usage: crewship " in result.stderr
    assert result.stdout == ""


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_launcher_help_matches_install_without_fetch(tmp_path):
    env = sandbox(tmp_path)
    # A fetch would throw, so only a local usage print can exit 0.
    stub = tmp_path / "no-fetch.js"
    stub.write_text("globalThis.fetch = () => { throw new Error('fetch called'); };\n")
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(ROOT / "tools/npm/crewship.js"), "--help"],
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert (result.returncode, result.stderr) == (0, "")
    assert result.stdout == install(env, "--help").stdout


# Release install, update and migration: the real build-release-artifact.sh and
# install.sh run against a curl shim that serves a local mirror of the GitHub URL layout.
CURL_SHIM = """#!/usr/bin/env bash
out=; fmt=
while (($#)); do
  case $1 in -o) out=$2; shift 2 ;; -w) fmt=$2; shift 2 ;; -*) shift ;; *) url=$1; shift ;; esac
done
code=200; redirect=
case $url in
  https://github.com/*/releases/latest) code=302; redirect=https://github.com/i098/Crewship/releases/tag/$(cat "$MIRROR/latest") ;;
  https://github.com/*/releases/download/*/*)
    if [ -f "$MIRROR/${url##*/}" ]; then cp "$MIRROR/${url##*/}" "$out"; else : >"$out"; code=404; fi ;;
  https://github.com/*/archive/refs/tags/*.tar.gz)
    if [ -f "$MIRROR/src-${url##*/}" ]; then cp "$MIRROR/src-${url##*/}" "$out"; else : >"$out"; code=404; fi ;;
  *) code=403; echo '{}' >"$out" ;;
esac
case $fmt in *redirect_url*) printf %s "$redirect" ;; *http_code*) printf %s "$code" ;; esac
"""
SHIP = """#!/usr/bin/env bash
echo "$1" >>"$HOME/calls"
echo "$*" >>"$HOME/args"
if [ "$1" = dock ]; then mkdir -p .local && echo "dock-v$(cat VERSION)" >.local/host.yml; fi
"""


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True, capture_output=True)


class Release:
    """A mirror holding releases v1.0.0 and v1.1.0 built by scripts/build-release-artifact.sh."""

    def __init__(self, tmp_path):
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.mirror = tmp_path / "mirror"
        self.repo = tmp_path / "repo"
        self.repo.mkdir()
        (self.repo / "ship.sh").write_text(SHIP)
        (self.repo / "ship.sh").chmod(0o755)
        (self.repo / "onboard.sh").write_text("#!/usr/bin/env bash\n")
        (self.repo / "onboard.sh").chmod(0o755)
        git(self.repo, "init", "-q")
        for tag in ("v1.0.0", "v1.1.0"):
            (self.repo / "VERSION").write_text(tag[1:])
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-qm", tag)
            git(self.repo, "tag", tag)
            subprocess.run([BASH, str(ROOT / "scripts/build-release-artifact.sh"), tag, str(self.mirror)], cwd=self.repo, check=True)
            # GitHub's source archive of the tag: a git archive whose header names the commit.
            subprocess.run(
                ["git", "archive", "--format=tar.gz", f"--prefix=Crewship-{tag[1:]}/", "-o", str(self.mirror / f"src-{tag}.tar.gz"), tag],
                cwd=self.repo,
                check=True,
            )
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        for name, body in {"curl": CURL_SHIM, "apt-get": "#!/bin/sh\n", "dpkg-query": "#!/bin/sh\nprintf installed\n"}.items():
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        self.env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(self.home),
            "MIRROR": str(self.mirror),
            # git ls-remote of the GitHub URL reads the local repo, whose tags stand in for the release tags.
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": f"url.{self.repo}.insteadOf",
            "GIT_CONFIG_VALUE_0": "https://github.com/i098/Crewship",
        }

    def install(self, latest, *args):
        (self.mirror / "latest").write_text(latest)
        return subprocess.run(
            [BASH, "-s", "--", *args],
            input=(ROOT / "install.sh").read_text(),
            capture_output=True,
            text=True,
            env=self.env,
            timeout=60,
        )

    @property
    def crewship(self):
        return self.home / "Crewship"

    @property
    def releases(self):
        return self.home / ".local/share/crewship/releases"


@pytest.fixture
def release(tmp_path):
    return Release(tmp_path)


def test_fresh_install_unpacks_a_release_without_git(release):
    result = release.install("v1.0.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.is_symlink()
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert not (release.crewship / ".git").exists()
    assert (release.crewship / ".local/host.yml").read_text() == "dock-v1.0.0\n"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize("latest, warns", [("1.1.0", True), ("1.0.0", False), ("0.9.0", False), (None, False), ("offline", False)])
def test_pnpm_release_policy_preserves_the_selected_release(release, tmp_path, latest, warns):
    import json

    launcher = tmp_path / "launcher"
    launcher.mkdir()
    shutil.copyfile(ROOT / "tools/npm/crewship.js", launcher / "crewship.js")
    (launcher / "package.json").write_text('{"version":"1.0.0"}')
    stub = tmp_path / "fetch.js"
    stub.write_text(
        "const fs = require('node:fs');\n"
        "globalThis.fetch = async (url) => {\n"
        "  if (url === 'https://registry.npmjs.org/crewship/latest') {\n"
        + ("    throw new Error('registry unavailable');\n" if latest == "offline" else "")
        + f"    return new Response(JSON.stringify({{version: {json.dumps(latest)}}}));\n"
        "  }\n"
        "  if (!url.endsWith('/v1.0.0/install.sh')) throw new Error(`unexpected URL: ${url}`);\n"
        f"  return new Response(fs.readFileSync({json.dumps(str(ROOT / 'install.sh'))}, 'utf8'));\n"
        "};\n"
    )
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(launcher / "crewship.js"), "--with", "none"],
        capture_output=True, text=True, timeout=60,
        env={**release.env, "npm_config_user_agent": "pnpm/12.14.0 npm/? node/v24.0.0 linux x64"},
    )
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert ("minimumReleaseAge" in result.stdout) is warns
    assert result.stdout.index("Installing Crewship v1.0.0") < result.stdout.index("Crewship v1.0.0 in")



@pytest.mark.parametrize(
    "ref, missing",
    [("v1.0.0", None), (None, None), (None, "curl"), (None, "ca-certificates")],
    ids=["pinned", "resolved", "missing-curl", "missing-ca-certificates"],
)
def test_release_is_announced_before_main_package_setup(release, tmp_path, ref, missing):
    if ref:
        release.env["CREWSHIP_REF"] = ref
    if missing is None:
        (release.home / "https-installed").touch()
    bin_dir = tmp_path / "bin"
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)
    (bin_dir / "apt-get").write_text(
        '#!/bin/sh\n'
        'if [ -f "$HOME/https-installed" ]; then echo MAIN_PACKAGE_SETUP; else echo HTTPS_BOOTSTRAP; fi\n'
        'case "$*" in *install*) touch "$HOME/https-installed" ;; esac\n'
    )
    (bin_dir / "dpkg-query").write_text(
        '#!/bin/sh\n[ "$3" != git ] && [ -f "$HOME/https-installed" ] || exit 1\nprintf installed\n'
    )
    (bin_dir / "curl").write_text(
        '#!/usr/bin/env bash\n[ -f "$HOME/https-installed" ] || exit 127\n' + CURL_SHIM.split("\n", 1)[1]
    )
    if missing == "curl":
        env = tmp_path / "bash-env"
        env.write_text(
            'command() {\n'
            '  if [[ $* == "-v curl" && ! -f "$HOME/https-installed" ]]; then return 1; fi\n'
            '  builtin command "$@"\n'
            '}\n'
        )
        release.env["BASH_ENV"] = str(env)
    result = release.install("v1.1.0" if ref else "v1.0.0")
    assert result.returncode == 0, result.stderr
    assert (release.home / "https-installed").exists()
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert result.stdout.index("Installing Crewship v1.0.0") < result.stdout.index("Updating OS packages...")
    assert "MAIN_PACKAGE_SETUP" not in result.stdout
    assert "MAIN_PACKAGE_SETUP" in install_log(result).read_text()
    assert ("HTTPS_BOOTSTRAP" in result.stderr) is (missing is not None)


@pytest.mark.parametrize("status", [0, 23])
def test_install_logs_keep_details_private_on_success_and_failure(release, status):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / "onboard.sh").write_text(
        f"#!/bin/sh\necho package-details\necho diagnostic-details >&2\nexit {status}\n"
    )
    result = release.install("v1.0.0")
    assert result.returncode == status
    assert "package-details" not in result.stdout + result.stderr
    assert "diagnostic-details" not in result.stdout + result.stderr
    log = install_log(result)
    assert log.stat().st_mode & 0o777 == 0o600
    assert log.parent == release.home / ".local/state/crewship-install"
    assert "package-details\n" in log.read_text()
    assert "diagnostic-details\n" in log.read_text()


def terminal_install(release, responses):
    pid, terminal = pty.fork()
    if pid == 0:
        termios.tcsetwinsize(0, (40, 120))
        os.execve(BASH, [BASH, str(ROOT / "install.sh")], release.env)
    output = b""
    deadline = time.monotonic() + 20
    status = None
    responses = dict(responses)
    try:
        while True:
            ready, _, _ = select.select([terminal], [], [], max(0, deadline - time.monotonic()))
            assert ready, f"The installer did not exit:\n{output.decode(errors='replace')}"
            try:
                chunk = os.read(terminal, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not chunk:
                break
            output += chunk
            for prompt, answer in list(responses.items()):
                if prompt in output:
                    os.write(terminal, answer)
                    del responses[prompt]
        _, status = os.waitpid(pid, 0)
    finally:
        os.close(terminal)
        if status is None:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
    assert not responses, output.decode(errors="replace")
    return subprocess.CompletedProcess(
        [], os.waitstatus_to_exitcode(status), output.decode(errors="replace"), ""
    )


@pytest.mark.parametrize("status", [0, 23])
def test_terminal_install_drains_output_before_exit(release, tmp_path, status):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / "ship.sh").write_text(
        SHIP + f'\nif [ "$1" = launch ]; then\n'
        '  echo terminal-output\n'
        '  echo terminal-error >&2\n'
        f'  exit {status}\nfi\n'
    )
    tee = tmp_path / "bin/tee"
    tee.write_text(
        f"#!{sys.executable}\n"
        "import subprocess, sys, time\n"
        "data = sys.stdin.buffer.read()\n"
        "time.sleep(0.1)\n"
        f"sys.exit(subprocess.run([{shutil.which('tee')!r}, *sys.argv[1:]], input=data).returncode)\n"
    )
    tee.chmod(0o755)
    result = terminal_install(release, {})
    assert result.returncode == status, result.stdout
    log = install_log(result)
    footer = f"Full install log: {log}"
    assert result.stdout.count(footer) == 1
    assert log.read_text().count(footer) == 1
    assert result.stdout.index("Installing repository tools...") < result.stdout.index(footer)
    assert result.stdout.index("terminal-output") < result.stdout.index(footer)
    assert result.stdout.count("terminal-error") == 1
    assert log.read_text().count("terminal-output") == 1
    assert log.read_text().count("terminal-error") == 1
    assert ("Crewship installation failed" in result.stdout) == bool(status)


def test_interrupt_during_package_lock_wait_does_not_hang(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    (release.home / "calls").unlink()
    bin_dir = tmp_path / "bin"
    for name, body in {
        "dpkg-query": "#!/bin/sh\nexit 1\n",
        "sudo": '#!/bin/sh\nexec "$@"\n',
        "apt-get": "#!/bin/sh\necho 'E: Could not get lock /var/lib/apt/lists/lock'\nexit 100\n",
        "sleep": "#!/bin/sh\necho ready-to-interrupt >/dev/tty\nexec /bin/sleep 60\n",
    }.items():
        (bin_dir / name).write_text(body)
        (bin_dir / name).chmod(0o755)
    result = terminal_install(release, {b"ready-to-interrupt": b"\x03"})
    assert result.returncode == -signal.SIGINT, result.stdout
    assert not (release.home / "calls").exists()


@pytest.mark.parametrize("question_status", [0, 17])
def test_install_questions_keep_terminal_and_capture_output(release, question_status):
    assert release.install("v1.0.0").returncode == 0
    config = yaml.safe_load((ROOT / "blueprint/config/default.yml").read_text())
    config["crewship"].update(
        home=str(release.home), user=ship.pwd.getpwuid(os.getuid()).pw_name,
        workspace=str(release.home / "Dev"),
    )
    config["crewship"]["profiles"]["firstmate"] = True
    config["crewship"]["firstmate"].pop("checklist", None)
    (release.crewship / ".local/host.yml").write_text(yaml.safe_dump(config))
    (release.home / "Dev/firstmate").mkdir(parents=True)
    omp = release.home / ".local/bin/omp"
    omp.parent.mkdir(parents=True)
    omp.write_text(
        f"#!{sys.executable}\n"
        "import os, pathlib, sys\n"
        "if sys.argv[1:] == ['models', '--json']:\n"
        "    print('{\"models\": [{\"id\": \"test\"}]}')\n"
        "    sys.exit(0)\n"
        "assert all(os.isatty(fd) for fd in (0, 1, 2)), 'missing terminal'\n"
        "assert all(os.get_terminal_size(1)), 'missing terminal size'\n"
        "home = pathlib.Path(os.environ['HOME'])\n"
        "assert pathlib.Path.cwd() == home / 'Dev/firstmate'\n"
        "answer = input('Choose a host name: ')\n"
        "(home / 'answer').write_text(answer)\n"
        "print('Configured host: ' + answer, flush=True)\n"
        "print('Question diagnostic', file=sys.stderr, flush=True)\n"
        f"sys.exit({question_status})\n"
    )
    omp.chmod(0o755)
    (release.crewship / "ship.sh").write_text(
        f"#!{sys.executable}\n"
        "import importlib.util, pathlib, sys\n"
        "if sys.argv[1] != 'launch':\n"
        "    sys.exit(0)\n"
        f"spec = importlib.util.spec_from_file_location('ship', {str(ROOT / 'scripts/ship.py')!r})\n"
        "ship = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(ship)\n"
        "ship.provision = lambda document, check: 0\n"
        "ship.load_config = lambda path: ship.yaml.safe_load(path.read_text())\n"
        "config = pathlib.Path(__file__).parent / '.local/host.yml'\n"
        "sys.argv = [sys.argv[0], 'launch', '--config', str(config)]\n"
        "sys.exit(ship.main())\n"
    )
    result = terminal_install(release, {b"Choose a host name: ": b"test-host\n"})
    assert result.returncode == 0, result.stdout
    assert (release.home / "answer").read_text() == "test-host"
    log = install_log(result)
    assert log.stat().st_mode & 0o777 == 0o600
    for message in ("Configured host: test-host", "Question diagnostic"):
        assert message in result.stdout
        assert log.read_text().count(message) == 1
    marker = release.home / ".local/share/crewship/new-host-questions-done"
    assert marker.exists() == (question_status == 0)
    assert (f"omp exited {question_status}" in result.stdout) == bool(question_status)


def test_install_preserves_legacy_state_and_cache_during_migration(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    for directory in (".local/state", ".cache"):
        old = release.home / directory / "code-factory"
        old.mkdir(parents=True)
        (old / "data").write_text(directory)
    migration = yaml.safe_load((ROOT / "blueprint/ansible/tasks/rename.yml").read_text())[0]
    migration["vars"]["crewship_renamed_paths"] = [
        pair for pair in migration["vars"]["crewship_renamed_paths"]
        if pair[0].endswith(("/.local/state/code-factory", "/.cache/code-factory"))
    ]
    tasks = migration["block"]
    migration["block"] = tasks[:3] + [
        next(task for task in tasks if task["name"] == "Move the pre-rename home paths to their new names")
    ]
    playbook = tmp_path / "migration.yml"
    playbook.write_text(yaml.safe_dump([{
        "hosts": "localhost", "connection": "local", "gather_facts": False,
        "vars": {
            "ansible_become": False, "ansible_python_interpreter": sys.executable,
            "crewship_become_target": False,
            "crewship_cfg": {"home": str(release.home), "user": getpass.getuser()},
            "crewship_share_dir": str(release.home / ".local/share/crewship"),
        },
        "tasks": [migration],
    }]))
    (release.crewship / "ship.sh").write_text(
        SHIP + '\ncase $1 in\n'
        '  launch) set -- ;;\n'
        '  *) exit 0 ;;\n'
        'esac\n'
        f'exec "{Path(sys.executable).parent / "ansible-playbook"}"'
        f' -i localhost, "{playbook}" "$@"\n'
    )
    release.env["ANSIBLE_PIPELINING"] = "1"
    result = release.install("v1.0.0")
    assert result.returncode == 0, install_log(result).read_text()
    for directory in (".local/state", ".cache"):
        assert not (release.home / directory / "code-factory").exists()
        assert (release.home / directory / "crewship/data").read_text() == directory
    assert install_log(result).stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("password_required", [False, True])
def test_install_routes_apply_output(release, tmp_path, password_required):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / "ship.sh").write_text(
        f"#!{sys.executable}\n"
        "import importlib.util, os, sys\n"
        "if sys.argv[1] != 'launch':\n"
        "    sys.exit(0)\n"
        f"spec = importlib.util.spec_from_file_location('ship', {str(ROOT / 'scripts/ship.py')!r})\n"
        "ship = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(ship)\n"
        "ship.os.geteuid = lambda: 1000\n"
        "ship.sys.stdin.isatty = lambda: True\n"
        "sys.exit(ship.provision({'crewship': {'home': os.environ['HOME']}}, False))\n"
    )
    bin_dir = tmp_path / "bin"
    (bin_dir / "sudo").write_text(f"#!/bin/sh\nexit {int(password_required)}\n")
    (bin_dir / "sudo").chmod(0o755)
    ansible = bin_dir / "ansible-playbook"
    ansible.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "assert ('--ask-become-pass' in sys.argv) == (os.environ['PASSWORD_REQUIRED'] == '1')\n"
        "print('apply-details')\n"
        "print('apply-diagnostic', file=sys.stderr)\n"
    )
    ansible.chmod(0o755)
    release.env["PASSWORD_REQUIRED"] = str(int(password_required))
    result = release.install("v1.0.0")
    log = install_log(result).read_text()
    assert result.returncode == 0, log
    for stream in ("details", "diagnostic"):
        message = f"apply-{stream}"
        assert log.count(message) == 1
        assert (message in result.stdout + result.stderr) == password_required



@pytest.mark.parametrize("failure", ["lock", "timeout", "frontend-timeout", "package"])
def test_package_failures_wait_only_for_locks(release, tmp_path, failure):
    release.env["CREWSHIP_REF"] = "v1.0.0"
    bin_dir = tmp_path / "bin"
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)
    (bin_dir / "dpkg-query").write_text("#!/bin/sh\nexit 1\n")
    (bin_dir / "apt-get").write_text(
        "#!/usr/bin/python3\n"
        "import os, pathlib, sys\n"
        "failure = os.environ['FAILURE']\n"
        "if failure == 'frontend-timeout' and 'install' not in sys.argv:\n"
        "    sys.exit(0)\n"
        "calls = pathlib.Path(os.environ['HOME']) / 'apt-calls'\n"
        "previous = calls.read_text() if calls.exists() else ''\n"
        "with calls.open('a') as log:\n"
        "    log.write(' '.join(sys.argv[1:]) + '\\n')\n"
        "if not previous or failure in ('timeout', 'frontend-timeout'):\n"
        "    message = 'Could not get lock /var/lib/apt/lists/lock'\n"
        "    if os.environ['FAILURE'] == 'package':\n"
        "        message = 'Unable to locate package missing'\n"
        "    if failure == 'frontend-timeout':\n"
        "        message = 'Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), is another process using it?'\n"
        "    print('E: ' + message, file=sys.stderr)\n"
        "    sys.exit(100)\n"
    )
    release.env["FAILURE"] = failure
    if failure.endswith("timeout"):
        bash_env = tmp_path / "bash-env"
        bash_env.write_text("sleep() { SECONDS=1000000; }\n")
        release.env["BASH_ENV"] = str(bash_env)

    result = release.install("v1.0.0")

    calls = (release.home / "apt-calls").read_text().splitlines()
    if failure == "lock":
        assert result.returncode == 0, result.stderr
        assert len(calls) == 3
        assert (release.home / "calls").read_text().split()[-1] == "launch"
    else:
        assert result.returncode == 100
        assert not release.crewship.exists()
        if failure.endswith("timeout"):
            assert "package locks did not clear within 600 seconds" in install_log(result).read_text()
        else:
            assert "Unable to locate package missing" in install_log(result).read_text()
            assert len(calls) == 1


def test_update_keeps_host_files_and_removes_the_replaced_release(release):
    assert release.install("v1.0.0").returncode == 0
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / "VERSION").read_text() == "1.1.0"
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"
    assert [p.name for p in release.releases.iterdir()] == ["v1.1.0"]


def test_bad_checksum_leaves_the_install_untouched(release):
    assert release.install("v1.0.0").returncode == 0
    (release.mirror / "crewship-v1.1.0.tar.gz.sha256").write_text(f"{'0' * 64}  crewship-v1.1.0.tar.gz\n")
    result = release.install("v1.1.0")
    assert result.returncode != 0
    assert "does not match its .sha256" in result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.0.0").resolve()
    assert [p.name for p in release.releases.iterdir()] == ["v1.0.0"]


def test_release_without_artifact_installs_the_verified_source_archive(release):
    for name in ("crewship-v1.1.0.tar.gz", "crewship-v1.1.0.tar.gz.sha256"):
        (release.mirror / name).unlink()
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert "has no install artifact; using GitHub's source archive" in result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / "VERSION").read_text() == "1.1.0"
    assert not (release.crewship / ".git").exists()


def test_source_archive_of_another_commit_is_refused(release):
    (release.mirror / "crewship-v1.1.0.tar.gz").unlink()
    # The v1.0.0 archive under the v1.1.0 name: a different commit than the tag's.
    (release.mirror / "src-v1.1.0.tar.gz").write_bytes((release.mirror / "src-v1.0.0.tar.gz").read_bytes())
    result = release.install("v1.1.0")
    assert result.returncode != 0
    assert "refusing to install" in result.stderr
    assert not release.crewship.exists()


def test_unknown_release_is_an_error_and_never_clones(release):
    result = release.install("v9.9.9")
    assert result.returncode != 0
    assert "no release v9.9.9" in result.stderr
    assert not release.crewship.exists()


def test_git_clone_migrates_to_a_release_and_a_backup(release):
    subprocess.run(["git", "clone", "-q", str(release.repo), str(release.crewship)], check=True)
    (release.crewship / ".local").mkdir()
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert release.crewship.is_symlink()
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"
    (backup,) = release.home.glob("Crewship.git-backup-*")
    assert (backup / ".git").is_dir()
    assert (backup / ".local/host.yml").read_text() == "mine\n"


@pytest.mark.parametrize("old_layout", ["", "blueprint/"], ids=["before-blueprint", "blueprint"])
@pytest.mark.parametrize("from_git", [False, True], ids=["release", "git-clone"])
def test_update_carries_private_skills_and_rules_into_the_blueprint(release, old_layout, from_git):
    if from_git:
        subprocess.run(["git", "clone", "-q", str(release.repo), str(release.crewship)], check=True)
    else:
        assert release.install("v1.0.0").returncode == 0
    for kind, name in (("skills", "mine/SKILL.md"), ("rules", "mine.md")):
        path = release.crewship / f"{old_layout}{kind}/private/{name}"
        path.parent.mkdir(parents=True)
        path.write_text(f"{kind}\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert (release.crewship / "blueprint/skills/private/mine/SKILL.md").read_text() == "skills\n"
    assert (release.crewship / "blueprint/rules/private/mine.md").read_text() == "rules\n"
    assert not (release.crewship / "skills").exists() and not (release.crewship / "rules").exists()


def test_v040_host_is_migrated_before_the_reapply(release):
    assert release.install("v1.0.0").returncode == 0
    # What v0.4.0 left: tools under share/code-factory linked from ~/.local/bin, and removed fleet keys.
    old = release.home / ".local/share/code-factory/tools/uv/1/linux"
    old.mkdir(parents=True)
    (old / "uv").write_text("x")
    bin_dir = release.home / ".local/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "uv").symlink_to(old / "uv")
    (bin_dir / "mine").write_text("not ours")
    host = release.crewship / ".local/host.yml"
    host.write_text("factory:\n  home: /h\n  fleet:\n    supabase_project_id: a\n    fixture_archive: b\n    worktree_pools: [c]\n    keep: 1\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert not (bin_dir / "uv").exists() and not (bin_dir / "uv").is_symlink()
    assert (bin_dir / "mine").read_text() == "not ours"
    assert (old / "uv").read_text() == "x"
    assert "factory:\n  home: /h\n  fleet:\n    keep: 1\n" == host.read_text()
    assert "supabase_project_id" in (host.parent / "host.yml.v0.4.0").read_text()


def test_failed_link_migration_stops_before_reapplying(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    old = release.home / ".local/share/code-factory/tools/uv/1/linux"
    old.mkdir(parents=True)
    (old / "uv").write_text("x")
    links = release.home / ".local/bin"
    links.mkdir(parents=True)
    link = links / "uv"
    link.symlink_to(old / "uv")
    env = tmp_path / "bash-env"
    env.write_text(
        'rm() {\n'
        '  if [[ $# == 2 && $1 == -f && $2 == "$FAILED_LINK" ]]; then return 73; fi\n'
        '  command rm "$@"\n'
        '}\n'
    )
    release.env.update(BASH_ENV=str(env), FAILED_LINK=str(link))
    result = release.install("v1.1.0")
    assert result.returncode == 73
    assert link.is_symlink()
    assert (release.home / "calls").read_text().split().count("launch") == 1


def test_update_installs_the_newest_release_and_passes_options_to_dock(release):
    assert release.install("v1.0.0", "update", "--container").returncode == 0
    assert (release.home / "args").read_text().splitlines()[0] == "dock --container"
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0", "update", "--container")
    assert result.returncode == 0, result.stderr
    assert release.crewship.resolve() == (release.releases / "v1.1.0").resolve()
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"


def test_with_goes_to_dock_for_a_new_host_and_is_refused_for_an_existing_one(release):
    assert release.install("v1.0.0", "--with=docker,chat").returncode == 0
    assert (release.home / "args").read_text().splitlines()[0] == "dock --with=docker,chat"
    (release.crewship / ".local").mkdir(exist_ok=True)
    (release.crewship / ".local/host.yml").write_text("mine\n")
    result = release.install("v1.1.0", "update", "--with", "docker")
    assert result.returncode == 1
    assert "--with applies to a new host config" in result.stderr
    assert (release.crewship / ".local/host.yml").read_text() == "mine\n"


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
@pytest.mark.parametrize(
    "location, status, output",
    [
        ("https://github.com/i098/Crewship/releases/tag/v1.1.0", 0, "ref=v1.1.0 args=--container"),
        ("https://github.com/i098/Crewship/releases", 1, "no release found"),
        ("", 1, "no release found"),
    ],
)
def test_launcher_update_runs_the_install_of_the_latest_tag(tmp_path, location, status, output):
    stub = tmp_path / "fetch.js"
    stub.write_text(
        "const location = process.env.LATEST_LOCATION;\n"
        "globalThis.fetch = async (url, options) => {\n"
        "  if (url.endsWith('/releases/latest')) {\n"
        "    if (options?.redirect !== 'manual') throw new Error('redirect not manual');\n"
        "    return new Response(null, { status: 302, headers: location ? { location } : {} });\n"
        "  }\n"
        "  const ref = url.split('/')[5];\n"
        "  return new Response(`echo \"ref=$CREWSHIP_REF args=$*\"; echo \"url-ref=${ref}\"`);\n"
        "};\n"
    )
    result = subprocess.run(
        [shutil.which("node"), "--require", str(stub), str(ROOT / "tools/npm/crewship.js"), "update", "--container"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "LATEST_LOCATION": location},
        timeout=10,
    )
    assert result.returncode == status
    assert output in result.stdout + result.stderr
    if status == 0:
        assert "url-ref=v1.1.0" in result.stdout


def test_v040_links_are_relinked_when_home_is_a_symlink(release, tmp_path):
    assert release.install("v1.0.0").returncode == 0
    old = release.home / ".local/share/code-factory/tools/uv/1/linux"
    old.mkdir(parents=True)
    (old / "uv").write_text("x")
    (release.home / ".local/bin").mkdir(parents=True, exist_ok=True)
    (release.home / ".local/bin/uv").symlink_to(old / "uv")
    alias = tmp_path / "home-alias"
    alias.symlink_to(release.home)
    release.env["HOME"] = str(alias)
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert not (alias / ".local/bin/uv").is_symlink()


def test_migration_is_a_noop_on_a_current_host(release):
    assert release.install("v1.0.0").returncode == 0
    host = release.crewship / ".local/host.yml"
    host.write_text("crewship:\n  fleet:\n    keep: 1\n")
    result = release.install("v1.1.0")
    assert result.returncode == 0, result.stderr
    assert host.read_text() == "crewship:\n  fleet:\n    keep: 1\n"
    assert not (host.parent / "host.yml.v0.4.0").exists()
