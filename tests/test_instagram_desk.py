"""The Instagram front desk (docs/imessage.md#instagram-front-desk): apps/imessage/instagram-desk.ts.

omp, the status command and fm-insta-reply are shell stand-ins that record their calls; the timing is real
(a short quiet period), so a test proves the desk's once-per-burst and stand-down behaviour end to end.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

DESK = json.dumps(str(Path(__file__).parents[1] / "apps/imessage/instagram-desk.ts"))

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def run(tmp_path, body, answer="hello there", omp_sleep=0, reply=None):
    """Run `body` (TypeScript) against a desk built on the stand-ins; return what it printed as JSON.

    In `body`: `desk`, `feed(source, row)` (fresh now), `wait(ms)`, `omp()` (desk calls so far, their stdin) and
    `sends()` (fm-insta-reply calls: its arguments and INSTAGRAM_DM_ACTOR), `log()` (desk.log lines).
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    (tmp_path / "answer").write_text(answer)
    stub = {
        "omp": f"""cat > "{tmp_path}/omp.$$"\nsleep {omp_sleep}\ncat "{tmp_path}/answer"\n""",
        "status": "echo fleet is quiet\n",
        "reply": reply or f"""printf '%s\\n' "$INSTAGRAM_DM_ACTOR|$*" >> "{tmp_path}/sends"\n""",
    }
    for name, script in stub.items():
        (bin_dir / name).write_text("#!/bin/sh\n" + script)
        (bin_dir / name).chmod(0o755)
    code = textwrap.dedent(f"""
        import {{ InstagramDesk, follow }} from {DESK};
        import {{ readdirSync, readFileSync, existsSync }} from "node:fs";
        const dir = {json.dumps(str(tmp_path / "state"))};
        const desk = new InstagramDesk({{
          dir, model: "m", owner: "Ana", supervisorModel: "", quietMs: 300, stopFile: {json.dumps(str(tmp_path / "stop"))},
          replyCmd: [{json.dumps(str(bin_dir / "reply"))}], statusCmd: [{json.dumps(str(bin_dir / "status"))}],
          env: {{ ...process.env, PATH: {json.dumps(str(bin_dir))} + ":" + process.env.PATH }},
          chat: () => ({{ say: async () => "x", end() {{}} }}),
        }});
        const now = () => Math.floor(Date.now() / 1000);
        const feed = (source, row) => desk.feed(source, {{ at: now(), thread: "T", ...row }}, true);
        const wait = (ms) => Bun.sleep(ms);
        const omp = () => readdirSync({json.dumps(str(tmp_path))}).filter((f) => f.startsWith("omp.")).map((f) => readFileSync({json.dumps(str(tmp_path))} + "/" + f, "utf8"));
        const sends = () => existsSync({json.dumps(str(tmp_path / "sends"))}) ? readFileSync({json.dumps(str(tmp_path / "sends"))}, "utf8").split("\\n").filter(Boolean) : [];
        const log = () => existsSync(dir + "/desk.log") ? readFileSync(dir + "/desk.log", "utf8").split("\\n").filter(Boolean).map((l) => l.split(" ").slice(2).join(" ")) : [];
        const out = {{}};
        {body}
        console.log(JSON.stringify(out));
        process.exit(0);
    """)
    result = subprocess.run(["bun", "-e", code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_one_desk_turn_per_burst_replies_through_fm_insta_reply(tmp_path):
    out = run(tmp_path, """
        feed("messages", { id: "a", text: "yo" });
        await wait(150);
        feed("messages", { id: "b", text: "you there?" });
        await wait(200);
        out.early = sends().length;                  // 150 ms after his second DM: still quiet
        await wait(1200);
        out.sends = sends(); out.prompts = omp(); out.log = log();
        feed("sent", { kind: "text", text: "hello there", by: "desk" });  // the desk's own send
        feed("messages", { id: "c", text: "ok" });
        await wait(1500);
        out.second = sends().length;
        out.memory = desk.memory.msgs.map((m) => `${m.kind}: ${m.text}`);
    """)
    assert out["early"] == 0
    assert out["sends"] == ["desk|--thread T -- hello there"]  # one turn for the burst, as the desk
    assert len(out["prompts"]) == 1
    assert "owner: yo\nowner: you there?" in out["prompts"][0] and "fleet is quiet" in out["prompts"][0]
    assert out["log"] == ["hello there"]
    assert out["second"] == 2  # the desk's own send does not stand it down for his next DM
    assert out["memory"] == ["owner: yo", "owner: you there?", "desk: hello there", "owner: ok"]


@pytest.mark.parametrize("action", [{"kind": "text", "text": "on it"}, {"kind": "react", "text": "x"}, {"kind": "typing"}])
def test_any_firstmate_action_stands_the_desk_down_for_the_burst(tmp_path, action):
    out = run(tmp_path, f"""
        feed("messages", {{ id: "a", text: "yo" }});
        await wait(100);
        feed("sent", {json.dumps({**action, "by": "firstmate"})});
        await wait(900);
        out.standDown = [omp().length, sends().length];
        feed("messages", {{ id: "b", text: "again" }});   // his next DM starts a new burst
        await wait(900);
        out.next = sends();
        out.memory = desk.memory.msgs.map((m) => m.kind);
    """)
    assert out["standDown"] == [0, 0]
    assert out["next"] == ["desk|--thread T -- hello there"]
    assert out["memory"][0] == "owner" and out["memory"][-1] == "owner"


def test_firstmate_answering_while_the_desk_drafts_drops_the_draft(tmp_path):
    out = run(tmp_path, """
        feed("messages", { id: "a", text: "yo" });
        await wait(500);                              // quiet period over, omp is sleeping
        out.drafting = omp().length;
        feed("sent", { kind: "typing", by: "firstmate" });
        await wait(2000);
        out.sends = sends(); out.log = log();
    """, omp_sleep=1)
    assert out["drafting"] == 1
    assert out["sends"] == [] and out["log"] == []


def test_a_new_dm_while_the_desk_drafts_restarts_the_wait(tmp_path):
    out = run(tmp_path, """
        feed("messages", { id: "a", text: "yo" });
        await wait(500);
        feed("messages", { id: "b", text: "more" });
        await wait(3000);
        out.sends = sends(); out.prompts = omp();
    """, omp_sleep=1)
    assert out["sends"] == ["desk|--thread T -- hello there"]  # only the second turn sends
    assert len(out["prompts"]) == 2  # the first draft was killed
    assert sum("owner: yo\nowner: more" in p for p in out["prompts"]) == 1


def test_a_stopped_line_gets_no_desk_turn_and_the_burst_is_dropped(tmp_path):
    stop = json.dumps(str(tmp_path / "stop"))
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "stop").write_text("stopped by hand")
    out = run(tmp_path, f"""
        feed("messages", {{ id: "a", text: "yo" }});
        await wait(800);
        out.stopped = [omp().length, sends().length, log()];
        (await import("node:fs")).unlinkSync({stop});    // resume
        feed("messages", {{ id: "b", text: "you there?" }});
        await wait(1200);
        out.after = [omp().length, sends().length];
        out.prompt = omp()[0];
    """)
    assert out["stopped"] == [0, 0, ["skip (line stopped)"]]
    assert out["after"] == [1, 1]
    assert "Latest messages, after the chat:\nowner: you there?" in out["prompt"]  # not the dropped "yo"


def test_react_skip_and_failed_desk_answers(tmp_path):
    react = run(tmp_path / "r", "feed('messages', { id: 'a', text: 'ship it' }); await wait(1200); out.sends = sends(); out.log = log();", answer="REACT:\u2764\ufe0f")
    assert react["sends"] == ["desk|--react \u2764\ufe0f --thread T"] and react["log"] == ["react \u2764\ufe0f"]
    skip = run(tmp_path / "s", "feed('messages', { id: 'a', text: 'lol' }); await wait(1200); out.sends = sends(); out.log = log();", answer="SKIP.")
    assert skip["sends"] == [] and skip["log"] == ["skip"]
    failed = run(tmp_path / "f", "feed('messages', { id: 'a', text: 'hi' }); await wait(1200); out.sends = sends(); out.log = log();", answer="")
    assert failed["sends"] == [] and failed["log"] == ["skip (desk failed)"]


def test_a_failed_send_logs_what_fm_insta_reply_said(tmp_path):
    out = run(tmp_path, "feed('messages', { id: 'a', text: 'hi' }); await wait(1200); out.log = log();", reply="echo 'poll halted (AccountSuspended at /api/v1/direct_v2/inbox/: challenge_required)' >&2\nexit 1\n")
    assert out["log"] == ["hello there (send failed, exit 1: poll halted (AccountSuspended at /api/v1/direct_v2/inbox/: challenge_required))"]


def test_old_rows_fill_the_memory_and_never_start_a_turn(tmp_path):
    out = run(tmp_path, """
        desk.feed("messages", { at: now() - 3600, thread: "T", id: "old", text: "ancient" }, false);
        desk.feed("sent", { at: now() - 3600, thread: "T", kind: "text", text: "old answer", by: "firstmate" }, false);
        await wait(1000);
        out.sends = sends(); out.memory = desk.memory.msgs.map((m) => `${m.kind}: ${m.text}`);
    """)
    assert out["sends"] == []
    assert out["memory"] == ["owner: ancient", "supervisor: old answer"]


def test_following_the_logs_starts_at_their_ends_and_merges_by_time(tmp_path):
    state = tmp_path / "ig"
    state.mkdir()
    (state / "messages.jsonl").write_text(json.dumps({"at": 1, "thread": "T", "id": "old", "text": "before"}) + "\n")
    out = run(tmp_path, f"""
        import {{ appendFileSync }} from "node:fs";
        const m = {json.dumps(str(state / "messages.jsonl"))}, s = {json.dumps(str(state / "sent.jsonl"))};
        const stop = follow(desk, m, s, dir + "/offsets.json", 50);
        await wait(300);
        out.replayed = desk.memory.msgs.length;               // the old DM is not replayed
        const t = now();
        appendFileSync(m, JSON.stringify({{ at: t, thread: "T", id: "n", text: "hi" }}) + "\\n" + '{{"torn":');
        await wait(150);
        appendFileSync(s, JSON.stringify({{ at: t + 1, thread: "T", kind: "text", text: "on it", by: "firstmate" }}) + "\\n");
        await wait(1500);
        out.sends = sends();                                   // Firstmate answered inside the quiet period
        out.memory = desk.memory.msgs.map((x) => `${{x.kind}}: ${{x.text}}`);
        stop();
    """)
    assert out["replayed"] == 0 and out["sends"] == []
    assert out["memory"] == ["owner: hi", "supervisor: on it"]
