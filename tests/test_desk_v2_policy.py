"""Relay target choice and dispatch model selection, as pure functions."""

import json
import shutil

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

RELAY = json.dumps(str(ROOT / "apps/imessage/relay.ts"))
POLICY = json.dumps(str(ROOT / "apps/imessage/dispatch-policy.ts"))
MATES = [{"id": "3", "home": "/h/3", "scope": "docs"}, {"id": "4", "home": "/h/4", "scope": "api"}]
REQUEST = {"requestId": "r1", "text": "fix the docs build", "firstmate": False, "mateEligible": True}


def relay(requests, metadata):
    return bun(f"""
import {{ relayTarget }} from {RELAY};
console.log(JSON.stringify(relayTarget({json.dumps(requests)}, {json.dumps(metadata)}, {json.dumps(MATES)}) ?? null));
""")


WORK = {"category": "work", "target": "3", "domains": ["3"]}


def test_relay_picks_the_single_listed_mate_for_work():
    assert relay([REQUEST], WORK)["id"] == "3"


@pytest.mark.parametrize("metadata", [
    {**WORK, "category": "approval"},
    {**WORK, "domains": ["3", "4"]},
    {**WORK, "domains": ["4"]},
    {**WORK, "target": "9", "domains": ["9"]},
    {**WORK, "target": 3},
    None,
    [WORK],
])
def test_relay_refuses_anything_but_one_matching_work_domain(metadata):
    assert relay([REQUEST], metadata) is None


@pytest.mark.parametrize("change", [
    {"firstmate": True}, {"mateEligible": False}, {"mutationPath": "/x"}, {"text": "use the token for the deploy"},
])
def test_relay_keeps_protected_requests_with_firstmate(change):
    assert relay([{**REQUEST, **change}], WORK) is None


CATALOG = [
    {"provider": "anthropic", "id": "claude-opus-5-5", "reasoning": ["minimal", "low", "xhigh"], "apiKeyEnv": "ANTHROPIC_API_KEY"},
    {"provider": "openai", "id": "gpt-6-luna", "reasoning": ["low", "high"], "apiKeyEnv": None},
    {"provider": "anthropic", "id": "claude-fable-5-1", "reasoning": ["low"], "apiKeyEnv": None},
    {"provider": "inception", "id": "mercury-3", "reasoning": ["low", "high"], "apiKeyEnv": "INCEPTION_API_KEY"},
    {"provider": "other", "id": "thing", "reasoning": ["low"], "apiKeyEnv": None},
]
POLICY_JSON = {"rules": [{"use": {"harness": "omp", "model": "openai/gpt-6-luna", "effort": "high"}}]}


def models(purpose="general"):
    return bun(f"""
import {{ dispatchModels }} from {POLICY};
console.log(JSON.stringify(dispatchModels({json.dumps(CATALOG)}, {json.dumps(POLICY_JSON)}, {json.dumps(purpose)})));
""")


def test_general_dispatch_lists_only_permitted_models_with_policy_efforts():
    listed = {m["id"]: m["reasoning"] for m in models()}
    assert listed == {"anthropic/claude-opus-5-5": ["minimal", "low"], "openai/gpt-6-luna": ["high"]}


def test_simple_coding_adds_only_the_high_effort_mercury():
    listed = {m["id"]: m["reasoning"] for m in models("simple-coding")}
    assert listed["inception/mercury-3"] == ["high"]


def selection(value, purpose="general"):
    return bun(f"""
import {{ dispatchModels, dispatchSelection }} from {POLICY};
const list = dispatchModels({json.dumps(CATALOG)}, {json.dumps(POLICY_JSON)});
console.log(JSON.stringify(dispatchSelection({json.dumps(value)}, list, {json.dumps(purpose)}) ?? null));
""")


def test_selection_accepts_a_listed_model_and_effort():
    assert selection({"model": "openai/gpt-6-luna", "reasoning": "high"}) == {
        "provider": "omp", "model": "openai/gpt-6-luna", "reasoning": "high", "apiKeyEnv": None,
    }


@pytest.mark.parametrize("value", [
    {"model": "openai/gpt-6-luna", "reasoning": "low"},
    {"model": "anthropic/claude-fable-5-1", "reasoning": "low"},
    {"model": "inception/mercury-3", "reasoning": "high"},
    {"model": 1, "reasoning": "high"},
    "openai/gpt-6-luna",
])
def test_selection_refuses_unlisted_or_unpermitted_choices(value):
    assert selection(value) is None
