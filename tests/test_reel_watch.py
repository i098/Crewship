import importlib.util
import os
import sys
import time
from pathlib import Path

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
