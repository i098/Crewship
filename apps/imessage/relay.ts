import { readdirSync, readFileSync } from "node:fs";
import { cleanText } from "./clean.ts";
import { type Secondmate, supervisorOnly } from "./desk.ts";

export type RelayRequest = Readonly<{
  requestId: string;
  text: string;
  authored?: string;
  mateEligible?: boolean;
  firstmate: boolean;
  mutationPath?: string;
}>;

// Decisions, money, deploys, credentials, writes and unclear approvals stay with Firstmate.
export function deskMayAct(requests: readonly RelayRequest[]): boolean {
  return requests.length > 0 && !requests.some((request) => request.firstmate || !request.mateEligible || request.mutationPath
    || supervisorOnly(request.authored ?? request.text));
}

export function relayTarget(requests: readonly RelayRequest[], metadata: unknown, mates: Secondmate[]): Secondmate | undefined {
  if (!deskMayAct(requests)) return;
  if (!metadata || typeof metadata !== "object" || Array.isArray(metadata)) return;
  const value = metadata as Record<string, unknown>;
  if (value.category !== "work" || typeof value.target !== "string" || !Array.isArray(value.domains)
    || value.domains.length !== 1 || value.domains[0] !== value.target) return;
  return mates.find((mate) => mate.id === value.target);
}

export function relayTargetCurrent(mate: Secondmate, mates: readonly Secondmate[]): boolean {
  return mates.some((entry) => entry.id === mate.id && entry.home === mate.home && entry.scope === mate.scope);
}

export const deskRequestMarker = (requestId: string) => `[desk request ${requestId}]`;

// True when a record in the mate's steering inbox (open or handled) holds the marker line of `requestId`. The sender
// may report a failure after it wrote the record, so this decides whether a delivery needs a retry or an "incomplete" note.
// It looks at the newest 200 records of each folder. A mate with no local inbox gives false.
// handledOnly: the mate has taken the message (its file moved to handled/), not merely received it.
export function mateInboxHas(fmHome: string, mateId: string, requestId: string, handledOnly = false): boolean {
  const marker = deskRequestMarker(requestId);
  const base = `${fmHome}/state/${mateId}.inbox`;
  for (const dir of handledOnly ? [`${base}/handled`] : [base, `${base}/handled`]) {
    let names: string[];
    try { names = readdirSync(dir).filter((name) => name.endsWith(".msg")).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).slice(-200); }
    catch { continue; }
    for (const name of names) {
      try { if (readFileSync(`${dir}/${name}`, "utf8").split("\n").some((line) => line.trimEnd() === marker)) return true; } catch { /* moved while reading */ }
    }
  }
  return false;
}

export const NOTICE_MAX = 80; // chars of the owner's text a relay notice shows

// The owner's one-line notice of a relay: who got which text. Plain words, so the outbound filter keeps the mate's name (it strips ids like `x-mate-1`).
// A text that looks sensitive is not echoed back.
export function relayNotice(to: Secondmate, texts: readonly string[], safe: (text: string) => string, verb = "Sent to"): string {
  const label = to.id.replace(/-/g, " ");
  const name = /\bmate\b/.test(label) ? label : `${label} mate`;
  const what = texts.join(" / ").replace(/\s+/g, " ").trim();
  const held = supervisorOnly(what) || safe(what) !== what;
  const short = what.length > NOTICE_MAX ? `${what.slice(0, NOTICE_MAX - 1).trimEnd()}…` : what;
  return cleanText(`${verb} ${name}: ${held ? "(held back, it may be sensitive)" : short}`);
}
