"""The browser rules fire, through omp's own TTSR matcher, on the phrases an agent writes before it waits for the owner."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(shutil.which("omp") is None, reason="omp binary not installed")

RULES = Path(__file__).parents[1] / "blueprint/rules/public"
LADDER = "fleet-browser-default-tier"
LOGIN = "never-bounce-login-back-to-the-owner"

SHARED = [
    "his Mac is offline, so I cannot pull the cookie",
    "we need Mac awake to continue",
    "I will wait for his Mac before going on",
    "this needs his Mac",
    "Please open a login URL and sign in",
]
TURNSTILE = [
    "I am blocked by Cloudflare Turnstile on this page",
    "Cloudflare keeps the Turnstile check stuck",
]
CASES = [(LADDER, p) for p in SHARED + TURNSTILE] + [(LOGIN, p) for p in SHARED]


def triggered(rule, source, phrase):
    out = subprocess.run(
        [
            "omp",
            "ttsr",
            "test",
            "-r",
            str(RULES / f"{rule}.md"),
            "--source",
            source,
            "--json",
            phrase,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(out)["triggered"]


@pytest.mark.parametrize("source", ["text", "thinking"])
@pytest.mark.parametrize(("rule", "phrase"), CASES)
def test_hand_back_phrase_triggers(rule, source, phrase):
    assert triggered(rule, source, phrase)


@pytest.mark.parametrize("source", ["text", "thinking"])
@pytest.mark.parametrize("rule", [LADDER, LOGIN])
def test_ordinary_browser_talk_does_not_trigger(rule, source):
    assert not triggered(rule, source, "The page loaded fine in obscura")
