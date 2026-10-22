#!/usr/bin/env python3
"""Relay important Slack messages to the operator by text, and drop the rest.

See SKILL.md beside this script for filtering, configuration, commands, and safety rules.
"""

import argparse
import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULTS = {
    "db": "~/.local/share/slk/cache.db",
    "self": {},  # workspace team id -> the operator's Slack user id (required)
    "operator_name": "the operator",
    "mention_only": False,
    "teammates": [],  # names whose messages about the operator's work matter
    "workspaces": {},  # team id -> {"name": ...}, a display name for the model
    "model": "anthropic/claude-haiku-5-5",
    "notify": ["fm-imessage", "--"],  # the text is appended as the last argument
    "interval": 15,  # seconds between cache reads
    "window": 60,  # at most one text per this many seconds
    "lookback": 6 * 3600,  # never look further back than this, so a long outage cannot flood
    "max_batch": 150,  # messages per model call
    "max_chars": 120_000,  # prompt size cap (about 40k tokens, far under 100k)
    "text_chars": 700,  # per-message clip
    "max_lines": 8,  # lines per text; the rest wait for the next window
}
SKIP_SUBTYPES = {"channel_join", "channel_leave", "bot_add", "bot_remove", "joiner_notification", "tombstone",
                 "channel_purpose", "channel_topic", "channel_name", "tabbed_canvas_updated"}
SYSTEM = """You filter Slack messages for {operator}. Each input message has an id and fields: workspace, channel, type \
(dm, group, channel, private), from, bot (true for an app or bot), mentions_him, in_his_thread, text.
KEEP: a DM to him, an @mention of him, a message in a thread he is in that addresses or concerns him, a decision, a \
deadline, an ask of him, an incident or outage, and anything from his teammates about his work.
DROP: chatter, greetings, reactions in words, jokes, bot and app posts, announcements, automated reports, anything \
that does not need him. A bot post that is an incident or a direct ask of him may stay.
Teammates: {teammates}.
Answer with only a JSON array, one object per input message, no prose: \
{{"id": <id>, "keep": true|false, "reason": "<five words>", "line": "<who>, <where>: <the message or a tight quote>"}}. \
Give "line" only when keep is true. "where" is DM, group DM, #channel or thread in #channel. The operator reads Slack on \
his own screen, so the line carries the content itself: the message, or a short quote of it, under 160 characters in \
all. When he must act, end with the action in a few words, for example "- reply today". Plain text; no link, no markup."""


def conf(name, default):
    return Path(os.environ.get(name) or default).expanduser()


def load_config():
    path = conf("SLACK_RELAY_CONFIG", "~/.config/crewship/slack-relay/config.json")
    cfg = {**DEFAULTS, **json.loads(path.read_text())}
    if not cfg["self"]:
        sys.exit(f"{path} needs \"self\": {{team id: operator user id}}")
    return cfg


def state_dir():
    return conf("SLACK_RELAY_DIR", "~/.local/state/crewship/slack-relay")


def read_log():
    f = state_dir() / "log.jsonl"
    return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.is_file() else []


def write_log(**row):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / "log.jsonl").open("a") as out:
        out.write(json.dumps({"at": int(time.time()), **row}) + "\n")


def load_state():
    f = state_dir() / "state.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def save_state(st):
    d = state_dir()
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st))
    tmp.replace(d / "state.json")


def key(m):
    return f"{m['workspace_id']}/{m['channel_id']}/{m['ts']}"


def open_cache(path):
    db = sqlite3.connect(f"file:{Path(path).expanduser()}?mode=ro", uri=True, timeout=10)
    db.execute("PRAGMA query_only=1")
    db.row_factory = sqlite3.Row
    return db


def clean(text, names):
    """Slack markup to plain text: <@U1> to @name, <url|label> to label, entities decoded."""
    text = re.sub(r"<@(\w+)(\|[^>]*)?>", lambda m: "@" + names.get(m.group(1), m.group(1)), text)
    text = re.sub(r"<!(everyone|channel|here)>", r"@\1", text)
    text = re.sub(r"<#\w+\|([^>]*)>", r"#\1", text)
    text = re.sub(r"<(?:[^|>]*\|)?([^>]*)>", r"\1", text)
    return html.unescape(text).strip()


def in_his_thread(db, m, me):
    """True when he subscribed to the thread or wrote its root."""
    if not m["thread_ts"]:
        return False
    sub = db.execute("select 1 from thread_subscriptions where workspace_id=? and channel_id=? and thread_ts=? and active=1",
                     (m["workspace_id"], m["channel_id"], m["thread_ts"])).fetchone()
    root = db.execute("select 1 from messages where channel_id=? and ts=? and user_id=?", (m["channel_id"], m["thread_ts"], me)).fetchone()
    return bool(sub or root)


