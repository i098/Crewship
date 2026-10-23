"""Observe responses and typing through the real bridge, with local transport and model processes."""

import json
import os
import shutil
import time

import pytest
from test_imessage import card_url, http, publish_json, wait_for
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


@pytest.mark.parametrize("downtime", [0, 62_000])
def test_pending_handoff_acknowledgement_survives_restart(tmp_path, desk_clock, downtime):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("work", "Fix the release job")
        wait_for(lambda: text(notes), "the durable handoff")
        bridge.terminate()
        bridge.wait(10)
        clock = tmp_path / "clock"
        publish_json(clock, int(clock.read_text()) + downtime)
        bridge = start(2)
        desk_clock(8000)
        wait_for(lambda: text(fake / "sent"), "the restored acknowledgement deadline")
        assert len(text(fake / "sent").splitlines()) == 1
        assert text(notes).count("photon-work ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("plain", [False, True])
@pytest.mark.parametrize("reply", [1, 2])
def test_targeted_answer_does_not_close_another_request(tmp_path, desk_clock, plain, reply):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("release", "Check the release job")
        receive("backup", "Check the backup job")
        answered, unanswered = ("backup", "release") if reply == 1 else ("release", "backup")
        response = f"The {answered} job passed."
        cli("--reply", str(reply), *(["--no-thread"] if plain else []), response)
        wait_for(lambda: response in text(fake / "sent"), "the targeted answer")
        desk_clock(8000)
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 2, "the unanswered request acknowledgement")
        assert f"{unanswered} job" in text(fake / "sent").splitlines()[1]
        confirmations = [event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines()) if event.get("responded")]
        assert confirmations == [[f"photon-{answered}"], [f"photon-{unanswered}"]]
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


