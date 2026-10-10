"""The iMessage bridge (docs/imessage.md): the send command's options and the service's pure decisions.

No test talks to Photon: curl is a stand-in that records its arguments, imessage/desk.ts holds
the decisions bridge.ts makes, free of spectrum-ts, and the outage test runs bridge.ts against a
fake spectrum-ts whose upstream returns UNAVAILABLE.
"""

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
SEND = ROOT / "imessage/fm-imessage"


def send(tmp_path, *args):
    """Run fm-imessage with a curl stand-in; return the result and the recorded curl calls."""
    calls = tmp_path / "curl-calls"
    (tmp_path / "curl").write_text(f'#!/bin/bash\necho "$*" >> {calls}\ncat >/dev/null\n')
    (tmp_path / "curl").chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(SEND), *args], input="", capture_output=True, text=True, env=env, timeout=10
    )
    return result, calls.read_text().splitlines() if calls.exists() else []


def test_text_goes_to_send(tmp_path):
    result, calls = send(tmp_path, "hello")
    assert result.returncode == 0
    assert len(calls) == 1 and calls[0].endswith("http://127.0.0.1:8765/send")


@pytest.mark.parametrize("option", ["--bogus", "-x", "--typo=1"])
@pytest.mark.parametrize("options", [[], ["--reply", "1"], ["--no-thread"]])
def test_unknown_option_sends_nothing(tmp_path, option, options):
    result, calls = send(tmp_path, *options, option, "--", "hello")
    assert result.returncode == 2
    assert "nothing sent" in result.stderr
    assert calls == []


def test_reply_threads_to_an_earlier_text(tmp_path):
    result, calls = send(tmp_path, "--reply", "3", "that one")
    assert result.returncode == 0
    assert len(calls) == 1 and calls[0].endswith("http://127.0.0.1:8765/send?reply=3")


@pytest.mark.parametrize("n", [None, "", "0", "11", "-1", "2x", "03"])
def test_reply_needs_a_kept_text_number(tmp_path, n):
    result, calls = send(tmp_path, "--reply", *([n] if n is not None else []))
    assert result.returncode == 2
    assert "nothing sent" in result.stderr
    assert calls == []


@pytest.mark.parametrize("option", ["--help", "-h"])
def test_help_sends_nothing(tmp_path, option):
    result, calls = send(tmp_path, option)
    assert result.returncode == 0
    assert "Usage: fm-imessage" in result.stdout
    assert calls == []


DESK = json.dumps(str(ROOT / "imessage/desk.ts"))


