"""The V2 front desk classifier against a fake model endpoint: routing, masking and fallbacks."""

import json
import shutil

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

FRONT = json.dumps(str(ROOT / "apps/imessage/front.ts"))
MATES = [{"id": "docs", "scope": "documentation"}, {"id": "api", "scope": "the HTTP API"}]
MODELS = [{"id": "openai/gpt-6-luna", "reasoning": ["low", "high"]}]


def front(original, replies, recent=None, api_key="k", status=200):
    """Run runFront against a server that returns `replies` in order; report the result and what the model saw."""
    return bun(f"""
import {{ runFront }} from {FRONT};
const replies = {json.dumps(replies)};
const seen = [];
const server = Bun.serve({{ port: 0, async fetch(req) {{
  seen.push({{ auth: req.headers.get("authorization"), body: await req.text() }});
  const reply = replies.shift();
  if ({status} !== 200) return new Response("no", {{ status: {status} }});
  return Response.json({{ choices: [{{ message: {{ content: typeof reply === "string" ? reply : JSON.stringify(reply) }} }}] }});
}} }});
const result = await runFront({{
  original: {json.dumps(original)}, recent: {json.dumps(recent or [])}, mates: {json.dumps(MATES)}, models: {json.dumps(MODELS)},
  apiKey: {json.dumps(api_key)}, signal: new AbortController().signal,
  redact: (payload) => payload.replaceAll("hunter2", "[REDACTED]"),
  endpoint: `http://127.0.0.1:${{server.port}}/v1`,
}});
server.stop(true);
console.log(JSON.stringify({{ result, calls: seen.length, seen }}));
""")


RELAY_FIRSTMATE = {"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}


def test_dispatch_choice_resolves_numeric_ids_and_never_writes_text():
    out = front(
        ["what is the build status?"],
        [{"kind": "dispatch", "model": 1, "reasoning": 2, "text": "I'll check the build status."}],
    )
    assert out["result"] == {
        "intents": [{"kind": "dispatch", "model": "openai/gpt-6-luna", "reasoning": "high"}],
    }


def test_work_for_one_listed_mate_relays_to_that_mate():
    out = front(
        ["update the docs"], [{"kind": "relay", "target": 1, "domains": [1], "category": "work"}]
    )
    assert out["result"]["intents"] == [
        {"kind": "relay", "target": "docs", "domains": ["docs"], "category": "work"}
    ]


def test_unknown_ownership_goes_to_firstmate():
    out = front(
        ["do something odd"],
        [{"kind": "relay", "target": 0, "domains": [], "category": "ambiguous"}],
    )
    assert out["result"]["intents"][0]["target"] == "firstmate"


def test_social_turn_gets_no_intent_and_no_text():
    out = front(["thanks"], [{"kind": "social", "text": "Anytime."}])
    assert out["result"] == {"intents": []}


def test_invalid_answer_is_retried_once_then_falls_back_to_firstmate():
    out = front(["do the thing"], ["not json", "still not json"])
    assert out["calls"] == 2
    assert out["result"] == {"intents": [RELAY_FIRSTMATE]}


def test_second_answer_can_recover():
    out = front(
        ["what is the build status?"], ["nope", {"kind": "dispatch", "model": 1, "reasoning": 1}]
    )
    assert out["calls"] == 2
    assert out["result"]["intents"][0]["kind"] == "dispatch"


@pytest.mark.parametrize("kwargs", [{"status": 500}, {"api_key": ""}])
def test_failed_or_unauthenticated_call_falls_back_to_firstmate(kwargs):
    out = front(["what is the build status?"], [{"kind": "social"}], **kwargs)
    assert out["result"] == {"intents": [RELAY_FIRSTMATE]}
    if kwargs.get("api_key") == "":
        assert out["calls"] == 0


def test_secrets_are_masked_before_the_request_leaves():
    out = front(
        ["the password is hunter2, check the build"],
        [{"kind": "dispatch", "model": 1, "reasoning": 1}],
    )
    assert "hunter2" not in out["seen"][0]["body"]
    assert "[REDACTED]" in out["seen"][0]["body"]
    assert out["seen"][0]["auth"] == "Bearer k"


def test_model_names_that_are_not_advertised_ids_are_refused():
    out = front(
        ["status?"], [{"kind": "dispatch", "model": "openai/gpt-6-luna", "reasoning": "high"}] * 2
    )
    assert out["result"]["intents"] == [RELAY_FIRSTMATE]
