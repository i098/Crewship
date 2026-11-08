"""imessage-deploy (docs/imessage.md#rolling-deploys): the bridge is rolled out beside the running one, gated, handed
over, and rolled back on failure. The bridge runs against the fake spectrum-ts of test_imessage.py and a stub
systemctl that runs each slot as a plain process, so no real unit, line or text is involved."""

import json
import os
import shutil
import subprocess
import threading
import time

import pytest
from test_imessage import FAKE_UPSTREAM, ROOT, SEND, free_port, publish_json, wait_for

pytestmark = pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl") and shutil.which("flock")),
                                reason="needs bun, curl and flock")

SYSTEMCTL = r"""#!/bin/bash
# Stub of `systemctl --user`: a slot is `bun bridge.ts` in $DIR/<slot>; the front unit's legacy process runs in $DIR.
shift
[ "${2:-}" = --quiet ] && set -- "$1" "${@:3}"
cmd=$1; name=${2:-}
slot=${name#fm-imessage@}; slot=${slot%.service}
[ "$name" = fm-imessage.service ] && slot=front
pidf=$RUN/$slot.pid
alive() { [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; }
case $cmd in
  start)
    [ "$slot" = front ] && ! [ -f "$RUN/front.legacy" ] && exit 0
    alive && exit 0
    if [ "$slot" = front ]; then cd "$DIR"; else cd "$DIR/$slot"; export FM_IMESSAGE_SLOT=$slot; fi
    setsid bun bridge.ts >> "$RUN/$slot.log" 2>&1 < /dev/null &
    echo $! > "$pidf" ;;
  stop)
    alive || exit 0
    pid=$(cat "$pidf"); kill -TERM "$pid"
    for _ in $(seq 150); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
    kill -KILL "$pid" 2>/dev/null; rm -f "$pidf"; [ "$slot" = front ] && rm -f "$RUN/front.legacy"; exit 0 ;;
  is-active) alive ;;
  reset-failed) ;;
  show)
    case "$*" in
      *MainPID*) if [ "$slot" = front ] && alive; then cat "$pidf"; else echo 0; fi ;;
      *) if alive; then printf 'active\nrunning\n'; else printf 'inactive\ndead\n'; fi ;;
    esac ;;
esac
"""


