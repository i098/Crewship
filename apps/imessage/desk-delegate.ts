// Background work for the desk session: the session replies at once, and one background job sends the owner's text
// to Firstmate or a listed second mate, waits for the routed answer, and hands it back to the bridge's checked reply path.
// The target answers by writing a file, the only answer channel; a restart or the wait limit ends the wait.
// A task that cannot be delivered is logged, not sent anywhere else.
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

export function createDelegator<O>(host: DelegateHost<O>) {
  async function run(target: DelegateTarget, text: string, origin: O) {
    mkdirSync(host.answerDir, { recursive: true, mode: 0o700 });
    const id = crypto.randomUUID();
    const path = `${host.answerDir}/${id}.answer`;
    const task = `${text}\nWhen you have the answer, write it for the owner in plain words to ${path}.tmp, then rename it to ${path}`;
    const to = typeof target === "string" ? target : target.id;
    let sent = false;
    try {
      sent = (typeof target === "string" || host.listed(target)) && await host.send(target, id, task);
    } catch (error) { host.log(error); }
    if (!sent) return host.log(new Error(`desk task for ${to} was not delivered`));
    const deadline = Date.now() + host.waitMs;
    const ready = () => (statSync(path, { throwIfNoEntry: false })?.size ?? 0) > 0;
    while (!host.stopping() && Date.now() < deadline && !ready()) await Bun.sleep(host.pollMs);
    if (!ready()) return;
    const answer = readFileSync(path, "utf8");
    rmSync(path, { force: true });
    if (host.muted()) return;
    try { host.report(bubbles(replyText({ text: answer }, host.safe)), `${TASK_GUID_PREFIX}${id}`, origin); } catch (error) { host.log(error); }
  }

  return (target: DelegateTarget, text: string, origin: O) => void run(target, text, origin).catch(host.log);
}
