"""The browser rules fire on the phrases an agent writes when it is about to wait for the owner."""

import json
import re
from pathlib import Path

import pytest

RULES = Path(__file__).parents[1] / "blueprint/rules/public"


def front(name):
    block = (RULES / f"{name}.md").read_text().split("---\n")[1]
    fields = dict(line.split(": ", 1) for line in block.strip().splitlines())
    return [re.compile(c) for c in json.loads(fields["condition"])], json.loads(fields["scope"])


@pytest.mark.parametrize(
    "phrase",
    [
        "I am blocked by Cloudflare Turnstile on this page",
        "Cloudflare keeps the Turnstile check stuck",
        "his Mac is offline, so I cannot pull the cookie",
        "we need Mac awake to continue",
        "I will wait for his Mac before going on",
        "this needs his Mac",
        "Please open a login URL and sign in",
    ],
)
@pytest.mark.parametrize("name", ["fleet-browser-default-tier", "never-bounce-login-back-to-the-owner"])
def test_hand_back_phrases_match(name, phrase):
    conditions, scope = front(name)
    assert {"text", "thinking"} <= set(scope)
    if name == "never-bounce-login-back-to-the-owner" and "Turnstile" in phrase:
        pytest.skip("Turnstile triggers live in the ladder rule")
    assert any(c.search(phrase) for c in conditions)


def test_ordinary_browser_talk_does_not_match():
    conditions, _ = front("fleet-browser-default-tier")
    for text in ("The page loaded fine in obscura", "Turnstile is a widget name in the docs index"):
        assert not any(c.search(text) for c in conditions)


def test_ladder_rule_names_the_final_order():
    body = (RULES / "fleet-browser-default-tier.md").read_text()
    order = "obscura, obscura `--proxy`, chrome, chrome `--proxy`, voxl, voxl `--proxy`"
    assert order in body
    assert "vnc" not in body.split("---\n", 2)[2].lower().replace("vnc-chrome-profile", "")
