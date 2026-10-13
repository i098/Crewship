import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/instagram-dm"
# The public-skill privacy scan reads every file in the skill folder: leave no .pyc there.
sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location("instagram_dm", SKILL / "instagram_dm.py")
ig = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ig)

ME = "1"
OP = "2"


def msg(mid, user="2", text=None, code=None, link=None, sent=False, at=1000):
    media = NS(code=code) if code else None
    return NS(
        id=mid,
        user_id=user,
        text=text,
        clip=media,
        media_share=None,
        is_sent_by_viewer=sent,
        item_type="clip" if code else "text",
        timestamp=datetime.fromtimestamp(at, timezone.utc),
        model_dump_json=lambda: json.dumps({"text": text, "link": link}),
    )


def thread(tid, messages, user="op", pk=2):
    return NS(
        id=tid,
        messages=messages,
        users=[NS(pk=pk, username=user)],
        last_activity_at=datetime.fromtimestamp(5, timezone.utc),
    )


def test_every_post_link_becomes_a_reel_url_once():
    text = (
        "see https://www.instagram.com/p/AbC_1-x/?igsh=z https://instagram.com/reel/AbC_1-x/ "
        'and "https://www.instagram.com/someone/reels/Q9/" https://www.instagram.com/tv/T1/'
    )
    assert ig.reel_urls(text) == [
        f"https://www.instagram.com/reel/{c}/" for c in ("AbC_1-x", "Q9", "T1")
    ]


def test_share_links_pass_through_and_other_links_are_ignored():
    assert ig.reel_urls(
        "https://www.instagram.com/share/reel/BAbc/ https://www.instagram.com/someone/ https://example.com/p/abc"
    ) == ["https://www.instagram.com/share/reel/BAbc/"]


def test_shared_media_code_wins_over_text():
    assert (
        ig.message_url(msg("a", code="CODE1", text="https://www.instagram.com/p/OTHER/"))
        == "https://www.instagram.com/reel/CODE1/"
    )
    assert (
        ig.message_url(msg("b", link="https://www.instagram.com/p/L1/"))
        == "https://www.instagram.com/reel/L1/"
    )
    assert ig.message_url(msg("c", text="hello")) is None


def test_collect_logs_each_message_once_oldest_first_and_skips_own_and_seen():
    t = thread(
        "T",
        [
            msg("m3", text="new", at=30),
            msg("m2", code="C2", at=20),
            msg("m1", text="old", at=10),
            msg("mine", user=ME, sent=True),
        ],
    )
    accept, rows = ig.collect([t], [], ME, OP, {"m1"})
    assert accept == []
    assert [r["id"] for r in rows] == ["m2", "m3"]
    assert rows[0] == {
        "at": 20,
        "id": "m2",
        "thread": "T",
        "sender": "op",
        "type": "clip",
        "url": "https://www.instagram.com/reel/C2/",
    }
    _, again = ig.collect([t], [], ME, OP, {"m1", "m2", "m3"})
    assert again == []


def test_only_the_operator_is_accepted_and_logged():
    stranger = thread("S", [msg("s1", user="9", text="hi")], user="stranger", pk=9)
    friend = thread("F", [msg("f1", text="hello")])
    group = NS(
        **{
            **vars(thread("G", [msg("g1", text="x")])),
            "users": [NS(pk=2, username="op"), NS(pk=9, username="other")],
        }
    )
    accept, rows = ig.collect(
        [thread("X", [msg("x1", user="9", text="spam")], pk=9)],
        [stranger, friend, group],
        ME,
        OP,
        set(),
    )
    assert accept == ["F"]
    assert [r["id"] for r in rows] == ["f1"]


def test_action_log_notices_are_not_messages():
    notice = msg("n1")
    notice.item_type = "action_log"
    assert ig.collect([thread("T", [notice])], [], ME, OP, set()) == ([], [])


def test_no_operator_accepts_and_logs_nobody():
    assert ig.collect([thread("T", [msg("m1")])], [thread("F", [msg("f1")])], ME, "", set()) == (
        [],
        [],
    )


@pytest.mark.parametrize(
    "fails,wait", [(0, 120), (1, 120), (2, 240), (3, 480), (4, 960), (5, 1800), (50, 1800)]
)
def test_backoff_doubles_and_caps(fails, wait):
    assert ig.backoff(fails, 120, 1800) == wait


def run_poll(monkeypatch, tmp_path, now, client):
    monkeypatch.setenv("INSTAGRAM_DM_DIR", str(tmp_path))
    monkeypatch.setenv("INSTAGRAM_DM_OPERATOR", OP)
    monkeypatch.setattr(ig, "client", client)
    monkeypatch.setattr(ig.time, "time", lambda: now)
    try:
        ig.poll()
    except SystemExit as e:
        return str(e)


def test_failed_polls_back_off_then_recover_and_never_log_twice(monkeypatch, tmp_path):
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("rate limited")

    assert "next try in 120s" in run_poll(monkeypatch, tmp_path, 1000, broken)
    assert (
        run_poll(monkeypatch, tmp_path, 1100, broken) is None
    )  # inside the wait: no request at all
    assert len(calls) == 1
    assert "next try in 240s" in run_poll(monkeypatch, tmp_path, 1120, broken)

    threads = [thread("T", [msg("m1", text="hi")])]
    cl = NS(
        user_id=ME,
        direct_threads=lambda amount: threads,
        direct_pending_inbox=lambda amount: [],
        direct_pending_approve=lambda i: True,
    )
    assert run_poll(monkeypatch, tmp_path, 1400, lambda: cl) is None
    assert run_poll(monkeypatch, tmp_path, 1500, lambda: cl) is None
    rows = [json.loads(line) for line in (tmp_path / "messages.jsonl").read_text().splitlines()]
    assert [r["id"] for r in rows] == ["m1"]
    assert json.loads((tmp_path / "poll.json").read_text())["fails"] == 0


def test_wake_prints_each_line_once_and_waits_for_a_complete_line(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("INSTAGRAM_DM_DIR", str(tmp_path))
    log = tmp_path / "messages.jsonl"
    ig.wake()  # no log: silent
    log.write_text(
        json.dumps({"sender": "op", "type": "clip", "url": "https://www.instagram.com/reel/C2/"})
        + "\n"
        + json.dumps({"sender": "op", "type": "text", "text": "two\nlines"})
        + "\n"
        + '{"sender": "op", "ty'
    )
    ig.wake()
    assert capsys.readouterr().out.splitlines() == [
        "instagram dm from op: https://www.instagram.com/reel/C2/",
        "instagram dm from op: two lines",
    ]
    ig.wake()
    assert capsys.readouterr().out == ""
