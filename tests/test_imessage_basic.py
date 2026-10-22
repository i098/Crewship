"""Run the actual bridge with isolated fake Photon and model processes. No live provider calls."""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from test_imessage import (
    ROOT,
    TEST_QUIET_MS,
    FallbackRig,
    bun,
    fake_bridge,
    publish_json,
    read_text,
    wait_for,
)

pytestmark = pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
PAST_QUIET = TEST_QUIET_MS / 1000 + 0.5  # seconds: past the bridge's test-mode quiet period, so a desk turn would have run


@pytest.fixture
def desk_clock(tmp_path, monkeypatch):
    """Control quiet periods, typing refreshes, and reaction ages; keep real retry timers and disk writes."""
    clock = tmp_path / "clock"
    clock.write_text(str(int(time.time() * 1000)))
    preload = tmp_path / "clock.ts"
    preload.write_text("""
import { existsSync, readFileSync, writeFileSync } from "node:fs";
if (process.env.STATE_DIRECTORY) {
  const spawn = Bun.spawn;
  Bun.spawn = (cmd, ...args) => {
    if (cmd[0] === "omp" && existsSync(`${process.env.FAKE_DIR}/spawn-error`)) throw new Error("test spawn failure");
    return spawn(cmd, ...args);
  };
  const file = process.env.FM_TEST_CLOCK;
  Date.now = () => Number(readFileSync(file, "utf8"));
  Math.random = () => 0.5;
  const timers = new Map();
  const schedule = globalThis.setTimeout;
  const cancel = globalThis.clearTimeout;
  globalThis.setTimeout = (fn, ms, ...args) => {
    if (![process.env.FM_IMESSAGE_TEST_QUIET_MS, process.env.FM_IMESSAGE_TEST_MAX_WAIT_MS]
        .some((value) => ms === Number(value))) return schedule(fn, ms, ...args);
    const timer = { at: Date.now() + ms, run: () => fn(...args) };
    timers.set(timer, timer);
    return timer;
  };
  globalThis.clearTimeout = (timer) => { if (!timers.delete(timer)) cancel(timer); };
  const interval = globalThis.setInterval;
  const clearInterval = globalThis.clearInterval;
  globalThis.setInterval = (fn, ms, ...args) => {
    if (ms !== 4000) return interval(fn, ms, ...args);
    const timer = { at: Date.now() + ms, repeat: ms, run: () => fn(...args) };
    timers.set(timer, timer);
    return timer;
  };
  globalThis.clearInterval = (timer) => { if (!timers.delete(timer)) clearInterval(timer); };
  let seen;
  setInterval(() => {
    const now = Date.now();
    if (seen === now) return;
    seen = now;
    for (const [key, timer] of timers) if (timer.at <= now) {
      if (timer.repeat) timer.at = now + timer.repeat;
      else timers.delete(key);
      timer.run();
    }
    writeFileSync(`${file}-seen`, String(now));
  }, 5).unref();
}
""")
    monkeypatch.setenv("FM_TEST_CLOCK", str(clock))
    monkeypatch.setenv("BUN_OPTIONS", f"--preload={preload}")

    def advance(ms=TEST_QUIET_MS):
        now = int(clock.read_text()) + ms
        publish_json(clock, now)
        wait_for(lambda: read_text(tmp_path / "clock-seen") == str(now), "the controlled clock tick")

    return advance


def basic_rig(tmp_path, test_mode=True):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path, test_mode)
    (fake / "status").write_text("The build is paused.")
    answer = {"kind": "reply", "answer": "The build is paused.", "evidence": [{"source": "status", "quote": "The build is paused."}]}
    (fake / "answer").write_text(json.dumps(answer))
    (tmp_path / "bin/omp").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, signal, sys, time\n"
        "p = pathlib.Path(os.environ['FAKE_DIR'])\n"
        "prompt = sys.stdin.read()\n"
        "voice = '-e' not in sys.argv\n"
        "if voice and (p / 'voice-ignore-kill').exists(): signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "if voice: (p / 'voice-pid').write_text(str(os.getpid()))\n"
        "with (p / ('voice-calls' if voice else 'model-calls')).open('a') as f: "
        "f.write(json.dumps({'args': sys.argv, 'prompt': prompt}) + '\\n')\n"
        "(p / ('voice-started' if voice else 'model-started')).touch()\n"
        "while (p / ('voice-hold' if voice else 'model-hold')).exists(): time.sleep(0.02)\n"
        "print((p / 'voice-answer').read_text() if voice and (p / 'voice-answer').exists() else "
        "json.loads(prompt)['draft'] if voice else (p / 'answer').read_text())\n"
        "sys.exit(1 if (p / ('voice-fail' if voice else 'model-fail')).exists() else 0)\n"
    )
    (tmp_path / "bin/fm-inbox").write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys, time\n"
        "p = pathlib.Path(os.environ['FAKE_DIR'])\n"
        f"notes = pathlib.Path({str(notes)!r})\n"
        "if sys.argv[1] == 'status':\n"
        "    if (p / 'status-fail').exists(): sys.exit(1)\n"
        "    (p / 'status-started').touch()\n"
        "    status = (p / 'status').read_text()\n"
        "    with (p / 'status-calls').open('a') as f: f.write(status + '\\n')\n"
        "    while (p / 'status-hold').exists(): time.sleep(0.02)\n"
        "    print(status)\n"
        "else:\n"
        "    if (p / 'inbox-fail').exists(): sys.exit(1)\n"
        "    key = sys.argv[sys.argv.index('--request-id') + 1]\n"
        "    old = notes.read_text() if notes.exists() else ''\n"
        "    if key + ' ' not in old:\n"
        "        with notes.open('a') as f: f.write(' '.join(sys.argv[1:]) + '\\n')\n"
    )

    def receive(mid, message, **fields):
        read_count = text(fake / "read").splitlines().count(mid)
        publish_json(fake / "inbound" / f"{mid}.json", {
            "id": mid, "space": "iMessage;-;+10000000000", "sender": "+10000000000", "text": message, **fields,
        })
        wait_for(lambda: f'"photon-{mid}"' in text(state / "routing.jsonl"), "durable inbound ownership")
        if os.environ.get("FM_TEST_CLOCK"):
            if read_count:
                wait_for(lambda: not (fake / "inbound" / f"{mid}.json").exists(), "the duplicate input")
            else:
                wait_for(lambda: text(fake / "read").splitlines().count(mid) > read_count, "the completed inbound handling")

    def records():
        return [json.loads(line) for p in (state / "memory/main").glob("*.jsonl") for line in p.read_text().splitlines()]

    return fake, state, notes, err, start, receive, cli, text, records


@pytest.mark.parametrize("rewrite,expected", [
    ("there are 1,200 jobs\n\ndetails: https://example.test/jobs/12", "there are 1,200 jobs\nsend details: https://example.test/jobs/12"),
    ("There are 1201 jobs. Details: https://example.test/jobs/12", None),
    ("There are 1200 jobs. Details: https://example.test/jobs/13", None),
    ("", None),
])
def test_voice_keeps_numbers_and_links_or_sends_original(tmp_path, desk_clock, rewrite, expected):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    draft = "There are 1200 jobs. Details: https://example.test/jobs/12"
    (fake / "status").write_text(draft)
    (fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": draft, "evidence": [{"source": "status", "quote": draft}],
    }))
    (fake / "voice-answer").write_text(rewrite)
    bridge = start(1)
    try:
        receive("question", "How many jobs are there?")
        desk_clock()
        wait_for(lambda: (fake / "voice-started").exists(), "the voice pass")
        wait_for(lambda: '"route":"done"' in text(state / "routing.jsonl"), "the saved route")
        wait_for(lambda: text(fake / "sent").count("send ") == (2 if expected else 1), "the voice bubbles")
        assert text(fake / "sent") == f"send {expected or draft}\n"
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("draft,rewrite", [
    ("The build is not ready.", "the build is ready"),
    ("The build is paused.", "I fixed the build."),
    ("The build is paused.", "The build is running."),
    ("Firstmate is not the desk.", "The desk is not Firstmate."),
    ("The fee is $12.", "The fee is 12."),
])
def test_voice_cannot_change_checked_claims(tmp_path, desk_clock, draft, rewrite):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "status").write_text(draft)
    (fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": draft, "evidence": [{"source": "status", "quote": draft}],
    }))
    (fake / "voice-answer").write_text(rewrite)
    bridge = start(1)
    try:
        receive("question", "What does the status say?")
        desk_clock()
        wait_for(lambda: text(fake / "sent"), "the checked draft after unsafe rewriting")
        assert text(fake / "sent") == f"send {draft}\n"
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("failure", ["voice-hold", "voice-fail"])
def test_voice_failure_sends_original(tmp_path, desk_clock, monkeypatch, failure):
    monkeypatch.setenv("FM_IMESSAGE_TEST_VOICE_MS", "100")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / failure).touch()
    bridge = start(1)
    try:
        receive("question", "What is the build status?")
        desk_clock()
        wait_for(lambda: text(fake / "sent"), "the original after voice failure")
        assert text(fake / "sent") == "send The build is paused.\n"
        assert (fake / "voice-started").exists()
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("reaction_text", [None, "nice!"])
def test_reaction_has_no_voice_pass(tmp_path, desk_clock, reaction_text):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    answer = {"kind": "tapback", "emoji": "❤️"}
    if reaction_text:
        answer["text"] = reaction_text
    (fake / "answer").write_text(json.dumps(answer))
    bridge = start(1)
    try:
        receive("thanks", "thanks!")
        desk_clock()
        expected = f"send {reaction_text}\n" if reaction_text else ""
        expected += "react thanks ❤️\n"
        wait_for(lambda: text(fake / "sent") == expected, "the social reaction")
        assert not (fake / "voice-started").exists()
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("activity", ["send", "react", "typing", "new-text"])
def test_voice_stands_down_before_delivery(tmp_path, desk_clock, activity):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "voice-hold").touch()
    bridge = start(1)
    try:
        receive("question", "What is the build status?")
        desk_clock()
        wait_for(lambda: (fake / "voice-started").exists(), "the held voice pass")
        if activity == "new-text":
            receive("correction", "Deploy it instead")
            desk_clock()
        elif activity == "send":
            cli("Supervisor answer")
        else:
            cli(f"--{activity}", *(["❤️"] if activity == "react" else []))
        wait_for(lambda: "photon-question " in text(notes), "the cancelled voice handoff")
        (fake / "voice-hold").unlink()
        assert "The build is paused." not in text(fake / "sent")
        if activity == "new-text":
            wait_for(lambda: "photon-correction " in text(notes), "the replacement handoff")
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_cancelled_voice_cleanup_keeps_the_replacement_draft(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "voice-hold").touch()
    (fake / "voice-ignore-kill").touch()
    bridge = start(1)
    try:
        receive("question", "What is the build status?")
        desk_clock()
        wait_for(lambda: (fake / "voice-started").exists(), "the held voice pass")
        old_pid = int(text(fake / "voice-pid"))
        (fake / "model-hold").touch()
        (fake / "model-started").unlink()
        receive("correction", "What is the current build status?")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the replacement classification")
        (fake / "voice-hold").unlink()
        wait_for(lambda: not os.path.exists(f"/proc/{old_pid}"), "the old voice process exit")
        desk_clock(0)
        (fake / "model-hold").unlink()
        wait_for(lambda: text(fake / "sent"), "the replacement answer")
        assert text(fake / "sent") == "send The build is paused.\n"
        assert text(notes) == ""
    finally:
        (fake / "voice-hold").unlink(missing_ok=True)
        bridge.terminate()
        bridge.wait(10)