def bun(code):
    """Run TypeScript that prints one JSON value; return the value."""
    out = subprocess.run(
        ["bun", "-e", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    return json.loads(out)


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_describe_unwraps_what_he_writes():
    result = bun(f"""
import {{ describe }} from {DESK};
const text = (t) => ({{ type: "text", text: t }});
const save = async (c, id) => {{ if (c.name === "bad.png") throw new Error("disk full"); return `/att/${{id}}-${{c.name}}`; }};
const contents = [
  text("ship it"),
  {{ type: "attachment", name: "a.png" }},
  {{ type: "attachment", name: "bad.png" }},
  {{ type: "contact", name: {{ formatted: "Ana" }} }},
  {{ type: "contact" }},
  {{ type: "reply", content: text("yes that one"), target: {{ content: text("deploy tonight?") }} }},
  {{ type: "reply", content: text("this"), target: {{ content: {{ type: "attachment" }} }} }},
  {{ type: "reply", content: {{ type: "reaction" }}, target: {{ content: text("x") }} }},
  {{ type: "edit", content: text("fixed typo") }},
  {{ type: "effect", content: text("boom") }},
  {{ type: "group", items: [{{ content: text("one") }}, {{ content: {{ type: "typing" }} }}, {{ content: {{ type: "attachment", name: "b.png" }} }}] }},
  {{ type: "group", items: [{{ content: {{ type: "read" }} }}] }},
  {{ type: "hologram" }},
  {{ type: "reaction" }},
  {{ type: "typing" }},
  {{ type: "read" }},
  {{ type: "unsend" }},
];
console.log(JSON.stringify(await Promise.all(contents.map(async (c) => (await describe(c, "m1", save)) ?? null))));
""")
    assert result == [
        "ship it",
        "(sent an attachment, saved for Firstmate at /att/m1-a.png)",
        "(sent an attachment that could not be saved yet; the bridge retries the download and files this note again with the path)",
        "(sent a contact: Ana)",
        "(sent a contact: no name)",
        'yes that one (replying in a thread to: "deploy tonight?")',
        'this (replying in a thread to: "attachment")',
        None,
        "(edited a message to) fixed typo",
        "boom",
        "one\n(sent an attachment, saved for Firstmate at /att/m1-2-b.png)",
        None,
        "(sent a hologram message the bridge cannot show)",
        None,
        None,
        None,
        None,
    ]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_answer_and_prompt():
    result = bun(f"""
import {{ deskPrompt, isSkip, parseReact }} from {DESK};
const answers = ["REACT:👍", "REACT: 🫡 ", "REACT:👍 thanks", "got it", "ok REACT:👍", "SKIP"];
const skips = ["skip", "Skip", "SKIP.", "skip!!", "skip it", "REACT:👍", "ok"];
console.log(JSON.stringify({{
  reacts: answers.map((a) => parseReact(a) ?? null),
  skips: skips.map(isSkip),
  named: deskPrompt("Ana", "desk-model-a", "boss-model-b"),
  unnamed: deskPrompt("the owner", "desk-model-a", ""),
}}));
""")
    assert result["reacts"] == ["👍", "🫡", None, None, None, None]
    assert result["skips"] == [True, True, True, True, False, False, False]
    assert "Ana's AI supervisor" in result["named"]
    assert "you're desk-model-a" in result["named"] and "Firstmate is boss-model-b" in result["named"]
    assert "say you don't know" in result["unnamed"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bubbles_split_paragraphs_and_keep_lists():
    result = bun(f"""
import {{ bubbles, typingPause }} from {DESK};
console.log(JSON.stringify({{
  split: bubbles("on it\\n\\nschedule:\\n9am standup\\n2pm deploy\\n  \\n\\nlmk"),
  single: bubbles("  just one  "),
  empty: bubbles("\\n \\n"),
  pauses: [typingPause("ok"), typingPause("x".repeat(400))],
}}));
""")
    assert result["split"] == ["on it", "schedule:\n9am standup\n2pm deploy", "lmk"]
    assert result["single"] == ["just one"]
    assert result["empty"] == []
    assert result["pauses"] == [450, 2500]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_timing():
    """The desk gets one turn per burst after a quiet period, and stands down for Firstmate or a newer text."""
    result = bun(f"""
import {{ DeskTiming }} from {DESK};
function clock() {{
  let now = 0, next = 1;
  const pending = new Map();
  return {{
    setTimeout: (fn, ms) => {{ pending.set(next, [now + ms, fn]); return next++; }},
    clearTimeout: (id) => pending.delete(id),
    advance(ms) {{
      now += ms;
      for (const [id, [at, fn]] of [...pending]) if (at <= now) {{ pending.delete(id); fn(); }}
    }},
  }};
}}
function desk() {{
  const c = clock(), turns = [];
  const d = new DeskTiming(4000, (current) => turns.push(current), c);
  return {{ c, d, turns }};
}}
const out = {{}};
{{ // quiet period
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(3999);
  out.beforeQuiet = turns.length;
  c.advance(1);
  out.afterQuiet = turns.length; out.current = turns[0]();
}}
{{ // a burst: each text restarts the wait, one turn for all of it
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(2500); d.inboundText(); c.advance(2500);
  out.burstEarly = turns.length;
  c.advance(1500); c.advance(60000);
  out.burstTurns = turns.length;
}}
{{ // Firstmate active before the quiet period ends: no turn; his next text starts a new one
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(1500); d.firstmateActive(); c.advance(60000);
  out.standDown = turns.length;
  d.inboundText(); c.advance(4000);
  out.nextBurst = turns.length; out.nextCurrent = turns[0]();
}}
{{ // the draft is dropped when Firstmate or a newer text arrives while the desk writes
  const {{ c, d, turns }} = desk();
  d.inboundText(); c.advance(4000); d.firstmateActive();
  out.firstmateWhileDrafting = turns[0]();
  d.inboundText(); c.advance(1000);
  out.newerWhileDrafting = turns[0]();
}}
console.log(JSON.stringify(out));
""")
    assert result == {
        "beforeQuiet": 0,
        "afterQuiet": 1,
        "current": True,
        "burstEarly": 0,
        "burstTurns": 1,
        "standDown": 0,
        "nextBurst": 1,
        "nextCurrent": True,
        "firstmateWhileDrafting": False,
        "newerWhileDrafting": False,
    }


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_service_refuses_foreign_requests():
    result = bun(f"""
import {{ localCommand }} from {DESK};
const h = (host, marker) => new Headers({{ ...(host ? {{ host }} : {{}}), ...(marker ? {{ "x-firstmate": marker }} : {{}}) }});
console.log(JSON.stringify([
  localCommand(h("127.0.0.1:8765", "1"), 8765),
  localCommand(h("127.0.0.1:8765"), 8765),
  localCommand(h("127.0.0.1:8765", "0"), 8765),
  localCommand(h("evil.example:8765", "1"), 8765),
  localCommand(h("localhost:8765", "1"), 8765),
  localCommand(h("127.0.0.1:9000", "1"), 8765),
  localCommand(h(undefined, "1"), 8765),
]));
""")
    assert result == [True, False, False, False, False, False, False]


MEMORY = json.dumps(str(ROOT / "imessage/memory.ts"))


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_merges_in_push_order():
    """With the rollback push's list length as the budget, the view makes exactly the merges push makes."""
    result = bun(f"""
import {{ shrink }} from {MEMORY};
function push(n, s) {{
  if (s === null) return {{ keep: 0, life: 0, state: n, older: null }};
  const {{ keep, life, state, older }} = s;
  if (keep === 0) return {{ keep: 1, life, state, older }};
  if (life > 0) return {{ keep: 0, life: 0, state: n, older: {{ keep: 0, life: life - 1, state, older }} }};
  return {{ keep: 0, life, state: n, older: push(state, older) }};
}}
let s = null, view = [], bad = [];
for (let t = 0; t <= 2000; t++) {{
  s = push(t, s);
  const starts = [];
  for (let x = s; x; x = x.older) starts.unshift(x.state);
  const want = starts.map((a, k) => {{ const n = (starts[k + 1] ?? t + 1) - a; return [Math.log2(n), a / n]; }});
  view.push([0, t]);
  shrink(view, t + 1, want.length, () => 1, () => true);
  if (JSON.stringify(view) !== JSON.stringify(want)) bad.push(t);
}}
console.log(JSON.stringify(bad));
""")
    assert result == []


# A fake desk model: each conversation answers with lines of the lengths in `sizes`, one per turn.
FAKE = """
import { readdirSync, readFileSync } from "node:fs";
const calls = [];
function fake(sizes) {
  return () => {
    const turns = [];
    calls.push(turns);
    return { say: async (text) => { turns.push(text); return "x".repeat(sizes[Math.min(turns.length, sizes.length) - 1]); }, end() {} };
  };
}
async function idle(m) { while (m.pending) await Bun.sleep(0); }
const files = (dir) => Object.fromEntries(["main", "tree"].flatMap((sub) =>
  readdirSync(`${dir}/${sub}`).map((f) => [`${sub}/${f}`, readFileSync(`${dir}/${sub}/${f}`, "utf8")])).concat([["view.json", readFileSync(`${dir}/view.json`, "utf8")]]));
"""


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_view_is_a_sawtooth(tmp_path):
    """The view grows one line per message and, past VIEW_MAX, drops back to at most VIEW_MIN in one batch."""
    result = bun(f"""
import {{ Memory, VIEW_MAX, VIEW_MIN }} from {MEMORY};
{FAKE}
const m = new Memory({json.dumps(str(tmp_path))}, fake([400]));
const sizes = [];
for (let n = 0; n < 3000; n++) {{
  m.append(["owner", "supervisor", "desk"][n % 3], `text ${{n}} `.padEnd(100, "."));
  sizes.push(Buffer.byteLength(m.render()));
  await idle(m);
}}
const drops = sizes.flatMap((s, k) => (k && s < sizes[k - 1] ? [s] : []));
const covered = m.view.reduce((s, [l]) => s + 2 ** l, 0);
console.log(JSON.stringify({{ max: Math.max(...sizes), drops, covered, VIEW_MAX, VIEW_MIN }}));
""")
    assert result["max"] <= result["VIEW_MAX"]
    assert len(result["drops"]) >= 2
    assert all(drop <= result["VIEW_MIN"] for drop in result["drops"])
    assert result["covered"] == 3000


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_survives_a_restart(tmp_path):
    """The log, the tree and the view load back unchanged; nothing is rebuilt; zoom opens lines from disk."""
    result = bun(f"""
import {{ load, Memory, zoom }} from {MEMORY};
{FAKE}
const dir = {json.dumps(str(tmp_path))};
const a = new Memory(dir, fake([300]));
for (let n = 0; n < 40; n++) {{ a.append(n % 2 ? "desk" : "owner", n === 5 ? "y".repeat(900) : `text ${{n}}`); await idle(a); }}
const before = files(dir), callsBefore = calls.length;
const b = new Memory(dir, fake([300]));
await idle(b);
const after = files(dir);
const view = JSON.stringify(a.view) === JSON.stringify(b.view) && a.render() === b.render();
const id = b.append("owner", "after restart");
const disk = load(dir);
console.log(JSON.stringify({{
  same: JSON.stringify(before) === JSON.stringify(after),
  view,
  newCalls: calls.length - callsBefore,
  id,
  long: zoom(disk.msgs, disk.nodes, 5, 1),
  pair: zoom(disk.msgs, disk.nodes, 0, 2),
  bad: zoom(disk.msgs, disk.nodes, 3, 2),
}}));
""")
    assert result["same"] and result["view"]
    assert result["newCalls"] == 0
    assert result["id"] == 40
    assert result["long"].endswith(" desk: " + "y" * 900)
    assert result["pair"] == "0+1|owner: text 0\n1+1|desk: text 1"
    assert result["bad"].startswith("no line 3+2")


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_memory_nodes_fit_the_limit(tmp_path):
    """A line over LIMIT is asked again in the same conversation, at most TRIES calls, and every node fits."""
    result = bun(f"""
import {{ LIMIT, Memory, TRIES }} from {MEMORY};
{FAKE}
const shrinking = new Memory({json.dumps(str(tmp_path / "a"))}, fake([2000, 1000, 500]));
shrinking.append("owner", "z".repeat(3000)); await idle(shrinking);
const stubborn = new Memory({json.dumps(str(tmp_path / "b"))}, fake([2000, 1500, 900, 700, 600, 100]));
stubborn.append("owner", "z".repeat(3000)); await idle(stubborn);
const sizes = [...shrinking.nodes.values(), ...stubborn.nodes.values()].map((n) => n.size);
console.log(JSON.stringify({{ turns: calls.map((c) => c.length), sizes, LIMIT, TRIES, retry: calls[0][1] }}));
""")
    assert result["turns"] == [3, result["TRIES"]]
    assert result["sizes"] == [500, result["LIMIT"]]
    assert result["retry"].startswith("Too long: your line is 2000 bytes, over the 512-byte limit.")


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_desk_call_stays_under_the_ceiling():
    """A desk prompt with huge status and texts, plus every zoom result, never passes CEILING bytes."""
    result = bun(f"""
import {{ deskInput }} from {DESK};
import {{ Budget, CEILING, LIMIT_REACHED, OVERHEAD, ZOOM_MAX, ZOOM_RESERVE }} from {MEMORY};
const system = "s".repeat(3000), view = "v".repeat(400000); // a view grown past VIEW_MAX by a compaction outage
const {{ prompt, spent }} = deskInput(system, view, "q".repeat(500000), "HEAD" + "m".repeat(1000000) + "TAIL");
const budget = new Budget(spent);
const results = [], requests = [spent];
for (let k = 0; k < 100; k++) {{
  const r = budget.take("ZOOMHEAD" + "z".repeat(100000) + "ZOOMTAIL");
  if (r === undefined) break;
  results.push(r);
  requests.push(budget.spent);
}}
console.log(JSON.stringify({{
  first: spent, own: OVERHEAD + Buffer.byteLength(system + prompt), keepsEnds: prompt.includes("HEAD") && prompt.includes("TAIL"),
  maxRequest: Math.max(...requests), zoomSizes: results.map((r) => Buffer.byteLength(r)), zoomEnds: results[0].startsWith("ZOOMHEAD") && results[0].endsWith("ZOOMTAIL"),
  refused: results.includes(LIMIT_REACHED), CEILING, ZOOM_MAX, ZOOM_RESERVE,
}}));
""")
    assert result["first"] == result["own"] <= result["CEILING"] - result["ZOOM_RESERVE"]
    assert result["keepsEnds"] and result["zoomEnds"]
    assert result["maxRequest"] <= result["CEILING"]
    assert all(size <= result["ZOOM_MAX"] for size in result["zoomSizes"])
    assert result["refused"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_compaction_stays_under_the_ceiling(tmp_path):
    """One huge message is clipped head and tail, and retries stop before a request passes CEILING bytes."""
    result = bun(f"""
import {{ CEILING, LIMIT, Memory, OVERHEAD }} from {MEMORY};
const requests = [], firsts = [];
const chat = (system) => {{
  let sent = Buffer.byteLength(system) + OVERHEAD;
  return {{
    async say(text) {{
      sent += Buffer.byteLength(text);
      requests.push(sent);
      if (requests.length === 1) firsts.push(text);
      const reply = "r".repeat(3000); // a model that never fits
      sent += Buffer.byteLength(reply);
      return reply;
    }},
    end() {{}},
  }};
}};
const m = new Memory({json.dumps(str(tmp_path))}, chat);
m.append("owner", "HEAD" + "m".repeat(1000000) + "TAIL");
while (m.pending) await Bun.sleep(0);
console.log(JSON.stringify({{
  requests, CEILING, keepsEnds: firsts[0].includes("owner: HEAD") && firsts[0].includes("TAIL\\n</input>"),
  size: m.nodes.get("0:0").size, LIMIT,
}}));
""")
    assert len(result["requests"]) >= 2
    assert max(result["requests"]) <= result["CEILING"]
    assert result["keepsEnds"]
    assert result["size"] <= result["LIMIT"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_compaction_stays_under_the_ceiling_when_the_model_keeps_failing(tmp_path):
    """Short messages and a model that always throws leave the context unmerged; its request is still clipped."""
    result = bun(f"""
import {{ CEILING, Memory }} from {MEMORY};
let largest = 0;
const chat = () => ({{
  async say(text) {{ largest = Math.max(largest, Buffer.byteLength(text)); throw new Error("down"); }},
  end() {{}},
}});
const m = new Memory({json.dumps(str(tmp_path))}, chat);
for (let i = 0; i < 900; i++) m.append("owner", "x".repeat(260));
while (m.pending) await Bun.sleep(0);
console.log(JSON.stringify({{ largest, CEILING }}));
""")
    assert 0 < result["largest"] <= result["CEILING"]


@pytest.mark.parametrize("args", [("hello",), ("--reply", "1", "hi"), ("--typing",), ("--react", "👍")])
def test_send_commands_carry_the_local_header(tmp_path, args):
    result, calls = send(tmp_path, *args)
    assert result.returncode == 0
    assert len(calls) == 1 and "-H X-Firstmate: 1" in calls[0]


def test_location_carries_the_local_header(tmp_path):
    (tmp_path / "curl").write_text(f'#!/bin/bash\necho "$*" >> {tmp_path / "calls"}\n')
    (tmp_path / "curl").chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    result = subprocess.run(
        [str(ROOT / "imessage/fm-location")], capture_output=True, text=True, env=env, timeout=10
    )
    assert result.returncode == 0
    calls = (tmp_path / "calls").read_text().splitlines()
    assert len(calls) == 1 and "-H X-Firstmate: 1" in calls[0] and calls[0].endswith("/location")


BB = json.dumps(str(ROOT / "imessage/bluebubbles.ts"))

# Fake BlueBubbles relays: local Bun servers with the API paths bluebubbles.ts calls, no network, no real
# password. Relays share `icloud`, the texts the Apple Account sent, as Macs on one account do. A relay can go
# down (connection refused), come back on its port, or take a send and never answer (`hang`).
FAKE_BB = """
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
const icloud = [];
function relay(password = "pw-test") {
  const r = { password, privateApi: true, calls: [], sent: [], messages: new Map(), files: new Map(), fail: {}, hang: false };
  r.start = () => {
    r.server = Bun.serve({ port: r.port ?? 0, async fetch(req) {
      const u = new URL(req.url);
      if (u.searchParams.get("password") !== r.password) return Response.json({ error: { message: "Unauthorized" } }, { status: 401 });
      const path = u.pathname.replace("/api/v1/", "");
      const body = req.method === "POST" ? await req.json().catch(() => null) : null;
      r.calls.push(`${req.method} ${path}`);
      const failing = Object.keys(r.fail).find((p) => path.startsWith(p) && r.fail[p]-- > 0);
      if (failing) return Response.json({ error: { message: "Service temporarily unavailable" } }, { status: 500 });
      if (path === "server/info") return Response.json({ data: { private_api: r.privateApi, helper_connected: r.privateApi } });
      if (!r.privateApi && (path === "message/react" || path.endsWith("/typing") || (path === "message/text" && body.selectedMessageGuid))) {
        return Response.json({ error: { message: "Please make sure you have completed the setup for the Private API" } }, { status: 500 });
      }
      if (path === "message/text") {
        r.sent.push(body);
        icloud.push({ guid: `sent-${r.sent.length}`, chat: body.chatGuid, text: body.message, at: Date.now() });
        if (r.hang) return new Promise(() => {});
        return Response.json({ data: { guid: `sent-${r.sent.length}`, tempGuid: body.tempGuid } });
      }
      if (path === "message/react") { r.sent.push(body); return Response.json({ data: {} }); }
      if (path === "message/query") return Response.json({ data: [...r.messages.values()].filter((m) => m.dateCreated > body.after).sort((a, b) => (body.sort === "DESC" ? b.dateCreated - a.dateCreated : a.dateCreated - b.dateCreated)) });
      let m = path.match(/^chat\\/([^/]+)\\/message$/);
      if (m) return Response.json({ data: r.blind ? [] : icloud.filter((s) => s.chat === decodeURIComponent(m[1]) && s.at > Number(u.searchParams.get("after"))).map((s) => ({ guid: s.guid, isFromMe: true, text: s.text })) });
      if (/^chat\\/[^/]+\\/(typing|read)$/.test(path)) return Response.json({ data: null });
      m = path.match(/^attachment\\/([^/]+)\\/download$/);
      if (m && r.slow && r.files.has(m[1])) {
        const body = r.files.get(m[1]);
        return new Response(new ReadableStream({ async start(c) { c.enqueue(new TextEncoder().encode(body.slice(0, 3))); await Bun.sleep(r.slow); c.enqueue(new TextEncoder().encode(body.slice(3))); c.close(); } }));
      }
      if (m) return r.files.has(m[1]) ? new Response(r.files.get(m[1])) : Response.json({ error: { message: "Attachment does not exist!" } }, { status: 404 });
      m = path.match(/^message\\/([^/]+)$/);
      if (m && r.messages.has(decodeURIComponent(m[1]))) return Response.json({ data: r.messages.get(decodeURIComponent(m[1])) });
      return Response.json({ error: { message: "Message does not exist!" } }, { status: 404 });
    } });
    r.port = r.server.port;
    r.url = `http://127.0.0.1:${r.port}`;
  };
  r.down = () => r.server.stop(true);
  r.start();
  return r;
}
const owner = "+15550000000", chat = `iMessage;-;${owner}`;
const text = (guid, t, extra = {}) => ({ guid, text: t, isFromMe: false, dateCreated: Date.now(), handle: { address: owner }, chats: [{ guid: chat }], attachments: [], ...extra });
const logs = [];
function line(relays, opts = {}, dir = mkdtempSync(`${tmpdir()}/bb-`)) {
  const bb = new BlueBubbles(relays.map((r) => ({ url: r.url, password: r.password })), dir,
    { pingMs: 200, healthMs: 0, sendMs: 300, ...opts }, (l) => logs.push(l));
  bb.got = [];
  (async () => { for await (const m of bb) { bb.got.push(m); if (bb.ack !== false) bb.markSeen(m.id); } })();
  bb.dir = dir;
  return bb;
}
const hook = (bb, guid, isFromMe = false) => bb.webhook(new Request("http://agent/bluebubbles", { method: "POST", body: JSON.stringify({ type: "new-message", data: { guid, isFromMe } }) }));
// Wait until every message accepted so far is queued: accept() on a seen GUID returns the queue's tail.
const settle = async (bb, guid) => { await bb.accept(guid); await Bun.sleep(5); };
// Bun.serve keeps the process alive, so each script prints its result and exits.
const done = (v) => { console.log(JSON.stringify(v)); process.exit(0); };
"""


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_send_typing_tapback_and_reply():
    """Sends carry a tempGuid, a reply threads to its message, tapbacks map to BlueBubbles names, typing never fails."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), bb = line([a]);
await bb.send(chat, "hello");
await bb.send(chat, "that one", "his-guid");
await bb.react(chat, "his-guid", "❤️");
let odd = null;
try {{ await bb.react(chat, "his-guid", "🦄"); }} catch (e) {{ odd = e.message; }}
a.fail["chat/"] = 2;
await bb.typing(chat, "POST"); await bb.typing(chat, "DELETE");
await bb.send(chat, "after a typing error");
done({{ sent: a.sent, calls: a.calls, odd, logs }});
""")
    plain, reply, tapback, after = result["sent"]
    assert plain["chatGuid"] == "iMessage;-;+15550000000" and plain["message"] == "hello" and plain["tempGuid"]
    assert "selectedMessageGuid" not in plain
    assert reply["selectedMessageGuid"] == "his-guid" and reply["message"] == "that one"
    assert tapback == {"chatGuid": plain["chatGuid"], "selectedMessageGuid": "his-guid", "reaction": "love", "partIndex": 0}
    assert "🦄" in result["odd"] and "❤️" in result["odd"]
    assert after["message"] == "after a typing error"
    assert any(c.startswith("POST chat/") and c.endswith("/typing") for c in result["calls"])
    assert any(c.startswith("DELETE chat/") for c in result["calls"])
    assert [line for line in result["logs"] if line.startswith("typing failed")]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_without_private_api_skips_actions_and_sends_plain_reply():
    """A relay without the Private API sends replies without a thread and never receives typing or tapback requests."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(); a.privateApi = false;
a.messages.set("his-guid", text("his-guid", "hello"));
const bb = line([a]);
const message = await bb.message("his-guid");
await message.space.startTyping(); await message.space.stopTyping();
const reaction = await message.react("❤️").catch((e) => e.message);
const reply = await message.reply("plain reply").catch((e) => e.message);
done({{ calls: a.calls, sent: a.sent, reaction: reaction ?? null, reply: reply ?? null, logs }});
""")
    assert not [call for call in result["calls"] if call.endswith("/typing") or call == "POST message/react"]
    assert [item["message"] for item in result["sent"]] == ["plain reply"]
    assert "selectedMessageGuid" not in result["sent"][0] and "partIndex" not in result["sent"][0]
    assert len(result["logs"]) == 1 and "Private API" in result["logs"][0]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_private_api_is_per_relay_and_refreshes_on_health_checks():
    """Startup reads every relay; a state change takes effect on the next health check and logs only once."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), b = relay(); a.privateApi = false;
const bb = line([a, b]);
bb.start(); await bb.catchUp();
await bb.typing(chat, "POST"); await bb.react(chat, "his-guid", "👍");
a.fail["message/text"] = 1;
await bb.send(chat, "fallback thread", "his-guid");
const initial = [a.calls.slice(), b.calls.slice()];
a.privateApi = true; b.privateApi = false;
await bb.catchUp(); await bb.catchUp();
await bb.typing(chat, "POST"); await bb.typing(chat, "DELETE");
await bb.react(chat, "his-guid", "👍");
await bb.send(chat, "thread on", "his-guid");
a.down();
await bb.typing(chat, "POST"); await bb.react(chat, "his-guid", "👍");
await bb.send(chat, "thread off", "his-guid");
done({{ initial, calls: [a.calls, b.calls], sent: [a.sent, b.sent], capabilityLogs: logs.filter((l) => l.includes("Private API")) }});
""")
    first, second = result["initial"]
    assert "GET server/info" in first and "GET server/info" in second
    assert not [call for call in first if call.endswith("/typing") or call == "POST message/react"]
    assert sum(call.endswith("/typing") for call in second) == 1 and "POST message/react" in second
    assert result["sent"][0][0]["reaction"] == "like"
    assert result["sent"][0][1]["selectedMessageGuid"] == "his-guid"
    tapback, threaded, plain = result["sent"][1]
    assert tapback["reaction"] == "like" and tapback["selectedMessageGuid"] == "his-guid"
    assert threaded["message"] == "fallback thread" and threaded["selectedMessageGuid"] == "his-guid"
    assert plain["message"] == "thread off" and "selectedMessageGuid" not in plain and "partIndex" not in plain
    assert sum(call.endswith("/typing") for call in result["calls"][0]) == 2
    assert [call for call in result["calls"][1] if call.endswith("/typing") or call == "POST message/react"] == [
        call for call in second if call.endswith("/typing") or call == "POST message/react"
    ]
    assert len(result["capabilityLogs"]) == 3
    assert "relay 1" in result["capabilityLogs"][0] and "is off" in result["capabilityLogs"][0]
    assert any("relay 1" in line and "is on" in line for line in result["capabilityLogs"])
    assert any("relay 2" in line and "is off" in line for line in result["capabilityLogs"])


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_private_api_cache_expires_during_active_sends():
    """Successful traffic does not keep an old capability alive beyond the health-check interval."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
let now = Date.now(); Date.now = () => now;
const a = relay(), bb = line([a], {{ healthMs: 1000 }});
await bb.send(chat, "first thread", "his-guid");
now += 500; await bb.send(chat, "busy");
a.privateApi = false;
now += 501; await bb.send(chat, "plain after refresh", "his-guid");
done({{ sent: a.sent, probes: a.calls.filter((c) => c === "GET server/info").length, logs }});
""")
    assert result["sent"][0]["selectedMessageGuid"] == "his-guid"
    assert "selectedMessageGuid" not in result["sent"][2]
    assert result["probes"] == 2
    assert len(result["logs"]) == 1 and "is off" in result["logs"][0]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_inbound_is_read_back_and_deduplicated(tmp_path):
    """Webhooks from every relay become one message each; a forged GUID yields nothing; the seen-set survives a restart."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), b = relay();
for (const r of [a, b]) {{
  r.messages.set("m1", text("m1", "ship it"));
  r.messages.set("m2", text("m2", "this one", {{ threadOriginatorGuid: "m1" }}));
}}
const dir = {json.dumps(str(tmp_path))};
const bb = line([a, b], {{}}, dir);
await hook(bb, "m1"); await hook(bb, "m1"); await settle(bb, "m1");
await hook(bb, "m2"); await settle(bb, "m2");
await hook(bb, "forged"); await hook(bb, "mine", true); await settle(bb, "m1");
const after = line([b, a], {{}}, dir);
await hook(after, "m1"); await hook(after, "m2"); await settle(after, "m1");
done({{
  got: bb.got.map((m) => [m.id, m.direction, m.sender.id, m.space.id, m.content]),
  restarted: after.got.length,
  reads: a.calls.filter((c) => c === "GET message/m1").length + b.calls.filter((c) => c === "GET message/m1").length,
  logs,
}});
""")
    assert result["got"] == [
        ["m1", "inbound", "+15550000000", "iMessage;-;+15550000000", {"type": "text", "text": "ship it"}],
        ["m2", "inbound", "+15550000000", "iMessage;-;+15550000000",
         {"type": "reply", "content": {"type": "text", "text": "this one"}, "target": {"content": {"type": "text", "text": "ship it"}}}],
    ]
    assert result["restarted"] == 0
    assert result["reads"] == 2  # m1 itself once, and once as the thread target of m2
    assert any(line.startswith("could not read message forged") for line in result["logs"])


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_catch_up_files_a_message_whose_webhook_was_lost_once(tmp_path):
    """A newer message arrives by webhook, an older one never does: a catch-up in the window files it, nothing twice."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), b = relay();
const now = Date.now();
for (const r of [a, b]) {{
  r.messages.set("old", text("old", "its webhook was lost", {{ dateCreated: now - 5 * 60_000 }}));
  r.messages.set("new", text("new", "this one came by webhook", {{ dateCreated: now - 60_000 }}));
  r.messages.set("stale", text("stale", "outside the window", {{ dateCreated: now - 30 * 60_000 }}));
}}
const dir = {json.dumps(str(tmp_path))};
const bb = line([a, b], {{}}, dir);
await hook(bb, "new"); await settle(bb, "new");
await bb.catchUp(); await bb.catchUp(); await settle(bb, "old");
const after = line([a, b], {{}}, dir);
await after.catchUp(); await settle(after, "old");
done({{ got: bb.got.map((m) => m.id), restarted: after.got.map((m) => m.id) }});
""")
    assert result["got"] == ["new", "old"]
    assert result["restarted"] == []


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_a_message_is_kept_as_seen_only_after_the_bridge_handled_it(tmp_path):
    """A bridge that exits before it files the note gets the message again from the catch-up, once; after the note, never."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay();
a.messages.set("m1", text("m1", "filed once", {{ dateCreated: Date.now() - 60_000 }}));
const dir = {json.dumps(str(tmp_path))};
const crashed = line([a], {{}}, dir); crashed.ack = false;
await crashed.catchUp(); await settle(crashed, "m1");
const restarted = line([a], {{}}, dir);
await restarted.catchUp(); await restarted.catchUp(); await settle(restarted, "m1");
const later = line([a], {{}}, dir);
await later.catchUp(); await settle(later, "m1");
done({{ crashed: crashed.got.map((m) => m.id), restarted: restarted.got.map((m) => m.id), later: later.got.map((m) => m.id) }});
""")
    assert result == {"crashed": ["m1"], "restarted": ["m1"], "later": []}


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_the_inbound_download_is_short_and_the_queue_keeps_the_long_one():
    """A slow attachment does not hold the inbound loop for downloadMs: its first read fails at callMs, the queue's read works."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ transient }} from {OUTBOX};
{FAKE_BB}
const a = relay();
a.files.set("at1", "PNGDATA"); a.slow = 600;
a.messages.set("m3", text("m3", "\\uFFFC", {{ attachments: [{{ guid: "at1", transferName: "pic.png", mimeType: "image/png" }}] }}));
const bb = line([a], {{ callMs: 200, downloadMs: 5000 }});
await hook(bb, "m3"); await settle(bb, "m3");
const started = Date.now();
const inline = await bb.got[0].content.read().catch((e) => e);
const inlineMs = Date.now() - started;
const queued = (await (await bb.message("m3")).content.read()).toString();
done({{ inline: transient(inline) ?? null, inlineMs, queued }});
""")
    assert result["inline"] == "TIMEOUT" and result["inlineMs"] < 2000
    assert result["queued"] == "PNGDATA"

