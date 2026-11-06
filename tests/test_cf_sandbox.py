"""cf-sandbox keeps a test off the live session: fake sockets only, never a real daemon."""

import os
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import pytest

SANDBOX = Path(__file__).parents[1] / "blueprint/maintenance/cf-sandbox"

FAKE_CLIENT = """#!/usr/bin/env python3
import os, socket
paths = [
    os.environ["XDG_RUNTIME_DIR"] + "/tuios/tuios.sock",
    os.path.expanduser("~/.config/herdr/herdr.sock"),
    os.environ.get("HERDR_SOCKET_PATH", ""),
]
for path in filter(None, paths):
    s = socket.socket(socket.AF_UNIX)
    try:
        s.connect(path)
        s.sendall(b"kill-session machine")
        print("reached", path)
    except OSError as e:
        print("unreachable", e.errno)
"""


def bwrap_works():
    if not shutil.which("bwrap"):
        return False
    return subprocess.run(["bwrap", "--ro-bind", "/", "/", "true"], capture_output=True).returncode == 0


pytestmark = pytest.mark.skipif(not bwrap_works(), reason="bubblewrap with user namespaces is required")


class FakeDaemon:
    """A Unix socket that counts connections, standing in for a live tuios or herdr daemon."""

    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(path))
        self.sock.listen(8)
        self.connections = 0
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                self.sock.accept()[0].close()
            except OSError:
                return
            self.connections += 1

    def close(self):
        self.sock.close()


@pytest.fixture
def live():
    root = Path(tempfile.mkdtemp(prefix="cfs"))
    home, runtime, other = root / "home", root / "run", root / "other"
    daemons = [
        FakeDaemon(runtime / "tuios/tuios.sock"),
        FakeDaemon(home / ".config/herdr/herdr.sock"),
        FakeDaemon(other / "herdr.sock"),
    ]
    checkout = root / "work"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "tuios").write_text(FAKE_CLIENT)
    (checkout / "tuios").chmod(0o755)
    env = {
        **os.environ,
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(runtime),
        "HERDR_SOCKET_PATH": str(other / "herdr.sock"),
        "CF_SANDBOX_SCRATCH": str(root),
    }
    yield checkout, env, daemons
    for daemon in daemons:
        daemon.close()
    shutil.rmtree(root, ignore_errors=True)


def sandbox(checkout, env, *command):
    return subprocess.run(
        [str(SANDBOX), "--cwd", str(checkout), "--", *command],
        env=env, capture_output=True, text=True, timeout=60,
    )


def test_client_reaches_the_fake_daemon_without_the_sandbox(live):
    """Control: the same client and environment do reach the sockets, so the test can fail."""
    checkout, env, daemons = live
    out = subprocess.run([str(checkout / "tuios"), "kill-session", "machine"], env=env,
                         capture_output=True, text=True, timeout=30).stdout
    assert out.count("reached") == 3
    deadline = time.time() + 5
    while time.time() < deadline and [d.connections for d in daemons] != [1, 1, 1]:
        time.sleep(0.05)
    assert [d.connections for d in daemons] == [1, 1, 1]


def test_kill_session_cannot_reach_the_live_sockets(live):
    checkout, env, daemons = live
    result = sandbox(checkout, env, str(checkout / "tuios"), "kill-session", "machine")
    assert result.returncode == 0, result.stderr
    assert "reached" not in result.stdout
    assert result.stdout.count("unreachable") == 2  # the herdr variable is dropped, not followed
    assert [d.connections for d in daemons] == [0, 0, 0]


def test_sandbox_cannot_signal_a_host_process(live):
    checkout, env, _ = live
    victim = subprocess.Popen(["sleep", "30"])
    try:
        result = sandbox(checkout, env, "sh", "-c", f"kill -9 {victim.pid}")
        assert result.returncode != 0
        assert victim.poll() is None
    finally:
        victim.send_signal(signal.SIGKILL)
        victim.wait()


def test_sandbox_state_is_private_but_the_checkout_is_writable(live):
    checkout, env, _ = live
    result = sandbox(
        checkout, env, "sh", "-c",
        'echo kept > out.txt; echo gone > /tmp/t.txt; echo gone > "$HOME/h.txt"; '
        'echo gone > "$XDG_RUNTIME_DIR/r.txt"; ! touch /usr/denied 2>/dev/null',
    )
    assert result.returncode == 0, result.stderr
    assert (checkout / "out.txt").read_text() == "kept\n"
    home, runtime = Path(env["HOME"]), Path(env["XDG_RUNTIME_DIR"])
    assert not (home / "h.txt").exists() and not (runtime / "r.txt").exists()
    assert not list(Path(env["CF_SANDBOX_SCRATCH"]).glob("cf-sandbox.*"))  # scratch is removed


def test_no_net_hides_abstract_sockets(live):
    checkout, env, _ = live
    name = f"\0cf-sandbox-test-{os.getpid()}"
    server = socket.socket(socket.AF_UNIX)
    server.bind(name)
    server.listen(1)
    code = ("import socket; s = socket.socket(socket.AF_UNIX); "
            f"s.connect({name!r}); print('reached')")
    try:
        shared = sandbox(checkout, env, "python3", "-c", code)
        isolated = subprocess.run(
            [str(SANDBOX), "--no-net", "--cwd", str(checkout), "--", "python3", "-c", code],
            env=env, capture_output=True, text=True, timeout=60,
        )
    finally:
        server.close()
    assert "reached" in shared.stdout  # the documented limit without --no-net
    assert "reached" not in isolated.stdout and isolated.returncode != 0


def test_no_command_is_an_error(live):
    checkout, env, _ = live
    result = subprocess.run([str(SANDBOX), "--cwd", str(checkout), "--"], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 2 and "no command" in result.stderr


def test_a_checkout_that_contains_the_real_home_is_refused(live):
    checkout, env, daemons = live
    env = {**env, "HOME": str(checkout / "home")}
    (checkout / "home").mkdir(exist_ok=True)
    result = subprocess.run([str(SANDBOX), "--cwd", str(checkout), "--", "true"], env=env,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode != 0 and "contains" in result.stderr
