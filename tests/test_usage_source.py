import importlib.util
import json
import os
import pwd
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "blueprint/config/omp-usage.ts"


@pytest.fixture(scope="module")
def native_source():
    executable = shutil.which("omp")
    if not executable or not shutil.which("bun"):
        pytest.skip("needs the native OMP source and Bun")
    installed = Path(executable).resolve().parents[2]
    source = installed / "pi-ai"
    if not (source / "src/stream.ts").is_file():
        pytest.skip("native OMP does not expose its source package here")
    mount = next((path for path in ROOT.parents if path.is_mount() and path != Path("/")), None)
    if mount is None:
        pytest.skip("the native collector fixture requires a separate mounted worktree")
    with tempfile.TemporaryDirectory(prefix=".usage-native-", dir=ROOT) as temporary:
        directory = Path(temporary)
        packages = directory / "node_modules"
        packages.mkdir()
        native = packages / "@oh-my-pi"
        native.mkdir()
        for package in installed.parent.iterdir():
            if package.name != "@oh-my-pi":
                (packages / package.name).symlink_to(package, target_is_directory=package.is_dir())
        for package in installed.iterdir():
            if package.name != "pi-ai":
                (native / package.name).symlink_to(package, target_is_directory=package.is_dir())
        shutil.copytree(source / "src", native / "pi-ai/src")
        shutil.copy2(source / "package.json", native / "pi-ai/package.json")
        subprocess.run(["patch", "--batch", "--fuzz=0", "-p3", "-d", str(native / "pi-ai"),
                        "-i", str(ROOT / "blueprint/patches/omp/usage.patch")],
                       capture_output=True, text=True, check=True)
        yield directory, native / "pi-ai/src", mount


def execute(native_source, code, *, enabled=True, collector=None, inspect=None, store=None):
    directory, native, mount = native_source
    with tempfile.TemporaryDirectory(prefix="case-", dir=directory) as temporary:
        case = Path(temporary)
        script = case / "scenario.ts"
        script.write_text(code.replace("NATIVE_SOURCE", native.as_posix())
                          .replace("ADAPTER_SOURCE", ADAPTER.as_posix()))
        home, temporary_files = case / "home", case / "tmp"
        home.mkdir()
        temporary_files.mkdir()
        environment = {"PATH": os.environ["PATH"], "HOME": str(home), "TMPDIR": str(temporary_files),
                       "LANG": "C.UTF-8",
                       "CREWSHIP_USAGE_COLLECTOR": str(collector or ROOT / "scripts/usage.py"),
                       "CREWSHIP_USAGE_DATA_DIR": str(case / "data"),
                       "CREWSHIP_USAGE_MOUNT": str(mount)}
        if enabled:
            environment["CREWSHIP_USAGE_ADAPTER"] = str(ADAPTER)
        if store:
            environment["CREWSHIP_USAGE_STORE"] = store
        result = subprocess.run(["bun", str(script)], cwd=directory, env=environment,
                                capture_output=True, text=True, timeout=60)
        database = case / "data" / ("usage.sqlite" if store == "ledger" else "spool.sqlite")
        records = []
        if result.returncode != 0:
            return result, records
        if database.exists():
            with sqlite3.connect(database) as connection:
                records = [json.loads(row[0]) for row in connection.execute(
                    "SELECT payload FROM events ORDER BY ingested,rowid")]
            if inspect:
                inspect(case / "data")
        return result, records


