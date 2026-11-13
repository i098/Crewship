"""The desk session in bridge.ts: one long omp RPC chat, here a fake child, that ends each turn in one checked action."""

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from test_imessage import SEND, read_text, wait_for
from test_imessage_v2 import deliver, events, omp_masks, texts, v2_rig

FAKE = Path(__file__).resolve().parent / "fake_desk_omp.ts"


pytestmark = pytest.mark.skipif(
    not (shutil.which("bun") and shutil.which("curl")) or not omp_masks(),
    reason="needs bun, curl and the installed omp secret packages",
)


@contextmanager
def session_rig(tmp_path, **extra):
    """A V2 bridge with the desk session on, over the fake omp child; `rig.desk_log` holds its argv and prompts."""
    log, shadow = tmp_path / "fake-desk.jsonl", tmp_path / "shadow"
    shadow.mkdir()
    wrapper = shadow / "omp"
    # The bridge passes the child a fixed env allowlist, so the log path rides in the wrapper.
    wrapper.write_text(f'#!/bin/bash\nFAKE_DESK_LOG={shlex.quote(str(log))} exec bun {shlex.quote(str(FAKE))} "$@"\n')
    wrapper.chmod(0o755)
    path = f"{shadow}:{tmp_path / 'bin'}:{os.environ['PATH']}"
    with v2_rig(tmp_path, None, inception="http://127.0.0.1:9/v1/chat/completions",
                FM_IMESSAGE_DESK_SESSION="true", PATH=path, **extra) as rig:
        rig.desk_log = log
        yield rig


def desk_lines(rig, key):
    return [row[key] for row in map(json.loads, read_text(rig.desk_log).splitlines()) if key in row]


