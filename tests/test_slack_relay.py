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
mode = open(os.environ["STUB_DIR"] + "/omp.mode").read().strip()
if mode == "garbage":
    print("sorry"); sys.exit(0)
out = [{"id": v["id"], "keep": "KEEP" in v["text"], "reason": "stub", "line": f"{v['from']}, {v['channel']}: {v['text']}"}
       for v in views if not (mode == "skip" and "SKIP" in v["text"])]
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
    found = sr.candidates(sr.open_cache(env.cfg), env.cfg, 100, set())
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


def test_an_unparsable_answer_logs_nothing_and_the_message_is_retried(env):
    env.run(100)
    env.add("101.1", "D1", BOB, "KEEP retry me")
    (env.stub / "omp.mode").write_text("garbage")
    with pytest.raises(ValueError):
        env.run(110)
    assert env.log() == [] and env.texts() == []
    (env.stub / "omp.mode").write_text("ok")
    env.run(120)
    assert len(env.texts()) == 1 and len(env.log()) == 1


def test_the_cache_is_opened_read_only(env):
    db = sr.open_cache(env.cfg)
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
