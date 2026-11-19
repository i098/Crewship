"""fm-call pager backup: a fake Twilio and a fake Bark run on localhost; no real call or page is made."""

import json
import os
import subprocess
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

FM_CALL = Path(__file__).parents[1] / "apps/imessage/fm-call"
NOON = int(
    datetime(2026, 11, 18, 12, tzinfo=ZoneInfo("America/Los_Angeles")).timestamp()
)  # outside quiet hours
KEY = "bark-secret-key"


@pytest.fixture
def fakes():
    """Serve Twilio (create call, then report the status in `state`) and Bark (record pushes)."""
    state = {"status": "completed", "pushes": [], "bark_http": 200}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            if self.path == "/push":
                state["pushes"].append(json.loads(raw))
                self.reply(state["bark_http"], {})
            else:
                self.reply(201, {"sid": "CA1"})

        def do_GET(self):
            self.reply(200, {"status": state["status"]})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


def ring(tmp_path, fakes, key=KEY):
    home = tmp_path / "home"
    home.mkdir()
    (tmp_path / "say").write_text("#!/bin/sh\nexit 0\n")
    (tmp_path / "say").chmod(0o755)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "SECRETS_FILE": str(tmp_path / "none.env"),
        "FM_CALL_STATE": str(tmp_path / "state"),
        "FM_CALL_IMESSAGE": str(tmp_path / "say"),
        "FM_CALL_NOW": str(NOON),
        "FM_CALL_TWILIO_URL": fakes["url"],
        "FM_CALL_BARK_URL": fakes["url"],
        "FM_CALL_POLL": "0",
        "TWILIO_ACCOUNT_SID": "ACx",
        "TWILIO_AUTH_TOKEN": "tok",
        "TWILIO_FROM": "+15550000001",
        "PERSONAL_PHONE": "+15550000002",
    }
    if key:
        env["BARK_DEVICE_KEY"] = key
    return subprocess.run(
        [str(FM_CALL), "--class", "asked", "disk full"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_answered_call_sends_no_page(tmp_path, fakes):
    fakes["status"] = "completed"
    assert ring(tmp_path, fakes).returncode == 0
    assert fakes["pushes"] == []


@pytest.mark.parametrize("status", ["no-answer", "busy", "canceled", "failed"])
def test_unanswered_call_sends_one_critical_page(tmp_path, fakes, status):
    fakes["status"] = status
    result = ring(tmp_path, fakes)
    assert result.returncode == 0
    assert len(fakes["pushes"]) == 1
    assert fakes["pushes"][0] | {"device_key": ""} == {
        "device_key": "",
        "title": "Firstmate called you (asked)",
        "body": "disk full",
        "level": "critical",
        "volume": 10,
    }
    assert KEY not in result.stdout + result.stderr


def test_missing_key_warns_and_does_not_crash(tmp_path, fakes):
    fakes["status"] = "no-answer"
    result = ring(tmp_path, fakes, key="")
    assert result.returncode == 0
    assert "BARK_DEVICE_KEY is not set" in result.stderr
    assert fakes["pushes"] == []


def test_no_ring_sends_no_page(tmp_path, fakes):
    """A prod call with no earlier text only texts; nothing rings, so nothing pages."""
    fakes["status"] = "no-answer"
    (tmp_path / "home").mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "FM_CALL_STATE": str(tmp_path / "state"),
        "FM_CALL_IMESSAGE": "true",
        "FM_CALL_NOW": str(NOON),
        "FM_CALL_TWILIO_URL": fakes["url"],
        "FM_CALL_BARK_URL": fakes["url"],
        "BARK_DEVICE_KEY": KEY,
    }
    result = subprocess.run(
        [str(FM_CALL), "--class", "prod", "--incident", "i1", "db down"],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 3
    assert fakes["pushes"] == []