@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_attachment_comes_from_the_relay_that_has_it():
    """A download tries every relay; its errors tell the bridge's download queue to retry or to give up."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ describe }} from {DESK};
import {{ permanent, transient }} from {OUTBOX};
{FAKE_BB}
const a = relay(), b = relay();
const pic = text("m3", "\\uFFFC", {{ attachments: [{{ guid: "at1", transferName: "pic one.png", mimeType: "image/png" }}] }});
a.messages.set("m3", pic); b.messages.set("m3", pic);
b.files.set("at1", "PNGDATA"); // only relay 2 has the file
b.fail["attachment/"] = 1; // and it fails once first
const bb = line([a, b]);
await hook(bb, "m3"); await settle(bb, "m3");
const save = async (c, id) => `${{id}}:${{c.name}}:${{(await c.read()).toString()}}`;
const first = await describe(bb.got[0].content, bb.got[0].id, save);
const again = await describe((await bb.message("m3")).content, "m3", save);
b.files.delete("at1");
const gone = await bb.download("at1").catch((e) => e);
a.down(); b.down();
const down = await bb.download("at1").catch((e) => e);
done({{ first, again, gone: [gone.message, permanent(gone)], down: [down.message, transient(down) ?? null, permanent(down)] }});
""")
    assert result["first"].startswith("(sent an attachment that could not be saved yet")
    assert result["again"] == "(sent an attachment, saved for Firstmate at m3:pic one.png:PNGDATA)"
    assert result["gone"][0].startswith("relay 2") and result["gone"][1] is True  # moves to the dead-letter folder
    assert result["down"] == ["no relay is reachable", "HTTP 503", False]  # the queue tries again later



