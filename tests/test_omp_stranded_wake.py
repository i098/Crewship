"""blueprint/config/omp-stranded-wake.ts, run under bun: when it starts a turn."""

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

SCRIPT = """
import ext from {ext};
const handlers = {{}};
const sent = [];
ext({{ on: (e, h) => (handlers[e] = h), sendUserMessage: (t) => sent.push(t) }});
await handlers.session_start({{}}, {{ cwd: {home}, agent: {{ kind: {kind} }}, isIdle: () => {idle} }});
await new Promise((r) => setTimeout(r, 2500));
if ({again}) {{ await handlers.agent_end({{}}, {{}}); await new Promise((r) => setTimeout(r, 1500)); }}
handlers.session_shutdown({{}});
console.log(JSON.stringify({{ sent }}));
"""


def run(home: Path, idle: bool = True, kind: str = "main", again: bool = False) -> dict:
    code = SCRIPT.format(
        ext=json.dumps(str(ROOT / "blueprint/config/omp-stranded-wake.ts")),
        home=json.dumps(str(home)),
        kind=json.dumps(kind),
        idle="true" if idle else "false",
        again="true" if again else "false",
    )
    out = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True, timeout=60
    )
    return json.loads(out.stdout)


@pytest.fixture
def home(tmp_path: Path) -> Path:
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "fm-wake-drain.sh").write_text("#!/bin/sh\n")
    (tmp_path / "state" / "inbox").mkdir(parents=True)
    return tmp_path


def age(path: Path, seconds: float) -> None:
    t = time.time() - seconds
    os.utime(path, (t, t))


def plant(home: Path, seconds: float) -> None:
    note = home / "state" / "inbox" / "1-test.note"
    note.write_text("owner text\n")
    age(note, seconds)


def test_old_note_while_idle_starts_a_turn(home):
    plant(home, 61)
    result = run(home)
    assert len(result["sent"]) == 1
    assert "STRANDED WAKE" in result["sent"][0]
    assert (home / "state" / ".stranded-wake.log").read_text().count("woken") == 1


def test_queued_wake_alone_counts(home):
    q = home / "state" / ".wake-queue"
    q.write_text("1\twake\n")
    age(q, 61)
    assert len(run(home)["sent"]) == 1


def test_fresh_note_is_left_for_the_grace_period(home):
    plant(home, 0)
    assert run(home)["sent"] == []


def test_busy_session_is_not_interrupted(home):
    plant(home, 61)
    assert run(home, idle=False)["sent"] == []


def test_subagent_and_non_firstmate_cwd_are_ignored(home, tmp_path_factory):
    plant(home, 61)
    assert run(home, kind="sub")["sent"] == []
    assert run(tmp_path_factory.mktemp("plain"))["sent"] == []


def test_a_stuck_item_wakes_once_and_a_new_item_wakes_again(home):
    plant(home, 61)
    assert len(run(home, again=True)["sent"]) == 1
    assert len(run(home, again=True)["sent"]) == 0
    assert (home / "state" / ".stranded-wake.log").read_text().count("woken") == 1
    note = home / "state" / "inbox" / "2-test.note"
    note.write_text("another\n")
    age(note, 61)
    assert len(run(home)["sent"]) == 1


def test_marker_is_written_at_start_and_removed_at_shutdown(home):
    code = SCRIPT.replace("handlers.session_shutdown({{}});", "").replace(
        "console.log(JSON.stringify({{ sent }}));",
        "import {{ existsSync, readFileSync }} from 'node:fs';"
        "const m = {home} + '/state/.stranded-wake.loaded/' + process.pid;"
        "const during = existsSync(m) ? JSON.parse(readFileSync(m, 'utf8')) : null;"
        "handlers.session_shutdown({{}});"
        "console.log(JSON.stringify({{ during, after: existsSync(m), pid: process.pid }}));",
    )
    out = subprocess.run(
        ["bun", "-e", code.format(
            ext=json.dumps(str(ROOT / "blueprint/config/omp-stranded-wake.ts")),
            home=json.dumps(str(home)), kind='"main"', idle="true", again="false")],
        capture_output=True, text=True, check=True, timeout=60,
    )
    seen = json.loads(out.stdout)
    assert seen["during"]["pid"] == seen["pid"]
    assert seen["after"] is False
