// Background work for the desk session: the session replies at once, and one background job sends the owner's text
// to Firstmate or a listed second mate, waits for the routed answer, and hands it back to the bridge's checked reply path.
// The target answers by writing a file, the only answer channel. A task file beside it keeps the chat and the text on disk,
// so an answer that comes after a restart or after the wait limit is still sent, once, by the sweep.
// A task that is lost (not delivered, no answer in time, answer refused) is put in Firstmate's inbox, and the owner gets one fixed follow-up.
import { mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { replyText, TASK_GUID_PREFIX } from "./desk-actions.ts";
import { bubbles, type Secondmate } from "./desk.ts";

export type DelegateTarget = Secondmate | "firstmate";

export type DelegateHost<O> = {
  answerDir: string;
  waitMs: number;
  pollMs: number;
  stopping(): boolean;
  muted(): boolean;
  safe(text: string): string;
  listed(mate: Secondmate): boolean; // the mate is still in the routing table
  send(target: DelegateTarget, id: string, text: string): Promise<boolean>; // true when the target's inbox took it
  report(parts: string[], guid: string, origin: O): void; // the bridge's outbox, on the chat the text came from; guid starts with TASK_GUID_PREFIX
  log(error: unknown): void;
};

export const FOLLOW_UP = "Still with Firstmate; you will hear back";
export const WAIT_MS = 600_000;

type Job<O> = { id: string; text: string; origin: O; guid: string };

const sizeOf = (path: string) => statSync(path, { throwIfNoEntry: false })?.size ?? 0;

async function attempt<O>(host: DelegateHost<O>, target: DelegateTarget, id: string, task: string): Promise<boolean> {
  try {
    return (typeof target === "string" || host.listed(target)) && await host.send(target, id, task);
  } catch (error) {
    host.log(error);
    return false;
  }
}

async function lost<O>(host: DelegateHost<O>, job: Job<O>, why: string, refused = "") {
  const note = `${job.text}\nThe desk stopped waiting for this task (${why}). Answer the owner directly.${refused && `\nThe answer the desk refused to send:\n${refused}`}`;
  let held = false;
  try { held = await host.send("firstmate", `${job.id}-lost`, note); } catch (error) { host.log(error); }
  if (!held) return host.log(new Error(`desk task ${job.id} reached no inbox`));
  if (!host.muted()) try { host.report([FOLLOW_UP], `${job.guid}-followup`, job.origin); } catch (error) { host.log(error); }
}

// The answer reaches the owner through the checked reply path; a muted desk drops it.
async function finish<O>(host: DelegateHost<O>, job: Job<O>, answer: string) {
  if (host.muted()) return;
  try { host.report(bubbles(replyText({ text: answer }, host.safe)), job.guid, job.origin); } catch (error) {
    host.log(error);
    return lost(host, job, "the answer was refused", answer);
  }
}

// The answer, taken from its file; undefined when the wait ended without one.
async function answerFrom<O>(host: DelegateHost<O>, path: string): Promise<string | undefined> {
  const deadline = Date.now() + host.waitMs;
  while (!host.stopping() && Date.now() < deadline && !sizeOf(path)) await Bun.sleep(host.pollMs);
  if (!sizeOf(path)) return undefined;
  const answer = readFileSync(path, "utf8");
  rmSync(path, { force: true });
  return answer;
}

async function run<O>(host: DelegateHost<O>, live: Set<string>, target: DelegateTarget, text: string, origin: O) {
  mkdirSync(host.answerDir, { recursive: true, mode: 0o700 });
  const id = crypto.randomUUID();
  const base = `${host.answerDir}/${id}`;
  const job = { id, text, origin, guid: `${TASK_GUID_PREFIX}${id}` };
  const task = `${text}\nWhen you have the answer, write it for the owner in plain words to ${base}.answer.tmp, then rename it to ${base}.answer`;
  writeFileSync(`${base}.task`, JSON.stringify({ text, origin }), { mode: 0o600 });
  live.add(id);
  try {
    if (!await attempt(host, target, id, task)) {
      rmSync(`${base}.task`, { force: true });
      host.log(new Error(`desk task for ${typeof target === "string" ? target : target.id} was not delivered`));
      return await lost(host, job, "not delivered");
    }
    const answer = await answerFrom(host, `${base}.answer`);
    if (answer === undefined) return host.stopping() ? undefined : await lost(host, job, "no answer in time");
    rmSync(`${base}.task`, { force: true });
    return await finish(host, job, answer);
  } finally {
    live.delete(id);
  }
}

// An answer with no live job: the bridge restarted or the wait limit passed. Its task file names the chat.
function sweep<O>(host: DelegateHost<O>, live: Set<string>) {
  if (host.stopping()) return;
  let names: string[] = [];
  try { names = readdirSync(host.answerDir); } catch { return; }
  for (const id of names.filter((name) => name.endsWith(".answer")).map((name) => name.slice(0, -".answer".length))) {
    const base = `${host.answerDir}/${id}`;
    if (live.has(id) || !sizeOf(`${base}.answer`) || !sizeOf(`${base}.task`)) continue;
    try {
      const { text, origin } = JSON.parse(readFileSync(`${base}.task`, "utf8"));
      const answer = readFileSync(`${base}.answer`, "utf8");
      rmSync(`${base}.answer`, { force: true });
      rmSync(`${base}.task`, { force: true });
      void finish(host, { id, text, origin, guid: `${TASK_GUID_PREFIX}${id}` }, answer).catch(host.log);
    } catch (error) { host.log(error); }
  }
}

export function createDelegator<O>(host: DelegateHost<O>) {
  const live = new Set<string>();
  setInterval(() => sweep(host, live), host.pollMs).unref();
  return (target: DelegateTarget, text: string, origin: O) => void run(host, live, target, text, origin).catch(host.log);
}
