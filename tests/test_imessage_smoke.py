"""Desk release smoke: one real text gets a real answer through the bridge, front and desk.

Run before every fm-imessage desk release (docs/imessage.md). With FM_DESK_SMOKE_STRICT=1 a front
secret masker that cannot load FAILS the run; without it the test skips, as in CI, whose omp stub
has none. Only the model's network edge is stubbed.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_imessage import wait_for
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


@pytest.fixture(autouse=True)
def masker(tmp_path):
    problem = masker_loads(tmp_path)
    if problem and not STRICT:
        pytest.skip(f"front secret masker unavailable: {problem}")
    assert problem is None, f"front secret masker cannot load, so the front relays every text: {problem}"


def test_front_secret_masker_loads():
    """The autouse fixture is the check: a missing native addon fails the smoke run."""


def test_real_text_gets_a_real_answer_not_the_routing_line(tmp_path):
    with v2_rig(tmp_path, [{"kind": "status", "text": ""}]) as rig:
        deliver(rig, "m1", "what is the mate doing right now")
        wait_for(lambda: len(texts(rig)) == 1, "the desk answer", timeout=120)
        reply = texts(rig)[0].split(" ", 1)[1].strip()
        assert reply, "the desk sent an empty reply"
        assert not ROUTING_RECEIPT.search(reply), f"the desk sent the routing receipt: {reply}"
        assert "Checks are running." in reply
        assert not any(e.get("route") == "handoff" for e in events(rig)), "the front relayed the text"