@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_a_404_is_final_only_when_every_relay_answered_it():
    """A relay that is down, or whose body was cut off, may still have the file, so the queue must retry."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ permanent }} from {OUTBOX};
{FAKE_BB}
const a = relay(), b = relay(), c = relay(), d = relay();
const both = await line([a, b]).download("none").catch((e) => e);
b.down();
const oneDown = await line([a, b]).download("none").catch((e) => e);
c.files.set("big", "PNGDATA"); c.slow = 500;
const cutThen404 = await line([c, d], {{ downloadMs: 200 }}).download("big").catch((e) => e);
done({{ both: permanent(both), oneDown: [permanent(oneDown), oneDown.status], cutThen404: [permanent(cutThen404), cutThen404.status], secret: JSON.stringify([oneDown.message, cutThen404.message]).includes("pw-test") }});
""")
    assert result["both"] is True
    assert result["oneDown"] == [False, 503]
    assert result["cutThen404"] == [False, 503]
    assert not result["secret"]


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_download_has_its_own_timeout_and_a_cut_body_is_a_relay_error():
    """A body slower than callMs still arrives; one slower than downloadMs fails as a timeout the queue retries."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ permanent, transient }} from {OUTBOX};
{FAKE_BB}
const a = relay();
a.files.set("big", "PNGDATA"); a.slow = 500;
const patient = line([a], {{ callMs: 200, downloadMs: 3000 }});
const ok = (await patient.download("big")).toString();
const impatient = line([a], {{ callMs: 200, downloadMs: 200 }});
const cut = await impatient.download("big").catch((e) => e);
done({{ ok, cut: [cut.constructor.name, cut.message, transient(cut) ?? null, permanent(cut), cut.maybeSent], logs, secret: JSON.stringify([cut.message, logs]).includes("pw-test") }});
""")
    assert result["ok"] == "PNGDATA"
    name, message, kind, perm, maybe_sent = result["cut"]
    assert (name, kind, perm, maybe_sent) == ("RelayError", "TIMEOUT", False, False) and message.endswith("download interrupted after 200 ms")
    assert not result["secret"] and not [line for line in result["logs"] if " is down: " in line]

@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_fails_over_in_order_and_never_sends_twice():
    """A down relay is skipped in config order; a send whose answer is lost is not repeated on the next relay."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), b = relay(), c = relay();
const bb = line([a, b, c]);
a.down();
await bb.send(chat, "one relay down");
const downLogs = logs.filter((l) => l.startsWith("relay 1")).length;
a.start(); b.hang = true;
const ambiguous = line([b, c]);
await ambiguous.send(chat, "answer lost");
done({{
  a: a.sent.map((s) => s.message), b: b.sent.map((s) => s.message), c: c.sent.map((s) => s.message), downLogs,
  checked: [b, c].some((r) => r.calls.some((x) => x.startsWith("GET chat/"))), logs,
}});
""")
    assert result["a"] == []
    assert result["b"] == ["one relay down", "answer lost"]
    assert result["c"] == []  # a relay showed the lost-answer send as sent, so it was not sent again
    assert result["checked"]
    assert result["downLogs"] == 1


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_asks_the_relay_that_may_have_sent_even_when_it_is_marked_down():
    """A send that times out on relay 1 is checked on relay 1, not only on relay 2 whose iCloud copy lags; with no other relay, still."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), b = relay(), c = relay();
b.blind = true; // iCloud has not shown the text to relay 2 yet
a.hang = true;
const bb = line([a, b], {{ healthMs: 10_000 }});
await bb.send(chat, "slow to answer");
c.hang = true;
const solo = line([c], {{ healthMs: 10_000 }});
const since = Date.now();
const failed = await solo.send(chat, "only relay").then(() => false, () => true);
done({{ a: a.sent.map((s) => s.message), b: b.sent.map((s) => s.message), failed, later: await solo.sent(chat, "only relay", since) }});
""")
    assert result["a"] == ["slow to answer"]
    assert result["b"] == []
    assert result["failed"] and result["later"] == "sent-1"

@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_bluebubbles_outage_then_recovery():
    """With every relay down a send fails visibly and inbound waits; after recovery both work, each message once."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
{FAKE_BB}
const a = relay(), b = relay();
const bb = line([a, b]);
a.down(); b.down();
let failed = null;
try {{ await bb.send(chat, "during the outage"); }} catch (e) {{ failed = e.message; }}
await bb.catchUp();
a.messages.set("m4", text("m4", "sent while the relays were down")); b.messages.set("m4", a.messages.get("m4"));
b.start();
await bb.send(chat, "after the outage");
await bb.catchUp(); await hook(bb, "m4"); await settle(bb, "m4");
a.start();
await bb.catchUp(); await settle(bb, "m4");
done({{
  failed, b: b.sent.map((s) => s.message), got: bb.got.map((x) => x.content.text), logs,
  secret: logs.some((l) => l.includes("pw-test")) || (failed ?? "").includes("pw-test"),
}});
""")
    assert result["failed"] == "no relay is reachable"
    assert result["b"] == ["after the outage"]
    assert result["got"] == ["sent while the relays were down"]
    assert not result["secret"]
    down = [line for line in result["logs"] if " is down: " in line]
    assert len(down) == 2 and all(line.endswith("connection refused") for line in down)
    assert any(line.startswith("relay 2") and line.endswith("is back") for line in result["logs"])


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_transports_fail_over_to_bluebubbles_and_back():
    """Photon down: the bubble goes to the BlueBubbles line. Photon back: Photon again. An unsure error: no second send."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ failover }} from {DESK};
{FAKE_BB}
const a = relay(), bb = line([a]);
const photon = {{ state: "down", sent: [], async send(t) {{
  if (this.state === "down") throw Object.assign(new Error("UNAVAILABLE: [upstream] Service temporarily unavailable. Please retry."), {{ code: 14 }});
  if (this.state === "dropped") throw Object.assign(new Error("14 UNAVAILABLE: Connection dropped"), {{ code: 14 }});
  if (this.state === "unsure") throw new Error("DEADLINE_EXCEEDED: no answer");
  this.sent.push(t);
}} }};
const routes = [{{ name: "photon", send: (t) => photon.send(t) }}, {{ name: "bluebubbles", send: (t) => bb.send(chat, t) }}];
const lines = [], out = {{}};
out.down = await failover(routes, "while photon is down", (l) => lines.push(l));
photon.state = "up";
out.back = await failover(routes, "photon is back", (l) => lines.push(l));
photon.state = "unsure";
try {{ await failover(routes, "maybe sent", (l) => lines.push(l)); }} catch (e) {{ out.unsure = e.message; }}
photon.state = "dropped";
try {{ await failover(routes, "dropped", (l) => lines.push(l)); }} catch (e) {{ out.dropped = e.message; }}
a.down(); photon.state = "up";
out.relaysDown = await failover([routes[1], routes[0]], "relays down", (l) => lines.push(l)).catch((e) => e.message);
done({{ ...out, photon: photon.sent, relay: a.sent.map((s) => s.message), lines }});
""")
    assert result["down"] == "bluebubbles"
    assert result["back"] == "photon"
    assert result["unsure"].startswith("DEADLINE_EXCEEDED")
    assert result["dropped"].endswith("Connection dropped")  # a bare UNAVAILABLE can follow a write: no fallback send
    assert result["relaysDown"] == "photon"  # BlueBubbles first, no relay reachable: Photon takes it
    assert result["photon"] == ["photon is back", "relays down"]
    assert result["relay"] == ["while photon is down"]
    assert len(result["lines"]) == 2 and result["lines"][0].startswith("photon could not send (UNAVAILABLE")


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_inbound_from_both_transports_once_each():
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ inbound }} from {DESK};
{FAKE_BB}
const a = relay();
a.messages.set("g-shared", text("g-shared", "both lines saw this"));
a.messages.set("g-icloud", text("g-icloud", "only on the iCloud line"));
const bb = line([a]);
const photonQueue = [{{ id: "p-1", content: {{ type: "text", text: "on photon" }} }}, {{ id: "g-shared", content: {{ type: "text", text: "both lines saw this" }} }}];
const photon = {{ name: "photon", messages: (async function* () {{ for (const m of photonQueue) {{ await Bun.sleep(20); yield m; }} }})() }};
const blue = {{ name: "bluebubbles", messages: bb }};
const got = [];
(async () => {{ for await (const [l, m] of inbound([photon, blue])) got.push([l.name, m.id]); }})();
await Bun.sleep(5);
await hook(bb, "g-shared"); await hook(bb, "g-icloud"); await settle(bb, "g-icloud");
await Bun.sleep(80);
done({{ got }});
""")
    got = result["got"]
    assert sorted(m for _, m in got) == ["g-icloud", "g-shared", "p-1"]
    assert ["photon", "p-1"] in got and ["bluebubbles", "g-icloud"] in got


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_a_message_the_bridge_failed_to_handle_is_delivered_again():
    """A released message is not kept as seen, so the next catch-up queues it again; once handled, never again."""
    result = bun(f"""
import {{ BlueBubbles }} from {BB};
import {{ inbound }} from {DESK};
{FAKE_BB}
const a = relay();
a.messages.set("m1", text("m1", "retry me", {{ dateCreated: Date.now() - 60_000 }}));
const bb = new BlueBubbles([{{ url: a.url, password: a.password }}], mkdtempSync(`${{tmpdir()}}/bb-`), {{ pingMs: 200, healthMs: 0 }}, () => {{}});
const delivered = new Set(), got = [];
(async () => {{
  for await (const [, m] of inbound([{{ messages: bb }}], 1000, delivered)) {{
    got.push(m.id);
    if (got.length === 1) {{ delivered.delete(m.id); bb.release(m.id); }} else bb.markSeen(m.id);
  }}
}})();
for (let i = 0; i < 3; i++) {{ await bb.catchUp(); await Bun.sleep(20); }}
done({{ got }});
""")
    assert result["got"] == ["m1", "m1"]



def load_ship():
    spec = importlib.util.spec_from_file_location("ship_imessage", ROOT / "scripts/ship.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("change", "error"),
    [
        (lambda f: f["profiles"].update(firstmate=False, fleet_guards=False), "firstmate profile"),
        (lambda f: f["imessage"].update(owner="5550100"), "imessage.owner"),
        (lambda f: f["imessage"].pop("owner"), "imessage"),
    ],
)
def test_config_rejects_a_bridge_it_cannot_run(change, error):
    document = yaml.safe_load((ROOT / "config/default.yml").read_text())
    document["crewship"]["imessage"] = {"owner": "+10000000000"}
    load_ship().validate_config(document)
    change(document["crewship"])
    with pytest.raises(ValueError, match=error):
        load_ship().validate_config(document)


@pytest.mark.parametrize(
    "change",
    [
        lambda b: b.pop("relays"),
        lambda b: b.update(relays=[]),
        lambda b: b["relays"][0].update(url="http://a:1234,b"),
        lambda b: b["relays"][0].update(url="http://a:1234/?password=x"),
        lambda b: b["relays"][0].update(password_env="lower"),
        lambda b: b.pop("webhook_listen"),
        lambda b: b.clear(),
    ],
)
def test_config_takes_a_bluebubbles_relay_set(change):
    document = yaml.safe_load((ROOT / "config/default.yml").read_text())
    relays = [{"url": "http://relay-a:1234"}, {"url": "https://relay-b/bb/", "password_env": "RELAY_B_PASSWORD"}]
    document["crewship"]["imessage"] = {
        "owner": "+10000000000",
        "transports": ["photon", "bluebubbles"],
        "bluebubbles": {"relays": relays, "webhook_listen": "relay-net-address:8766"},
    }
    load_ship().validate_config(document)
    bluebubbles = document["crewship"]["imessage"]["bluebubbles"]
    change(bluebubbles)
    if not bluebubbles:
        document["crewship"]["imessage"].pop("bluebubbles")
    with pytest.raises(ValueError, match="imessage"):
        load_ship().validate_config(document)
OUTBOX = json.dumps(str(ROOT / "imessage/outbox.ts"))


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_upstream_errors_are_classified():
    """Outage errors are transient and labelled; only an item that is provably bad is permanent; the rest retry."""
    result = bun(f"""
