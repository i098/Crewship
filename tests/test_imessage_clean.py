"""Outbound text filter (apps/imessage/clean.ts) and its use by the fm-imessage CLI. Fixture strings only."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLEAN = ROOT / "apps/imessage/clean.ts"
CLI = ROOT / "apps/imessage/fm-imessage"
pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def clean(text):
    return subprocess.run(["bun", str(CLEAN)], input=text, capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("text,want", [
    ("[D039b88] Ship it", "Ship it"),
    ("Ship it [key=nm-1-ci] now", "Ship it now"),
    ("Ship it key=abc corr=xyz", "Ship it"),
    ("working: building\ndone: built", "building\nbuilt"),
    ("[D0123ab] needs-decision: pick one", "pick one"),
    ("Blocked: x\npaused: z", "Blocked: x\nz"),
    ("Asked crewship-mate-c1 and `cf-text-filter` and `sm-fleet` and bob-mate-7 today", "Asked and and and today"),
    ("cf-text-filter: working: built", "built"),
    ("See /home/a/b.txt and /sdb-disk/x ~/notes /tmp/y state/z.log data/q.json", "See and"),
    ("Use data/science and cf-style, sm-ooth, state/of the art, and/or 1/2", "Use data/science and cf-style, sm-ooth, state/of the art, and/or 1/2"),
    ("Tests failed (decision stuck after 3 attempts). Next.", "Tests failed. Next."),
    ("Decision stuck after 3 attempts on cf-x build\nNext step", "Next step"),
    ("send /stop to cancel", "send /stop to cancel"),
    ("Not a status: working: ok mid-line done: x", "Not a status: working: ok mid-line done: x"),
    ("[D039b88] one\n\n\n\ntwo   three ( ) [ ]", "one\n\ntwo three"),
])
def test_rules(text, want):
    assert clean(text) == want


def test_urls_are_untouched():
    text = "Open https://example.com/data/x?key=1&corr=2 or http://h/tmp/cf-a"
    assert clean(text) == text


def test_text_without_slop_stays_byte_exact():
    assert clean("  a  b \n\n\n\nc ") == "  a  b \n\n\n\nc "


def test_empty_result_falls_back_to_original():
    assert clean("[D039b88]") == "[D039b88]"


def cli(*args, stdin=None, tmp_path=None, bun_ok=True):
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "curl").write_text('#!/bin/bash\ncat > "$STUB_OUT"\n')
    (stub / "curl").chmod(0o755)
    out = tmp_path / "sent"
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}", "STUB_OUT": str(out)}
    if not bun_ok:
        (stub / "bun").write_text("#!/bin/bash\ncat >/dev/null; echo partial; exit 1\n")
        (stub / "bun").chmod(0o755)
    r = subprocess.run([str(CLI), *args], input=stdin, capture_output=True, text=True, env=env)
    return r, out.read_text()


def test_cli_cleans_arguments_and_stdin(tmp_path):
    assert cli("done: [D039b88] Shipped /tmp/x", tmp_path=tmp_path)[1] == "Shipped"
    assert cli(stdin="working: hi `cf-abc`", tmp_path=tmp_path)[1] == "hi"


def test_cli_sends_original_when_filter_fails(tmp_path):
    r, sent = cli("done: x", tmp_path=tmp_path, bun_ok=False)
    assert sent == "done: x" and "unfiltered" in r.stderr
