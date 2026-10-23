"""Desk decisions must never become message text on any messaging surface."""

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
FACT = "The build is paused."
REPLY = {
    "kind": "reply", "answer": FACT, "evidence": [{"source": "status", "quote": FACT}],
}

REACTIONS = [
    (LEAKED, "👍"),
    ("REACT:👍", "👍"),
    ("tapback:❤️", "❤️"),
    (json.dumps({"kind": "tapback", "emoji": "👍"}), "👍"),
    (json.dumps({"decision": "REACT:❤️"}), "❤️"),
    (json.dumps({**REPLY, "other": {"kind": "tapback", "emoji": "👍"}}), "👍"),
    (json.dumps({"kind": "tapback", "emoji": "👍", "other": {"decision": "REACT:👍"}}), "👍"),
]

pytestmark = pytest.mark.skipif(
    not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl"
)


def run_desk(tmp_path, surface, output, status=FACT, message=REQUEST):
    if surface == "instagram":
        return run(tmp_path, f"""
            feed('messages', {{ id: 'a', text: {json.dumps(message)} }});
            await wait(1200);
            out.sends = sends(); out.log = log();
        """, answer=output)

    rig = FallbackRig(tmp_path, FM_IMESSAGE_TEST="1", FM_IMESSAGE_TEST_QUIET_MS="30")
    (tmp_path / "bin/omp").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "prompt = sys.stdin.read()\n"
        f"answer = {output!r} if '-e' in sys.argv else json.loads(prompt)['draft']\n"
        "print(json.dumps({'type': 'desk_result', 'drafted': answer, 'tools': {}}) "
        "if os.environ.get('FM_DESK_SERVER_TOOLS') == '1' else answer)\n"
    )
    (tmp_path / "bin/fm-inbox").write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = status ]; then printf '%s' {shlex.quote(status)}; "
        f"else printf '%s\\n' \"$*\" >> {shlex.quote(str(rig.notes))}; fi\n"
    )
    try:
        rig.start()
        if surface == "photon":
            publish_json(rig.fake / "inbound/report.json", {
                "id": "report", "space": "iMessage;-;+10000000000",
                "sender": "+10000000000", "text": message,
            })
        else:
            rig.relay_message("report", message, int(time.time() * 1000))
            assert http(f"http://127.0.0.1:{rig.hook_port}/bluebubbles", "POST",
                        json.dumps({"type": "new-message", "data": {"guid": "report"}}))[0] == 200
        wait_for(lambda: any(
            event.get("route") == "done" and f"{surface}-report" in event.get("ids", [])
            for event in map(json.loads, read_text(rig.state / "routing.jsonl").splitlines())
        ), "the completed routing decision")
        wait_for(lambda: not rig.outbox(), "the completed desk delivery")
        rig.stop()
        if output == LEAKED:
            rig.start()
            time.sleep(0.15)
            rig.stop()
        sent = rig.fake / ("sent" if surface == "photon" else "relay-sent")
        other = rig.fake / ("relay-sent" if surface == "photon" else "sent")
        assert read_text(other) == ""
        return {
            "sends": read_text(sent).splitlines(),
            "notes": read_text(rig.notes),
            "log": [line.split(" ", 2)[2] for line in read_text(rig.state / "desk.log").splitlines()],
        }
    finally:
        rig.close()


@pytest.mark.parametrize("surface", ["instagram", "photon", "bluebubbles"])
@pytest.mark.parametrize("output,action", [
    *REACTIONS,
    (json.dumps({**REPLY, "decision": "SKIP"}), "skip"),
    (json.dumps({**REPLY, "other": {"decision": "handoff"}}), "handoff"),
    (json.dumps({"kind": "tapback", "emoji": "👍", "other": {"decision": "REACT:👎"}}), "skip"),
    (json.dumps({**REPLY, "decision": "not a decision"}), "skip"),
    ("handoff", "handoff"),
    ("This needs another look.\nhandoff", "handoff"),
    ("skip", "skip"),
    ("Nothing is needed.\nskip", "skip"),
    ("Firstmate handles this in this thread. I will defer.", "skip"),
    ("This belongs to Firstmate. I will hand it off.", "skip"),
    ('[optional] reply "skip" to pass', "skip"),
    ("Unrecognized prose.\nMore prose.", "skip"),
    ("Thought.\n" + json.dumps(REPLY), "skip"),
    (json.dumps(REPLY) + "\nMore prose.", "skip"),
    ('Thought.\n{"kind":"reply","answer":"REACT:👍"}', "skip"),
    ("Working...\n" + json.dumps(REPLY), "skip"),
    ('{"kind":"reply","answer":', "skip"),
    (json.dumps([REPLY]), "skip"),
    (json.dumps(REPLY) + json.dumps(REPLY), "skip"),
    (json.dumps({"answer": FACT}), "skip"),
    (json.dumps({"kind": "reply", "answer": "  "}), "skip"),
    (json.dumps({"kind": "reply", "answer": "A thought.\nREACT:👍"}), "skip"),
    (json.dumps({"kind": "reply", "answer": "A thought.\nSKIP"}), "skip"),
    ('"REACT:👍"', "skip"),
    ('REACT:👍"}', "skip"),
    (json.dumps({"kind": "tapback", "emoji": "👍👎"}), "skip"),
    (json.dumps({**REPLY, "kind": "basic"}), "skip"),
])
def test_only_structural_actions_leave_the_desk(tmp_path, surface, output, action):
    message = "thanks!" if surface != "instagram" and action not in ("skip", "handoff") else REQUEST
    result = run_desk(tmp_path, surface, output, message=message)
    if action in ("skip", "handoff"):
        expected = []
    elif surface == "instagram":
        expected = [f"desk|--react {action} --thread T"]
    else:
        reaction = action if surface == "photon" else {"👍": "like", "❤️": "love"}[action]
        expected = [f"react report {reaction}"]
    assert result["sends"] == expected
    assert not any(line in "\n".join(result["log"]) for line in output.splitlines() if len(line) > 30)
    if surface != "instagram":
        if action in ("skip", "handoff"):
            assert result["notes"].count(f"{surface}-report ") == 1
            assert message in result["notes"]
        else:
            assert result["notes"] == ""


@pytest.mark.parametrize("surface", ["photon", "bluebubbles"])
@pytest.mark.parametrize("output", [output for output, _ in REACTIONS])
def test_request_hands_off_despite_a_reaction_directive(tmp_path, surface, output):
    result = run_desk(tmp_path, surface, output)
    assert result["sends"] == []
    assert result["notes"].count(f"{surface}-report ") == 1
    assert REQUEST in result["notes"]


@pytest.mark.parametrize("surface", ["instagram", "photon", "bluebubbles"])
@pytest.mark.parametrize("field", ["kind", "decision"])
@pytest.mark.parametrize("answer", [
    FACT,
    'Firstmate is the supervisor in this thread.',
    '[optional] reply "skip" to pass',
])
def test_reply_json_sends_only_its_answer(tmp_path, surface, field, answer):
    output = json.dumps({
        field: "reply", "answer": answer, "evidence": [{"source": "status", "quote": answer}],
    })
    result = run_desk(tmp_path, surface, output, status=answer, message="What is the status?")
    if surface == "instagram":
        expected = [f"desk|--thread T -- {answer}"]
    else:
        prefix = "send" if surface == "photon" else "iMessage;-;+10000000000"
        expected = [f"{prefix} {answer}"]
    assert result["sends"] == expected
    if surface != "instagram":
        assert result["notes"] == ""