import {{ brief, permanent, transient }} from {OUTBOX};
const err = (message, extra) => Object.assign(new Error(message), extra);
const codes = ["ETIMEDOUT", "ECONNRESET", "ECONNREFUSED", "EAI_AGAIN", "ENOTFOUND", "ENETUNREACH", "EHOSTUNREACH", "EPIPE"];
const cases = [
  err("/photon.imessage.v1.MessageService/Send UNAVAILABLE: [upstream] Service temporarily unavailable. Please retry.", {{ code: 14 }}),
  err("[upstream] Service temporarily unavailable. Please retry.", {{ grpcCode: 14 }}),
  err("Bad Gateway", {{ status: 502 }}),
  err("Service Unavailable", {{ status: 503 }}),
  err("Gateway Timeout", {{ status: 504 }}),
  err("send failed", {{ cause: err("down", {{ grpcCode: 14 }}) }}),
  Object.assign(new Error("The operation timed out"), {{ name: "TimeoutError" }}),
  ...codes.map((code) => err(`connect ${{code}}`, {{ code }})),
  err("deadline", {{ grpcCode: 4 }}),
  err("fetch failed", {{ cause: err("socket hang up") }}),
  err("The socket connection was closed unexpectedly"),
  err("bad request", {{ code: "UND_ERR_INVALID_ARG" }}),
  err("Internal Server Error", {{ status: 500 }}),
  err("Too Many Requests", {{ status: 429 }}),
  err("internal", {{ grpcCode: 13 }}),
  err("resource exhausted", {{ grpcCode: 8 }}),
  err("Target not allowed for this project", {{ grpcCode: 7 }}),
  err("something odd"),
  "unavailable",
  err("message m1 not found"),
  err("send failed", {{ cause: err("x", {{ status: 404 }}) }}),
  err("Gone", {{ status: 410 }}),
  err("The attachment has expired"),
  err("bad argument", {{ grpcCode: 3 }}),
  err("Unprocessable", {{ status: 422 }}),
  err("token expired", {{ status: 401 }}),
  err("unreadable", {{ permanent: true }}),
  err("message m1 not found", {{ status: 503 }}),
];
console.log(JSON.stringify({{
  codes: cases.map((e) => transient(e) ?? null),
  permanent: cases.map(permanent),
  line: brief(err("first\\nsecond", {{ grpcCode: 14 }})),
}}));
""")
    outage = ["UNAVAILABLE", "UNAVAILABLE", "HTTP 502", "HTTP 503", "HTTP 504", "UNAVAILABLE"] + ["TIMEOUT"] * 12
    assert result["codes"] == outage + [None] * 16 + ["HTTP 503"]
    assert result["permanent"] == [False] * 26 + [True] * 6 + [False] + [True] + [False]
    assert result["line"] == "UNAVAILABLE: first"


@pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")
def test_queue_moves_only_provably_bad_items_to_the_dead_letter_folder(tmp_path):
    """Outage and unknown errors retry the same item in order; a bad item or a corrupt file never blocks the rest."""
    queue = tmp_path / "queue"
    queue.mkdir()
    for n, text in enumerate(['{"v":"bad"}', "{not json", '{"v":"flaky"}', '{"v":"odd"}', '{"v":"denied"}', '{"v":"ok"}'], 1):
        (queue / f"{n}.json").write_text(text)
    result = bun(f"""
