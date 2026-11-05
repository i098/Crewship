"""blueprint/config/omp-compact-adviser.ts, run under bun with the adviser package and omp's host module stubbed."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

SCRIPT = """
import { mkdtempSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "ca-"));
const registered = [];
let installed;
Bun.plugin({
  setup(build) {
    build.module("@earendil-works/pi-coding-agent", () => ({
      exports: { getAgentDir: () => dir, VERSION: "18.0.0" },
      loader: "object",
    }));
    build.onResolve({ filter: /compact-adviser\\/src\\/(adviser|env)\\.ts$/ }, args => ({
      path: args.path.endsWith("env.ts") ? "env" : "adviser",
      namespace: "stub",
    }));
    build.onLoad({ filter: /.*/, namespace: "stub" }, args => ({
      loader: "js",
      contents: args.path === "env"
        ? 'export const parseDotenvKey = (t, n) => (t.match(new RegExp("^" + n + "=(.*)$", "m")) || [])[1];'
        : "export const installAdviser = (pi, o) => globalThis.__installed = { pi, o };",
    }));
  },
});
const mod = await import(process.env.MODULE);
const deny = join(dir, "compact-adviser-deny.json");
const out = {};

// Exclusion: no file excludes nothing, a match excludes, an invalid file excludes everything.
out.noFile = mod.isExcluded("/work/app", {}, deny);
writeFileSync(deny, JSON.stringify(["client-x", "mate-home/3(/|$)"]));
out.cwdMatch = mod.isExcluded("/work/Client-X-api", {}, deny);
out.homeMatch = mod.isExcluded("/work/app", { FM_HOME: "/h/mate-home/3/fm" }, deny);
out.other = mod.isExcluded("/work/app", { FM_HOME: "/h/mate-home/30/fm" }, deny);
writeFileSync(deny, '{"x":1}');
out.invalid = mod.isExcluded("/work/app", {}, deny);
writeFileSync(deny, JSON.stringify(["client-x"]));

// Key: the environment wins over the file; the value is only returned, never printed.
const envFile = join(dir, "super.env");
writeFileSync(envFile, "TYPESAFE_API_KEY=from-file\\n");
out.keyEnv = mod.typesafeKey({ TYPESAFE_API_KEY: "from-env" }, envFile);
out.keyFile = mod.typesafeKey({}, envFile);

// Fallback: three snapcompact failures, then remote, then soft, then the caller's onError once.
const calls = [];
const failing = { compact: o => (calls.push(o.mode), o.onError("boom")) };
let finalErrors = 0;
mod.compactWithFallback(failing, { onError: () => finalErrors++ });
out.chain = calls;
out.finalErrors = finalErrors;
const second = [];
let completed = 0;
mod.compactWithFallback(
  { compact: o => (second.push(o.mode), second.length < 2 ? o.onError("x") : o.onComplete("ok")) },
  { onComplete: () => completed++, onError: () => { throw new Error("no"); } },
);
out.retrySucceeds = second;
out.completed = completed;

// Factory: maps agent_end, drops session_before_compact, skips excluded sessions, keeps existing settings.
const events = {};
mod.default({ on: (e, h) => (events[e] = h), registerCommand() {} });
const shim = globalThis.__installed.pi;
shim.on("session_before_compact", () => {});
let settled = 0;
shim.on("agent_settled", () => settled++);
shim.on("turn_end", () => settled += 100);
out.events = Object.keys(events).sort();
const idle = cwd => ({ cwd, isIdle: () => true, sessionManager: { getBranch: () => ["e"] } });
events.agent_end({ willContinue: true }, idle("/work/app"));
events.agent_end({ awaitingAsyncWork: true }, idle("/work/app"));
events.agent_end({}, idle("/work/client-x/app"));
events.agent_end({}, idle("/work/app"));
events.turn_end({}, idle("/work/client-x/app"));
await Bun.sleep(400);
out.settled = settled;
out.settings = JSON.parse(readFileSync(join(dir, "compact-adviser.json"), "utf8"));
writeFileSync(join(dir, "compact-adviser.json"), '{"version":1,"mode":"hint"}');
mod.default({ on() {}, registerCommand() {} });
out.settingsKept = readFileSync(join(dir, "compact-adviser.json"), "utf8");
console.log(JSON.stringify(out));
"""


def run():
    module = str(ROOT / "blueprint/config/omp-compact-adviser.ts")
    out = subprocess.run(["bun", "-e", SCRIPT], capture_output=True, text=True, check=True,
                         env={**os.environ, "MODULE": module})
    return json.loads(out.stdout.splitlines()[-1])


def test_compact_adviser_extension():
    out = run()
    assert (out["noFile"], out["cwdMatch"], out["homeMatch"], out["other"], out["invalid"]) == (
        False, True, True, False, True)
    assert (out["keyEnv"], out["keyFile"]) == ("from-env", "from-file")
    assert out["chain"] == ["snapcompact"] * 3 + ["remote", "soft"]
    assert out["finalErrors"] == 1
    assert out["retrySucceeds"] == ["snapcompact", "snapcompact"] and out["completed"] == 1
    # agent_end replaces agent_settled; session_before_compact is dropped; the excluded cwd and a continuing run never settle.
    assert out["events"] == ["agent_end", "turn_end"]
    assert out["settled"] == 1
    assert out["settings"]["mode"] == "auto" and out["settings"]["autoAcknowledged"] is True
    assert '"mode":"hint"' in out["settingsKept"]
