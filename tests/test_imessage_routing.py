"""Exercise desk routing through the real bridge with local model and inbox processes."""

import json
import shutil
import time

import pytest
from test_imessage import wait_for
from test_imessage_basic import basic_rig
from test_imessage_basic import desk_clock as desk_clock

pytestmark = pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")

SCOPES = {
    "web-mate": "Website pages and browser layout; exclude native applications",
    "data-mate": "Database queries and report exports",
    "build-mate": "Compiler builds and CI jobs",
}


def routing_rig(tmp_path):
    rig = basic_rig(tmp_path)
    fake = rig[0]
    registry = tmp_path / "data/secondmates.md"
    registry.parent.mkdir()
    registry.write_text("# Second mates\n\n" + "".join(
        f"- {mate} - Test owner (home: {tmp_path / 'mates' / mate}; scope: {scope}; projects: test; added 2026-10-23)\n"
        for mate, scope in SCOPES.items()
    ))
    (tmp_path / "state").mkdir(exist_ok=True)
    for mate in SCOPES:
        (tmp_path / "mates" / mate).mkdir(parents=True)
        (tmp_path / "state" / f"{mate}.meta").write_text("kind=secondmate\n")
    sender = tmp_path / "bin/fm-send.sh"
    sender.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, signal, sys, time\n"
        "p = pathlib.Path(os.environ['FAKE_DIR'])\n"
        "def cancelled(signum, frame):\n"
        "    (p / 'send-cancelled').touch()\n"
        "    sys.exit(143)\n"
        "signal.signal(signal.SIGTERM, cancelled)\n"
        "if not (pathlib.Path(os.environ['FM_HOME']) / 'state' / (sys.argv[1] + '.meta')).is_file(): sys.exit(1)\n"
        "with (p / 'mate-sends').open('a') as f:\n"
        "    f.write(json.dumps({'home': os.environ['FM_HOME'], 'args': sys.argv[1:]}) + '\\n')\n"
        "while (p / 'mate-hold').exists(): time.sleep(0.02)\n"
        "if (p / 'send-timeout').exists(): time.sleep(30)\n"
        "sys.exit(1 if (p / 'send-fail').exists() else 0)\n"
    )
    sender.chmod(0o755)
    (fake / "answer").write_text(json.dumps({
        "kind": "handoff", "target": "web-mate", "confidence": "high", "domains": ["web-mate"], "category": "work",
    }))
    return rig


@pytest.mark.parametrize("mate,message", [
    ("web-mate", "Fix the website menu alignment.\nKeep the label 'Main'."),
    ("data-mate", "Fix the database report export query"),
    ("build-mate", "Fix the compiler build in CI"),
])
def test_mate_handoff_preserves_text_and_notifies_firstmate(tmp_path, desk_clock, mate, message):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "answer").write_text(json.dumps({
        "target": mate, "confidence": "high", "domains": [mate], "category": "work",
    }))
    bridge = start(1)
    try:
        receive("work", message)
        desk_clock()
        wait_for(lambda: "routed to " in text(notes), "the Firstmate routing note")
        sends = [json.loads(line) for line in text(fake / "mate-sends").splitlines()]
        assert sends == [{"home": str(tmp_path), "args": [mate, f"[from captain via desk] {message}"]}]
        assert f"routed to {mate}\n{message}" in text(notes)
        assert text(notes).count("photon-work ") == 1
        assert text(fake / "sent") == ""
        assert [r["text"] for r in records() if r["kind"] == "owner"] == [message]
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("work", message)
        desk_clock()
        assert text(fake / "mate-sends").splitlines() == [json.dumps(sends[0])]
        assert text(notes).count("photon-work ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("message,decision", [
    ("Fix the website and database exports", {"domains": ["web-mate", "data-mate"]}),
    ("Can you handle that?", {"confidence": "low"}),
    ("Approved, go ahead with the website", {}),
    ("Merge the website change", {}),
    ("Choose which website design we should use", {}),
    ("The website password is a test value", {}),
    ("Fix the website menu", {"target": "unknown-mate", "domains": ["unknown-mate"]}),
    ("Fix the website menu", {"category": "approval"}),
    ("Fix the website menu", {"target": "firstmate"}),
])
def test_unsafe_or_uncertain_routes_keep_firstmate(tmp_path, desk_clock, message, decision):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "answer").write_text(json.dumps({
        "target": "web-mate", "confidence": "high", "domains": ["web-mate"], "category": "work", **decision,
    }))
    bridge = start(1)
    try:
        receive("work", message)
        desk_clock()
        wait_for(lambda: "photon-work " in text(notes), "the normal handoff")
        assert message in text(notes)
        assert "routed to " not in text(notes)
        assert text(fake / "mate-sends") == ""
        assert text(fake / "sent") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("failure", ["send-fail", "missing-sender", "model-fail", "invalid-json"])
