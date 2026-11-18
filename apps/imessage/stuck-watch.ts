// Stuck supervisors (docs/imessage.md#stuck-supervisors). A supervisor session (the main one or a second mate) is stuck
// when its herdr pane sits on an interactive prompt (status "blocked") or its oldest inbox note stays unread, for
// `stuckMs`. Unread notes get a bump (tried again each poll until it goes through or the grace ends) through the inbox path the desk already uses, and the owner is texted once per
// incident if the session is still stuck `graceMs` later, then once more when it moves again. A prompt is never
// bumped: the doorbell line is typed into the pane and could answer it, so the owner is told at once. The core is free
// of the bridge so tests run on recorded JSON and plain files.
import { Database } from "bun:sqlite";
import { readdirSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync } from "node:fs";
import { cleanText } from "./clean.ts";
import type { Secondmate } from "./desk.ts";

export const BUMP_MARK = "[desk stuck-check]"; // the bump note carries it, so it is not counted as an unread note
const CALM_POLLS = 2; // an incident ends after this many polls in a row that find the session moving
const PROMPT_LINES = 12;
const SETTLE_MS = 120_000; // a limit stops each session within a minute or two; one text names them all
const RERING_MS = 600_000; // a session that hits the limit again after a ring is not rung in a loop

export type Session = { id: string; label: string; notes: number; oldest?: number; blocked: boolean; prompt?: string; limited?: boolean };
// The newest long 429 of the fleet: `at` is the failed call, `cleared` says a later call on that model went through or the reset passed.
export type Limit = { model: string; at: number; resetAt: number; cleared: boolean };
type Incident = { since: number; bumpedAt?: number; nudged?: boolean; texted?: boolean; calm: number };
export type Action = { kind: "bump" | "owner"; id: string; key: string; text: string; done(ok: boolean): void };

const span = (ms: number) => ms >= 3_600_000 ? `${Math.floor(ms / 3_600_000)} h ${Math.floor(ms % 3_600_000 / 60_000)} min` : `${Math.max(1, Math.floor(ms / 60_000))} min`;
const clock = (t: number) => `${new Date(t).toISOString().slice(5, 16).replace("T", " ")} UTC`;
const pt = (t: number) => `${new Date(t).toLocaleTimeString("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit" })} PT`;
const notes = (n: number) => `${n} note${n === 1 ? "" : "s"}`;

export class StuckWatch {
  private blockedAt = new Map<string, number>();
  private incidents = new Map<string, Incident>();
  private saved = "";
  private limit?: { resetAt: number; since: number; texted?: boolean; cleared?: boolean };
  private rung = new Map<string, number>();

  constructor(private config: { stuckMs: number; graceMs: number; file?: string }) {
    try {
      const state = JSON.parse(readFileSync(config.file ?? "", "utf8"));
      this.blockedAt = new Map(state.blockedAt);
      this.incidents = new Map(state.incidents);
      this.limit = state.limit;
      this.saved = JSON.stringify(state);
    } catch { /* no state yet */ }
  }

  private save() {
    if (!this.config.file) return;
    const json = JSON.stringify({ blockedAt: [...this.blockedAt], incidents: [...this.incidents], limit: this.limit });
    if (json === this.saved) return;
    writeFileSync(`${this.config.file}.tmp`, json, { mode: 0o600 });
    renameSync(`${this.config.file}.tmp`, this.config.file);
    this.saved = json;
  }

  // Persists the state once the caller has reported what happened to an action.
  private persisted(fn: (ok: boolean) => unknown) {
    return (ok: boolean) => { fn(ok); this.save(); };
  }

  // Takes the sessions seen now; returns the bumps and owner texts due. A text that was not sent (`done(false)`) comes again next poll.
  poll(sessions: Session[], now: number, limit?: Limit): Action[] {
    const ids = new Set(sessions.map((s) => s.id));
    for (const id of [...this.blockedAt.keys(), ...this.incidents.keys()]) {
      if (ids.has(id)) continue;
      this.blockedAt.delete(id);
      this.incidents.delete(id);
    }
    const out = sessions.flatMap((s) => this.step(s, now, limit) ?? []).concat(this.fleet(sessions.filter((s) => s.limited), now, limit) ?? []);
    this.save();
    return out;
  }