def view_of(cfg, db, m, me, ref):
    """What the model sees of one message. ref holds the users, names, channels and workspaces of the cache."""
    users, names, chans, ws = ref
    ch = chans.get(m["channel_id"])
    ctype = ch["type"] if ch else "channel"
    kind = {"dm": "dm", "app": "dm", "mpim": "group", "group_dm": "group"}.get(ctype, ctype)
    who, is_bot = users.get(m["user_id"], (m["user_id"] or "unknown", False))
    named = bool(ch and ch["name"]) and kind not in ("dm", "group")
    return {
        "workspace": cfg["workspaces"].get(m["workspace_id"], {}).get("name") or ws.get(m["workspace_id"], m["workspace_id"]),
        "channel": ("#" + ch["name"]) if named else ("DM" if kind == "dm" else kind),
        "type": kind,
        "from": who,
        "bot": bool(is_bot or m["subtype"] == "bot_message" or m["user_id"].startswith("B") or ctype == "app"),
        "mentions_him": bool(re.search(rf"<@{re.escape(me)}(?:\|[^>]*)?>", m["text"])),
        "in_his_thread": in_his_thread(db, m, me),
        "text": clean(m["text"], names)[: cfg["text_chars"]],
    }


def candidates(db, cfg, since, seen):
    """New, unseen messages from other people, each with the context the model needs."""
    users = {r["id"]: (r["display_name"] or r["name"], bool(r["is_bot"])) for r in db.execute("select * from users")}
    ref = (
        users,
        {k: v[0] for k, v in users.items()},
        {r["id"]: r for r in db.execute("select id, name, type from channels")},
        {r["id"]: r["name"] for r in db.execute("select id, name from workspaces")},
    )
    out = []
    for r in db.execute("select * from messages where cast(ts as real) > ? and is_deleted = 0 order by ts", (since,)):
        m = dict(r)
        me = cfg["self"].get(m["workspace_id"])
        if me is None or m["user_id"] == me or m["subtype"] in SKIP_SUBTYPES or key(m) in seen:
            continue
        out.append({**m, "view": view_of(cfg, db, m, me, ref)})
    return out


def cached_candidates(cfg, since, seen):
    found = []
    for path in cfg.get("dbs") or [cfg["db"]]:
        db = open_cache(path)
        try:
            batch = candidates(db, cfg, since, seen)
        finally:
            db.close()
        found.extend(batch)
        seen.update(key(m) for m in batch)
    return sorted(found, key=lambda m: m["ts"])


def verdicts(cfg, batch):
    """One omp call. Returns {id: verdict}; raises on a failed call or an unparsable answer."""
    views = [{"id": i, **m["view"]} for i, m in enumerate(batch)]
    system = SYSTEM.format(operator=cfg["operator_name"], teammates=", ".join(cfg["teammates"]) or "none listed")
    cmd = ["omp", "-p", "--no-extensions", "--no-tools", "--no-skills", "--no-rules", "--no-session",
           "--thinking=off", "--model", cfg["model"], "--system-prompt", system]
    out = subprocess.run(cmd, input=json.dumps(views, ensure_ascii=False), capture_output=True, text=True,
                         check=True, timeout=300, cwd=tempfile.gettempdir()).stdout
    match = re.search(r"\[.*\]", out, re.S)
    if not match:
        raise ValueError(f"no JSON array in the omp answer: {out[:200]!r}")
    found = json.loads(match.group(0))
    return {int(v["id"]): v for v in found if isinstance(v, dict) and "id" in v}


def drop_reason(cfg, m):
    if cfg["mention_only"] and not m["view"]["mentions_him"]:
        if cfg["mention_only"] == "direct":
            broadcast = cfg["workspaces"].get(m["workspace_id"], {}).get("broadcasts", False)
            allowed = m["view"]["type"] == "dm" or (broadcast and re.search(r"<!(?:everyone|channel|here)>", m["text"]))
            return "" if allowed else "not tagged or DM"
        return "not tagged"
    return ""


def decide(cfg, m, v):
    """Return (keep, reason, line)."""
    reason = drop_reason(cfg, m)
    if reason:
        return False, reason, ""
    if cfg["mention_only"] == "direct":
        return True, "direct mention, DM or broadcast", str((v or {}).get("line") or "").strip()[:240]
    if v is None:
        sure = m["view"]["type"] == "dm" or m["view"]["mentions_him"]
        return sure and not m["view"]["bot"], "no verdict from the model", ""
    return bool(v.get("keep")), str(v.get("reason") or "")[:80], str(v.get("line") or "").strip()[:240]