class Rig:
    def __init__(self, tmp_path):
        self.root = tmp_path
        self.dir, self.state, self.fake, self.run = (tmp_path / d for d in ("imessage", "state", "fake", "run"))
        self.notes = tmp_path / "notes"
        bin_dir = tmp_path / "bin"
        for d in (self.dir, self.state, self.run, bin_dir, self.fake / "inbound", self.fake / "messages", self.fake / "edits"):
            d.mkdir(parents=True)
        (self.fake / "down").write_text("0")
        (self.fake / "typing-down").touch()
        pkg = self.dir / "node_modules/spectrum-ts"
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text(json.dumps({"name": "spectrum-ts", "type": "module",
                                                      "exports": {".": "./index.js", "./providers/imessage": "./index.js"}}))
        (pkg / "index.js").write_text(FAKE_UPSTREAM)
        stubs = {
            "systemctl": SYSTEMCTL[SYSTEMCTL.index("\n") + 1:],
            "omp": 'echo ok',
            "fm-inbox": f'printf "%s\\n" "$*" >> {self.notes}',
        }
        for name, body in stubs.items():
            (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
            (bin_dir / name).chmod(0o755)
        self.port, self.next_port, card = free_port(), free_port(), free_port()
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "FAKE_DIR": str(self.fake), "RUN": str(self.run), "DIR": str(self.dir),
            "FM_HOME": str(tmp_path), "FM_INBOX_CMD": str(bin_dir / "fm-inbox"),
            "FM_IMESSAGE_OWNER": "+10000000000", "FM_IMESSAGE_PORT": str(self.port), "FM_IMESSAGE_NEXT_PORT": str(self.next_port),
            "FM_IMESSAGE_CARD_URL": f"http://127.0.0.1:{card}", "FM_IMESSAGE_CARD_PORT": str(card),
            "FM_IMESSAGE_RETRY_MS": "20", "PHOTON_PROJECT_ID": "fake", "PHOTON_PROJECT_SECRET": "fake",
            "STATE_DIRECTORY": str(self.state), "FM_IMESSAGE_DIR": str(self.dir),
            "FM_IMESSAGE_TEST": "1", "FM_IMESSAGE_TEST_QUIET_MS": "2000",
            "FM_IMESSAGE_TEST_NATIVES": f"test ! -e {self.fake}/natives-broken",
            "FM_DEPLOY_POLL_MS": "200", "FM_DEPLOY_GATE_MS": "40000", "FM_DEPLOY_OWN_MS": "30000", "FM_DEPLOY_BACK_MS": "40000",
        }
        self.sent_file = self.fake / "sent"

    def stage(self, plant=None):
        """Copies the bridge into <dir>/stage the way the Ansible role does."""
        stage = self.dir / "stage"
        shutil.rmtree(stage, ignore_errors=True)
        shutil.copytree(ROOT / "apps/imessage", stage, ignore=shutil.ignore_patterns("fm-*", "*.test.ts", "bluebubbles-relay"))
        if plant:
            plant(stage)

    def legacy(self):
        """The pre-slot bridge: files directly in <dir>, run by the front unit."""
        shutil.copytree(ROOT / "apps/imessage", self.dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns("fm-*", "*.test.ts", "bluebubbles-relay"))
        (self.run / "front.legacy").touch()
        subprocess.run(["systemctl", "--user", "start", "fm-imessage.service"], env=self.env, check=True)
        wait_for(lambda: self.health(), "the legacy bridge")

    def health(self, port=None):
        r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "-H", "X-Firstmate: 1",
                            f"http://127.0.0.1:{port or self.port}/health"], capture_output=True, text=True)
        return r.stdout == "200"

    def inbound(self, mid):
        publish_json(self.fake / "inbound" / f"{mid}.json",
                     {"id": mid, "space": "iMessage;-;+10000000000", "sender": "+10000000000", "text": "hello"})
        wait_for(lambda: f"photon-{mid} " in (self.notes.read_text() if self.notes.exists() else ""), f"note {mid}")

    def send(self, text):
        r = subprocess.run([str(SEND), "--", text], capture_output=True, text=True, env=self.env, timeout=30)
        assert r.returncode == 0, r.stderr

    def sent(self):
        return sorted(self.sent_file.read_text().splitlines()) if self.sent_file.exists() else []

    def deploy(self):
        return subprocess.run(["bun", str(ROOT / "apps/imessage/deploy.ts")], capture_output=True, text=True, env=self.env, timeout=180)

    def needed(self):
        return subprocess.run(["bun", str(ROOT / "apps/imessage/deploy.ts"), "needed"], capture_output=True, text=True, env=self.env, timeout=60).returncode

    def gap_during(self, action):
        """Runs action while polling /health; returns (action result, longest stretch in seconds with no answer)."""
        stop, longest, down_since = threading.Event(), [0.0], [None]

        def poll():
            while not stop.is_set():
                now = time.monotonic()
                if self.health():
                    down_since[0] = None
                else:
                    down_since[0] = down_since[0] or now
                    longest[0] = max(longest[0], time.monotonic() - down_since[0])
                time.sleep(0.05)

        thread = threading.Thread(target=poll)
        thread.start()
        try:
            return action(), longest[0]
        finally:
            stop.set()
            thread.join()

    def alive(self, slot):
        return subprocess.run(["systemctl", "--user", "is-active", f"fm-imessage@{slot}.service"], env=self.env).returncode == 0

    def active(self):
        return (self.state / "active").read_text().strip()

    def close(self):
        for pidf in self.run.glob("*.pid"):
            try:
                os.kill(int(pidf.read_text()), 9)
            except (OSError, ValueError):
                pass


@pytest.fixture
def rig(tmp_path):
    r = Rig(tmp_path)
    yield r
    r.close()


