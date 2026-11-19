// The duplicate guard. One claim is one file made with an exclusive create (`wx`), so two actors that race get exactly one winner,
// and the claim stays on disk through a bridge restart. A claim is never released: a crash after the claim loses the action, never repeats it.
// The desk takes claims in desk-actions.ts; the supervisor runs `fm-claim` (fm-claim, next to this file) before it acts on an owner text.
import { closeSync, fsyncSync, openSync, readdirSync, readFileSync, writeSync, mkdirSync } from "node:fs";
import { createHash } from "node:crypto";

export type Actor = "desk" | "firstmate";
// "msg": the owner text with that id. The actor that holds it may take it again (a later tool call in its own turn); the other actor may not.
// "act": one action key. Strict: nobody takes it twice, not even the same actor.
export type Kind = "msg" | "act";

export function claim(dir: string, kind: Kind, key: string, actor: Actor): boolean {
  mkdirSync(dir, { recursive: true, mode: 0o700 });
  const path = `${dir}/${kind}-${createHash("sha256").update(key).digest("hex")}`;
  try {
    const fd = openSync(path, "wx", 0o600);
    try { writeSync(fd, `${actor}\n${key}\n`); fsyncSync(fd); } finally { closeSync(fd); }
    return true;
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "EEXIST") throw e;
    return kind === "msg" && readFileSync(path, "utf8").split("\n")[0] === actor;
  }
}

// What the desk already did for owner text `id`: one "tool path" per act claim it holds ([] when the desk holds none).
export function deskActions(dir: string, id: string): string[] {
  const done: string[] = [];
  if (claimHolder(dir, "msg", id) !== "desk") return done;
  let names: string[] = [];
  try { names = readdirSync(dir).filter((n) => n.startsWith("act-")); } catch { return done; }
  for (const name of names) {
    const [actor, ids, tool, path] = readFileSync(`${dir}/${name}`, "utf8").split("\n");
    if (actor === "desk" && ids?.split(",").includes(id)) done.push(`${tool} ${path}`);
  }
  return done;
}

export function claimHolder(dir: string, kind: Kind, key: string): Actor | undefined {
  try { return readFileSync(`${dir}/${kind}-${createHash("sha256").update(key).digest("hex")}`, "utf8").split("\n")[0] as Actor; } catch { return undefined; }
}

export function claimsDir(env: Record<string, string | undefined>): string {
  return env.FM_IMESSAGE_CLAIMS || `${env.STATE_DIRECTORY || `${env.HOME}/.local/state/fm-imessage`}/claims`;
}

// fm-claim msg|act KEY...   exit 0: yours, act. Exit 3: held by the other actor, stop and do nothing. Actor: FM_CLAIM_ACTOR, default firstmate.
if (import.meta.main) {
  const [kind, ...key] = Bun.argv.slice(2);
  if ((kind !== "msg" && kind !== "act") || !key.length) { console.error("usage: fm-claim msg|act KEY..."); process.exit(2); }
  const actor = process.env.FM_CLAIM_ACTOR === "desk" ? "desk" : "firstmate";
  const ok = claim(claimsDir(process.env), kind, key.join(" "), actor);
  console.log(ok ? "claimed" : "held: another actor has this; stop and do nothing");
  process.exit(ok ? 0 : 3);
}

// The desk may not tell the owner that an action is done unless a tool that can do that kind of action succeeded in the same turn.
// A kind with no tool in its list can never be claimed: no desk tool orders, buys, pays, books or posts.
// shortcut: a word list, so an unlisted wording slips through and a loose match makes the model reword; upgrade to gating reply text structurally.
// A verb whose subject is the owner or another person ("the email you sent") is history, not a claim.
const OTHER = String.raw`(?<!\b(?:you|they|he|she)\s+)`;
const CLAIMS: [kind: string, pattern: RegExp, tools: string[]][] = [
  ["order", /\b(?:ordered|order placed|placed (?:the|an?|your) order|purchased|bought|paid|payment (?:made|sent)|booked|reserved|subscribed|on its way|on the way)\b/i, []],
  ["post", /\b(?:posted|published|tweeted|submitted|cancell?ed|scheduled)\b/i, []],
  ["send", /\b(?:sent|emailed|texted|messaged)\b/i, ["message_mate"]],
].map(([kind, re, tools]) => [kind, new RegExp(OTHER + (re as RegExp).source, "i"), tools]) as [string, RegExp, string[]][];

// The refusal for `text`, or undefined; `succeeded` holds the tools that succeeded so far in this turn.
export function unprovenClaim(text: string, succeeded: ReadonlySet<string>): string | undefined {
  for (const [kind, pattern, tools] of CLAIMS) {
    const said = pattern.exec(text)?.[0];
    if (said && !tools.some((t) => succeeded.has(t)))
      return `refused: the text says "${said}" (${kind}) but ${tools.length ? `${tools.join(" or ")} did not succeed in this turn` : "no desk tool can do that"}; say what you recommend or what is queued, not that it is done`;
  }
}