def test_route_failure_falls_back_to_firstmate(tmp_path, desk_clock, failure):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    if failure == "missing-sender":
        (tmp_path / "bin/fm-send.sh").unlink()
    elif failure == "invalid-json":
        (fake / "answer").write_text("not JSON")
    else:
        (fake / failure).touch()
    bridge = start(1)
    try:
        receive("work", "Fix the website menu")
        desk_clock()
        wait_for(lambda: "photon-work " in text(notes), "the fallback handoff")
        assert "Fix the website menu" in text(notes)
        assert "routed to " not in text(notes)
        assert text(notes).count("photon-work ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_firstmate_note_retries_without_resending_to_mate(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "inbox-fail").touch()
    bridge = start(1)
    try:
        receive("work", "Fix the website menu")
        desk_clock()
        wait_for(lambda: "routing retains the request" in text(err), "the retained routing note")
        bridge.terminate()
        bridge.wait(10)
        assert len(text(fake / "mate-sends").splitlines()) == 1
        (fake / "inbox-fail").unlink()
        bridge = start(2)
        wait_for(lambda: "routed to web-mate" in text(notes), "the recovered routing note")
        assert len(text(fake / "mate-sends").splitlines()) == 1
        assert text(notes).count("photon-work ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("registry", [None, "# Second mates\n", "- web-mate - Missing scope (home: /unused;)\n"])
def test_missing_or_empty_registry_keeps_existing_handoff(tmp_path, desk_clock, registry):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    path = tmp_path / "data/secondmates.md"
    if registry is None:
        path.unlink()
    else:
        path.write_text(registry)
    bridge = start(1)
    try:
        receive("work", "Fix the website menu")
        desk_clock()
        wait_for(lambda: "photon-work " in text(notes), "the single-home handoff")
        assert text(fake / "mate-sends") == ""
        assert text(fake / "model-calls") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_firstmate_activity_cancels_pending_mate_route(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("work", "Fix the website menu")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the held routing decision")
        cli("--typing")
        wait_for(lambda: "photon-work " in text(notes), "the stand-down handoff")
        (fake / "model-hold").unlink()
        assert text(fake / "mate-sends") == ""
        assert "routed to " not in text(notes)
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_registry_changes_apply_without_restart(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    path = tmp_path / "data/secondmates.md"
    table = path.read_text()
    path.unlink()
    bridge = start(1)
    try:
        receive("before", "Fix the website menu")
        wait_for(lambda: "photon-before " in text(notes), "the initial Firstmate handoff")
        path.write_text(table)
        receive("after", "Fix the website layout")
        desk_clock()
        wait_for(lambda: "routed to web-mate" in text(notes), "the added routing table")
        (fake / "model-started").unlink()
        (fake / "model-hold").touch()
        receive("removed", "Fix the website footer")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the next routing decision")
        path.unlink()
        (fake / "model-hold").unlink()
        wait_for(lambda: "photon-removed " in text(notes), "the removed-table fallback")
        assert len(text(fake / "mate-sends").splitlines()) == 1
        assert text(notes).count("routed to web-mate") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_multi_mate_burst_hands_every_text_to_firstmate(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "answer").write_text(json.dumps({
        "target": "firstmate", "confidence": "high", "domains": ["web-mate", "data-mate"], "category": "work",
    }))
    bridge = start(1)
    try:
        receive("website", "Fix the website menu")
        receive("database", "Fix the database export too")
        desk_clock()
        wait_for(lambda: "photon-database " in text(notes), "the whole-burst handoff")
        assert text(notes).count("photon-website ") == text(notes).count("photon-database ") == 1
        assert text(fake / "mate-sends") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_sender_timeout_preserves_uncertainty_for_firstmate(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "send-timeout").touch()
    bridge = start(1)
    try:
        receive("work", "Fix the website menu")
        desk_clock()
        wait_for(lambda: text(fake / "mate-sends"), "the active sender")
        started = time.monotonic()
        desk_clock(4000)
        assert time.monotonic() - started < 2
        wait_for(lambda: "photon-work " in text(notes), "the uncertain-delivery handoff")
        assert "Delivery to web-mate may be incomplete" in text(notes)
        assert "Fix the website menu" in text(notes)
        assert len(text(fake / "mate-sends").splitlines()) == 1
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        receive("work", "Fix the website menu")
        desk_clock()
        assert len(text(fake / "mate-sends").splitlines()) == 1
        assert text(notes).count("photon-work ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_scope_change_after_semicolon_cancels_stale_route(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "model-hold").touch()
    bridge = start(1)
    try:
        receive("work", "Fix the website menu")
        desk_clock()
        wait_for(lambda: (fake / "model-started").exists(), "the pending scope decision")
        call = json.loads(text(fake / "model-calls").splitlines()[-1])
        system = call["args"][call["args"].index("--system-prompt") + 1]
        assert json.loads(system.splitlines()[-1]) == [{"id": mate, "scope": scope} for mate, scope in SCOPES.items()]
        path = tmp_path / "data/secondmates.md"
        path.write_text(path.read_text().replace("exclude native applications", "reports only"))
        (fake / "model-hold").unlink()
        wait_for(lambda: "photon-work " in text(notes), "the stale-scope handoff")
        assert text(fake / "mate-sends") == ""
    finally:
        bridge.terminate()
        bridge.wait(10)


def test_same_mate_burst_delivers_each_text_once(tmp_path, desk_clock):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    messages = ["Fix the website menu", "Fix the website footer", "Fix the website header"]
    bridge = start(1)
    try:
        for index, message in enumerate(messages):
            receive(str(index), message)
        desk_clock()
        wait_for(lambda: text(notes).count("routed to web-mate") == 3, "the complete mate handoff")
        sends = [json.loads(line) for line in text(fake / "mate-sends").splitlines()]
        assert [send["args"] for send in sends] == [
            ["web-mate", f"[from captain via desk] {message}"] for message in messages
        ]
        for index in range(3):
            assert text(notes).count(f"photon-{index} ") == 1
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.parametrize("cancel", ["inbound", "firstmate", "shutdown"])
def test_slow_mate_sender_allows_cancellation_and_keeps_uncertainty(tmp_path, desk_clock, cancel):
    fake, state, notes, err, start, receive, cli, text, records = routing_rig(tmp_path)
    (fake / "mate-hold").touch()
    bridge = start(1)
    try:
        for index in range(3):
            receive(str(index), f"Fix the website section {index}")
        desk_clock()
        wait_for(lambda: text(fake / "mate-sends"), "the held mate sender")
        assert text(notes) == ""
        started = time.monotonic()
        desk_clock(4000)
        if cancel == "inbound":
            receive("new", "Fix the database export")
        elif cancel == "firstmate":
            assert cli("--typing") == "typing\n"
        else:
            bridge.terminate()
            bridge.wait(10)
        wait_for(lambda: (fake / "send-cancelled").exists(), "sender cancellation", timeout=2)
        assert time.monotonic() - started < 2
        (fake / "mate-hold").unlink()
        if cancel != "shutdown":
            wait_for(lambda: "photon-2 " in text(notes), "the cancelled burst handoff")
            bridge.terminate()
            bridge.wait(10)
        bridge = start(2)
        wait_for(lambda: "photon-2 " in text(notes), "the recovered burst handoff")
        assert len(text(fake / "mate-sends").splitlines()) == 1
        assert text(notes).count("Delivery to web-mate may be incomplete") == 1
        for index in range(3):
            assert text(notes).count(f"photon-{index} ") == 1
        assert "routed to web-mate" not in text(notes)
    finally:
        bridge.terminate()
        bridge.wait(10)
