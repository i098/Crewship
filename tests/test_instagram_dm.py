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


def msg(mid, user="2", text=None, code=None, link=None, sent=False, at=1000, meta=None):
    media = NS(code=code, **(meta or {})) if code else None
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
    assert run(monkeypatch, ig.reply, 1000, "ok " + "x" * 100, None, "\u2764", True) is None
    monkeypatch.setenv("INSTAGRAM_DM_ACTOR", "desk")
    assert run(monkeypatch, ig.reply, 1010, "hey", None, None, False) is None
    rows = [json.loads(line) for line in (host / "sent.jsonl").read_text().splitlines()]
    assert [(r["kind"], r.get("text"), r["by"]) for r in rows] == [
        ("typing", None, "firstmate"),
        ("react", "\u2764", "firstmate"),
        ("text", "ok " + "x" * 100, "firstmate"),
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


def test_an_unparsed_challenge_halts_and_keeps_instagrams_answer(monkeypatch, host):
    """instagrapi raised KeyError('challenge') on a challenge_required answer with no challenge data: that is a flag."""
    answer = {"message": "challenge_required", "status": "fail"}

    def broken():
        err = KeyError("challenge")
        err.last_json = answer
        raise err

    monkeypatch.setattr(ig, "client", broken)
    out = run(monkeypatch, ig.poll, 1000)
    assert "halted (KeyError" in out and '"message": "challenge_required"' in out
    other = ValueError("odd")  # any class, when Instagram's own answer says it
    other.last_json = answer
    assert ig.is_halt(other) and not ig.is_halt(ValueError("odd"))


def test_the_library_hands_instagrams_answer_to_the_exception_it_raises():
    err = ValueError("x")
    with pytest.raises(ValueError):
        ig.refuse(NS(last_json={"message": "feedback_required"}), err)
    assert err.last_json == {"message": "feedback_required"}


def test_a_failure_names_its_class_and_endpoint(monkeypatch, host):
    err = RuntimeError("boom")
    err.response = NS(url="https://i.instagram.com/api/v1/direct_v2/inbox/?persistentBadge=true")

    def broken():
        raise err

    monkeypatch.setattr(ig, "client", broken)
    assert "RuntimeError at /api/v1/direct_v2/inbox/: boom" in run(monkeypatch, ig.poll, 1000)


def test_the_one_login_pins_the_zone_of_the_hosts_ip_and_a_second_needs_force(monkeypatch, host):
    class Client:
        device_settings = {"model": "Pixel 8 Pro"}

        def set_timezone_offset(self, seconds, name):
            self.zone = (seconds, name)

        def login(self, user, password):
            pass

        def dump_settings(self, path):
            path.write_text(json.dumps({"timezone": self.zone}))

    monkeypatch.setitem(sys.modules, "instagrapi", NS(Client=Client))
    monkeypatch.setenv("INSTAGRAM_DM_SESSION", str(host / "session.json"))
    monkeypatch.setenv("INSTAGRAM_FIRSTMATE_USERNAME", "bot")
    monkeypatch.setenv("INSTAGRAM_FIRSTMATE_PASSWORD", "pw")
    with pytest.raises(SystemExit, match="INSTAGRAM_DM_TIMEZONE"):
        ig.login()
    monkeypatch.setenv("INSTAGRAM_DM_TIMEZONE", "Etc/GMT+5")  # fixed UTC-5, no daylight saving
    ig.login()
    assert json.loads((host / "session.json").read_text()) == {"timezone": [-18000, "Etc/GMT+5"]}
    with pytest.raises(SystemExit, match="--force"):
        ig.login()


class Clock:
    """A fake clock: sleeping moves it, so a test of a 20 s gap takes no time."""

    def __init__(self, monkeypatch, start=100000):
        self.now = start
        monkeypatch.setattr(ig.time, "time", lambda: self.now)
        monkeypatch.setattr(ig.time, "sleep", self.sleep)
        monkeypatch.setattr(ig.random, "uniform", lambda a, b: b)  # the longest jitter

    def sleep(self, seconds):
        self.now += seconds


def writes(host):
    return json.loads((host / "poll.json").read_text())["writes"]


def reply_ok(*args):
    try:
        ig.reply(*args)
    except SystemExit as e:
        return str(e)


def test_every_write_waits_20s_plus_jitter_after_the_last(monkeypatch, host):
    Clock(monkeypatch)
    fake = Fake([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    assert reply_ok("one", None, "\u2764", False) is None
    assert reply_ok("two", None, None, False) is None
    # react, then text, then the next reply: each 20 s plus the longest jitter (10 s) after the one before
    assert [at for at, _ in writes(host)] == [100000, 100030, 100060]


def test_ten_replies_an_hour_and_forty_a_day_then_the_limiter_says_no(monkeypatch, host):
    clock = Clock(monkeypatch)
    fake = Fake([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    monkeypatch.setenv("INSTAGRAM_DM_WRITE_GAP", "0")
    monkeypatch.setenv("INSTAGRAM_DM_WRITE_JITTER", "0")
    for hour in range(4):
        for i in range(10):
            assert reply_ok(f"h{hour}-{i}", None, None, False) is None
            clock.now += 60
        if hour == 0:
            assert "limit of 10 text writes per 1 h" in reply_ok("eleventh", None, None, False)
        clock.now += 3600  # the next hour starts empty
    assert len(fake.sent) == 40
    assert "limit of 40 text writes per 24 h" in reply_ok("forty-first", None, None, False)
    clock.now += 86400
    assert reply_ok("next day", None, None, False) is None


def test_twenty_reactions_and_typing_an_hour_together(monkeypatch, host):
    class Typing(Fake):
        def realtime_connect(self):
            return NS(direct_indicate_activity=lambda thread_id, on: None)

    clock = Clock(monkeypatch)
    fake = Typing([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    monkeypatch.setenv("INSTAGRAM_DM_WRITE_GAP", "0")
    monkeypatch.setenv("INSTAGRAM_DM_WRITE_JITTER", "0")
    for i in range(10):  # a reaction and a typing indicator each
        assert reply_ok("t" * 101, None, "\u2764", True) is None
        clock.now += 1
    assert len(fake.reacted) == 10 and len(fake.sent) == 10  # texts have their own, lower cap: 10 an hour
    assert "limit of 20 react/typing writes per 1 h" in reply_ok(None, None, "\u2764", False)
    clock.now += 3600
    assert reply_ok(None, None, "\u2764", False) is None


def test_typing_comes_only_before_a_reply_over_100_characters(monkeypatch, host):
    class Typing(Fake):
        def realtime_connect(self):
            return NS(direct_indicate_activity=lambda thread_id, on: None)

    Clock(monkeypatch)
    monkeypatch.setattr(ig, "client", lambda: Typing([msg("m1", text="hi")]))
    assert reply_ok("s" * 100, None, None, True) is None
    assert [k for _, k in writes(host)] == ["text"]
    assert reply_ok("l" * 101, None, None, True) is None
    assert [k for _, k in writes(host)] == ["text", "typing", "text"]
    assert reply_ok(None, None, None, True) is None  # a lone typing request has nothing left to do
    assert [k for _, k in writes(host)] == ["text", "typing", "text"]


def test_an_error_stops_sends_for_30_minutes_but_not_reads(monkeypatch, host):
    clock = Clock(monkeypatch)
    state = ig.load_state()
    ig.fail(state, RuntimeError("boom"), clock.now)
    ig.save_state(state)
    fake = Fake([msg("m1", text="hi")])
    monkeypatch.setattr(ig, "client", lambda: fake)
    clock.now += 300  # the 120 s read backoff is over
    assert ig.sync(lambda: fake) is None and logged(host) == ["m1"]
    assert "send cooldown" in reply_ok("hi", None, None, False)
    clock.now += 1500
    assert reply_ok("hi", None, None, False) is None


def test_a_read_receipt_waits_for_the_gap_and_a_flag_on_it_halts(monkeypatch, host):
    clock = Clock(monkeypatch)
    fake = Fake([msg("m1", text="hi")])
    state = ig.load_state()
    ig.record_write(state, "text")  # a send just went out
    ig.save_state(state)
    assert ig.sync(lambda: fake) is None and fake.seen == []  # inside the gap: no receipt, and no waiting
    assert clock.now == 100000
    fake2 = Fake([msg("m2", text="hi")])
    clock.now += 100
    assert ig.sync(lambda: fake2) is None and fake2.seen == [("7", "m2")]

    class LoginRequired(Exception):
        pass

    def flagged(thread_id, message_id):
        raise LoginRequired("login_required")

    fake3 = Fake([msg("m3", text="hi")])
    fake3.direct_message_seen = flagged
    clock.now += 100
    assert "halted (LoginRequired" in ig.sync(lambda: fake3)


def test_events_coalesce_into_one_poll_30s_after_the_last(monkeypatch, host):
    clock = Clock(monkeypatch)

    class Live(Fake):
        polls = 0
        reads = 0

        def direct_threads(self, amount):
            self.polls += 1
            return super().direct_threads(amount)

        def realtime_on(self, name, handler):
            self.handler = handler

        def realtime_connect(self):
            return NS(direct_subscribe=lambda: None, ping=lambda: True)

        def realtime_read_once(self):
            self.reads += 1
            clock.now += 5
            if 1 <= self.reads <= 9:  # an event every 5 s for 45 s
                self.handler({"event": self.reads})
            if self.reads == 20:
                ig.save_state({**ig.load_state(), "halted": "stop the test"})

    live = Live()
    ig.listen_once(live)
    assert live.polls == 1 + 2  # the poll on connect, one at +30 s, one for the events after it


def test_a_halt_writes_the_flag_file_and_resume_removes_it(monkeypatch, host):
    def flagged():
        raise ChallengeError("checkpoint")

    monkeypatch.setattr(ig, "client", flagged)
    run(monkeypatch, ig.poll, 1000)
    assert "ChallengeError" in (host / "stop").read_text()  # what the desk and the shell tools look at
    ig.resume()
    assert not (host / "stop").exists()


def test_stop_is_a_kill_switch_for_every_command_and_resume_ends_it(monkeypatch, host):
    made = lib(monkeypatch)
    (host / "session.json").write_text(json.dumps({"uuids": {"u": 1}, "device_settings": {"m": 1}}))
    monkeypatch.setenv("INSTAGRAM_DM_SESSION", str(host / "session.json"))
    ig.stop()
    assert (host / "stop").read_text() == "stopped by hand"
    for call in (ig.client, lambda: ig.reply("hi", None, None, False)):
        with pytest.raises(SystemExit, match="stopped by hand"):
            call()
    ig.poll()  # the timer's poll ends quietly
    assert made == []  # no client was even built
    ig.listen()  # returns at once instead of connecting
    ig.resume()
    assert ig.client() is not None and len(made) == 1


def test_a_halt_from_before_the_flag_file_still_stops_everything(monkeypatch, host):
    (host / "poll.json").write_text(json.dumps({"halted": "AccountSuspended: challenge_required"}))
    with pytest.raises(SystemExit, match="AccountSuspended"):
        ig.client()


class Spy:
    """Wraps a client and records every method the code calls on it."""

    def __init__(self, inner):
        self.inner, self.calls = inner, []

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            self.calls.append(name)
            return attr(*args, **kwargs)

        return call


def test_a_reel_dm_files_its_metadata_in_the_note_and_makes_no_extra_request(monkeypatch, host):
    clip = {"user": NS(username="creator"), "caption_text": "A  new\nopen-source tool", "video_duration": 23.4}
    spy = Spy(Fake([msg("m1", code="C1", meta=clip), msg("m2", text="hi", at=2000)]))
    monkeypatch.setattr(ig, "client", lambda: spy)
    assert run(monkeypatch, ig.poll, 1000) is None
    note = [n for n in notified(host) if "reel/C1" in n[-1]][0][-1]
    assert note == (
        "[Instagram DM from op; answer with fm-insta-reply] https://www.instagram.com/reel/C1/"
        ' (by @creator, 23.4 s) caption: "A new open-source tool"'
    )
    row = json.loads((host / "messages.jsonl").read_text().splitlines()[0])
    assert row["meta"] == {"author": "creator", "caption": "A new open-source tool", "duration": 23.4}
    # the two inbox reads and the read receipt: no media, clip, user or download request
    assert sorted(set(spy.calls)) == ["direct_message_seen", "direct_pending_inbox", "direct_threads"]


def test_a_shared_reel_without_metadata_and_a_plain_text_keep_the_short_note(monkeypatch, host):
    monkeypatch.setattr(ig, "client", lambda: Fake([msg("m1", code="C2")]))
    assert run(monkeypatch, ig.poll, 1000) is None
    assert notified(host)[0][-1].endswith("fm-insta-reply] https://www.instagram.com/reel/C2/")
    assert "meta" not in json.loads((host / "messages.jsonl").read_text())
