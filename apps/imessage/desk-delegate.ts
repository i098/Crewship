// Background work for the desk session: the session replies at once, and one background job sends the owner's text
// to Firstmate or a listed second mate, waits for the routed answer, and hands it back to the bridge's checked reply path.
// The target answers by writing a file, the only answer channel; a restart or the wait limit ends the wait.
// A task that is lost (not delivered, no answer in time, answer refused) is put in Firstmate's inbox, and the owner gets one fixed follow-up.
import { mkdirSync, readFileSync, rmSync, statSync } from "node:fs";
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
  if (!host.muted()) try { host.report([FOLLOW_UP], job.guid, job.origin); } catch (error) { host.log(error); }
}

// The answer, taken from its file; undefined when the wait ended without one.
async function answerFrom<O>(host: DelegateHost<O>, path: string): Promise<string | undefined> {
  const deadline = Date.now() + host.waitMs;
  const ready = () => (statSync(path, { throwIfNoEntry: false })?.size ?? 0) > 0;
  while (!host.stopping() && Date.now() < deadline && !ready()) await Bun.sleep(host.pollMs);
  if (!ready()) return undefined;
  const answer = readFileSync(path, "utf8");
  rmSync(path, { force: true });
  return answer;
}

async function run<O>(host: DelegateHost<O>, target: DelegateTarget, text: string, origin: O) {
  mkdirSync(host.answerDir, { recursive: true, mode: 0o700 });
  const id = crypto.randomUUID();
  const path = `${host.answerDir}/${id}.answer`;
  const job = { id, text, origin, guid: `${TASK_GUID_PREFIX}${id}` };
  const task = `${text}\nWhen you have the answer, write it for the owner in plain words to ${path}.tmp, then rename it to ${path}`;
  if (!await attempt(host, target, id, task)) {
    host.log(new Error(`desk task for ${typeof target === "string" ? target : target.id} was not delivered`));
    return lost(host, job, "not delivered");
  }
  const answer = await answerFrom(host, path);
  if (answer === undefined) return host.stopping() ? undefined : lost(host, job, "no answer in time");
  if (host.muted()) return;
  try { host.report(bubbles(replyText({ text: answer }, host.safe)), job.guid, origin); } catch (error) {
    host.log(error);
    return lost(host, job, "the answer was refused", answer);
  }
}

export const createDelegator = <O>(host: DelegateHost<O>) =>
  (target: DelegateTarget, text: string, origin: O) => void run(host, target, text, origin).catch(host.log);
