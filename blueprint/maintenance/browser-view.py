#!/usr/bin/env python3
"""Read-only viewer for every local browser that speaks CDP (docs/herdr.md#browser-view).

Headed tabs (chrome, voxl tiers) are LIVE: a CDP screencast, each frame acked and drawn as it arrives.
Headless tabs (obscura, worker headless Chrome) get a screenshot every few seconds.
Lists the fleet-browser tiers (obscura, chrome, voxl) and any other DevTools port
on 127.0.0.1 (worker headless Chrome) with their tabs, and shows the selected tab, drawn by chafa. It only sends Page.captureScreenshot,
Page.startScreencast and Page.screencastFrameAck and reads /json/version and /json/list:
it never navigates, closes, clicks or types.

Keys: up/down or j/k select a tab, r refresh now, q quit.
`browser-view.py --list [--json]` prints the browsers and tabs once and exits.
"""

import argparse
import base64
import concurrent.futures
import http.client
import json
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import termios
import threading
import time
import tty
import urllib.request
from urllib.parse import urlparse

HOST = "127.0.0.1"
FLEET_BROWSER = os.environ.get(
    "FLEET_BROWSER", os.path.expanduser("~/oss-fleet/browsers/fleet-browser")
)


def fleet_tiers():
    """{port: (tier, state)} from `fleet-browser status`; empty when it is missing."""
    try:
        out = subprocess.run(
            [FLEET_BROWSER, "status"], capture_output=True, text=True, timeout=15
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    tiers = {}
    for line in out.splitlines():
        cols = line.split()
        if len(cols) >= 3 and cols[1].isdigit() and not cols[0].endswith(":"):
            tiers[int(cols[1])] = (cols[0], cols[2])
    return tiers


def listening_ports():
    """Loopback or wildcard TCP listeners, from /proc/net/tcp{,6} (state 0A)."""
    ports = set()
    for path, local in (
        ("/proc/net/tcp", "0100007F"),
        ("/proc/net/tcp6", "00000000000000000000000001000000"),
    ):
        try:
            rows = open(path).read().splitlines()[1:]
        except OSError:
            continue
        for row in rows:
            cols = row.split()
            addr, port = cols[1].split(":")
            if cols[3] == "0A" and (addr == local or set(addr) == {"0"}):
                ports.add(int(port, 16))
    return ports


def get_json(port, path, timeout=1.0):
    with urllib.request.urlopen(f"http://{HOST}:{port}{path}", timeout=timeout) as r:
        return json.load(r)


def headed(name, user_agent):
    """The chrome and voxl tiers and any non-headless Chrome have a window; obscura and HeadlessChrome do not.

    Chrome's --headless=new reports `Browser: Chrome/N`; only User-Agent says HeadlessChrome.
    Keep in step with tools/browser-tui/browser-tui.ts, which reads the same field.
    """
    return name != "obscura" and "Headless" not in user_agent


def probe(port, tier=None):
    """One browser dict, or None when the port is not a DevTools endpoint."""
    try:
        version = get_json(port, "/json/version")
        if "Chrome" not in version.get("Browser", "") and not tier:
            return None
        tabs = [t for t in get_json(port, "/json/list") if t.get("type") == "page"]
    except (OSError, http.client.HTTPException, ValueError, AttributeError, TypeError):
        return None
    ua, build = version.get("User-Agent", ""), version.get("Browser", "")
    name = tier[0] if tier else ("headless chrome" if "Headless" in ua else "chrome")
    is_headed = headed(name, ua)
    return {
        "name": name,
        "port": port,
        "state": "up",
        "headed": is_headed,
        "version": build,
        "tabs": [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "headed": is_headed,
                "ws": t.get("webSocketDebuggerUrl"),
            }
            for t in tabs
        ],
    }


