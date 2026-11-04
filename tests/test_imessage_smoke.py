"""Desk release smoke: real texts get real handling through the bridge, front and desk, never the routing line.

Run with FM_DESK_SMOKE_STRICT=1 before every fm-imessage desk release (docs/imessage.md): a front
secret masker that cannot load then FAILS the run. Without it the masker check, the status check and the
desk session check skip, as in CI, whose omp stub has none. The relay routing check needs no masker and always runs.
Only the model's network edge is stubbed; the desk session check runs a fake omp child (tests/fake_desk_omp.ts).
"""

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from test_imessage import wait_for
from test_imessage_session import session_rig
from test_imessage_v2 import deliver, events, texts, v2_rig

STRICT = os.environ.get("FM_DESK_SMOKE_STRICT") == "1"
ROUTING_RECEIPT = re.compile(r"\bI am routing\b|routing (this|the|your) request", re.I)
FRONT_TS = Path(__file__).resolve().parent.parent / "apps/imessage/front.ts"

pytestmark = pytest.mark.skipif(not STRICT and not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")


def masker_loads(tmp_path):
    """Load the front masker as the bridge does and mask one payload; None when it loads, else why not."""
    code = f"""
import {{ loadFrontRedactor }} from {json.dumps(str(FRONT_TS))};
const redact = await loadFrontRedactor(process.cwd(), process.env.PI_CODING_AGENT_DIR!);
console.log(redact(JSON.stringify({{ messages: [{{ role: "user", content: "hello" }}] }})));
"""
    run = subprocess.run(["bun", "-e", code], capture_output=True, text=True, timeout=60,
                         env={**os.environ, "PI_CODING_AGENT_DIR": str(tmp_path / "agent")})
    if run.returncode == 0:
        return None
    lines = run.stderr.splitlines()
    return next((line for line in lines if "rror" in line), "unknown")


def test_front_secret_masker_loads(tmp_path):
    problem = masker_loads(tmp_path)
    if problem and not STRICT:
        pytest.skip(f"front secret masker unavailable: {problem}")
    assert problem is None, f"front secret masker cannot load, so the front relays every text: {problem}"


def test_work_text_is_handed_off_with_no_routing_line(tmp_path):
    with v2_rig(tmp_path, [{"kind": "relay", "target": 0, "domains": [], "category": "other"}]) as rig:
        deliver(rig, "m1", "please check the whole repo")
        wait_for(lambda: any(e.get("route") == "handoff" for e in events(rig)), "the handoff", timeout=120)
        deadline = time.monotonic() + 8
        while not texts(rig) and time.monotonic() < deadline:
            time.sleep(0.2)
        sent = texts(rig)
        assert not any(ROUTING_RECEIPT.search(line) for line in sent), f"the desk sent the routing receipt: {sent}"
        assert sent == [], "the desk answered a text it handed to the firstmate"


def test_status_text_gets_a_real_answer_not_the_routing_line(tmp_path):
    problem = masker_loads(tmp_path)
    if problem and not STRICT:
        pytest.skip(f"front secret masker unavailable, so the front relays every text: {problem}")
    with v2_rig(tmp_path, [{"kind": "status", "text": ""}]) as rig:
        deliver(rig, "m1", "what is the mate doing right now")
        wait_for(lambda: len(texts(rig)) == 1, "the desk answer", timeout=120)
        reply = texts(rig)[0].split(" ", 1)[1].strip()
        assert reply, "the desk sent an empty reply"
        assert not ROUTING_RECEIPT.search(reply), f"the desk sent the routing receipt: {reply}"
        assert not any(e.get("route") == "handoff" for e in events(rig)), "the front relayed the text"


def test_session_text_gets_a_real_reply_not_the_routing_line(tmp_path):
    problem = masker_loads(tmp_path)
    if problem and not STRICT:
        pytest.skip(f"front secret masker unavailable, so the desk session hands off every text: {problem}")
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how was your day")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        reply = texts(rig)[0].split(" ", 1)[1].strip()
        assert reply, "the desk session sent an empty reply"
        assert not ROUTING_RECEIPT.search(reply), f"the desk session sent the routing receipt: {reply}"
        assert not any(e.get("route") == "handoff" for e in events(rig)), "the desk session handed the text off"
