"""The V2 desk wiring in bridge.ts: the front's short answer, the social tapback, and the Firstmate handoff."""

import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager

import pytest
from test_imessage import FallbackRig, read_text, wait_for

# The bridge masks the front context through the installed omp packages; the CI omp stub has none,
# so these tests skip where the redactor cannot load.
REDactor_PROBE = """
try {
  const omp = Bun.which("omp");
  if (!omp) throw new Error("no omp");
  const base = require("node:path").dirname(require("node:fs").realpathSync(omp));
  Bun.resolveSync("@oh-my-pi/pi-utils/dirs", base);
  Bun.resolveSync("@oh-my-pi/pi-coding-agent/secrets", base);
  console.log("true");
} catch { console.log("false"); }
"""

# One Inception endpoint for the front classification: every call gets the scripted reply,
# or the relay default when the test scripts none.
FAKE_INCEPTION = """
const server = Bun.serve({
  port: 0,
  async fetch() {
    const content = process.env.FRONT ?? JSON.stringify({ kind: "relay", target: 0, domains: [], category: "other" });
    return Response.json({ choices: [{ message: { content } }] });
  },
});
await Bun.write(process.env.PORT_FILE!, String(server.port));
"""


def omp_masks():
    return subprocess.run(["bun", "-e", REDactor_PROBE], capture_output=True, text=True,
                          timeout=30, check=True).stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not (shutil.which("bun") and shutil.which("curl")) or not omp_masks(),
    reason="needs bun, curl and the installed omp secret packages",
)

def events(rig):
    return [json.loads(line) for line in read_text(rig.state / "routing.jsonl").splitlines()]


def texts(rig):
    """The relay log: a text as "<chat> <text>", a tapback as "react <message> <name>"."""
    return read_text(rig.fake / "relay-sent").splitlines()


@contextmanager
def v2_rig(tmp_path, front, inception=None):
    """A V2 bridge over the fake transports; `front` holds the one scripted front reply."""
    server, url = None, inception
    if url is None:
        port_file = tmp_path / "inception-port"
        env = {**os.environ, "PORT_FILE": str(port_file), **({"FRONT": json.dumps(front[0])} if front else {})}
        server = subprocess.Popen(["bun", "-e", FAKE_INCEPTION], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            wait_for(lambda: port_file.exists(), "the fake inception endpoint", timeout=120)
            url = f"http://127.0.0.1:{read_text(port_file).strip()}/v1/chat/completions"
        except BaseException:
            subprocess.Popen.terminate(server)
            raise
    rig = FallbackRig(tmp_path, FM_IMESSAGE_TEST="1", FM_IMESSAGE_TEST_QUIET_MS="30",
                      FM_IMESSAGE_DESK_V2="true", INCEPTION_API_KEY="test-key",
                      FM_DESK_INCEPTION_URL=url, PI_CODING_AGENT_DIR=str(tmp_path / "agent"))
    (tmp_path / "bin" / "omp").unlink()  # unshadow the real omp: the V2 desk needs its installed packages
    try:
        rig.start()
        yield rig
    finally:
        if server:
            subprocess.Popen.terminate(server)
            subprocess.Popen.wait(server, 10)


def deliver(rig, guid, text):
    """Send one BlueBubbles text and wait until the bridge owns it durably."""
    rig.relay_message(guid, text, int(time.time() * 1000))
    hook = json.dumps({"type": "new-message", "data": {"guid": guid}})
    subprocess.run(["curl", "-sS", "-d", hook, f"http://127.0.0.1:{rig.hook_port}/bluebubbles"],
                   check=True, capture_output=True)
    wait_for(lambda: any("received" in e and e.get("received", {}).get("requestId") == f"bluebubbles-{guid}"
                         for e in events(rig)), f"durable ownership of {guid}", timeout=120)


def test_short_social_answer_is_delivered_as_written(tmp_path):
    with v2_rig(tmp_path, [{"kind": "social", "text": "Anytime."}]) as rig:
        deliver(rig, "m1", "thanks")
        wait_for(lambda: any(e.get("route") == "desk" and "bluebubbles-m1" in e.get("ids", [])
                             and e.get("out", {}).get("bubbles") == ["Anytime."]
                             for e in events(rig)), "the front answer as the desk route", timeout=120)
        wait_for(lambda: "Anytime." in " ".join(texts(rig)), "the delivered bubble", timeout=120)
        wait_for(lambda: rig.outbox() == [], "the empty outbox", timeout=120)
        assert not any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig))
        assert not any("react" in e.get("out", {}) for e in events(rig))


def test_silent_social_turn_ends_in_one_tapback(tmp_path):
    with v2_rig(tmp_path, [{"kind": "social", "text": ""}]) as rig:
        deliver(rig, "m1", "thanks")
        wait_for(lambda: any(e.get("route") == "desk" and e.get("social") and "bluebubbles-m1" in e.get("ids", [])
                             and e.get("out", {}).get("react") == "❤️" for e in events(rig)), "the social tapback", timeout=120)
        wait_for(lambda: "react m1 love" in texts(rig), "the tapback on his text", timeout=120)
        wait_for(lambda: rig.outbox() == [], "the empty outbox", timeout=120)
        assert all("react" in line for line in texts(rig))
        assert not any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig))


def test_work_request_relays_to_firstmate_without_any_text(tmp_path):
    with v2_rig(tmp_path, [{"kind": "relay", "target": 0, "domains": [], "category": "other"}]) as rig:
        deliver(rig, "m1", "please check the whole repo")
        wait_for(lambda: any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", [])
                             for e in events(rig)), "the firstmate handoff", timeout=120)
        assert not texts(rig)  # a work request hands off silently: no text and no tapback
        assert not any(e.get("route") == "desk" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig))


def test_unreachable_front_falls_back_to_firstmate(tmp_path):
    with v2_rig(tmp_path, None, inception="http://127.0.0.1:9/v1/chat/completions") as rig:
        deliver(rig, "m1", "please check the whole repo")
        wait_for(lambda: any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", [])
                             for e in events(rig)), "the fail-closed handoff", timeout=120)
        assert not texts(rig)
