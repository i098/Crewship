#!/usr/bin/env python3
"""Read Instagram DMs with instagrapi, hand new ones to an agent at once, and reply from the agent account.

Run it with `uv run --quiet --with instagrapi python instagram_dm.py ...` (instagrapi is imported only when a command needs it).

instagram_dm.py login                # one login, then the session file is reused; needs INSTAGRAM_FIRSTMATE_USERNAME / _PASSWORD
instagram_dm.py inbox [--limit N]    # thread id, "request" for a message request, title
instagram_dm.py reels THREAD [--limit N] [--mark-seen]   # one normalised reel URL per line
instagram_dm.py poll                 # read once: log and hand over every NEW message of the operator, mark it seen
instagram_dm.py listen               # keep Instagram's realtime channel open and run `poll` on each event (a service)
instagram_dm.py reply [TEXT] [--thread ID] [--react EMOJI] [--typing]   # DM the operator
instagram_dm.py resume               # clear a halt (see below) after you fixed the account

Settings come from the environment:
  INSTAGRAM_DM_SESSION    session file (default ~/.config/crewship/instagram/session.json)
  INSTAGRAM_DM_DIR        state: seen ids, failure count, lock (default ~/.local/state/instagram-dm)
  INSTAGRAM_DM_LOG        JSON lines of every new message (default $INSTAGRAM_DM_DIR/messages.jsonl)
  INSTAGRAM_DM_OPERATOR   numeric user id of the operator: his message requests are accepted, only his messages are
                          logged, and `reply` writes only to him; empty does none of these
  INSTAGRAM_DM_NOTIFY     command that takes `--request-id ID -- TEXT` and tells the agent (for Firstmate:
                          `<home>/bin/fm-inbox.sh note`); its request id makes a repeat harmless. Empty: log only
  INSTAGRAM_DM_CODE_CMD   shell command that prints the newest 6-digit Instagram email code (see SKILL.md)
  INSTAGRAM_DM_INTERVAL   base backoff in seconds after a failure (default 120); the cap is INSTAGRAM_DM_BACKOFF_MAX (1800)
A failure backs off for 2, 4, 8 ... times the base (poll, listen and reply share it). A challenge, a feedback
block, a suspension or a bad password halts everything instead: one notice goes to the agent and nothing calls
Instagram again until `resume`. Nothing but `reply` sends anything, and no media is downloaded.
"""

import argparse
import contextlib
import fcntl
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

# Any post link (post, reel, tv, or with a username prefix). "Always assume it is a reel."
LINK = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?!share/)(?:[\w.]+/)?(?:p|reels?|tv)/([\w-]+)"
)
# A /share/ link holds no shortcode: it only resolves by redirect, so it passes through unchanged.
SHARE = re.compile(r"https?://(?:www\.)?instagram\.com/share/[\w/-]+")
SEEN_KEEP = 5000
REPLY_MAX = 500  # characters: the operator asked for short plain texts
REPLY_GAP = 3  # seconds between two sends
REALTIME_GAP = 5  # seconds between two polls caused by realtime events
# Exception class names that mean the account is flagged: stop, never retry.
HALT = {"ChallengeError", "FeedbackRequired", "AccountSuspended", "BadPassword", "BadCredentials"}


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


def note_text(row):
    """The one line the agent gets for a log row: sender, then the reel URL or the text."""
    what = row.get("url") or " ".join(row.get("text", "").split())[:300] or f"[{row.get('type')}]"
    return f"[Instagram DM from {row['sender']}; answer with fm-insta-reply] {what}"


def notify(rows):
    """Hand each row to INSTAGRAM_DM_NOTIFY. The request id makes a retry after a later failure harmless."""
    cmd = conf("INSTAGRAM_DM_NOTIFY").split()
    for row in rows if cmd else ():
        subprocess.run(
            [*cmd, "--request-id", f"ig-{row['id']}", "--", note_text(row)],
            check=True,
            capture_output=True,
        )


