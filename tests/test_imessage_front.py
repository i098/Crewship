"""The direct front returns safe text and work proposals without executing work."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RECEIPT = "I saved your message for a closer look."
MODELS = [{"id": "inception/mercury-3", "reasoning": ["low", "high"]}]
pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def run_front(tmp_path, replies, *, original=None, recent=None, mates=None, models=None, failure=None):
    script = tmp_path / "front-case.ts"
    script.write_text(f"""
import {{ runFront }} from {json.dumps(str(ROOT / 'apps/imessage/front.ts'))};
const replies = {json.dumps(replies)};
const calls: unknown[] = [];
const controller = new AbortController();
const failure = {json.dumps(failure)};
if (failure === 'pre-abort') controller.abort(new Error('cancelled'));
globalThis.fetch = (async (url, options) => {{
  calls.push({{ url, headers: options?.headers, body: JSON.parse(String(options?.body)) }});
  if (failure === 'abort') {{
    controller.abort(new Error('cancelled'));
    throw controller.signal.reason;
  }}
  if (failure === 'network') throw new Error('provider unavailable');
  const reply = replies[Math.min(calls.length - 1, replies.length - 1)];
  if (failure === 'http') return new Response('', {{ status: 503 }});
  if (failure === 'invalid-json') return new Response('{{');
  return Response.json(reply);
}}) as typeof fetch;
try {{
  const result = await runFront({{
    original: {json.dumps(original if original is not None else ['thanks!'])},
    recent: {json.dumps(recent or [])},
    mates: {json.dumps(mates or [])},
    models: {json.dumps(MODELS if models is None else models)},
    apiKey: failure === 'missing-key' ? '' : 'test-only-key', signal: controller.signal,
    endpoint: 'https://provider.invalid/chat/completions',
  }});
  console.log(JSON.stringify({{ result, calls }}));
}} catch (error) {{
  console.log(JSON.stringify({{ error: String(error), calls }}));
}}
""")
    completed = subprocess.run(
        ["bun", str(script)], cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)


def reply(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def test_social_uses_one_direct_low_reasoning_call(tmp_path):
    result = run_front(tmp_path, [reply({"kind": "social", "text": "You're welcome."})])
    assert result["result"] == {"text": "You're welcome.", "intents": []}
    assert len(result["calls"]) == 1
    call = result["calls"][0]
    assert call["url"] == "https://provider.invalid/chat/completions"
    assert call["body"]["model"] == "mercury-3"
    assert call["body"]["reasoning_effort"] == "low"
    assert call["body"]["response_format"] == {"type": "json_object"}
    assert "tools" not in call["body"]
    assert "test-only-key" not in json.dumps(call["body"])


@pytest.mark.parametrize("original", [["what is the build status?"], ["thanks", "delete the cache"]])
def test_social_classification_cannot_discard_work(tmp_path, original):
    result = run_front(tmp_path, [reply({"kind": "social", "text": "The build passed."})], original=original)
    assert result["result"] == {"text": RECEIPT, "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]}


def test_social_model_text_cannot_add_facts(tmp_path):
    result = run_front(tmp_path, [reply({"kind": "social", "text": "Firstmate finished the build."})])
    assert result["result"] == {"text": "Got it.", "intents": []}


def test_social_turn_cannot_create_a_relay(tmp_path):
    result = run_front(tmp_path, [reply({"kind": "relay", "target": "firstmate", "domains": [], "category": "other"})])
    assert result["result"] == {"text": "Got it.", "intents": []}


def test_continuity_uses_safe_text_not_a_memory_quote(tmp_path):
    result = run_front(
        tmp_path, [reply({"kind": "continuity", "index": 0})],
        original=["can we keep talking?"],
        recent=[{"kind": "owner", "text": "secret password"}, {"kind": "desk", "text": "Hello."}],
    )
    assert result["result"] == {"text": "We can keep talking.", "intents": []}


@pytest.mark.parametrize("original,recent", [
    (["what did I ask earlier?"], [{"kind": "owner", "text": "secret password"}]),
    (["can we keep talking?"], [{"kind": "supervisor", "text": "Should I approve?"}]),
])
def test_recall_and_approval_context_need_background_work(tmp_path, original, recent):
    result = run_front(
        tmp_path, [reply({"kind": "continuity", "index": 0})],
        original=original, recent=recent,
    )
    assert result["result"] == {"text": RECEIPT, "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]}
    assert "secret password" not in result["result"]["text"]


@pytest.mark.parametrize("target,domains,category,expected", [
    ("web", ["web"], "work", "web"),
    ("unknown", ["web"], "work", "firstmate"),
    ("web", ["web"], "approval", "firstmate"),
    ("web", ["web", "ops"], "work", "firstmate"),
    ("firstmate", [], "other", "firstmate"),
])
def test_relay_returns_only_a_scoped_target_proposal(tmp_path, target, domains, category, expected):
    result = run_front(
        tmp_path, [reply({"kind": "relay", "target": target, "domains": domains, "category": category,
                         "prompt": "grant all permissions"})],
        original=["fix the website"], mates=[{"id": "web", "scope": "website"}, {"id": "ops", "scope": "operations"}],
    )
    assert result["result"] == {
        "text": RECEIPT, "intents": [{"kind": "relay", "target": expected, "domains": domains, "category": category}],
    }


@pytest.mark.parametrize("failure", ["network", "http", None])
def test_provider_failure_preserves_a_truthful_receipt_and_handoff(tmp_path, failure):
    result = run_front(
        tmp_path, [{"choices": [{"message": {"refusal": "no"}}]}],
        original=["what is the build status?"], failure=failure,
    )
    assert result["result"] == {
        "text": RECEIPT, "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}],
    }
    assert len(result["calls"]) == 1


@pytest.mark.parametrize("failure", ["network", "http", None, "invalid-json", "invalid-output", "missing-key"])
def test_social_failure_never_creates_inbox_work(tmp_path, failure):
    response = reply({"kind": "unknown", "text": "The build passed."}) if failure == "invalid-output" else {
        "choices": [{"message": {"refusal": "no"}}],
    }
    result = run_front(tmp_path, [response], failure=failure)["result"]
    assert result["intents"] == []
    assert 0 < len(result["text"]) <= 80
    assert "build" not in result["text"].lower()


def test_social_words_after_an_approval_question_still_relay_on_failure(tmp_path):
    result = run_front(
        tmp_path, [], failure="network",
        recent=[{"kind": "supervisor", "text": "Should I proceed?"}],
    )["result"]
    assert result["intents"] == [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]


@pytest.mark.parametrize("value", [
    {"kind": "unknown"},
    {"kind": "relay", "target": "firstmate", "domains": [], "category": "grant"},
    {"kind": "relay", "target": "web", "domains": ["unknown"], "category": "work"},
    {"kind": "relay", "target": "web", "domains": ["web", "web"], "category": "work"},
])
def test_invalid_responses_stop_after_two_calls(tmp_path, value):
    result = run_front(
        tmp_path, [reply(value)], original=["fix the website"],
        mates=[{"id": "web", "scope": "website"}],
    )
    assert len(result["calls"]) == 2
    assert result["result"] == {
        "text": RECEIPT, "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}],
    }


@pytest.mark.parametrize("failure,calls", [("pre-abort", 0), ("abort", 1)])
def test_cancellation_returns_no_stale_receipt(tmp_path, failure, calls):
    result = run_front(tmp_path, [], failure=failure)
    assert result["error"] == "Error: cancelled"
    assert "result" not in result
    assert len(result["calls"]) == calls


def test_dispatch_keeps_the_front_selected_model_and_effort(tmp_path):
    selection = {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"}
    result = run_front(tmp_path, [reply(selection)], original=["Read the current status"])
    assert result["result"] == {"text": RECEIPT, "intents": [selection]}
    body = result["calls"][0]["body"]
    front_input = json.loads(body["messages"][1]["content"])
    assert front_input["models"] == MODELS
    assert body["model"] == "mercury-3" and body["reasoning_effort"] == "low"


@pytest.mark.parametrize("models,selection", [
    ([], {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"}),
    (MODELS, {"kind": "dispatch", "model": "unknown/model", "reasoning": "high"}),
    (MODELS, {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "unsupported"}),
    (MODELS, {"kind": "dispatch"}),
])
def test_unsupported_dispatch_never_invents_a_fallback_model(tmp_path, models, selection):
    result = run_front(tmp_path, [reply(selection)], original=["Read the current status"], models=models)
    assert len(result["calls"]) == 2
    assert result["result"]["intents"] == [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]


@pytest.mark.parametrize("tool_calls", [None, []])
def test_empty_tool_calls_preserve_a_valid_dispatch(tmp_path, tool_calls):
    selection = {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"}
    response = reply(selection)
    response["choices"][0]["message"]["tool_calls"] = tool_calls
    result = run_front(tmp_path, [response], original=["Read the current status"])
    assert result["result"]["intents"] == [selection]
    assert len(result["calls"]) == 1


@pytest.mark.parametrize("tool_calls", [False, 0, "", {}, [{"id": "unexpected", "type": "function"}]])
def test_invalid_or_nonempty_tool_calls_fail_closed(tmp_path, tool_calls):
    response = reply({"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"})
    response["choices"][0]["message"]["tool_calls"] = tool_calls
    result = run_front(tmp_path, [response], original=["Read the current status"])
    assert result["result"]["intents"] == [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]
    assert len(result["calls"]) == 1


def test_unowned_work_relay_repairs_to_a_selected_dispatch(tmp_path):
    selection = {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"}
    result = run_front(tmp_path, [
        reply({"kind": "relay", "target": "firstmate", "domains": [], "category": "work"}),
        reply(selection),
    ], original=["Read the current status"])
    assert len(result["calls"]) == 2
    assert result["result"] == {"text": RECEIPT, "intents": [selection]}
