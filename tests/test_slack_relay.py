import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/slack-relay"
# The public-skill privacy scan reads every file in the skill folder: leave no .pyc there.
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("slack_relay", SKILL / "slack_relay.py")
sr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sr)

WS, ME, BOB, BOT = "T1", "UME", "UBOB", "B1"
SCHEMA = """
create table workspaces (id text, name text);
create table users (id text, workspace_id text, name text, display_name text, is_bot int);
create table channels (id text, workspace_id text, name text, type text);
create table messages (ts text, channel_id text, workspace_id text, user_id text, text text,
  thread_ts text default '', is_deleted int default 0, subtype text default '');
create table thread_subscriptions (workspace_id text, channel_id text, thread_ts text, active int);
"""
# Stub omp: keeps a message whose text holds KEEP, wraps the JSON in prose, counts its calls.
OMP = """#!/usr/bin/env python3
import json, os, re, sys
views = json.load(sys.stdin)
n = os.environ["STUB_DIR"] + "/omp.calls"
open(n, "a").write("x")
open(os.environ["STUB_DIR"] + "/omp.views", "w").write(json.dumps(views))
mode = open(os.environ["STUB_DIR"] + "/omp.mode").read().strip()
if mode == "garbage":
    print("sorry"); sys.exit(0)
if mode == "error":
    sys.exit(1)
out = [{"id": v["id"], "keep": "KEEP" in v["text"], "reason": "stub", "line": f"{v['from']}, {v['channel']}: {v['text']}"}
       for v in views if not (mode == "skip" and "SKIP" in v["text"])]
if mode == "empty":
    out = []
if mode in ("no-line", "blank-line"):
    for v in out:
        v["line"] = None if mode == "no-line" else "   "
print("Here you go:\\n" + json.dumps(out))
"""
NOTIFY = """#!/bin/sh
shift
printf '%s\\n---\\n' "$1" >> "$STUB_DIR/texts"
"""