def test_rolls_out_over_a_running_bridge_and_a_planted_broken_build_rolls_back(rig):
    rig.legacy()
    rig.inbound("m1")
    (rig.fake / "send-hold").touch()  # the legacy bridge holds these texts in its outbox
    rig.send("one")
    rig.send("two")
    rig.stage()

    good, gap = rig.gap_during(rig.deploy)
    assert good.returncode == 0, good.stdout + good.stderr
    print(f"handover gap: {gap:.1f} s")
    assert gap < 30  # the line answers /health again within seconds of the old slot stopping
    assert rig.active() == "blue" and rig.alive("blue") and not (rig.run / "front.pid").exists()
    (rig.fake / "send-hold").unlink()
    wait_for(lambda: len(rig.sent()) == 2, "the held texts")
    assert rig.sent() == ["send one", "send two"]  # each exactly once across the handover

    # the next build comes up with broken natives: the gate fails and the serving slot is never touched
    (rig.fake / "natives-broken").touch()
    (rig.fake / "send-hold").touch()
    rig.send("three")
    rig.stage()
    bad = rig.deploy()
    assert bad.returncode == 1, bad.stdout + bad.stderr
    assert "natives do not load" in bad.stdout
    assert "skipped: natives failed" in bad.stdout  # the paid desk call is not made for a build whose natives do not load
    assert rig.active() == "blue" and rig.alive("blue") and not rig.alive("green")
    (rig.fake / "send-hold").unlink()
    wait_for(lambda: len(rig.sent()) == 3, "the text queued during the failed deploy")
    assert rig.sent() == ["send one", "send three", "send two"]
    assert rig.health()


def test_a_gate_failure_on_the_first_install_leaves_the_state_as_it_was(rig):
    rig.legacy()
    rig.inbound("m1")
    (rig.fake / "natives-broken").touch()
    rig.stage()
    bad = rig.deploy()
    assert bad.returncode == 1 and "natives do not load" in bad.stdout, bad.stdout + bad.stderr
    assert not (rig.state / "active").exists() and rig.alive("front") and rig.health()

    (rig.fake / "natives-broken").unlink()
    good = rig.deploy()
    assert good.returncode == 0, good.stdout + good.stderr
    assert rig.active() == "blue" and rig.alive("blue") and not rig.alive("legacy") and rig.health()


def test_a_slot_that_fails_after_the_handover_rolls_back_to_the_old_slot(rig):
    rig.legacy()
    rig.inbound("m1")
    rig.stage()
    assert rig.deploy().returncode == 0  # first rolling install: legacy to blue
    rig.send("kept")
    wait_for(lambda: rig.sent() == ["send kept"], "the first text")

    def plant(stage):  # the build passes the gate, then dies when it takes the line
        bridge = stage / "bridge.ts"
        bridge.write_text(bridge.read_text().replace('memory = new Memory(', 'if (process.env.FM_IMESSAGE_SLOT) throw new Error("planted failure after the handover");\nmemory = new Memory(', 1))

    rig.stage(plant)
    result = rig.deploy()
    assert result.returncode == 1, result.stdout + result.stderr
    assert "rolling back to blue" in result.stdout
    assert rig.active() == "blue" and rig.alive("blue") and rig.health()
    rig.send("after")
    wait_for(lambda: len(rig.sent()) == 2, "a text through the restored slot")
    assert rig.sent() == ["send after", "send kept"]
    wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "an empty outbox")  # no item left behind


PLANT_AFTER_HANDOVER = ('memory = new Memory(', 'if (process.env.FM_IMESSAGE_SLOT) throw new Error("planted failure after the handover");\nmemory = new Memory(')


def plant_after_handover(stage):  # the build passes the gate, then dies when it takes the line
    bridge = stage / "bridge.ts"
    bridge.write_text(bridge.read_text().replace(*PLANT_AFTER_HANDOVER, 1))


def test_a_failed_first_install_leaves_the_legacy_slot_and_the_next_deploy_still_works(rig):
    rig.legacy()
    rig.inbound("m1")
    rig.stage(plant_after_handover)
    assert rig.needed() == 3
    failed = rig.deploy()
    assert failed.returncode == 1 and "rolling back to legacy" in failed.stdout, failed.stdout + failed.stderr
    assert rig.active() == "legacy" and rig.alive("legacy") and rig.health()
    assert rig.needed() == 3  # a failed deploy is not recorded, so the next apply tries again

    rig.stage()
    good = rig.deploy()
    assert good.returncode == 0, good.stdout + good.stderr
    assert rig.active() == "blue" and rig.alive("blue") and not rig.alive("legacy") and rig.health()
    assert rig.needed() == 0
    rig.stage(lambda stage: (stage / "extra.ts").write_text("// a new build\n"))
    assert rig.needed() == 3