@contextmanager
def locked():
    """Hold the state lock: poll, listen and reply never run their Instagram calls at the same time."""
    state_dir().mkdir(parents=True, exist_ok=True)
    with open(state_dir() / "lock", "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield


def load_state():
    file = state_dir() / "poll.json"
    return {
        "seen": [],
        "fails": 0,
        "next": 0,
        "sent": 0,
        **(json.loads(file.read_text()) if file.is_file() else {}),
    }


def save_state(state):
    (state_dir() / "poll.json").write_text(json.dumps(state))


def fail(state, e, now):
    """Record a failure in state and return its one-line report. A flagged account halts; anything else backs off."""
    secret = os.environ.get("INSTAGRAM_FIRSTMATE_PASSWORD")
    what = f"{type(e).__name__}: {str(e).replace(secret, '***') if secret else e}"[:300]
    if any(c.__name__ in HALT for c in type(e).__mro__):
        state["halted"] = what
        with contextlib.suppress(Exception):
            notify(
                [
                    {
                        "id": f"halt-{int(now)}",
                        "sender": "poller",
                        "text": f"halted, run `instagram_dm.py resume` after you fix the account: {what}",
                    }
                ]
            )
        return f"halted ({what})"
    state["fails"] += 1
    wait = backoff(
        state["fails"],
        int(conf("INSTAGRAM_DM_INTERVAL", "120")),
        int(conf("INSTAGRAM_DM_BACKOFF_MAX", "1800")),
    )
    state["next"] = now + wait
    return f"failed ({what}); next try in {wait}s"


def blocked(state, now):
    """Why Instagram must not be called now, or None."""
    if state.get("halted"):
        return f"halted ({state['halted']}); run `instagram_dm.py resume` after you fix the account"
    if now < state["next"]:
        return f"backing off for {int(state['next'] - now)}s more"
    return None


def poll_once(cl, state):
    """Read the inbox and the requests, accept the operator's, hand over and log new messages, mark them seen."""
    log = Path(conf("INSTAGRAM_DM_LOG", str(state_dir() / "messages.jsonl")))
    accept, rows = collect(
        cl.direct_threads(amount=20),
        cl.direct_pending_inbox(amount=20),
        cl.user_id,
        conf("INSTAGRAM_DM_OPERATOR"),
        set(state["seen"]),
    )
    for thread_id in accept:
        cl.direct_pending_approve(thread_id)
    notify(rows)
    if rows:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))
    state.update(seen=(state["seen"] + [r["id"] for r in rows])[-SEEN_KEEP:], fails=0, next=0)
    save_state(state)  # before the receipts: a failure there must not log the rows twice
    newest = {r["thread"]: r["id"] for r in rows}  # rows are oldest first
    for thread_id, message_id in newest.items():
        with contextlib.suppress(Exception):  # a read receipt is best effort
            cl.direct_message_seen(thread_id, message_id)


def sync(get_client):
    """One locked poll with the shared backoff. Returns the failure report, or None."""
    with locked():
        state, now = load_state(), time.time()
        if blocked(state, now):
            return None
        try:
            poll_once(get_client(), state)
            return None
        except Exception as e:  # any failure backs off; nothing retries by itself
            err = fail(state, e, now)
            save_state(state)
            return err


def poll():
    if err := sync(client):
        sys.exit(f"poll {err}")


def halt_if_flagged(e):
    """Halt the account when e means Instagram flagged it. Returns True when halted."""
    if not any(c.__name__ in HALT for c in type(e).__mro__):
        return False
    with locked():
        state = load_state()
        fail(state, e, time.time())
        save_state(state)
    return True


def listen_once(cl):
    """Serve one realtime connection until it breaks (raises) or the account is halted (returns)."""
    events = []
    cl.realtime_on("message", events.append)
    cl.realtime_on("direct", events.append)
    rt = cl.realtime_connect()
    rt.direct_subscribe()
    sync(lambda: cl)  # what arrived while the channel was down
    last = time.time()
    while not load_state().get("halted"):
        try:
            cl.realtime_read_once()
        except TimeoutError:  # idle: the broker must still answer a ping
            if not rt.ping():
                raise ConnectionError("realtime ping unanswered") from None
        if events:
            time.sleep(max(0, REALTIME_GAP - (time.time() - last)))
            events.clear()
            last = time.time()
            if err := sync(lambda: cl):
                print(f"poll {err}", flush=True)


