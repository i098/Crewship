#!/usr/bin/env python3
"""Watch one Instagram reel with no login: the watch skill, no cookies, one fetch at a time.

reel_watch.py URL [watch.py options]

Takes a lock so only one reel is fetched at a time, however many agents call it, and waits until MIN_GAP seconds have
passed since the last fetch ended. It never passes a cookie jar or browser session. If Instagram refuses the host, it
stops with the error: do not retry in a loop, and do not add a login.
  REEL_WATCH_DIR   lock and timestamp (default ~/.cache/instagram-dm)
  WATCH_SCRIPT     watch.py of the video-watch skill (default: the one under ~/.omp/agent/skills or ~/.claude/skills)
  GEONODE_GATEWAY, GEONODE_USERNAME, GEONODE_PASSWORD, GEONODE_STICKY_PORT_BASE, GEONODE_STICKY_PORT_MAX
                   Geonode residential proxy for the fetch, on a sticky port picked per fetch. Unset: fetch direct.
"""
import fcntl
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlparse

MIN_GAP = 20


def watch_script():
    if env := os.environ.get("WATCH_SCRIPT"):
        return env
    for base in ("~/.omp/agent/skills", "~/.claude/skills"):
        f = Path(base, "watch/scripts/watch.py").expanduser()
        if f.is_file():
            return str(f)
    sys.exit("the watch skill is not installed")


GEONODE_KEYS = ("GEONODE_GATEWAY", "GEONODE_USERNAME", "GEONODE_PASSWORD", "GEONODE_STICKY_PORT_BASE", "GEONODE_STICKY_PORT_MAX")
PROXY_KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def geonode_proxy(env, pick=random.randint):
    """The Geonode proxy URL on a sticky port picked for one fetch, or None when no GEONODE_* setting is present.

    The URL holds the password: never print it. Errors name only the variables.
    """
    values = {k: env.get(k, "").strip() for k in GEONODE_KEYS}
    if not any(values.values()):
        return None
    if missing := [k for k, v in values.items() if not v]:
        sys.exit(f"reel_watch.py: the Geonode proxy needs {', '.join(missing)}; unset all GEONODE_* to fetch direct")
    try:
        base, top = int(values["GEONODE_STICKY_PORT_BASE"]), int(values["GEONODE_STICKY_PORT_MAX"])
    except ValueError:
        sys.exit("reel_watch.py: GEONODE_STICKY_PORT_BASE and GEONODE_STICKY_PORT_MAX must be port numbers")
    if not 0 < base <= top <= 65535:
        sys.exit("reel_watch.py: GEONODE_STICKY_PORT_BASE must be at most GEONODE_STICKY_PORT_MAX, both in 1-65535")
    user, password = quote(values["GEONODE_USERNAME"], safe=""), quote(values["GEONODE_PASSWORD"], safe="")
    return f"http://{user}:{password}@{values['GEONODE_GATEWAY']}:{pick(base, top)}"



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
            if proxy := geonode_proxy(os.environ):
                # yt-dlp reads these proxy variables. NO_PROXY is cleared: a match there would fetch Instagram direct.
                env |= {k: proxy for k in PROXY_KEYS} | {"NO_PROXY": "", "no_proxy": ""}
            return os.spawnve(os.P_WAIT, cmd[0], cmd, env)
        finally:
            stamp.touch()


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
