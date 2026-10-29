"""Exercise the native background runner without provider or transport calls."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FACT = "The build is paused."
REPLY = {"kind": "reply", "answer": FACT, "evidence": [{"source": "status", "quote": FACT}]}
pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def run_subagent(tmp_path, *, reply=REPLY, tools=None, voice=FACT, fail=False, voice_fail=False,
                 cancel_at=0, stale_at=0, stale=False, request="What is the build status?", write_path=None, selection=None, legacy=False,
                 masked_question=None, voice_event=False):
    script = tmp_path / "run.ts"
    settings = json.dumps({
        "reply": reply, "tools": tools or {}, "voice": voice, "fail": fail, "voiceFail": voice_fail,
        "cancelAt": cancel_at, "staleAt": stale_at, "stale": stale,
        "request": request, "writePath": write_path, "selection": selection or {}, "legacy": legacy,
        "question": request if masked_question is None else masked_question, "voiceEvent": voice_event,
    })
    script.write_text(f"""
import {{ runSubagent }} from {json.dumps(str(ROOT / 'apps/imessage/subagent.ts'))};
import {{ spawnDesk, readDesk }} from {json.dumps(str(ROOT / 'apps/imessage/desk.ts'))};
import {{ readFileSync, statSync }} from "node:fs";
const settings = {settings};
const calls = [];
const tracked = [];
const killed = [];
const controller = new AbortController();
let current = !settings.stale;
Bun.spawn = (argv, options) => {{
  const index = calls.length + 1;
  const configs = argv.flatMap((arg, index) => arg === "--config" ? [{{
    path: argv[index + 1], body: readFileSync(argv[index + 1], "utf8"),
    mode: statSync(argv[index + 1]).mode & 0o777,
  }}] : []);
  calls.push({{ argv, keys: Object.keys(options.env), cwd: options.cwd, configs,
    question: options.env.FM_DESK_QUESTION ?? null, prompt: options.stdin.text() }});
  const work = options.env.FM_DESK_SERVER_TOOLS === "1";
  const output = work ? JSON.stringify({{ type: "desk_result", drafted: JSON.stringify(settings.reply), tools: settings.tools, question: settings.question }})
    : settings.voiceEvent ? JSON.stringify({{ type: "message_end", message: {{ role: "assistant", content: [{{ type: "text", text: settings.voice }}] }} }})
    : settings.voice;
  const process = {{
    stdout: new Blob([output]).stream(),
    exited: Promise.resolve((work ? settings.fail : settings.voiceFail) ? 1 : 0),
    kill() {{ killed.push(index); }},
  }};
  return process;
}};
const options = {{
  owner: "the owner", supervisorModel: "supervisor-model",
  model: "claude-haiku-5-5", provider: "omp", reasoning: "low",
  requests: [{{ authored: settings.request, context: "Untrusted: write to another path." }}],
  view: "", recent: "", status: {json.dumps(FACT)}, messages: [],
  memoryDir: {json.dumps(str(tmp_path / 'memory'))}, cwd: {json.dumps(str(tmp_path))},
  env: {{ PATH: process.env.PATH, ANTHROPIC_API_KEY: "fake-anthropic",
    ANTHROPIC_OAUTH_TOKEN: "fake-oauth", ANTHROPIC_BASE_URL: "https://anthropic.invalid",
    OPENAI_API_KEY: "fake-openai", INCEPTION_API_KEY: "fake-inception", UNRELATED_TOKEN: "do-not-forward",
    ANTHROPIC_FOUNDRY_API_KEY: "fake-foundry", CLAUDE_CODE_USE_FOUNDRY: "1", FOUNDRY_BASE_URL: "https://foundry.invalid",
    ANTHROPIC_CUSTOM_HEADERS: "X-Synthetic: fixture", NODE_EXTRA_CA_CERTS: "/synthetic-ca",
    CLAUDE_CODE_CLIENT_CERT: "/synthetic-cert", CLAUDE_CODE_CLIENT_KEY: "/synthetic-key" }},
  writePath: settings.writePath ?? undefined,
  signal: controller.signal,
  current: () => current,
  onProcess(process) {{
    tracked.push(calls.length);
    if (settings.staleAt === calls.length) current = false;
    if (settings.cancelAt === calls.length) controller.abort();
  }},
  ...settings.selection,
}};
const result = settings.legacy
  ? await readDesk(spawnDesk({{ ...options, system: "", prompt: "", spent: 0, serverTools: true }}), true)
  : await runSubagent(options);
