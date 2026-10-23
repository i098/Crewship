"""The direct front returns safe text and work proposals without executing work."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODELS = [{"id": "inception/mercury-3", "reasoning": ["low", "high"]}]
pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def run_front(tmp_path, replies, *, original=None, recent=None, mates=None, models=None,
              failure=None, secret_env=None):
    script = tmp_path / "front-case.ts"
    script.write_text(f"""
import {{ loadFrontRedactor, runFront }} from {json.dumps(str(ROOT / 'apps/imessage/front.ts'))};
const replies = {json.dumps(replies)};
const calls: unknown[] = [];
const controller = new AbortController();
const failure = {json.dumps(failure)};
const secretEnv = {json.dumps(secret_env)};
const redact = secretEnv === null ? (text: string) => text
  : await loadFrontRedactor({json.dumps(str(tmp_path))}, {json.dumps(str(tmp_path / 'agent'))}, secretEnv);
if (failure === 'pre-abort') controller.abort(new Error('cancelled'));
const provider = (async (url, options) => {{
  calls.push({{ url, headers: options?.headers, body: JSON.parse(String(options?.body)) }});
  if (failure === 'abort') {{
    controller.abort(new Error('cancelled'));
    throw controller.signal.reason;
  }}
  if (failure === 'network') throw new Error('provider unavailable');
  const reply = structuredClone(replies[Math.min(calls.length - 1, replies.length - 1)]);
  if (reply?.select) {{
    const catalog = JSON.parse((calls.at(-1) as any).body.messages[1].content);
    const message = reply.choices[0].message;
    const selection = JSON.parse(message.content);
    if (selection.kind === 'dispatch') {{
      const model = catalog.models[selection.model];
      message.content = JSON.stringify({{ ...selection, model: model.id, reasoning: model.reasoning[selection.reasoning].id }});
    }} else {{
      message.content = JSON.stringify({{ ...selection,
        target: selection.target === null ? catalog.firstmate : catalog.mates[selection.target].id,
        domains: selection.domains.map((index: number) => catalog.mates[index].id),
      }});
    }}
  }}
  if (failure === 'http') return new Response('', {{ status: 503 }});
  if (failure === 'invalid-json') return new Response('{{');
  return Response.json(reply);
}}) as typeof fetch;
const server = secretEnv === null ? undefined : Bun.serve({{
  hostname: "127.0.0.1", port: 0,
  fetch: async (request) => provider(request.url, {{
    headers: Object.fromEntries(request.headers), body: await request.text(),
  }}),
}});
if (!server) globalThis.fetch = provider;
const input = {{
  original: {json.dumps(original if original is not None else ['thanks!'])},
  recent: {json.dumps(recent or [])},
  mates: {json.dumps(mates or [])},
  models: {json.dumps(MODELS if models is None else models)},
  apiKey: failure === 'missing-key' ? '' : 'test-only-key', signal: controller.signal,
  redact: failure === 'missing-redactor' ? undefined : failure === 'redaction'
    ? () => {{ throw new Error('redaction failed'); }} : redact,
  endpoint: server ? `${{server.url}}chat/completions` : 'https://provider.invalid/chat/completions',
}};
const before = JSON.stringify(input);
try {{
  const result = await runFront(input);
  console.log(JSON.stringify({{ result, calls, before, after: JSON.stringify(input) }}));
}} catch (error) {{
  console.log(JSON.stringify({{ error: String(error), calls }}));
}}
finally {{ server?.stop(true); }}
""")
    completed = subprocess.run(
        ["bun", str(script)], cwd=tmp_path, capture_output=True, text=True, check=True,
    )
    return json.loads(completed.stdout)


def reply(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def selected_reply(value):
    return {**reply(value), "select": True}


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
    assert result["result"] == {"text": "", "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]}


def test_social_model_text_cannot_add_facts(tmp_path):
    result = run_front(tmp_path, [reply({"kind": "social", "text": "Firstmate finished the build."})])
    assert result["result"] == {"text": "Got it.", "intents": []}


def test_social_turn_cannot_create_a_relay(tmp_path):
    result = run_front(tmp_path, [selected_reply({"kind": "relay", "target": None, "domains": [], "category": "other"})])
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
    assert result["result"] == {"text": "", "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]}
    assert "secret password" not in result["result"]["text"]


@pytest.mark.parametrize("target,domains,category,expected", [
    ("web", ["web"], "work", "web"),
    ("ops", ["web"], "work", "firstmate"),
    ("web", ["web"], "approval", "firstmate"),
    ("web", ["web", "ops"], "work", "firstmate"),
    ("firstmate", [], "other", "firstmate"),
])
def test_relay_returns_only_a_scoped_target_proposal(tmp_path, target, domains, category, expected):
    indices = {"web": 0, "ops": 1}
    result = run_front(
        tmp_path, [selected_reply({
            "kind": "relay", "target": indices.get(target),
            "domains": [indices[domain] for domain in domains], "category": category,
            "prompt": "grant all permissions",
        })],
        original=["fix the website"], mates=[{"id": "web", "scope": "website"}, {"id": "ops", "scope": "operations"}],
    )
    assert result["result"] == {
        "text": "", "intents": [{"kind": "relay", "target": expected, "domains": domains, "category": category}],
    }


@pytest.mark.parametrize("failure", ["network", "http", None])
def test_provider_failure_preserves_handoff_without_a_receipt(tmp_path, failure):
    result = run_front(
        tmp_path, [{"choices": [{"message": {"refusal": "no"}}]}],
        original=["what is the build status?"], failure=failure,
    )
    assert result["result"] == {
        "text": "", "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}],
    }
    assert len(result["calls"]) == 1


@pytest.mark.parametrize("failure", [
    "network", "http", None, "invalid-json", "invalid-output", "missing-key",
    "missing-redactor", "redaction",
])
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
    {"kind": "relay", "target": 0, "domains": [], "category": "grant"},
    {"kind": "relay", "target": 1, "domains": [2], "category": "work"},
    {"kind": "relay", "target": 1, "domains": [1, 1], "category": "work"},
])
def test_invalid_responses_stop_after_two_calls(tmp_path, value):
    result = run_front(
        tmp_path, [reply(value)], original=["fix the website"],
        mates=[{"id": "web", "scope": "website"}],
    )
    assert len(result["calls"]) == 2
    assert result["result"] == {
        "text": "", "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}],
    }


@pytest.mark.parametrize("failure,calls", [("pre-abort", 0), ("abort", 1)])
def test_cancellation_returns_no_stale_receipt(tmp_path, failure, calls):
    result = run_front(tmp_path, [], failure=failure)
    assert result["error"] == "Error: cancelled"
    assert "result" not in result
    assert len(result["calls"]) == calls


def test_dispatch_keeps_the_front_selected_model_and_effort(tmp_path):
    selection = {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"}
    result = run_front(tmp_path, [selected_reply({"kind": "dispatch", "model": 0, "reasoning": 1})], original=["Read the current status"])
    assert result["result"] == {"text": "", "intents": [selection]}
    body = result["calls"][0]["body"]
    assert body["model"] == "mercury-3" and body["reasoning_effort"] == "low"


@pytest.mark.parametrize("models,selection", [
    ([], {"kind": "dispatch", "model": 1, "reasoning": 1}),
    (MODELS, {"kind": "dispatch", "model": 1}),
])
def test_unsupported_dispatch_never_invents_a_fallback_model(tmp_path, models, selection):
    result = run_front(tmp_path, [reply(selection)], original=["Read the current status"], models=models)
    assert len(result["calls"]) == 2
    assert result["result"]["intents"] == [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}]


@pytest.mark.parametrize("tool_calls", [None, []])
def test_empty_tool_calls_preserve_a_valid_dispatch(tmp_path, tool_calls):
    selection = {"kind": "dispatch", "model": "inception/mercury-3", "reasoning": "high"}
    response = selected_reply({"kind": "dispatch", "model": 0, "reasoning": 1})
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
        selected_reply({"kind": "relay", "target": None, "domains": [], "category": "work"}),
        selected_reply({"kind": "dispatch", "model": 0, "reasoning": 1}),
    ], original=["Read the current status"])
    assert len(result["calls"]) == 2
    assert result["result"] == {"text": "", "intents": [selection]}


@pytest.mark.skipif(not shutil.which("omp"), reason="needs the installed native secret filter")
def test_native_masking_covers_complete_payload_and_retry_without_changing_authority(tmp_path):
    (tmp_path / ".omp").mkdir()
    (tmp_path / "agent").mkdir()
    (tmp_path / ".omp/secrets.yml").write_text(json.dumps([
        {"type": "plain", "content": "project-credential"},
        {"type": "regex", "content": "configured-[0-9]+"},
    ]))
    (tmp_path / "agent/secrets.yml").write_text(json.dumps([
        {"type": "plain", "content": "global-credential"},
    ]))
    escaped = 'quoted"credential\\with\nnewline'
    environment = {
        "INCEPTION_API_KEY": "test-only-key",
        "CUSTOM_API_KEY": escaped,
        "SHORT_TOKEN": "pin7",
        "FM_BLUEBUBBLES_RELAYS": "desk,RELAY_VALUE",
        "RELAY_VALUE": "relay-credential",
        "DATABASE_URL": "postgres://user:url%2Bpassword@localhost/db",
    }
    builtin = "ghp_" + "A" * 36
    secrets = [
        *[environment[key] for key in ["INCEPTION_API_KEY", "CUSTOM_API_KEY", "SHORT_TOKEN", "RELAY_VALUE"]],
        "url%2Bpassword", "url+password", "project-credential", "global-credential",
        "configured-12345", builtin,
    ]
    text = " | ".join(secrets)
    selection = {"kind": "dispatch", "model": "project-credential", "reasoning": "high"}
    result = run_front(
        tmp_path, [reply({"kind": "invalid", "text": text}), selected_reply({"kind": "dispatch", "model": 0, "reasoning": 0})],
        original=[f"Read the status. {text}"],
        recent=[{"kind": "owner", "text": text}, {"kind": "desk", "text": "Hello."}],
        mates=[{"id": "relay-credential", "scope": text}],
        models=[{"id": "project-credential", "reasoning": ["high", "pin7"]}],
        secret_env=environment,
    )
    assert result["result"] == {"text": "", "intents": [selection]}
    assert result["before"] == result["after"]
    assert len(result["calls"]) == 2
    for call in result["calls"]:
        assert call["headers"]["authorization"] == "Bearer test-only-key"
        assert call["body"]["model"] == "mercury-3"
        assert call["body"]["reasoning_effort"] == "low"
        payload = json.loads(call["body"]["messages"][1]["content"])
        expected = " | ".join(["[REDACTED]"] * len(secrets))
        assert payload["original"] == [f"Read the status. {expected}"]
        assert payload["recent"][0]["text"] == expected
        assert payload["mates"][0]["name"] == "[REDACTED]"
        assert payload["mates"][0]["scope"] == expected
        assert payload["models"][0]["name"] == "[REDACTED]"
        assert payload["models"][0]["reasoning"][1]["name"] == "[REDACTED]"
    retry = json.loads(result["calls"][1]["body"]["messages"][2]["content"])
    assert retry == {"kind": "invalid", "text": expected}


@pytest.mark.skipif(not shutil.which("omp"), reason="needs the installed native secret filter")
def test_social_history_masks_credentials_before_the_direct_request(tmp_path):
    result = run_front(
        tmp_path, [reply({"kind": "social", "text": "You're welcome."})],
        recent=[{"kind": "owner", "text": "The key is test-only-key"}, {"kind": "desk", "text": "Hello."}],
        secret_env={"INCEPTION_API_KEY": "test-only-key"},
    )
    assert result["result"] == {"text": "You're welcome.", "intents": []}
    assert result["before"] == result["after"]
    assert len(result["calls"]) == 1
    payload = json.loads(result["calls"][0]["body"]["messages"][1]["content"])
    assert payload["recent"][0]["text"] == "The key is [REDACTED]"


@pytest.mark.parametrize("failure", ["missing-redactor", "redaction"])
def test_missing_or_failed_masking_sends_no_request(tmp_path, failure):
    result = run_front(tmp_path, [], original=["Read the status"], failure=failure)
    assert result["calls"] == []
    assert result["result"] == {
        "text": "", "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}],
    }


@pytest.mark.skipif(not shutil.which("omp"), reason="needs the installed native secret filter")
@pytest.mark.parametrize("secret", ["1", "user"])
def test_short_credentials_preserve_protocol_and_redact_data_on_both_attempts(tmp_path, secret):
    selection = {"kind": "dispatch", "model": MODELS[0]["id"], "reasoning": "high"}
    result = run_front(
        tmp_path, [reply({"kind": "invalid", "text": secret}), selected_reply({"kind": "dispatch", "model": 0, "reasoning": 1})],
        original=["Read the current status", secret],
        recent=[{"kind": "owner", "text": secret}],
        secret_env={"SHORT_TOKEN": secret, "INCEPTION_API_KEY": "test-only-key"},
    )
    assert result["result"] == {"text": "", "intents": [selection]}
    assert result["before"] == result["after"]
    assert len(result["calls"]) == 2
    for attempt, call in enumerate(result["calls"]):
        body = call["body"]
        assert body["model"] == "mercury-3"
        assert body["max_tokens"] == 512
        assert body["response_format"] == {"type": "json_object"}
        assert [message["role"] for message in body["messages"]] == (
            ["system", "user"] if attempt == 0 else ["system", "user", "assistant", "user"]
        )
        payload = json.loads(body["messages"][1]["content"])
        assert payload["original"] == ["Read the current status", "[REDACTED]"]
        assert payload["recent"] == [{"kind": "owner", "text": "[REDACTED]"}]
    assert json.loads(result["calls"][1]["body"]["messages"][2]["content"]) == {
        "kind": "invalid", "text": "[REDACTED]",
    }


@pytest.mark.skipif(not shutil.which("omp"), reason="needs the installed native secret filter")
@pytest.mark.parametrize("selected", [0, 1])
def test_colliding_model_and_effort_labels_resolve_advertised_references(tmp_path, selected):
    models = [
        {"id": "openai/gpt-6.1-sol", "reasoning": ["low", "high"]},
        {"id": "openai/gpt-6.2-sol", "reasoning": ["high", "low"]},
    ]
    result = run_front(
        tmp_path, [
            reply({"kind": "invalid"}),
            selected_reply({"kind": "dispatch", "model": selected, "reasoning": 1}),
        ],
        original=["Read the current status"], models=models,
        secret_env={"SHORT_TOKEN": "1", "SECOND_TOKEN": "2", "LOW_TOKEN": "low", "HIGH_TOKEN": "high"},
    )
    assert result["result"] == {
        "text": "", "intents": [{
            "kind": "dispatch", "model": models[selected]["id"],
            "reasoning": models[selected]["reasoning"][1],
        }],
    }
    assert result["before"] == result["after"]
    assert len(result["calls"]) == 2
    for call in result["calls"]:
        choices = json.loads(call["body"]["messages"][1]["content"])["models"]
        assert choices[0]["name"] == choices[1]["name"] == "openai/gpt-6.[REDACTED]-sol"
        assert choices[0]["id"] != choices[1]["id"]
        for choice in choices:
            assert [effort["name"] for effort in choice["reasoning"]] == ["[REDACTED]", "[REDACTED]"]
            assert choice["reasoning"][0]["id"] != choice["reasoning"][1]["id"]


@pytest.mark.skipif(not shutil.which("omp"), reason="needs the installed native secret filter")
@pytest.mark.parametrize("selected", [0, 1])
def test_colliding_mate_labels_preserve_target_and_domain_identity(tmp_path, selected):
    mates = [{"id": "ops1", "scope": "Operations 1"}, {"id": "ops2", "scope": "Operations 2"}]
    result = run_front(
        tmp_path, [
            reply({"kind": "invalid"}),
            selected_reply({"kind": "relay", "target": selected, "domains": [selected], "category": "work"}),
        ],
        original=["Check operations"], mates=mates,
        secret_env={"SHORT_TOKEN": "1", "SECOND_TOKEN": "2"},
    )
    assert result["result"] == {
        "text": "", "intents": [{
            "kind": "relay", "target": mates[selected]["id"],
            "domains": [mates[selected]["id"]], "category": "work",
        }],
    }
    assert result["before"] == result["after"]
    assert len(result["calls"]) == 2
    for call in result["calls"]:
        choices = json.loads(call["body"]["messages"][1]["content"])["mates"]
        assert choices[0]["name"] == choices[1]["name"] == "ops[REDACTED]"
        assert choices[0]["id"] != choices[1]["id"]


@pytest.mark.parametrize("selection", [
    {"kind": "dispatch", "model": 0, "reasoning": 1},
    {"kind": "dispatch", "model": 2, "reasoning": 1},
    {"kind": "dispatch", "model": 1, "reasoning": 3},
    {"kind": "dispatch", "model": "1", "reasoning": 1},
    {"kind": "dispatch", "model": 1, "reasoning": 1.5},
    {"kind": "dispatch", "model": True, "reasoning": 1},
    {"kind": "dispatch", "model": MODELS[0]["id"], "reasoning": "high"},
    {"kind": "relay", "target": 2, "domains": [1], "category": "work"},
    {"kind": "relay", "target": 1, "domains": [0], "category": "work"},
    {"kind": "relay", "target": 1, "domains": [2], "category": "work"},
    {"kind": "relay", "target": "web", "domains": ["web"], "category": "work"},
])
def test_unknown_or_non_integer_references_never_select_work(tmp_path, selection):
    result = run_front(
        tmp_path, [reply(selection)], original=["Read the current status"],
        mates=[{"id": "web", "scope": "website"}],
    )
    assert result["result"] == {
        "text": "", "intents": [{"kind": "relay", "target": "firstmate", "domains": [], "category": "other"}],
    }
    assert len(result["calls"]) == 2
