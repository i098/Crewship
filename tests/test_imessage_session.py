"""The desk session in bridge.ts: one long omp RPC chat, here a fake child, that ends each turn in one checked action."""

import json
import re
import shlex
import shutil
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_imessage import read_text, wait_for
from test_imessage_v2 import deliver, events, omp_masks, texts, v2_rig

FAKE = Path(__file__).resolve().parent / "fake_desk_omp.ts"
ROUTING_RECEIPT = re.compile(r"\bI am routing\b|routing (this|the|your) request", re.I)

pytestmark = pytest.mark.skipif(
    not (shutil.which("bun") and shutil.which("curl")) or not omp_masks(),
    reason="needs bun, curl and the installed omp secret packages",
)


@contextmanager
def session_rig(tmp_path, **extra):
    """A V2 bridge with the desk session on, over the fake omp child; `rig.desk_log` holds its argv and prompts."""
    log, wrapper = tmp_path / "fake-desk.jsonl", tmp_path / "desk-omp"
    # The bridge passes the child a fixed env allowlist, so the log path rides in the wrapper.
    wrapper.write_text(f'#!/bin/bash\nFAKE_DESK_LOG={shlex.quote(str(log))} exec bun {shlex.quote(str(FAKE))} "$@"\n')
    wrapper.chmod(0o755)
    with v2_rig(tmp_path, None, inception="http://127.0.0.1:9/v1/chat/completions",
                FM_IMESSAGE_DESK_SESSION="true", FM_DESK_SESSION_OMP=str(wrapper), **extra) as rig:
        rig.desk_log = log
        yield rig


def desk_lines(rig, key):
    return [row[key] for row in map(json.loads, read_text(rig.desk_log).splitlines()) if key in row]


def test_plain_text_gets_the_session_reply(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        assert texts(rig)[0].split(" ", 1)[1] == "Fake desk reply."
        assert not ROUTING_RECEIPT.search(texts(rig)[0])
        assert not any(e.get("route") == "handoff" for e in events(rig))
        [argv] = desk_lines(rig, "argv")
        assert argv[argv.index("--model") + 1] == "claude-haiku-5-5"
        config = Path(next(argv[i + 1] for i, arg in enumerate(argv) if arg == "--config" and argv[i + 1].endswith("session-config.json")))
        assert json.loads(config.read_text())["compaction"]["modelThresholds"] == {"anthropic/claude-haiku-5-5": "f80000"}
        [prompt] = desk_lines(rig, "prompt")
        assert "1: how are you" in prompt


def test_social_text_gets_the_session_tapback(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "thanks TAPBACK")
        wait_for(lambda: "react m1 love" in texts(rig), "the tapback", timeout=120)
        time.sleep(1)
        assert texts(rig) == ["react m1 love"]


def test_protected_text_never_reaches_the_session(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "approve the deploy")
        wait_for(lambda: any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig)),
                 "the firstmate handoff", timeout=120)
        time.sleep(1)
        assert desk_lines(rig, "prompt") == []
        assert texts(rig) == []