TRANSPORT = r'''
import { stream, completeSimple } from "NATIVE_SOURCE/stream.ts";
import { buildModel } from "NATIVE_SOURCE/../../pi-catalog/src/build.ts";
const model = buildModel({
    id: "model-a", name: "Model A", api: "openai-responses", provider: "openai",
    baseUrl: "https://provider.invalid/v1", reasoning: false, input: ["text"],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: 10000, maxTokens: 1000,
});
let calls = 0;
let reported = true;
let failed = false;
globalThis.fetch = async () => {
    calls++;
    const item = { type: "message", id: "synthetic-message", role: "assistant", status: "completed",
        content: [{ type: "output_text", text: "fixture-text-do-not-capture", annotations: [] }] };
    const response = { id: "synthetic-response", model: "model-a", status: failed ? "failed" : "completed",
        output: failed ? [] : [item], ...(reported ? { usage: { input_tokens: 35, output_tokens: 8, total_tokens: 43,
            input_tokens_details: { cached_tokens: 20, cache_write_tokens: 5 },
            output_tokens_details: { reasoning_tokens: 3 } } } : {}),
        ...(failed ? { error: { code: "server_error", message: "fixture-error-do-not-capture" } } : {}) };
    const events = [{ type: "response.created", response: { id: response.id, status: "in_progress", output: [] } }];
    if (!failed) events.push(
        { type: "response.output_item.added", output_index: 0, item: { ...item, content: [] } },
        { type: "response.content_part.added", item_id: item.id, output_index: 0, content_index: 0,
          part: { type: "output_text", text: "", annotations: [] } },
        { type: "response.output_text.delta", item_id: item.id, output_index: 0, content_index: 0,
          delta: "fixture-text-do-not-capture" },
        { type: "response.output_item.done", output_index: 0, item },
    );
    events.push({ type: failed ? "response.failed" : "response.completed", response });
    return new Response(events.map(event => "data: " + JSON.stringify(event) + "\n\n").join("") + "data: [DONE]\n\n",
        { headers: { "content-type": "text/event-stream", "fixture-private-header": "do-not-capture" } });
};
const context = { systemPrompt: [], messages: [] };
const options = { apiKey: "fixture-private-key", cacheRetention: "none", acceptEmptyResponse: true,
                  loopGuard: { enabled: false }, fetch: globalThis.fetch };
async function request() {
    const response = stream(model, context, options);
    for await (const event of response) { if (event.type === "done" || event.type === "error") break; }
    return await response.result();
}
'''


def test_actual_native_provider_completions_keep_usage_presence_and_distinct_attempts(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
await request();
await request();
reported = false;
await request();
failed = true;
await request();
console.log(JSON.stringify({ calls }));
''')
    assert result.returncode == 0, result.stderr
    completions = [row for row in records if row["kind"] == "complete"]
    assert len(completions) == 4
    assert [row["sequence"] for row in completions] == [1, 2, 3, 4]
    assert len({row["event"] for row in completions}) == 4
    assert completions[0]["input_basis"] == "inclusive"
    assert {key: completions[0][key] for key in ("input", "output", "cache_read", "cache_write", "reasoning")} == {
        "input": 35, "output": 8, "cache_read": 20, "cache_write": 5, "reasoning": 3}
    assert [row["usage_present"] for row in completions] == [True, True, False, False]
    assert completions[-1]["outcome"] == "error"
    assert records[-1]["kind"] == "shutdown"
    serialized = json.dumps(records)
    assert all(private not in serialized for private in (
        "fixture-private-key", "fixture-private-header", "fixture-error-do-not-capture",
        "fixture-text-do-not-capture", "synthetic-response"))


def test_native_source_is_disabled_without_the_explicit_adapter_path(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
import { existsSync } from "node:fs";
const response = await request();
if (response.usageMetadata !== undefined || existsSync(process.env.CREWSHIP_USAGE_DATA_DIR!))
    throw new Error("the disabled source must not claim usage presence or create storage");
''', enabled=False)
    assert result.returncode == 0, result.stderr
    assert records == []


def test_failed_durable_start_prevents_native_dispatch(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
let rejected = false;
try { await request(); } catch { rejected = true; }
if (!rejected || calls !== 0) throw new Error("the durable start must fail before provider dispatch");
''', collector=ROOT / "missing-collector.py")
    assert result.returncode == 0, result.stderr
    assert records == []


def test_stale_spool_refuses_the_native_call_before_dispatch_and_keeps_the_ledger_closed(native_source):
    stored = {}
    result, records = execute(native_source, TRANSPORT + r'''
import { Database } from "bun:sqlite";
await request();
const spool = new Database(process.env.CREWSHIP_USAGE_DATA_DIR + "/spool.sqlite");
const stale = Date.now() / 1000 - 8 * 86400;
spool.run("INSERT INTO events(producer,event,kind,at,ingested,expires,payload,sequence_through,"
    + "retired_completions) VALUES(?,?,'gap',?,?,?,'{}',0,0)",
    [crypto.randomUUID(), crypto.randomUUID(), stale, stale, stale + 35 * 86400]);
let refused = false;
try { await request(); } catch { refused = true; }
if (!refused || calls !== 1) throw new Error("a stale spool must refuse the call before dispatch");
spool.run("DELETE FROM events WHERE payload = '{}'");
spool.close();
await request();
if (calls !== 2) throw new Error("the spool must accept calls after the stale record leaves");
''', inspect=lambda data: stored.update(ledger=(data / "usage.sqlite").exists()))
    assert result.returncode == 0, result.stderr
    assert stored == {"ledger": False}
    assert [row["kind"] for row in records] == [
        "register", "start", "complete", "gap", "start", "complete", "checkpoint", "shutdown"]
    assert [row["sequence"] for row in records if row["kind"] == "start"] == [1, 3]


def test_native_helper_calls_register_separately_from_chat(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
await request();
await completeSimple(model, context, options);
''')
    assert result.returncode == 0, result.stderr
    assert sorted(row["producer_kind"] for row in records if row["kind"] == "register") == ["chat", "helper"]
    assert len([row for row in records if row["kind"] == "complete"]) == 2


