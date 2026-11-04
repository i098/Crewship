// Token use of every desk and compaction call: one JSON line per call in tokens.jsonl, and one line per day in
// tokens-daily.log. Both live in the bridge's state directory. Logging never fails a call.
import { appendFileSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";

type Env = Record<string, string | undefined>;
export type TokenEntry = { kind: string; model: string; input: number; output: number };

export function tokenDir(env: Env = process.env): string {
  return env.STATE_DIRECTORY || `${env.HOME || homedir()}/.local/state/fm-imessage`;
}

// The counts a provider returned: OpenAI-style prompt_tokens/completion_tokens or omp's input/output.
export function usageTokens(usage: unknown): Pick<TokenEntry, "input" | "output"> | undefined {
  if (typeof usage !== "object" || usage === null) return;
  const u = usage as Record<string, unknown>;
  const input = u.prompt_tokens ?? u.input;
  const output = u.completion_tokens ?? u.output;
  if (typeof input !== "number" || typeof output !== "number") return;
  return { input, output };
}

export function logTokens(entry: TokenEntry, env: Env = process.env, now = new Date()): void {
  try {
    const dir = tokenDir(env);
    mkdirSync(dir, { recursive: true, mode: 0o700 });
    const ts = now.toISOString();
    appendFileSync(`${dir}/tokens.jsonl`, `${JSON.stringify({ ts, kind: entry.kind, model: entry.model, input_tokens: entry.input, output_tokens: entry.output })}\n`, { mode: 0o600 });
    writeDaily(dir, ts.slice(0, 10));
  } catch (error) {
    console.error("fm-imessage: token log failed:", error instanceof Error ? error.message : error);
  }
}

// The day's line is recomputed from tokens.jsonl, so two processes logging at once never lose a count.
// shortcut: re-reads the whole journal per call, fine at a few thousand lines a day; rotate it before it passes a few MB.
function writeDaily(dir: string, day: string): void {
  let calls = 0, input = 0, output = 0;
  for (const line of readFileSync(`${dir}/tokens.jsonl`, "utf8").split("\n")) {
    if (!line.includes(`"ts":"${day}`)) continue;
    try {
      const row = JSON.parse(line);
      calls++; input += row.input_tokens; output += row.output_tokens;
    } catch { /* a torn line counts for nothing */ }
  }
  const path = `${dir}/tokens-daily.log`;
  let rows: string[] = [];
  try { rows = readFileSync(path, "utf8").split("\n").filter((row) => row && !row.startsWith(`${day} `)); } catch { /* first day */ }
  rows.push(`${day} calls=${calls} input_tokens=${input} output_tokens=${output}`);
  const tmp = `${path}.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
  writeFileSync(tmp, `${rows.join("\n")}\n`, { mode: 0o600 });
  renameSync(tmp, path);
}