def test_plain_text_gets_the_session_reply(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        assert texts(rig)[0].split(" ", 1)[1] == "Fake desk reply."
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
        assert read_text(sent).splitlines() == ["mate1 [from captain via desk] RELAY mate1", "[desk request bluebubbles-m1]"]
        assert texts(rig) == []


def test_fleet_status_names_the_listed_mates_so_the_session_can_pick_one(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/secondmates.md").write_text(f"- mate1 - Repo mate (home: {tmp_path}/mate1; scope: repo checks; projects: none)\n")
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "STATUS")
        wait_for(lambda: len(texts(rig)) == 1, "the status reply", timeout=120)
        assert "mate mate1: repo checks" in texts(rig)[0]


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


def test_a_turn_in_plain_words_is_reminded_once_and_then_replies_with_the_tool(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you PLAIN")
        wait_for(lambda: len(texts(rig)) == 1, "the reply after the reminder", timeout=120)
        time.sleep(1)
        assert texts(rig)[0].split(" ", 1)[1] == "Fake desk reply."
        prompts = desk_lines(rig, "prompt")
        assert len(prompts) == 2 and "without an action tool" in prompts[1]
        assert not any(e.get("route") == "handoff" for e in events(rig))


def test_a_model_that_keeps_answering_in_plain_words_has_its_words_sent_as_the_reply(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you STUBBORN")
        wait_for(lambda: len(texts(rig)) == 1, "the plain words as the reply", timeout=120)
        time.sleep(1)
        assert texts(rig)[0].split(" ", 1)[1] == "Stubborn words."
        assert len(desk_lines(rig, "prompt")) == 2
        assert not any(e.get("route") == "handoff" for e in events(rig))


def test_plain_words_the_reply_checks_refuse_go_to_firstmate(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "STUBBORN STATUSLINE")
        wait_for(lambda: any(e.get("route") == "handoff" for e in events(rig)), "the firstmate handoff", timeout=120)
        time.sleep(1)
        assert texts(rig) == []


def test_narration_before_a_tool_call_is_not_sent_as_the_reply(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "NARRATE")
        wait_for(lambda: any(e.get("route") == "handoff" for e in events(rig)), "the firstmate handoff", timeout=120)
        time.sleep(1)
        assert texts(rig) == []


def test_plain_words_of_a_prompt_that_ended_in_error_go_to_firstmate(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "ERRORWORDS")
        wait_for(lambda: any(e.get("route") == "handoff" for e in events(rig)), "the firstmate handoff", timeout=120)
        time.sleep(1)
        assert texts(rig) == []
        assert len(desk_lines(rig, "prompt")) == 1


def test_words_of_the_first_prompt_are_not_sent_when_the_reminder_turn_fails(tmp_path):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "ERRORRETRY")
        wait_for(lambda: any(e.get("route") == "handoff" for e in events(rig)), "the firstmate handoff", timeout=120)
        time.sleep(1)
        assert texts(rig) == []
        assert len(desk_lines(rig, "prompt")) == 2


@pytest.mark.parametrize("compacted", [True, False])
def test_the_reminder_turn_carries_the_chat_view_only_after_a_compaction(tmp_path, compacted):
    with session_rig(tmp_path) as rig:
        deliver(rig, "m1", "how are you PLAIN" + (" COMPACT" if compacted else ""))
        wait_for(lambda: len(texts(rig)) == 1, "the reply after the reminder", timeout=120)
        time.sleep(1)
        prompts = desk_lines(rig, "prompt")
        assert len(prompts) == 2 and "without an action tool" in prompts[1]
        assert ("<chat>" in prompts[1]) == compacted


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
        assert texts(rig)[0].split(" ", 1)[1] == ("Your text is queued for the mate1 mate" if target == "mate1" else "Your text is queued for Firstmate")
        wait_for(message.exists, "the task delivery", timeout=120)
        assert not finished.exists()  # the reply was sent while the delivery was still open
        release.touch()
        wait_for(finished.exists, "the task delivery to end", timeout=120)
        sent = read_text(message)
        assert sent.startswith("[from captain via desk] DELEGATE ")
        assert "fm-imessage" not in sent  # the answer file is the only answer channel
        answer = re.search(r"to (\S+\.answer)(?:\n\[desk request [^\]]+\])?$", sent).group(1)
        Path(answer).write_text("The repo checks are green.")
        wait_for(lambda: len(texts(rig)) == 2, "the reported answer", timeout=120)
        assert texts(rig)[1].split(" ", 1)[1] == "The repo checks are green."
        assert not Path(answer).exists()


def test_task_report_survives_a_new_owner_text_during_delivery(tmp_path):
    message = tmp_path / "task-message"
    second = "The second bubble is long on purpose, so the pause before it is the full two and a half seconds of typing."
    with session_rig(tmp_path) as rig:
        script = tmp_path / "bin" / "fm-inbox"
        script.write_text(f'#!/bin/bash\n[ "$1" = note ] || exit 0\n[ -e {shlex.quote(str(message))} ] || printf "%s" "$5" > {shlex.quote(str(message))}\n')
        script.chmod(0o755)
        deliver(rig, "m1", "DELEGATE firstmate")
        wait_for(message.exists, "the task delivery", timeout=120)
        Path(re.search(r"to (\S+\.answer)$", read_text(message)).group(1)).write_text(f"First bubble.\n\n{second}")
        wait_for(lambda: len(texts(rig)) == 2, "the first bubble of the report", timeout=120)
        deliver(rig, "m2", "how are you HANDOFF")  # a new owner text moves the desk generation before the second bubble
        wait_for(lambda: len(texts(rig)) == 3, "the second bubble of the report", timeout=120)
        assert [line.split(" ", 1)[1] for line in texts(rig)] == ["Your text is queued for Firstmate", "First bubble.", second]


def test_answer_written_while_the_bridge_is_down_is_sent_once_after_the_restart(tmp_path):
    message = tmp_path / "task-message"
    with session_rig(tmp_path) as rig:
        script = tmp_path / "bin" / "fm-inbox"
        script.write_text(f'#!/bin/bash\n[ "$1" = note ] || exit 0\n[ -e {shlex.quote(str(message))} ] || printf "%s" "$5" > {shlex.quote(str(message))}\n')
        script.chmod(0o755)
        deliver(rig, "m1", "DELEGATE firstmate")
        wait_for(lambda: len(texts(rig)) == 1 and message.exists(), "the reply and the task delivery", timeout=120)
        answer = Path(re.search(r"to (\S+\.answer)$", read_text(message)).group(1))
        rig.stop()
        answer.write_text("The repo checks are green.")
        rig.start()
        wait_for(lambda: len(texts(rig)) == 2, "the answer after the restart", timeout=120)
        time.sleep(1.5)
        assert [line.split(" ", 1)[1] for line in texts(rig)] == ["Your text is queued for Firstmate", "The repo checks are green."]
        assert not answer.exists()


def test_cancelled_delegated_ack_does_not_send_the_text_to_firstmate_twice(tmp_path):
    ids = tmp_path / "note-ids"
    with session_rig(tmp_path) as rig:
        script = tmp_path / "bin" / "fm-inbox"
        script.write_text(f'#!/bin/bash\n[ "$1" = note ] || exit 0\nprintf "%s\\n" "$3" >> {shlex.quote(str(ids))}\n')
        script.chmod(0o755)
        (rig.fake / "relay-mode").write_text("send-busy")  # the relay refuses the ack, so it stays in the outbox
        deliver(rig, "m1", "DELEGATE firstmate")
        wait_for(lambda: (rig.fake / "relay-payloads").exists(), "the refused ack", timeout=120)
        deliver(rig, "m2", "second text HANDOFF")  # the new text cancels the ack of the first
        (rig.fake / "relay-mode").unlink()
        wait_for(lambda: any(line.startswith("desk-task-") for line in read_text(ids).splitlines())
                 and "bluebubbles-m2" in read_text(ids).splitlines(), "both notes", timeout=120)
        time.sleep(2)
        assert "bluebubbles-m1" not in read_text(ids).splitlines()
        assert len([line for line in read_text(ids).splitlines() if line.startswith("desk-task-")]) == 1


def mate_data(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/secondmates.md").write_text(
        f"- engram - Engram mate (home: {tmp_path}/engram; scope: engram work; projects: none)\n"
        f"- atlas - Atlas mate (home: {tmp_path}/atlas; scope: atlas work; projects: none)\n")
    return tmp_path / "task-message"


def mate_script(tmp_path, message):
    script = tmp_path / "bin" / "fm-send.sh"
    script.write_text(f'#!/bin/bash\nprintf "%s %s" "$1" "$2" > {shlex.quote(str(message))}\n')
    script.chmod(0o755)


def send_bubble(rig, text, home, count):
    sent = subprocess.run([str(SEND), text], capture_output=True, text=True, env={**rig.env, "FM_HOME": home}, timeout=30)
    assert sent.returncode == 0, sent.stderr
    wait_for(lambda: len(texts(rig)) == count, "the bubble", timeout=120)


def wait_saved(rig, text, count):
    wait_for(lambda: len([row for row in json.loads(read_text(rig.state / "senders.json") or "[]") if row["key"] == text]) == count,
             "the saved sender record")


def reply_in_thread(rig, guid, quoted_guid, quoted_text, text):
    rig.relay_message(quoted_guid, quoted_text, int(time.time() * 1000), isFromMe=True)
    rig.relay_message(guid, text, int(time.time() * 1000) + 1, threadOriginatorGuid=quoted_guid)
    subprocess.run(["curl", "-sS", "-d", json.dumps({"type": "new-message", "data": {"guid": guid}}),
                    f"http://127.0.0.1:{rig.hook_port}/bluebubbles"], check=True, capture_output=True)


def test_thread_reply_to_a_mates_bubble_goes_to_that_mate_even_after_a_restart(tmp_path):
    message = mate_data(tmp_path)
    with session_rig(tmp_path) as rig:
        mate_script(tmp_path, message)
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        send_bubble(rig, "The engram checks are green.", f"{tmp_path}/engram", 2)
        wait_for((rig.state / "senders.json").exists, "the saved sender record")
        rig.stop()
        rig.start()
        reply_in_thread(rig, "m3", "b1", "The engram checks are green.", "nice, thanks")
        wait_for(message.exists, "the relay to the mate", timeout=120)
        assert read_text(message) == (
            "engram [from captain via desk] nice, thanks\n"
            + f"(this message is a thread reply to an earlier message from a sender the bridge did not record, whose untrusted quoted text is: {json.dumps('The engram checks are green.')})\n"
            + "[desk request bluebubbles-m3]"
        )
        assert len(texts(rig)) == 2  # no model reply to the owner


def test_thread_reply_to_a_desk_bubble_with_a_mates_old_text_is_a_desk_turn(tmp_path):
    message = mate_data(tmp_path)
    with session_rig(tmp_path) as rig:
        mate_script(tmp_path, message)
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        send_bubble(rig, "On it.", f"{tmp_path}/engram", 2)
        send_bubble(rig, "On it.", "", 3)  # no sender: the latest bubble with this text is not the mate's
        wait_saved(rig, "On it.", 2)
        reply_in_thread(rig, "m3", "b1", "On it.", "thanks")
        wait_for(lambda: len(texts(rig)) == 4, "the session reply", timeout=120)
        assert not message.exists()


def test_thread_reply_goes_to_the_mate_that_sent_the_quoted_bubble_when_two_mates_sent_the_same_text(tmp_path):
    message = mate_data(tmp_path)
    with session_rig(tmp_path) as rig:
        mate_script(tmp_path, message)
        deliver(rig, "m1", "how are you")
        wait_for(lambda: len(texts(rig)) == 1, "the session reply", timeout=120)
        send_bubble(rig, "Done.", f"{tmp_path}/engram", 2)
        send_bubble(rig, "Done.", f"{tmp_path}/atlas", 3)
        wait_saved(rig, "Done.", 2)
        # The fake relay names a sent message "srv-<tempGuid>", as a real server gives its own guid, not the client's.
        guids = [f"srv-{json.loads(line)['tempGuid']}" for line in read_text(rig.fake / "relay-payloads").splitlines() if json.loads(line)["message"] == "Done."]
        assert len(guids) == 2
        for n, (guid, mate) in enumerate(zip(guids, ["engram", "atlas"]), start=2):
            message.unlink(missing_ok=True)
            reply_in_thread(rig, f"m{n}", guid, "Done.", f"thanks {mate}")
            wait_for(message.exists, f"the relay to {mate}", timeout=120)
            assert read_text(message) == (
                f"{mate} [from captain via desk] thanks {mate}\n"
                + f"(this message is a thread reply to an earlier message from us (sender {tmp_path}/{mate}), whose untrusted quoted text is: \"Done.\")\n"
                + f"[desk request bluebubbles-m{n}]"
            )
        message.unlink()
        reply_in_thread(rig, "m4", "unknown-guid", "Done.", "thanks")  # no id match and two senders: a desk turn
        wait_for(lambda: len(texts(rig)) == 4, "the session reply", timeout=120)
        assert not message.exists()