def prepare_typing_exit(fake, exit_path):
    (fake / "typing-down").unlink()
    (fake / "model-hold").touch()
    if exit_path in ("spawn-error", "cancel-status"):
        (fake / "status-hold").touch()
    if exit_path == "reaction":
        (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️"}')
    elif exit_path in ("skip", "handoff"):
        (fake / "answer").write_text(json.dumps({"kind": exit_path}))
    elif exit_path == "error":
        (fake / "model-fail").touch()


def end_typing_turn(fake, exit_path, receive, cli, bridge):
    if exit_path in ("cancel", "cancel-status"):
        receive("new-chat", "Deploy the build", space="iMessage;-;+10000000001")
    elif exit_path == "spawn-error":
        (fake / "spawn-error").touch()
        (fake / "status-hold").unlink()
    elif exit_path == "send":
        cli("The build is paused.")
    elif exit_path in ("react", "typing"):
        cli(f"--{exit_path}", *(["❤️"] if exit_path == "react" else []))
    elif exit_path == "shutdown":
        bridge.terminate()
        bridge.wait(10)
    else:
        (fake / "model-hold").unlink()


@pytest.mark.parametrize("exit_path", [
    "answer", "reaction", "skip", "handoff", "error", "spawn-error", "cancel", "cancel-status",
    "send", "react", "typing", "shutdown",
])
def test_desk_refreshes_typing_only_until_its_turn_ends(tmp_path, desk_clock, exit_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    prepare_typing_exit(fake, exit_path)

    def events():
        return [json.loads(row) for row in text(fake / "typing-events").splitlines()]

    bridge = start(1)
    try:
        receive("question", "thanks!" if exit_path == "reaction" else "What is the build status?")
        desk_clock()
        if exit_path in ("spawn-error", "cancel-status"):
            wait_for(lambda: events(), "typing while status is pending")
        else:
            wait_for(lambda: (fake / "model-started").exists(), "the held desk call")
        assert events() == [{"chat": "iMessage;-;+10000000000", "on": True}]
        desk_clock(4000)
        assert events() == [{"chat": "iMessage;-;+10000000000", "on": True}] * 2
        end_typing_turn(fake, exit_path, receive, cli, bridge)
        wait_for(lambda: any(not row["on"] for row in events()), "typing stopped")
        if exit_path == "typing":
            wait_for(lambda: events()[-1]["on"], "supervisor typing after desk cleanup")
        if exit_path in ("answer", "reaction"):
            wait_for(lambda: text(fake / "sent"), "the desk response")
        elif exit_path in ("skip", "handoff", "error", "spawn-error"):
            wait_for(lambda: "photon-question " in text(notes), "the desk handoff")
        if exit_path != "shutdown":
            desk_clock(0)
            before = events()
            desk_clock(8000)
            assert events() == before
        assert all(row["chat"] == "iMessage;-;+10000000000" for row in events())
        assert events()[-1]["on"] == (exit_path == "typing")
    finally:
        if bridge.poll() is None:
            bridge.terminate()
            bridge.wait(10)


def test_desk_does_not_type_in_another_chat_when_the_burst_spans_chats(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    answer = json.loads((fake / "answer").read_text())
    (fake / "answer").write_text(json.dumps({**answer, "target": 1}))
    (fake / "typing-down").unlink()
    bridge = start(1)
    try:
        receive("question", "What is the build status?")
        receive("elsewhere", "And now?", space="iMessage;-;+10000000001")
        desk_clock()
        wait_for(lambda: text(fake / "sent"), "the selected chat response")
        assert text(fake / "send-targets") == "iMessage;-;+10000000000\n"
        assert text(fake / "typing-events") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("exit_path", ["answer", "cancel", "typing", "shutdown"])
def test_desk_stops_typing_after_an_inflight_refresh(tmp_path, desk_clock, exit_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "model-hold").touch()

    def events():
        return [json.loads(row)["on"] for row in text(fake / "typing-events").splitlines()]

    bridge = start(1)
    try:
        receive("question", "What is the build status?")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the held model call")
        assert events() == [True]
        (fake / "typing-hold").touch()
        desk_clock(4000)
        wait_for(lambda: (fake / "typing-waiting").exists(), "the pending typing refresh")
        desk_clock(4000)
        if exit_path == "answer":
            (fake / "model-hold").unlink()
            wait_for(lambda: text(fake / "sent"), "the response without waiting for typing")
        elif exit_path == "cancel":
            receive("new-chat", "Deploy the build", space="iMessage;-;+10000000001")
        elif exit_path == "typing":
            cli("--typing")
        else:
            bridge.terminate()
        (fake / "typing-hold").unlink()
        if exit_path == "shutdown":
            bridge.wait(10)
        expected = [True, True, False] + ([True] if exit_path == "typing" else [])
        wait_for(lambda: events() == expected, "the ordered typing state after the pending refresh")
        if exit_path != "shutdown":
            desk_clock(8000)
            assert events() == expected
    finally:
        (fake / "typing-hold").unlink(missing_ok=True)
        if bridge.poll() is None:
            bridge.terminate()
            bridge.wait(10)


@pytest.mark.parametrize("response", ["answer", "reaction"])
@pytest.mark.parametrize("waiting", ["lookup", "queued", "retry"])
def test_desk_keeps_typing_until_delivery(tmp_path, desk_clock, response, waiting):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    if response == "reaction":
        (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️"}')
    hold = fake / {"lookup": "lookup-hold", "queued": "send-hold", "retry": "outage"}[waiting]
    hold.touch()
    bridge = start(1)
    try:
        if waiting == "queued":
            hold.unlink()
            receive("previous", "Deploy the build")
            cli("An earlier response")
            wait_for(lambda: text(fake / "sent"), "the previous completed response")
            hold.touch()
            cli("A queued response")
            wait_for(lambda: (fake / "send-waiting").exists(), "the blocked older response")
        receive("question", "thanks!" if response == "reaction" else "What is the build status?")
        desk_clock()
        wait_for(lambda: '"route":"desk"' in text(state / "routing.jsonl"), "the queued desk response")
        if waiting == "lookup":
            wait_for(lambda: (fake / "lookup-waiting").exists(), "the slow delivery lookup")
        elif waiting == "retry":
            wait_for(lambda: "failed (try" in text(err), "the delivery retry")
        desk_clock(4000)
        def events():
            return [json.loads(row) for row in text(fake / "typing-events").splitlines()]

        expected = ([False, False] if waiting == "queued" else []) + [True, True]
        assert [row["on"] for row in events()] == expected
        hold.unlink()
        wait_for(lambda: events()[-1]["on"] is False, "typing stopped after delivery")
        deliveries = [json.loads(row) for row in text(fake / "delivery-events").splitlines()]
        delivered = deliveries[-1]
        expected_response = "react question ❤️" if response == "reaction" else "The build is paused."
        assert delivered["line"].endswith(expected_response)
        assert delivered["chat"] == "iMessage;-;+10000000000"
        assert delivered["typing"] is True
        before = events()
        desk_clock(8000)
        assert events() == before
    finally:
        hold.unlink(missing_ok=True)
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("threaded", [False, True])
@pytest.mark.parametrize("code", ["EIO", "ENOSPC"])
def test_desk_stops_typing_when_accepted_reply_progress_cannot_be_saved(
    tmp_path, desk_clock, monkeypatch, threaded, code,
):
    preload = tmp_path / "progress-failure.ts"
    preload.write_text("""
import * as fs from "node:fs";
import { mock } from "bun:test";
const real = { ...fs };
const fault = `${process.env.FAKE_DIR}/progress-failure`;
mock.module("node:fs", () => ({
  ...real,
  writeSync(fd, data, ...args) {
    const item = typeof data === "string" && data.startsWith("{") ? JSON.parse(data) : undefined;
    if (item?.kind === "desk" && item.done === 1 && real.existsSync(fault)) {
      throw Object.assign(new Error("injected delivery progress failure"), {
        code: real.readFileSync(fault, "utf8"),
      });
    }
    return real.writeSync(fd, data, ...args);
  },
}));
""")
    monkeypatch.setenv("BUN_OPTIONS", f"{os.environ['BUN_OPTIONS']} --preload={preload}")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "model-hold").touch()
    fault = fake / "progress-failure"
    fault.write_text(code)

    def events():
        return [json.loads(row) for row in text(fake / "typing-events").splitlines()]

    bridge = start(1)
    try:
        receive("question", "What is the build status?")
        if threaded:
            next(fake.glob("last-*")).write_text("an intervening message")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the held desk model")
        (fake / "model-hold").unlink()
        wait_for(lambda: "injected delivery progress failure" in text(err), "the progress write failure")
        delivered = [json.loads(row) for row in text(fake / "delivery-events").splitlines()][0]
        assert delivered["line"] == (
            "reply question The build is paused." if threaded else "send The build is paused."
        )
        assert delivered["typing"] is True
        pending = json.loads(next((state / "outbox").glob("*.json")).read_text())
        assert pending["requestId"] == "photon-question"
        assert pending.get("done", 0) == 0
        assert not list((state / "outbox-done").glob("*.json"))
        desk_clock(8000)
        assert events() == [
            {"chat": "iMessage;-;+10000000000", "on": True},
            {"chat": "iMessage;-;+10000000000", "on": False},
        ]
        fault.unlink()
        wait_for(lambda: list((state / "outbox-done").glob("*.json")), "the recovered delivery receipt")
        completed = json.loads(next((state / "outbox-done").glob("*.json")).read_text())
        assert completed["requestId"] == pending["requestId"]
        assert completed["guid"] == pending["guid"]
        assert completed["done"] == 1
        assert not list((state / "outbox").glob("*.json"))
        desk_clock(8000)
        assert events()[-1]["on"] is False
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("response,ending", [
    ("answer", "dead"), ("reaction", "dead"), ("reaction", "expired"),
    ("answer", "cancel"), ("reaction", "cancel"),
    ("answer", "shutdown"), ("reaction", "shutdown"),
])
def test_undelivered_desk_response_stops_typing(tmp_path, desk_clock, response, ending):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "typing-down").unlink()
    (fake / "outage").touch()
    if response == "reaction":
        (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️"}')
    bridge = start(1)
    try:
        receive("question", "thanks!" if response == "reaction" else "What is the build status?")
        desk_clock()
        wait_for(lambda: "failed (try" in text(err), "the undelivered desk response")
        desk_clock(4000)
        if ending == "dead":
            (fake / ("react-refused" if response == "reaction" else "send-refused")).touch()
            (fake / "outage").unlink()
        elif ending == "expired":
            desk_clock(121_000)
        elif ending == "cancel":
            receive("new-chat", "Deploy the build", space="iMessage;-;+10000000001")
        else:
            bridge.terminate()
            bridge.wait(10)
        def events():
            return [json.loads(row) for row in text(fake / "typing-events").splitlines()]

        wait_for(lambda: events()[-1]["on"] is False, "typing stopped without delivery")
        assert text(fake / "sent") == ""
        assert all(row["chat"] == "iMessage;-;+10000000000" for row in events())
        if ending in ("dead", "expired"):
            wait_for(lambda: list((state / "outbox-dead").glob("*.json")), "the discarded response")
        if ending != "shutdown":
            before = events()
            desk_clock(8000)
            assert events() == before
    finally:
        if bridge.poll() is None:
            bridge.terminate()
            bridge.wait(10)


def transport_desk_rig(tmp_path, **env):
    rig = FallbackRig(tmp_path, FM_IMESSAGE_TEST="1", FM_IMESSAGE_TEST_QUIET_MS=str(TEST_QUIET_MS), **env)
    (tmp_path / "bin/omp").write_text('#!/bin/sh\ncat >/dev/null\ncat "$FAKE_DIR/answer"\n')
    (tmp_path / "bin/fm-inbox").write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        f"notes = pathlib.Path({str(rig.notes)!r})\n"
        "if sys.argv[1] == 'status': print('The build is paused.')\n"
        "else:\n"
        "    key = sys.argv[sys.argv.index('--request-id') + 1]\n"
        "    old = notes.read_text() if notes.exists() else ''\n"
        "    if key + ' ' not in old:\n"
        "        with notes.open('a') as f: f.write(' '.join(sys.argv[1:]) + '\\n')\n"
    )
    (rig.fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": "The build is paused.",
        "evidence": [{"source": "status", "quote": "The build is paused."}],
    }))

    def receive(transport, mid, message, space="iMessage;-;+10000000000"):
        if transport == "photon":
            publish_json(rig.fake / "inbound" / f"{mid}.json", {
                "id": mid, "space": space, "sender": "+10000000000", "text": message,
            })
        else:
            rig.relay_message(mid, message, int((tmp_path / "clock").read_text()), chats=[{"guid": space}])
            subprocess.run([
                "curl", "-sS", "-d", json.dumps({"type": "new-message", "data": {"guid": mid}}),
                f"http://127.0.0.1:{rig.hook_port}/bluebubbles",
            ], check=True, capture_output=True)
        wait_for(lambda: f'"requestId":"{transport}-{mid}"' in read_text(rig.state / "routing.jsonl"),
                 "the durable request")
        latest = "latest" if transport == "photon" else "latest-bluebubbles"
        wait_for(lambda: f"\n{mid}\n" in read_text(rig.state / latest), "the completed inbound handling")

    return rig, receive