def test_adapter_never_reads_content_and_surfaces_completion_delivery_failure(native_source):
    result, records = execute(native_source, r'''
import { capture } from "ADAPTER_SOURCE";
import { AssistantMessageEventStream } from "NATIVE_SOURCE/utils/event-stream.ts";
const collector = process.env.CREWSHIP_USAGE_COLLECTOR;
const stream = capture({ provider: "example", model: "model-a", producer_kind: "chat" }, () => {
    const source = new AssistantMessageEventStream();
    const message = { role: "assistant", stopReason: "stop", usageMetadata: null,
        get content() { throw new Error("content must never be read"); } };
    queueMicrotask(() => source.push({ type: "done", reason: "stop", message }));
    return source;
});
await stream.result();
const broken = capture({ provider: "example", model: "model-a", producer_kind: "chat" }, () => {
    const source = new AssistantMessageEventStream();
    queueMicrotask(() => {
        process.env.CREWSHIP_USAGE_COLLECTOR = "/missing-collector.py";
        source.push({ type: "done", reason: "stop", message: { role: "assistant", stopReason: "stop", usageMetadata: null } });
    });
    return source;
});
let rejected = false;
try { await broken.result(); } catch { rejected = true; }
if (!rejected) throw new Error("completion delivery failure must escape");
process.env.CREWSHIP_USAGE_COLLECTOR = collector;
const recovered = capture({ provider: "example", model: "model-a", producer_kind: "chat" }, () => {
    const source = new AssistantMessageEventStream();
    queueMicrotask(() => source.push({ type: "done", reason: "stop",
        message: { role: "assistant", stopReason: "stop", usageMetadata: null } }));
    return source;
});
await recovered.result();
''')
    assert result.returncode == 0, result.stderr
    assert len([row for row in records if row["kind"] == "complete"]) == 2
    assert len([row for row in records if row["kind"] == "start"]) == 3
    assert len([row for row in records if row["kind"] == "gap"]) == 1


def test_native_chat_backed_judgments_have_their_own_producer(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
import { chatTextBackend } from "NATIVE_SOURCE/judgment/chat.ts";
await chatTextBackend(model, { apiKey: "fixture-private-key" }).complete(
    { system: "", user: "", retry: false }, {});
if (calls !== 1) throw new Error("expected one native judgment completion");
''')
    assert result.returncode == 0, result.stderr
    assert [row["producer_kind"] for row in records if row["kind"] == "register"] == ["judgment"]
    assert [row["usage_present"] for row in records if row["kind"] == "complete"] == [True]


def test_actual_anthropic_stream_merges_usage_without_reading_reasoning_text(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
const anthropic = buildModel({ ...model, id: "model-b", name: "Model B",
    api: "anthropic-messages", provider: "anthropic", baseUrl: "https://provider.invalid" });
globalThis.fetch = async () => {
    const events = [
        { type: "message_start", message: { id: "synthetic-response", type: "message", role: "assistant",
          model: "model-b", content: [], usage: { input_tokens: 10, output_tokens: 0,
          cache_read_input_tokens: 20, cache_creation_input_tokens: 5 } } },
        { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
        { type: "content_block_delta", index: 0,
          delta: { type: "text_delta", text: "fixture-text-do-not-capture" } },
        { type: "content_block_stop", index: 0 },
        { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: { output_tokens: 8 } },
        { type: "message_stop" },
    ];
    return new Response(events.map(event => "event: " + event.type + "\ndata: " +
        JSON.stringify(event) + "\n\n").join(""), { headers: { "content-type": "text/event-stream" } });
};
const response = stream(anthropic, context, { ...options, fetch: globalThis.fetch });
for await (const event of response) {}
const terminal = await response.result();
if (terminal.stopReason === "error") throw new Error("synthetic Anthropic transport failed");
''')
    assert result.returncode == 0, result.stderr
    completion = next(row for row in records if row["kind"] == "complete")
    assert completion["input_basis"] == "exclusive"
    assert completion["usage_present"] is True
    assert {key: completion[key] for key in ("input", "output", "cache_read", "cache_write", "reasoning")} == {
        "input": 10, "output": 8, "cache_read": 20, "cache_write": 5, "reasoning": None}


