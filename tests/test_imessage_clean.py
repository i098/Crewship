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
    ("Ship it key=abc corr=xyz at=123", "Ship it"),
    ("working: building\ndone: built", "building\nbuilt"),
    ("[D0123ab] needs-decision: pick one", "pick one"),
    ("Blocked: x\nFailed: y\npaused: z\nresolved: w", "x\ny\nz\nw"),
    ("Asked crewship-mate-c1 and cf-text-filter and sm-fleet and bob-mate-7 today", "Asked and and and today"),
    ("See /home/a/b.txt and /sdb-disk/x /tmp/y state/z.log data/q", "See and"),
    ("Tests failed (decision stuck after 3 attempts). Next.", "Tests failed. Next."),
    ("Not a status: working: ok mid-line done: x", "Not a status: working: ok mid-line done: x"),
    ("[D039b88] one\n\n\n\ntwo   three ( ) [ ]", "one\n\ntwo three"),
])
def test_rules(text, want):
    assert clean(text) == want


def test_urls_and_code_fences_are_untouched():
    text = "Open https://example.com/data/x?key=1&corr=2 or http://h/tmp/cf-a\n```\n[D039b88] state/x working: key=1\n```"
    assert clean(text) == text


def test_text_without_slop_stays_byte_exact():
    assert clean("  a  b \n\n\n\nc ") == "  a  b \n\n\n\nc "


def test_empty_result_falls_back_to_original():
    assert clean("[D039b88]") == "[D039b88]"


def cli(*args, stdin=None, env=None):
    return subprocess.run([str(CLI), *args], input=stdin, capture_output=True, text=True,
                          env={**os.environ, "FM_IMESSAGE_DRY_RUN": "1", **(env or {})})


def test_cli_cleans_arguments_and_stdin_but_raw_skips():
    assert cli("done: [D039b88] Shipped /tmp/x").stdout == "Shipped\n"
    assert cli(stdin="working: hi cf-abc").stdout == "hi\n"
    assert cli("--raw", "done: [D039b88] Shipped").stdout == "done: [D039b88] Shipped\n"


def test_cli_without_bun_warns_and_sends_unchanged(tmp_path):
    out = cli("done: x", env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "FM_IMESSAGE_CLEAN": ""})
    if shutil.which("bun", path="/usr/bin:/bin"):
        pytest.skip("bun on the minimal PATH")
    assert out.stdout == "done: x\n" and "unfiltered" in out.stderr
