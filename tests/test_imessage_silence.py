"""Observe responses and typing through the real bridge, with local transport and model processes."""

import json
import shutil

import pytest
from test_imessage import wait_for
from test_imessage_basic import basic_rig
from test_imessage_basic import desk_clock as desk_clock

pytestmark = pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")


def typing_events(fake, text):
    return [json.loads(row)["on"] for row in text(fake / "typing-events").splitlines()]


@pytest.mark.parametrize("failure", ["model-fail", "refusal", "model-hold", "status-fail"])
def test_failed_desk_acknowledges_one_burst_and_clears_typing(tmp_path, desk_clock, failure):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    if failure == "refusal":
        (fake / "answer").write_text("I cannot answer this request.")
    else:
        (fake / failure).touch()
    bridge = start(1)
    try:
        receive("lookup", "Did the release job finish?")
        receive("detail", "Check the release job, not the build job.")
        desk_clock()
        wait_for(lambda: text(notes) or (fake / "model-started").exists(), "the model attempt or handoff")
        desk_clock(8000)
        wait_for(lambda: text(fake / "sent"), "the delayed acknowledgement")
        sent = text(fake / "sent").splitlines()
        assert len(sent) == 1
        assert "release job" in sent[0]
        assert "no confirmed answer yet" in sent[0]
        wait_for(lambda: typing_events(fake, text)[-1] is False, "typing cleanup")
        assert text(notes).count("photon-lookup ") == text(notes).count("photon-detail ") == 1
        receive("detail", "Check the release job, not the build job.")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == sent
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == sent
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_supervisor_typing_is_not_an_answer(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    bridge = start(1)
    try:
        receive("lookup", "Check the release job")
        cli("--typing")
        desk_clock(8000)
        wait_for(lambda: text(fake / "sent"), "the acknowledgement while the supervisor is delayed")
        wait_for(lambda: typing_events(fake, text)[-1] is False, "the expired typing indicator")
        assert "release job" in text(fake / "sent")
        cli("The release job passed.")
        wait_for(lambda: "The release job passed." in text(fake / "sent"), "the later supervisor answer")
        desk_clock(8000)
        assert len(text(fake / "sent").splitlines()) == 2
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("answer", ["desk", "supervisor"])
def test_prompt_answer_prevents_an_acknowledgement(tmp_path, desk_clock, answer):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("lookup", "What is the build status?")
        if answer == "supervisor":
            cli("The build is paused.")
        else:
            desk_clock()
        wait_for(lambda: text(fake / "sent"), "the prompt answer")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_queued_supervisor_answer_is_not_delivery(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "outage").touch()
    bridge = start(1)
    try:
        receive("lookup", "Check the release job")
        cli("--typing")
        assert "queued" in cli("The release job passed.")
        wait_for(lambda: "outbox item" in text(err), "the failed transport attempt")
        desk_clock(8000)
        assert text(fake / "sent") == ""
        assert not any(event.get("responded") for event in map(json.loads, text(state / "routing.jsonl").splitlines()))
        wait_for(lambda: typing_events(fake, text)[-1] is False, "typing cleanup during the outage")
        (fake / "outage").unlink()
        wait_for(lambda: text(fake / "sent"), "the recovered supervisor delivery")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == ["send The release job passed."]
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_queued_desk_answer_survives_the_acknowledgement_deadline(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "outage").touch()
    bridge = start(1)
    try:
        receive("lookup", "What is the build status?")
        desk_clock()
        wait_for(lambda: "outbox item" in text(err), "the queued checked answer")
        desk_clock(8000)
        wait_for(lambda: typing_events(fake, text)[-1] is False, "the bounded typing state")
        assert text(fake / "sent") == ""
        (fake / "outage").unlink()
        wait_for(lambda: text(fake / "sent"), "the original checked answer")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_pure_social_burst_never_gets_a_timeout_acknowledgement(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"skip"}')
    bridge = start(1)
    try:
        receive("thanks", "Thanks!")
        receive("noted", "Got it.")
        desk_clock()
        wait_for(lambda: text(notes), "the conservative handoff")
        desk_clock(8000)
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_pending_handoff_acknowledgement_survives_restart(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("work", "Fix the release job")
        wait_for(lambda: text(notes), "the durable handoff")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        desk_clock(8000)
        wait_for(lambda: text(fake / "sent"), "the restored acknowledgement deadline")
        assert len(text(fake / "sent").splitlines()) == 1
        assert text(notes).count("photon-work ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("plain", [False, True])
def test_targeted_answer_does_not_close_another_request(tmp_path, desk_clock, plain):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("release", "Check the release job")
        receive("backup", "Check the backup job")
        cli("--reply", "2", *(["--no-thread"] if plain else []), "The release job passed.")
        wait_for(lambda: "The release job passed." in text(fake / "sent"), "the targeted answer")
        desk_clock(8000)
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 2, "the unanswered request acknowledgement")
        assert "backup job" in text(fake / "sent").splitlines()[1]
        confirmations = [event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines()) if event.get("responded")]
        assert confirmations == [["photon-release"], ["photon-backup"]]
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("other_chat", ["iMessage;+;group", "iMessage;-;+10000000001"])
def test_another_chat_does_not_cancel_a_direct_acknowledgement(tmp_path, desk_clock, other_chat):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("release", "Fix the release job")
        desk_clock(4000)
        receive("elsewhere", "Fix the backup job", space=other_chat)
        desk_clock(4000)
        wait_for(lambda: text(fake / "sent"), "the original direct-chat acknowledgement")
        assert "release job" in text(fake / "sent").splitlines()[0]
        assert text(fake / "send-targets").splitlines()[0] == "iMessage;-;+10000000000"
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("app", [False, True])
def test_delivered_card_prevents_a_false_missing_answer(tmp_path, desk_clock, app):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("options", "Send the available options")
        cli("--card", json.dumps({
            "kind": "choice", "key": "options", "title": "Available options",
            "options": ["Release", "Backup"], "app": app,
        }))
        wait_for(lambda: text(fake / "sent"), "the delivered card")
        sent = text(fake / "sent")
        desk_clock(8000)
        assert text(fake / "sent") == sent
        assert any(event.get("responded") for event in map(json.loads, text(state / "routing.jsonl").splitlines()))
    finally:
        bridge.terminate()
        bridge.wait(10)
