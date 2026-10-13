#!/usr/bin/env python3
"""Read Instagram DMs with instagrapi, print shared reels as /reel/ URLs, and poll for new DMs.

Run it with `uv run --quiet --with instagrapi python instagram_dm.py ...` (instagrapi is imported only when a command needs it).

instagram_dm.py login                # one login, then the session file is reused; needs INSTAGRAM_FIRSTMATE_USERNAME / _PASSWORD
instagram_dm.py inbox [--limit N]    # thread id, "request" for a message request, title
instagram_dm.py reels THREAD [--limit N] [--mark-seen]   # one normalised reel URL per line
instagram_dm.py poll                 # append one JSON line per NEW message to the log (for a timer)
instagram_dm.py wake                 # print one wake line per log line not yet printed (a Firstmate check)

Settings come from the environment:
  INSTAGRAM_DM_SESSION    session file (default ~/.config/crewship/instagram/session.json)
  INSTAGRAM_DM_DIR        poll state and wake offset (default ~/.local/state/instagram-dm)
  INSTAGRAM_DM_LOG        JSON lines the poller appends and the wake check reads (default $INSTAGRAM_DM_DIR/messages.jsonl)
  INSTAGRAM_DM_OPERATOR   numeric user id of the operator: his message requests are accepted and only his messages are logged; empty does neither
  INSTAGRAM_DM_CODE_CMD   shell command that prints the newest 6-digit Instagram email code (see SKILL.md)
  INSTAGRAM_DM_INTERVAL   base backoff in seconds after a failed poll (default 120); the cap is INSTAGRAM_DM_BACKOFF_MAX (1800)
Read-only except `poll`, which accepts message requests from the operator. Nothing is sent, and no media is downloaded.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Any post link (post, reel, tv, or with a username prefix). "Always assume it is a reel."
LINK = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?!share/)(?:[\w.]+/)?(?:p|reels?|tv)/([\w-]+)"
)
# A /share/ link holds no shortcode: it only resolves by redirect, so it passes through unchanged.
SHARE = re.compile(r"https?://(?:www\.)?instagram\.com/share/[\w/-]+")
SEEN_KEEP = 5000


def conf(name, default=""):
    return os.environ.get(name) or default


def state_dir():
    return Path(conf("INSTAGRAM_DM_DIR", "~/.local/state/instagram-dm")).expanduser()


def reel_urls(text):
    """Return the unique /reel/ URLs for every post link in text, in order; /share/ links stay as they are."""
    reels = (f"https://www.instagram.com/reel/{c}/" for c in LINK.findall(text))
    return list(dict.fromkeys([*reels, *SHARE.findall(text)]))


def backoff(fails, base, cap):
    """Seconds to wait after `fails` failures in a row: base, 2*base, 4*base ... up to cap."""
    return min(cap, base * 2 ** (max(fails, 1) - 1))


def message_url(msg):
    """The reel or post link a DM carries, or None. Reads the shared media code first, then every link in the message."""
    for media in (msg.clip, msg.media_share):
        if media and media.code:
            return f"https://www.instagram.com/reel/{media.code}/"
    urls = reel_urls(msg.model_dump_json())
    return urls[0] if urls else None


def collect(inbox, pending, me, operator, seen):
    """Return (thread ids to accept, new log rows) from the inbox and the message requests.

    Only the operator (a numeric user id) counts: a request from a thread with him alone is accepted,
    and only his messages are logged. Everyone else is ignored and never accepted. With no operator set nothing happens.
    """
    accept, rows, threads = [], [], list(inbox)
    for t in pending:
        if operator and [str(u.pk) for u in t.users] == [
            operator
        ]:  # a 1:1 thread only, never a group
            accept.append(t.id)
            threads.append(t)
    names = {str(u.pk): u.username for t in threads for u in t.users}
    for t in threads:
        for m in t.messages:
            if (
                m.id in seen
                or m.is_sent_by_viewer
                or str(m.user_id) == str(me)
                or str(m.user_id) != operator
                or not operator
                or m.item_type == "action_log"
            ):  # action_log: "started following" notices
                continue
            row = {
                "at": int(m.timestamp.timestamp()),
                "id": m.id,
                "thread": t.id,
                "sender": names.get(operator, operator),
                "type": m.item_type,
            }
            if url := message_url(m):
                row["url"] = url
            if m.text:
                row["text"] = m.text
            rows.append(row)
    return accept, sorted(rows, key=lambda r: r["at"])


def wake_lines(chunk):
    """One short wake line per complete log line in chunk (bytes); lines that are not JSON are skipped."""
    out = []
    for raw in chunk.splitlines():
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        what = (
            row.get("url") or " ".join(row.get("text", "").split())[:200] or f"[{row.get('type')}]"
        )
        out.append(f"instagram dm from {row['sender']}: {what}")
    return out


def wake():
    """Print the wake lines for log lines past the saved offset. A missing offset starts at 0: the log is ours alone."""
    log = Path(conf("INSTAGRAM_DM_LOG", str(state_dir() / "messages.jsonl")))
    offset_file = state_dir() / "wake.offset"
    if not log.is_file():
        return
    off = int(offset_file.read_text()) if offset_file.is_file() else 0
    data = log.read_bytes()
    if len(data) < off:  # log was truncated or rotated
        off = 0
    end = data.rfind(b"\n") + 1  # a line the poller is still writing waits for the next run
    if end <= off:
        return
    offset_file.parent.mkdir(parents=True, exist_ok=True)
    offset_file.write_text(str(end))
    for line in wake_lines(data[off:end]):
        print(line)


def code_handler(username, choice):
    """Challenge handler: take the code from the email Instagram sent. Refuses SMS."""
    from instagrapi.mixins.challenge import ChallengeChoice

    if choice != ChallengeChoice.EMAIL:
        return False
    cmd = conf("INSTAGRAM_DM_CODE_CMD")
    if not cmd:
        return input("Instagram email code: ").strip() if sys.stdin.isatty() else False
    for _ in range(30):
        time.sleep(6)
        out = subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout
        if m := re.search(r"\b(\d{6})\b", out):
            return m.group(1)
    return False


def login(cl):
    """Log in once with the env credentials and save the session (mode 600)."""
    user, password = (
        os.environ.get("INSTAGRAM_FIRSTMATE_USERNAME"),
        os.environ.get("INSTAGRAM_FIRSTMATE_PASSWORD"),
    )
    if not user or not password:
        sys.exit("set INSTAGRAM_FIRSTMATE_USERNAME and INSTAGRAM_FIRSTMATE_PASSWORD")
    os.environ["INSTAGRAM_DM_CODE_SINCE"] = str(
        int(time.time())
    )  # the code command must ignore older mail
    cl.login(user, password)
    session = Path(
        conf("INSTAGRAM_DM_SESSION", "~/.config/crewship/instagram/session.json")
    ).expanduser()
    session.parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(session)
    session.chmod(0o600)


def client():
    """A client on the saved session; it logs in only when there is no session or Instagram rejects it."""
    from instagrapi import Client
    from instagrapi.exceptions import LoginRequired

    cl = Client()
    cl.delay_range = [1, 3]
    cl.challenge_code_handler = code_handler
    session = Path(
        conf("INSTAGRAM_DM_SESSION", "~/.config/crewship/instagram/session.json")
    ).expanduser()
    if not session.is_file():
        login(cl)
        return cl
    cl.load_settings(session)
    try:
        cl.account_info()
    except LoginRequired:
        login(cl)
    return cl


def poll():
    state_file = state_dir() / "poll.json"
    state = json.loads(state_file.read_text()) if state_file.is_file() else {}
    state = {"seen": [], "fails": 0, "next": 0, **state}
    now = time.time()
    if now < state["next"]:
        return  # still backing off
    log = Path(conf("INSTAGRAM_DM_LOG", str(state_dir() / "messages.jsonl")))
    try:
        cl = client()
        seen = set(state["seen"])
        accept, rows = collect(
            cl.direct_threads(amount=20),
            cl.direct_pending_inbox(amount=20),
            cl.user_id,
            conf("INSTAGRAM_DM_OPERATOR"),
            seen,
        )
        for thread_id in accept:
            cl.direct_pending_approve(thread_id)
        if rows:
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write("".join(json.dumps(r) + "\n" for r in rows))
        state.update(seen=(state["seen"] + [r["id"] for r in rows])[-SEEN_KEEP:], fails=0, next=0)
        err = None
    except Exception as e:  # any failure backs off; the loop never retries by itself
        state["fails"] += 1
        wait = backoff(
            state["fails"],
            int(conf("INSTAGRAM_DM_INTERVAL", "120")),
            int(conf("INSTAGRAM_DM_BACKOFF_MAX", "1800")),
        )
        state["next"] = now + wait
        secret = os.environ.get("INSTAGRAM_FIRSTMATE_PASSWORD")
        err = (
            f"poll failed ({type(e).__name__}: {str(e).replace(secret, '***') if secret else e})"[
                :300
            ]
            + f"; next try in {wait}s"
        )
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state))
    if err:
        sys.exit(err)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("login", "poll", "wake"):
        sub.add_parser(name)
    inbox = sub.add_parser("inbox")
    inbox.add_argument("--limit", type=int, default=20)
    reels = sub.add_parser("reels")
    reels.add_argument("thread")
    reels.add_argument("--limit", type=int, default=20)
    reels.add_argument("--mark-seen", action="store_true")
    a = ap.parse_args()
    if a.cmd == "wake":
        wake()
    elif a.cmd == "poll":
        poll()
    elif a.cmd == "login":
        from instagrapi import Client

        cl = Client()
        cl.challenge_code_handler = code_handler
        login(cl)
        print("logged in")
    elif a.cmd == "inbox":
        cl = client()
        for kind, threads in (
            ("", cl.direct_threads(a.limit)),
            ("request", cl.direct_pending_inbox(a.limit)),
        ):
            for t in threads:
                print(
                    t.id, kind, t.thread_title or ", ".join(u.username for u in t.users), sep="\t"
                )
    else:
        cl = client()
        msgs = cl.direct_messages(a.thread, a.limit)
        for url in dict.fromkeys(u for m in msgs if (u := message_url(m))):
            print(url)
        if a.mark_seen:
            cl.direct_send_seen(a.thread)


if __name__ == "__main__":
    main()
