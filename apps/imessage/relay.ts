import { readdirSync, readFileSync } from "node:fs";
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
export function mateInboxHas(fmHome: string, mateId: string, requestId: string): boolean {
  const marker = deskRequestMarker(requestId);
  const base = `${fmHome}/state/${mateId}.inbox`;
  for (const dir of [base, `${base}/handled`]) {
    let names: string[];
    try { names = readdirSync(dir).filter((name) => name.endsWith(".msg")).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).slice(-200); }
    catch { continue; }
    for (const name of names) {
      try { if (readFileSync(`${dir}/${name}`, "utf8").split("\n").some((line) => line.trimEnd() === marker)) return true; } catch { /* moved while reading */ }
    }
  }
  return false;
}
