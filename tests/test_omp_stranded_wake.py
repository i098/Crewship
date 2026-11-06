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
handlers.session_shutdown({{}});
console.log(JSON.stringify({{ sent }}));
"""


def run(home: Path, idle: bool = True, kind: str = "main") -> dict:
    code = SCRIPT.format(
        ext=json.dumps(str(ROOT / "blueprint/config/omp-stranded-wake.ts")),
        home=json.dumps(str(home)),
        kind=json.dumps(kind),
        idle="true" if idle else "false",
    )
    out = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True, timeout=60)
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
