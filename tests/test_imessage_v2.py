"""The V2 desk wiring in bridge.ts: the front's short answer, the social tapback, and the Firstmate handoff."""

import json
import os
import shutil
import subprocess
import time
from contextlib import contextmanager

import pytest
from test_imessage import FallbackRig, publish_json, read_text, wait_for

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
        rig.close()
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


def test_social_text_gets_one_tapback_even_when_the_model_returns_text(tmp_path):
    with v2_rig(tmp_path, [{"kind": "social", "text": "Anytime."}]) as rig:
        deliver(rig, "m1", "thanks")
        wait_for(lambda: any(e.get("route") == "desk" and e.get("social") and "bluebubbles-m1" in e.get("ids", [])
                             and e.get("out", {}).get("react") == "❤️" for e in events(rig)), "the social tapback", timeout=120)
        wait_for(lambda: "react m1 love" in texts(rig), "the tapback on his text", timeout=120)
        wait_for(lambda: rig.outbox() == [], "the empty outbox", timeout=120)
        assert all("react" in line for line in texts(rig))
        assert not any(e.get("out", {}).get("bubbles") for e in events(rig))
        assert not any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig))


@pytest.mark.parametrize("resume,destination", [(None, "Firstmate"), ("relay", "Firstmate"), ("dispatch", "Firstmate"), ("mate", "mate1 secondmate")])
def test_work_request_gets_front_reply_without_completing_handoff(tmp_path, resume, destination):
    front = {"kind": "relay", "target": 0, "domains": [], "category": "other"}
    if resume == "mate":
        front = {"kind": "relay", "target": 1, "domains": [1], "category": "work"}
        (tmp_path / "data").mkdir()
        (tmp_path / "data/secondmates.md").write_text(f"- mate1 - Repo mate (home: {tmp_path}/mate1; scope: repo checks; projects: none)\n")
    with v2_rig(tmp_path, [front]) as rig:
        deliver(rig, "m1", "please check the whole repo")
        wait_for(lambda: any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", [])
                             for e in events(rig)), "the firstmate handoff", timeout=120)
        wait_for(lambda: texts(rig), "the front reply", timeout=5)
        assert len(texts(rig)) == 1
        assert destination in texts(rig)[0] and "worker" not in texts(rig)[0]
        assert not any("responded" in e for e in events(rig))
        if resume == "mate":
            return
        if resume:
            wait_for(lambda: rig.outbox() == [], "the front delivery receipt")
            rig.stop()
            plan = next(e["v2"] for e in events(rig) if "v2" in e)
            if resume == "dispatch":
                plan["intents"] = [{"kind": "dispatch", "model": "anthropic/claude-haiku-5.5", "reasoning": "off"}]
            with (rig.state / "routing.jsonl").open("a") as log:
                log.write(json.dumps({"ids": ["bluebubbles-m1"], "v2": plan}) + "\n")
                log.write(json.dumps({"ids": ["bluebubbles-m1"], "route": "pending"}) + "\n")
            rig.start()
            wait_for(lambda: sum(e.get("route") == "handoff" for e in events(rig)) == 2, "the resumed handoff")
            wait_for(lambda: rig.outbox() == [], "the deduplicated front reply")
            assert len(texts(rig)) == 1
            assert not any("responded" in e for e in events(rig))
        rig.cli("The review is complete.")
        wait_for(lambda: len(texts(rig)) == 2, "the final answer", timeout=30)
        wait_for(lambda: any("responded" in e for e in events(rig)), "the completed request", timeout=30)
        assert not any(e.get("route") == "desk" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig))


def test_front_reply_keeps_typing_until_the_final_answer(tmp_path):
    with v2_rig(tmp_path, [{"kind": "relay", "target": 0, "domains": [], "category": "other"}]) as rig:
        typing = rig.fake / "typing-events"
        record = {"id": "m1", "space": "iMessage;-;+10000000000", "sender": "+10000000000", "text": "please check the whole repo"}
        publish_json(rig.fake / "inbound" / "m1.json", record)
        wait_for(lambda: "send " in read_text(rig.fake / "sent"), "the front reply", timeout=120)
        wait_for(lambda: rig.outbox() == [], "the front delivery receipt")
        rows = [json.loads(line) for line in read_text(typing).splitlines()]
        assert rows and all(row["on"] for row in rows)
        assert not any("responded" in e for e in events(rig))
        rig.cli("The review is complete.")
        wait_for(lambda: any("responded" in e for e in events(rig)), "the completed request", timeout=30)
        wait_for(lambda: not json.loads(read_text(typing).splitlines()[-1])["on"], "typing stopped by the final answer")


def test_unreachable_front_falls_back_to_firstmate(tmp_path):
    with v2_rig(tmp_path, None, inception="http://127.0.0.1:9/v1/chat/completions") as rig:
        deliver(rig, "m1", "please check the whole repo")
        wait_for(lambda: any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", [])
                             for e in events(rig)), "the fail-closed handoff", timeout=120)
        wait_for(lambda: texts(rig), "the fallback front reply", timeout=30)
        assert not texts(rig)[0].startswith("react ")