ANTHROPIC = TRANSPORT + r'''
const anthropic = buildModel({ ...model, id: "model-b", name: "Model B",
    api: "anthropic-messages", provider: "anthropic", baseUrl: "https://provider.invalid" });
const scenario = SCENARIO;
const usage = (output, compactionOutput) => ({ input_tokens: 10, output_tokens: output,
    cache_read_input_tokens: 20, cache_creation_input_tokens: 5,
    ...(scenario.compaction ? { iterations: [
        { type: "compaction", input_tokens: 100, output_tokens: compactionOutput,
          cache_read_input_tokens: 0, cache_creation_input_tokens: 0 },
        { type: "message", input_tokens: 10, output_tokens: output,
          cache_read_input_tokens: 20, cache_creation_input_tokens: 5 }] } : {}) });
globalThis.fetch = async () => {
    calls++;
    const events = [
        { type: "message_start", message: { id: "synthetic-response", type: "message", role: "assistant",
          model: "model-b", content: [], usage: usage(1, 2) } },
        { type: "content_block_start", index: 0, content_block: { type: "text", text: "" } },
        { type: "content_block_delta", index: 0,
          delta: { type: "text_delta", text: "fixture-text-do-not-capture" } },
        { type: "message_delta", delta: { stop_reason: null }, usage: { output_tokens: 5 } },
    ];
    if (scenario.final) events.push(
        { type: "content_block_stop", index: 0 },
        { type: "message_delta", delta: { stop_reason: "end_turn" }, usage: usage(8, 40) },
        { type: "message_stop" },
    );
    return new Response(events.map(event => "event: " + event.type + "\ndata: " +
        JSON.stringify(event) + "\n\n").join(""), { headers: { "content-type": "text/event-stream" } });
};
const response = stream(anthropic, context, { ...options, fetch: globalThis.fetch });
for await (const event of response) {}
const terminal = await response.result();
if (calls !== 1 || (terminal.stopReason === "error") === scenario.final)
    throw new Error("the synthetic Anthropic stream ended unexpectedly");
'''


