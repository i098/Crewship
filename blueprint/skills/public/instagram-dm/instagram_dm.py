#!/usr/bin/env python3
"""Read Instagram DMs with instagrapi, hand new ones to an agent at once, and reply from the agent account.

Run it with `uv run --quiet --with instagrapi python instagram_dm.py ...` (instagrapi is imported only when a command needs it).

instagram_dm.py login [--force]     # the one manual login (a human, the app checked first); needs INSTAGRAM_FIRSTMATE_USERNAME / _PASSWORD
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
  INSTAGRAM_DM_SENT       JSON lines of every `reply` send, tapback and typing (default $INSTAGRAM_DM_DIR/sent.jsonl);
                          INSTAGRAM_DM_ACTOR names who made it (default firstmate; the front desk sets desk)
  INSTAGRAM_DM_OPERATOR   numeric user id of the operator: his message requests are accepted, only his messages are
                          logged, and `reply` writes only to him; empty does none of these
  INSTAGRAM_DM_NOTIFY     command that takes `--request-id ID -- TEXT` and tells the agent (for Firstmate:
                          `<home>/bin/fm-inbox.sh note`); its request id makes a repeat harmless. Empty: log only
  INSTAGRAM_DM_CODE_CMD   shell command that prints the newest 6-digit Instagram email code (see SKILL.md)
  INSTAGRAM_DM_TIMEZONE   IANA time zone of the host's public IP (America/Chicago): REQUIRED by the first `login`, which
                          pins it in the session file; never the library's New York default
  INSTAGRAM_DM_WRITE_GAP / _WRITE_JITTER   seconds between two writes: 20, plus 0-10 of random
  INSTAGRAM_DM_REPLIES_HOUR / _REPLIES_DAY   texts allowed per hour and per day (10, 40)
  INSTAGRAM_DM_SIGNALS_HOUR   tapbacks and typing indicators allowed per hour together (20)
  INSTAGRAM_DM_ERROR_COOLDOWN   seconds without sends after any error (1800)
  INSTAGRAM_DM_REALTIME_GAP   least seconds between two polls that realtime events cause (30)
  INSTAGRAM_DM_INTERVAL   base backoff in seconds after a failure (default 120); the cap is INSTAGRAM_DM_BACKOFF_MAX (1800)
A failure backs off for 2, 4, 8 ... times the base (poll, listen and reply share it). The first challenge, feedback
block, suspension, login_required, please-wait, throttle (429), bad password or a challenge answer it could not parse
(KeyError) halts everything instead, with no retry, and the log keeps Instagram's whole answer: one notice goes to the agent and nothing calls Instagram again until `resume`. Nothing here ever logs in
again by itself: a missing or dead session is such a halt, and a human runs `login --force` after checking the app.
Every failure is reported with its exception class and endpoint. Nothing but `reply` sends anything, and no media
is downloaded.
"""

import argparse
import contextlib
import fcntl
import json
import os
import random
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

# Any post link (post, reel, tv, or with a username prefix). "Always assume it is a reel."
LINK = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?!share/)(?:[\w.]+/)?(?:p|reels?|tv)/([\w-]+)"
)
# A /share/ link holds no shortcode: it only resolves by redirect, so it passes through unchanged.
SHARE = re.compile(r"https?://(?:www\.)?instagram\.com/share/[\w/-]+")
SEEN_KEEP = 5000
REPLY_MAX = 500  # characters: the operator asked for short plain texts
TYPING_MIN = 100  # characters: a typing indicator only comes before a reply longer than this
# What the shared limiter counts: per write kind, (window in s, kinds counted together, env name, default cap).
CAPS = {
    "text": [
        (3600, ("text",), "INSTAGRAM_DM_REPLIES_HOUR", 10),
        (86400, ("text",), "INSTAGRAM_DM_REPLIES_DAY", 40),
    ],
    "react": [(3600, ("react", "typing"), "INSTAGRAM_DM_SIGNALS_HOUR", 20)],
    "typing": [(3600, ("react", "typing"), "INSTAGRAM_DM_SIGNALS_HOUR", 20)],
}
# Exception class names that mean the account is flagged, throttled or logged out: stop, never retry.
HALT = {
    "ChallengeError",
    "FeedbackRequired",
    "AccountSuspended",
    "BadPassword",
    "BadCredentials",
    "LoginRequired",
    "SessionLost",
    "PleaseWaitFewMinutes",
    "RateLimitError",
    "ClientThrottledError",
    "SentryBlock",
    "CaptchaChallengeRequired",
    "KeyError",  # instagrapi reads a response["challenge"] it does not have: a challenge it could not parse
}
# What Instagram's own answer says when it flags the account, whatever exception class carried it.
FLAGGED = re.compile(r"challenge_required|checkpoint_required|feedback_required|login_required|/suspended/", re.I)


class SessionLost(Exception):
    """No usable saved session. Nothing here logs in again: a human does."""


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


def is_halt(e):
    """True when e is one of HALT (a parent class counts), or Instagram's answer in e.last_json says flagged."""
    return any(c.__name__ in HALT for c in type(e).__mro__) or bool(FLAGGED.search(json.dumps(getattr(e, "last_json", None), default=str)))