@pytest.mark.parametrize("transport,failure", [
    ("photon", "definite"), ("photon", "uncertain"),
    ("bluebubbles", "definite"), ("bluebubbles", "uncertain"),
])
def test_desk_answer_stays_in_its_chat_during_failure_and_restart(tmp_path, desk_clock, transport, failure):
    rig, receive = transport_desk_rig(tmp_path)
    other = "bluebubbles" if transport == "photon" else "photon"
    try:
        rig.start()
        receive(other, "group", "Group update", "iMessage;+;group-test")
        wait_for(lambda: f"{other}-group " in read_text(rig.notes), "the group handoff")
        if transport == "photon":
            if failure == "definite":
                rig.photon_down(True)
            else:
                (rig.fake / "send-unsure").touch()
        else:
            rig.relay_mode("last-down" if failure == "definite" else "send-down")
        receive(transport, "private", "What is the build status?")
        desk_clock()
        wait_for(lambda: rig.outbox() and "outbox item 1 failed" in read_text(rig.err), "the retained answer")
        assert read_text(rig.fake / "sent") == read_text(rig.fake / "relay-sent") == ""
        assert f"{transport}-private " not in read_text(rig.notes)
        receive(transport, "new-group", "Another group update", "iMessage;+;another-group")
        rig.stop()
        if transport == "photon":
            rig.photon_down(False)
            (rig.fake / "send-unsure").unlink(missing_ok=True)
        else:
            rig.relay_mode("")
        rig.start()
        wait_for(lambda: list((rig.state / "outbox-done").glob("*.json")), "the recovered desk answer")
        assert f"{transport}-private " not in read_text(rig.notes)
        if transport == "photon":
            assert read_text(rig.fake / "sent").splitlines() == ["send The build is paused."]
            assert read_text(rig.fake / "send-targets").splitlines() == ["iMessage;-;+10000000000"]
            assert read_text(rig.fake / "relay-sent") == ""
        else:
            assert read_text(rig.fake / "relay-sent").splitlines() == ["iMessage;-;+10000000000 The build is paused."]
            assert read_text(rig.fake / "sent") == ""
    finally:
        rig.close()


