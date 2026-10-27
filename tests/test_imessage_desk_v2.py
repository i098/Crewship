"""Exercise the installed bridge with local transports and a local front provider."""

import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import jsonschema
import pytest
from jinja2 import Environment
from test_imessage import ROOT, FallbackRig, publish_json, read_text, wait_for

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
MODEL = {
    "id": "anthropic/claude-haiku-5-5",
    "provider": "omp",
    "model": "anthropic/claude-haiku-5-5",
    "reasoning": ["low"],
    "apiKeyEnv": None,
}


def test_configuration_requires_boolean_and_defaults_to_legacy():
    schema = json.loads((ROOT / "blueprint/schemas/crewship.schema.json").read_text())
    section = schema["properties"]["crewship"]["properties"]["imessage"]
    for value in (False, True):
        jsonschema.validate({"owner": "+10000000000", "desk_v2": value}, section)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"owner": "+10000000000", "desk_v2": "true"}, section)
    env = Environment()
    env.filters["comment"] = lambda text: "# " + text
    template = env.from_string(
        (ROOT / "blueprint/ansible/templates/fm-imessage.service.j2").read_text()
    )
    for config, expected in (
        ({}, "false"),
        ({"desk_v2": False}, "false"),
        ({"desk_v2": True}, "true"),
    ):
        unit = template.render(
            ansible_managed="test",
            crewship_cfg={"imessage": config},
            crewship_instagram_dm_backend="off",
        )
        assert f'Environment="FM_IMESSAGE_DESK_V2={expected}"' in unit


@contextmanager
def desk_bridge(tmp_path, *, enabled=True, intent=None, restored=False):
    calls = []
    release = threading.Event()
    release.set()

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            release.wait(10)
            if "response_format" in body:
                answer = json.dumps(intent or {"kind": "dispatch", "model": 1, "reasoning": 1})
            else:
                answer = json.loads(body["messages"][1]["content"])["draft"]
            data = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
            self.send_response(200)
            self.end_headers()
            try:
                self.wfile.write(data)
            except BrokenPipeError:
                pass

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    rig = FallbackRig(
        tmp_path,
        FM_IMESSAGE_DESK_V2="true" if enabled else "false",
        FM_IMESSAGE_TEST="1",
        FM_IMESSAGE_TEST_QUIET_MS="50",
        INCEPTION_API_KEY="local-test",
        FM_DESK_INCEPTION_URL=endpoint,
    )
    (rig.fake / "edits").mkdir()
    (rig.app / "front.ts").write_text(f"""
import {{ runFront as front }} from {json.dumps(str(ROOT / "apps/imessage/front.ts"))};
export const loadFrontRedactor = async () => (text: string) => text;
export const runFront = (input) => front({{ ...input, endpoint: {json.dumps(endpoint)} }});
""")
    # Keep the bridge's auth loader real, but use the installed package instead of the worker stand-in.
    actual_omp = shutil.which("omp")
    if not actual_omp:
        rig.close()
        server.shutdown()
        pytest.skip("needs installed omp authentication modules")
    package_base = Path(actual_omp).resolve().parent
    credentials = tmp_path / "credentials.sqlite"
    with sqlite3.connect(credentials) as database:
        database.execute(
            "CREATE TABLE auth_credentials (provider TEXT, credential_type TEXT, data TEXT, disabled_cause TEXT)"
        )
        database.execute(
            "INSERT INTO auth_credentials VALUES (?, ?, ?, NULL)",
            ("anthropic", "api_key", '{"key":"fake-stored-key"}'),
        )
    bridge_source = (rig.app / "bridge.ts").read_text()
    policy = rig.app / "dispatch-policy.ts"
    policy_source = policy.read_text()
    package_marker = 'dirname(realpathSync(Bun.which("omp") ?? "omp"))'
    db_marker = "const path = getAgentDbPath(agentDir);"
    policy_marker = "dirname(realpathSync(executable))"
    assert package_marker in bridge_source
    assert db_marker in bridge_source
    assert policy_marker in policy_source
    (rig.app / "bridge.ts").write_text(
        bridge_source.replace(package_marker, json.dumps(str(package_base))).replace(
            db_marker, f"const path = {json.dumps(str(credentials))};"
        )
    )
    policy.write_text(policy_source.replace(policy_marker, json.dumps(str(package_base))))
    (tmp_path / "agent").mkdir()
    rig.env["PI_CODING_AGENT_DIR"] = str(tmp_path / "agent")
    rig.env.pop("ANTHROPIC_API_KEY", None)
    rig.env.pop("ANTHROPIC_OAUTH_TOKEN", None)
    (tmp_path / "agent/config.yml").write_text(json.dumps({"enabledModels": [MODEL["id"]]}))
    (tmp_path / "config").mkdir()
    (tmp_path / "config/crew-dispatch.json").write_text('{"rules":[]}')
    worker = tmp_path / "bin/omp"
    worker.write_text("""#!/usr/bin/env python3
import json, os, pathlib, sys, time
prompt = sys.stdin.read()
fake = pathlib.Path(os.environ['FAKE_DIR'])
if os.environ.get('FM_DESK_SERVER_TOOLS') == '1':
    with (fake / 'workers').open('a') as log:
        log.write(json.dumps({'pid': os.getpid(), 'question': os.environ['FM_DESK_QUESTION'], 'args': sys.argv, 'prompt': prompt}) + '\\n')
    while (fake / 'hold-worker').exists(): time.sleep(0.02)
    answer = {'kind': 'reply', 'answer': 'All systems are idle.', 'evidence': [{'source': 'status', 'quote': 'All systems are idle.'}]}
    print(json.dumps({'type': 'desk_result', 'drafted': json.dumps(answer), 'tools': {}, 'question': os.environ['FM_DESK_QUESTION']}))
else:
    print('SKIP')
""")
    worker.chmod(0o755)
    inbox = tmp_path / "bin/fm-inbox"
    inbox.write_text(f"""#!/usr/bin/env python3
import json, pathlib, sys
state = pathlib.Path({str(rig.state)!r})
if sys.argv[1] == 'status':
    events = [json.loads(line) for line in (state / 'routing.jsonl').read_text().splitlines()]
    assert any('plan' in event for event in events), 'status before plan'
    assert any(event.get('acknowledgement') for event in events), 'status before receipt'
    print('All systems are idle.')
with pathlib.Path({str(rig.notes)!r}).open('a') as log: log.write(' '.join(sys.argv[1:]) + '\\n')
""")
    inbox.chmod(0o755)
    try:
        if restored:
            rig.state.mkdir()
            (rig.state / "routing.jsonl").write_text(
                json.dumps(
                    {
                        "received": {
                            "requestId": "photon-protected",
                            "text": "My diagnosis is private.",
                            "firstmate": True,
                            "memoryId": 0,
                            "ref": {
                                "line": "photon",
                                "space": "iMessage;-;+10000000000",
                                "id": "protected",
                            },
                        }
                    }
                )
                + "\n"
            )
        rig.start()
        yield rig, calls, release
    finally:
        release.set()
        rig.close()
        server.shutdown()
        server.server_close()
        thread.join(5)


