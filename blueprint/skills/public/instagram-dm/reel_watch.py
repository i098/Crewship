#!/usr/bin/env python3
"""Watch one Instagram reel with no login: the watch skill, no cookies, one fetch at a time.

reel_watch.py URL [watch.py options]

Takes a lock so only one reel is fetched at a time, however many agents call it, and waits until MIN_GAP seconds have
passed since the last fetch ended. It never passes a cookie jar or browser session. If Instagram refuses the host, it
stops with the error: do not retry in a loop, and do not add a login.
  REEL_WATCH_DIR   lock and timestamp (default ~/.cache/instagram-dm)
  WATCH_SCRIPT     watch.py of the video-watch skill (default: the one under ~/.omp/agent/skills or ~/.claude/skills)
"""
import fcntl
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

MIN_GAP = 20


def watch_script():
    if env := os.environ.get("WATCH_SCRIPT"):
        return env
    for base in ("~/.omp/agent/skills", "~/.claude/skills"):
        f = Path(base, "watch/scripts/watch.py").expanduser()
        if f.is_file():
            return str(f)
    sys.exit("the watch skill is not installed")


def command(argv):
    """The watch.py command line for a reel URL plus options; exits on a non-Instagram URL or a cookie option."""
    if not argv or (urlparse(argv[0]).hostname or "").removeprefix("www.") != "instagram.com":
        sys.exit("usage: reel_watch.py https://www.instagram.com/reel/CODE/ [watch.py options]")
    if any(a.split("=")[0] in ("--cookies", "--cookies-from-browser") for a in argv[1:]):
        sys.exit("reel_watch.py never uses cookies for Instagram")
    return [sys.executable, watch_script(), *argv]


def run(argv, wait=time.sleep):
    cmd = command(argv)
    state = Path(os.environ.get("REEL_WATCH_DIR", "~/.cache/instagram-dm")).expanduser()
    state.mkdir(parents=True, exist_ok=True)
    stamp = state / "reel-watch.last"
    with open(state / "reel-watch.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            last = stamp.stat().st_mtime
        except FileNotFoundError:
            last = 0
        if (gap := last + MIN_GAP - time.time()) > 0:
            print(f"[reel_watch] waiting {gap:.0f}s", file=sys.stderr)
            wait(gap)
        try:
            # An empty value beats the watch config file: no jar, no browser session.
            env = {**os.environ, "WATCH_COOKIES_FILE": "", "WATCH_COOKIES_FROM_BROWSER": ""}
            return os.spawnve(os.P_WAIT, cmd[0], cmd, env)
        finally:
            stamp.touch()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
