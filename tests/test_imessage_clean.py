"""Outbound text filter (apps/imessage/clean.ts) and its use by the fm-imessage CLI. Fixture strings only."""

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
    ("[D039b88] one\n\n\n\ntwo   three ( ) [ ]", "one\n\n\n\ntwo   three ( ) [ ]"),
    ("Fix (key=abc) and now", "Fix and now"),
    ("done: x\n    nested\n  y [D039b88]", "x\n    nested\n  y"),
    ("done: call `reset()` now", "call `reset()` now"),
    ("done: - [ ] deploy", "- [ ] deploy"),
    ("See key=https://x.com/a ok", "See https://x.com/a ok"),
    ("Also [key=https://y.com/b] and (corr=http://z.io)", "Also [https://y.com/b] and (http://z.io)"),
    ("Fix [corr=1] now", "Fix now"),
])
def test_rules(text, want):
    assert clean(text) == want


def test_urls_are_untouched():
    text = "Open https://example.com/data/x?key=1&corr=2 or http://h/tmp/cf-a"
    assert clean(text) == text


@pytest.mark.parametrize("text,want", [
    ("done: : hi", "hi"),
    ("[D039b88]: hi", "hi"),
    ("The owner asked and the captain agreed; the owner's call.", "You asked and you agreed; your call."),
    ("Ask the Owner. Owner-only and ownership stay.", "Ask you. Owner-only and ownership stay."),
    ("Tell the owner https://x.com/the-owner/captain now", "Tell you https://x.com/the-owner/captain now"),
    ("owner and captain stay, Captain Smith too, the owner of the repo, the captain Smith", "owner and captain stay, Captain Smith too, the owner of the repo, the captain Smith"),
    ("see the owner.json, `the owner`, github.com/the owner/x [D039b88]", "see the owner.json, `the owner`, github.com/the owner/x"),
    (": hi", "hi"),
    (":) ok", ":) ok"),
    (": [D039b88]", "[D039b88]"),
])
def test_leading_colon_and_reader_word(text, want):
    assert clean(text) == want


def test_leading_colon_is_dropped_on_every_line():
    assert clean("done: x\n: child run\n: idle sweep\n:) ok\n  : last") == "x\nchild run\nidle sweep\n:) ok\nlast"
    assert clean("hello\n: child") == "hello\nchild"


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
