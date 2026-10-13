#!/usr/bin/env python3
"""Read Instagram DMs with instagram-cli and print shared reel links as /reel/ URLs.

instagram_dm.py login               # session login from INSTAGRAM_FIRSTMATE_USERNAME / _PASSWORD (/ _TOTP)
instagram_dm.py inbox [--limit N]   # thread id, unread flag, title
instagram_dm.py reels THREAD [--limit N] [--mark-seen]   # one normalised reel URL per line
Read-only: this script never sends, replies or unsends.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# Any post link (post, reel, tv, or with a username prefix). "Always assume it is a reel."
LINK = re.compile(r"https?://(?:www\.)?instagram\.com/(?:[\w.]+/)?(?:p|reels?|tv)/([\w-]+)")


def reel_urls(text):
    """Return the unique /reel/ URLs for every post link in text, in order."""
    return list(dict.fromkeys(f"https://www.instagram.com/reel/{c}/" for c in LINK.findall(text)))


def cli(*args):
    """Run instagram-cli with JSON output and return its data; exit with its error otherwise."""
    run = subprocess.run(["instagram-cli", *args, "--output", "json"], capture_output=True, text=True)
    try:
        out = json.loads(run.stdout)
    except ValueError:
        sys.exit(f"instagram-cli failed ({run.returncode}): {run.stderr.strip()[:300]}")
    if not out.get("ok"):
        sys.exit(f"instagram-cli: {out.get('error')}")
    return out["data"]


def login():
    user = os.environ.get("INSTAGRAM_FIRSTMATE_USERNAME")
    password = os.environ.get("INSTAGRAM_FIRSTMATE_PASSWORD")
    if not user or not password:
        sys.exit("set INSTAGRAM_FIRSTMATE_USERNAME and INSTAGRAM_FIRSTMATE_PASSWORD")
    cmd = ["instagram-cli", "auth", "login", "-u", user, "-p", password]
    if os.environ.get("INSTAGRAM_FIRSTMATE_TOTP"):
        cmd += ["--totp", os.environ["INSTAGRAM_FIRSTMATE_TOTP"]]
    # Output is dropped: it can echo the account name.
    if subprocess.run(cmd, capture_output=True).returncode:
        sys.exit("login failed (wrong credentials, 2FA, or an Instagram challenge: see SKILL.md)")
    print("logged in")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("login")
    inbox = sub.add_parser("inbox")
    inbox.add_argument("--limit", type=int, default=20)
    reels = sub.add_parser("reels")
    reels.add_argument("thread")
    reels.add_argument("--limit", type=int, default=20)
    reels.add_argument("--mark-seen", action="store_true")
    a = ap.parse_args()
    if a.cmd == "login":
        login()
    elif a.cmd == "inbox":
        data = cli("inbox", "--limit", str(a.limit))
        for t in data if isinstance(data, list) else data.get("threads", []):
            print(t["id"], "unread" if t.get("unread") else "read", t.get("title", ""), sep="\t")
    else:
        extra = ["--mark-seen"] if a.mark_seen else []
        data = cli("read", a.thread, "--limit", str(a.limit), *extra)
        msgs = data if isinstance(data, list) else data.get("messages", [])
        # A shared reel may carry its link outside `text`, so scan the whole message.
        for url in reel_urls("\n".join(json.dumps(m) for m in msgs)):
            print(url)


if __name__ == "__main__":
    main()
