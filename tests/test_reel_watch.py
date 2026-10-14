import importlib.util
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import pytest

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/instagram-dm"
sys.dont_write_bytecode = True  # The public-skill privacy scan reads every file in the skill folder.
SPEC = importlib.util.spec_from_file_location("reel_watch", SKILL / "reel_watch.py")
rw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rw)

URL = "https://www.instagram.com/reel/ABC/"


@pytest.fixture
def fake_watch(tmp_path, monkeypatch):
    """A watch.py stand-in that records the cookie settings it was started with."""
    script = tmp_path / "watch.py"
    script.write_text(
        "import os, sys\n"
        f"open({str(tmp_path / 'seen')!r}, 'a').write(repr((sys.argv[1:], os.environ.get('WATCH_COOKIES_FILE'),"
        " os.environ.get('WATCH_COOKIES_FROM_BROWSER'))) + '\\n')\n"
    )
    monkeypatch.setenv("WATCH_SCRIPT", str(script))
    monkeypatch.setenv("REEL_WATCH_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCH_COOKIES_FILE", "/jar/cookies.txt")
    return tmp_path


def test_runs_watch_with_the_cookie_settings_emptied(fake_watch):
    assert rw.run([URL, "--detail", "transcript"], wait=lambda s: None) == 0
    assert (fake_watch / "seen").read_text() == f"(['{URL}', '--detail', 'transcript'], '', '')\n"


def test_second_fetch_waits_for_the_gap_after_the_first(fake_watch):
    waits = []
    rw.run([URL], wait=waits.append)
    rw.run([URL], wait=waits.append)
    assert len(waits) == 1 and rw.MIN_GAP - 5 < waits[0] <= rw.MIN_GAP


def test_no_wait_when_the_last_fetch_is_old(fake_watch):
    rw.run([URL], wait=lambda s: None)
    old = time.time() - rw.MIN_GAP - 1
    os.utime(fake_watch / "state" / "reel-watch.last", (old, old))
    waits = []
    rw.run([URL], wait=waits.append)
    assert waits == []


@pytest.mark.parametrize("argv", [
    [],
    ["https://example.com/v"],
    ["https://notinstagram.com/reel/A/"],
    [URL, "--cookies", "/jar.txt"],
    [URL, "--cookies-from-browser=chrome"],
])
def test_refuses_other_hosts_and_cookie_options(fake_watch, argv):
    with pytest.raises(SystemExit):
        rw.run(argv, wait=lambda s: None)
    assert not (fake_watch / "seen").exists()


GEONODE = {
    "GEONODE_GATEWAY": "gw.example", "GEONODE_USERNAME": "user", "GEONODE_PASSWORD": "p@ss word",
    "GEONODE_STICKY_PORT_BASE": "10000", "GEONODE_STICKY_PORT_MAX": "10009",
}


@pytest.fixture
def spawned(tmp_path, monkeypatch):
    """Records the child environment instead of starting watch.py."""
    calls = []
    monkeypatch.setattr(rw.os, "spawnve", lambda mode, path, argv, env: calls.append(env) or 0)
    monkeypatch.setenv("REEL_WATCH_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("WATCH_SCRIPT", str(tmp_path / "watch.py"))
    for key in (*rw.GEONODE_KEYS, *rw.PROXY_KEYS, "NO_PROXY", "no_proxy"):
        monkeypatch.delenv(key, raising=False)
    return calls


def test_no_geonode_settings_fetch_direct(spawned):
    rw.run([URL], wait=lambda s: None)
    assert not any(k in spawned[0] for k in rw.PROXY_KEYS)


def test_geonode_settings_route_the_fetch_through_a_sticky_port(spawned, monkeypatch):
    for key, value in GEONODE.items():
        monkeypatch.setenv(key, value)
    rw.run([URL], wait=lambda s: None)
    env = spawned[0]
    proxy = urlparse(env["HTTPS_PROXY"])
    assert (proxy.scheme, proxy.hostname, proxy.username) == ("http", "gw.example", "user")
    assert unquote(proxy.password) == "p@ss word"
    assert 10000 <= proxy.port <= 10009
    assert env["HTTP_PROXY"] == env["ALL_PROXY"] == env["https_proxy"] == env["HTTPS_PROXY"]
    assert env["NO_PROXY"] == env["no_proxy"] == ""
    assert env["WATCH_COOKIES_FILE"] == "" and env["WATCH_COOKIES_FROM_BROWSER"] == ""


def test_partial_geonode_settings_stop_and_never_print_the_password(spawned, monkeypatch):
    monkeypatch.setenv("GEONODE_GATEWAY", "gw.example")
    monkeypatch.setenv("GEONODE_USERNAME", "user")
    monkeypatch.setenv("GEONODE_PASSWORD", "secret-pw")
    with pytest.raises(SystemExit) as error:
        rw.run([URL], wait=lambda s: None)
    assert "GEONODE_STICKY_PORT_BASE" in str(error.value) and "secret-pw" not in str(error.value)
    assert spawned == []
