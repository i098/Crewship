import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

SKILL = Path(__file__).parents[1] / "blueprint/skills/public/instagram-dm"
# The public-skill privacy scan reads every file in the skill folder: leave no .pyc there.
sys.dont_write_bytecode = True
sys.path.insert(0, str(SKILL))
SPEC = importlib.util.spec_from_file_location("reel_curator", SKILL / "reel_curator.py")
rc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rc)

CFG = {**rc.DEFAULTS, "accounts": ["a"], "hashtags": ["t"], "jitter": [0, 0]}


class PleaseWaitFewMinutes(Exception):
    pass


def reel(code, likes=1, caption=""):
    return NS(
        code=code,
        id=f"{code}_1",
        product_type="clips",
        like_count=likes,
        caption_text=caption,
        taken_at=datetime.fromtimestamp(time.time() - 3600, timezone.utc),
        user=NS(username="creator"),
    )


class Client:
    def __init__(self, user=(), tag=(), thread=(), fail=None):
        self.user, self.tag, self.thread, self.fail = user, tag, thread, fail

    def user_id_from_username(self, name):
        return 1

    def user_clips_v1(self, uid, amount):
        if self.fail:
            raise self.fail
        return list(self.user)

    def hashtag_medias_reels_v1(self, name, amount):
        return list(self.tag)

    def direct_messages(self, thread, amount):
        return [NS(code=c) for c in self.thread]


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("CURATOR_LOG", str(tmp_path / "reels.jsonl"))
    monkeypatch.setenv("INSTAGRAM_DM_DIR", str(tmp_path / "dm"))
    monkeypatch.setenv("INSTAGRAM_DM_OPERATOR", "2")
    monkeypatch.setenv("INSTAGRAM_DM_ACTOR", "curator")  # main() sets it; keep it out of the other tests
    monkeypatch.setattr(rc.ig, "operator_thread", lambda cl, thread, op: NS(id="9"))
    monkeypatch.setattr(rc.ig, "message_url", lambda m: f"https://www.instagram.com/reel/{m.code}/")
    monkeypatch.setattr(rc, "transcribe", lambda cl, m: ("a new open source tool", None))
    monkeypatch.setattr(rc, "score", lambda cfg, m, s: {"score": 8, "what": "A tool", "why": "Useful."})
    monkeypatch.setattr(rc, "resolve", lambda info, caption: "https://github.com/o/r")
    sent = []
    monkeypatch.setattr(rc, "send", lambda cl, t, m, line: sent.append(m.code))
    return sent


def test_logged_and_thread_reels_are_never_scored_or_sent_again(env):
    rc.write_log(action="reject", code="old", score=2)
    cl = Client(user=[reel("old"), reel("his"), reel("new", 5)], tag=[reel("new", 5)], thread=["his"])
    rc.cycle(cl, CFG, time.time())
    assert env == ["new"]  # one send: the same reel from account and hashtag counts once
    rc.cycle(cl, CFG, time.time())
    assert env == ["new"]  # its pick row is in the log now


def test_daily_cap_stops_before_any_request_and_limits_sends(env):
    for i in range(3):
        rc.write_log(action="pick", code=f"p{i}", score=9)
    cl = Client(fail=RuntimeError("must not be called"))
    assert "cap" in rc.cycle(cl, CFG, time.time())
    assert env == []

    Path(rc.log_file()).write_text("")
    rc.write_log(action="pick", code="p0", score=9)
    cl = Client(user=[reel(c, i) for i, c in enumerate("xyz")])
    rc.cycle(cl, CFG, time.time())
    assert len(env) == 2  # 1 of 3 already sent today


def test_yesterdays_picks_do_not_count(env):
    f = rc.log_file()
    f.write_text("".join(json.dumps({"at": int(time.time()) - 2 * 86400, "action": "pick", "code": f"p{i}"}) + "\n" for i in range(3)))
    rc.cycle(Client(user=[reel("n")]), CFG, time.time())
    assert env == ["n"]


