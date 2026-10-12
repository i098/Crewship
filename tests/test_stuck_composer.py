"""stuck-composer.check.sh rendered from its template, run in a fake Firstmate home with stubbed herdr."""

import os
import shlex
import subprocess
import time
from pathlib import Path

import jinja2

ROOT = Path(__file__).parents[1]
TEMPLATE = ROOT / "blueprint/ansible/templates/stuck-composer.check.sh.j2"
STUB = "#!/usr/bin/env bash\n"


def setup(tmp_path, pane_text, msg_age=300, seen=None):
    home = tmp_path / "fm"
    (home / "bin").mkdir(parents=True)
    (home / "state/m1.inbox").mkdir(parents=True)
    (home / "state/m1.meta").write_text("kind=secondmate\nwindow=default:w1\n")
    (home / "state/m1.inbox/001.msg").write_text("hi")
    t = time.time() - msg_age
    os.utime(home / "state/m1.inbox/001.msg", (t, t))
    (home / "bin/fm-backend.sh").write_text(
        'fm_backend_send_text_submit() { echo "submit $2 $3" >> "$LOG"; }\n'
    )
    (home / "bin/fm-task-inbox-lib.sh").write_text(
        'fm_task_inbox_doorbell_line() { echo "bell $1"; }\n'
    )
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    herdr = stubs / "herdr"
    herdr.write_text(
        STUB
        + 'case "$2" in read) printf "out\\n%s\\n" "$PANE";; send-keys) echo "keys $3 $4" >> "$LOG";; esac\n'
    )
    sleep = stubs / "sleep"
    sleep.write_text(STUB)
    for f in (herdr, sleep):
        f.chmod(0o755)
    if seen:
        d = home / "state/.stuck-composer"
        d.mkdir()
        (d / "m1.seen").write_text(seen)
    script = tmp_path / "check.sh"
    jenv = jinja2.Environment(undefined=jinja2.StrictUndefined)
    jenv.filters["quote"] = shlex.quote
    script.write_text(
        jenv.from_string(TEMPLATE.read_text()).render(
            crewship_firstmate_dir=str(home),
            crewship_stuck_composer_msg_age=120,
            crewship_stuck_composer_hold=120,
            crewship_stuck_composer_poll=30,
        )
    )
    env = {"PATH": f"{stubs}:/usr/bin:/bin", "LOG": str(tmp_path / "log"), "PANE": pane_text}
    out = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, check=True
    ).stdout
    log = (tmp_path / "log").read_text() if (tmp_path / "log").exists() else ""
    return home, out, log


def seen_for(text, age):
    import hashlib

    return f"{hashlib.sha1(text.encode()).hexdigest()[:12]} {int(time.time()) - age}\n"


def test_clears_text_held_past_threshold(tmp_path):
    home, out, log = setup(tmp_path, "❯ can you spin up a", seen=seen_for("can you spin up a", 200))
    assert "stuck composer cleared: m1" in out
    assert "keys w1 ctrl+u" in log and "submit default:w1 bell state/m1.inbox/001.msg" in log
    saved = list((home / "state/.stuck-composer").glob("m1.*.txt"))
    assert [p.read_text() for p in saved] == ["can you spin up a\n"]


def test_leaves_text_held_under_threshold(tmp_path):
    _, out, log = setup(tmp_path, "❯ typing", seen=seen_for("typing", 30))
    assert out == "" and log == ""


def test_changed_text_restarts_the_timer(tmp_path):
    home, out, log = setup(tmp_path, "❯ new text", seen=seen_for("old text", 500))
    assert out == "" and log == ""
    assert (home / "state/.stuck-composer/m1.seen").read_text().split()[0] != seen_for(
        "old text", 0
    ).split()[0]


def test_young_inbox_message_is_not_stuck(tmp_path):
    _, out, log = setup(tmp_path, "❯ text", msg_age=10, seen=seen_for("text", 500))
    assert out == "" and log == ""
