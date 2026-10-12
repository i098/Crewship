// Installed by Crewship from config/omp-quality-gate.ts; `./ship.sh launch`
// overwrites it. The structural and code-health gate at the end of every
// agent turn (docs/omp.md#quality-gate):
//   - Blocking: in a git repository with .sentrux/baseline.json, a turn that
//     changed files runs `sentrux gate .`. A DEGRADED verdict, or a quality
//     drop larger than FM_QUALITY_MAX_DROP points (default 250) against the
//     baseline, sends the agent one continuation: fix it, or re-baseline on
//     purpose. A low score alone never blocks. SENTRUX_GATE=advisory turns
//     the block off.
//   - Advisory: with uncommitted changes, `sentrux check .` (when
//     .sentrux/rules.toml exists) and `fallow audit --changed-since HEAD`
//     (when package.json or tsconfig.json exists) run in the background. A
//     failing check is shown to the agent at the start of its next prompt.
// A missing tool, no baseline, a timeout or unparseable output never blocks.
// `bun config/omp-quality-gate.ts` runs the blocking check once in the current
// directory and exits 1 on a block (the CI job in .github/workflows/ci.yml).
// That entry point fails closed: a missing baseline or sentrux, a timeout or
// no parseable verdict also exits 1, naming the cause.
// @ts-nocheck

import { execFile } from "node:child_process";
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import path from "node:path";

const GATE_TIMEOUT_MS = 25_000; // omp stops waiting for a handler at 30 s.
const ADVISORY_TIMEOUT_MS = 10 * 60_000;
const MAX_ADVISORY_LINES = 60;

type Result = { code: number; out: string };

// Never rejects: a missing command, a timeout or a kill is code -1.
function run(cmd: string, args: string[], cwd: string, timeout: number, signal?: AbortSignal): Promise<Result> {
  const { promise, resolve } = Promise.withResolvers<Result>();
  execFile(cmd, args, { cwd, timeout, signal, encoding: "utf8", maxBuffer: 64 << 20 }, (error, stdout, stderr) => {
    const code = !error ? 0 : typeof error.code === "number" ? error.code : -1;
    resolve({ code, out: `${stdout ?? ""}${stderr ?? ""}` });
  });
  return promise;
}

export function maxDrop(env = process.env): number {
  const n = Number(env.FM_QUALITY_MAX_DROP);
  return env.FM_QUALITY_MAX_DROP && Number.isFinite(n) ? n : 250;
}

const QUALITY = /Quality:\s*(\d+)\s*(?:->|→)\s*(\d+)/;

// The blocking reason for `sentrux gate` output, or "" when it does not block.
export function blockReason(output: string, limit = maxDrop()): string {
  const evidence = output
    .split("\n")
    .filter((line) => /✗|Quality|Coupling|Cycles|God/.test(line))
    .join("\n");
  const rebaseline =
    "If the change is understood and intended, re-baseline with `sentrux gate --save .` and commit .sentrux/baseline.json.";
  if (output.includes("DEGRADED")) {
    return `sentrux gate: structural regression against the baseline (DEGRADED).\n${evidence}\nFix the structure. ${rebaseline}`;
  }
  const m = output.match(QUALITY);
  if (!m) return "";
  const drop = Number(m[1]) - Number(m[2]);
  if (drop <= limit) return "";
  return (
    `sentrux gate: quality fell ${drop} points (${m[1]} -> ${m[2]}), past the ${limit}-point tolerance.\n` +
    `A low score alone does not block; this much movement does. Fix the structure or split the change. ${rebaseline}`
  );
}

// The block text for the repository at root, or "" (also for every skip case).
export async function gate(root: string, signal?: AbortSignal): Promise<string> {
  if (process.env.SENTRUX_GATE === "advisory") return "";
  if (!existsSync(path.join(root, ".sentrux/baseline.json"))) return "";
  const { code, out } = await run("sentrux", ["gate", "."], root, GATE_TIMEOUT_MS, signal);
  return code === -1 ? "" : blockReason(out);
}

async function gitRoot(cwd: string): Promise<string> {
  const { code, out } = await run("git", ["rev-parse", "--show-toplevel"], cwd, 10_000);
  return code === 0 ? out.trim() : "";
}

