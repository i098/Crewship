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


class ChallengeError(Exception):
    """Same class name as instagrapi's: the poller halts on it by name."""


class Fake:
    """A logged-in client with two threads: the operator's 1:1 and a stranger's."""

    def __init__(self, messages=()):
        self.user_id = ME
        self.threads = [thread("7", list(messages))]
        self.seen, self.sent, self.reacted = [], [], []

    def direct_threads(self, amount):
        return self.threads

    def direct_pending_inbox(self, amount):
        return []

    def direct_pending_approve(self, thread_id):
        return True

    def direct_message_seen(self, thread_id, message_id):
        self.seen.append((thread_id, message_id))

    def direct_thread(self, thread_id):
        return next(t for t in self.threads if t.id == str(thread_id))

    def direct_send(self, text, thread_ids):
        self.sent.append((text, thread_ids))

    def direct_send_reaction(self, thread_id, message_id, emoji):
        self.reacted.append((thread_id, message_id, emoji))


@pytest.fixture
def host(monkeypatch, tmp_path):
    """Env for one host: state dir, operator, and a notify command that records its arguments."""
    notifier = tmp_path / "notify.py"
    notifier.write_text(
        "import json, sys, os\n"
        "if os.path.exists(sys.argv[0] + '.fail'): sys.exit(1)\n"
        "open(sys.argv[0] + '.out', 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
    )
    monkeypatch.setenv("INSTAGRAM_DM_DIR", str(tmp_path))
    monkeypatch.setenv("INSTAGRAM_DM_OPERATOR", OP)
    monkeypatch.setenv("INSTAGRAM_DM_NOTIFY", f"{sys.executable} {notifier}")
    monkeypatch.setattr(ig.time, "sleep", lambda s: None)
    return tmp_path


def run(monkeypatch, fn, now, *args):
    monkeypatch.setattr(ig.time, "time", lambda: now)
    try:
        fn(*args)
    except SystemExit as e:
        return str(e)


def notified(host):
    out = host / "notify.py.out"
    return [json.loads(line) for line in out.read_text().splitlines()] if out.exists() else []


def logged(host):
    log = host / "messages.jsonl"
    return [json.loads(line)["id"] for line in log.read_text().splitlines()] if log.exists() else []


