"""Observe responses and typing through the real bridge, with local transport and model processes."""

import json
import os
import shutil
import time

import pytest
from test_imessage import card_url, http, png, publish_json, wait_for
from test_imessage_basic import basic_rig
from test_imessage_basic import desk_clock as desk_clock

pytestmark = pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")


def typing_events(fake, text):
    return [json.loads(row)["on"] for row in text(fake / "typing-events").splitlines()]


@pytest.mark.parametrize("failure", ["model-fail", "refusal", "model-hold", "status-fail"])
def test_failed_desk_hands_off_one_burst_without_a_receipt_and_clears_typing(tmp_path, desk_clock, failure):
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
        if failure != "model-hold":
            wait_for(lambda: {
                request for event in map(json.loads, text(state / "routing.jsonl").splitlines())
                if event.get("route") == "done" for request in event["ids"]
            } >= {"photon-lookup", "photon-detail"}, "the completed failure handoff")
        desk_clock(8000)
        wait_for(lambda: typing_events(fake, text)[-1:] == [False], "typing cleanup")
        wait_for(lambda: text(notes).count("photon-lookup ") == text(notes).count("photon-detail ") == 1, "the durable handoff")
        assert text(fake / "sent") == ""
        receive("detail", "Check the release job, not the build job.")
        desk_clock(8000)
        assert text(fake / "sent") == ""
        assert text(notes).count("photon-detail ") == 1
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        desk_clock(8000)
        assert text(fake / "sent") == ""
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
        wait_for(lambda: typing_events(fake, text)[-1:] == [False], "the expired typing indicator")
        assert text(fake / "sent") == ""
        cli("The release job passed.")
        wait_for(lambda: "The release job passed." in text(fake / "sent"), "the later supervisor answer")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == ["send The release job passed."]
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_repeated_unanswered_requests_get_no_generic_receipt(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("release", "Check the release job")
        desk_clock(8000)
        wait_for(lambda: "photon-release " in text(notes), "the first durable handoff")
        receive("backup", "Check the backup job")
        desk_clock(8000)
        wait_for(lambda: "photon-backup " in text(notes), "the second durable handoff")
        assert text(fake / "sent") == ""
        (fake / "model-hold").unlink()
        cli("The release job passed.")
        wait_for(lambda: "The release job passed." in text(fake / "sent"), "the later useful answer")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == ["send The release job passed."]
        assert text(notes).count("photon-release ") == text(notes).count("photon-backup ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("answer", ["desk", "supervisor"])
def test_prompt_answer_is_the_only_response(tmp_path, desk_clock, answer):
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


def test_queued_desk_answer_survives_the_deadline(tmp_path, desk_clock):
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


def test_pure_social_burst_gets_no_timeout_text(tmp_path, desk_clock):
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
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the completed response confirmation")
        sent = text(fake / "sent").splitlines()
        assert len(sent) == 1 and sent[0].endswith(response)
        confirmations = [event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines()) if event.get("responded")]
        assert confirmations == [[f"photon-{answered}"]]
        assert f"photon-{unanswered} " in text(notes)
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


def test_first_chat_deadline_leaves_another_chat_model_running(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    bridge = start(1)
    try:
        receive("release", "Deploy the release job")
        desk_clock(4000)
        (fake / "model-hold").touch()
        receive("build", "What is the build status?", space="iMessage;-;+10000000001")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the other chat model")
        desk_clock(2000)
        assert text(fake / "sent") == ""
        assert "photon-build " not in text(notes)
        assert "build model-failed" not in text(state / "desk.log")
        (fake / "model-hold").unlink()
        wait_for(lambda: "The build is paused." in text(fake / "sent"), "the other chat answer")
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(fake / "send-targets").splitlines() == ["iMessage;-;+10000000001"]
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


def test_synchronous_inbox_timeouts_delay_but_do_not_lose_the_deadline_handoff(tmp_path, desk_clock):
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
        wait_for(lambda: typing_events(fake, text)[-1:] == [False], "typing cleanup after two inbox timeouts")
        elapsed = time.monotonic() - started
        attempts = [float(row) for row in text(fake / "note-attempts").splitlines()]
        assert len(attempts) == 2
        assert attempts[1] - attempts[0] >= 4.5
        assert elapsed >= 9
        assert text(err).count("the inbox note failed; routing retains the request") >= 2
        wait_for(lambda: text(notes).count("photon-release ") == text(notes).count("photon-backup ") == 1, "both retained handoffs")
        assert text(fake / "sent") == ""
        print(f"Two synchronous inbox timeouts delayed the deadline handoff by {elapsed:.3f} seconds.")
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
        acceptance = [row for row in text(state / "desk.log").splitlines() if row.endswith(" transport-accepted")]
        assert len(acceptance) == 1
        bridge = start(2)
        wait_for(lambda: any(event.get("responded") for event in map(json.loads, text(state / "routing.jsonl").splitlines())), "the replayed card confirmation")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the replayed card completion")
        before = text(fake / "sent")
        assert len(before.splitlines()) == (2 if app else 1)
        assert [row for row in text(state / "desk.log").splitlines() if row.endswith(" transport-accepted")] == acceptance
        assert text(state / "desk.log").count("card-update-accepted") == (1 if app else 0)
        assert "options response-confirmed" in text(state / "desk.log")
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
        assert len(text(fake / "sent").splitlines()) == len(before.splitlines()) + (1 if app else 0)
        sent = text(fake / "sent")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        desk_clock(8000)
        assert text(fake / "sent") == sent
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("image", [False, True])
@pytest.mark.parametrize("plain", [False, True])
def test_explicit_reply_confirms_current_edits(tmp_path, desk_clock, image, plain):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("original", "Check the release job")
        for sequence, message in enumerate(["Check the backup job", "Check the deploy job"], 1):
            publish_json(fake / "edits" / f"{sequence}.json", {
                "type": "message.edited", "sequence": sequence, "messageGuid": "original",
                "content": {"text": message}, "chatGuid": "any;-;+10000000000", "isFromMe": False,
            })
            wait_for(lambda: f"photon-original-edit-{sequence} " in text(notes), "the edited request")
        arguments = ["--reply", "1", *(["--no-thread"] if plain else [])]
        expected = []
        if image:
            photo = tmp_path / "reply.png"
            photo.write_bytes(png(2, 2))
            arguments += ["--image", str(photo)]
            expected.append("send [image reply.png image/png 2x2]")
        expected.append("send The deploy job passed.")
        cli(*arguments, "The deploy job passed.")
        wait_for(lambda: len(text(fake / "sent").splitlines()) >= len(expected), "the explicit reply")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the completed reply")
        confirmations = [
            event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines())
            if event.get("responded")
        ]
        assert confirmations == [["photon-original", "photon-original-edit-1", "photon-original-edit-2"]]
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == expected
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == expected
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("output", ["text", "image", "link-card", "app-card"])
@pytest.mark.parametrize("restart", [False, True])
def test_queued_supervisor_response_excludes_later_requests_in_same_millisecond(tmp_path, desk_clock, output, restart):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "send-hold").touch()
    bridge = start(1)
    try:
        receive("release", "Check the release job")
        if output.endswith("card"):
            cli("--card", json.dumps({
                "kind": "text", "key": "release", "title": "Release status",
                "lines": ["The release job passed."], "app": output == "app-card",
            }))
        elif output == "image":
            photo = tmp_path / "release.png"
            photo.write_bytes(png(2, 2))
            cli("--image", str(photo), "The release job passed.")
        else:
            cli("The release job passed.")
        wait_for(lambda: (fake / "send-waiting").exists(), "the queued supervisor response")
        queued = json.loads(next((state / "outbox").glob("*.json")).read_text())
        receive("backup", "Restart the backup job")
        arrivals = [event["received"] for event in map(json.loads, text(state / "routing.jsonl").splitlines()) if "received" in event]
        assert arrivals[0]["at"] == arrivals[1]["at"] == queued["at"]
        if restart:
            bridge.terminate()
            bridge.wait(10)
        (fake / "send-hold").unlink()
        if restart:
            bridge = start(2)
        wait_for(lambda: text(fake / "sent"), "the original response")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the completed original response")
        confirmations = [event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines()) if event.get("responded")]
        assert confirmations == [["photon-release"]]
        before = text(fake / "sent").splitlines()
        assert len(before) == (2 if output == "image" else 1)
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == before
        assert "photon-backup " in text(notes)
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3 if restart else 2)
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == before
    finally:
        (fake / "send-hold").unlink(missing_ok=True)
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("kind", ["voice", "attachment"])
@pytest.mark.parametrize("outcome", ["transcribed", "failed", "unsaved"])
def test_audio_handoff_keeps_the_transcript_and_saved_path_private(tmp_path, desk_clock, monkeypatch, kind, outcome):
    preload = tmp_path / "audio-result.ts"
    preload.write_text("""
import { mock } from "bun:test";
const path = `${process.cwd()}/transcribe.ts`;
const transcription = { ...await import(path) };
mock.module(path, () => ({
  ...transcription,
  async transcribe() {
    if (process.env.FM_TEST_AUDIO === "failed") throw new Error("transcription failed");
    return { text: "private transcript 743821", seconds: 4 };
  },
}));
if (process.env.FM_TEST_AUDIO === "unsaved") {
  const write = Bun.write;
  Bun.write = (path, ...args) => {
    if (String(path).includes("/attachments/")) throw new Error("disk full");
    return write(path, ...args);
  };
}
""")
    monkeypatch.setenv("FM_TEST_AUDIO", outcome)
    monkeypatch.setenv("BUN_OPTIONS", f"{os.environ['BUN_OPTIONS']} --preload={preload}")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    bridge = start(1)
    try:
        receive("audio", "", name="memo.caf", data="synthetic audio", voice=kind == "voice")
        wait_for(lambda: "photon-audio " in text(notes), "the private audio handoff")
        if outcome == "transcribed":
            assert "private transcript 743821" in text(notes)
        elif outcome == "failed":
            assert "transcription failed" in text(notes)
        else:
            assert "could not be saved yet" in text(notes)
        if outcome != "unsaved":
            assert str(state / "attachments") in text(notes)
        cli("--typing")
        desk_clock(8000)
        wait_for(lambda: typing_events(fake, text)[-1:] == [False], "audio typing cleanup")
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("failure", ["write", "fsync"])
@pytest.mark.parametrize("output", ["text", "image", "reaction"])
@pytest.mark.parametrize("restart", [False, True])
def test_accepted_response_survives_journal_failure_without_resending(tmp_path, desk_clock, monkeypatch, failure, output, restart):
    preload = tmp_path / "confirmation-failure.ts"
    preload.write_text("""
import * as fs from "node:fs";
import { mock } from "bun:test";
const real = { ...fs };
const journal = `${process.env.STATE_DIRECTORY}/routing.jsonl`;
const fault = `${process.env.FAKE_DIR}/confirmation-failure`;
const descriptors = new Set();
const responses = new Set();
function fail() {
  const log = `${process.env.STATE_DIRECTORY}/desk.log`;
  const accepted = real.readFileSync(log, "utf8").trim().split("\\n").filter((row) => row.endsWith(" transport-accepted"));
  real.appendFileSync(`${process.env.FAKE_DIR}/confirmation-attempts`, JSON.stringify(accepted) + "\\n");
  throw Object.assign(new Error("injected response journal failure"), { code: "EIO" });
}
mock.module("node:fs", () => ({
  ...real,
  openSync(path, ...args) {
    const fd = real.openSync(path, ...args);
    if (path === journal) descriptors.add(fd);
    return fd;
  },
  writeSync(fd, data, ...args) {
    if (descriptors.has(fd) && typeof data === "string" && JSON.parse(data).responded) {
      if (process.env.FM_TEST_JOURNAL_FAILURE === "write" && real.existsSync(fault)) fail();
      responses.add(fd);
    }
    return real.writeSync(fd, data, ...args);
  },
  fsyncSync(fd) {
    if (responses.has(fd) && process.env.FM_TEST_JOURNAL_FAILURE === "fsync" && real.existsSync(fault)) fail();
    return real.fsyncSync(fd);
  },
  closeSync(fd) {
    descriptors.delete(fd);
    responses.delete(fd);
    return real.closeSync(fd);
  },
}));
""")
    monkeypatch.setenv("FM_TEST_JOURNAL_FAILURE", failure)
    monkeypatch.setenv("BUN_OPTIONS", f"{os.environ['BUN_OPTIONS']} --preload={preload}")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    fault = fake / "confirmation-failure"
    fault.touch()
    if output == "reaction":
        (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️"}')
    bridge = start(1)
    try:
        receive("question", "Thanks!" if output == "reaction" else "What is the build status?")
        if output == "image":
            photo = tmp_path / "reply.png"
            photo.write_bytes(png(2, 2))
            cli("--typing")
            cli("--image", str(photo), "The build is paused.")
        else:
            desk_clock()
        wait_for(lambda: len(text(fake / "confirmation-attempts").splitlines()) >= 2, "repeated response confirmation attempts")
        sent = text(fake / "sent").splitlines()
        assert len(sent) == 1
        acceptance = json.loads(text(fake / "confirmation-attempts").splitlines()[0])
        assert len(acceptance) == 1
        assert acceptance[0].endswith(" question transport-accepted")
        assert all(json.loads(row) == acceptance for row in text(fake / "confirmation-attempts").splitlines())
        pending = json.loads(next((state / "outbox").glob("*.json")).read_text())
        if output == "reaction":
            assert pending["reacted"] is True
        else:
            assert pending["done"] == 1
        wait_for(lambda: typing_events(fake, text)[-1] is False, "typing cleanup before confirmation recovery")
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == sent
        desk_clock(22000)
        if restart:
            bridge.terminate()
            bridge.wait(10)
        fault.unlink()
        if restart:
            bridge = start(2)
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "response confirmation recovery")
        confirmations = [event["ids"] for event in map(json.loads, text(state / "routing.jsonl").splitlines()) if event.get("responded")]
        assert ["photon-question"] in confirmations
        expected = sent + (["send The build is paused."] if output == "image" else [])
        assert text(fake / "sent").splitlines() == expected
        traces = text(state / "desk.log").splitlines()
        accepted = [row for row in traces if row.endswith(" transport-accepted")]
        assert len(accepted) == len(expected)
        assert accepted[0] == acceptance[0]
        assert any(row.endswith(" question response-confirmed") for row in traces)
        desk_clock(8000)
        assert text(fake / "sent").splitlines() == expected
        assert [row for row in text(state / "desk.log").splitlines() if row.endswith(" transport-accepted")] == accepted
    finally:
        fault.unlink(missing_ok=True)
        bridge.terminate()
        bridge.wait(10)