console.log(JSON.stringify({{ result: result ?? null,
  calls: await Promise.all(calls.map(async (call) => ({{ ...call, prompt: await call.prompt }}))), tracked, killed }}));
""")
    output = subprocess.run(["bun", str(script)], cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(output.stdout)


def basic_answer(tmp_path, reply, *, status=FACT, messages=None, tools=None):
    script = tmp_path / "legacy-answer.ts"
    script.write_text(f"""
import {{ basicAnswer }} from {json.dumps(str(ROOT / 'apps/imessage/desk.ts'))};
const answer = basicAnswer(
  true, JSON.stringify({json.dumps(reply)}), {json.dumps(status)}, {json.dumps(messages or [])},
  {{ desk: "worker", supervisor: "supervisor" }}, {json.dumps(tools or {})}
);
console.log(JSON.stringify(answer ?? null));
""")
    output = subprocess.run(["bun", str(script)], cwd=ROOT, text=True, capture_output=True, check=True)
    return json.loads(output.stdout)


@pytest.mark.parametrize("source", ["status", "tool", "chat"])
@pytest.mark.parametrize("blank", ["", " \t"])
def test_legacy_rejects_blank_evidence_even_beside_valid_facts(tmp_path, source, blank):
    fact = "Build paused."
    reply = {"kind": "reply", "answer": f"{fact}\n{blank}", "evidence": [
        {"source": "status", "quote": fact}, {"source": source, "quote": blank, "id": 7},
    ]}
    assert basic_answer(
        tmp_path, reply, status=f"{fact}\n{blank}",
        messages=[{"i": 7, "kind": "supervisor", "text": blank}],
        tools={"read-1": {"name": "read", "text": blank}},
    ) is None


def test_legacy_keeps_whitespace_in_nonblank_evidence(tmp_path):
    quotes = ["  Build paused.\t", "\tTool reports ready.  ", "  Remember this.\t"]
    reply = {"kind": "reply", "answer": "\n".join(quotes), "evidence": [
        {"source": "status", "quote": quotes[0]},
        {"source": "tool", "quote": quotes[1]},
        {"source": "chat", "quote": quotes[2], "id": 7},
    ]}
    assert basic_answer(
        tmp_path, reply, status=quotes[0],
        messages=[{"i": 7, "kind": "supervisor", "text": quotes[2]}],
        tools={"read-1": {"name": "read", "text": quotes[1]}},
    ) == {"answer": "\n".join(quotes), "identity": False}


def test_blank_reply_evidence_cannot_bypass_isolated_source_selection(tmp_path):
    reply = {"kind": "reply", "answer": f"{FACT}\n", "evidence": [
        {"source": "status", "quote": FACT}, {"source": "tool", "quote": ""},
    ]}
    tools = {"read-1": {"name": "read", "text": ""}}
    result = run_subagent(tmp_path, reply=reply, tools=tools)
    assert result["result"] == {"kind": "handoff", "reason": "unverified", "tools": tools}
    assert len(result["calls"]) == 1


def test_blank_source_lines_cannot_bypass_answer_length_limit(tmp_path):
    tools = {"read-1": {"name": "read", "text": " " * 2000 + "\nReady."}}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}, {"tool": 1, "line": 2}]}
    result = run_subagent(tmp_path, reply=reply, tools=tools)
    assert result["result"] == {"kind": "handoff", "reason": "unverified", "tools": tools}
    assert len(result["calls"]) == 1


def test_checked_answer_uses_direct_private_voice(tmp_path):
    result = run_subagent(tmp_path)
    assert result["result"] == {"kind": "answer", "bubbles": [FACT], "tools": {}}
    voice = result["calls"][-1]
    assert voice["argv"][1].endswith("/inception-desk.ts")
    assert voice["argv"][2:4] == ["mercury-3", "low"]
    assert "INCEPTION_API_KEY" in voice["keys"]
    assert "ANTHROPIC_API_KEY" not in voice["keys"]
    assert "UNRELATED_TOKEN" not in voice["keys"]


@pytest.mark.parametrize("reply", [
    {"kind": "tapback", "emoji": "👍"},
    {"kind": "reply", "answer": "Invented status.", "evidence": [{"source": "status", "quote": "Invented status."}]},
    {**REPLY, "target": 2},
    {"kind": "handled"},
])
def test_unverified_results_never_reach_voice(tmp_path, reply):
    result = run_subagent(tmp_path, reply=reply)
    assert result["result"]["kind"] == "handoff"
    assert result["result"]["reason"] == "unverified"
    assert len(result["calls"]) == 1


@pytest.mark.parametrize("field", ["cancel_at", "stale_at"])
@pytest.mark.parametrize("phase", [1, 2])
def test_obsolete_work_never_returns_a_reply_or_handoff(tmp_path, field, phase):
    result = run_subagent(tmp_path, **{field: phase})
    assert result["result"] is None
    assert result["tracked"] == list(range(1, phase + 1))
    if field == "cancel_at":
        assert phase in result["killed"]


def test_obsolete_request_does_not_spawn(tmp_path):
    result = run_subagent(tmp_path, stale=True)
    assert result["result"] is None
    assert result["calls"] == []


def test_failed_worker_returns_handoff_without_voice(tmp_path):
    result = run_subagent(tmp_path, fail=True)
    assert result["result"] == {"kind": "handoff", "reason": "failed", "tools": {}}
    assert len(result["calls"]) == 1


@pytest.mark.parametrize("voice", [
    "The build is ready.",
    "The build is paused and ready.",
    "The build is paused. The release is ready.",
    "The build passed with 50 jobs.",
    '{"answer":"The build is paused."}',
    '["The build is paused."]',
])
@pytest.mark.parametrize("tool_backed", [False, True])
def test_voice_cannot_change_checked_facts(tmp_path, voice, tool_backed):
    tools = {"read-1": {"name": "read", "text": FACT}} if tool_backed else {}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}]} if tool_backed else REPLY
    result = run_subagent(tmp_path, voice=voice, reply=reply, tools=tools)
    assert result["result"] == {"kind": "handoff", "reason": "unverified", "tools": tools}


@pytest.mark.parametrize("source,voice", [
    ("The build is waiting.", "The build is running."),
    ("The build is paused.", "The release is paused."),
    ("Alpha is ready. Beta is paused.", "Alpha is paused. Beta is ready."),
])
def test_voice_cannot_replace_or_reassign_source_words(tmp_path, source, voice):
    tools = {"read-1": {"name": "read", "text": source}}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}]}
    result = run_subagent(tmp_path, reply=reply, tools=tools, voice=voice)
    assert result["result"] == {"kind": "handoff", "reason": "unverified", "tools": tools}


def test_voice_cannot_invent_a_subject_for_a_status(tmp_path):
    tools = {"read-1": {"name": "read", "text": "Paused."}}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}]}
    result = run_subagent(tmp_path, reply=reply, tools=tools, voice="The setup is paused.")
    assert result["result"] == {"kind": "handoff", "reason": "unverified", "tools": tools}


def test_voice_can_change_case_and_bubble_breaks_without_changing_words(tmp_path):
    source = "The build is paused. The release is waiting."
    tools = {"read-1": {"name": "read", "text": source}}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}]}
    result = run_subagent(tmp_path, reply=reply, tools=tools,
                          voice="the build is paused.\n\nthe release is waiting.")
    assert result["result"] == {
        "kind": "answer", "bubbles": ["the build is paused.", "the release is waiting."], "tools": tools,
    }


@pytest.mark.parametrize("source,question,voice,bubbles", [
    (
        "runtime: herdr\nmemory: off",
        "Return the exact runtime and memory values, one per line.",
        "herdr\noff",
        ["herdr\noff"],
    ),
    (
        "runtime: herdr\nmemory: off",
        "What are the settings?",
        "The runtime is herdr.\n\nMemory is off.",
        ["The runtime is herdr.", "Memory is off."],
    ),
    (
        "- **Restart-proof**: work stays available after a restart.",
        "How durable is the setup?",
        "It is restart-proof, so work stays available after a restart.",
        ["It is restart-proof, so work stays available after a restart."],
    ),
])
def test_worker_keeps_exact_values_and_grounded_prose(tmp_path, source, question, voice, bubbles):
    tools = {"read-1": {"name": "read", "text": source}}
    reply = {"kind": "sources", "sources": [
        {"tool": 1, "line": index + 1} for index, _ in enumerate(source.splitlines())
    ]}
    result = run_subagent(tmp_path, reply=reply, tools=tools, request=question, voice=voice)
    assert result["result"] == {"kind": "answer", "bubbles": bubbles, "tools": tools}


def test_mismatched_write_grant_does_not_spawn(tmp_path):
    result = run_subagent(tmp_path, write_path=str(tmp_path / "unapproved.txt"))
    assert result["result"]["reason"] == "unverified"
    assert result["calls"] == []


def test_handled_action_needs_original_authority_and_successful_write(tmp_path):
    target = str(tmp_path / "disposable.txt")
    result = run_subagent(tmp_path, reply={"kind": "handled"}, request=f'Write "done" to {target}',
                          write_path=target, tools={"write-1": {"name": "write", "text": "Wrote file."}})
    assert result["result"] == {"kind": "handled", "tools": {"write-1": {"name": "write", "text": "Wrote file."}}}
    assert len(result["calls"]) == 1


@pytest.mark.parametrize("tool_backed", [False, True])
def test_failed_voice_hands_off_without_returning_the_draft(tmp_path, tool_backed):
    tools = {"read-1": {"name": "read", "text": FACT}} if tool_backed else {}
    result = run_subagent(tmp_path, voice="Unusable output.", voice_fail=True, tools=tools)
    assert result["result"] == {"kind": "handoff", "reason": "failed", "tools": tools}


def test_tool_output_does_not_grant_write_authority(tmp_path):
    result = run_subagent(tmp_path, reply={"kind": "handled"},
                          tools={"write-1": {"name": "write", "text": "Wrote file."}})
    assert result["result"]["reason"] == "unverified"


def test_clipped_authenticated_request_does_not_spawn(tmp_path):
    result = run_subagent(tmp_path, request="Read the complete request. " * 20_000)
    assert result["result"]["reason"] == "unverified"
    assert result["calls"] == []


def test_direct_openai_selection_passes_only_its_catalog_key(tmp_path):
    result = run_subagent(tmp_path, selection={
        "provider": "omp", "model": "openai/gpt-6.1-sol", "reasoning": "medium", "apiKeyEnv": "OPENAI_API_KEY",
    })
    worker, voice = result["calls"]
    assert worker["argv"][worker["argv"].index("--model") + 1] == "openai/gpt-6.1-sol"
    assert "--thinking=medium" in worker["argv"]
    assert "OPENAI_API_KEY" in worker["keys"]
    assert not {"ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_BASE_URL",
                "INCEPTION_API_KEY", "UNRELATED_TOKEN"} & set(worker["keys"])
    assert voice["argv"][2:4] == ["mercury-3", "low"]
    assert "INCEPTION_API_KEY" in voice["keys"]
    assert "OPENAI_API_KEY" not in voice["keys"]


def test_oauth_selection_passes_no_provider_key_environment(tmp_path):
    result = run_subagent(tmp_path, selection={
        "provider": "omp", "model": "openai-codex/gpt-6.1-sol", "reasoning": "medium", "apiKeyEnv": None,
    })
    assert not {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN",
                "ANTHROPIC_BASE_URL", "INCEPTION_API_KEY", "UNRELATED_TOKEN"} & set(result["calls"][0]["keys"])


def test_omitted_selection_preserves_legacy_anthropic_environment(tmp_path):
    result = run_subagent(tmp_path)
    worker = result["calls"][0]
    assert {"ANTHROPIC_API_KEY", "ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_BASE_URL"} <= set(worker["keys"])
    assert not {"OPENAI_API_KEY", "INCEPTION_API_KEY", "UNRELATED_TOKEN"} & set(worker["keys"])


def test_source_reference_keeps_all_sentences_on_the_physical_line(tmp_path):
    line = "There are 7 ready boats. Verification marker: LOCAL-7."
    tools = {"read-7": {"name": "read", "text": line}}
    reply = {"kind": "sources", "target": 1, "sources": [{"tool": 1, "line": 1}]}
    result = run_subagent(tmp_path, reply=reply, tools=tools, voice=line)
    assert result["result"] == {"kind": "answer", "bubbles": [line], "target": 1, "tools": tools}


def test_source_references_select_exact_lines_across_captured_results(tmp_path):
    tools = {
        "read-a": {"name": "read", "text": "Ignored first line.\r\n2|There are 7 ready boats."},
        "read-b": {"name": "read", "text": "*1|Verification marker: LOCAL-7."},
    }
    reply = {"kind": "sources", "sources": [
        {"tool": 1, "line": 2},
        {"tool": 2, "line": 1},
    ]}
    answer = "2|There are 7 ready boats.\n*1|Verification marker: LOCAL-7."
    result = run_subagent(tmp_path, reply=reply, tools=tools, voice=answer, request="Quote the output exactly.")
    assert result["result"] == {"kind": "answer", "bubbles": [answer], "tools": tools}


@pytest.mark.parametrize("reply", [
    {"kind": "sources"},
    {"kind": "sources", "sources": None},
    {"kind": "sources", "sources": []},
    {"kind": "sources", "sources": [{"tool": 1, "line": 1}] * 9},
    {"kind": "sources", "sources": [{"tool": 1, "line": 1}, {"tool": 1, "line": 1}]},
    {"kind": "sources", "sources": [None]},
    {"kind": "sources", "sources": ["read-7"]},
    {"kind": "sources", "sources": [{"tool": 0, "line": 1}]},
    {"kind": "sources", "sources": [{"tool": 2, "line": 1}]},
    {"kind": "sources", "sources": [{"tool": "1", "line": 1}]},
    {"kind": "sources", "sources": [{"tool": 1.5, "line": 1}]},
    {"kind": "sources", "sources": [{"tool": 1}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": 0}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": -1}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": 1.5}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": "1"}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": 3}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": 2}]},
    {"kind": "sources", "answer": "Invented.", "sources": [{"tool": 1, "line": 1}]},
    {"kind": "sources", "sources": [{"tool": 1, "line": 1, "quote": "Invented."}]},
    {"kind": "sources", "target": 0, "sources": [{"tool": 1, "line": 1}]},
    {"kind": "sources", "target": "1", "sources": [{"tool": 1, "line": 1}]},
    {"kind": "sources", "target": 2, "sources": [{"tool": 1, "line": 1}]},
])
def test_invalid_source_references_never_reach_voice(tmp_path, reply):
    tools = {"read-7": {"name": "read", "text": "There are 7 ready boats.\n  "}}
    result = run_subagent(tmp_path, reply=reply, tools=tools)
    assert result["result"]["kind"] == "handoff"
    assert result["result"]["reason"] == "unverified"
    assert len(result["calls"]) == 1


def test_source_references_still_use_the_shared_work_claim_guard(tmp_path):
    line = "I deployed the service."
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}]}
    result = run_subagent(tmp_path, reply=reply, tools={"read-7": {"name": "read", "text": line}})
    assert result["result"]["reason"] == "unverified"
    assert len(result["calls"]) == 1


def test_old_partial_sentence_quotes_remain_invalid(tmp_path):
    first, second = "There are 7 ready boats.", "Verification marker: LOCAL-7."
    reply = {"kind": "reply", "answer": f"{first}\n{second}", "evidence": [
        {"source": "tool", "quote": first},
        {"source": "tool", "quote": second},
    ]}
    result = run_subagent(tmp_path, reply=reply, tools={"read-7": {"name": "read", "text": f"{first} {second}"}})
    assert result["result"]["reason"] == "unverified"
    assert len(result["calls"]) == 1


def test_voice_reasoning_override_preserves_legacy_defaults(tmp_path):
    script = tmp_path / "voice-options.ts"
    script.write_text(f"""