def test_unsupported_bluebubbles_social_reaction_hands_off_without_false_memory(tmp_path, desk_clock):
    rig, receive = transport_desk_rig(tmp_path)
    (rig.fake / "no-private-api").touch()
    (rig.fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    try:
        rig.start()
        receive("bluebubbles", "thanks", "thanks!")
        desk_clock()
        wait_for(lambda: "bluebubbles-thanks " in read_text(rig.notes), "the unsupported-reaction handoff")
        assert read_text(rig.fake / "relay-sent") == ""
        records = [json.loads(line) for p in (rig.state / "memory/main").glob("*.jsonl")
                   for line in p.read_text().splitlines()]
        assert not any(r["kind"] == "desk" for r in records)
        dead = [json.loads(p.read_text()) for p in (rig.state / "outbox-dead").glob("*.json")]
        assert len(dead) == 1 and not dead[0].get("maybe")
        rig.stop()
        rig.start()
        desk_clock()
        assert read_text(rig.notes).count("bluebubbles-thanks ") == 1
        assert read_text(rig.fake / "relay-sent") == ""
    finally:
        rig.close()


@pytest.mark.parametrize("transport", ["photon", "bluebubbles"])
def test_uncertain_social_reaction_survives_refusal_and_dead_letter_restart(tmp_path, desk_clock, transport):
    rig, receive = transport_desk_rig(tmp_path, FM_IMESSAGE_REACT_MAX_MS="2000")
    (rig.fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    if transport == "photon":
        (rig.fake / "react-unsure").touch()
    else:
        rig.relay_mode("react-garbled")
    try:
        rig.start()
        receive(transport, "thanks", "thanks!")
        desk_clock()
        sent = rig.fake / ("sent" if transport == "photon" else "relay-sent")
        wait_for(lambda: rig.outbox() and rig.outbox()[0].get("maybe") and "react thanks" in read_text(sent),
                 "the durable uncertain reaction")
        assert rig.outbox()[0]["maybe"] == {transport: "iMessage;-;+10000000000"}
        rig.stop()
        if transport == "photon":
            (rig.fake / "react-refused").touch()
        else:
            rig.relay_mode("react-refused")
        rig.start()
        wait_for(lambda: list((rig.state / "outbox-dead").glob("*.json")), "the retained dead letter")
        dead = json.loads(next((rig.state / "outbox-dead").glob("*.json")).read_text())
        assert dead["maybe"] == {transport: "iMessage;-;+10000000000"}
        assert f"{transport}-thanks " not in read_text(rig.notes)
        delivered = read_text(rig.fake / ("sent" if transport == "photon" else "relay-sent"))
        assert f"react thanks {'👍' if transport == 'photon' else 'like'}" in delivered
        rig.stop()
        rig.start()
        desk_clock()
        assert f"{transport}-thanks " not in read_text(rig.notes)
    finally:
        rig.close()


def test_uncertain_social_reaction_expires_without_a_handoff(tmp_path, monkeypatch, desk_clock):
    monkeypatch.setenv("FM_IMESSAGE_REACT_MAX_MS", "200")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    (fake / "react-unsure").touch()
    bridge = start(1)
    try:
        receive("thanks", "thanks!")
        desk_clock()
        wait_for(lambda: "reaction timed out" in text(err), "the uncertain mutation")
        desk_clock(201)
        wait_for(lambda: list((state / "outbox-dead").glob("*.json")), "the expired uncertain reaction")
        dead = json.loads(next((state / "outbox-dead").glob("*.json")).read_text())
        assert dead["maybe"] == {"photon": "iMessage;-;+10000000000"}
        assert "react thanks 👍" in text(fake / "sent")
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("failure", ["missing", "timeout"])
@pytest.mark.parametrize("prior_uncertain", [False, True])
def test_photon_reaction_lookup_failure_preserves_only_prior_uncertainty(tmp_path, monkeypatch, desk_clock, failure, prior_uncertain):
    monkeypatch.setenv("FM_IMESSAGE_REACT_MAX_MS", "2000")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    failure_flag = fake / f"lookup-{failure}"
    (fake / "react-unsure" if prior_uncertain else failure_flag).touch()
    bridge = start(1)
    try:
        receive("thanks", "thanks!")
        desk_clock()
        if prior_uncertain:
            wait_for(lambda: "reaction timed out" in text(err), "the uncertain reaction")
            failure_flag.touch()
        error = "message thanks not found" if failure == "missing" else "lookup timed out"
        wait_for(lambda: error in text(err), "the failed read-only lookup")
        bridge.terminate()
        bridge.wait(10)
        if failure == "timeout":
            queued = json.loads(next((state / "outbox").glob("*.json")).read_text())
            assert bool(queued.get("maybe")) == prior_uncertain
        bridge = start(2)
        desk_clock(2001)
        wait_for(lambda: list((state / "outbox-dead").glob("*.json")), "the failed-reaction receipt")
        dead = json.loads(next((state / "outbox-dead").glob("*.json")).read_text())
        assert bool(dead.get("maybe")) == prior_uncertain
        if prior_uncertain:
            assert text(notes) == ""
            assert "react thanks 👍" in text(fake / "sent")
        else:
            wait_for(lambda: "photon-thanks " in text(notes), "the unsent-reaction handoff")
            assert text(fake / "sent") == ""
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        desk_clock()
        assert text(notes).count("photon-thanks ") == int(not prior_uncertain)
        assert not any(r["kind"] == "desk" for r in records())
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("prior_uncertain", [False, True])
def test_photon_reaction_crash_during_lookup_preserves_only_prior_uncertainty(tmp_path, desk_clock, prior_uncertain):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    (fake / ("react-unsure" if prior_uncertain else "lookup-stop")).touch()
    bridge = start(1)
    try:
        receive("lost", "thanks!")
        desk_clock()
        if prior_uncertain:
            wait_for(lambda: "reaction timed out" in text(err), "the uncertain reaction")
            (fake / "lookup-stop").touch()
        wait_for(lambda: (fake / "lookup-ready").exists(), "the held Photon lookup")
        bridge.kill()
        bridge.wait(10)
        queued = json.loads(next((state / "outbox").glob("*.json")).read_text())
        assert bool(queued.get("maybe")) == prior_uncertain
        (fake / "lookup-missing").touch()
        bridge = start(2)
        wait_for(lambda: list((state / "outbox-dead").glob("*.json")), "the failed-reaction receipt")
        if prior_uncertain:
            assert text(notes) == ""
            assert "react lost 👍" in text(fake / "sent")
        else:
            wait_for(lambda: "photon-lost " in text(notes), "the unsent-reaction handoff")
            assert text(notes).count("photon-lost ") == 1
            assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("prior_uncertain", [False, True])
def test_bluebubbles_reaction_crash_during_health_check_preserves_only_prior_uncertainty(tmp_path, desk_clock, prior_uncertain):
    rig, receive = transport_desk_rig(tmp_path)
    (rig.fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    (tmp_path / "bin/omp").write_text(
        '#!/bin/sh\ncat >/dev/null\n'
        'while [ -e "$FAKE_DIR/model-hold" ]; do sleep 0.02; done\n'
        'cat "$FAKE_DIR/answer"\n'
    )
    if prior_uncertain:
        rig.relay_mode("react-garbled")
    else:
        (rig.fake / "model-hold").touch()
    try:
        rig.start()
        receive("bluebubbles", "thanks", "thanks!")
        desk_clock()
        if prior_uncertain:
            wait_for(lambda: rig.outbox() and rig.outbox()[0].get("maybe")
                     and "react thanks like" in read_text(rig.fake / "relay-sent"), "the uncertain reaction")
        rig.stop()
        (rig.fake / "model-hold").unlink(missing_ok=True)
        rig.relay_mode("hold-health")
        rig.start()
        desk_clock()
        wait_for(lambda: (rig.fake / "health-waiting").exists()
                 and '"route":"done"' in read_text(rig.state / "routing.jsonl"), "the queued reaction during a held health check")
        rig.bridge.kill()
        rig.bridge.wait(10)
        rig.bridge = None
        assert bool(rig.outbox()[0].get("maybe")) == prior_uncertain
        (rig.fake / "no-private-api").touch()
        rig.relay_mode("")
        rig.start()
        wait_for(lambda: list((rig.state / "outbox-dead").glob("*.json")), "the failed-reaction receipt")
        if prior_uncertain:
            assert read_text(rig.notes) == ""
            assert "react thanks like" in read_text(rig.fake / "relay-sent")
        else:
            wait_for(lambda: "bluebubbles-thanks " in read_text(rig.notes), "the unsent-reaction handoff")
            assert read_text(rig.notes).count("bluebubbles-thanks ") == 1
            assert read_text(rig.fake / "relay-sent") == ""
    finally:
        rig.close()


def test_photon_reaction_retries_after_lookup_recovers_on_restart(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    (fake / "lookup-timeout").touch()
    bridge = start(1)
    try:
        receive("thanks", "thanks!")
        desk_clock()
        wait_for(lambda: "lookup timed out" in text(err), "the failed lookup")
        bridge.terminate()
        bridge.wait(10)
        queued = json.loads(next((state / "outbox").glob("*.json")).read_text())
        assert not queued.get("maybe")
        (fake / "lookup-timeout").unlink()
        bridge = start(2)
        wait_for(lambda: text(fake / "sent"), "the recovered reaction")
        assert text(fake / "sent").splitlines() == ["react thanks 👍"]
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_single_text_starts_after_the_short_quiet_period(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("single", "What is the build status?")
        wait_for(lambda: text(fake / "status-calls"), "status before the quiet period ends")
        desk_clock(TEST_QUIET_MS - 1)
        assert text(fake / "model-calls") == ""
        desk_clock(1)
        wait_for(lambda: text(fake / "sent"), "the single-text answer")
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_burst_cap_drafts_latest_text_and_a_correction_replaces_the_draft(tmp_path, monkeypatch, desk_clock):
    monkeypatch.setenv("FM_IMESSAGE_TEST_MAX_WAIT_MS", str(TEST_QUIET_MS * 3))
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("first", "What is the build status?")
        for i in range(3):
            desk_clock(TEST_QUIET_MS - 1)
            receive(f"more{i}", "Is the build paused?")
        assert text(fake / "model-calls") == ""
        desk_clock(3)
        wait_for(lambda: (fake / "model-started").exists(), "the draft at the burst cap")
        first = json.loads(text(fake / "model-calls").splitlines()[0])
        assert "owner 4: Is the build paused?" in first["prompt"]
        (fake / "status").write_text("The build is running.")
        (fake / "answer").write_text(json.dumps({
            "kind": "reply", "answer": "The build is running.",
            "evidence": [{"source": "status", "quote": "The build is running."}],
        }))
        receive("correction", "Correction: is the build running?")
        desk_clock(TEST_QUIET_MS - 1)
        assert len(text(fake / "model-calls").splitlines()) == 1
        assert text(fake / "sent") == ""
        desk_clock(1)
        wait_for(lambda: len(text(fake / "model-calls").splitlines()) == 2, "the replacement draft")
        (fake / "model-hold").unlink()
        wait_for(lambda: text(fake / "sent"), "the corrected answer")
        assert text(fake / "sent").splitlines() == ["send The build is running."]
        last = json.loads(text(fake / "model-calls").splitlines()[-1])
        assert "owner 1: What is the build status?" in last["prompt"]
        assert "owner 5: Correction: is the build running?" in last["prompt"]
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_status_starts_during_quiet_and_refreshes_for_the_latest_text(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("first", "What is the build status?")
        wait_for(lambda: text(fake / "status-calls"), "status during the quiet period", timeout=1)
        assert text(fake / "model-calls") == ""
        (fake / "status").write_text("The build is running.")
        (fake / "answer").write_text(json.dumps({
            "kind": "reply", "answer": "The build is running.",
            "evidence": [{"source": "status", "quote": "The build is running."}],
        }))
        receive("second", "Is the build running?")
        wait_for(lambda: len(text(fake / "status-calls").splitlines()) == 2, "fresh status during the new wait", timeout=1)
        (fake / "status").write_text("The build failed.")
        assert text(fake / "model-calls") == ""
        wait_for(lambda: text(fake / "sent"), "the answer from the prefetched status")
        assert text(fake / "sent").splitlines() == ["send The build is running."]
        assert len(text(fake / "status-calls").splitlines()) == 2
        assert len(text(fake / "model-calls").splitlines()) == 1
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_status_starts_before_slow_inbound_persistence(tmp_path, monkeypatch):
    preload = tmp_path / "slow-sync.ts"
    preload.write_text("""
import { mock } from "bun:test";
import * as fs from "node:fs";
const sync = fs.fsyncSync;
let delayed = false;
mock.module("node:fs", () => ({
  ...fs,
  fsyncSync(fd) {
    const journal = `${process.env.STATE_DIRECTORY}/routing.jsonl`;
    if (!delayed && fs.existsSync(journal) && fs.readFileSync(journal, "utf8").includes('"received"')) {
      delayed = true;
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 4000);
    }
    return sync(fd);
  },
}));
""")
    monkeypatch.setenv("BUN_OPTIONS", f"--preload={preload}")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path, test_mode=False)
    bridge = start(1)
    try:
        publish_json(fake / "inbound/slow.json", {
            "id": "slow", "space": "iMessage;-;+10000000000",
            "sender": "+10000000000", "text": "What is the build status?",
        })
        wait_for(lambda: text(fake / "status-calls"), "status before the slow sync completes", timeout=2)
        wait_for(lambda: text(fake / "sent"), "the answer after durable ownership")
        assert text(fake / "sent") == "send The build is paused.\n"
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("message,fact", [
    ("What is the build status?", "The build is paused."),
    ("Build status?", "The build is paused."),
    ("Build status", "The build is paused."),
    ("Run status?", "The run is paused."),
    ("Change history?", "The latest change adds the iMessage desk."),
    ("Restart policy?", "The worker restarts after failures."),
    ("Approved PR count?", "Approved PRs: 2"),
    ("OK response count?", "OK responses: 2"),
    ("Go ahead policy?", "The policy requires owner approval."),
])
def test_basic_answer_uses_haiku_without_a_supervisor_note_and_survives_replay(tmp_path, message, fact, recover):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "status").write_text(fact)
    (fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": fact, "evidence": [{"source": "status", "quote": fact}],
    }))
    bridge = start(1)
    try:
        receive("basic", message)
        if recover:
            bridge.terminate()
            bridge.wait(10)
            bridge = start(2)
        wait_for(lambda: text(fake / "sent"), "the direct answer")
        assert text(fake / "sent").splitlines() == [f"send {fact}"]
        assert text(notes) == ""
        call = json.loads(text(fake / "model-calls").splitlines()[0])
        assert call["args"][call["args"].index("--model") + 1] == "claude-haiku-5-5"
        assert "--thinking=off" in call["args"]
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3 if recover else 2)
        receive("basic", message)
        time.sleep(PAST_QUIET)
        assert text(fake / "sent").splitlines() == [f"send {fact}"]
        assert text(notes) == ""
        assert [r["text"] for r in records() if r["kind"] == "owner"] == [message]
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("recover", [False, True])
@pytest.mark.parametrize("message,classified", [
    ("Deploy the build", False),
    ("Build the dashboard", False),
    ("Please run the checks", False),
    ("Could you restart it?", False),
    ("Approved, proceed", False),
    ("Approved.", False),
    ("OK!", False),
    ("Yes, go ahead.", False),
    ("Proceed", False),
    ("Approve PR 12", False),
    ("Please approve PR 12", False),
    ("Could you approve PR 12?", False),
    ("yes please", False),
    ("ok go ahead and merge", False),
    ("Yes, merge PR 12", False),
    ("OK, deploy staging", False),
    ("Approved for deployment", True),
    ("What is the account password?", False),
    ("Run tests", True),
    ("What should I do?", True),
])
def test_work_approval_ambiguous_and_sensitive_handoff_once(tmp_path, message, classified, recover):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    if classified:
        (fake / "answer").write_text('{"kind":"handoff"}')
    if recover:
        (fake / "inbox-fail").touch()
    bridge = start(1)
    try:
        receive("work", message)
        if recover:
            wait_for(lambda: "routing retains the request" in text(err), "the retained handoff")
            bridge.terminate()
            bridge.wait(10)
            journal = state / "routing.jsonl"
            events = [json.loads(line) for line in journal.read_text().splitlines()]
            journal.write_text("".join(json.dumps(event) + "\n" for event in events if "received" in event))
            (fake / "inbox-fail").unlink()
            bridge = start(2)
        wait_for(lambda: "photon-work " in text(notes), "the supervisor handoff")
        receive("work", message)
        time.sleep(PAST_QUIET)
        assert text(notes).count("photon-work ") == 1
        assert text(fake / "sent") == ""
        assert [r["text"] for r in records() if r["kind"] == "owner"] == [message]
        if not classified:
            assert text(fake / "model-calls") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("response,failed", [
    ("not JSON", False),
    ('{"kind":"handoff"}', False),
    ('{"kind":"reply","answer":"Deployed.","evidence":[]}', False),
    ('{"kind":"reply","answer":"The build passed.","evidence":[{"source":"status","quote":"The build passed."}]}', False),
    ('{"kind":"reply","answer":"I deployed it.","evidence":[{"source":"status","quote":"The build is paused."}]}', False),
    ('{"kind":"reply","answer":"The build is paused.","evidence":[{"source":"status","quote":"The build is paused."}]}', True),
])
def test_failed_unsupported_or_ungrounded_answer_hands_off_without_a_desk_reply(tmp_path, response, failed):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text(response)
    if failed:
        (fake / "model-fail").touch()
    bridge = start(1)
    try:
        receive("fallback", "What is the build status?")
        wait_for(lambda: "photon-fallback " in text(notes), "the fallback handoff")
        time.sleep(0.2)
        assert text(notes).count("photon-fallback ") == 1
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("source_kind", ["status", "supervisor", "desk"])
@pytest.mark.parametrize("question,fact", [
    ("What is Firstmate?", "Firstmate is the coding-agent supervisor."),
    ("What is your role?", "I am the iMessage front desk."),
    ("Which desk model is in use?", "We use Claude Haiku 5.5 at the front desk."),
    ("What is your role?", "My role is the front desk."),
    ("What is the default region?", "Our default region is the US."),
    ("Which OS do you run?", "I run Linux."),
    ("What do you check?", "We check the supplied status."),
    ("Which format do you send?", "I send plain text."),
    ("Where is Firstmate's work directory?", "Firstmate's work directory is /workspace/firstmate."),
    ("Where are Firstmate’s saved settings?", "Firstmate’s saved settings are local."),
    ("What are Firstmate's working hours?", "Firstmate's working hours are 9am to 5pm."),
    ("What is Firstmate’s sending limit?", "Firstmate’s sending limit is five messages."),
    ("What is Firstmate's run status?", "Firstmate's run status is green."),
    ("When does Firstmate start?", "Firstmate's start time is 9am."),
])
def test_grounded_personal_descriptions_receive_a_direct_answer(tmp_path, source_kind, question, fact):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    if source_kind == "status":
        (fake / "status").write_text(fact)
        evidence = {"source": "status", "quote": fact}
    else:
        main = state / "memory/main"
        main.mkdir(parents=True)
        record = {"i": 0, "kind": source_kind, "text": fact, "size": len(fact.encode()), "date": "2026-10-17T00:00:00.000Z"}
        (main / "2026-10-17.jsonl").write_text(json.dumps(record) + "\n")
        evidence = {"source": "chat", "id": 0, "quote": fact}
    (fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": fact, "evidence": [evidence],
    }))
    bridge = start(1)
    try:
        receive("description", question)
        wait_for(lambda: text(fake / "sent"), "the grounded description")
        assert text(fake / "sent").splitlines() == [f"send {fact}"]
        assert text(notes) == ""
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("description", question)
        time.sleep(PAST_QUIET)
        assert text(fake / "sent").splitlines() == [f"send {fact}"]
        assert text(notes) == ""
        assert [r["text"] for r in records() if r["kind"] == "owner"] == [question]
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("source_kind", ["status", "supervisor", "desk"])
@pytest.mark.parametrize("claim", [
    "I fixed the bridge.",
    "I've deployed it.",
    "I’ve deployed it.",
    "We've repaired it.",
    "Firstmate’s deployed it.",
    "Our changes are live.",
    "Firstmate has already fixed the bridge.",
    "I have just merged the change.",
    "I have run the checks.",
    "I've run the checks.",
    "I’m running the checks.",
    "I will run the checks.",
    "We are sending the report.",
    "We’ll send the report.",
    "We have checked the build.",
    "I’ll check the build.",
    "Firstmate will deploy the build.",
    "Firstmate's saved it.",
    "Firstmate's running the checks.",
    "Firstmate’s working on it.",
    "Firstmate's run the checks.",
])
def test_grounded_action_claims_handoff_once_without_a_desk_send(tmp_path, source_kind, claim):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    if source_kind == "status":
        (fake / "status").write_text(claim)
        evidence = {"source": "status", "quote": claim}
    else:
        main = state / "memory/main"
        main.mkdir(parents=True)
        record = {"i": 0, "kind": source_kind, "text": claim, "size": len(claim.encode()), "date": "2026-10-17T00:00:00.000Z"}
        (main / "2026-10-17.jsonl").write_text(json.dumps(record) + "\n")
        evidence = {"source": "chat", "id": 0, "quote": claim}
    (fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": claim, "evidence": [evidence],
    }))
    bridge = start(1)
    try:
        receive("claim", "What is the bridge status?")
        wait_for(lambda: "photon-claim " in text(notes), "the action-claim handoff")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("claim", "What is the bridge status?")
        time.sleep(PAST_QUIET)
        assert text(notes).count("photon-claim ") == 1
        assert text(fake / "sent") == ""
        assert [r["text"] for r in records() if r["kind"] == "owner"] == ["What is the bridge status?"]
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("subject,quote,supervisor,direct", [
    ("desk", "claude-haiku-5-5", "claude-opus-5-5", True),
    ("supervisor", "claude-opus-5-5", "claude-opus-5-5", True),
    ("supervisor", "claude-opus-5-5", "", False),
    ("supervisor", "claude-haiku-5-5", "claude-opus-5-5", False),
    ("desk", "claude-opus-5-5", "claude-opus-5-5", False),
    ("supervisor", "claude-opus-5-5", "claude-opus-5-5\nother-model", False),
    ("unknown", "claude-haiku-5-5", "claude-opus-5-5", False),
    (None, "claude-haiku-5-5", "claude-opus-5-5", False),
])
def test_model_identity_is_bound_to_its_configured_subject(tmp_path, monkeypatch, subject, quote, supervisor, direct):
    monkeypatch.setenv("FM_IMESSAGE_SUPERVISOR_MODEL", supervisor)
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text(json.dumps({
        "kind": "reply", "answer": quote,
        "evidence": [{"source": "identity", "subject": subject, "quote": quote}],
    }))
    question = "Which model does Firstmate use?" if subject == "supervisor" else "Which model does the desk use?"
    bridge = start(1)
    try:
        receive("identity", question)
        if direct:
            wait_for(lambda: text(fake / "sent"), "the direct identity answer")
            assert text(fake / "sent").splitlines() == [f"send {quote}"]
            assert text(notes) == ""
        else:
            wait_for(lambda: "photon-identity " in text(notes), "the unsupported-identity handoff")
            assert text(fake / "sent") == ""
        call = json.loads(text(fake / "model-calls").splitlines()[0])
        assert call["args"][call["args"].index("--model") + 1] == "claude-haiku-5-5"
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("identity", question)
        time.sleep(PAST_QUIET)
        assert text(fake / "sent").splitlines() == ([f"send {quote}"] if direct else [])
        assert text(notes).count("photon-identity ") == (0 if direct else 1)
        assert [r["text"] for r in records() if r["kind"] == "owner"] == [question]
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_new_work_cancels_the_basic_draft_and_hands_each_message_off_once(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("first", "What is the build status?")
        wait_for(lambda: (fake / "model-started").exists(), "the pending basic draft")
        (fake / "answer").write_text('{"kind":"handoff"}')
        receive("second", "Deploy it instead")
        (fake / "model-hold").unlink()
        wait_for(lambda: "photon-second " in text(notes), "the replacement handoff")
        assert text(notes).count("photon-first ") == 1
        assert text(notes).count("photon-second ") == 1
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("mode", ["answer", "refused", "cancelled"])
def test_inception_desk_answers_through_zoom_or_hands_off_without_a_fallback(tmp_path, monkeypatch, mode):
    """The real bridge and inception-desk.ts against a local chat-completions server."""
    requests, release = [], threading.Event()

    class Server(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"auth": self.headers["Authorization"], "body": body, "at": time.monotonic()})
            if mode == "cancelled":
                release.wait(20)
            if mode == "refused":
                status, reply = 500, {"error": "upstream echo body-secret"}
            elif "tools" not in body:
                if body["reasoning_effort"] != "instant":
                    status, reply = 400, {"error": "unsupported reasoning effort"}
                else:
                    status, reply = 200, {"choices": [{"message": {"content": "the build is paused"}}]}
            elif len(requests) == 1:
                call = {"id": "c1", "type": "function", "function": {"name": "zoom", "arguments": '{"id": 0, "n": 1}'}}
                status, reply = 200, {"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [call]}}]}
            else:
                answer = {"kind": "reply", "answer": "The build is paused.", "evidence": [{"source": "status", "quote": "The build is paused."}]}
                status, reply = 200, {"choices": [{"message": {"role": "assistant", "content": json.dumps(answer)}}]}
            data = json.dumps(reply).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name, value in {"FM_IMESSAGE_DESK_PROVIDER": "inception", "FM_IMESSAGE_DESK_MODEL": "mercury-3", "FM_IMESSAGE_DESK_REASONING": "low",
                        "INCEPTION_API_KEY": "test-inception-key", "FM_DESK_INCEPTION_URL": f"http://127.0.0.1:{server.server_port}/v1/chat/completions"}.items():
        monkeypatch.setenv(name, value)
    # The answer mode ignores the test override and uses the production quiet period.
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path, test_mode=mode != "answer")
    bridge = start(1)
    try:
        published = time.monotonic()
        receive("first", "What is the build status?")
        if mode == "answer":
            wait_for(lambda: text(fake / "sent"), "the direct answer")
            assert text(fake / "sent").splitlines() == ["send the build is paused"]
            assert requests[2]["body"]["reasoning_effort"] == "instant"
            assert "tools" not in requests[2]["body"]
            assert text(notes) == ""
            result = requests[1]["body"]["messages"][-1]
            assert (result["role"], result["tool_call_id"]) == ("tool", "c1") and "What is the build status?" in result["content"]
        elif mode == "refused":
            wait_for(lambda: "photon-first " in text(notes), "the handoff")
        else:
            wait_for(lambda: requests, "the held desk request")
            receive("second", "Deploy it instead")
            wait_for(lambda: "photon-second " in text(notes), "the replacement handoff")
            assert text(notes).count("photon-first ") == 1
        if mode != "answer":
            assert text(fake / "sent") == ""
        first = requests[0]
        assert first["at"] - published >= (0.35 if mode == "answer" else TEST_QUIET_MS / 1000)
        if mode == "answer":
            assert first["at"] - published < 6
        assert first["auth"] == "Bearer test-inception-key"
        assert (first["body"]["model"], first["body"]["reasoning_effort"]) == ("mercury-3", "low")
        assert [t["function"]["name"] for t in first["body"]["tools"]] == ["zoom"]
        assert "zoom.ts" not in text(fake / "model-calls")
        if mode != "cancelled":
            assert f"inception mercury-3 reasoning=low HTTP {200 if mode == 'answer' else 500}" in text(err)
        assert "test-inception-key" not in text(err) and "body-secret" not in text(err)
    finally:
        release.set()
        bridge.terminate()
        bridge.wait(10)
        server.shutdown()


