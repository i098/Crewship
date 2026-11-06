"""fm-desk: list the desk session's turns and open the chosen one in omp over a read-only copy."""

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

FM_DESK = Path(__file__).resolve().parents[1] / "apps" / "imessage" / "fm-desk"


def entry(kind, text, stamp, stop=None):
    message = {"role": kind, "content": [{"type": "text", "text": text}]}
    if stop:
        message["stopReason"] = stop
    return json.dumps({"type": "message", "timestamp": stamp, "message": message}) + "\n"


def write_session(path, turns):
    path.write_text(
        "".join(
            entry("user", text, stamp) + entry("assistant", f"reply to {text[:5]}", stamp)
            for text, stamp in turns
        )
    )


def rig(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    omp = tmp_path / "bin" / "omp"
    omp.parent.mkdir()
    omp.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$@" > {tmp_path}/argv\ncp "$(printf "%s\\n" "$@" | sed -n "/jsonl$/p")" {tmp_path}/seen\n'
    )
    omp.chmod(omp.stat().st_mode | stat.S_IEXEC)
    env = {
        **os.environ,
        "FM_DESK_SESSIONS": str(sessions),
        "PATH": f"{omp.parent}:{os.environ['PATH']}",
        "FM_DESK_SETTLE": "0",
        "TZ": "UTC",
    }
    return sessions, env


def run(env, *args, **kw):
    return subprocess.run(
        [sys.executable, str(FM_DESK), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        **kw,
    )


def test_lists_newest_first_with_kind_and_words(tmp_path):
    sessions, env = rig(tmp_path)
    write_session(
        sessions / "a.jsonl",
        [
            ("<chat>\nold history", "2026-11-05T01:00:00Z"),
            (
                "The owner's new texts. Answer them together once, with one action.\n1: Use podman please",
                "2026-11-05T02:00:00Z",
            ),
            ("You ended your turn without an action tool. Send it.", "2026-11-05T03:30:00Z"),
        ],
    )
    out = run(env).stdout.splitlines()
    assert [line.split()[3] for line in out] == ["retry", "owner", "seed"]
    assert "2026-11-05 03:30:00" in out[0] and "Use podman please" in out[1]


def test_open_cuts_after_chosen_turn_on_a_copy_and_leaves_original(tmp_path):
    sessions, env = rig(tmp_path)
    f = sessions / "a.jsonl"
    write_session(
        f,
        [
            ("first one", "2026-11-05T01:00:00Z"),
            ("second one", "2026-11-05T02:00:00Z"),
            ("third one", "2026-11-05T03:00:00Z"),
        ],
    )
    before = f.read_text()
    assert run(env, "2").returncode == 0
    seen = (tmp_path / "seen").read_text()
    assert "second one" in seen and "third one" not in seen
    argv = (tmp_path / "argv").read_text()
    assert str(sessions) not in argv and "--no-tools" in argv
    assert f.read_text() == before


def test_bad_pick_and_empty_dir(tmp_path):
    sessions, env = rig(tmp_path)
    assert run(env).returncode == 1
    write_session(sessions / "a.jsonl", [("only", "2026-11-05T01:00:00Z")])
    assert run(env, "5").returncode == 2


def test_follow_streams_entries_as_appended_and_never_launches_omp(tmp_path):
    sessions, env = rig(tmp_path)
    env["FM_DESK_SETTLE"] = "2"
    f = sessions / "a.jsonl"
    write_session(f, [("old turn", "2026-11-05T01:00:00Z")])
    before = f.read_text()
    proc = subprocess.Popen(
        [sys.executable, str(FM_DESK), "--follow"], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    time.sleep(1)
    with f.open("a") as h:
        h.write(entry("user", "brand new turn", "2026-11-05T04:00:00Z"))
    first = proc.stdout.readline()
    assert "user: brand new turn" in first
    with f.open("a") as h:
        h.write(entry("assistant", "second line out", "2026-11-05T04:00:01Z"))
    out = proc.stdout.read()
    proc.wait(timeout=20)
    assert proc.returncode == 0
    assert "assistant: second line out" in out
    out = first + out
    assert "old turn" not in out
    assert not (tmp_path / "argv").exists()
    assert f.read_text().startswith(before)


def test_follow_exits_at_end_marker_well_before_settle(tmp_path):
    sessions, env = rig(tmp_path)
    env["FM_DESK_SETTLE"] = "60"
    f = sessions / "a.jsonl"
    write_session(f, [("old turn", "2026-11-05T01:00:00Z")])
    proc = subprocess.Popen([sys.executable, str(FM_DESK), "--follow"], env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(1)
    with f.open("a") as h:
        h.write(entry("user", "go", "2026-11-05T04:00:00Z"))
        h.write(entry("assistant", "working", "2026-11-05T04:00:01Z", "toolUse"))
    time.sleep(1.5)
    assert proc.poll() is None
    with f.open("a") as h:
        h.write(entry("assistant", "all done", "2026-11-05T04:00:02Z", "stop"))
    out, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0 and "assistant: all done" in out


def test_follow_with_zero_settle_still_prints_the_appended_turn(tmp_path):
    sessions, env = rig(tmp_path)
    f = sessions / "a.jsonl"
    write_session(f, [("old turn", "2026-11-05T01:00:00Z")])
    proc = subprocess.Popen([sys.executable, str(FM_DESK), "--follow"], env=env, stdout=subprocess.PIPE, text=True)
    time.sleep(1)
    with f.open("a") as h:
        h.write(entry("user", "zero settle turn", "2026-11-05T04:00:00Z"))
    out, _ = proc.communicate(timeout=10)
    assert proc.returncode == 0 and "user: zero settle turn" in out


def test_bad_count_is_a_usage_error(tmp_path):
    sessions, env = rig(tmp_path)
    for bad in ("abc", "0"):
        r = run(env, "-n", bad)
        assert r.returncode == 2 and "Traceback" not in r.stderr