def test_chat_acknowledgement_leaves_another_chat_model_running(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    bridge = start(1)
    try:
        receive("release", "Fix the release job")
        desk_clock(4000)
        (fake / "model-hold").touch()
        receive("build", "What is the build status?", space="iMessage;-;+10000000001")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the other chat model")
        desk_clock(2000)
        wait_for(lambda: text(fake / "sent"), "the first chat acknowledgement")
        assert "release job" in text(fake / "sent")
        assert "photon-build " not in text(notes)
        assert "build model-failed" not in text(state / "desk.log")
        (fake / "model-hold").unlink()
        wait_for(lambda: "The build is paused." in text(fake / "sent"), "the other chat answer")
        assert text(fake / "send-targets").splitlines() == [
            "iMessage;-;+10000000000", "iMessage;-;+10000000001",
        ]
        wait_for(lambda: typing_events(fake, text)[-1] is False, "the other chat typing cleanup")
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("source", ["command", "desk"])
def test_typing_trace_keeps_its_request_after_a_new_message(tmp_path, desk_clock, source):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "typing-hold").touch()
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("release", "What is the build status?")
        if source == "command":
            cli("--typing")
        else:
            desk_clock()
        wait_for(lambda: (fake / "typing-waiting").exists(), "the held typing start")
        receive("backup", "Check the backup job")
        (fake / "typing-hold").unlink()
        wait_for(lambda: "typing-stop" in text(state / "desk.log"), "the queued typing cleanup")
        events = [row.split()[1:] for row in text(state / "desk.log").splitlines() if "typing-" in row]
        assert events == [["release", "typing-start"], ["release", "typing-stop"]]
        assert typing_events(fake, text) == [True, False]
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_synchronous_inbox_timeouts_delay_but_do_not_lose_acknowledgements(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "model-hold").touch()
    (tmp_path / "bin/fm-inbox").write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys, time\n"
        "p = pathlib.Path(os.environ['FAKE_DIR'])\n"
        f"notes = pathlib.Path({str(notes)!r})\n"
        "if sys.argv[1] == 'status': print((p / 'status').read_text())\n"
        "else:\n"
        "    key = sys.argv[sys.argv.index('--request-id') + 1]\n"
        "    attempted = p / f'note-{key}'\n"
        "    if not attempted.exists():\n"
        "        attempted.touch()\n"
        "        with (p / 'note-attempts').open('a') as f: f.write(str(time.monotonic()) + '\\n')\n"
        "        time.sleep(120)\n"
        "    with notes.open('a') as f: f.write(' '.join(sys.argv[1:]) + '\\n')\n"
    )
    bridge = start(1)
    try:
        receive("release", "Did the release job finish?")
        receive("backup", "Did the backup job finish?")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the held model")
        started = time.monotonic()
        desk_clock(8000)
        wait_for(lambda: text(fake / "sent"), "the acknowledgement after two inbox timeouts")
        elapsed = time.monotonic() - started
        attempts = [float(row) for row in text(fake / "note-attempts").splitlines()]
        assert len(attempts) == 2
        assert attempts[1] - attempts[0] >= 4.5
        assert elapsed >= 9
        assert text(err).count("the inbox note failed; routing retains the request") >= 2
        assert "backup job" in text(fake / "sent")
        wait_for(lambda: typing_events(fake, text)[-1] is False, "typing cleanup after the timeouts")
        wait_for(lambda: text(notes).count("photon-release ") == text(notes).count("photon-backup ") == 1, "both retained handoffs")
        assert len(text(fake / "sent").splitlines()) == 1
        print(f"Two synchronous inbox timeouts delayed acknowledgement by {elapsed:.3f} seconds.")
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("restart", [False, True])
def test_cancelled_acknowledgement_recovers_after_a_targeted_reply(tmp_path, desk_clock, restart):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "outage").touch()
    bridge = start(1)
    try:
        receive("release", "Check the release job")
        cli("--typing")
        desk_clock(8000)
        wait_for(lambda: "outbox item" in text(err), "the queued acknowledgement during the outage")
        receive("backup", "Check the backup job")
        cli("--reply", "1", "The backup job passed.")
        wait_for(lambda: any(
            "acknowledgement" in event and event["acknowledgement"] is None
            for event in map(json.loads, text(state / "routing.jsonl").splitlines())
        ), "the cancelled acknowledgement ownership")
        assert text(fake / "sent") == ""
        if restart:
            bridge.terminate()
            bridge.wait(10)
            bridge = start(2)
        (fake / "outage").unlink()
        wait_for(lambda: len(text(fake / "sent").splitlines()) >= 2, "the targeted reply and recovered acknowledgement")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the drained outbox")
        expected = [
            "send The backup job passed.",
            "reply release I saved “Check the release job”; no confirmed answer yet.",
        ]
        assert text(fake / "sent").splitlines() == expected
        wait_for(lambda: typing_events(fake, text)[-1] is False, "typing cleanup")
        assert text(notes).count("photon-release ") == text(notes).count("photon-backup ") == 1
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3 if restart else 2)
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == expected
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("app", [False, True])
def test_initial_card_replay_confirms_only_original_requests(tmp_path, desk_clock, monkeypatch, app):
    preload = tmp_path / "card-crash.ts"
    preload.write_text("""
import * as fs from "node:fs";
import { mock } from "bun:test";
const real = { ...fs };
const marker = `${process.env.FAKE_DIR}/card-crashed`;
mock.module("node:fs", () => ({
  ...real,
  renameSync(from, to) {
    real.renameSync(from, to);
    if (String(to).startsWith(`${process.env.STATE_DIRECTORY}/cards/`)
      && JSON.parse(real.readFileSync(to, "utf8")).sent && !real.existsSync(marker)) {
      real.writeFileSync(marker, "");
      process.exit(91);
    }
  },
}));
""")
    monkeypatch.setenv("BUN_OPTIONS", f"{os.environ['BUN_OPTIONS']} --preload={preload}")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("options", "Send the available options")
        cli("--card", json.dumps({
            "kind": "choice", "key": "options", "title": "Available options",
            "options": ["Release", "Backup"], "app": app,
        }))
        assert bridge.wait(10) == 91
        assert len(text(fake / "sent").splitlines()) == 1
        assert not any(event.get("responded") for event in map(json.loads, text(state / "routing.jsonl").splitlines()))
        bridge = start(2)
        wait_for(lambda: any(event.get("responded") for event in map(json.loads, text(state / "routing.jsonl").splitlines())), "the replayed card confirmation")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the replayed card completion")
        before = text(fake / "sent")
        assert len(before.splitlines()) == (2 if app else 1)
        desk_clock(8000)
        assert text(fake / "sent") == before
        receive("backup", "Check the backup job")
        url = card_url(before.splitlines()[0])
        assert http(url + "/pick", "POST", "choice=1")[0] == 303
        if app:
            wait_for(lambda: "Picked B: Backup" in text(fake / "sent"), "the card edit")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the card edit completion")
        assert all(
            "photon-backup" not in event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines())
            if event.get("responded")
        )
        desk_clock(8000)
        expected_count = len(before.splitlines()) + (2 if app else 1)
        wait_for(lambda: len(text(fake / "sent").splitlines()) >= expected_count, "the unanswered followup acknowledgement")
        assert len(text(fake / "sent").splitlines()) == expected_count
        assert text(fake / "sent").splitlines()[-1].endswith("I saved “Check the backup job”; no confirmed answer yet.")
        sent = text(fake / "sent")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        desk_clock(8000)
        assert text(fake / "sent") == sent
    finally:
        bridge.terminate()
        bridge.wait(10)
