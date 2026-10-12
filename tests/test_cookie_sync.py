"""blueprint/fleet/browsers/cookie-sync.ts never fans Google cookies out between tiers.

Three file-only tiers run the real sync without a browser. The vnc tier holds a
Google sign-in and a GitHub session; the canonical jar still carries a Google
cookie from an earlier sync. obscura holds a copy of vnc's Google session left
by the old fan-out, and chrome holds its own Google cookie with a different
value. After one sync the GitHub session reaches every tier, no Google cookie
is pushed, the replayed copy is gone from obscura, and chrome and vnc keep
their own Google cookies.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def cookie(name: str, domain: str, value: str = "v") -> dict:
    return {
        "name": name,
        "value": value,
        "domain": domain,
        "path": "/",
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        "expires": None,
    }


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_google_cookies_stay_in_their_tier(tmp_path: Path) -> None:
    vnc, obscura, chrome, state = (
        tmp_path / "vnc.json",
        tmp_path / "obscura.json",
        tmp_path / "chrome.json",
        tmp_path / "state",
    )
    vnc.write_text(
        json.dumps(
            [
                cookie("__Secure-1PSID", ".google.com", "vnc-sid"),
                cookie("SID", ".youtube.com", "vnc-yt"),
                cookie("user_session", "github.com"),
            ]
        )
    )
    obscura.write_text(
        json.dumps(
            [
                cookie("sb-auth-token", "localhost"),
                cookie("__Secure-1PSID", ".google.com", "vnc-sid"),
            ]
        )
    )
    chrome.write_text(json.dumps([cookie("__Secure-1PSID", ".google.com", "chrome-sid")]))
    state.mkdir()
    stale = cookie("SID", ".google.com", "stale-from-canonical")
    stale["expires"] = -1
    (state / "cookies.json").write_text(json.dumps({"google.com|/|SID": stale}))

    subprocess.run(
        [
            "bun",
            str(ROOT / "blueprint/fleet/browsers/cookie-sync.ts"),
            "--state",
            str(state),
            f"obscura=file://{obscura}",
            f"chrome=file://{chrome}",
            f"vnc=file://{vnc}",
        ],
        check=True,
    )

    got_obscura = {c["name"]: c for c in json.loads(obscura.read_text())}
    got_chrome = {(c["domain"], c["name"]): c["value"] for c in json.loads(chrome.read_text())}
    got_vnc = {(c["domain"], c["name"]): c["value"] for c in json.loads(vnc.read_text())}
    assert set(got_obscura) == {"user_session", "sb-auth-token"}, (
        "Google cookie pushed into, or replayed copy kept in, another tier"
    )
    assert got_chrome == {
        ("github.com", "user_session"): "v",
        ("localhost", "sb-auth-token"): "v",
        (".google.com", "__Secure-1PSID"): "chrome-sid",
    }, "a tier's own Google cookie was lost or another tier's was pushed in"
    # vnc's file is rewritten to receive sb-auth-token, so its Google cookies must survive the rewrite.
    assert ("localhost", "sb-auth-token") in got_vnc, "normal cookie did not sync"
    assert got_vnc[(".google.com", "__Secure-1PSID")] == "vnc-sid", (
        "Google cookie deleted from its tier"
    )
    assert got_vnc[(".youtube.com", "SID")] == "vnc-yt", "Google cookie deleted from its tier"
    assert ("google.com", "SID") not in got_vnc and (".google.com", "SID") not in got_vnc
    assert "google" not in (state / "cookies.json").read_text()


# Like Obscura: answers every CDP call with an empty result and deletes nothing.
FAKE_OBSCURA = """
const s = Bun.serve({
  port: 0,
  fetch: (req, srv) => new URL(req.url).pathname === "/json/version"
    ? Response.json({ webSocketDebuggerUrl: `ws://127.0.0.1:${srv.port}/` })
    : srv.upgrade(req) ? undefined : new Response("", { status: 400 }),
  websocket: { message: (ws, m) => ws.send(JSON.stringify({ id: JSON.parse(String(m)).id, result: {} })) },
});
console.log(s.port);
"""


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_replayed_google_copy_in_running_obscura_asks_for_a_stop(tmp_path: Path) -> None:
    obscura, vnc, state, fake = (
        tmp_path / "obscura.json",
        tmp_path / "vnc.json",
        tmp_path / "state",
        tmp_path / "fake.ts",
    )
    copy = cookie("__Secure-1PSID", ".google.com", "vnc-sid")
    vnc.write_text(json.dumps([copy]))
    obscura.write_text(json.dumps([copy, cookie("sb-auth-token", "localhost")]))
    fake.write_text(FAKE_OBSCURA)
    server = subprocess.Popen(["bun", str(fake)], stdout=subprocess.PIPE, text=True)
    try:
        port = server.stdout.readline().strip()
        sync = ["bun", str(ROOT / "blueprint/fleet/browsers/cookie-sync.ts"), "--state", str(state)]
        running = subprocess.run(
            [*sync, f"obscura=http://127.0.0.1:{port}|file://{obscura}", f"vnc=file://{vnc}"],
            capture_output=True,
            text=True,
        )
    finally:
        server.kill()
    assert running.returncode == 3, running.stdout + running.stderr
    assert "obscura: set 0 del 1 needs a stop" in running.stdout

    # fleet-browser then stops obscura and syncs again: the file-only pass drops the copy.
    stopped = subprocess.run(
        [*sync, f"obscura=file://{obscura}", f"vnc=file://{vnc}"], capture_output=True, text=True
    )
    assert stopped.returncode == 0, stopped.stdout + stopped.stderr
    assert {c["name"] for c in json.loads(obscura.read_text())} == {"sb-auth-token"}
    got_vnc = {c["name"]: c["value"] for c in json.loads(vnc.read_text())}
    assert got_vnc["__Secure-1PSID"] == "vnc-sid", "vnc lost its Google sign-in"