def describe(e):
    """One line for a failure: exception class, the endpoint path when the error carries its response, the message
    (password masked, clipped). A halting failure adds Instagram's whole answer (last_json), so the next flag is read
    from the log and not guessed."""
    line = f"{type(e).__name__}"
    if url := getattr(getattr(e, "response", None), "url", None):
        line += f" at {urlsplit(url).path}"
    line = f"{line}: {e}"[:300]
    if (payload := getattr(e, "last_json", None)) and is_halt(e):
        line += f" payload={json.dumps(payload, default=str)}"[:600]
    secret = os.environ.get("INSTAGRAM_FIRSTMATE_PASSWORD")
    return line.replace(secret, "***") if secret else line


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


def num(name, default):
    return float(conf(name, str(default)))


def load_state():
    file = state_dir() / "poll.json"
    return {
        "seen": [],
        "fails": 0,
        "next": 0,
        "writes": [],  # [time, kind] of every outbound write of the last day: the limiter's memory
        "write_at": 0,  # no write before this time: the gap after the last one, jitter included
        "cooldown": 0,  # no write before this time: the pause after an error
        **(json.loads(file.read_text()) if file.is_file() else {}),
    }


def save_state(state):
    (state_dir() / "poll.json").write_text(json.dumps(state))


def allow(state, kind, now):
    """Why a write of this kind may not go out now (the error cooldown or a cap), or None. `seen` has no cap."""
    if now < state["cooldown"]:
        return f"send cooldown, {int(state['cooldown'] - now)}s more after an error"
    for window, kinds, env, default in CAPS.get(kind, ()):
        cap = int(num(env, default))
        if sum(k in kinds and now - at < window for at, k in state["writes"]) >= cap:
            return f"limit of {cap} {'/'.join(kinds)} writes per {window // 3600} h reached"
    return None


def pace(state, kind):
    """Wait out the gap since the last write, or exit when a cap or the cooldown forbids this one."""
    if why := allow(state, kind, time.time()):
        sys.exit(f"not sending: {why}")
    time.sleep(max(0, state["write_at"] - time.time()))


def record_write(state, kind, now=None):
    """Remember a write and set the earliest time of the next one: INSTAGRAM_DM_WRITE_GAP (20 s) plus up to
    INSTAGRAM_DM_WRITE_JITTER (10 s) of random."""
    now = now or time.time()
    state["writes"] = [[at, k] for at, k in state["writes"] if now - at < 86400] + [[now, kind]]
    gap, jitter = num("INSTAGRAM_DM_WRITE_GAP", 20), num("INSTAGRAM_DM_WRITE_JITTER", 10)
    state["write_at"] = now + gap + random.uniform(0, jitter)


def write(state, kind, thread, call, text=None):
    """One outbound write through the shared limiter: wait for the gap, make the call, count it, log it for the front
    desk (a text of None is not logged)."""
    pace(state, kind)
    call()
    record_write(state, kind)
    if text is not None:
        record_sent(kind, thread, text)


def save_state(state):
    (state_dir() / "poll.json").write_text(json.dumps(state))