// HEAD, the status and the diff: equal fingerprints mean no file changed.
async function fingerprint(root: string): Promise<{ hash: string; dirty: boolean }> {
  const [head, status, diff] = await Promise.all([
    run("git", ["rev-parse", "HEAD"], root, 10_000),
    run("git", ["status", "--porcelain", "--untracked-files=all"], root, 10_000),
    run("git", ["diff", "HEAD"], root, 10_000),
  ]);
  const hash = createHash("sha256").update(head.out).update(status.out).update(diff.out).digest("hex");
  return { hash, dirty: status.out.trim() !== "" };
}

function failing(name: string, { code, out }: Result): string {
  if (code <= 0) return "";
  const lines = out.trim().split("\n");
  const shown = lines.slice(0, MAX_ADVISORY_LINES).join("\n");
  return `${name} (advisory):\n${shown}${lines.length > MAX_ADVISORY_LINES ? "\n…" : ""}`;
}

// The advisory checks this repository opts into: [label, command, args].
function advisoryChecks(root: string): [string, string, string[]][] {
  const has = (file: string) => existsSync(path.join(root, file));
  const checks: [string, string, string[]][] = [];
  if (has(".sentrux/rules.toml")) checks.push(["sentrux check", "sentrux", ["check", "."]]);
  if (has("package.json") || has("tsconfig.json")) {
    checks.push(["fallow audit", "fallow", ["audit", "--changed-since", "HEAD"]]);
  }
  return checks;
}

async function advisory(root: string, checks: [string, string, string[]][]): Promise<string> {
  const found = await Promise.all(
    checks.map(([name, cmd, args]) => run(cmd, args, root, ADVISORY_TIMEOUT_MS).then((r) => failing(name, r))),
  );
  return found.filter(Boolean).join("\n\n");
}

export default function (pi) {
  let start = ""; // the fingerprint when the current agent loop started
  let blocked = false; // this prompt's settle already sent its one block
  let auditing = false;
  let audited = "";
  let pending = "";

  pi.on("agent_start", async (_event, ctx) => {
    const root = await gitRoot(ctx?.cwd ?? process.cwd());
    start = root && existsSync(path.join(root, ".sentrux/baseline.json")) ? (await fingerprint(root)).hash : "";
  });

  pi.on("session_stop", async (event, ctx) => {
    if (!event.stop_hook_active) blocked = false;
    const root = await gitRoot(ctx?.cwd ?? process.cwd());
    const checks = root ? advisoryChecks(root) : [];
    if (!root || (!start && checks.length === 0)) return {};
    const now = await fingerprint(root);
    if (checks.length && now.dirty && !auditing && now.hash !== audited) {
      auditing = true;
      audited = now.hash;
      advisory(root, checks)
        .then((found) => {
          pending = found;
        })
        .finally(() => {
          auditing = false;
        });
    }
    if (blocked || !start || now.hash === start) return {};
    const reason = await gate(root, event.signal);
    if (!reason) return {};
    blocked = true;
    return { continue: true, additionalContext: `Quality gate blocked this turn's end.\n${reason}` };
  });

  pi.on("before_agent_start", async () => {
    if (!pending) return {};
    const content = `Quality gate advisory findings for the last change. Review and address as needed.\n\n${pending}`;
    pending = "";
    return { message: { customType: "quality-gate", content, display: true } };
  });
}

if (import.meta.main) {
  const fail = (message: string) => {
    console.error(message);
    process.exit(1);
  };
  if (!existsSync(".sentrux/baseline.json")) fail("sentrux gate: the committed .sentrux/baseline.json is missing.");
  const { code, out } = await run("sentrux", ["gate", "."], process.cwd(), GATE_TIMEOUT_MS);
  if (code === -1) fail(`sentrux gate: sentrux did not run (not on PATH, timed out after ${GATE_TIMEOUT_MS / 1000} s, or killed).`);
  if (!out.includes("DEGRADED") && !QUALITY.test(out)) fail(`sentrux gate: sentrux printed no verdict (exit ${code}).\n${out}`);
  const reason = blockReason(out);
  if (reason) fail(reason);
  console.log("sentrux gate: no block");
}