def send(rig, message_id, text):
    publish_json(
        rig.fake / "inbound" / f"{message_id}.json",
        {
            "id": message_id,
            "space": "iMessage;-;+10000000000",
            "sender": "+10000000000",
            "text": text,
        },
    )


def test_selected_entrypoint_saves_receipt_before_status_and_worker(tmp_path):
    with desk_bridge(tmp_path) as (rig, calls, _):
        credentials = tmp_path / "credentials.sqlite"
        before = credentials.read_bytes()
        send(rig, "status", "What is the current status?")
        wait_for(lambda: "All systems are idle." in read_text(rig.fake / "sent"), "factual answer")
        sent = read_text(rig.fake / "sent").splitlines()
        assert sent[0].endswith("I saved your request. I will check it.")
        assert sent[1].endswith("All systems are idle.")
        assert len(calls) == 2
        worker = json.loads(read_text(rig.fake / "workers"))
        assert worker["question"] == "What is the current status?"
        assert MODEL["model"] in worker["args"]
        assert "status" in read_text(rig.notes)
        assert "note --request-id photon-status" not in read_text(rig.notes)
        rig.stop()
        rig.start()
        assert read_text(rig.fake / "sent").splitlines() == sent
        assert credentials.read_bytes() == before


def test_legacy_entrypoint_never_calls_front(tmp_path):
    with desk_bridge(tmp_path, enabled=False) as (rig, calls, _):
        send(rig, "legacy", "Hello")
        wait_for(lambda: "photon-legacy" in read_text(rig.notes), "legacy handoff")
        assert calls == []
        assert not (rig.fake / "workers").exists()


