"""apps/imessage/instagram-graph.ts: fm-insta-reply on the official Instagram API, run with bun against a fake Graph API.

Covers the 24-hour window, the refusals (no Graph call), the call order and bodies, the sent rows, and the token file.
"""

import json
import os
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

CLI = str(Path(__file__).parents[1] / "apps/imessage/instagram-graph.ts")
OP = "1784"
TOKEN = "IGAAfake-token-123"

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


@pytest.fixture
def graph():
    """A fake Graph API: `graph.calls` records each request; set `graph.answer` to (status, json)."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.answer()

        def do_POST(self):
            self.answer()

        def answer(self):
            url = urlsplit(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            server.calls.append({
                "method": self.command,
                "path": url.path,
                "query": parse_qs(url.query),
                "auth": self.headers.get("Authorization"),
                "body": json.loads(body) if body else None,
            })
            status, payload = server.answer
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.calls, server.answer = [], (200, {"recipient_id": OP, "message_id": "m-out"})
    server.url = f"http://127.0.0.1:{server.server_address[1]}"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server
    server.shutdown()


@pytest.fixture
def ig(tmp_path):
    """The state dir: a fresh token and one DM of the operator 1 h ago."""
    d = tmp_path / "ig"
    d.mkdir()
    (d / "graph-token.json").write_text(json.dumps({"token": TOKEN, "at": int(time.time())}))
    dm(d, 3600)
    return d


@pytest.fixture
def run(ig, graph):
    """Run the CLI on `ig` against the fake Graph API."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("INSTAGRAM_")}
    env |= {"INSTAGRAM_DM_DIR": str(ig), "INSTAGRAM_DM_OPERATOR": OP, "INSTAGRAM_GRAPH_URL": graph.url}
    return lambda *args, stdin=None: subprocess.run(
        ["bun", CLI, *args], env=env, input=stdin, capture_output=True, text=True, timeout=30
    )


def dm(d, ago, mid="mid-1", thread=OP):
    row = {"at": int(time.time() - ago), "id": mid, "thread": thread, "sender": thread, "type": "text", "text": "hi"}
    with (d / "messages.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


def sent(d):
    return [json.loads(row) for row in (d / "sent.jsonl").read_text().splitlines()]


def test_a_text_inside_the_window_goes_to_the_operator(ig, graph, run):
    r = run("reply", "  got   it,\n watching ")
    assert r.returncode == 0, r.stderr
    [call] = graph.calls
    assert call["method"] == "POST" and call["path"] == "/v25.0/me/messages"
    assert call["auth"] == f"Bearer {TOKEN}"
    assert call["body"] == {"recipient": {"id": OP}, "message": {"text": "got it, watching"}}
    [row] = sent(ig)
    assert row["thread"] == OP and row["kind"] == "text" and row["text"] == "got it, watching" and row["by"] == "firstmate"


def test_typing_react_and_text_go_in_order_and_the_react_hits_his_last_dm(ig, graph, run):
    dm(ig, 60, mid="mid-2")
    dm(ig, 30, mid="other", thread="999")  # another sender's row is not his last DM
    long = "x" * 120
    r = run("reply", "--react", "\U0001f440", "--thread", OP, "--typing", "--", long)
    assert r.returncode == 0, r.stderr
    assert [c["body"] for c in graph.calls] == [
        {"recipient": {"id": OP}, "sender_action": "typing_on"},
        {"recipient": {"id": OP}, "sender_action": "react", "payload": {"message_id": "mid-2", "reaction": "\U0001f440"}},
        {"recipient": {"id": OP}, "message": {"text": long}},
    ]
    assert [(s["kind"], s.get("text")) for s in sent(ig)] == [("typing", None), ("react", "\U0001f440"), ("text", long)]


@pytest.mark.parametrize(
    ("setup", "args", "reason"),
    [
        (
            lambda d: (d / "messages.jsonl").unlink() or dm(d, 30 * 3600 + 60),
            ("reply", "hi"),
            "outside the 24-hour window: his last DM was 30 h ago",
        ),
        (lambda d: None, ("reply", "hi", "--thread", "999"), "thread 999 is not the operator's"),
        (lambda d: (d / "stop").write_text("stopped by hand"), ("reply", "hi"), "the line is stopped (stopped by hand)"),
        (lambda d: (d / "graph-token.json").unlink(), ("reply", "hi"), "no token in"),
    ],
)
def test_refusals_make_no_graph_call(ig, graph, run, setup, args, reason):
    setup(ig)
    r = run(*args)
    assert r.returncode == 1 and r.stderr.startswith("not sending: ") and reason in r.stderr
    assert graph.calls == [] and not (ig / "sent.jsonl").exists()


def test_a_graph_error_exits_without_the_token(ig, graph, run):
    graph.answer = (400, {"error": {"message": f"bad token {TOKEN}"}})
    r = run("reply", "hi")
    assert r.returncode == 1 and "send failed: text HTTP 400 bad token" in r.stderr
    assert TOKEN not in r.stdout + r.stderr and not (ig / "sent.jsonl").exists()


def test_token_is_saved_0600_and_never_printed(ig, run):
    r = run("token", stdin=f"  {TOKEN}-new\n")
    assert r.returncode == 0 and r.stdout == "token saved\n" and TOKEN not in r.stdout + r.stderr
    f = ig / "graph-token.json"
    assert f.stat().st_mode & 0o777 == 0o600
    saved = json.loads(f.read_text())
    assert saved["token"] == f"{TOKEN}-new" and abs(saved["at"] - time.time()) < 5


def test_refresh_waits_until_the_token_is_a_day_old(ig, graph, run):
    r = run("refresh")
    assert r.returncode == 0 and "refresh not due" in r.stdout and graph.calls == []


def test_refresh_saves_the_new_token(ig, graph, run):
    (ig / "graph-token.json").write_text(json.dumps({"token": TOKEN, "at": int(time.time()) - 7 * 86400}))
    graph.answer = (200, {"access_token": "IGAAnew", "token_type": "bearer", "expires_in": 5184000})
    r = run("refresh")
    assert r.returncode == 0 and r.stdout == "token refreshed; expires in 60 days\n", r.stderr
    [call] = graph.calls
    assert call["method"] == "GET" and call["path"] == "/refresh_access_token"
    assert call["query"] == {"grant_type": ["ig_refresh_token"], "access_token": [TOKEN]}
    saved = json.loads((ig / "graph-token.json").read_text())
    assert saved["token"] == "IGAAnew" and abs(saved["at"] - time.time()) < 5
    assert (ig / "graph-token.json").stat().st_mode & 0o777 == 0o600


def test_a_failed_refresh_exits_1_without_the_token(ig, graph, run):
    (ig / "graph-token.json").write_text(json.dumps({"token": TOKEN, "at": int(time.time()) - 7 * 86400}))
    graph.answer = (400, {"error": {"message": f"Session for {TOKEN} has expired"}})
    r = run("refresh")
    assert r.returncode == 1 and "refresh failed: HTTP 400" in r.stderr
    assert TOKEN not in r.stdout + r.stderr
    assert json.loads((ig / "graph-token.json").read_text())["token"] == TOKEN