def test_failed_polls_back_off_then_recover_and_never_log_twice(monkeypatch, host):
    calls = []

    def broken():
        calls.append(1)
        raise RuntimeError("rate limited")

    monkeypatch.setattr(ig, "client", broken)
    assert "next try in 120s" in run(monkeypatch, ig.poll, 1000)
    assert run(monkeypatch, ig.poll, 1100) is None  # inside the wait: no request at all
    assert len(calls) == 1
    assert "next try in 240s" in run(monkeypatch, ig.poll, 1120)

    fake = Fake([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    assert run(monkeypatch, ig.poll, 1400) is None
    assert run(monkeypatch, ig.poll, 1500) is None
    assert logged(host) == ["m1"]
    assert json.loads((host / "poll.json").read_text())["fails"] == 0


def test_new_message_is_handed_to_the_agent_once_and_marked_seen(monkeypatch, host):
    fake = Fake(
        [msg("m2", code="C2", at=20), msg("m1", text="hello", at=10), msg("m0", text="x", at=5)]
    )
    monkeypatch.setattr(ig, "client", lambda: fake)
    for now in (1000, 1001):
        assert run(monkeypatch, ig.poll, now) is None
    assert notified(host) == [
        ["--request-id", "ig-m0", "--", "[Instagram DM from op; answer with fm-insta-reply] x"],
        [
            "--request-id",
            "ig-m1",
            "--",
            "[Instagram DM from op; answer with fm-insta-reply] hello",
        ],
        [
            "--request-id",
            "ig-m2",
            "--",
            "[Instagram DM from op; answer with fm-insta-reply] https://www.instagram.com/reel/C2/",
        ],
    ]
    assert fake.seen == [("7", "m2")]  # one receipt per thread, for the newest message


def test_failed_hand_over_logs_nothing_and_is_retried(monkeypatch, host):
    fake = Fake([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    (host / "notify.py.fail").touch()
    assert "failed" in run(monkeypatch, ig.poll, 1000)
    assert logged(host) == [] and fake.seen == []
    (host / "notify.py.fail").unlink()
    assert run(monkeypatch, ig.poll, 2000) is None  # past the backoff
    assert logged(host) == ["m1"] and len(notified(host)) == 1


def test_a_flagged_account_halts_everything_until_resume(monkeypatch, host):
    def flagged():
        raise ChallengeError("checkpoint")

    monkeypatch.setattr(ig, "client", flagged)
    assert "halted" in run(monkeypatch, ig.poll, 1000)
    assert "halted" in notified(host)[0][-1]  # the agent gets one notice

    fake = Fake([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    assert run(monkeypatch, ig.poll, 9999) is None
    assert logged(host) == []  # nothing called Instagram
    assert "not sending: halted" in run(monkeypatch, ig.reply, 9999, "hi", None, None, False)
    ig.resume()
    assert run(monkeypatch, ig.poll, 10000) is None
    assert logged(host) == ["m1"]


def test_reply_sends_one_short_plain_text_to_the_operator_only(monkeypatch, host):
    fake = Fake([msg("m1", text="hi")])
    fake.threads.append(thread("9", [], user="stranger", pk=9))
    monkeypatch.setattr(ig, "client", lambda: fake)
    assert run(monkeypatch, ig.reply, 1000, "ok\n  done", None, None, False) is None
    assert fake.sent == [("ok done", [7])]
    assert "keep it under" in run(monkeypatch, ig.reply, 1010, "x" * 501, None, None, False)
    assert "refusing" in run(monkeypatch, ig.reply, 1020, "hi", "9", None, False)
    assert len(fake.sent) == 1


def test_reply_reacts_to_the_operators_latest_message(monkeypatch, host):
    fake = Fake([msg("mine", user=ME, sent=True, at=30), msg("m2", at=20), msg("m1", at=10)])
    monkeypatch.setattr(ig, "client", lambda: fake)
    assert run(monkeypatch, ig.reply, 1000, None, None, "\u2764", False) is None
    assert fake.reacted == [("7", "m2", "\u2764")] and fake.sent == []


def test_every_reply_action_is_logged_for_the_front_desk(monkeypatch, host):
    class Typing(Fake):
        def realtime_connect(self):
            return NS(direct_indicate_activity=lambda thread_id, on: None)

    fake = Typing([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    assert run(monkeypatch, ig.reply, 1000, "ok", None, "\u2764", True) is None
    monkeypatch.setenv("INSTAGRAM_DM_ACTOR", "desk")
    assert run(monkeypatch, ig.reply, 1010, "hey", None, None, False) is None
    rows = [json.loads(line) for line in (host / "sent.jsonl").read_text().splitlines()]
    assert [(r["kind"], r.get("text"), r["by"]) for r in rows] == [
        ("typing", None, "firstmate"),
        ("react", "\u2764", "firstmate"),
        ("text", "ok", "firstmate"),
        ("text", "hey", "desk"),
    ]
    assert {r["thread"] for r in rows} == {"7"} and rows[0]["at"] == 1000


def lib(monkeypatch):
    """A stand-in `instagrapi` whose Client records its settings and fails the test on any login."""
    made = []

    class Client:
        def __init__(self):
            made.append(self)

        def set_settings(self, settings):
            self.settings = settings

        def login(self, *args):
            raise AssertionError("a login nothing asked for")

    monkeypatch.setitem(sys.modules, "instagrapi", NS(Client=Client))
    return made


def test_a_missing_or_incomplete_session_halts_and_never_logs_in(monkeypatch, host):
    made = lib(monkeypatch)
    session = host / "session.json"
    monkeypatch.setenv("INSTAGRAM_DM_SESSION", str(session))
    assert "halted (SessionLost" in run(monkeypatch, ig.poll, 1000)
    assert "a human runs `instagram_dm.py login`" in notified(host)[0][-1]
    session.write_text('{"cookies": {}}')  # a session without its pinned device would get a random one
    ig.resume()
    assert "halted (SessionLost" in run(monkeypatch, ig.poll, 2000)
    assert made == []


def test_the_saved_session_is_loaded_as_it_is_and_the_library_never_solves_a_challenge(monkeypatch, host):
    made = lib(monkeypatch)
    saved = {"uuids": {"uuid": "u"}, "device_settings": {"model": "Pixel 8 Pro"}}
    (host / "session.json").write_text(json.dumps(saved))
    monkeypatch.setenv("INSTAGRAM_DM_SESSION", str(host / "session.json"))
    cl = ig.client()
    assert made == [cl] and cl.settings == {**saved, "session_retry_total": 0}
    with pytest.raises(ValueError):  # instagrapi's default would solve the challenge and retry the call
        cl.handle_exception(cl, ValueError("challenge"))


@pytest.mark.parametrize(
    "name,parent",
    [
        ("PleaseWaitFewMinutes", Exception),
        ("FeedbackRequired", Exception),
        ("AccountSuspended", Exception),
        ("LoginRequired", Exception),
        ("ClientThrottledError", Exception),
        ("ChallengeRequired", ChallengeError),  # halts through its parent, as instagrapi's does
    ],
)
def test_the_first_flag_halts_with_no_retry(monkeypatch, host, name, parent):
    calls = []

    def flagged():
        calls.append(1)
        raise type(name, (parent,), {})("flag")

    monkeypatch.setattr(ig, "client", flagged)
    assert f"halted ({name}" in run(monkeypatch, ig.poll, 1000)
    assert run(monkeypatch, ig.poll, 1000 + 86400) is None  # a day later: still nothing called
    assert len(calls) == 1 and len(notified(host)) == 1


def test_a_failure_names_its_class_and_endpoint(monkeypatch, host):
    err = RuntimeError("boom")
    err.response = NS(url="https://i.instagram.com/api/v1/direct_v2/inbox/?persistentBadge=true")

    def broken():
        raise err

    monkeypatch.setattr(ig, "client", broken)
    assert "RuntimeError at /api/v1/direct_v2/inbox/: boom" in run(monkeypatch, ig.poll, 1000)