@pytest.mark.parametrize("action", ["policy-change", "supervisor", "mute"])
def test_selected_loop_discards_stale_or_unapproved_work(tmp_path, action):
    with desk_bridge(tmp_path) as (rig, calls, release):
        release.clear()
        send(rig, "pending", "What is the current status?")
        wait_for(lambda: calls, "front request")
        if action == "policy-change":
            (tmp_path / "agent/config.yml").write_text('{"enabledModels":["missing/model"]}')
        elif action == "supervisor":
            rig.cli("The supervisor owns this request.")
        else:
            (rig.state / "muted").touch()
        release.set()
        if action == "policy-change":
            wait_for(lambda: "photon-pending" in read_text(rig.notes), "policy handoff")
        else:
            wait_for(lambda: "pending" in read_text(rig.fake / "read"), "transport acknowledgement")
            rig.stop()
        assert not (rig.fake / "workers").exists()


def test_new_request_cancels_worker_and_keeps_both_originals(tmp_path):
    with desk_bridge(tmp_path) as (rig, _, _):
        (rig.fake / "hold-worker").touch()
        send(rig, "first", "What is the current status?")
        wait_for(lambda: (rig.fake / "workers").exists(), "first worker")
        send(rig, "second", "Also check the current queue.")
        wait_for(
            lambda: len(read_text(rig.fake / "workers").splitlines()) == 2, "replacement worker"
        )
        first_pid = json.loads(read_text(rig.fake / "workers").splitlines()[0])["pid"]
        wait_for(lambda: not Path(f"/proc/{first_pid}").exists(), "cancelled worker exit")
        with pytest.raises(ProcessLookupError):
            os.kill(first_pid, 0)
        (rig.fake / "hold-worker").unlink()
        wait_for(
            lambda: "All systems are idle." in read_text(rig.fake / "sent"), "replacement answer"
        )
        workers = [json.loads(line) for line in read_text(rig.fake / "workers").splitlines()]
        assert (
            workers[1]["question"] == "What is the current status?\nAlso check the current queue."
        )
        assert read_text(rig.fake / "sent").count("All systems are idle.") == 1


def test_protected_request_cannot_dispatch(tmp_path):
    with desk_bridge(tmp_path) as (rig, _, _):
        send(rig, "protected", "Please deploy the service.")
        wait_for(lambda: "photon-protected" in read_text(rig.notes), "protected handoff")
        assert not (rig.fake / "workers").exists()


def test_restored_protected_request_never_reaches_front(tmp_path):
    with desk_bridge(tmp_path, restored=True) as (rig, calls, _):
        wait_for(lambda: "photon-protected" in read_text(rig.notes), "protected recovery handoff")
        assert calls == []
        assert not (rig.fake / "workers").exists()


@pytest.mark.parametrize("registered", [True, False])
def test_relay_rechecks_registry_and_preserves_accepted_ownership(tmp_path, registered):
    intent = {"kind": "relay", "target": 1, "domains": [1], "category": "work"}
    with desk_bridge(tmp_path, intent=intent) as (rig, calls, release):
        registry = tmp_path / "data/secondmates.md"
        registry.parent.mkdir()
        registry.write_text(
            f"- project - Project (home: {tmp_path / 'project'}; scope: project work; projects: project)\n"
        )
        sender = tmp_path / "bin/fm-send.sh"
        sender.write_text(f"#!/bin/sh\nprintf '%s\\n' \"$*\" >> {rig.fake / 'relayed'}\n")
        sender.chmod(0o755)
        release.clear()
        send(rig, "relay", "Build the project feature.")
        wait_for(lambda: calls, "relay proposal")
        if not registered:
            registry.write_text("")
        release.set()
        if registered:
            wait_for(
                lambda: "routed to project" in read_text(rig.state / "routing.jsonl"),
                "accepted relay",
            )
            before = read_text(rig.fake / "relayed")
            assert before.endswith("Build the project feature.\n")
            assert "note --request-id photon-relay" not in read_text(rig.notes)
            rig.stop()
            rig.start()
            assert read_text(rig.fake / "relayed") == before
        else:
            wait_for(lambda: "photon-relay" in read_text(rig.notes), "stale registry handoff")
            assert not (rig.fake / "relayed").exists()
        assert not (rig.fake / "workers").exists()


def test_social_reply_uses_no_worker_or_reaction(tmp_path):
    with desk_bridge(tmp_path, intent={"kind": "social", "text": "Hello."}) as (rig, _, _):
        send(rig, "social", "Hello")
        wait_for(lambda: "Hello." in read_text(rig.fake / "sent"), "social answer")
        assert "react" not in read_text(rig.fake / "sent")
        assert "status" not in read_text(rig.notes)
        assert not (rig.fake / "workers").exists()
