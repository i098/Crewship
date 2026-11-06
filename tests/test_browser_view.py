"""browser-view lists CDP browsers and shows them read-only: headed tabs as a live screencast, headless as screenshots."""

import base64
import hashlib
import importlib.util
import json
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "blueprint" / "maintenance" / "browser-view.py"
spec = importlib.util.spec_from_file_location("browser_view", SCRIPT)
bv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bv)

GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
JPEG = base64.b64encode(b"jpeg-bytes").decode()


def ws_read(sock):
    b0, b1 = sock.recv(2)
    size = b1 & 0x7F
    if size == 126:
        size = struct.unpack(">H", sock.recv(2))[0]
    mask = sock.recv(4)
    data = b""
    while len(data) < size:
        data += sock.recv(size - len(data))
    return json.loads(bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def ws_write(sock, obj):
    data = json.dumps(obj).encode()
    sock.sendall(bytes([0x81, 126]) + struct.pack(">H", len(data)) + data)


class FakeChrome:
    """A DevTools endpoint: HTTP discovery plus a websocket that records every CDP method it is sent."""

    def __init__(self, browser):
        self.methods = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path == "/json/version":
                    body = {"Browser": browser}
                elif self.path == "/json/list":
                    body = [
                        {
                            "id": "T1",
                            "type": "page",
                            "title": "Home",
                            "url": "https://example.test/",
                            "webSocketDebuggerUrl": f"ws://127.0.0.1:{outer.port}/devtools/page/T1",
                        },
                        {
                            "id": "W1",
                            "type": "service_worker",
                            "title": "sw",
                            "url": "https://example.test/sw.js",
                        },
                    ]
                else:
                    return self.websocket()
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def websocket(self):
                accept = base64.b64encode(
                    hashlib.sha1(self.headers["Sec-WebSocket-Key"].encode() + GUID).digest()
                ).decode()
                self.wfile.write(
                    f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: {accept}\r\n\r\n".encode()
                )
                self.wfile.flush()
                sock = self.connection
                try:
                    while True:
                        msg = ws_read(sock)
                        outer.methods.append(msg["method"])
                        ws_write(sock, {"id": msg["id"], "result": {"data": JPEG}})
                        if msg["method"] == "Page.startScreencast":
                            ws_write(
                                sock,
                                {
                                    "method": "Page.screencastFrame",
                                    "params": {"data": JPEG, "sessionId": 7},
                                },
                            )
                except (OSError, ValueError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def test_discover_lists_pages_only_and_marks_headed_by_tier_and_version():
    headless, headed = FakeChrome("HeadlessChrome/140"), FakeChrome("Chrome/140")
    try:
        found = bv.discover({headed.port: ("chrome", "up"), 1: ("voxl", "down")})
        by_port = {b["port"]: b for b in found}
        assert by_port[headed.port]["headed"] and by_port[headed.port]["name"] == "chrome"
        assert [t["title"] for t in by_port[headed.port]["tabs"]] == [
            "Home"
        ]  # the service worker is no tab
        assert (
            by_port[1]["state"] == "down" and by_port[1]["tabs"] == []
        )  # a down tier stays listed
        other = bv.discover({})
        mine = next(b for b in other if b["port"] == headless.port)
        assert (
            mine["name"] == "headless chrome"
            and not mine["headed"]
            and mine["tabs"][0]["headed"] is False
        )
    finally:
        headless.close()
        headed.close()


def test_screencast_acks_each_frame_and_screenshot_is_read_only():
    chrome = FakeChrome("Chrome/140")
    try:
        ws = f"ws://127.0.0.1:{chrome.port}/devtools/page/T1"
        cdp = bv.start_screencast(ws)
        assert bv.frame(cdp) is None  # the startScreencast reply is not a frame
        assert bv.frame(cdp) == b"jpeg-bytes"
        bv.frame(cdp)  # the ack's reply
        cdp.close()
        assert bv.capture(ws) == b"jpeg-bytes"
        for _ in range(50):
            if "Page.captureScreenshot" in chrome.methods:
                break
            threading.Event().wait(0.02)
        assert chrome.methods[:2] == ["Page.startScreencast", "Page.screencastFrameAck"]
        assert set(chrome.methods) <= {
            "Page.startScreencast",
            "Page.screencastFrameAck",
            "Page.captureScreenshot",
        }
    finally:
        chrome.close()


def test_fleet_status_ignores_the_session_line(monkeypatch, tmp_path):
    fake = tmp_path / "fleet-browser"
    fake.write_text(
        "#!/bin/sh\necho 'TIER PORT STATE'\necho 'obscura 9222 up 0 default'\necho 'session: 709 cookies in jar'\n"
    )
    fake.chmod(0o755)
    monkeypatch.setattr(bv, "FLEET_BROWSER", str(fake))
    assert bv.fleet_tiers() == {9222: ("obscura", "up")}


def test_obscura_placeholder_page_gets_an_explanation_not_a_raw_error(monkeypatch):
    def refuse(_ws):
        raise RuntimeError("No page for session")

    monkeypatch.setattr(bv, "capture", refuse)
    preview, note = bv.shoot({"ws": "ws://x/y", "url": "about:blank"}, (80, 24), 4, "symbols")
    assert preview == [] and "client's session" in note