  // One text for the whole fleet when a rate limit stops it, after SETTLE_MS, and one when the limit clears.
  private fleet(limited: Session[], now: number, limit?: Limit): Action | undefined {
    if (!limit) return;
    // The reset time names the episode: each 429 of one episode gives a reset inside the same hour.
    if (!this.limit || Math.abs(limit.resetAt - this.limit.resetAt) > 3_600_000) {
      if (limit.cleared || !limited.length) return;
      this.limit = { resetAt: limit.resetAt, since: now };
    }
    const ep = this.limit;
    const key = ep.resetAt;
    if (limit.cleared) {
      if (!ep.texted || ep.cleared) return;
      return { kind: "owner", id: "fleet", key: `limit-clear-${key}`, text: `The ${limit.model} rate limit cleared. I rang each stopped session again.`, done: this.persisted((ok) => { if (ok) ep.cleared = true; }) };
    }
    if (ep.texted || !limited.length || now - ep.since < SETTLE_MS) return;
    const names = limited.map((s) => s.id.replace(/-mate-\w+$/, "")).join(", ");
    return { kind: "owner", id: "fleet", key: `limit-${key}`, text: `Rate limit on ${limit.model}. Stopped: ${names}. It resets at ${pt(limit.resetAt)}. I ring each one again when it clears.`, done: this.persisted((ok) => { if (ok) ep.texted = true; }) };
  }

  private step(s: Session, now: number, limit?: Limit): Action | undefined {
    if (!s.blocked) this.blockedAt.delete(s.id);
    else if (!this.blockedAt.has(s.id)) this.blockedAt.set(s.id, now);
    // A session stopped by the rate limit shows an error, not a question: the fleet text covers it, and it is rung when the limit clears.
    if (s.limited && limit) {
      if (!limit.cleared) return;
      const last = this.rung.get(s.id) ?? 0;
      if (now - last < this.config.stuckMs) return; // rung a short time ago: the usual stuck text comes only if the ring did not help
      if (last < limit.at && now - last >= RERING_MS) {
        return { kind: "bump", id: s.id, key: `limit-${s.id}-${limit.at}`, text: `${BUMP_MARK} The ${limit.model} rate limit cleared. Continue your work and read your inbox notes now.`, done: (ok) => { if (ok) this.rung.set(s.id, now); } };
      }
    }
    const since = Math.min(this.blockedAt.get(s.id) ?? Infinity, s.oldest ?? Infinity);
    const inc = this.incidents.get(s.id);
    if (now - since < this.config.stuckMs) return inc && this.recover(s, inc, now);
    const incident = inc ?? { since, calm: 0 };
    this.incidents.set(s.id, incident);
    incident.calm = 0;
    return incident.texted ? undefined : this.escalate(s, incident, now);
  }

  // The session moves: the incident ends after CALM_POLLS polls, with one text if the owner was told it was stuck.
  private recover(s: Session, inc: Incident, now: number): Action | undefined {
    if (++inc.calm < CALM_POLLS) return;
    if (!inc.texted) return void this.incidents.delete(s.id);
    const text = `${s.label} is moving again after ${span(now - inc.since)}. ${s.notes ? `${notes(s.notes)} still wait.` : "No notes wait."}`;
    return { kind: "owner", id: s.id, key: `${s.id}-${inc.since}`, text, done: this.persisted((ok) => ok && this.incidents.delete(s.id)) };
  }

  // Unread notes get a bump, tried again each poll until one goes through or the grace ends; a prompt and a bump that did not help get the owner text.
  private escalate(s: Session, inc: Incident, now: number): Action | undefined {
    const key = `${s.id}-${inc.since}`;
    const waiting = inc.bumpedAt !== undefined && now - inc.bumpedAt < this.config.graceMs;
    if (!s.blocked && !inc.nudged && (inc.bumpedAt === undefined || waiting)) {
      return { kind: "bump", id: s.id, key, text: `${BUMP_MARK} You look stuck: ${notes(s.notes)} wait since ${clock(s.oldest!)}. Read and act on your inbox notes now.`,
        done: this.persisted((ok) => { inc.bumpedAt ??= now; if (ok) inc.nudged = true; }) };
    }
    if (!s.blocked && waiting) return;
    const body = [`${s.label} is stuck: ${s.blocked ? "it sits on a prompt" : "it has not read its inbox"} since ${clock(inc.since)} (${span(now - inc.since)}).`,
      s.notes ? `${notes(s.notes)} wait.` : "No notes wait.",
      inc.nudged ? "I nudged it, and it is still stuck."
        : s.blocked ? "I did not nudge it: a prompt may take the nudge as its answer."
        : "My nudge did not go through."].join(" ");
    return { kind: "owner", id: s.id, key, text: s.blocked && s.prompt ? `${body}\nPrompt: ${s.prompt}` : body, done: this.persisted((ok) => { if (ok) inc.texted = true; }) };
  }
}