def process(cfg, batch, st, test=False):
    """Filter one batch; log every message; queue the kept lines."""
    eligible = []
    for m in batch:
        reason = drop_reason(cfg, m)
        if reason:
            write_log(key=key(m), ws=m["workspace_id"], channel=m["channel_id"], ts=m["ts"],
                      user=m["view"]["from"], decision="dropped", reason=reason, **({"test": True} if test else {}))
        else:
            eligible.append(m)
    try:
        got = verdicts(cfg, eligible) if eligible else {}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        if cfg["mention_only"] != "direct":
            raise
        got = {}
    for i, m in enumerate(eligible):
        keep, reason, line = decide(cfg, m, got.get(i))
        v = m["view"]
        write_log(key=key(m), ws=m["workspace_id"], channel=m["channel_id"], ts=m["ts"], user=v["from"],
                  decision="kept" if keep else "dropped", reason=reason, **({"test": True} if test else {}))
        if keep:
            line = line or f"{v['from']}, {v['channel']}: {v['text'][:160]}"
            if cfg["mention_only"] == "direct" and cfg["workspaces"].get(m["workspace_id"], {}).get("broadcasts", False):
                line = f"{v['workspace']}: {line}"
            line = re.sub(r"<(?:https?://|slack://)[^>|]*(?:\|([^>]*))?>",
                          lambda match: match[1] or "", line, flags=re.I)
            line = " ".join(re.sub(r"(?:https?://|slack://)[^\s<>]+", "", line, flags=re.I).split())
            st.setdefault("pending", []).append(f"{'[test] ' if test else ''}{line}")


def flush(cfg, st, now):
    """Send at most one text per window; True when one went out."""
    pending = st.get("pending") or []
    if not pending or now - st.get("sent_at", 0) < cfg["window"]:
        return False
    head, rest = pending[: cfg["max_lines"]], pending[cfg["max_lines"]:]
    subprocess.run([*cfg["notify"], "\n".join(head)], check=True, timeout=60)
    st["pending"], st["sent_at"] = rest, now
    return True


def cycle(cfg, st, now):
    if cfg["mention_only"] and cfg["mention_only"] != st.get("mention_only"):
        st["pending"] = []  # Old queued lines have no mention metadata.
    st["mention_only"] = cfg["mention_only"]
    seen = {r["key"] for r in read_log() if not r.get("test")}
    st.setdefault("since", now)
    found = cached_candidates(cfg, max(st["since"], now - cfg["lookback"]), seen)
    while found:
        batch, size = [], 0
        for m in found:
            size += len(m["view"]["text"]) + 200
            if len(batch) >= cfg["max_batch"] or (batch and size > cfg["max_chars"]):
                break
            batch.append(m)
        process(cfg, batch, st)
        found = found[len(batch):]
        save_state(st)
    flush(cfg, st, now)
    save_state(st)


def dry_run(cfg):
    """Count recent cached messages with the fallback filter; do not call the model, notify, or write state."""
    batch = cached_candidates(cfg, time.time() - cfg["lookback"], set())
    counts = {"tagged": 0, "untagged": 0, "kept": 0, "dropped": 0}
    for m in batch:
        counts["tagged" if m["view"]["mentions_him"] else "untagged"] += 1
        keep, _, _ = decide(cfg, m, None)
        counts["kept" if keep else "dropped"] += 1
    print(json.dumps(counts))


def replay(cfg, workspace, channel, ts):
    batch = [m for m in cached_candidates(cfg, float(ts) - 1, set())
             if m["workspace_id"] == workspace and m["channel_id"] == channel and m["ts"] == ts]
    if not batch:
        sys.exit("message not in the slk caches, or is own, deleted or a skipped kind")
    st = {"sent_at": 0}
    process(cfg, batch, st, test=True)
    print(f"pending: {st.get('pending', [])}")
    flush(cfg, st, time.time())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run")
    sub.add_parser("once")
    sub.add_parser("dry-run")
    rp = sub.add_parser("replay")
    rp.add_argument("workspace"), rp.add_argument("channel"), rp.add_argument("ts")
    args = ap.parse_args()
    cfg = load_config()
    if args.cmd == "dry-run":
        return dry_run(cfg)
    if args.cmd == "replay":
        return replay(cfg, args.workspace, args.channel, args.ts)
    print(f"slack-relay started: mention_only={cfg['mention_only']}", flush=True)
    st, fails = load_state(), 0
    while True:
        try:
            cycle(cfg, st, time.time())
            fails = 0
        except Exception as e:  # Unseen eligible messages are retried.
            fails += 1
            print(f"cycle failed: {e}", file=sys.stderr, flush=True)
        if args.cmd == "once":
            return
        time.sleep(min(cfg["interval"] * 2 ** min(fails, 4), 300))


if __name__ == "__main__":
    main()
