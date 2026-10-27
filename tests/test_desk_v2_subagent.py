"""The V2 desk subagent against a fake omp and a fake Inception voice endpoint."""

import json
import shutil

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

SUBAGENT = json.dumps(str(ROOT / "apps/imessage/subagent.ts"))
DESK = json.dumps(str(ROOT / "apps/imessage/desk.ts"))


UNSET = object()


def subagent(
    requests,
    drafted,
    tools=None,
    write_path=UNSET,
    voice_reply=None,
    voice_status=200,
    aborted=False,
    stale=False,
):
    """Run runSubagent with a fake omp that drafts `drafted` over fake tool `tools`.

    The fake Inception endpoint echoes the draft unless `voice_reply` or a failing
    `voice_status` is given, and the script reports the result plus the voice call count.
    """
    if write_path is UNSET:
        write_path = "undefined"
    return bun(f"""
import {{ runSubagent }} from {SUBAGENT};
import {{ authorizedWritePath }} from {DESK};
import {{ mkdtempSync }} from "node:fs";
import {{ tmpdir }} from "node:os";
import {{ join }} from "node:path";

const drafted = {json.dumps(drafted)};
const tools = {json.dumps(tools or {})};
const voiceCalls = [];
const voice = Bun.serve({{ port: 0, async fetch(req) {{
  const body = JSON.parse(await req.text());
  voiceCalls.push(body);
  if ({voice_status} !== 200) return new Response("down", {{ status: {voice_status} }});
  const reply = {json.dumps(voice_reply)};
  return Response.json({{ choices: [{{ message: {{ content: reply ?? JSON.parse(body.messages[1].content).draft }} }}] }});
}} }});
const cwd = mkdtempSync(join(tmpdir(), "fm-desk-cwd-"));
const bin = mkdtempSync(join(tmpdir(), "fm-desk-bin-"));
await Bun.write(join(bin, "omp"), `#!/usr/bin/env python3
import json, os, sys
open("${{join(cwd, "capture.json")}}", "w").write(json.dumps({{"argv": sys.argv, "stdin": sys.stdin.read()}}))
print(json.dumps({{"type": "desk_result", "drafted": ${{JSON.stringify(drafted)}}, "tools": ${{JSON.stringify(tools)}}}}))
`);
Bun.spawnSync(["chmod", "+x", join(bin, "omp")]);
const requests = {json.dumps(requests)};
let stale = false;
const result = await runSubagent({{
  model: "anthropic/claude-haiku-5.5", provider: "omp", reasoning: "off",
  memoryDir: cwd, cwd, apiKeyEnv: undefined,
  env: {{ ...process.env, PATH: `${{bin}}:${{process.env.PATH}}`,
    INCEPTION_API_KEY: "k", FM_DESK_INCEPTION_URL: `http://127.0.0.1:${{voice.port}}/v1`,
    FM_IMESSAGE_TEST: "1", FM_IMESSAGE_TEST_VOICE_MS: "4000" }},
  owner: "the captain", supervisorModel: "claude-opus-5.5",
  requests,
  view: "nothing worth seeing", recent: "", status: "all systems nominal",
  messages: [{{ i: 1, kind: "owner", text: requests[0]?.authored ?? "" }}],
  writePath: {write_path},
  current: () => !stale,
  signal: {"AbortSignal.abort()" if aborted else "undefined"},
  onProcess: () => {{ stale = {"true" if stale else "false"}; }},
}});
voice.stop(true);
const capture = JSON.parse(await Bun.file(join(cwd, "capture.json")).text().catch(() => "null"));
console.log(JSON.stringify({{ result, voiceCalls: voiceCalls.length, voiceBodies: voiceCalls, capture }}));
""")


def test_tool_sources_answer_quotes_whole_lines_only():
    out = subagent(
        [{"authored": "how much disk is free?", "context": "df output"}],
        json.dumps({"kind": "sources", "target": 1, "sources": [{"tool": 1, "line": 1}]}),
        tools={"1": {"text": "Disk usage is 12 percent.\nsecond line"}},
    )
    assert out["result"]["kind"] == "answer"
    assert out["result"]["bubbles"] == ["Disk usage is 12 percent."]
    assert out["result"]["tools"] == {"1": {"text": "Disk usage is 12 percent.\nsecond line"}}
    assert out["voiceCalls"] == 1