def fail(state, e, now):
    """Record a failure in state and return its one-line report. A flagged account halts; anything else backs off."""
    what = describe(e)
    if is_halt(e):
        state["halted"] = what
        with contextlib.suppress(Exception):
            notify(
                [
                    {
                        "id": f"halt-{int(now)}",
                        "sender": "poller",
                        "text": f"halted, a human must open the Instagram app first, then run `instagram_dm.py resume`: {what}",
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
    state["cooldown"] = now + num("INSTAGRAM_DM_ERROR_COOLDOWN", 1800)  # reads may go on, sends wait
    return f"failed ({what}); next try in {wait}s"


def blocked(state, now):
    """Why Instagram must not be called now, or None."""
    if state.get("halted"):
        return f"halted ({state['halted']}); a human must open the Instagram app first, then run `instagram_dm.py resume`"
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
        if time.time() < state["write_at"]:
            break  # a receipt is best effort: never wait for the gap, never go under it
        try:
            cl.direct_message_seen(thread_id, message_id)
            record_write(state, "seen")
        except Exception as e:
            if is_halt(e):
                raise
    save_state(state)


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
    if not is_halt(e):
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
    last, pending = time.time(), False
    while not load_state().get("halted"):
        try:
            cl.realtime_read_once()
        except TimeoutError:  # idle: the broker must still answer a ping
            if not rt.ping():
                raise ConnectionError("realtime ping unanswered") from None
        pending = pending or bool(events)  # events only ring the doorbell: any number of them mean one poll
        events.clear()
        if pending and time.time() - last >= num("INSTAGRAM_DM_REALTIME_GAP", 30):
            pending, last = False, time.time()
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
            print(f"realtime {describe(e)}; reconnect in {wait}s", flush=True)
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
    print("resumed. The next call goes to Instagram: open the app first and make sure the account is fine.")


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


def record_sent(kind, thread, text=""):
    """Append one row per send, tapback or typing to INSTAGRAM_DM_SENT: the front desk reads it to stand down
    when Firstmate answers. `by` is INSTAGRAM_DM_ACTOR ("desk" for the desk's own calls). Best effort."""
    log = Path(conf("INSTAGRAM_DM_SENT", str(state_dir() / "sent.jsonl")))
    row = {"at": int(time.time()), "thread": thread, "kind": kind, "by": conf("INSTAGRAM_DM_ACTOR", "firstmate")}
    if text:
        row["text"] = text
    with contextlib.suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as f:
            f.write(json.dumps(row) + "\n")


def send_actions(cl, state, t, operator, text, emoji, typing):
    """Typing indicator (only before a text longer than TYPING_MIN), reaction to his latest message, then the text:
    each through the shared limiter."""
    if typing and len(text) > TYPING_MIN:
        write(
            state,
            "typing",
            t.id,
            lambda: cl.realtime_connect().direct_indicate_activity(t.id, True),
            "",
        )
        time.sleep(min(4, 1 + len(text) / 25))  # typing time grows with the text
    if emoji:
        latest = next(
            (m for m in t.messages if str(m.user_id) == operator and m.item_type != "action_log"),
            None,
        )
        if latest is None:
            sys.exit("no message of the operator to react to")
        write(state, "react", t.id, lambda: cl.direct_send_reaction(t.id, latest.id, emoji), emoji)
    if text:
        write(state, "text", t.id, lambda: cl.direct_send(text, thread_ids=[int(t.id)]), text)


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
    typing = typing and len(text) > TYPING_MIN
    kinds = [k for k, on in (("typing", typing), ("react", emoji), ("text", text)) if on]
    if not kinds:
        return print("no typing indicator for a short reply: nothing to send")
    with locked():
        state, now = load_state(), time.time()
        if why := blocked(state, now) or next(filter(None, (allow(state, k, now) for k in kinds)), None):
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
            sys.exit(f"reply {err}")
        finally:
            save_state(state)  # the writes made before a failure still count
            if cl:
                with contextlib.suppress(Exception):
                    cl.realtime_disconnect()


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


def session_file():
    return Path(conf("INSTAGRAM_DM_SESSION", "~/.config/crewship/instagram/session.json")).expanduser()


def login(force=False):
    """The one manual login: the env credentials, saved with the device it pinned to the session file (mode 600).
    A session file already there means a second login, which needs --force and keeps that device."""
    from instagrapi import Client

    user, password = (
        os.environ.get("INSTAGRAM_FIRSTMATE_USERNAME"),
        os.environ.get("INSTAGRAM_FIRSTMATE_PASSWORD"),
    )
    if not user or not password:
        sys.exit("set INSTAGRAM_FIRSTMATE_USERNAME and INSTAGRAM_FIRSTMATE_PASSWORD")
    session = session_file()
    if session.is_file() and not force:
        sys.exit(f"{session} exists and nothing logs in again by itself: check the account in the app, then `login --force`")
    cl = Client()
    cl.challenge_code_handler = code_handler
    if session.is_file():
        cl.load_settings(session)  # the same device as the first login
    else:
        zone = conf("INSTAGRAM_DM_TIMEZONE")  # the zone of the egress IP, never the library's New York default
        if not zone:
            sys.exit("set INSTAGRAM_DM_TIMEZONE to the time zone of this host's public IP, e.g. America/Chicago")
        cl.set_timezone_offset(int(datetime.now(ZoneInfo(zone)).utcoffset().total_seconds()), zone)
    os.environ["INSTAGRAM_DM_CODE_SINCE"] = str(int(time.time()))  # the code command must ignore older mail
    cl.login(user, password)
    session.parent.mkdir(parents=True, exist_ok=True)
    cl.dump_settings(session)
    session.chmod(0o600)
    print(f"logged in; device {cl.device_settings.get('model')}, pinned in {session}")


def refuse(cl, e):
    """instagrapi's handle_exception: raise at once, with Instagram's answer on the exception. Its default solves a
    challenge and retries by itself."""
    with contextlib.suppress(Exception):
        e.last_json = cl.last_json
    raise e


def client():
    """A client on the saved session. It never logs in: no session file, or one without its pinned device, raises
    SessionLost; a session Instagram rejects raises LoginRequired on its first call. Both halt the line."""
    from instagrapi import Client

    session = session_file()
    if not session.is_file():
        raise SessionLost(f"no session file {session}: a human runs `instagram_dm.py login`")
    saved = json.loads(session.read_text())
    if not (saved.get("uuids") and saved.get("device_settings")):
        raise SessionLost(f"{session} holds no pinned device: a human runs `instagram_dm.py login --force`")
    cl = Client()
    cl.delay_range = [1, 3]
    cl.handle_exception = refuse
    cl.set_settings({**saved, "session_retry_total": 0})  # the HTTP layer would retry a 429 three times
    return cl


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("poll", "listen", "resume"):
        sub.add_parser(name)
    sub.add_parser("login").add_argument("--force", action="store_true")
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
        login(a.force)
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