// Unread notes in a steering inbox: files with `ext` directly in `dir` (an acknowledged one moved to handled/), not our own bump.
export function pendingNotes(dir: string, ext: string): { count: number; oldest?: number } {
  let count = 0, oldest: number | undefined;
  let names: string[];
  try { names = readdirSync(dir); } catch { return { count }; }
  for (const name of names) {
    if (!name.endsWith(ext)) continue;
    try {
      if (readFileSync(`${dir}/${name}`, "utf8").includes(BUMP_MARK)) continue;
      const at = statSync(`${dir}/${name}`).mtimeMs;
      count++;
      oldest = Math.min(oldest ?? at, at);
    } catch { /* acknowledged while reading */ }
  }
  return { count, oldest };
}

const SECRET = /\b(?:sk|pk|ghp|gho|ghs|xox[a-z]|AKIA)[-_A-Za-z0-9]{12,}|[A-Za-z0-9+/_=-]{32,}/g;

// The last lines of a pane as one plain line: where a prompt sits. Glyphs, box lines, blank rows, paths, ids and long token-like strings are dropped.
export function promptOf(screen: string): string | undefined {
  const lines = screen.split("\n").map((l) => l.replace(/[\p{Co}\u2500-\u259f]/gu, "").trim()).filter((l) => /[\p{L}\p{N}]/u.test(l));
  const text = cleanText(lines.slice(-PROMPT_LINES).join(" | ").replace(SECRET, "[hidden]")).slice(-500);
  return text || undefined;
}

const dirs = (home: string) => new Set([home.replace(/\/+$/, ""), (() => { try { return realpathSync(home); } catch { return home; } })()]);

// Joins the inboxes with `herdr agent list`: the sessions of the main home and each second mate's home.
export async function collectSessions(o: { home: string; mates: readonly Secondmate[]; agentsJson: string; limited?: boolean; readPane(pane: string): Promise<string | undefined> }): Promise<Session[]> {
  const list: unknown = JSON.parse(o.agentsJson)?.result?.agents;
  if (!Array.isArray(list)) throw new Error("herdr agent list: no agents array");
  const targets = [
    { id: "main", label: "Firstmate (main)", home: o.home, inbox: pendingNotes(`${o.home}/state/inbox`, ".note") },
    ...o.mates.map((m) => ({ id: m.id, label: `${m.id} (second mate)`, home: m.home, inbox: pendingNotes(`${o.home}/state/${m.id}.inbox`, ".msg") })),
  ];
  const sessions: Session[] = [];
  for (const t of targets) {
    const here = dirs(t.home);
    const panes = list.filter((a) => typeof a?.pane_id === "string" && here.has(String(a.foreground_cwd ?? a.cwd ?? "").replace(/\/+$/, "")));
    // Several panes in one home: only all of them waiting on input counts, so a spare pane cannot raise the alarm.
    const blocked = panes.length > 0 && panes.every((a) => a.agent_status === "blocked");
    const screen = panes.length > 0 && (blocked || o.limited || t.inbox.count > 0) ? await o.readPane(panes[0].pane_id) : undefined;
    sessions.push({ id: t.id, label: t.label, notes: t.inbox.count, oldest: t.inbox.oldest, blocked, prompt: blocked && screen !== undefined ? promptOf(screen) : undefined,
      limited: !!screen && /rate_limit_error|exceeds retry\.maxDelayMs/.test(screen) });
  }
  return sessions;
}

// Reads the newest long 429 from omp's stats database (read-only): the reset is the failed call plus its retry-after.
export function rateLimit(file: string, now: number): Limit | undefined {
  let db: Database | undefined;
  try {
    db = new Database(file, { readonly: true });
    const e = db.query("select timestamp at, model, error_message m from messages where stop_reason='error' and error_message like '429%retry-after-ms=%' and timestamp>? order by timestamp desc limit 1")
      .get(now - 7 * 86_400_000) as { at: number; model: string; m: string } | null;
    const wait = Number(e?.m.match(/retry-after-ms=(\d+)/)?.[1]);
    if (!e || !(wait > 60_000)) return;
    const ok = db.query("select min(timestamp) t from messages where model=? and timestamp>? and stop_reason not in ('error','aborted')").get(e.model, e.at) as { t: number | null };
    const clearedAt = Math.min(ok.t ?? Infinity, e.at + wait);
    if (now >= clearedAt + RERING_MS) return;
    return { model: e.model, at: e.at, resetAt: e.at + wait, cleared: now >= clearedAt };
  } catch {
    return; // a missing or unreadable stats.db must not stop the watch
  } finally {
    db?.close();
  }
}