def test_unparsable_draft_hands_off_without_a_voice_call():
    out = subagent([{"authored": "how much disk is free?", "context": "df output"}], "not json")
    assert out["result"] == {"kind": "handoff", "reason": "unverified", "tools": {}}
    assert out["voiceCalls"] == 0


def test_source_reference_outside_the_tools_hands_off():
    out = subagent(
        [{"authored": "how much disk is free?", "context": "df output"}],
        json.dumps({"kind": "sources", "target": 1, "sources": [{"tool": 9, "line": 1}]}),
        tools={"1": {"text": "one line"}},
    )
    assert out["result"] == {
        "kind": "handoff",
        "reason": "unverified",
        "tools": {"1": {"text": "one line"}},
    }
    assert out["voiceCalls"] == 0


def test_handled_requires_the_authorized_write_path():
    drafted = json.dumps({"kind": "handled"})
    out = subagent(
        [{"authored": "write the report to /tmp/report.txt", "context": ""}],
        drafted,
        write_path=json.dumps("/tmp/other.txt"),
    )
    assert out["result"]["kind"] == "handoff"
    assert out["voiceCalls"] == 0


def test_authorized_write_with_write_tool_is_handled():
    out = subagent(
        [{"authored": "write to /tmp/report.txt", "context": ""}],
        json.dumps({"kind": "handled"}),
        tools={"1": {"name": "write", "text": "ok"}},
        write_path="authorizedWritePath([requests[0].authored])",
    )
    assert out["result"] == {"kind": "handled", "tools": {"1": {"name": "write", "text": "ok"}}}
    assert out["voiceCalls"] == 0


def test_handled_without_a_write_tool_hands_off():
    out = subagent(
        [{"authored": "write to /tmp/report.txt", "context": ""}],
        json.dumps({"kind": "handled"}),
        write_path="authorizedWritePath([requests[0].authored])",
    )
    assert out["result"] == {"kind": "handoff", "reason": "unverified", "tools": {}}


SOURCES = json.dumps({"kind": "sources", "target": 1, "sources": [{"tool": 1, "line": 1}]})
DISK = {"1": {"text": "Disk usage is 12 percent."}}
ASK = [{"authored": "how much disk is free?", "context": ""}]


def test_voice_failure_hands_off_failed():
    out = subagent(ASK, SOURCES, tools=DISK, voice_status=500)
    assert out["result"] == {"kind": "handoff", "reason": "failed", "tools": DISK}
    assert out["voiceCalls"] == 1


def test_voice_reply_reordering_source_words_hands_off():
    out = subagent(ASK, SOURCES, tools=DISK, voice_reply="percent 12 is usage Disk.")
    assert out["result"] == {"kind": "handoff", "reason": "unverified", "tools": DISK}


def test_aborted_signal_returns_nothing_and_skips_voice():
    out = subagent(ASK, SOURCES, tools=DISK, aborted=True)
    assert "result" not in out
    assert out["voiceCalls"] == 0


def test_result_stale_after_omp_returns_nothing_and_skips_voice():
    out = subagent(ASK, SOURCES, tools=DISK, stale=True)
    assert "result" not in out
    assert out["voiceCalls"] == 0


def test_omp_gets_server_tools_and_requests_and_voice_is_tool_free():
    out = subagent(
        [{"authored": "how much disk is free?", "context": "df output"}], SOURCES, tools=DISK
    )
    argv = out["capture"]["argv"]
    assert "--tools=read,grep,glob,bash,write,zoom" in argv
    assert "--mode=json" in argv and "--no-tools" not in argv
    assert argv[argv.index("--model") + 1] == "anthropic/claude-haiku-5.5"
    assert "--thinking=off" in argv
    assert "how much disk is free?" in out["capture"]["stdin"]
    assert out["voiceCalls"] == 1
    assert "tools" not in out["voiceBodies"][0]
