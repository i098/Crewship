"""The V2 desk subagent against a fake omp and a fake Inception voice endpoint."""

import json
import shutil

import pytest
from test_imessage import ROOT, bun

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

SUBAGENT = json.dumps(str(ROOT / "apps/imessage/subagent.ts"))


UNSET = object()


def subagent(requests, drafted, tools=None, voice=None, write_path=UNSET):
    """Run runSubagent with a fake omp that drafts `drafted` over fake tool `tools`.

    The fake Inception endpoint echoes the draft, and the script reports the result
    plus how many voice calls it saw.
    """
    if write_path is UNSET:
        write_path = "undefined"
    return bun(f"""
import {{ runSubagent }} from {SUBAGENT};
import {{ mkdtempSync }} from "node:fs";
import {{ tmpdir }} from "node:os";
import {{ join }} from "node:path";

const drafted = {json.dumps(drafted)};
const tools = {json.dumps(tools or {})};
const voiceCalls = [];
const voice = Bun.serve({{ port: 0, async fetch(req) {{
  const body = JSON.parse(await req.text());
  voiceCalls.push(body);
  return Response.json({{ choices: [{{ message: {{ content: JSON.parse(body.messages[1].content).draft }} }}] }});
}} }});
const bin = mkdtempSync(join(tmpdir(), "fm-desk-bin-"));
await Bun.write(join(bin, "omp"), `#!/usr/bin/env python3
import json, sys
sys.stdin.read()
print(json.dumps({{"type": "desk_result", "drafted": ${{JSON.stringify(drafted)}}, "tools": ${{JSON.stringify(tools)}}}}))
`);
Bun.spawnSync(["chmod", "+x", join(bin, "omp")]);
const cwd = mkdtempSync(join(tmpdir(), "fm-desk-cwd-"));
const requests = {json.dumps(requests)};
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
  current: () => true,
  onProcess: () => {{}},
}});
voice.stop(true);
console.log(JSON.stringify({{ result, voiceCalls: voiceCalls.length }}));
""")


def test_tool_sources_answer_quotes_whole_lines_only():
    out = subagent([{"authored": "how much disk is free?", "context": "df output"}],
                   json.dumps({"kind": "sources", "target": 1, "sources": [{"tool": 1, "line": 1}]}),
                   tools={"1": {"text": "Disk usage is 12 percent.\nsecond line"}})
    assert out["result"]["kind"] == "answer"
    assert out["result"]["bubbles"] == ["Disk usage is 12 percent."]
    assert out["result"]["tools"] == {"1": {"text": "Disk usage is 12 percent.\nsecond line"}}
    assert out["voiceCalls"] == 1


def test_unparsable_draft_hands_off_without_a_voice_call():
    out = subagent([{"authored": "how much disk is free?", "context": "df output"}], "not json")
    assert out["result"] == {"kind": "handoff", "reason": "unverified", "tools": {}}
    assert out["voiceCalls"] == 0


def test_source_reference_outside_the_tools_hands_off():
    out = subagent([{"authored": "how much disk is free?", "context": "df output"}],
                   json.dumps({"kind": "sources", "target": 1, "sources": [{"tool": 9, "line": 1}]}),
                   tools={"1": {"text": "one line"}})
    assert out["result"] == {"kind": "handoff", "reason": "unverified", "tools": {"1": {"text": "one line"}}}
    assert out["voiceCalls"] == 0


def test_handled_requires_the_authorized_write_path():
    drafted = json.dumps({"kind": "handled"})
    out = subagent([{"authored": "write the report to /tmp/report.txt", "context": ""}], drafted,
                   write_path=json.dumps("/tmp/other.txt"))
    assert out["result"]["kind"] == "handoff"
    assert out["voiceCalls"] == 0