def discover(tiers=None):
    """Fleet tiers first (a down tier stays listed), then other DevTools ports by number."""
    tiers = fleet_tiers() if tiers is None else tiers
    with concurrent.futures.ThreadPoolExecutor(16) as pool:
        found = list(pool.map(lambda p: probe(p, tiers.get(p)), sorted(listening_ports())))
    browsers = {b["port"]: b for b in found if b}
    for port, (name, state) in tiers.items():
        browsers.setdefault(
            port,
            {
                "name": name,
                "port": port,
                "state": state,
                "headed": name != "obscura",
                "version": "",
                "tabs": [],
            },
        )
    return sorted(browsers.values(), key=lambda b: (b["port"] not in tiers, b["port"]))


# ---- screenshot over a minimal websocket client ------------------------------------------


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("websocket closed")
        buf += chunk
    return buf


def _send_text(sock, text):
    data = text.encode()
    head = bytearray([0x81])
    mask = os.urandom(4)
    if len(data) < 126:
        head.append(0x80 | len(data))
    elif len(data) < 65536:
        head += bytes([0x80 | 126]) + struct.pack(">H", len(data))
    else:
        head += bytes([0x80 | 127]) + struct.pack(">Q", len(data))
    sock.sendall(bytes(head) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))


def _recv_message(sock):
    payload = b""
    while True:
        b0, b1 = _recv_exact(sock, 2)
        size = b1 & 0x7F
        if size == 126:
            size = struct.unpack(">H", _recv_exact(sock, 2))[0]
        elif size == 127:
            size = struct.unpack(">Q", _recv_exact(sock, 8))[0]
        data = _recv_exact(sock, size)
        if b0 & 0x0F == 8:
            raise ConnectionError("websocket closed")
        if b0 & 0x0F in (0, 1, 2):
            payload += data
            if b0 & 0x80:
                return payload.decode()