@pytest.fixture
def env(tmp_path, monkeypatch):
    stub = tmp_path / "stub"
    stub.mkdir()
    (stub / "omp").write_text(OMP)
    (stub / "notify").write_text(NOTIFY)
    for f in ("omp", "notify"):
        (stub / f).chmod(0o755)
    (stub / "omp.mode").write_text("ok")
    db = tmp_path / "cache.db"
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.executemany("insert into users values (?,?,?,?,?)", [
        (ME, WS, "me", "Me", 0), (BOB, WS, "bob", "Bob", 0), (BOT, WS, "ci", "CI", 1)])
    c.executemany("insert into channels values (?,?,?,?)", [("D1", WS, "", "dm"), ("C1", WS, "dev", "channel")])
    c.execute("insert into workspaces values (?,?)", (WS, "Acme"))
    c.commit()
    cfg = {"db": str(db), "self": {WS: ME}, "window": 60, "teammates": ["Bob"],
           "workspaces": {WS: {"name": "Acme"}}, "notify": [str(stub / "notify"), "--"]}
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    monkeypatch.setenv("SLACK_RELAY_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setenv("SLACK_RELAY_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("STUB_DIR", str(stub))
    monkeypatch.setenv("PATH", f"{stub}:/usr/bin:/bin")
    monkeypatch.setattr(sr.subprocess, "run", _run(sr.subprocess.run, stub))
    return NS(c, stub, sr.load_config())


class NS:
    def __init__(self, db, stub, cfg):
        self.db, self.stub, self.cfg, self.st = db, stub, cfg, {}

    def add(self, ts, channel, user, text, **extra):
        cols = {"ts": ts, "channel_id": channel, "workspace_id": WS, "user_id": user, "text": text, **extra}
        self.db.execute(f"insert into messages ({','.join(cols)}) values ({','.join('?' * len(cols))})", list(cols.values()))
        self.db.commit()

    def run(self, now):
        sr.cycle(self.cfg, self.st, now)

    def texts(self):
        f = self.stub / "texts"
        return [t.strip() for t in f.read_text().split("---\n") if t.strip()] if f.exists() else []

    def calls(self):
        f = self.stub / "omp.calls"
        return len(f.read_text()) if f.exists() else 0

    def log(self):
        return sr.read_log()


def _run(real, stub):
    """Route the bare `omp` command to the stub; everything else runs as given."""
    def run(cmd, **kw):
        if cmd[0] == "omp":
            cmd = [sys.executable, str(stub / "omp")]
        return real(cmd, **kw)
    return run


def test_keeps_and_drops_with_reasons_and_ignores_own_and_old_messages(env):
    env.add("90.1", "C1", BOB, "KEEP before the relay started")
    env.run(100)  # first cycle: since = 100, nothing to read
    assert env.calls() == 0
    env.add("101.5", "D1", BOB, "KEEP can you review?")
    env.add("102.5", "C1", BOB, "lol nice")
    env.add("103.5", "C1", ME, "KEEP my own message")
    env.add("104.5", "C1", BOT, "build ok", subtype="bot_message")
    env.run(110)
    assert env.texts() == ["Bob, DM: KEEP can you review?"]
    rows = {r["ts"]: r for r in env.log()}
    assert set(rows) == {"101.5", "102.5", "104.5"}
    assert rows["101.5"]["decision"] == "kept" and rows["102.5"]["decision"] == "dropped"
    assert rows["102.5"]["reason"] == "stub"
    assert rows["104.5"]["user"] == "CI"


def test_a_message_is_decided_once(env):
    env.run(100)
    env.add("101.5", "D1", BOB, "KEEP once")
    env.run(110)
    env.run(200)
    env.run(300)
    assert env.calls() == 1 and len(env.texts()) == 1
    assert [r["ts"] for r in env.log()] == ["101.5"]


def test_a_burst_is_one_text_and_the_next_waits_for_the_window(env):
    env.run(100)
    env.add("101.1", "D1", BOB, "KEEP one")
    env.add("101.2", "C1", BOB, "KEEP two")
    env.run(110)
    assert len(env.texts()) == 1 and env.texts()[0].count("\n") == 1  # two lines, one text
    env.add("120.1", "D1", BOB, "KEEP three")
    env.run(130)  # 20 s after the last text
    assert len(env.texts()) == 1 and len(env.st["pending"]) == 1
    env.run(171)
    assert len(env.texts()) == 2 and not env.st["pending"]
    assert env.texts()[1] == "Bob, DM: KEEP three"


def test_pending_lines_beyond_the_cap_go_in_later_windows(env):
    env.cfg["max_lines"] = 2
    env.run(100)
    for i in range(5):
        env.add(f"101.{i}", "D1", BOB, "KEEP")
    env.run(110)
    env.run(171)
    env.run(232)
    assert [t.count("\n") + 1 for t in env.texts()] == [2, 2, 1]


def test_thread_and_mention_context_reaches_the_model_and_a_skipped_message_falls_back(env):
    env.run(100)
    env.db.execute("insert into thread_subscriptions values (?,?,?,1)", (WS, "C1", "50.0"))
    env.add("101.1", "C1", BOB, "in my thread", thread_ts="50.0")
    env.add("101.2", "C1", BOB, f"<@{ME}> SKIP ping")
    env.add("101.3", "C1", BOB, "SKIP chatter")
    env.add("101.4", "D1", BOB, "SKIP dm")
    env.add("101.5", "C1", BOB, "KEEP mine", thread_ts="40.0")
    env.db.execute("insert into messages (ts, channel_id, workspace_id, user_id, text) values ('40.0','C1',?,?,'my root')", (WS, ME))
    env.db.commit()
    (env.stub / "omp.mode").write_text("skip")
    found = sr.cached_candidates(env.cfg, 100, set())
    flags = {m["ts"]: (m["view"]["in_his_thread"], m["view"]["mentions_him"]) for m in found}
    assert flags == {"101.1": (True, False), "101.2": (False, True), "101.3": (False, False),
                     "101.4": (False, False), "101.5": (True, False)}
    assert "@Me SKIP ping" in [m["view"]["text"] for m in found][1]
    env.run(110)
    rows = {r["ts"]: r for r in env.log()}
    assert rows["101.2"]["decision"] == "kept" and rows["101.4"]["decision"] == "kept"
    assert rows["101.3"]["decision"] == "dropped"
    assert rows["101.2"]["reason"] == "no verdict from the model"
    # the fallback line carries the message itself, and no text ever holds a link
    assert "Bob, #dev: @Me SKIP ping" in env.texts()[0]
    assert "http" not in "".join(env.texts()) and "slack://" not in "".join(env.texts())


@pytest.mark.parametrize("mention_only", [False, True])
def test_an_unparsable_answer_logs_nothing_and_the_message_is_retried(env, mention_only):
    env.cfg["mention_only"] = mention_only
    env.run(100)
    env.add("101.1", "D1", BOB, f"<@{ME}> KEEP retry me")
    (env.stub / "omp.mode").write_text("garbage")
    with pytest.raises(ValueError):
        env.run(110)
    assert env.log() == [] and env.texts() == []
    (env.stub / "omp.mode").write_text("ok")
    env.run(120)
    assert len(env.texts()) == 1 and len(env.log()) == 1


def test_the_cache_is_opened_read_only(env):
    db = sr.open_cache(env.cfg["db"])
    with pytest.raises(sqlite3.OperationalError):
        db.execute("delete from messages")


def test_replay_marks_the_text_and_does_not_block_the_real_message(env):
    env.add("101.1", "D1", BOB, "KEEP replay me")
    sr.replay(env.cfg, WS, "D1", "101.1")
    assert env.texts() == ["[test] Bob, DM: KEEP replay me"]
    assert env.log()[0]["test"] is True
    env.run(100)
    env.add("150.1", "D1", BOB, "KEEP later")
    env.st["since"] = 0
    env.run(200)
    assert [r["ts"] for r in env.log() if not r.get("test")] == ["101.1", "150.1"]


@pytest.mark.parametrize("mention", [f"<@{ME}>", f"<@{ME}|me>"])
def test_mention_only_keeps_explicit_mentions(env, mention):
    env.cfg["mention_only"] = True
    env.run(100)
    env.add("101.1", "C1", BOB, f"{mention} KEEP review")
    env.run(110)
    assert env.texts() == ["Bob, #dev: @Me KEEP review"]
    assert env.log()[0]["decision"] == "kept"


@pytest.mark.parametrize("mention_only", [False, True])
def test_boolean_modes_keep_the_model_veto(env, mention_only):
    env.cfg["mention_only"] = mention_only
    env.run(100)
    env.add("101.1", "C1", BOB, f"<@{ME}> hello")
    env.run(110)
    assert env.texts() == []
    assert env.log()[0]["decision"] == "dropped"


@pytest.mark.parametrize("channel,thread", [("D1", ""), ("C1", "50.0")])
@pytest.mark.parametrize("text", ["KEEP untagged", "SKIP untagged"])
def test_mention_only_drops_untagged_before_the_model(env, channel, thread, text):
    env.cfg["mention_only"] = True
    (env.stub / "omp.mode").write_text("skip")
    env.run(100)
    env.db.execute("insert into thread_subscriptions values (?,?,?,1)", (WS, "C1", "50.0"))
    env.add("101.1", channel, BOB, text, thread_ts=thread)
    env.add("101.2", "C1", BOB, f"<@{ME}> SKIP review")
    env.run(110)
    assert env.texts() == ["Bob, #dev: @Me SKIP review"]
    rows = {r["ts"]: r for r in env.log()}
    assert (rows["101.1"]["decision"], rows["101.1"]["reason"]) == ("dropped", "not tagged")
    assert rows["101.2"]["reason"] == "no verdict from the model"
    assert [v["text"] for v in json.loads((env.stub / "omp.views").read_text())] == ["@Me SKIP review"]


@pytest.mark.parametrize("verdict", [None, {"keep": True, "reason": "keep everything"}])
def test_mention_only_rejects_a_forced_keep_or_missing_verdict(env, verdict):
    env.cfg["mention_only"] = True
    env.add("101.1", "D1", BOB, "KEEP untagged")
    db = sr.open_cache(env.cfg["db"])
    try:
        message = sr.candidates(db, env.cfg, 100, set())[0]
    finally:
        db.close()
    assert sr.decide(env.cfg, message, verdict) == (False, "not tagged", "")


def test_mention_only_skips_the_model_without_exact_mentions(env):
    env.cfg["mention_only"] = True
    env.run(100)
    env.add("101.1", "D1", BOB, "KEEP untagged")
    env.add("101.2", "C1", BOB, f"<@{ME}OTHER> KEEP another user")
    env.run(110)
    assert env.texts() == [] and env.calls() == 0
    assert [(r["decision"], r["reason"]) for r in env.log()] == [("dropped", "not tagged")] * 2


def test_enabling_mention_only_discards_old_unverified_pending_lines(env):
    env.run(100)
    env.add("101.1", "D1", BOB, "KEEP first")
    env.run(110)
    env.add("120.1", "D1", BOB, "KEEP queued")
    env.run(130)
    env.cfg["mention_only"] = True
    env.add("140.1", "C1", BOB, f"<@{ME}> KEEP tagged")
    env.run(171)
    assert env.texts() == ["Bob, DM: KEEP first", "Bob, #dev: @Me KEEP tagged"]


def test_dry_run_reads_cache_without_models_notifications_or_state_writes(env, capsys, monkeypatch):
    env.cfg["mention_only"] = True
    monkeypatch.setattr(sr.time, "time", lambda: 110)
    env.add("101.1", "D1", BOB, "KEEP untagged")
    env.add("101.2", "C1", BOB, f"<@{ME}> SKIP review")
    sr.dry_run(env.cfg)
    assert json.loads(capsys.readouterr().out) == {"tagged": 1, "untagged": 1, "kept": 1, "dropped": 1}
    assert env.calls() == 0 and env.texts() == [] and env.log() == []
    assert not sr.state_dir().exists()


@pytest.mark.parametrize("channel_type", ["dm", "group_dm", "mpim", "channel", "private"])
@pytest.mark.parametrize("tagged", [False, True])
def test_direct_mode_filters_before_the_model(env, channel_type, tagged):
    env.cfg["mention_only"] = "direct"
    env.db.execute("update channels set type=? where id='C1'", (channel_type,))
    env.run(100)
    text = f"<@{ME}> hello" if tagged else "hello"
    env.add("101.1", "C1", BOB, text)
    env.run(110)
    allowed = tagged or channel_type == "dm"
    assert env.calls() == int(allowed)
    where = {"dm": "DM", "mpim": "group", "group_dm": "group"}.get(channel_type, "#dev")
    assert env.texts() == ([f"Bob, {where}: {'@Me ' if tagged else ''}hello"] if allowed else [])
    assert env.log()[0]["decision"] == ("kept" if allowed else "dropped")
    if not allowed:
        assert env.log()[0]["reason"] == "not tagged or DM"


@pytest.mark.parametrize("command", ["once", "replay"])
@pytest.mark.parametrize("mode", ["ok", "no-line", "blank-line", "empty", "garbage", "error"])
@pytest.mark.parametrize("channel,text,where", [("D1", "hello", "DM"), ("C1", f"<@{ME}> hello", "#dev")])
@pytest.mark.parametrize("sender,name", [(BOB, "Bob"), (BOT, "CI")])
def test_direct_mode_delivers_despite_model_rejection_or_failure(
    env, tmp_path, monkeypatch, command, mode, channel, text, where, sender, name
):
    env.cfg["mention_only"] = "direct"
    (tmp_path / "config.json").write_text(json.dumps(env.cfg))
    env.run(100)
    env.add("101.1", channel, sender, text)
    (env.stub / "omp.mode").write_text(mode)
    args = ["slack_relay.py", command]
    if command == "replay":
        args.extend([WS, channel, "101.1"])
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setattr(sr.time, "time", lambda: 110)
    sr.main()
    prefix = "[test] " if command == "replay" else ""
    message = "@Me hello" if channel == "C1" else "hello"
    assert env.texts() == [f"{prefix}{name}, {where}: {message}"]
    assert [row["decision"] for row in env.log()] == ["kept"]


@pytest.mark.parametrize("verdict", [None, {"keep": True, "reason": "keep everything"}])
def test_direct_mode_blocks_untagged_thread_even_with_forced_keep(env, verdict):
    env.cfg["mention_only"] = "direct"
    env.db.execute("insert into thread_subscriptions values (?,?,?,1)", (WS, "C1", "50.0"))
    env.add("101.1", "C1", BOB, "KEEP thread", thread_ts="50.0")
    with sr.open_cache(env.cfg["db"]) as db:
        message = sr.candidates(db, env.cfg, 100, set())[0]
    assert sr.decide(env.cfg, message, verdict) == (False, "not tagged or DM", "")
    env.run(100)
    env.run(110)
    assert env.calls() == 0 and env.texts() == []
    assert env.log()[0]["reason"] == "not tagged or DM"


@pytest.mark.parametrize("previous", [False, True])
def test_switching_to_direct_discards_pending_without_replaying_dropped_messages(env, previous):
    env.cfg["mention_only"] = previous
    env.run(100)
    env.add("101.1", "C1", BOB, f"<@{ME}> KEEP first")
    env.run(110)
    env.add("120.1", "C1", BOB, f"<@{ME}> KEEP queued")
    env.run(130)
    if previous:
        env.add("135.1", "D1", BOB, "KEEP previously dropped")
        env.run(140)
    env.cfg["mention_only"] = "direct"
    env.add("150.1", "D1", BOB, "KEEP new DM")
    env.run(171)
    env.run(240)
    assert env.texts() == ["Bob, #dev: @Me KEEP first", "Bob, DM: KEEP new DM"]
    assert len(env.log()) == (4 if previous else 3)


def test_direct_mode_preserves_dedup_and_burst_limits(env):
    env.cfg.update(mention_only="direct", max_lines=2)
    env.run(100)
    for i in range(5):
        env.add(f"101.{i}", "D1", BOB, f"KEEP DM {i}")
    env.run(110)
    env.run(130)
    assert env.texts() == ["Bob, DM: KEEP DM 0\nBob, DM: KEEP DM 1"]
    env.run(171)
    env.run(232)
    assert env.texts() == ["Bob, DM: KEEP DM 0\nBob, DM: KEEP DM 1",
                           "Bob, DM: KEEP DM 2\nBob, DM: KEEP DM 3", "Bob, DM: KEEP DM 4"]
    assert env.calls() == 1 and len(env.log()) == 5


@pytest.fixture
def two_caches(env, tmp_path):
    env.add("101.1", "D1", BOB, "KEEP first cache")
    path = tmp_path / "second.db"
    with sqlite3.connect(path) as db:
        env.db.backup(db)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("insert into workspaces values ('T2', 'Second')")
        db.executemany("insert into users values (?, 'T2', ?, ?, 0)", [
            ("UME2", "me2", "Me Two"), ("UBOB2", "bob2", "Bob Two")])
        db.execute("insert into channels values ('D2', 'T2', '', 'dm')")
        db.execute("insert into channels values ('C2', 'T2', 'second', 'channel')")
        db.executemany("insert into messages (ts, channel_id, workspace_id, user_id, text) values (?, ?, 'T2', ?, ?)", [
            ("101.1", "D2", "UBOB2", "KEEP second cache"),
            ("101.2", "D2", "UME2", "KEEP own message"),
            ("101.3", "C2", "UBOB2", f"<@{ME}> KEEP wrong workspace tag"),
            ("101.4", "C2", "UBOB2", "<@UME2> KEEP second mention")])
        db.commit()
        env.cfg.update(dbs=[env.cfg["db"], str(path)], mention_only="direct")
        env.cfg["self"]["T2"] = "UME2"
        yield env


def test_two_caches_keep_workspace_context_and_deduplicate(two_caches):
    env = two_caches
    env.run(100)
    env.run(110)
    env.run(180)
    assert env.texts() == ["Bob, DM: KEEP first cache\nBob Two, DM: KEEP second cache\n"
                           "Bob Two, #second: @Me Two KEEP second mention"]
    assert {r["key"] for r in env.log()} == {
        "T1/D1/101.1", "T2/D2/101.1", "T2/C2/101.3", "T2/C2/101.4"}
    assert len(env.log()) == 4 and env.calls() == 1
    views = json.loads((env.stub / "omp.views").read_text())
    assert [v["workspace"] for v in views] == ["Acme", "Second", "Second"]
    for path in env.cfg["dbs"]:
        with sr.open_cache(path) as db:
            with pytest.raises(sqlite3.OperationalError):
                db.execute("delete from messages")


def test_dry_run_counts_each_message_once_across_caches(two_caches, monkeypatch, capsys):
    monkeypatch.setattr(sr.time, "time", lambda: 110)
    sr.dry_run(two_caches.cfg)
    assert json.loads(capsys.readouterr().out) == {"tagged": 1, "untagged": 3, "kept": 3, "dropped": 1}
    assert two_caches.texts() == [] and two_caches.calls() == 0


@pytest.mark.parametrize("mention", ["<!everyone>", "<!channel>", "<!here>"])
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("workspace", [WS, "T2"])
def test_broadcasts_require_workspace_opt_in(env, mention, enabled, workspace):
    env.cfg["mention_only"] = "direct"
    env.cfg["workspaces"][workspace] = {"name": "Workspace", "broadcasts": enabled}
    (env.stub / "omp.mode").write_text("empty")
    env.run(100)
    env.add("101.1", "C1", BOB, f"{mention} announcement")
    env.run(110)
    env.run(180)
    allowed = enabled and workspace == WS
    assert env.texts() == ([f"Workspace: Bob, #dev: @{mention[2:-1]} announcement"] if allowed else [])
    assert [row["decision"] for row in env.log()] == ["kept" if allowed else "dropped"]


@pytest.mark.parametrize("mode", [False, True])
def test_broadcast_opt_in_does_not_change_boolean_modes(env, mode):
    env.cfg["mention_only"] = mode
    env.cfg["workspaces"][WS]["broadcasts"] = True
    env.run(100)
    env.add("101.1", "C1", BOB, "<!here> announcement")
    env.run(110)
    assert env.texts() == []


def test_enabling_broadcasts_does_not_replay_dropped_messages(env):
    env.cfg["mention_only"] = "direct"
    env.run(100)
    env.add("101.1", "C1", BOB, "<!here> old announcement")
    env.run(110)
    env.cfg["workspaces"][WS]["broadcasts"] = True
    env.add("120.1", "C1", BOB, "<!here> new announcement")
    env.run(130)
    env.run(200)
    assert env.texts() == ["Acme: Bob, #dev: @here new announcement"]
    assert [row["decision"] for row in env.log()] == ["dropped", "kept"]


@pytest.mark.parametrize("channel,text,expected", [
    ("D1", "hello", "DM: hello"),
    ("C1", f"<@{ME}> hello", "#dev: @Me hello"),
])
def test_broadcast_workspace_keeps_context_for_direct_messages(env, channel, text, expected):
    env.cfg["mention_only"] = "direct"
    env.cfg["workspaces"][WS]["broadcasts"] = True
    (env.stub / "omp.mode").write_text("error")
    env.run(100)
    env.add("101.1", channel, BOB, text)
    env.run(110)
    assert env.texts() == [f"Acme: Bob, {expected}"]


def test_replay_finds_a_message_in_the_second_cache(two_caches):
    sr.replay(two_caches.cfg, "T2", "D2", "101.1")
    assert two_caches.texts() == ["[test] Bob Two, DM: KEEP second cache"]
    assert two_caches.log()[0]["key"] == "T2/D2/101.1"


@pytest.mark.parametrize("command", ["once", "replay"])
@pytest.mark.parametrize("mode", ["ok", "empty"])
@pytest.mark.parametrize("mention_only,channel,mention", [
    (False, "D1", ""),
    (True, "C1", f"<@{ME}> "),
    ("direct", "D1", ""),
    ("direct", "C1", f"<@{ME}> "),
    ("direct", "C1", "<!here> "),
])
def test_notifications_keep_one_line_without_links(env, command, mode, mention_only, channel, mention):
    env.cfg["mention_only"] = mention_only
    env.cfg["workspaces"][WS].update(name="Acme\nOperations", broadcasts=True)
    env.db.execute("update users set display_name='Bob\nBuilder' where id=?", (BOB,))
    env.db.execute("update channels set name='dev\nchat' where id='C1'")
    env.run(100)
    text = mention + (
        "KEEP a\nb\rc\u2028d\t&lt;T&gt; &amp;lt;T&amp;gt; "
        "<https://acme.slack.com/a|thread> https://acme.slack.com/b slack://channel?id=C1"
    )
    env.add("101.1", channel, BOB, text)
    (env.stub / "omp.mode").write_text(mode)

    workspace = "Acme Operations: " if mention_only == "direct" else ""
    where = "DM" if channel == "D1" else "#dev chat"
    tag = "@here " if mention == "<!here> " else "@Me " if mention else ""
    expected = f"{workspace}Bob Builder, {where}: {tag}KEEP a b c d <T> &lt;T&gt; thread"
    if command == "replay":
        sr.replay(env.cfg, WS, channel, "101.1")
        expected = "[test] " + expected
    else:
        env.st["sent_at"] = 100
        env.run(110)
        assert env.st["pending"] == [expected]
        env.run(161)

    assert env.texts() == [expected]


def test_model_link_labels_do_not_strip_literal_brackets(env, monkeypatch):
    env.run(100)
    env.add("101.1", "D1", BOB, "KEEP review")
    monkeypatch.setattr(sr, "verdicts", lambda cfg, batch: {
        0: {"keep": True, "line": "Bob, DM: <T> &lt;T&gt;\n<https://acme.slack.com/a|thread> <slack://open>"}
    })

    env.run(110)

    assert env.texts() == ["Bob, DM: <T> &lt;T&gt; thread"]


@pytest.mark.parametrize("command", ["once", "replay"])
@pytest.mark.parametrize("line", [
    "<https://acme.slack.com/archives/C1/p1>",
    " \nhttps://acme.slack.com/archives/C1/p1 slack://open\t",
    "<https://acme.slack.com/archives/C1/p1|slack://open>",
])
@pytest.mark.parametrize("mention_only,channel,mention,broadcasts", [
    (False, "D1", "", False),
    (True, "C1", f"<@{ME}> ", False),
    ("direct", "D1", "", False),
    ("direct", "C1", f"<@{ME}> ", False),
    ("direct", "C1", "<!here> ", True),
    ("direct", "D1", "", True),
])
def test_link_only_model_line_uses_message_text(
    env, monkeypatch, command, line, mention_only, channel, mention, broadcasts
):
    env.cfg["mention_only"] = mention_only
    env.cfg["workspaces"][WS]["broadcasts"] = broadcasts
    env.run(100)
    env.add("101.1", channel, BOB, f"{mention}review\nthis https://acme.slack.com/a")
    monkeypatch.setattr(sr, "verdicts", lambda cfg, batch: {0: {"keep": True, "line": line}})

    if command == "replay":
        sr.replay(env.cfg, WS, channel, "101.1")
    else:
        env.run(110)

    prefix = "[test] " if command == "replay" else ""
    workspace = "Acme: " if broadcasts else ""
    where = "DM" if channel == "D1" else "#dev"
    tag = "@here " if mention == "<!here> " else "@Me " if mention else ""
    assert env.texts() == [f"{prefix}{workspace}Bob, {where}: {tag}review this"]
