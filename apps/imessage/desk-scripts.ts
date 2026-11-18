// Operator scripts the desk may run: files in one fixed directory, picked by name, no arguments, no shell.
// A script that concerns credentials, payments or public posts (by its name or header comment) is neither listed nor run.
import { lstatSync, openSync, readSync, closeSync, readdirSync, realpathSync } from "node:fs";
import { deniedTopic } from "./desk-deny.ts";

export const SCRIPT_MS = 60_000;
export const SCRIPT_OUTPUT_MAX = 4_000; // chars of output one run returns (the head); the script is killed past 4x this
const NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export type ScriptRun = { code: number | null; timedOut: boolean; output: string };

// What the script says about itself: its comment lines after the shebang, from the first 2 KB.
function header(path: string): string {
  const fd = openSync(path, "r");
  try {
    const buf = Buffer.alloc(2048);
    const text = buf.toString("utf8", 0, readSync(fd, buf, 0, buf.length, 0));
    return text.split("\n").filter((line, i) => /^\s*(?:#|\/\/)/.test(line) && !(i === 0 && line.startsWith("#!"))).map((line) => line.replace(/^\s*(?:#|\/\/)\s?/, "")).join("\n");
  } finally { closeSync(fd); }
}

// The runnable path and header of `name`, or the reason it may not run.
function resolve(dir: string, name: string): { path: string; about: string } | string {
  if (!NAME.test(name)) return "not a script name";
  const path = `${dir}/${name}`;
  try {
    const stat = lstatSync(path);
    if (!stat.isFile() || !(stat.mode & 0o111)) return "not an executable file in the script directory";
    if (!realpathSync(path).startsWith(`${realpathSync(dir)}/`)) return "outside the script directory";
    const about = header(path);
    const topic = deniedTopic(`${name}\n${about}`);
    return topic ? `it concerns ${topic}` : { path, about };
  } catch { return "no such script"; }
}

// "name: first header line" for every script the desk may run.
export function listScripts(dir: string): string[] {
  let names: string[];
  try { names = readdirSync(dir).sort(); } catch { return []; }
  return names.flatMap((name) => {
    const found = resolve(dir, name);
    return typeof found === "string" ? [] : [`${name}: ${found.about.split("\n")[0] || "no description"}`];
  });
}

async function capture(stream: ReadableStream<Uint8Array>, max: number, full: () => void): Promise<string> {
  const decoder = new TextDecoder();
  let out = "";
  for await (const chunk of stream) {
    out += decoder.decode(chunk, { stream: true });
    if (out.length > max) { full(); break; }
  }
  return out;
}

// Runs one allowlisted script with a timeout. Throws "refused: ..." when it may not run.
export async function runScript(dir: string, name: string, env: Record<string, string | undefined>, timeoutMs = SCRIPT_MS): Promise<ScriptRun> {
  const found = resolve(dir, name);
  if (typeof found === "string") throw new Error(`refused: ${name}: ${found}`);
  const proc = Bun.spawn([found.path], {
    cwd: dir, stdin: "ignore", stdout: "pipe", stderr: "pipe", detached: true,
    env: { PATH: env.PATH, HOME: env.HOME, FM_HOME: env.FM_HOME },
  });
  const killGroup = () => { try { process.kill(-proc.pid, "SIGKILL"); } catch { /* group already gone */ } };
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; killGroup(); }, timeoutMs);
  try {
    const cap = SCRIPT_OUTPUT_MAX * 4;
    const [out, err] = await Promise.all([capture(proc.stdout, cap, killGroup), capture(proc.stderr, cap, killGroup)]);
    const code = await proc.exited;
    return { code: timedOut ? null : code, timedOut, output: `${out}${err}`.slice(0, SCRIPT_OUTPUT_MAX) };
  } finally {
    clearTimeout(timer);
    killGroup(); // no child outlives the run
  }
}