class Cdp:
    """One CDP websocket to a tab. Only read methods are sent through it."""

    def __init__(self, ws_url, timeout=10.0):
        u = urlparse(ws_url)
        self.sock = socket.create_connection((u.hostname, u.port), timeout=timeout)
        self.next_id = 0
        try:
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall(
                (
                    f"GET {u.path} HTTP/1.1\r\nHost: {u.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            head = b""
            while b"\r\n\r\n" not in head:
                head += _recv_exact(self.sock, 1)
            if b" 101 " not in head.split(b"\r\n")[0]:
                raise ConnectionError(head.split(b"\r\n")[0].decode(errors="replace"))
        except BaseException:
            self.sock.close()
            raise

    def send(self, method, **params):
        self.next_id += 1
        _send_text(self.sock, json.dumps({"id": self.next_id, "method": method, "params": params}))
        return self.next_id

    def recv(self):
        return json.loads(_recv_message(self.sock))

    def close(self):
        self.sock.close()


def capture(ws_url):
    """JPEG bytes of the tab at ws_url via Page.captureScreenshot. Short timeout: this runs on the UI loop."""
    cdp = Cdp(ws_url, timeout=2.0)
    try:
        want = cdp.send("Page.captureScreenshot", format="jpeg", quality=70)
        while True:
            msg = cdp.recv()
            if msg.get("id") == want:
                if "error" in msg:
                    raise RuntimeError(msg["error"].get("message", "captureScreenshot failed"))
                return base64.b64decode(msg["result"]["data"])
    finally:
        cdp.close()


def start_screencast(ws_url):
    """A Cdp streaming Page.screencastFrame events; frame() acks each one."""
    cdp = Cdp(ws_url)
    cdp.send("Page.startScreencast", format="jpeg", quality=70, everyNthFrame=1)
    return cdp


def frame(cdp):
    """Read messages until one screencast frame; ack it so the browser sends the next. None on other traffic."""
    msg = cdp.recv()
    if msg.get("error"):
        raise RuntimeError(msg["error"].get("message", "startScreencast failed"))
    if msg.get("method") != "Page.screencastFrame":
        return None
    cdp.send("Page.screencastFrameAck", sessionId=msg["params"]["sessionId"])
    return base64.b64decode(msg["params"]["data"])


def render(image, cols, rows, fmt):
    """chafa output for the image, as lines."""
    out = subprocess.run(
        ["chafa", "-f", fmt, "-s", f"{cols}x{rows}", "--animate=off", "-"],
        input=image,
        capture_output=True,
        timeout=15,
    )
    if out.returncode:
        raise RuntimeError(out.stderr.decode(errors="replace").strip() or "chafa failed")
    return out.stdout.decode(errors="replace").splitlines()


# ---- terminal UI ---------------------------------------------------------------------------


def rows_of(browsers):
    """Flat selectable rows: ('browser', b) headings and ('tab', b, tab) entries."""
    rows = []
    for b in browsers:
        rows.append(("browser", b, None))
        rows += [("tab", b, t) for t in b["tabs"]]
    return rows


def clip(text, width):
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


def draw(browsers, sel, preview, note, size):
    cols, lines = size
    rows = rows_of(browsers)
    tabs = [i for i, r in enumerate(rows) if r[0] == "tab"]
    list_h = min(len(rows), max(lines // 3, 4))
    cur = tabs[sel] if tabs else 0
    top = min(max(cur - list_h + 2, 0), max(len(rows) - list_h, 0))
    out = ["\x1b[H\x1b[2J"]
    for i, (kind, b, t) in enumerate(rows[top : top + list_h]):
        if kind == "browser":
            state = "" if b["state"] == "up" else f" [{b['state']}]"
            text = clip(
                f"{b['name']}  :{b['port']}  {b['version']}{state}  {len(b['tabs'])} tab(s)", cols
            )
            out.append(f"\x1b[1m{text}\x1b[0m\r\n")
        else:
            mark = "\x1b[7m" if top + i == cur else ""
            out.append(
                f"{mark}{clip('  ' + (t['title'] or '(untitled)') + '  ' + t['url'], cols)}\x1b[0m\r\n"
            )
    out.append(f"\x1b[2m{clip(note or 'up/down select  r refresh  q quit', cols)}\x1b[0m\r\n")
    for line in (preview or [])[: max(lines - list_h - 2, 0)]:
        out.append(line + "\x1b[0m\r\n")
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def shoot(tab, size, list_rows, fmt):
    """(preview lines, note) for the tab; a failed capture becomes the note."""
    cols, lines = size
    try:
        if not tab.get("ws"):
            raise RuntimeError("tab has no debugger URL")
        return render(
            capture(tab["ws"]), cols, max(lines - list_rows - 2, 1), fmt
        ), f"{time.strftime('%H:%M:%S')}  {tab['url']}"
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as e:
        # obscura lists a placeholder page-1; its real pages exist only inside the client session that opened them.
        why = (
            "obscura pages live in their client's session, no shared view"
            if "No page for session" in str(e)
            else e
        )
        return [], f"no screenshot: {why}"


class Viewer:
    """Viewer state. Headed tabs stream a CDP screencast, drawn as each frame arrives (at most --fps a second); headless ones get a screenshot every --interval."""

    def __init__(self, args):
        self.args = args
        self.browsers, self.sel, self.preview, self.note = [], 0, [], ""
        self.last_scan = self.last_shot = self.last_draw = 0.0
        self.shown = self.live = self.latest = self.scanning = self.found = None

    def select_tab(self, tab):
        """Switch the screencast to the newly selected tab."""
        if self.live:
            self.live.close()
        self.live = self.latest = None
        self.preview, self.shown, self.last_shot = [], tab and tab["id"], 0.0
        if tab and tab["headed"] and tab["ws"] and not self.args.no_live:
            try:
                self.live = start_screencast(tab["ws"])
            except OSError as e:
                self.note = f"no screencast: {e}"

    def update_preview(self, tab, size, list_h, now):
        if not tab:
            self.preview, self.note = [], "no browser tabs"
        elif self.live is None and now - self.last_shot >= self.args.interval:
            self.preview, self.note = shoot(tab, size, list_h, self.args.format)
            self.last_shot = now
        if self.latest and now - self.last_draw >= 1 / self.args.fps:
            try:
                self.preview = render(
                    self.latest, size[0], max(size[1] - list_h - 2, 1), self.args.format
                )
                self.note = f"LIVE  {tab['url']}"
            except (RuntimeError, subprocess.SubprocessError) as e:
                self.note = f"no screencast: {e}"
            self.latest, self.last_draw = None, now

    def read_frame(self):
        try:
            self.latest = frame(self.live) or self.latest
        except (OSError, RuntimeError, ValueError) as e:
            self.live.close()
            self.live, self.note, self.shown = None, f"screencast ended: {e}", None

    def key(self, key):
        """Handle one keypress; False quits."""
        if key in (b"q", b"\x03"):
            return False
        if key in (b"j", b"\x1b[B"):
            self.sel += 1
        elif key in (b"k", b"\x1b[A"):
            self.sel = max(self.sel - 1, 0)
        elif key == b"r":
            self.last_scan = self.last_shot = 0.0
        return True

    def scan(self, now):
        """Rescan in a worker thread; the loop keeps drawing and reading keys meanwhile."""
        if self.scanning is not None and not self.scanning.is_alive():
            self.scanning = None
            if self.found is not None:
                self.browsers, self.found = self.found, None
        if self.scanning is None and now - self.last_scan >= self.args.refresh:

            def work():
                self.found = discover()

            self.scanning, self.last_scan = threading.Thread(target=work, daemon=True), now
            self.scanning.start()

    def step(self, fd):
        """One loop turn; False quits."""
        now = time.monotonic()
        self.scan(now)
        tabs = [t for b in self.browsers for t in b["tabs"]]
        self.sel = min(self.sel, max(len(tabs) - 1, 0))
        size = shutil.get_terminal_size()
        list_h = min(len(rows_of(self.browsers)), max(size.lines // 3, 4))
        tab = tabs[self.sel] if tabs else None
        if (tab and tab["id"]) != self.shown:
            self.select_tab(tab)
        self.update_preview(tab, size, list_h, now)
        draw(self.browsers, self.sel, self.preview, self.note, size)
        ready = select.select([fd] + ([self.live.sock] if self.live else []), [], [], 0.2)[0]
        if self.live and self.live.sock in ready:
            self.read_frame()
        return fd not in ready or self.key(os.read(fd, 8))


def run(args):
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    viewer = Viewer(args)
    try:
        while viewer.step(fd):
            pass
    finally:
        if viewer.live:
            viewer.live.close()
        sys.stdout.write("\x1b[?25h\x1b[?1049l")
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="print browsers and tabs once and exit")
    ap.add_argument("--json", action="store_true", help="with --list, print JSON")
    ap.add_argument(
        "--refresh", type=float, default=3.0, help="seconds between browser and tab rescans"
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="seconds between screenshots of the selected tab",
    )
    ap.add_argument(
        "--no-live",
        action="store_true",
        help="screenshot headed tabs too instead of streaming a screencast",
    )
    ap.add_argument(
        "--fps",
        type=float,
        default=8.0,
        help="most screencast frames drawn per second for headed tabs",
    )
    ap.add_argument(
        "--format", default="symbols", help="chafa output format (symbols, kitty, sixels)"
    )
    args = ap.parse_args(argv)
    if args.list:
        browsers = discover()
        if args.json:
            print(json.dumps(browsers, indent=2))
            return 0
        for b in browsers:
            print(f"{b['name']}  :{b['port']}  {b['state']}  {b['version']}")
            for t in b["tabs"]:
                print(f"  {t['title'] or '(untitled)'}  {t['url']}")
        return 0
    if not sys.stdin.isatty() or not shutil.which("chafa"):
        print(
            "browser-view: needs a terminal and chafa (apt install chafa); use --list without them",
            file=sys.stderr,
        )
        return 1
    run(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