@pytest.mark.parametrize("latest", ["short", "huge"])
def test_inception_requests_stay_within_100000_bytes_and_zoom_ends_with_limit_reached(tmp_path, latest):
    """A full memory view, then zooms of quote-heavy messages: every body fits and the model hears LIMIT_REACHED."""
    memory = tmp_path / "memory"
    (memory / "main").mkdir(parents=True)
    noisy = 'he said "go"\\ then\n' * 2000  # JSON escapes grow this text by about a quarter
    (memory / "main" / "2026-01-01.jsonl").write_text("".join(
        json.dumps({"i": i, "kind": "owner", "text": noisy, "size": len(noisy), "date": "2026-01-01"}) + "\n" for i in range(8)))
    made = bun(f"""
import {{ deskInput, deskPrompt, INCEPTION_MAX }} from {json.dumps(str(ROOT / "apps/imessage/desk.ts"))};
import {{ LIMIT_REACHED }} from {json.dumps(str(ROOT / "apps/imessage/memory.ts"))};
const system = deskPrompt("the owner", "mercury-3", "");
const view = Array.from({{ length: 2000 }}, (_, i) => `${{i}}+1|the owner wrote about the trip and the build plan`).join("\\n");
const ask = {json.dumps(latest)} === "short" ? "What did I say?" : "HEAD" + 'he "asked"\\n'.repeat(20000) + "TAIL";
const recent = Array.from({{ length: 12 }}, (_, i) => JSON.stringify({{ i, kind: "supervisor", text: '"\\\\\\n'.repeat(100) }})).join("\\n");
const {{ prompt }} = deskInput(system, view, "The build is paused.", ask, "inception", recent);
console.log(JSON.stringify({{ system, prompt, LIMIT_REACHED, INCEPTION_MAX }}));
""")
    raw = made["prompt"].split("<recent>\n", 1)[1].split("\n</recent>", 1)[0]
    rows = [json.loads(line) for line in raw.splitlines()]
    assert 0 < len(rows) < 12
    assert [row["i"] for row in rows] == list(range(12 - len(rows), 12))
    assert len(json.dumps(raw, ensure_ascii=False)[1:-1].encode()) <= 6000
    sizes, results = [], []

    class Server(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            sizes.append(len(raw))
            tools = [m["content"] for m in json.loads(raw)["messages"] if m["role"] == "tool"]
            results[:] = tools
            if made["LIMIT_REACHED"] in tools or len(sizes) > 6:
                message = {"role": "assistant", "content": "SKIP"}
            else:  # two zooms per turn, so a later call's refusal is reserved too
                calls = [{"id": f"call-{k}", "type": "function", "function": {"name": "zoom", "arguments": json.dumps({"id": k, "n": 1})}}
                         for k in (len(tools), len(tools) + 1)]
                message = {"role": "assistant", "content": None, "tool_calls": calls}
            data = json.dumps({"choices": [{"message": message}]}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        done = subprocess.run(
            ["bun", str(ROOT / "apps/imessage/inception-desk.ts"), "mercury-3", "low", made["system"]], input=made["prompt"],
            capture_output=True, text=True, timeout=60,
            env={"PATH": os.environ["PATH"], "INCEPTION_API_KEY": "test-key", "FM_DESK_MEMORY": str(memory),
                 "FM_DESK_INCEPTION_URL": f"http://127.0.0.1:{server.server_port}/v1/chat/completions"})
    finally:
        server.shutdown()
    assert (done.returncode, done.stdout) == (0, "SKIP"), done.stderr
    assert max(sizes) <= made["INCEPTION_MAX"]
    assert results[-1] == made["LIMIT_REACHED"] and len(sizes) == 2
    taken = [r for r in results if r != made["LIMIT_REACHED"]]
    if latest == "short":  # room for one zoom of the large view's call, not two
        assert len(taken) == 1 and taken[0].startswith("2026-01-01 owner: ") and sizes[0] > 64_000
    else:  # the escaped burst fills the first body; it keeps both ends and leaves room only for the refusal
        assert taken == [] and sizes[0] > 90_000 and "HEAD" in made["prompt"] and "TAIL" in made["prompt"]
    assert "test-key" not in done.stderr and "he said" not in done.stderr


def test_restart_recovers_owned_inbound_and_keeps_an_uncertain_send_out_of_firstmate(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("restart", "What is the build status?")
        wait_for(lambda: (fake / "model-started").exists(), "the draft before restart")
        bridge.terminate()
        bridge.wait(10)
        (fake / "model-hold").unlink()
        (fake / "send-unsure").touch()
        bridge = start(2)
        wait_for(lambda: "write timed out" in text(err), "the uncertain direct send")
        assert text(notes) == ""
        assert len(list((state / "outbox").glob("*.json"))) == 1
        bridge.terminate()
        bridge.wait(10)
        (fake / "send-unsure").unlink()
        bridge = start(3)
        wait_for(lambda: text(fake / "sent"), "the recovered direct send")
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(notes) == ""
        assert len([r for r in records() if r["kind"] == "owner"]) == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_basic_burst_sends_one_answer_and_replays_a_decision_without_requeueing(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("burst1", "What is the build status?")
        receive("burst2", "Is the build paused?")
        wait_for(lambda: text(fake / "sent"), "the burst answer")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the completed outbox receipt")
        assert text(notes) == ""
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert len(text(fake / "model-calls").splitlines()) == 1
        bridge.terminate()
        bridge.wait(10)
        # Simulate a stop after enqueue but before recording routing completion.
        journal = state / "routing.jsonl"
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        journal.write_text("".join(json.dumps(e) + "\n" for e in events if e.get("route") != "done") + '{"ids":')
        bridge = start(2)
        time.sleep(PAST_QUIET)
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(notes) == ""
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        receive("burst1", "What is the build status?")
        receive("burst2", "Is the build paused?")
        time.sleep(PAST_QUIET)
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert len([r for r in records() if r["kind"] == "owner"]) == 2
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_social_burst_completes_with_one_reaction_and_keeps_records_after_restart(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️","target":1}')
    bridge = start(1)
    try:
        receive("thanks", "thanks!")
        receive("ack", "got it")
        receive("emoji", "🙌")
        (fake / "outage").touch()
        desk_clock()
        wait_for(lambda: list((state / "outbox").glob("*.json")), "the saved social reaction")
        wait_for(lambda: '"route":"done"' in text(state / "routing.jsonl"), "the completed social routing")
        assert text(notes) == ""
        bridge.terminate()
        bridge.wait(10)
        (fake / "outage").unlink()
        bridge = start(2)
        wait_for(lambda: text(fake / "sent"), "the recovered reaction")
        assert text(fake / "sent").splitlines() == ["react thanks ❤️"]
        receive("thanks", "thanks!")
        desk_clock()
        assert text(fake / "sent").splitlines() == ["react thanks ❤️"]
        assert text(notes) == ""
        assert [r["text"] for r in records() if r["kind"] == "owner"] == ["thanks!", "got it", "🙌"]
        received = [e["received"] for e in map(json.loads, text(state / "routing.jsonl").splitlines()) if "received" in e]
        assert [r["text"] for r in received] == ["thanks!", "got it", "🙌"]
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("messages,context", [
    (["ok"], "Shall I deploy the build?"),
    (["yes"], "Shall I deploy the build?"),
    (["👍"], "Shall I deploy the build?"),
    (["🛑"], "Build failed on main."),
    (["❓"], "Build failed on main."),
    (["✅"], "The change is ready."),
    (["👍"], "The change is ready."),
    (["got it"], "Tests pass. Say the word and I'll merge."),
    (["🙏"], "Let me know when to deploy."),
    (["thanks", "Run tests"], None),
    (["What is the build status?"], None),
    (["thanks", "What is the build status?"], None),
    (["thanks, please check the account"], None),
    (["My account password is secret"], None),
])
def test_approval_and_mixed_bursts_hand_off_without_a_reaction(tmp_path, desk_clock, messages, context):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    bridge = start(1)
    try:
        if context:
            receive("context", "A question")
            cli(context)
            wait_for(lambda: text(fake / "sent"), "the prior supervisor message")
        for i, message in enumerate(messages):
            receive(f"turn{i}", message)
        desk_clock()
        wait_for(lambda: all(f"photon-turn{i} " in text(notes) for i in range(len(messages))), "the full handoff")
        assert [r["text"] for r in records() if r["kind"] == "owner"] == (["A question"] if context else []) + messages
        assert text(fake / "sent").splitlines()[int(bool(context)):] == []
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("messages,response,expected", [
    (["thanks!"], {"kind": "tapback", "emoji": "❤️"}, ["react social0 ❤️"]),
    (["hahaha", "nice"], {"kind": "tapback", "emoji": "😂"}, ["react social1 😂"]),
    (["great news!", "awesome"], {"kind": "tapback", "emoji": "‼️", "text": "nice!"},
     ["send nice!", "react social1 ‼️"]),
])
def test_social_burst_sends_one_fitting_reaction_with_optional_text(tmp_path, desk_clock, messages, response, expected):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text(json.dumps(response))
    bridge = start(1)
    try:
        for i, message in enumerate(messages):
            receive(f"social{i}", message)
        desk_clock()
        wait_for(lambda: text(fake / "sent").splitlines() == expected, "the social response")
        assert text(notes) == ""
        assert sum(line.startswith("react ") for line in text(fake / "sent").splitlines()) == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("extra", ["I fixed it", "checking now", "your account is safe", "run tests", ""])
def test_social_reaction_rejects_unchecked_extra_text(tmp_path, desk_clock, extra):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text(json.dumps({"kind": "tapback", "emoji": "❤️", "text": extra}))
    bridge = start(1)
    try:
        receive("thanks", "thanks!")
        desk_clock()
        wait_for(lambda: "photon-thanks " in text(notes), "the unsafe-text handoff")
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("ending", ["retry", "expired"])
def test_social_text_is_not_repeated_or_handed_off_when_its_reaction_fails(tmp_path, desk_clock, ending):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️","text":"nice!"}')
    (fake / "react-unsure").touch()
    bridge = start(1)
    try:
        receive("social", "great news!")
        desk_clock()
        wait_for(lambda: "reaction timed out" in text(err), "the reaction retry")
        assert text(fake / "sent").splitlines().count("send nice!") == 1
        bridge.terminate()
        bridge.wait(10)
        (fake / "react-unsure").unlink()
        if ending == "expired":
            publish_json(tmp_path / "clock", int((tmp_path / "clock").read_text()) + 121_000)
        bridge = start(2)
        receipt = state / ("outbox-dead" if ending == "expired" else "outbox-done")
        wait_for(lambda: list(receipt.glob("*.json")), "the reaction receipt after restart")
        assert text(fake / "sent").splitlines().count("send nice!") == 1
        assert text(notes) == ""
        assert [r["text"] for r in records() if r["kind"] == "desk"].count("nice!") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("crash", ["before", "after"])
@pytest.mark.parametrize("response", ["social", "desk", "supervisor"])
def test_delivered_text_memory_survives_a_crash_without_duplicates(tmp_path, monkeypatch, desk_clock, crash, response):
    preload = tmp_path / "memory-crash.ts"
    preload.write_text("""
import { existsSync } from "node:fs";
import { Memory } from "./app/memory.ts";
const append = Memory.prototype.append;
Memory.prototype.append = function(kind, ...args) {
  if (kind !== "owner" && existsSync(`${process.env.FAKE_DIR}/memory-crash`)) {
    if (CRASH === "before") process.exit(86);
    append.call(this, kind, ...args);
    process.exit(86);
  }
  return append.call(this, kind, ...args);
};
""".replace("CRASH", json.dumps(crash)))
    monkeypatch.setenv("BUN_OPTIONS", f"{os.environ['BUN_OPTIONS']} --preload={preload}")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    reply = "nice!" if response == "social" else "The build is paused."
    kind = "supervisor" if response == "supervisor" else "desk"
    if response == "social":
        (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️","text":"nice!"}')
    marker = fake / "memory-crash"
    marker.touch()
    bridge = start(1)
    try:
        receive("question", "great news!" if response == "social" else "What is the build status?")
        if response == "supervisor":
            cli(reply)
        else:
            desk_clock()
        assert bridge.wait(10) == 86
        pending, = (state / "outbox").glob("*.json")
        item = json.loads(pending.read_text())
        assert item["done"] == len(item["bubbles"]) == 1
        assert text(fake / "sent").splitlines() == [f"send {reply}"]
        assert [r["text"] for r in records() if r["kind"] == kind] == ([reply] if crash == "after" else [])
        original_notes = text(notes)
        marker.unlink()
        bridge = start(2)
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the recovered delivery")
        expected = [f"send {reply}"] + (["react question ❤️"] if response == "social" else [])
        assert text(fake / "sent").splitlines() == expected
        delivered, = [r for r in records() if r["kind"] == kind and r["text"] == reply]
        assert delivered["requestId"] == f"outbox-text-{item['guid']}"
        assert text(notes) == original_notes
    finally:
        if bridge.poll() is None:
            bridge.terminate()
            bridge.wait(10)


def test_expired_social_reaction_hands_the_full_burst_to_firstmate(tmp_path, monkeypatch, desk_clock):
    monkeypatch.setenv("FM_IMESSAGE_REACT_MAX_MS", "50")
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"👍"}')
    bridge = start(1)
    try:
        receive("thanks", "thanks")
        receive("ack", "got it")
        (fake / "outage").touch()
        desk_clock()
        wait_for(lambda: "outbox item 1 failed" in text(err), "the failed reaction attempt")
        desk_clock(51)
        wait_for(lambda: all(f"photon-{mid} " in text(notes) for mid in ("thanks", "ack")), "the failed-reaction handoff")
        assert text(fake / "sent") == ""
        assert "thanks" in text(notes) and "got it" in text(notes)
        assert text(notes).count("photon-thanks ") == text(notes).count("photon-ack ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("target,expected", [
    (1, "reply burst1 The build is paused."),
    (2, "reply burst2 The build is paused."),
    (3, "send The build is paused."),
])
def test_burst_answer_targets_the_selected_message_and_threads_only_across_bubbles(tmp_path, desk_clock, target, expected):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    answer = json.loads((fake / "answer").read_text())
    (fake / "answer").write_text(json.dumps({**answer, "target": target}))
    bridge = start(1)
    try:
        receive("burst1", "What is the build status?")
        receive("burst2", "Is the build paused?")
        receive("burst3", "Paused or running?")
        desk_clock()
        wait_for(lambda: text(fake / "sent"), "the selected burst answer")
        assert text(fake / "sent").splitlines() == [expected]
        assert text(notes) == ""
        assert len([r for r in records() if r["kind"] == "owner"]) == 3
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("target", [0, -1, 4, 1.5, "1"])
def test_invalid_burst_target_hands_off_without_sending(tmp_path, desk_clock, target):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    answer = json.loads((fake / "answer").read_text())
    (fake / "answer").write_text(json.dumps({**answer, "target": target}))
    bridge = start(1)
    try:
        receive("target", "What is the build status?")
        desk_clock()
        wait_for(lambda: "photon-target " in text(notes), "the invalid-target handoff")
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("content", [
    {"type": "reply", "target": {"content": {"type": "text", "text": "the build"}}, "content": {"type": "text", "text": "What is its status?"}},
    {"type": "effect", "content": {"type": "text", "text": "What is the build status?"}},
    {"type": "group", "items": [{"content": {"type": "text", "text": "What is the build status?"}}]},
])
def test_plain_reply_effect_and_group_contents_can_receive_a_direct_answer(tmp_path, content):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("wrapped", "status?", content=content)
        wait_for(lambda: text(fake / "sent"), "the wrapped basic answer")
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(notes) == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("wrapper", ["reply", "effect", "group", "markdown"])
@pytest.mark.parametrize("restart", [False, True])
def test_threaded_social_text_reacts_without_handoff_and_keeps_metadata(tmp_path, desk_clock, wrapper, restart):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"tapback","emoji":"❤️"}')
    inner = {"type": "markdown", "markdown": "thanks!"} if wrapper == "markdown" else {"type": "text", "text": "thanks!"}
    content = {
        "type": "reply", "content": inner,
        "target": {"content": {"type": "text", "text": "The build is paused. The secret is saved.\nDeploy the build."}},
    }
    if wrapper == "effect":
        content = {"type": "effect", "content": content}
    elif wrapper == "group":
        content = {"type": "group", "items": [{"content": content}]}
    bridge = start(1)
    try:
        receive("threaded", "thanks!", content=content)
        if restart:
            bridge.terminate()
            bridge.wait(10)
            bridge = start(2)
        desk_clock()
        wait_for(lambda: text(fake / "sent"), "the threaded social reaction")
        assert text(fake / "sent").splitlines() == ["react threaded ❤️"]
        assert text(notes) == ""
        received = next(e["received"] for e in map(json.loads, text(state / "routing.jsonl").splitlines()) if "received" in e)
        assert received["authored"] == "thanks!"
        assert 'replying in a thread to: "The build is paused.' in received["text"]
        assert [r["text"] for r in records() if r["kind"] == "owner"] == [received["text"]]
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_attachment_hands_off_without_using_the_basic_model(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("attachment", "sent an attachment", name="sample.txt", data="synthetic attachment")
        wait_for(lambda: "photon-attachment " in text(notes), "the attachment handoff")
        assert text(notes).count("photon-attachment ") == 1
        assert text(fake / "sent") == ""
        assert text(fake / "model-calls") == ""
        assert (state / "attachments/attachment-sample.txt").read_text() == "synthetic attachment"
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("activity,expected", [
    (["--typing"], []),
    (["--react", "❤️"], ["react activity ❤️"]),
    (["The build is running."], ["send The build is running."]),
])
def test_supervisor_activity_cancels_a_draft_without_losing_the_pending_request(tmp_path, desk_clock, activity, expected):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("activity", "What is the build status?")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the draft")
        cli(*activity)
        (fake / "model-hold").unlink()
        wait_for(lambda: "photon-activity " in text(notes), "the handoff after supervisor activity")
        desk_clock(TEST_QUIET_MS * 6)
        assert text(notes).count("photon-activity ") == 1
        assert text(fake / "sent").splitlines() == expected
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("source_kind", ["owner", "supervisor"])
def test_only_trusted_chat_records_can_ground_a_basic_answer(tmp_path, source_kind):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"handoff"}')
    bridge = start(1)
    try:
        receive("seed", "The queue is empty.")
        wait_for(lambda: "photon-seed " in text(notes), "the seed handoff")
        if source_kind == "supervisor":
            cli("The queue is empty.")
            wait_for(lambda: any(r["kind"] == "supervisor" for r in records()), "the supervisor record")
        source = next(r for r in records() if r["kind"] == source_kind)
        (fake / "answer").write_text(json.dumps({
            "kind": "reply", "answer": "The queue is empty.",
            "evidence": [{"source": "chat", "id": source["i"], "quote": "The queue is empty."}],
        }))
        receive("question", "What is in the queue?")
        if source_kind == "supervisor":
            wait_for(lambda: text(fake / "sent").splitlines().count("send The queue is empty.") == 2, "the grounded answer")
            assert "photon-question " not in text(notes)
        else:
            wait_for(lambda: "photon-question " in text(notes), "the untrusted-source handoff")
            assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_clipped_latest_input_hands_off_the_full_durable_request(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "status").write_text("The build is paused. " + "s" * 16_000)
    bridge = start(1)
    try:
        message = "What is the build status? " + "x" * 130_000
        receive("large", message)
        wait_for(lambda: "photon-large " in text(notes), "the full-input handoff")
        assert message in text(notes)
        assert text(fake / "sent") == ""
        assert any(r["text"] == message for r in records())
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.skipif(sys.platform != "linux", reason="uses the Linux per-argument size limit")
def test_oversized_handoff_does_not_block_later_work_or_restart_recovery(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    message = "What is the build status? " + "x" * 190_001
    bridge = start(1)
    try:
        receive("oversized", message)
        wait_for(lambda: "E2BIG" in text(err), "the oversized inbox argument failure")
        receive("later", "Deploy the next build.")
        wait_for(lambda: "photon-later " in text(notes), "work after the oversized handoff")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("oversized", message)
        receive("later", "Deploy the next build.")
        receive("recovered", "Deploy the next build.")
        wait_for(
            lambda: any(event.get("route") == "done" and "photon-recovered" in event["ids"]
                        for event in map(json.loads, text(state / "routing.jsonl").splitlines())),
            "the durable recovered handoff",
        )
        assert text(notes).count("photon-later ") == 1
        assert text(notes).count("photon-recovered ") == 1
        assert "photon-oversized " not in text(notes)
        events = [json.loads(line) for line in text(state / "routing.jsonl").splitlines()]
        assert [e["received"]["text"] for e in events if e.get("received", {}).get("requestId") == "photon-oversized"] == [message]
        completed = {request for e in events if e.get("route") == "done" for request in e["ids"]}
        assert completed == {"photon-later", "photon-recovered"}
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_unavailable_status_hands_off_without_using_the_basic_model(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "status-fail").touch()
    bridge = start(1)
    try:
        receive("status", "What is the build status?")
        wait_for(lambda: "photon-status " in text(notes), "the status-failure handoff")
        assert text(fake / "sent") == ""
        assert text(fake / "model-calls") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_failed_handoff_survives_restart_and_notifies_once_after_recovery(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "answer").write_text('{"kind":"handoff"}')
    (fake / "inbox-fail").touch()
    bridge = start(1)
    try:
        receive("held", "Deploy the build")
        wait_for(lambda: "routing retains the request" in text(err), "the durable handoff retry")
        assert text(notes) == ""
        bridge.terminate()
        bridge.wait(10)
        (fake / "inbox-fail").unlink()
        bridge = start(2)
        wait_for(lambda: "photon-held " in text(notes), "the recovered handoff")
        receive("held", "Deploy the build")
        time.sleep(0.2)
        assert text(notes).count("photon-held ") == 1
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_memory_write_failure_keeps_the_input_and_hands_off_once(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    main = state / "memory/main"
    saved = state / "memory/saved-main"
    try:
        main.rename(saved)
        main.write_text("simulate an unavailable memory directory")
        receive("memory-failed", "What is the build status?")
        wait_for(lambda: "photon-memory-failed " in text(notes), "the memory-failure handoff")
        assert text(notes).count("photon-memory-failed ") == 1
        assert text(fake / "sent") == ""
        assert "What is the build status?" in text(state / "routing.jsonl")
        main.unlink()
        saved.rename(main)
        receive("later", "Deploy the later build")
        wait_for(lambda: "photon-later " in text(notes), "the later request at the old memory index")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        assert sorted(r["text"] for r in records() if r["kind"] == "owner") == ["Deploy the later build", "What is the build status?"]
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        assert sorted(r["text"] for r in records() if r["kind"] == "owner") == ["Deploy the later build", "What is the build status?"]
        assert text(notes).count("photon-memory-failed ") == 1
        assert text(notes).count("photon-later ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_multiline_work_bypasses_a_ready_basic_answer(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    bridge = start(1)
    try:
        receive("mixed", "What is the build status?\n  Restart the worker")
        wait_for(lambda: "photon-mixed " in text(notes), "the mixed-request handoff")
        assert text(notes).count("photon-mixed ") == 1
        assert text(fake / "sent") == ""
        assert text(fake / "model-calls") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("status,evidence,answer", [
    ("The build did not pass.", {"source": "status", "quote": "pass"}, "pass"),
    ("The build is paused.", {"source": "identity", "subject": "desk", "quote": "haiku"}, "haiku"),
])
def test_partial_evidence_cannot_reverse_a_fact_or_shorten_model_identity(tmp_path, status, evidence, answer):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "status").write_text(status)
    (fake / "answer").write_text(json.dumps({"kind": "reply", "answer": answer, "evidence": [evidence]}))
    bridge = start(1)
    try:
        receive("partial", "What is the build status?")
        wait_for(lambda: "photon-partial " in text(notes), "the partial-evidence handoff")
        assert text(notes).count("photon-partial ") == 1
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_a_stuck_status_reader_times_out_and_hands_off(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "status-hold").touch()
    bridge = start(1)
    try:
        receive("status-timeout", "What is the build status?")
        wait_for(lambda: (fake / "status-started").exists(), "the blocked status reader")
        wait_for(lambda: "photon-status-timeout " in text(notes), "the bounded status handoff", timeout=15)
        assert text(notes).count("photon-status-timeout ") == 1
        assert text(fake / "sent") == ""
        assert text(fake / "model-calls") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_a_definitely_refused_basic_burst_hands_off_once_even_after_lost_notice_recovery(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "send-refused").touch()
    (fake / "inbox-fail").touch()
    bridge = start(1)
    try:
        receive("refused1", "What is the build status?")
        receive("refused2", "Is the build paused?")
        wait_for(lambda: list((state / "outbox-dead").glob("*.json")), "the definite send refusal")
        bridge.terminate()
        bridge.wait(10)
        # Keep the saved decision but lose the failure callback's journal writes.
        journal = state / "routing.jsonl"
        events = [json.loads(line) for line in journal.read_text().splitlines()]
        journal.write_text("".join(json.dumps(e) + "\n" for e in events if e.get("route") not in {"done", "handoff"}))
        (fake / "inbox-fail").unlink()
        bridge = start(2)
        wait_for(lambda: "photon-refused2 " in text(notes), "the restored refusal handoff")
        assert text(notes).count("photon-refused1 ") == 1
        assert text(notes).count("photon-refused2 ") == 1
        assert text(fake / "sent") == ""
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        time.sleep(0.2)
        assert text(notes).count("photon-refused1 ") == 1
        assert text(notes).count("photon-refused2 ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_a_refusal_after_an_uncertain_attempt_never_creates_a_second_answer(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "send-unsure").touch()
    bridge = start(1)
    try:
        receive("uncertain", "What is the build status?")
        wait_for(lambda: "write timed out" in text(err), "the uncertain first attempt")
        bridge.terminate()
        bridge.wait(10)
        (fake / "send-unsure").unlink()
        (fake / "send-refused").touch()
        bridge = start(2)
        wait_for(lambda: list((state / "outbox-dead").glob("*.json")), "the later refusal with retained uncertainty")
        assert text(notes) == ""
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)