import {{ readdirSync }} from "node:fs";
import {{ Queue }} from {OUTBOX};
const done = [], lost = [], tries = {{}};
const fail = {{
  bad: () => new Error("message m1 not found"),
  flaky: () => Object.assign(new Error("down"), {{ grpcCode: 14 }}),
  odd: () => Object.assign(new Error("Internal Server Error"), {{ status: 500 }}),
  denied: () => Object.assign(new Error("permission denied"), {{ grpcCode: 7 }}),
}};
const q = new Queue({json.dumps(str(queue))}, "item", async (item) => {{
  tries[item.v] = (tries[item.v] ?? 0) + 1;
  if (item.v in fail && (item.v === "bad" || tries[item.v] < 3)) throw fail[item.v]();
  done.push(item.v);
}}, 5, (item) => lost.push(item));
const end = Date.now() + 10000;
while (done.length < 4 && Date.now() < end) await Bun.sleep(10);
console.log(JSON.stringify({{ done, lost, tries, left: readdirSync({json.dumps(str(queue))}), dead: readdirSync({json.dumps(str(queue) + "-dead")}).length }}));
process.exit(0);
""")
    assert result["done"] == ["flaky", "odd", "denied", "ok"]
    assert result["tries"] == {"bad": 1, "flaky": 3, "odd": 3, "denied": 3, "ok": 1}
    assert result["left"] == [] and result["dead"] == 2
    assert result["lost"] == [{"v": "bad"}]  # told of the parsed item only, not of the corrupt file


# A fake spectrum-ts for bridge.ts. Its state is in FAKE_DIR, so it outlives a bridge restart: `down` holds how
# many more upstream calls fail with UNAVAILABLE, typing always fails while `typing-down` exists, `inbound/` holds
# the owner's messages for the bridge to receive, `edits/` holds the line's raw message.edited events, `calls` logs
# every call, and `sent` logs each delivered message.
FAKE_UPSTREAM = """
import { appendFileSync, existsSync, readdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
const dir = process.env.FAKE_DIR;
const unavailable = () => Object.assign(new Error("[upstream] Service temporarily unavailable. Please retry."), { name: "ConnectionError", grpcCode: 14 });
function call(op) {
  const left = Number(readFileSync(`${dir}/down`, "utf8"));
  appendFileSync(`${dir}/calls`, `${op} ${left > 0 ? "UNAVAILABLE" : "ok"}\\n`);
  if (op === "send" && existsSync(`${dir}/send-unsure`)) throw Object.assign(new Error("write timed out"), { grpcCode: 4 });
  if (op === "last" && existsSync(`${dir}/read-timeout`)) throw Object.assign(new Error("read timed out"), { grpcCode: 4 });
  if (op === "status" && existsSync(`${dir}/status-down`)) throw unavailable();
  if (left > 0) {
    writeFileSync(`${dir}/down`, String(left - 1));
    throw unavailable();
  }
}
async function typing() {
  appendFileSync(`${dir}/calls`, "typing UNAVAILABLE\\n");
  if (existsSync(`${dir}/typing-down`)) throw unavailable();
}
const lastFile = (chat) => `${dir}/last-${encodeURIComponent(chat)}`;
function sent(line, chat) {
  appendFileSync(`${dir}/sent`, `${line}\\n`);
  if (chat) writeFileSync(lastFile(chat), crypto.randomUUID());
}
const load = (id) => message(JSON.parse(readFileSync(`${dir}/messages/${id}.json`, "utf8")));
function space(id) {
  return {
    id,
    startTyping: typing,
    stopTyping: typing,
    async send(text) { call("send"); sent(`send ${text}`, id); },
    async getMessage(mid) { call("getMessage"); return existsSync(`${dir}/messages/${mid}.json`) ? load(mid) : undefined; },
  };
}
function message(m) {
  return {
    id: m.id, direction: "inbound", sender: { id: m.sender }, space: space(m.space), timestamp: m.at ? new Date(m.at) : undefined,
    content: m.name
      ? { type: "attachment", name: m.name, async read() { call("download"); return new TextEncoder().encode(m.data); } }
      : m.content ?? { type: "text", text: m.text },
    async react(emoji) { call("react"); sent(`react ${m.id} ${emoji}`); },
    async reply(text) { call("reply"); sent(`reply ${m.id} ${text}`, m.space); },
    async read() {},
  };
}
async function* messages() {
  for (;;) {
    for (const f of readdirSync(`${dir}/inbound`).sort()) {
      renameSync(`${dir}/inbound/${f}`, `${dir}/messages/${f}`);
      const next = load(f.replace(/\\.json$/, ""));
      writeFileSync(lastFile(next.space.id), next.id);
      yield ["imessage", next];
    }
    await Bun.sleep(20);
  }
}
// The line's own client, which spectrum-ts keeps in its internals; its message events include edits.
async function* lineEvents() {
  for (;;) {
    for (const f of readdirSync(`${dir}/edits`).sort()) {
      const event = JSON.parse(readFileSync(`${dir}/edits/${f}`, "utf8"));
      renameSync(`${dir}/edits/${f}`, `${dir}/seen-${f}`);
      yield event;
    }
    await Bun.sleep(20);
  }
}
const line = {
  messages: {
    subscribeEvents: lineEvents,
    async sendText(chat, text, options = {}) {
      const key = `${dir}/receipt-${encodeURIComponent(options.clientMessageId ?? crypto.randomUUID())}`;
      if (existsSync(key)) return JSON.parse(readFileSync(key, "utf8"));
      call("send");
      const m = { guid: crypto.randomUUID(), isFromMe: true, chatGuids: [chat], isDelivered: true, sendErrorCode: 0 };
      sent(options.replyTo ? `reply ${options.replyTo} ${text}` : `send ${text}`, chat);
      appendFileSync(`${dir}/send-targets`, `${chat}\\n`);
      writeFileSync(key, JSON.stringify(m));
      writeFileSync(`${dir}/status-${m.guid}.json`, JSON.stringify(m));
      return m;
    },
    async get(id) {
      call("status");
      const m = JSON.parse(readFileSync(`${dir}/status-${id}.json`, "utf8"));
      if (existsSync(`${dir}/delivery-pending`)) m.isDelivered = false;
      if (existsSync(`${dir}/wrong-chat`)) m.chatGuids = ["wrong-chat"];
      if (existsSync(`${dir}/delivery-error`)) m.sendErrorCode = 42;
      return m;
    },
  },
  chats: { async get(chat) {
    call("last");
    const file = lastFile(chat);
    return { lastMessage: existsSync(file) ? { guid: readFileSync(file, "utf8") } : undefined };
  } },
};
export const Spectrum = async () => {
  if (existsSync(`${dir}/spectrum-down`)) throw new Error("spectrum did not start");
  return { messages: messages(), __internal: { platforms: new Map([["imessage", { client: existsSync(`${dir}/raw-missing`) ? [] : [{ client: line }] }]]) } };
};
export const imessage = Object.assign(() => ({ space: { get: async (id) => space(id) } }), { config: () => ({}) });
"""


def wait_for(check, what, timeout=30):
    end = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < end, f"timed out waiting for {what}"
        time.sleep(0.05)


def publish_json(path, record):
    pending = path.parent.parent / path.name
    pending.write_text(json.dumps(record))
    pending.replace(path)


def fake_bridge(tmp_path):
    """bridge.ts against the fake spectrum-ts: the fake's directory, the state directory, the notes file, and
    start(n), inbound(mid, ...), cli(*args) and text(path) helpers."""
    app, fake, state, bin_dir = (tmp_path / d for d in ("app", "fake", "state", "bin"))
    shutil.copytree(ROOT / "imessage", app, ignore=shutil.ignore_patterns("fm-*"))
    pkg = app / "node_modules/spectrum-ts"
    pkg.mkdir(parents=True)
    exports = {".": "./index.js", "./providers/imessage": "./index.js"}
    (pkg / "package.json").write_text(json.dumps({"name": "spectrum-ts", "type": "module", "exports": exports}))
    (pkg / "index.js").write_text(FAKE_UPSTREAM)
    for d in (fake / "inbound", fake / "messages", fake / "edits", bin_dir):
        d.mkdir(parents=True)
    (fake / "down").write_text("0")
    (fake / "typing-down").touch()
    notes = tmp_path / "notes"
    stubs = {
        "omp": f'cat >/dev/null; [ -e {fake / "desk-on"} ] && echo "desk ok" || echo SKIP',
        "fm-inbox": f'printf "%s\\n" "$*" >> {notes}; [ "$1" != note ] || [ ! -e {fake / "inbox-fail"} ]',
    }
    for name, body in stubs.items():
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "FM_HOME": str(tmp_path),
        "FM_INBOX_CMD": str(bin_dir / "fm-inbox"),
        "FM_IMESSAGE_OWNER": "+10000000000",
        "FM_IMESSAGE_PORT": str(port),
        "FM_IMESSAGE_RETRY_MS": "20",
        "PHOTON_PROJECT_ID": "fake",
        "PHOTON_PROJECT_SECRET": "fake",
        "STATE_DIRECTORY": str(state),
    }
    out, err = tmp_path / "out", tmp_path / "err"
    text = lambda p: p.read_text() if p.exists() else ""  # noqa: E731

    def start(n):
        with out.open("a") as o, err.open("a") as e:
            bridge = subprocess.Popen(["bun", "bridge.ts"], cwd=app, env=env, stdout=o, stderr=e)
        wait_for(lambda: text(out).count("listening") == n, f"bridge start {n}")
        return bridge

    def inbound(mid, **fields):
        record = {"id": mid, "space": "chat-1", "sender": "+10000000000", **fields}
        publish_json(fake / "inbound" / f"{mid}.json", record)
        wait_for(lambda: f"photon-{mid} " in text(notes), f"the note for {mid}")

    def cli(*args):
        result = subprocess.run([str(SEND), *args], capture_output=True, text=True, env=env, timeout=30)
        assert result.returncode == 0, result.stderr
        return result.stdout

    return fake, state, notes, err, start, inbound, cli, text


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_bridge_reply_threads_only_across_later_bubbles(tmp_path):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    bridge = start(1)
    try:
        inbound("m1", text="first text")
        cli("--reply", "1", "immediate answer")
        wait_for(lambda: text(fake / "sent"), "the immediate answer")
        assert text(fake / "sent").splitlines() == ["send immediate answer"]
        cli("--reply", "1", "after our bubble\n\nsecond")
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 3, "the separated answer")
        assert text(fake / "sent").splitlines()[1:] == ["reply m1 after our bubble", "send second"]
        inbound("m2", text="another target")
        inbound("m3", text="later owner bubble")
        cli("--reply", "2", "after his bubble")
        cli("--no-thread", "--reply", "2", "forced plain")
        cli("--reply", "2", "--no-thread", "forced plain again")
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 6, "the owner separation and opt-outs")
        assert text(fake / "sent").splitlines()[3:] == [
            "reply m2 after his bubble", "send forced plain", "send forced plain again",
        ]
        inbound("m4", content={"type": "reply", "content": {"type": "text", "text": "thread text"},
                               "target": {"content": {"type": "text", "text": "first text"}}})
        cli("plain by default")
        wait_for(lambda: "send plain by default" in text(fake / "sent"), "the plain answer to a thread reply")
        bridge.terminate()
        bridge.wait(10)
        bridge = start(2)
        inbound("m5", text="after restart")
        cli("--reply", "1", "adjacent after restart")
        wait_for(lambda: "send adjacent after restart" in text(fake / "sent"), "the adjacent restored answer")
        cli("--reply", "1", "separated after restart")
        wait_for(lambda: "reply m5 separated after restart" in text(fake / "sent"), "the separated restored answer")
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_reply_does_not_count_a_bubble_in_another_chat(tmp_path):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    bridge = start(1)
    try:
        inbound("m1", text="target")
        inbound("m2", text="another chat", space="chat-2")
        cli("--reply", "2", "adjacent in the target chat")
        wait_for(lambda: text(fake / "sent"), "the same-chat check")
        assert text(fake / "sent").splitlines() == ["send adjacent in the target chat"]
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_cli_delimiter_preserves_payload_and_thread_selection(tmp_path):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    bridge = start(1)
    try:
        inbound("m1", text="earlier")
        inbound("m2", content={"type": "reply", "content": {"type": "text", "text": "yes"},
                               "target": {"content": {"type": "text", "text": "earlier"}}})
        payload = "- first item\n- second item\n--typing"
        cases = [
            ([], "send"),
            (["--reply", "1"], "reply m2"),
            (["--reply", "2"], "reply m1"),
            (["--no-thread"], "send"),
            (["--reply", "2", "--no-thread"], "send"),
            (["--no-thread", "--reply", "2"], "send"),
        ]
        expected = ""
        for options, prefix in cases:
            cli(*options, "--", payload)
            expected += f"{prefix} {payload}\n"
            wait_for(lambda: text(fake / "sent") == expected, "the dash-leading list")
        inbound("m3", text="plain latest")
        cli("--", payload)
        expected += f"send {payload}\n"
        wait_for(lambda: text(fake / "sent") == expected, "the plain latest list")
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_bridge_rides_out_an_upstream_outage(tmp_path):
    """Sends, a tapback and an attachment outlive an UNAVAILABLE outage and a restart, then arrive in order."""
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    bridge = start(1)
    try:
        inbound("m1", text="you there")
        (fake / "down").write_text("1000000")  # the outage begins
        assert cli("one\n\ntwo").startswith("queued 2 bubble(s)")
        assert cli("--react", "👍").startswith("queued tapback")
        assert cli("--reply", "1", "three").startswith("queued 1 bubble(s)")
        cli("--typing")
        inbound("m2", name="photo.jpg", data="JPEG")
        assert "could not be saved yet" in text(notes)
        wait_for(lambda: "outbox item 1 failed (try 2)" in text(err), "an outbox retry")
        wait_for(lambda: "attachment download 1 failed (try 2)" in text(err), "a download retry")
        bridge.terminate()  # a restart in the middle of the outage
        bridge.wait(10)
        assert len(list((state / "outbox").glob("*.json"))) == 3
        assert len(list((state / "downloads").glob("*.json"))) == 1
        bridge = start(2)
        cli("four")
        inbound("m5", name="gone.jpg", data="X")  # its download is queued behind m2, then the message disappears upstream
        (fake / "messages" / "m5.json").unlink()
        (fake / "desk-on").touch()
        inbound("m3", text="ping")
        inbound("m4", text="ping again")  # nobody answers, so the desk writes a late ack into the queue
        wait_for(lambda: len(list((state / "outbox").glob("*.json"))) == 5, "the desk item in the outbox")
        (fake / "down").write_text("3")  # three more failures, then the upstream recovers
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 6 and "photon-m2-saved" in text(notes), "recovery")
        wait_for(lambda: "photon-m5-lost" in text(notes), "the note for the lost attachment")
        (fake / "messages" / "m3.json").unlink()  # the text that a threaded send points to is gone
        cli("--reply", "2", "five")
        wait_for(lambda: len(text(fake / "sent").splitlines()) == 7 and not list((state / "outbox").glob("*.json")), "the unthreaded send, delivered and dequeued")
    finally:
        bridge.terminate()
        bridge.wait(10)
    sent = ["send one", "send two", "react m1 👍", "reply m1 three", "send four", "send desk ok", "send five"]
    assert text(fake / "sent").splitlines() == sent
    assert "typing UNAVAILABLE" in text(fake / "calls")
    saved = state / "attachments/m2-photo.jpg"
    assert saved.read_text() == "JPEG"
    assert f"(an earlier attachment is saved now) (sent an attachment, saved for Firstmate at {saved})" in text(notes)
    assert list((state / "outbox").glob("*.json")) == [] and list((state / "downloads").glob("*.json")) == []
    logs = text(err)
    assert "UNAVAILABLE" in logs and not re.search(r"^\s+at ", logs, re.M), logs


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_bridge_files_his_edits_as_new_notes(tmp_path):
    """An edit of his text wakes Firstmate with a new note that carries the old text; other edits file nothing."""
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)

    def edit(seq, mid, new, **fields):
        event = {"type": "message.edited", "sequence": seq, "messageGuid": mid, "content": {"text": new},
                 "chatGuid": "any;-;+10000000000", "isFromMe": False, **fields}
        publish_json(fake / "edits" / f"{seq:03}.json", event)

    bridge = start(1)
    try:
        inbound("m1", text="adding a memory")
        edit(1, "m1", "adding a member")
        edit(2, "m1", "member")  # a second edit is compared with the first
        edit(3, "m1", "hijack", chatGuid="any;-;+19999999999")  # someone else's conversation
        edit(4, "m1", "mine", isFromMe=True)  # the line's own edit
        edit(5, "m9", "late")  # a text the bridge never saw
        wait_for(lambda: "photon-m9-edit-5 " in text(notes), "the note for the last edit")
    finally:
        bridge.terminate()
        bridge.wait(10)
    head = "[iMessage from the owner; answer with fm-imessage]"
    assert [line for line in text(notes).splitlines() if "[edited]" in line] == [
        f"note --request-id photon-m1-edit-1 -- {head} [edited] adding a member (was: adding a memory)",
        f"note --request-id photon-m1-edit-2 -- {head} [edited] member (was: adding a member)",
        f"note --request-id photon-m9-edit-5 -- {head} [edited] late (was: not known: the bridge did not see the text before the edit)",
    ]


# A fake BlueBubbles relay for a whole-bridge test: it logs each send to FAKE_DIR/relay-sent (a text as
# "<chat> <text>", a tapback as "react <message> <name>") and serves the messages in FAKE_DIR/relay/<guid>.json. While
# FAKE_DIR/relay-mode holds "garbled", a send is taken but the answer is unreadable and the sent-texts query fails; while
# it holds "lost", the answer is unreadable and the send never arrived; while it holds "hold-query", a message query waits
# for FAKE_DIR/query-go. A message query returns the messages in FAKE_DIR/relay newer than its `after`.
FAKE_RELAY = """
import { appendFileSync, existsSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { Database } from "bun:sqlite";
const db = new Database(":memory:");
db.run("CREATE TABLE message (payload TEXT, chatGuid TEXT, associated_message_guid TEXT, dateCreated INTEGER)");
const dir = process.env.FAKE_DIR;
const mode = () => (existsSync(`${dir}/relay-mode`) ? readFileSync(`${dir}/relay-mode`, "utf8").trim() : "");
const history = () => {
  const outgoing = existsSync(`${dir}/relay-history`) ? readFileSync(`${dir}/relay-history`, "utf8").trim().split("\\n").map((l) => JSON.parse(l)) : [];
  const incoming = readdirSync(`${dir}/relay`).map((f) => JSON.parse(readFileSync(`${dir}/relay/${f}`, "utf8")));
  return [...incoming, ...outgoing];
};
const server = Bun.serve({ port: 0, async fetch(req) {
  const u = new URL(req.url), path = u.pathname.replace("/api/v1/", "");
  if (u.searchParams.get("password") !== "pw-test") return new Response("no", { status: 401 });
  if (path === "server/info") return Response.json({ data: { private_api: !existsSync(`${dir}/no-private-api`), helper_connected: true } });
  if (path === "message/text") {
    const b = await req.json();
    appendFileSync(`${dir}/relay-payloads`, `${JSON.stringify(b)}\\n`);
    if (mode() === "send-down") return new Response("unavailable", { status: 503 });
    if (mode() === "lost") return new Response("garbled");
    appendFileSync(`${dir}/relay-sent`, `${b.chatGuid} ${b.message}\\n`);
    const m = { guid: b.tempGuid, text: b.message, isFromMe: true, isDelivered: true, dateCreated: Date.now(), chats: [{ guid: b.chatGuid }] };
    appendFileSync(`${dir}/relay-history`, `${JSON.stringify(m)}\\n`);
    return mode() === "garbled" ? new Response("garbled") : Response.json({ data: m });
  }
  if (path === "message/react") {
    const b = await req.json();
    appendFileSync(`${dir}/relay-sent`, `react ${b.selectedMessageGuid} ${b.reaction}\\n`);
    return Response.json({ data: {} });
  }
  if (/^chat\\/[^/]+\\/message$/.test(path)) {
    if (mode() === "garbled") return new Response("down", { status: 500 });
    if (u.searchParams.has("after")) {
      const chat = decodeURIComponent(path.split("/")[1]);
      return Response.json({ data: history().filter((m) => m.isFromMe && m.chats.some((c) => c.guid === chat)) });
    }
    if (mode() === "last-404") return new Response("chat not found", { status: 404 });
    const chat = decodeURIComponent(path.split("/")[1]);
    const recent = history().filter((m) => m.chats.some((c) => c.guid === chat)).sort((a, b) => b.dateCreated - a.dateCreated);
    return Response.json({ data: recent.slice(0, Number(u.searchParams.get("limit") || 50)) });
  }
  if (path === "message/query") {
    const b = await req.json();
    if (b.chatGuid) {
      if (mode() === "last-404") return new Response("chat not found", { status: 404 });
      db.run("DELETE FROM message");
      for (const m of history()) for (const chat of m.chats) {
        db.query("INSERT INTO message VALUES (?, ?, ?, ?)").run(JSON.stringify(m), chat.guid, m.associatedMessageGuid ?? null, m.dateCreated);
      }
      const where = (b.where ?? []).map((w) => `AND (${w.statement})`).join(" ");
      const rows = db.query(`SELECT payload FROM message WHERE chatGuid = ? ${where} ORDER BY dateCreated DESC LIMIT ?`).all(b.chatGuid, b.limit);
      return Response.json({ data: rows.map((r) => JSON.parse(r.payload)) });
    }
    while (mode() === "hold-query" && !existsSync(`${dir}/query-go`)) await Bun.sleep(20);
    const found = readdirSync(`${dir}/relay`).map((f) => JSON.parse(readFileSync(`${dir}/relay/${f}`, "utf8"))).filter((m) => m.dateCreated > b.after);
    return Response.json({ data: found });
  }
  const m = path.match(/^message\\/([^/]+)$/);
  if (m && existsSync(`${dir}/relay/${m[1]}.json`)) return Response.json({ data: JSON.parse(readFileSync(`${dir}/relay/${m[1]}.json`, "utf8")) });
  if (m) {
    if (mode() === "status-down") return new Response("status unavailable", { status: 503 });
    const found = history().find((x) => x.guid === m[1]);
    if (found) return Response.json({ data: { ...found, isDelivered: mode() !== "pending",
      chats: mode() === "wrong-chat" ? [{ guid: "wrong-chat" }] : found.chats, error: mode() === "delivery-error" ? 42 : 0 } });
  }
  if (m) return new Response("message not found", { status: 404 });
  return Response.json({ data: null });
} });
writeFileSync(`${dir}/relay-port`, String(server.port));
"""


def read_text(path):
    return path.read_text() if path.exists() else ""


class FallbackRig:
    """The bridge on the photon and bluebubbles transports, over the fake spectrum-ts and a fake relay. It restarts."""

    def __init__(self, tmp_path, **env):
        self.app, self.fake, self.state, bin_dir = (tmp_path / d for d in ("app", "fake", "state", "bin"))
        shutil.copytree(ROOT / "imessage", self.app, ignore=shutil.ignore_patterns("fm-*"))
        pkg = self.app / "node_modules/spectrum-ts"
        pkg.mkdir(parents=True)
        exports = {".": "./index.js", "./providers/imessage": "./index.js"}
        (pkg / "package.json").write_text(json.dumps({"name": "spectrum-ts", "type": "module", "exports": exports}))
        (pkg / "index.js").write_text(FAKE_UPSTREAM)
        for d in (self.fake / "inbound", self.fake / "messages", self.fake / "relay", bin_dir):
            d.mkdir(parents=True)
        (self.fake / "down").write_text("0")
        self.notes = tmp_path / "notes"
        for name, body in {"omp": "cat >/dev/null; echo SKIP", "fm-inbox": f'printf "%s\\n" "$*" >> {self.notes}'}.items():
            (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
            (bin_dir / name).chmod(0o755)
        ports = []
        for _ in range(2):
            with socket.socket() as s:
                s.bind(("127.0.0.1", 0))
                ports.append(s.getsockname()[1])
        self.hook_port = ports[1]
        self.env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(self.fake)}
        self.relay = subprocess.Popen(["bun", "-e", FAKE_RELAY], env=self.env)
        wait_for(lambda: read_text(self.fake / "relay-port"), "the fake relay")
        self.env |= {
            "FM_HOME": str(tmp_path),
            "FM_INBOX_CMD": str(bin_dir / "fm-inbox"),
            "FM_IMESSAGE_OWNER": "+10000000000",
            "FM_IMESSAGE_PORT": str(ports[0]),
            "FM_IMESSAGE_RETRY_MS": "20",
            "FM_IMESSAGE_TRANSPORTS": "photon bluebubbles",
            "FM_BLUEBUBBLES_RELAYS": f"http://127.0.0.1:{read_text(self.fake / 'relay-port')},RELAY_PASSWORD",
            "FM_BLUEBUBBLES_WEBHOOK": f"127.0.0.1:{ports[1]}",
            "RELAY_PASSWORD": "pw-test",
            "PHOTON_PROJECT_ID": "fake",
            "PHOTON_PROJECT_SECRET": "fake",
            "STATE_DIRECTORY": str(self.state),
            **env,
        }
        self.out, self.err = tmp_path / "out", tmp_path / "err"
        self.starts = 0
        self.bridge = None

    def start(self):
        self.starts += 1
        with self.out.open("a") as o, self.err.open("a") as e:
            self.bridge = subprocess.Popen(["bun", "bridge.ts"], cwd=self.app, env=self.env, stdout=o, stderr=e)
        wait_for(lambda: read_text(self.out).count("listening") == self.starts, "bridge start")

    def stop(self):
        if self.bridge:
            self.bridge.terminate()
            self.bridge.wait(10)
            self.bridge = None

    def close(self):
        self.stop()
        self.relay.terminate()
        self.relay.wait(10)

    def photon_down(self, down):
        (self.fake / "down").write_text("1000000" if down else "0")

    def relay_mode(self, mode):
        (self.fake / "relay-mode").write_text(mode)

    def cli(self, *args):
        result = subprocess.run([str(SEND), *args], capture_output=True, text=True, env=self.env, timeout=30)
        assert result.returncode == 0, result.stderr

    def photon_text(self, mid, text):
        record = {"id": mid, "space": "chat-1", "sender": "+10000000000", "text": text}
        publish_json(self.fake / "inbound" / f"{mid}.json", record)
        wait_for(lambda: f"photon-{mid} " in read_text(self.notes), f"the Photon note {mid}")

    def relay_message(self, guid, text, at, **fields):
        message = {"guid": guid, "text": text, "isFromMe": False, "dateCreated": at, "attachments": [],
                   "handle": {"address": "+10000000000"}, "chats": [{"guid": "iMessage;-;+10000000000"}], **fields}
        (self.fake / "relay" / f"{guid}.json").write_text(json.dumps(message))

    def relay_text(self, guid, text, at, **fields):
        self.relay_message(guid, text, at, **fields)
        hook = json.dumps({"type": "new-message", "data": {"guid": guid}})
        subprocess.run(["curl", "-sS", "-d", hook, f"http://127.0.0.1:{self.hook_port}/bluebubbles"], check=True, capture_output=True)
        wait_for(lambda: f"bluebubbles-{guid} " in read_text(self.notes), f"the BlueBubbles note {guid}")

    def outbox(self):
        return [json.loads(p.read_text()) for p in sorted((self.state / "outbox").glob("*.json"))]


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_reply_keeps_an_uncertain_fallback_queued_after_a_permanent_read_error(tmp_path):
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("p1", "on Photon")
        rig.relay_text("g1", "on BlueBubbles", int(time.time() * 1000))
        rig.relay_mode("last-404")
        (rig.fake / "send-unsure").touch()
        rig.cli("--reply", "1", "first\n\nsecond")
        wait_for(lambda: "outbox item 1 failed" in read_text(rig.err)
                 or list((rig.state / "outbox-dead").glob("*.json")), "the uncertain send result")
        assert not list((rig.state / "outbox-dead").glob("*.json"))
        assert rig.outbox()[0]["maybe"] == {"photon": "chat-1"}
        (rig.fake / "send-unsure").unlink()
        rig.relay_mode("")
        wait_for(lambda: "send second" in read_text(rig.fake / "sent"), "the queued remaining bubbles")
        assert read_text(rig.fake / "sent").splitlines() == ["send first", "send second"]
        assert not read_text(rig.fake / "relay-sent")
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_reply_read_timeout_uses_the_fallback_without_blocking_plain_sends(tmp_path):
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("p1", "the target")
        (rig.fake / "read-timeout").touch()
        rig.cli("--reply", "1", "fallback answer")
        rig.cli("plain behind it")
        wait_for(lambda: "fallback answer" in read_text(rig.fake / "relay-sent")
                 or "outbox item 1 failed" in read_text(rig.err), "the read-only failure result")
        assert "fallback answer" in read_text(rig.fake / "relay-sent")
        wait_for(lambda: "send plain behind it" in read_text(rig.fake / "sent"), "the unblocked plain send")
        wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "the completed fallback queue")
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_inbox_failure_notice_waits_without_the_raw_photon_client(tmp_path):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    (fake / "raw-missing").touch()
    (fake / "inbox-fail").touch()
    bridge = start(1)
    try:
        inbound("m1", text="the refused note")
        (fake / "inbox-fail").unlink()
        inbound("m2", text="the accepted note")
        cli("later response")
        wait_for(lambda: "outbox item 1 failed" in text(err), "the unavailable delivery client")
        assert not text(fake / "sent")
        assert len(list((state / "outbox").glob("*.json"))) == 2
    finally:
        bridge.terminate()
        bridge.wait(10)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_reply_does_not_count_a_bluebubbles_tapback_as_a_later_bubble(tmp_path):
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.relay_text("g1", "the target", int(time.time() * 1000))
        rig.relay_message("tapback", "", int(time.time() * 1000) + 1000,
                          associatedMessageGuid="g1", isFromMe=True)
        rig.cli("--reply", "1", "adjacent despite the tapback")
        wait_for(lambda: read_text(rig.fake / "relay-payloads"), "the tapback-only answer")
        payload = json.loads(read_text(rig.fake / "relay-payloads").splitlines()[0])
        assert payload["message"] == "adjacent despite the tapback"
        assert "selectedMessageGuid" not in payload and "partIndex" not in payload
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
@pytest.mark.parametrize("later", [None, "owner", "service"])
def test_smart_reply_orders_history_across_lagging_relays(tmp_path, later):
    rig = FallbackRig(tmp_path)
    second = tmp_path / "second-relay"
    (second / "relay").mkdir(parents=True)
    relay = subprocess.Popen(["bun", "-e", FAKE_RELAY], env={**rig.env, "FAKE_DIR": str(second)})
    try:
        wait_for(lambda: read_text(second / "relay-port"), "the second fake relay")
        rig.env["FM_BLUEBUBBLES_RELAYS"] += (
            f" http://127.0.0.1:{read_text(second / 'relay-port')},RELAY_PASSWORD"
        )
        rig.start()
        rig.photon_text("p1", "the plain route")
        at = int(time.time() * 1000)
        rig.relay_message("older", "older history", at - 1000)
        rig.relay_text("target", "the target", at)
        target = rig.fake / "relay/target.json"
        shutil.copy(target, second / "relay/target.json")
        if later is None:
            target.unlink()
        else:
            rig.relay_message("later", "a later bubble", at + 1000, isFromMe=later == "service")
            record = rig.fake / "relay/later.json"
            shutil.move(record, second / "relay/later.json")
            if later == "owner":
                hook = json.dumps({"type": "new-message", "data": {"guid": "later"}})
                subprocess.run(
                    ["curl", "-sS", "-d", hook, f"http://127.0.0.1:{rig.hook_port}/bluebubbles"],
                    check=True, capture_output=True,
                )
                wait_for(lambda: "bluebubbles-later " in read_text(rig.notes), "the later owner note")
        rig.relay_message("tapback", "", at + 2000, associatedMessageGuid="target", isFromMe=True)
        rig.relay_message("unrelated", "another chat", at + 3000,
                          chats=[{"guid": "iMessage;-;+19999999999"}])
        for guid in ("tapback", "unrelated"):
            shutil.copy(rig.fake / f"relay/{guid}.json", second / f"relay/{guid}.json")
        n = "2" if later == "owner" else "1"
        rig.cli("--reply", n, "--", "- the answer")
        wait_for(lambda: read_text(rig.fake / "relay-payloads"), "the multi-relay reply")
        payload = json.loads(read_text(rig.fake / "relay-payloads").splitlines()[0])
        assert payload["chatGuid"] == "iMessage;-;+10000000000"
        assert payload["message"] == "- the answer"
        if later is None:
            assert "selectedMessageGuid" not in payload
        else:
            assert payload["selectedMessageGuid"] == "target"
        rig.cli("--no-thread", "--reply", n, "--", "- forced plain")
        rig.cli("--reply", n, "--no-thread", "--", "- forced plain again")
        rig.cli("--", "- plain")
        wait_for(lambda: "- plain" in read_text(rig.fake / "relay-sent"), "the plain sends on the latest line")
        payloads = [json.loads(line) for line in read_text(rig.fake / "relay-payloads").splitlines()]
        assert [p["message"] for p in payloads] == ["- the answer", "- forced plain", "- forced plain again", "- plain"]
        assert all(p["chatGuid"] == "iMessage;-;+10000000000" for p in payloads)
        assert all("selectedMessageGuid" not in p for p in payloads[1:])
        assert not read_text(rig.fake / "sent")
    finally:
        rig.close()
        relay.terminate()
        relay.wait(10)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
@pytest.mark.parametrize("private_api", [True, False])
def test_bridge_smart_reply_uses_inbound_bluebubbles_transport(tmp_path, private_api):
    rig = FallbackRig(tmp_path)
    if not private_api:
        (rig.fake / "no-private-api").touch()
    try:
        rig.start()
        rig.photon_text("p1", "earlier on Photon")
        rig.relay_text("g1", "on BlueBubbles", int(time.time() * 1000))
        rig.cli("--reply", "1", "adjacent")
        wait_for(lambda: "adjacent" in read_text(rig.fake / "relay-sent"), "the adjacent BlueBubbles answer")
        rig.cli("--reply", "1", "after our bubble")
        wait_for(lambda: "after our bubble" in read_text(rig.fake / "relay-sent"), "the separated BlueBubbles answer")
        rig.relay_text("g2", "another target", int(time.time() * 1000))
        rig.relay_text("g3", "later owner bubble", int(time.time() * 1000))
        rig.cli("--reply", "2", "after his bubble")
        wait_for(lambda: "after his bubble" in read_text(rig.fake / "relay-sent"), "the later-owner BlueBubbles answer")
        payloads = [json.loads(line) for line in read_text(rig.fake / "relay-payloads").splitlines()]
        assert [p["message"] for p in payloads] == ["adjacent", "after our bubble", "after his bubble"]
        assert all(p["chatGuid"] == "iMessage;-;+10000000000" for p in payloads)
        assert "selectedMessageGuid" not in payloads[0]
        if private_api:
            assert [p["selectedMessageGuid"] for p in payloads[1:]] == ["g1", "g2"]
        else:
            assert all("selectedMessageGuid" not in p and "partIndex" not in p for p in payloads)
        assert not read_text(rig.fake / "sent")
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_bridge_falls_back_to_bluebubbles_and_back(tmp_path):
    """Photon down: queued bubbles go out on the BlueBubbles line. Photon back: Photon again. Both lines feed the inbox."""
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("m1", "you there")
        rig.photon_down(True)
        rig.cli("--reply", "1", "on the fallback")
        wait_for(lambda: read_text(rig.fake / "relay-sent"), "the fallback send")
        rig.photon_down(False)
        rig.cli("on photon again")
        wait_for(lambda: "send on photon again" in read_text(rig.fake / "sent"), "the Photon send")
        for _ in range(2):  # two relays, or one relay twice: one note
            rig.relay_text("g1", "from the icloud line", 1)
        wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "an empty outbox")
    finally:
        rig.close()
    assert read_text(rig.fake / "relay-sent").splitlines() == ["iMessage;-;+10000000000 on the fallback"]
    assert read_text(rig.fake / "sent").splitlines() == ["send on photon again"]
    assert read_text(rig.notes).count("bluebubbles-g1 ") == 1
    assert "photon could not send (" in read_text(rig.err) and "on the bluebubbles fallback" in read_text(rig.err)


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_a_text_that_may_be_out_on_one_line_is_not_sent_on_another_after_a_restart(tmp_path):
    """Photon is down, the relay takes the text but its answer is lost, then Photon is back: the text is not sent twice."""
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("m1", "you there")
        rig.photon_down(True)
        rig.relay_mode("garbled")
        rig.cli("--reply", "1", "once only")
        wait_for(lambda: read_text(rig.fake / "relay-sent"), "the relay send")
        wait_for(lambda: rig.outbox() and rig.outbox()[0].get("maybe"), "the unsure state in the outbox item")
        item = rig.outbox()[0]
        assert item["maybe"] == {"bluebubbles": "iMessage;-;+10000000000"} and item["since"] > 0 and item["guid"]
        rig.stop()
        rig.photon_down(False)
        rig.relay_mode("")
        rig.start()
        wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "the outbox to empty")
    finally:
        rig.close()
    assert read_text(rig.fake / "relay-sent").splitlines() == ["iMessage;-;+10000000000 once only"]
    assert read_text(rig.fake / "sent") == ""


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_a_text_that_may_be_out_on_photon_waits_while_photon_does_not_start(tmp_path):
    """The restart after an unsure Photon send finds Photon down: the bubble is not sent on BlueBubbles, and Photon sends it once later."""
    rig = FallbackRig(tmp_path)
    (rig.state / "outbox").mkdir(parents=True)
    item = {"space": "chat-1", "id": "m1", "bubbles": ["pinned"], "guid": "g-1", "maybe": {"photon": "chat-1"}, "since": 1}
    (rig.state / "outbox/1.json").write_text(json.dumps(item))
    (rig.fake / "spectrum-down").touch()
    try:
        rig.start()
        wait_for(lambda: "outbox item 1 failed (try 2)" in read_text(rig.err), "a retry while Photon is not running")
        assert read_text(rig.fake / "relay-sent") == "" and rig.outbox()[0]["maybe"] == {"photon": "chat-1"}
        rig.stop()
        (rig.fake / "spectrum-down").unlink()
        rig.start()
        wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "the outbox to empty")
    finally:
        rig.close()
    assert read_text(rig.fake / "relay-sent") == ""
    assert read_text(rig.fake / "sent").splitlines() == ["send pinned"]

@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_a_text_the_check_proves_not_sent_goes_out_once_on_photon(tmp_path):
    """The relay's answer is lost and the text never arrived: the retry's check says so, and Photon then sends it once."""
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("m1", "you there")
        rig.photon_down(True)
        rig.relay_mode("lost")
        rig.cli("--reply", "1", "once only")
        wait_for(lambda: rig.outbox() and rig.outbox()[0].get("maybe"), "the unsure state in the outbox item")
        rig.photon_down(False)
        wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "the outbox to empty")
    finally:
        rig.close()
    assert read_text(rig.fake / "relay-sent") == ""
    assert read_text(rig.fake / "sent").splitlines() == ["send once only"]

@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_a_stuck_tapback_is_dropped_and_the_sends_behind_it_go_out(tmp_path):
    """A tapback on a down transport moves to the dead-letter folder after its maximum age; later sends use the fallback."""
    rig = FallbackRig(tmp_path, FM_IMESSAGE_REACT_MAX_MS="300")
    try:
        rig.start()
        rig.photon_text("m1", "you there")
        rig.photon_down(True)
        rig.cli("--react", "👍")
        rig.cli("--reply", "1", "behind the tapback")
        wait_for(lambda: "behind the tapback" in read_text(rig.fake / "relay-sent"), "the send behind the tapback")
        wait_for(lambda: not list((rig.state / "outbox").glob("*.json")), "an empty outbox")
    finally:
        rig.close()
    dead = [json.loads(p.read_text()) for p in (rig.state / "outbox-dead").glob("*.json")]
    assert [d["react"] for d in dead] == ["👍"]
    assert "react" not in read_text(rig.fake / "sent")
    assert len(re.findall(r"tapback 👍 older than", read_text(rig.err))) == 1


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_a_restart_targets_his_newest_text_on_any_transport(tmp_path):
    """The tapback after a restart goes to the newest text, on the BlueBubbles line; an untimed latest file counts as oldest."""
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("m1", "on photon")
        rig.relay_text("g1", "later, on the icloud line", int(time.time() * 1000) + 5000)
        wait_for(lambda: (rig.state / "latest-bluebubbles").exists(), "the BlueBubbles latest file")
        rig.stop()
        (rig.state / "latest").write_text("chat-1\nm1\n")  # the format before the time was kept
        rig.start()
        rig.cli("--react", "❤️")
        wait_for(lambda: "react g1 love" in read_text(rig.fake / "relay-sent"), "the tapback on the newest text")
        rig.stop()
        (rig.state / "latest-bluebubbles").unlink()  # only the untimed file is left: it is used
        rig.start()
        rig.cli("--react", "👍")
        wait_for(lambda: "react m1 👍" in read_text(rig.fake / "sent"), "the tapback on the only text")
    finally:
        rig.close()
    assert "react m1 ❤️" not in read_text(rig.fake / "sent")


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_a_replayed_older_text_never_becomes_his_latest(tmp_path):
    """A BlueBubbles text whose webhook was lost is filed by the catch-up after a newer Photon text; the tapback still goes to Photon."""
    rig = FallbackRig(tmp_path)
    rig.relay_message("g1", "lost webhook, sent earlier", int(time.time() * 1000) - 5 * 60_000)
    rig.relay_mode("hold-query")
    try:
        rig.start()
        rig.photon_text("m1", "newer, on photon")
        (rig.fake / "query-go").touch()
        wait_for(lambda: "bluebubbles-g1 " in read_text(rig.notes), "the replayed BlueBubbles note")
        rig.cli("--react", "👍")
        wait_for(lambda: "react m1 👍" in read_text(rig.fake / "sent"), "the tapback on the Photon text")
    finally:
        rig.close()
    assert "react" not in read_text(rig.fake / "relay-sent")
    assert not (rig.state / "latest-bluebubbles").exists()
    assert read_text(rig.notes).count("bluebubbles-g1 ") == 1


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
@pytest.mark.parametrize("restart", [False, True])
def test_proactive_send_uses_the_latest_inbound_chat_and_transport(tmp_path, restart):
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("p1", "old chat")
        rig.relay_text("g1", "new chat", int(time.time() * 1000) + 1000,
                       chats=[{"guid": "iMessage;-;new-handle"}])
        wait_for(lambda: (rig.state / "latest-bluebubbles").exists(), "the latest chat")
        if restart:
            rig.stop()
            rig.start()
        rig.cli("daily schedule")
        wait_for(lambda: not rig.outbox(), "the confirmed schedule")
        assert read_text(rig.fake / "relay-sent").splitlines() == ["iMessage;-;new-handle daily schedule"]
        assert not read_text(rig.fake / "sent")
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_proactive_send_does_not_leave_the_latest_transport_during_an_outage(tmp_path):
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("p1", "old chat")
        rig.relay_text("g1", "new chat", int(time.time() * 1000) + 1000,
                       chats=[{"guid": "iMessage;-;new-handle"}])
        wait_for(lambda: (rig.state / "latest-bluebubbles").exists(), "the latest chat")
        rig.relay_mode("send-down")
        rig.cli("daily schedule")
        wait_for(lambda: "outbox item 1 failed" in read_text(rig.err), "the queued retry")
        assert rig.outbox() and not read_text(rig.fake / "sent")
        rig.relay_mode("")
        wait_for(lambda: not rig.outbox(), "the recovered schedule")
        assert read_text(rig.fake / "relay-sent").splitlines() == ["iMessage;-;new-handle daily schedule"]
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
@pytest.mark.parametrize("transport", ["photon", "bluebubbles"])
@pytest.mark.parametrize("failure", ["pending", "wrong-chat", "status-down"])
def test_delivery_confirmation_survives_a_restart_without_resending(tmp_path, transport, failure):
    rig = FallbackRig(tmp_path)
    marker = {"pending": "delivery-pending", "wrong-chat": "wrong-chat", "status-down": "status-down"}[failure]
    try:
        rig.start()
        rig.photon_text("p1", "old chat")
        if transport == "bluebubbles":
            rig.relay_text("g1", "new chat", int(time.time() * 1000) + 1000,
                           chats=[{"guid": "iMessage;-;new-handle"}])
            wait_for(lambda: (rig.state / "latest-bluebubbles").exists(), "the latest chat")
            rig.relay_mode(failure)
        else:
            (rig.fake / marker).touch()
        rig.cli("--reply", "1", "daily schedule")
        wait_for(lambda: rig.outbox() and rig.outbox()[0].get("receipt"), "the saved delivery receipt")
        wait_for(lambda: "outbox item 1 failed" in read_text(rig.err), "the unconfirmed delivery")
        memory = rig.state / "memory/main"
        assert "daily schedule" not in "".join(p.read_text() for p in memory.glob("*.jsonl"))
        receipt = rig.outbox()[0]["receipt"]
        rig.stop()
        rig.start()
        wait_for(lambda: "outbox item 1 failed (try 2)" in read_text(rig.err), "the restarted delivery check")
        assert rig.outbox()[0]["receipt"] == receipt
        if transport == "bluebubbles":
            rig.relay_mode("")
        else:
            (rig.fake / marker).unlink()
        wait_for(lambda: not rig.outbox(), "the confirmed delivery")
        assert "".join(p.read_text() for p in memory.glob("*.jsonl")).count("daily schedule") == 1
        sends = read_text(rig.fake / ("sent" if transport == "photon" else "relay-sent")).splitlines()
        assert len(sends) == 1 and sends[0].endswith("daily schedule")
        assert not read_text(rig.fake / ("relay-sent" if transport == "photon" else "sent"))
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
@pytest.mark.parametrize("transport", ["photon", "bluebubbles"])
def test_failed_delivery_is_reported_without_sent_memory(tmp_path, transport):
    rig = FallbackRig(tmp_path)
    try:
        rig.start()
        rig.photon_text("p1", "old chat")
        if transport == "bluebubbles":
            rig.relay_text("g1", "new chat", int(time.time() * 1000) + 1000)
            wait_for(lambda: (rig.state / "latest-bluebubbles").exists(), "the latest chat")
            rig.relay_mode("delivery-error")
        else:
            (rig.fake / "delivery-error").touch()
        rig.cli("failed schedule")
        wait_for(lambda: list((rig.state / "outbox-dead").glob("*.json")), "the reported delivery error")
        assert "failed schedule" not in "".join(p.read_text() for p in (rig.state / "memory/main").glob("*.jsonl"))
        assert "send error 42" in read_text(rig.err)
    finally:
        rig.close()


@pytest.mark.skipif(not (shutil.which("bun") and shutil.which("curl")), reason="needs bun and curl")
def test_proactive_send_uses_a_changed_photon_chat(tmp_path):
    fake, state, notes, err, start, inbound, cli, text = fake_bridge(tmp_path)
    bridge = start(1)
    try:
        inbound("m1", text="old handle")
        inbound("m2", space="chat-new-handle", text="new handle")
        cli("daily schedule")
        wait_for(lambda: not list((state / "outbox").glob("*.json")), "the confirmed schedule")
        assert text(fake / "send-targets").splitlines() == ["chat-new-handle"]
        assert text(fake / "sent").splitlines() == ["send daily schedule"]
    finally:
        bridge.terminate()
        bridge.wait(10)
