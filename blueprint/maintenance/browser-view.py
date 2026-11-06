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


def headed(name, version):
    """The chrome and voxl tiers and any non-headless Chrome have a window; obscura and HeadlessChrome do not."""
    return name != "obscura" and "Headless" not in version


def probe(port, tier=None):
    """One browser dict, or None when the port is not a DevTools endpoint."""
    try:
        version = get_json(port, "/json/version")
        if "Chrome" not in version.get("Browser", "") and not tier:
            return None
        tabs = [t for t in get_json(port, "/json/list") if t.get("type") == "page"]
    except (OSError, http.client.HTTPException, ValueError, AttributeError, TypeError):
        return None
    name = (
        tier[0]
        if tier
        else ("headless chrome" if "Headless" in version.get("Browser", "") else "chrome")
    )
    return {
        "name": name,
        "port": port,
        "state": "up",
        "headed": headed(name, version["Browser"]),
        "version": version["Browser"],
        "tabs": [
            {
                "id": t["id"],
                "title": t.get("title", ""),
                "url": t.get("url", ""),
                "headed": headed(name, version["Browser"]),
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
    """JPEG bytes of the tab at ws_url via Page.captureScreenshot."""
    cdp = Cdp(ws_url)
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
        return [], f"no screenshot: {e}"


def run(args):
    """Headed tabs stream a CDP screencast (a frame is drawn as it arrives, at most --fps a second); headless ones get a screenshot every --interval."""
    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    sys.stdout.write("\x1b[?1049h\x1b[?25l")
    browsers, sel, preview, note, last_scan, last_shot, shown = [], 0, [], "", 0.0, 0.0, None
    live, latest, last_draw = None, None, 0.0
    try:
        while True:
            now = time.monotonic()
            if now - last_scan >= args.refresh:
                browsers, last_scan = discover(), now
            tabs = [t for b in browsers for t in b["tabs"]]
            sel = min(sel, max(len(tabs) - 1, 0))
            size = shutil.get_terminal_size()
            list_h = min(len(rows_of(browsers)), max(size.lines // 3, 4))
            tab = tabs[sel] if tabs else None
            ident = tab["id"] if tab else None
            if ident != shown:
                if live:
                    live.close()
                live, latest, preview, shown, last_shot = None, None, [], ident, 0.0
                if tab and tab["headed"] and tab["ws"]:
                    try:
                        live = start_screencast(tab["ws"])
                    except OSError as e:
                        note = f"no screencast: {e}"
            if not tab:
                preview, note = [], "no browser tabs"
            elif live is None and now - last_shot >= args.interval:
                preview, note = shoot(tab, size, list_h, args.format)
                last_shot = now
            if latest and now - last_draw >= 1 / args.fps:
                try:
                    preview, note = (
                        render(latest, size[0], max(size[1] - list_h - 2, 1), args.format),
                        f"LIVE  {tab['url']}",
                    )
                except (RuntimeError, subprocess.SubprocessError) as e:
                    note = f"no screencast: {e}"
                latest, last_draw = None, now
            draw(browsers, sel, preview, note, size)
            ready = select.select([fd] + ([live.sock] if live else []), [], [], 0.2)[0]
            if live and live.sock in ready:
                try:
                    latest = frame(live) or latest
                except (OSError, RuntimeError, ValueError) as e:
                    live.close()
                    live, note, shown = None, f"screencast ended: {e}", None
            if fd in ready:
                key = os.read(fd, 8)
                if key in (b"q", b"\x03"):
                    return
                if key in (b"j", b"\x1b[B"):
                    sel += 1
                elif key in (b"k", b"\x1b[A"):
                    sel = max(sel - 1, 0)
                elif key == b"r":
                    last_scan = last_shot = 0.0
    finally:
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