def listen():
    """Keep the realtime channel open; every message event runs a poll. The channel is a doorbell only:
    the HTTP poll supplies the data, so the private event format is never parsed. A dead channel reconnects
    with backoff. Return when the account is halted."""
    fails = 0
    while not load_state().get("halted"):
        cl = None
        try:
            cl = client()
            listen_once(cl)
        except Exception as e:
            if halt_if_flagged(e):
                return
            fails += 1
            wait = backoff(
                fails,
                int(conf("INSTAGRAM_DM_INTERVAL", "120")),
                int(conf("INSTAGRAM_DM_BACKOFF_MAX", "1800")),
            )
            print(f"realtime {type(e).__name__}: {str(e)[:200]}; reconnect in {wait}s", flush=True)
            time.sleep(wait)
        finally:
            if cl:
                with contextlib.suppress(Exception):
                    cl.realtime_disconnect()


def resume():
    with locked():
        state = load_state()
        state.update(halted=None, fails=0, next=0)
        save_state(state)


def operator_thread(cl, thread, operator):
    """The thread to write to: the given one or the operator's 1:1 thread. Exits unless it holds the operator alone."""
    if thread:
        t = cl.direct_thread(int(thread))
    else:
        t = next(
            (t for t in cl.direct_threads(amount=20) if [str(u.pk) for u in t.users] == [operator]),
            None,
        )
    if t is None or [str(u.pk) for u in t.users] != [operator]:
        sys.exit("no thread with the operator alone: refusing to send")
    return t


def send_actions(cl, state, t, operator, text, emoji, typing):
    """Typing indicator, reaction to his latest message, then the text, each at least REPLY_GAP after the last send."""

    def pause():
        time.sleep(max(0, state["sent"] + REPLY_GAP - time.time()))

    if typing:
        cl.realtime_connect().direct_indicate_activity(t.id, True)
        time.sleep(min(4, 1 + len(text) / 25) if text else 3)  # typing time grows with the text
    if emoji:
        latest = next(
            (m for m in t.messages if str(m.user_id) == operator and m.item_type != "action_log"),
            None,
        )
        if latest is None:
            sys.exit("no message of the operator to react to")
        pause()
        cl.direct_send_reaction(t.id, latest.id, emoji)
        state["sent"] = time.time()
    if text:
        pause()
        cl.direct_send(text, thread_ids=[int(t.id)])
        state["sent"] = time.time()


def reply(text, thread, emoji, typing):
    """DM the operator: an optional typing indicator, an optional reaction to his latest message, an optional text."""
    operator = conf("INSTAGRAM_DM_OPERATOR")
    text = " ".join((text or "").split())
    if not operator:
        sys.exit("set INSTAGRAM_DM_OPERATOR")
    if len(text) > REPLY_MAX:
        sys.exit(f"reply is {len(text)} characters: keep it under {REPLY_MAX}, short and plain")
    if not (text or emoji or typing):
        sys.exit("nothing to send: give TEXT, --react or --typing")
    with locked():
        state, now = load_state(), time.time()
        if why := blocked(state, now):
            sys.exit(f"not sending: {why}")
        cl = None
        try:
            cl = client()
            send_actions(
                cl, state, operator_thread(cl, thread, operator), operator, text, emoji, typing
            )
        except SystemExit:
            raise
        except Exception as e:
            err = fail(state, e, now)
            save_state(state)
            sys.exit(f"reply {err}")
        finally:
            if cl:
                with contextlib.suppress(Exception):
                    cl.realtime_disconnect()
        save_state(state)


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


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("login", "poll", "listen", "resume"):
        sub.add_parser(name)
    inbox = sub.add_parser("inbox")
    inbox.add_argument("--limit", type=int, default=20)
    reels = sub.add_parser("reels")
    reels.add_argument("thread")
    reels.add_argument("--limit", type=int, default=20)
    reels.add_argument("--mark-seen", action="store_true")
    send = sub.add_parser("reply")
    send.add_argument("text", nargs="?")
    send.add_argument("--thread")
    send.add_argument("--react", metavar="EMOJI")
    send.add_argument("--typing", action="store_true")
    a = ap.parse_args()
    if a.cmd == "poll":
        poll()
    elif a.cmd == "listen":
        listen()
    elif a.cmd == "resume":
        resume()
    elif a.cmd == "reply":
        reply(a.text, a.thread, a.react, a.typing)
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