def ledger_view(data):
    spec = importlib.util.spec_from_file_location("usage_ledger", ROOT / "scripts/usage.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    now, sent = datetime.now(UTC), []
    with module.Ledger(data / "usage.sqlite") as ledger:
        report = ledger.summary(now - timedelta(hours=1), now + timedelta(hours=1))
        ledger.export(lambda payload: sent.append(payload) or {})
    logs = [{item["key"]: item["value"] for item in log["attributes"]}
            for log in sent[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]]
    return report, next(log for log in logs if log["usage.kind"] == {"stringValue": "complete"})


@pytest.mark.parametrize("compaction", [False, True])
@pytest.mark.parametrize("final", [False, True])
def test_actual_anthropic_output_counts_only_after_a_terminal_stop_reason(native_source, compaction, final):
    view = {}
    result, records = execute(
        native_source, ANTHROPIC.replace("SCENARIO", json.dumps({"compaction": compaction, "final": final})),
        inspect=lambda data: view.update(zip(("report", "export"), ledger_view(data))), store="ledger")
    assert result.returncode == 0, result.stderr
    completion = next(row for row in records if row["kind"] == "complete")
    input_tokens, output = (110, 48) if compaction else (10, 8)
    assert completion["outcome"] == ("success" if final else "error")
    assert completion["usage_present"] is True and completion["input_basis"] == "exclusive"
    assert {key: completion[key] for key in ("input", "output", "cache_read", "cache_write", "reasoning")} == {
        "input": input_tokens, "output": output if final else None,
        "cache_read": 20, "cache_write": 5, "reasoning": None}
    total = input_tokens + 25 + output
    assert view["report"]["requests"] == 1
    assert view["report"]["counted_tokens"] == (total if final else None)
    assert view["report"]["unknown_tokens"] == (0 if final else 1)
    assert view["export"]["usage.input_total"] == {"intValue": str(input_tokens + 25)}
    if final:
        assert view["export"]["usage.total"] == {"intValue": str(total)}
        assert view["export"]["usage.output"] == {"intValue": str(output)}
    else:
        assert "usage.total" not in view["export"] and "usage.output" not in view["export"]


def test_idle_source_checkpoints_do_not_invent_completed_requests(native_source):
    result, _ = execute(native_source, r'''
import { spawnSync } from "node:child_process";
import { AssistantMessageEventStream } from "NATIVE_SOURCE/utils/event-stream.ts";
const originalInterval = globalThis.setInterval;
let pulse: (() => void) | undefined;
globalThis.setInterval = (callback) => {
    if (typeof callback !== "function") throw new Error("expected a checkpoint callback");
    pulse = () => callback();
    return originalInterval(() => {}, 86_400_000);
};
const { capture } = await import("ADAPTER_SOURCE");
const underlying = new AssistantMessageEventStream();
const pending = capture({ provider: "example", model: "model-a", producer_kind: "chat" }, () => underlying);
if (!pulse) throw new Error("the idle checkpoint is missing");
pulse();
function report() {
    const result = spawnSync("python3", [process.env.CREWSHIP_USAGE_COLLECTOR!, "--data-dir",
        process.env.CREWSHIP_USAGE_DATA_DIR!, "--mount", process.env.CREWSHIP_USAGE_MOUNT!, "report"],
        { encoding: "utf8" });
    if (result.status !== 0) throw new Error("the metadata report failed");
    return JSON.parse(result.stdout);
}
const before = report();
if (before.requests !== 0 || before.counted_tokens !== null || before.partial !== true
    || JSON.stringify(before.coverage[0].missing_sequences) !== "[[1,1]]")
    throw new Error("the checkpoint must preserve the pending request as a gap");
underlying.push({ type: "done", reason: "stop", message: {
    role: "assistant", stopReason: "stop", usageMetadata: null } });
await pending.result();
pulse();
const after = report();
if (after.requests !== 1 || after.counted_tokens !== null
    || after.coverage[0].missing_sequences.length !== 0)
    throw new Error("the acknowledged completion must close the sequence gap exactly once");
''', store="ledger")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("recovery", ["shutdown", "completion", "checkpoint"])
def test_pending_outage_is_durable_before_recovered_source_records(native_source, recovery):
    view = {}

    def inspect(data):
        report = subprocess.run(
            [sys.executable, str(ROOT / "scripts/usage.py"), "--mount", str(native_source[2]),
             "--data-dir", str(data), "report"],
            check=True, capture_output=True, text=True)
        view.update(json.loads(report.stdout))

    result, records = execute(native_source, r'''
import { AssistantMessageEventStream } from "NATIVE_SOURCE/utils/event-stream.ts";
const originalInterval = globalThis.setInterval;
let pulse: (() => void) | undefined;
globalThis.setInterval = (callback) => {
    pulse = () => callback();
    return originalInterval(() => {}, 86_400_000);
};
const { capture } = await import("ADAPTER_SOURCE");
const underlying = new AssistantMessageEventStream();
const pending = capture({ provider: "example", model: "model-a", producer_kind: "chat" }, () => underlying);
const recovery = RECOVERY;
function finish() {
    underlying.push({ type: "done", reason: "stop", message: {
        role: "assistant", stopReason: "stop", usageMetadata: null } });
}
if (recovery === "shutdown") {
    finish();
    await pending.result();
}
if (!pulse) throw new Error("the checkpoint callback is missing");
const collector = process.env.CREWSHIP_USAGE_COLLECTOR;
process.env.CREWSHIP_USAGE_COLLECTOR = "/missing-collector.py";
pulse();
process.env.CREWSHIP_USAGE_COLLECTOR = collector;
if (recovery === "completion") {
    finish();
    await pending.result();
} else if (recovery === "checkpoint") {
    pulse();
}
'''.replace("RECOVERY", json.dumps(recovery)),
        inspect=inspect, store="ledger")
    assert result.returncode == 0, result.stderr
    assert "usage metadata checkpoint acknowledgement failed" in result.stderr
    gaps = [row for row in records if row["kind"] == "gap"]
    assert len(gaps) == 1
    gap = gaps[0]
    recovered_kind = "complete" if recovery == "completion" else recovery
    recovered = next(row for row in records if row["kind"] == recovered_kind)
    assert records.index(gap) < records.index(recovered)
    assert gap["reason"] == "delivery" and gap["producer"] == recovered["producer"]
    coverage = view["coverage"][0]
    assert coverage["gap_intervals"] == 1
    assert coverage["missing_sequences"] == ([[1, 1]] if recovery == "checkpoint" else [])
    assert coverage["shutdown"] is True
    assert view["requests"] == (0 if recovery == "checkpoint" else 1)
    assert view["counted_tokens"] is None


def test_native_cancellation_keeps_a_completion_with_unknown_tokens(native_source):
    result, records = execute(native_source, TRANSPORT + r'''
const response = stream(model, context, { ...options, signal: AbortSignal.abort() });
for await (const event of response) {}
const terminal = await response.result();
if (terminal.stopReason !== "aborted" || calls !== 0)
    throw new Error("the synthetic request must abort before transport");
''')
    assert result.returncode == 0, result.stderr
    completion = next(row for row in records if row["kind"] == "complete")
    assert completion["outcome"] == "aborted"
    assert completion["input"] is None and completion["output"] is None


@pytest.fixture
def usage_installation():
    mount = next((path for path in ROOT.parents if path.is_mount() and path != Path("/")), None)
    if mount is None or not shutil.which("ansible-playbook"):
        pytest.skip("needs Ansible and a separate mounted worktree")
    with tempfile.TemporaryDirectory(prefix=".usage-install-", dir=ROOT) as temporary:
        scratch = Path(temporary)
        (scratch / "templates").symlink_to(ROOT / "blueprint/ansible/templates")
        config = scratch / "ansible.cfg"
        config.write_text("[defaults]\nretry_files_enabled = False\nlocal_tmp = "
                          + str(scratch / "local-tmp") + "\nremote_tmp = "
                          + str(scratch / "remote-tmp") + "\n")
        play = scratch / "play.yml"
        play.write_text(yaml.safe_dump([{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "vars_files": [str(ROOT / "blueprint/ansible/group_vars/all" / (name + ".yml"))
                           for name in ("base", "services", "usage")],
            "tasks": [{"ansible.builtin.import_tasks": str(ROOT / "blueprint/ansible/tasks/usage.yml")}],
            "handlers": [{"name": "Reload preview", "ansible.builtin.debug": {"msg": "no runtime"},
                          "listen": "reload user systemd"}],
        }]))

        def apply(settings, *options):
            variables = {
                "crewship_repo": str(ROOT), "crewship_blueprint": str(ROOT / "blueprint"),
                "crewship": {"user": pwd.getpwuid(os.getuid()).pw_name,
                             "home": str(scratch / "home"), "start_services": False,
                             "data_dir": str(scratch / "data"),
                             "usage": {"mount": str(mount), **settings}},
                "ansible_become": False, "ansible_python_interpreter": sys.executable,
            }
            environment = {**os.environ, "ANSIBLE_CONFIG": str(config)}
            result = subprocess.run(
                ["ansible-playbook", "-i", "localhost,", str(play), "-e", json.dumps(variables), *options],
                env=environment, text=True, capture_output=True, timeout=60)
            assert result.returncode == 0, result.stdout + result.stderr
            return result.stdout

        yield scratch, apply


@pytest.mark.parametrize("endpoint", ["", "https://otlp.example.invalid/v1/logs"])
def test_usage_preview_creates_no_directories_on_a_new_host(usage_installation, endpoint):
    scratch, apply = usage_installation
    apply({"endpoint": endpoint}, "--check")
    assert not (scratch / "home").exists()
    assert not (scratch / "data").exists()


def test_usage_disable_and_removal_preserve_pending_and_old_data(usage_installation):
    scratch, apply = usage_installation
    configured = {"endpoint": "https://otlp.example.invalid/v1/logs"}
    state = scratch / "data/usage"
    state.mkdir(parents=True)
    saved = {name: name.encode() for name in ("usage.sqlite", "spool.sqlite", "operator-notes")}
    for name, content in saved.items():
        (state / name).write_bytes(content)
    assets = scratch / "home/.local/share/crewship/usage"
    units = scratch / "home/.config/systemd/user"
    enabled = units / "timers.target.wants/crewship-usage.timer"

    apply(configured)
    assert enabled.is_symlink()
    assert "changed=0" in apply(configured)
    apply({**configured, "enabled": False})
    assert not enabled.exists()
    assert not any(assets.iterdir())
    assert "changed=0" in apply({**configured, "enabled": False})
    apply(configured)
    assert enabled.is_symlink()
    apply({})
    assert not any(assets.iterdir())
    assert not (units / "crewship-usage.timer").exists()
    assert not (units / "crewship-usage.service").exists()
    assert not enabled.exists()
    assert {name: (state / name).read_bytes() for name in saved} == saved
    assert "changed=0" in apply({})
