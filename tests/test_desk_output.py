"""Desk directives must never become message text on any messaging surface."""

import json
import shlex
import shutil
import time

import pytest
from test_imessage import FallbackRig, read_text
from test_instagram_desk import run

LEAKED = (
    "I need to check the unsummarized lines 79 and the latest text before deciding. "
    "The latest text is a fleet instruction (change limits), which Firstmate handles in this thread. "
    "My move is a tapback only.\n\nREACT:👍"
)
REQUEST = "Increase the limit to 25 on day 1 instead of 10. Raise total final limit to 50"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl"
)


@pytest.mark.parametrize("surface", ["instagram", "photon", "bluebubbles"])
@pytest.mark.parametrize("output,action", [
    (LEAKED, "👍"),
    ("REACT:👍\nI should check the chat first.", "👍"),
    ("My move is a tapback only. TAPBACK:❤️", "❤️"),
    ("I should leave this to Firstmate. SKIP", None),
    ("Firstmate handles this request in this thread.", None),
    ("The desk should check the unsummarized lines before deciding.", None),
    ("My move is to wait for more context.", None),
    ("REACT: not-an-emoji", None),
    ("REACT:👍\nREACT:👎", None),
    ("REACT:👍\nSKIP", None),
])
def test_reasoning_and_directives_never_become_message_text(tmp_path, surface, output, action):
    if surface == "instagram":
        result = run(tmp_path, f"""
            feed('messages', {{ id: 'a', text: {json.dumps(REQUEST)} }});
            await wait(1200);
            out.sends = sends();
        """, answer=output)
        expected = [f"desk|--react {action} --thread T"] if action else []
        assert result["sends"] == expected
        return

    rig = FallbackRig(tmp_path, FM_IMESSAGE_TEST="1", FM_IMESSAGE_TEST_QUIET_MS="30")
    model = tmp_path / "bin/omp"
    drafted = json.dumps({
        "kind": "basic", "answer": output, "evidence": [{"source": "status", "quote": output}],
    })
    model.write_text(f"#!/bin/sh\ncat >/dev/null\nprintf '%s' {shlex.quote(drafted)}\n")
    inbox = tmp_path / "bin/fm-inbox"
    inbox.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = status ]; then printf '%s' {shlex.quote(output)}; "
        f"else printf '%s\\n' \"$*\" >> {shlex.quote(str(rig.notes))}; fi\n"
    )
    try:
        rig.start()
        if surface == "photon":
            rig.photon_text("report", REQUEST)
        else:
            rig.relay_text("report", REQUEST, int(time.time() * 1000))
        assert read_text(rig.fake / "sent") == ""
        assert read_text(rig.fake / "relay-sent") == ""
        assert read_text(rig.notes).count(f"{surface}-report ") == 1
    finally:
        rig.close()


@pytest.mark.parametrize("output", [
    "my bad, i should've replied sooner",
    "yeah skip the queue",
    "firstmate needs your approval on the pr",
])
def test_normal_desk_text_still_reaches_the_user(tmp_path, output):
    result = run(tmp_path, """
        feed('messages', { id: 'a', text: 'you there?' });
        await wait(1200);
        out.sends = sends();
    """, answer=output)
    assert result["sends"] == [f"desk|--thread T -- {output}"]
