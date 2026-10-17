"""Run the actual bridge with isolated fake Photon and model processes. No live provider calls."""

import json
import shutil
import time

import pytest
from test_imessage import fake_bridge, publish_json, wait_for

pytestmark = pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")


def basic_rig(tmp_path):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    (fake / "status").write_text("The build is paused.")
    answer = {"kind": "basic", "answer": "The build is paused.", "evidence": [{"source": "status", "quote": "The build is paused."}]}
    (fake / "answer").write_text(json.dumps(answer))
    (tmp_path / "bin/omp").write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys, time\n"
        "p = pathlib.Path(os.environ['FAKE_DIR'])\n"
        "prompt = sys.stdin.read()\n"
        "with (p / 'model-calls').open('a') as f: f.write(json.dumps({'args': sys.argv, 'prompt': prompt}) + '\\n')\n"
        "(p / 'model-started').touch()\n"
        "while (p / 'model-hold').exists(): time.sleep(0.02)\n"
        "print((p / 'answer').read_text())\n"
        "sys.exit(1 if (p / 'model-fail').exists() else 0)\n"
    )
    (tmp_path / "bin/fm-inbox").write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, sys, time\n"
        "p = pathlib.Path(os.environ['FAKE_DIR'])\n"
        f"notes = pathlib.Path({str(notes)!r})\n"
        "if sys.argv[1] == 'status':\n"
        "    if (p / 'status-fail').exists(): sys.exit(1)\n"
        "    (p / 'status-started').touch()\n"
        "    while (p / 'status-hold').exists(): time.sleep(0.02)\n"
        "    print((p / 'status').read_text())\n"
        "else:\n"
        "    if (p / 'inbox-fail').exists(): sys.exit(1)\n"
        "    key = sys.argv[sys.argv.index('--request-id') + 1]\n"
        "    old = notes.read_text() if notes.exists() else ''\n"
        "    if key + ' ' not in old:\n"
        "        with notes.open('a') as f: f.write(' '.join(sys.argv[1:]) + '\\n')\n"
    )

    def receive(mid, message, **fields):
        publish_json(fake / "inbound" / f"{mid}.json", {
            "id": mid, "space": "iMessage;-;+10000000000", "sender": "+10000000000", "text": message, **fields,
        })
        wait_for(lambda: f'"photon-{mid}"' in text(state / "routing.jsonl"), "durable inbound ownership")

    def records():
        return [json.loads(line) for p in (state / "memory/main").glob("*.jsonl") for line in p.read_text().splitlines()]

    return fake, state, notes, err, start, receive, cli, text, records


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
        "kind": "basic", "answer": fact, "evidence": [{"source": "status", "quote": fact}],
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
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3 if recover else 2)
        receive("basic", message)
        time.sleep(4.5)
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
        time.sleep(4.5)
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
    ('{"kind":"basic","answer":"Deployed.","evidence":[]}', False),
    ('{"kind":"basic","answer":"The build passed.","evidence":[{"source":"status","quote":"The build passed."}]}', False),
    ('{"kind":"basic","answer":"I deployed it.","evidence":[{"source":"status","quote":"The build is paused."}]}', False),
    ('{"kind":"basic","answer":"The build is paused.","evidence":[{"source":"status","quote":"The build is paused."}]}', True),
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
        "kind": "basic", "answer": fact, "evidence": [evidence],
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
        time.sleep(4.5)
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
        "kind": "basic", "answer": claim, "evidence": [evidence],
    }))
    bridge = start(1)
    try:
        receive("claim", "What is the bridge status?")
        wait_for(lambda: "photon-claim " in text(notes), "the action-claim handoff")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("claim", "What is the bridge status?")
        time.sleep(4.5)
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
        "kind": "basic", "answer": quote,
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
        time.sleep(4.5)
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
        time.sleep(4.5)
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert text(notes) == ""
        bridge.terminate()
        bridge.wait(10)
        bridge = start(3)
        receive("burst1", "What is the build status?")
        receive("burst2", "Is the build paused?")
        time.sleep(4.5)
        assert text(fake / "sent").splitlines() == ["send The build is paused."]
        assert len([r for r in records() if r["kind"] == "owner"]) == 2
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


def test_supervisor_activity_cancels_a_draft_without_losing_the_pending_request(tmp_path):
    fake, state, notes, err, start, receive, cli, text, records = basic_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("activity", "What is the build status?")
        wait_for(lambda: (fake / "model-started").exists(), "the draft")
        cli("--typing")
        (fake / "model-hold").unlink()
        wait_for(lambda: "photon-activity " in text(notes), "the handoff after supervisor activity")
        time.sleep(0.2)
        assert text(notes).count("photon-activity ") == 1
        assert text(fake / "sent") == ""
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
            "kind": "basic", "answer": "The queue is empty.",
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
    (fake / "answer").write_text(json.dumps({"kind": "basic", "answer": answer, "evidence": [evidence]}))
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