def test_the_confirm_step_fails_when_there_is_no_text_to_read_back(rig):
    rig.legacy()  # no inbound text: the bridge knows no latest text, so a probe would reach no transport
    rig.stage()
    result = rig.deploy()
    assert result.returncode == 1 and "rolling back to legacy" in result.stdout, result.stdout + result.stderr
    assert rig.active() == "legacy" and rig.alive("legacy") and rig.health()


def test_texts_sent_through_the_handover_wait_for_the_line_and_go_out_exactly_once(rig):
    rig.legacy()
    rig.inbound("m1")
    rig.stage()
    results, stop = [], threading.Event()

    def keep_sending():
        n = 0
        while not stop.is_set():
            r = subprocess.run([str(SEND), "--", f"text {n}"], capture_output=True, text=True, env=rig.env, timeout=200)
            results.append(r.returncode)
            n += 1
            time.sleep(0.05)

    sender = threading.Thread(target=keep_sending)
    sender.start()
    try:
        deploy = rig.deploy()
    finally:
        stop.set()
        sender.join()
    assert deploy.returncode == 0, deploy.stdout + deploy.stderr
    assert results and set(results) == {0}  # no send was refused, whichever side of the handover it hit
    wait_for(lambda: len(rig.sent()) == len(results), "every text")
    assert rig.sent() == sorted(f"send text {n}" for n in range(len(results)))  # each exactly once


def test_the_heal_unit_runs_the_selfheal_of_the_active_slot(tmp_path):
    """The heal unit's ExecStart, rendered as the role renders it and run the way systemd runs it ($$ is one $)."""
    import shlex

    from jinja2 import Environment
    jinja = Environment()
    jinja.filters["comment"] = lambda text: "# " + text
    dir_, state, bin_dir = tmp_path / "imessage", tmp_path / "state", tmp_path / "bin"
    for d in (dir_ / "green", state, bin_dir):
        d.mkdir(parents=True)
    (dir_ / "green/selfheal.ts").write_text("")
    (state / "active").write_text("green\n")
    (bin_dir / "bun").write_text('#!/bin/bash\n[ -f "$1" ] && echo "$PWD $*" > "$OUT"\n')
    (bin_dir / "bun").chmod(0o755)
    unit = jinja.from_string((ROOT / "blueprint/ansible/templates/fm-imessage-heal.service.j2").read_text()).render(
        ansible_managed="test", crewship_imessage_dir=str(dir_), crewship_local_bin=str(bin_dir), crewship_firstmate_dir=str(tmp_path))
    start = next(line.removeprefix("ExecStart=") for line in unit.splitlines() if line.startswith("ExecStart="))
    out = tmp_path / "out"
    subprocess.run(shlex.split(start.replace("$$", "$")), env={**os.environ, "STATE_DIRECTORY": str(state), "OUT": str(out)}, check=True)
    assert out.read_text().strip() == f"{dir_ / 'green'} selfheal.ts failed"


@pytest.mark.parametrize("mainpid, stops", [("", False), ("4242", True)])
def test_the_front_unit_stops_the_slots_only_when_it_is_stopped_on_purpose(tmp_path, mainpid, stops):
    """ExecStop as rendered, with systemd's ${MAINPID} substitution applied (it is empty when the process exited on its own)."""
    import shlex

    from jinja2 import Environment
    jinja = Environment()
    jinja.filters["comment"] = lambda text: "# " + text
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "bun").write_text('#!/bin/bash\necho "$*" >> "$OUT"\n')
    (bin_dir / "bun").chmod(0o755)
    unit = jinja.from_string((ROOT / "blueprint/ansible/templates/fm-imessage.service.j2").read_text()).render(
        ansible_managed="test", crewship_imessage_dir=str(tmp_path), crewship_local_bin=str(bin_dir))
    stop = next(line.removeprefix("ExecStop=") for line in unit.splitlines() if line.startswith("ExecStop="))
    out = tmp_path / "out"
    subprocess.run(shlex.split(stop.replace("${MAINPID}", mainpid)), env={**os.environ, "OUT": str(out)}, check=True)
    assert out.exists() == stops
    if stops:
        assert out.read_text().strip().endswith("imessage-deploy.ts stop-all")