def test_session_relays_to_a_listed_mate(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/secondmates.md").write_text(f"- mate1 - Repo mate (home: {tmp_path}/mate1; scope: repo checks; projects: none)\n")
    sent = tmp_path / "mate-sent"
    with session_rig(tmp_path) as rig:
        sender = tmp_path / "bin" / "fm-send.sh"  # the bridge finds fm-send.sh next to FM_INBOX_CMD
        sender.write_text(f'#!/bin/bash\nprintf "%s\\n" "$*" >> {shlex.quote(str(sent))}\n')
        sender.chmod(0o755)
        deliver(rig, "m1", "RELAY mate1")
        wait_for(lambda: any(e.get("handoffNote") == "routed to mate1" and e.get("route") == "done" for e in events(rig)),
                 "the mate delivery", timeout=120)
        assert read_text(sent).splitlines() == ["mate1 [from captain via desk] RELAY mate1"]
        assert texts(rig) == []


def test_bridge_restart_continues_the_same_session(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the first reply", timeout=120)
        rig.stop()
        rig.start()
        deliver(rig, "m2", "and now")
        wait_for(lambda: len(texts(rig)) == 2, "the reply after the restart", timeout=120)
        starts = desk_lines(rig, "argv")
        assert len(starts) == 2
        session_dir = str(rig.state / "desk-session" / "sessions")
        for argv in starts:
            assert "--continue" in argv
            assert argv[argv.index("--session-dir") + 1] == session_dir


def test_a_turn_with_no_action_goes_to_firstmate(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you PLAIN")
        wait_for(lambda: any(e.get("route") == "handoff" and "bluebubbles-m1" in e.get("ids", []) for e in events(rig)),
                 "the firstmate handoff", timeout=120)
        time.sleep(1)
        assert texts(rig) == []


def test_instant_reasoning_starts_the_inception_session(tmp_path):
    extra = dict(FM_IMESSAGE_DESK_PROVIDER="inception", FM_IMESSAGE_DESK_MODEL="mercury-3", FM_IMESSAGE_DESK_REASONING="instant")
    with session_rig(tmp_path, **extra) as rig:
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        [argv] = desk_lines(rig, "argv")
        assert "--thinking=off" in argv
        assert desk_lines(rig, "instant") == ["1"]
        config = Path(next(argv[i + 1] for i, arg in enumerate(argv) if arg == "--config" and argv[i + 1].endswith("session-config.json")))
        assert json.loads(config.read_text())["compaction"]["modelThresholds"] == {"inception/mercury-3": "f80000"}


@pytest.mark.parametrize("target", ["mate1", "firstmate"])
def test_delegated_task_replies_first_then_reports_the_answer(tmp_path, target):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/secondmates.md").write_text(f"- mate1 - Repo mate (home: {tmp_path}/mate1; scope: repo checks; projects: none)\n")
    message, finished, release = tmp_path / "task-message", tmp_path / "task-finished", tmp_path / "task-release"
    # The delivery blocks on the release file (at most 4.5 s: the bridge kills a sender after 5 s), so the reply must come first.
    body = f'for _ in $(seq 45); do [ -e {shlex.quote(str(release))} ] && break; sleep 0.1; done\ntouch {shlex.quote(str(finished))}\n'
    with session_rig(tmp_path) as rig:
        if target == "mate1":
            script = tmp_path / "bin" / "fm-send.sh"
            script.write_text(f'#!/bin/bash\nprintf "%s" "$2" > {shlex.quote(str(message))}\n{body}')
        else:
            script = tmp_path / "bin" / "fm-inbox"
            script.write_text(f'#!/bin/bash\n[ "$1" = note ] || exit 0\nprintf "%s" "$5" > {shlex.quote(str(message))}\n{body}')
        script.chmod(0o755)
        deliver(rig, "m1", f"DELEGATE {target}")
        wait_for(lambda: len(texts(rig)) == 1, "the reply", timeout=120)
        assert texts(rig)[0].split(" ", 1)[1] == "On it."
        wait_for(message.exists, "the task delivery", timeout=120)
        assert not finished.exists()  # the reply was sent while the delivery was still open
        release.touch()
        wait_for(finished.exists, "the task delivery to end", timeout=120)
        sent = read_text(message)
        assert sent.startswith("[from captain via desk] DELEGATE ")
        assert "fm-imessage" not in sent  # the answer file is the only answer channel
        answer = re.search(r"to (\S+\.answer)$", sent).group(1)
        Path(answer).write_text("The repo checks are green.")
        wait_for(lambda: len(texts(rig)) == 2, "the reported answer", timeout=120)
        assert texts(rig)[1].split(" ", 1)[1] == "The repo checks are green."
        assert not Path(answer).exists()