@pytest.mark.parametrize(
    ("text", "score", "pick"),
    [
        ("Comment DRIVE and I'll send you the repo link", 8, False),
        ("Comment DRIVE and I'll send you the repo link", 9, True),
        ("link in bio", 7, False),
        ("a free open source dashboard", 8, True),
        ("a free open source dashboard", 6, False),
    ],
)
def test_bait_needs_a_stronger_score(text, score, pick):
    assert rc.judge(CFG, "", text, {"score": score})[0] is pick


def test_rejection_is_logged_with_its_score_and_not_sent(env, monkeypatch):
    monkeypatch.setattr(rc, "score", lambda cfg, m, s: {"score": 8})
    rc.cycle(Client(user=[reel("b", caption="Comment LINK for the repo")]), CFG, time.time())
    assert env == []
    (row,) = rc.read_log()
    assert (row["action"], row["code"], row["score"]) == ("reject", "b", 8)


def test_a_429_stops_the_curator_for_a_day_and_is_logged(env, monkeypatch, capsys):
    monkeypatch.setattr(rc, "load_config", lambda: CFG)
    monkeypatch.setattr(rc.ig, "client", lambda: Client(fail=PleaseWaitFewMinutes("slow down")))
    monkeypatch.setattr(sys, "argv", ["reel_curator.py", "run"])
    with pytest.raises(SystemExit, match="24 h"):
        rc.main()
    (row,) = rc.read_log()
    assert row["action"] == "halt" and row["until"] > time.time() + 86000
    monkeypatch.setattr(rc.ig, "client", lambda: pytest.fail("called Instagram while stopped"))
    with pytest.raises(SystemExit, match="stopped"):
        rc.main()


def test_the_kill_switch_stops_the_curator_before_any_request(env, monkeypatch, tmp_path):
    monkeypatch.setattr(rc, "load_config", lambda: CFG)
    monkeypatch.setattr(rc.ig, "client", lambda: pytest.fail("called Instagram while stopped"))
    monkeypatch.setattr(sys, "argv", ["reel_curator.py", "run"])
    rc.ig.stop()
    with pytest.raises(SystemExit, match="stopped by hand"):
        rc.main()


@pytest.mark.parametrize(
    ("spoken", "speech", "caption", "lang"),
    [
        (None, "Se avessero davvero decompilato Photoshop, in Italia sarebbe reato. Non è un dettaglio da nerd.", "", "it"),
        (None, "Claude trouve toujours ton idée géniale. C'est exactement le problème, et le lien est dans la description.", "", "fr"),
        ("fr", "this is a free open source tool that you can use", "", "fr"),  # the transcriber's language wins
        (None, "this is a free open source tool that you can use", "Le skill est gratuit et open source pour tous ceux qui codent", "fr"),
        (None, "", "これはオープンソースのツールです", "other"),
        ("en", "this is a free open source tool that you can use", "A free tool for you, with a link in the repo", None),
        (None, "", "", None),  # nothing to judge
        (None, "", "#claudecode #ai", None),  # too short to judge
    ],
)
def test_non_english_by_transcriber_speech_or_caption(spoken, speech, caption, lang):
    assert rc.non_english(spoken, speech, caption) == lang


def test_non_english_reel_is_logged_and_never_scored_or_sent(env, monkeypatch):
    monkeypatch.setattr(rc, "transcribe", lambda cl, m: ("Claude trouve toujours ton idée, et le lien est dans la description.", None))
    monkeypatch.setattr(rc, "score", lambda *a: pytest.fail("scored a non-English reel"))
    rc.cycle(Client(user=[reel("fr1")]), CFG, time.time())
    assert env == []
    (row,) = rc.read_log()
    assert (row["action"], row["code"], row["reason"]) == ("reject", "fr1", "non-english:fr")
