"""blueprint/fleet/doctor/devtools-bridge-reaper.sh against a fixture bridge process tree.

The fixture is a detached `bash <marker>` run as argv[0] `node`, so its
command line has the shape of a real bridge, `node <path>/<marker>`. It is
reparented to init like a real bridge, has a `sleep` child, and carries
CHROME_DEVTOOLS_AXI_BROWSER_URL like an attached fleet bridge. The per-test
marker stands in for chrome-devtools-axi-bridge.js, so real bridges on the
host are never matched.
Idle time is simulated by backdating the busy timestamp in the state file.
"""

import os
import shutil
import signal
import subprocess
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SESSION = "fixture"
# USR1 burns ~0.3 s of CPU in the tree, then the bridge goes back to waiting.
# HUNG=1 makes the whole tree ignore TERM.
BRIDGE = """
trap 'for ((i = 0; i < 500000; i++)); do :; done; touch "$STUB/burned"' USR1
[ -z "${HUNG:-}" ] || trap '' TERM
while :; do sleep 600 & wait $!; done
"""


def alive(pid: int) -> bool:
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(") ")[1][0] != "Z"
    except (FileNotFoundError, IndexError):
        return False


def gone(pids: list[int]) -> bool:
    deadline = time.time() + 5
    while any(alive(p) for p in pids) and time.time() < deadline:
        time.sleep(0.05)
    return not any(alive(p) for p in pids)


class Reaper:
    def __init__(self, tmp: Path):
        self.doctor = tmp / "doctor"
        self.stub = tmp / "stub"
        self.axi = tmp / "axi"
        self.session = self.axi / "sessions" / SESSION
        for d in (self.doctor, self.stub, self.session):
            d.mkdir(parents=True)
        shutil.copy(ROOT / "blueprint/fleet/doctor/devtools-bridge-reaper.sh", self.doctor)
        self.state = self.doctor / "devtools-bridge-reaper.state"
        self.mark = f"fixture-bridge-{uuid.uuid4().hex}.js"
        self.script = self.stub / self.mark
        self.script.write_text(BRIDGE)
        self.spawned: list[int] = []
        self.env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(tmp),
            "STUB": str(self.stub),
            "BRIDGE_REAPER_MARK": self.mark,
            "BRIDGE_REAPER_AXI_STATE_DIR": str(self.axi),
        }
        self.pid = self.start()
        self.tree = [self.pid, *self.children(self.pid)]

    def start(self, argv0: str = "node", attached: bool = True, hung: bool = False) -> int:
        env = {**self.env, "CHROME_DEVTOOLS_AXI_SESSION": SESSION}
        if attached:
            env["CHROME_DEVTOOLS_AXI_BROWSER_URL"] = "http://127.0.0.1:9222"
        if hung:
            env["HUNG"] = "1"
        # The wrapper backgrounds `bash <marker>` under argv[0] and exits, so
        # init adopts it.
        out = subprocess.run(
            [
                "bash",
                "-c",
                'exec -a "$1" bash "$0" </dev/null >/dev/null 2>&1 & echo $!',
                str(self.script),
                argv0,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        pid = int(out)
        deadline = time.time() + 5
        while not self.children(pid) and time.time() < deadline:
            time.sleep(0.05)
        self.spawned += [pid, *self.children(pid)]
        return pid

    @staticmethod
    def children(pid: int) -> list[int]:
        path = Path(f"/proc/{pid}/task/{pid}/children")
        return [int(c) for c in path.read_text().split()] if path.exists() else []

    def bridge_pid_file(self, age_s: int = 7200):
        f = self.session / "bridge.pid"
        f.write_text(f'{{"pid": {self.pid}, "port": 9999}}\n')
        t = time.time() - age_s
        os.utime(f, (t, t))

    def backdate(self, minutes: int):
        busy = int(time.time()) - minutes * 60
        rows = (line.split()[:2] for line in self.state.read_text().splitlines())
        self.state.write_text("".join(f"{key} {ticks} {busy}\n" for key, ticks in rows))

    def run(self, *args: str) -> str:
        return subprocess.run(
            [str(self.doctor / "devtools-bridge-reaper.sh"), *args],
            env=self.env,
            capture_output=True,
            text=True,
            check=True,
            timeout=90,
        ).stdout

    def cleanup(self):
        for p in self.spawned:
            if alive(p):
                os.kill(p, signal.SIGKILL)


@pytest.fixture
def reaper(tmp_path):
    r = Reaper(tmp_path)
    r.bridge_pid_file()
    yield r
    r.cleanup()


def test_first_sighting_is_never_reaped(reaper):
    reaper.run()
    assert all(alive(p) for p in reaper.tree)
    assert reaper.state.read_text().startswith(f"{reaper.pid}:")


def test_idle_tree_is_killed_after_idle_min(reaper):
    reaper.run()
    reaper.backdate(59)
    reaper.run()
    assert all(alive(p) for p in reaper.tree)
    reaper.backdate(61)
    reaper.run()
    assert gone(reaper.tree)
    assert reaper.state.read_text() == ""
    assert (
        f"REAPED bridge {reaper.pid} session={SESSION}"
        in (reaper.doctor / "devtools-bridge-reaper.log").read_text()
    )


def test_cpu_in_the_tree_keeps_it(reaper):
    reaper.run()
    reaper.backdate(61)
    os.kill(reaper.pid, signal.SIGUSR1)
    deadline = time.time() + 30
    while not (reaper.stub / "burned").exists() and time.time() < deadline:
        time.sleep(0.05)
    reaper.run()
    assert all(alive(p) for p in reaper.tree)


def test_session_state_change_keeps_it(reaper):
    reaper.run()
    reaper.backdate(61)
    os.utime(reaper.session / "bridge.pid")
    reaper.run()
    assert all(alive(p) for p in reaper.tree)


def test_dry_run_signals_nothing_and_writes_no_state(reaper):
    reaper.run()
    reaper.backdate(61)
    before = reaper.state.read_text()
    out = reaper.run("--dry-run")
    assert f"would reap bridge {reaper.pid} session={SESSION} idle=61min" in out
    assert all(alive(p) for p in reaper.tree)
    assert reaper.state.read_text() == before
    assert not (reaper.doctor / "devtools-bridge-reaper.log").exists()


def test_bridge_that_ignores_term_is_killed_with_its_tree(reaper):
    hung = reaper.start(hung=True)
    hung_tree = [hung, *reaper.children(hung)]
    reaper.run()
    reaper.backdate(61)
    reaper.run()
    assert gone(hung_tree)
    assert gone(reaper.tree)
    assert f"REAPED bridge {hung} " in (reaper.doctor / "devtools-bridge-reaper.log").read_text()


def test_unattached_bridge_is_never_touched(reaper):
    unattached = reaper.start(attached=False)
    unattached_tree = [unattached, *reaper.children(unattached)]
    reaper.run()
    assert reaper.state.read_text().startswith(f"{reaper.pid}:")
    reaper.backdate(61)
    reaper.run()
    assert gone(reaper.tree)
    assert all(alive(p) for p in unattached_tree)


def test_process_that_only_names_the_bridge_file_is_never_touched(reaper):
    decoy = reaper.start("bash")
    decoy_tree = [decoy, *reaper.children(decoy)]
    reaper.run()
    assert reaper.state.read_text().startswith(f"{reaper.pid}:")
    reaper.backdate(61)
    reaper.run()
    assert gone(reaper.tree)
    assert all(alive(p) for p in decoy_tree)