import {{ spawnDesk }} from {json.dumps(str(ROOT / 'apps/imessage/desk.ts'))};
const calls = [];
Bun.spawn = (argv) => {{ calls.push(argv); return {{ exited: Promise.resolve(0) }}; }};
const options = {{ provider: "inception", model: "mercury-3", voice: true,
  system: "", prompt: "", spent: 0, memoryDir: "", cwd: {json.dumps(str(tmp_path))}, env: {{}} }};
spawnDesk(options);
spawnDesk({{ ...options, reasoning: "low" }});
spawnDesk({{ ...options, provider: "omp", reasoning: "high" }});
console.log(JSON.stringify(calls));
""")
    completed = subprocess.run(["bun", str(script)], cwd=ROOT, capture_output=True, text=True, check=True)
    calls = json.loads(completed.stdout)
    assert calls[0][2:4] == ["mercury-3", "instant"]
    assert calls[1][2:4] == ["mercury-3", "low"]
    assert "--thinking=off" in calls[2]


def test_selected_runtime_overlay_binds_model_and_cleans_private_directory(tmp_path):
    result = run_subagent(tmp_path)
    worker, voice = result["calls"]
    assert len(worker["configs"]) == 2
    assert worker["configs"][0]["path"].endswith("/desk-tools.yml")
    overlay = worker["configs"][-1]
    assert worker["argv"][-2:] == ["--config", overlay["path"]]
    assert json.loads(overlay["body"]) == {
        "retry": {"modelFallback": False},
        "contextPromotion": {"enabled": False},
        "providers": {"anthropic": {"serverSideFallback": False}},
    }
    assert overlay["mode"] == 0o600
    assert not Path(worker["cwd"]).exists()
    assert voice["configs"] == []


def test_legacy_runtime_keeps_only_existing_tool_overlay(tmp_path):
    result = run_subagent(tmp_path, legacy=True)
    worker, = result["calls"]
    assert len(worker["configs"]) == 1
    assert worker["configs"][0]["path"].endswith("/desk-tools.yml")
    assert not Path(worker["cwd"]).exists()


@pytest.mark.parametrize("credential", ["ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY"])
def test_selected_anthropic_keeps_its_context_and_one_credential(tmp_path, credential):
    result = run_subagent(tmp_path, selection={
        "provider": "omp", "model": "anthropic/claude-haiku-5-5", "reasoning": "low", "apiKeyEnv": credential,
    })
    worker, voice = result["calls"]
    credentials = {"ANTHROPIC_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "ANTHROPIC_FOUNDRY_API_KEY", "OPENAI_API_KEY", "INCEPTION_API_KEY"}
    context = {"ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_FOUNDRY", "FOUNDRY_BASE_URL"}
    excluded = {"ANTHROPIC_CUSTOM_HEADERS", "NODE_EXTRA_CA_CERTS", "CLAUDE_CODE_CLIENT_CERT", "CLAUDE_CODE_CLIENT_KEY"}
    assert credentials & set(worker["keys"]) == {credential}
    assert context <= set(worker["keys"])
    assert not context & set(voice["keys"])
    assert not excluded & set(worker["keys"])
    assert not excluded & set(voice["keys"])


def test_other_selected_provider_does_not_receive_anthropic_context(tmp_path):
    result = run_subagent(tmp_path, selection={
        "provider": "omp", "model": "openai/gpt-6.1-sol", "reasoning": "medium", "apiKeyEnv": "OPENAI_API_KEY",
    })
    context = {"ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_FOUNDRY", "FOUNDRY_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
               "NODE_EXTRA_CA_CERTS", "CLAUDE_CODE_CLIENT_CERT", "CLAUDE_CODE_CLIENT_KEY"}
    assert not context & set(result["calls"][0]["keys"])




@pytest.mark.parametrize("quote", [
    "  Alpha is ready.  \n\tBeta is paused.\t",
    '{"answer":"The build is paused."}',
    "Alpha is ready.\n\nBeta is paused.",
    "  Alpha is ready. \n \t\n\tBeta is paused.  ",
    " \t\nAlpha is ready.\n\t ",
])
@pytest.mark.parametrize("voice_event", [False, True])
def test_exact_source_keeps_whitespace_in_one_validated_bubble(tmp_path, voice_event, quote):
    question = "Quote the output exactly."
    tools = {"read-1": {"name": "read", "text": quote}}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": i + 1} for i, _ in enumerate(quote.splitlines())]}
    result = run_subagent(tmp_path, reply=reply, tools=tools, voice=quote, request=question, voice_event=voice_event)
    assert result["result"] == {"kind": "answer", "bubbles": [quote], "tools": tools}


def test_voice_uses_the_masked_question_from_native_result(tmp_path):
    original = "What does PRIVATE_CONTEXT mean?"
    masked = "What does [REDACTED] mean?"
    result = run_subagent(tmp_path, request=original, masked_question=masked)
    assert result["result"] == {"kind": "answer", "bubbles": [FACT], "tools": {}}
    native, voice = result["calls"]
    assert native["question"] == original
    assert json.loads(voice["prompt"])["question"] == masked
    assert original not in voice["prompt"]


def test_configured_identity_metadata_reaches_voice_validation(tmp_path):
    model = "claude-haiku-5-5"
    reply = {"kind": "reply", "answer": model, "evidence": [
        {"source": "identity", "subject": "desk", "quote": model},
    ]}
    result = run_subagent(tmp_path, reply=reply, request="What model are you?", voice=model)
    assert result["result"] == {"kind": "answer", "bubbles": [model], "tools": {}}


def test_subagent_answer_is_cleaned_of_tags_and_paths(tmp_path):
    quote = "[D039b88] The build is paused."
    tools = {"read-1": {"name": "read", "text": quote}}
    reply = {"kind": "sources", "sources": [{"tool": 1, "line": 1}]}
    result = run_subagent(tmp_path, reply=reply, tools=tools, voice=quote, request="Quote the output exactly.")
    assert result["result"] == {"kind": "answer", "bubbles": ["The build is paused."], "tools": tools}
