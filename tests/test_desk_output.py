"""Desk directives must never become message text on any messaging surface."""

import json
import shlex
import shutil
import time

import pytest
from test_imessage import FallbackRig, http, publish_json, read_text, wait_for
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


def draft_rig(tmp_path, output, structured=True):
    rig = FallbackRig(tmp_path, FM_IMESSAGE_TEST="1", FM_IMESSAGE_TEST_QUIET_MS="30")
    drafted = json.dumps({
        "kind": "basic", "answer": output, "evidence": [{"source": "status", "quote": output}],
    }) if structured else output
    (tmp_path / "bin/omp").write_text(
        f"#!/bin/sh\ncat >/dev/null\nprintf '%s' {shlex.quote(drafted)}\n"
    )
    (tmp_path / "bin/fm-inbox").write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = status ]; then printf '%s' {shlex.quote(output)}; "
        f"else printf '%s\\n' \"$*\" >> {shlex.quote(str(rig.notes))}; fi\n"
    )
    return rig


@pytest.mark.parametrize("surface,structured", [
    ("instagram", False), ("photon", False), ("photon", True),
    ("bluebubbles", False), ("bluebubbles", True),
])
@pytest.mark.parametrize("output,action", [
    (LEAKED, "👍"),
    ("REACT:👍\nI should check the chat first.", "👍"),
    ("My move is a tapback only. TAPBACK:❤️", "❤️"),
    ("I should leave this to Firstmate. SKIP", None),
    ("I should leave this to Firstmate.\n\nskip", None),
    ("I should leave this to Firstmate.\n\n  sKiP!!  \nMore reasoning.", None),
    ("Nothing else is needed.\n\nskip", None),
    ("REACT:👍\n\nsKiP.", None),
    ("For this thread, I should defer to Firstmate.", None),
    ("I should defer to Firstmate for this thread.", None),
    ("Firstmate handles this request in this thread.", None),
    ("This is a fleet instruction that Firstmate handles in this thread.", None),
    ("Firstmate handles this fleet instruction in this thread.", None),
    ("The desk should check the unsummarized lines before deciding.", None),
    ("My move is to wait for more context.", None),
    ("REACT: not-an-emoji", None),
    ("REACT:👍\nREACT:👎", None),
    ("REACT:👍\nSKIP", None),
])
def test_reasoning_and_directives_never_become_message_text(
    tmp_path, surface, structured, output, action
):
    if surface == "instagram":
        result = run(tmp_path, f"""
            feed('messages', {{ id: 'a', text: {json.dumps(REQUEST)} }});
            await wait(1200);
            out.sends = sends();
        """, answer=output)
        expected = [f"desk|--react {action} --thread T"] if action else []
        assert result["sends"] == expected
        return

    rig = draft_rig(tmp_path, output, structured)
    try:
        rig.start()
        if surface == "photon":
            rig.photon_text("report", REQUEST)
        else:
            rig.relay_text("report", REQUEST, int(time.time() * 1000))
        wait_for(lambda: "report " in read_text(rig.state / "desk.log"), "the completed desk turn")
        wait_for(lambda: not rig.outbox(), "the completed desk delivery")
        rig.stop()
        if output == LEAKED:
            rig.start()
            time.sleep(0.15)
            rig.stop()
        expected = [f"react report {action}"] if action else []
        reaction = {"👍": "like", "❤️": "love"}.get(action)
        relay_expected = [f"react report {reaction}"] if action else []
        assert read_text(rig.fake / "sent").splitlines() == (expected if surface == "photon" else [])
        assert read_text(rig.fake / "relay-sent").splitlines() == (
            relay_expected if surface == "bluebubbles" else []
        )
        assert read_text(rig.notes).count(f"{surface}-report ") == 1
        assert REQUEST in read_text(rig.notes)
    finally:
        rig.close()


@pytest.mark.parametrize("surface", ["instagram", "photon", "bluebubbles"])
@pytest.mark.parametrize("output", [
    "my bad, i should've replied sooner",
    "yeah skip the queue",
    "firstmate needs your approval on the pr",
    "Firstmate is the supervisor in this thread.",
    "The front desk handles questions in this thread.",
    "Firstmate handles fleet instructions in this thread.",
    "Firstmate handles each request in this thread.",
])
def test_normal_desk_text_still_reaches_the_user(tmp_path, surface, output):
    if surface == "instagram":
        result = run(tmp_path, """
            feed('messages', { id: 'a', text: 'you there?' });
            await wait(1200);
            out.sends = sends();
        """, answer=output)
        assert result["sends"] == [f"desk|--thread T -- {output}"]
        return

    rig = draft_rig(tmp_path, output)
    try:
        rig.start()
        if surface == "photon":
            publish_json(rig.fake / "inbound/normal.json", {
                "id": "normal", "space": "iMessage;-;+10000000000",
                "sender": "+10000000000", "text": "What is the status?",
            })
        else:
            rig.relay_message("normal", "What is the status?", int(time.time() * 1000))
            assert http(f"http://127.0.0.1:{rig.hook_port}/bluebubbles", "POST",
                        json.dumps({"type": "new-message", "data": {"guid": "normal"}}))[0] == 200
        sent = rig.fake / ("sent" if surface == "photon" else "relay-sent")
        wait_for(lambda: read_text(sent), "the normal desk reply")
        rig.stop()
        prefix = "send" if surface == "photon" else "iMessage;-;+10000000000"
        assert read_text(sent).splitlines() == [f"{prefix} {output}"]
        assert read_text(rig.notes) == ""
    finally:
        rig.close()
