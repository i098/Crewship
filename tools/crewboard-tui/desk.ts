// Read-only front desk health view: the iMessage bridge's outbox folders, desk.log, routing.jsonl and unit state (apps/imessage/bridge.ts, outbox.ts).
// The health figures are counts, ages and latencies. The recent turns list shows message text (in, route, out) from routing.jsonl, locally only.
import { readdirSync, readFileSync, statSync } from "node:fs"
import { spawnSync } from "node:child_process"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { age } from "./tasks-model.ts"
import { plain, type Line, type Seg } from "./tasks-view.ts"
import { parseTurns, type Turn } from "./traffic.ts"

const DAY_MS = 86_400_000
const UNIT = "fm-imessage"
export const STATE_DIR = process.env.FM_IMESSAGE_STATE ?? `${process.env.HOME}/.local/state/${UNIT}`

export type Desk = {
  unit: string // `systemctl --user is-active` output
  lastLogMs?: number // newest desk.log line
  pending: number; oldestPendingMs?: number
  retries: number | null; retrying: number // highest try number among pending items and how many have one; null: journal unreadable
  sent24h: number; lastSentMs?: number
  dead24h: number; deadTotal: number; lastDeadMs?: number
  latency: { n: number; last?: number; median?: number; p95?: number } // seconds from inbox-accepted to response-confirmed, last 24h
  turns: Turn[] // oldest first
}

// desk.log lines are `<ISO time> <message id> <event>`; other lines are skipped.
export function parseLog(text: string): { t: number; id: string; ev: string }[] {
  const out: { t: number; id: string; ev: string }[] = []
  for (const l of text.split("\n")) {
    const m = /^(\d{4}-\d\d-\d\dT[\d:.]+Z) (\S+) (\S+)/.exec(l)
    const t = m ? Date.parse(m[1]) : NaN
    if (m && !Number.isNaN(t)) out.push({ t, id: m[2], ev: m[3] })
  }
  return out
}

// Seconds from a message's inbox-accepted to its first later response-confirmed, for responses at or after `since`, oldest response first.
export function replyLatencies(events: { t: number; id: string; ev: string }[], since: number): number[] {
  const accepted = new Map<string, number>()
  const out: { at: number; s: number }[] = []
  for (const e of events) {
    if (e.ev === "inbox-accepted") accepted.set(e.id, e.t)
    else if (e.ev === "response-confirmed" && accepted.has(e.id)) {
      if (e.t >= since) out.push({ at: e.t, s: (e.t - accepted.get(e.id)!) / 1000 })
      accepted.delete(e.id)
    }
  }
  return out.sort((a, b) => a.at - b.at).map(x => x.s)
}

// Nearest-rank percentile of an ascending list.
const pct = (sorted: number[], p: number) => sorted[Math.max(0, Math.ceil(p * sorted.length) - 1)]

export function latencyStats(s: number[]): Desk["latency"] {
  const sorted = [...s].sort((a, b) => a - b)
  return { n: s.length, last: s.at(-1), median: sorted.length ? pct(sorted, 0.5) : undefined, p95: sorted.length ? pct(sorted, 0.95) : undefined }
}

// The bridge logs `outbox item <seq> failed (try <n>), ...` to its journal; a seq's highest n is its retry count.
export function retryCounts(journal: string): Map<number, number> {
  const out = new Map<number, number>()
  for (const m of journal.matchAll(/outbox item (\d+) failed \(try (\d+)\)/g)) out.set(Number(m[1]), Math.max(out.get(Number(m[1])) ?? 0, Number(m[2])))
  return out
}

export type Probe = { unit: string; journal: string | null }

export function probe(): Probe {
  const run = (args: string[]) => spawnSync(args[0], args.slice(1), { encoding: "utf8", timeout: 15000, maxBuffer: 256 << 20 })
  const unit = run(["systemctl", "--user", "is-active", UNIT]).stdout?.trim() || "unknown"
  const j = run(["journalctl", "--user", "-u", UNIT, "--since", "-24h", "-o", "cat", "--no-pager"])
  return { unit, journal: j.status === 0 ? j.stdout : null }
}

const list = (dir: string): string[] => { try { return readdirSync(dir) } catch { return [] } }
const mtime = (f: string) => { try { return statSync(f).mtimeMs } catch { return undefined } } // a file moved since the listing is skipped

export function loadDesk(dir: string, nowMs: number, p: Probe): Desk {
  const since = nowMs - DAY_MS
  const pend = list(join(dir, "outbox")).filter(f => /^\d+\.json$/.test(f)).map(f => ({ seq: parseInt(f, 10), at: mtime(join(dir, "outbox", f)) })).filter(x => x.at !== undefined)
  const rc = p.journal === null ? null : retryCounts(p.journal)
  const tries = rc ? pend.map(x => rc.get(x.seq) ?? 0).filter(n => n > 0) : []
  const log = parseLog(readText(join(dir, "desk.log")))
  const sent = log.filter(e => e.ev === "transport-accepted" || e.ev === "history-reconciled").map(e => e.t) // a retry that finds the bubble already in transport history logs history-reconciled instead
  const dead = list(join(dir, "outbox-dead")).map(f => /^(\d+)-\d+\.json$/.exec(f)).filter(m => m).map(m => Number(m![1])) // file name starts with the burial time
  return {
    unit: p.unit,
    lastLogMs: log.at(-1)?.t,
    pending: pend.length, oldestPendingMs: pend.length ? Math.min(...pend.map(x => x.at!)) : undefined,
    retries: rc ? Math.max(0, ...tries) : null, retrying: tries.length,
    sent24h: sent.filter(t => t >= since).length, lastSentMs: sent.length ? Math.max(...sent) : undefined,
    dead24h: dead.filter(t => t >= since).length, deadTotal: dead.length, lastDeadMs: dead.length ? Math.max(...dead) : undefined,
    latency: latencyStats(replyLatencies(log, since)),
    turns: parseTurns(readText(join(dir, "routing.jsonl"))),
  }
}

const readText = (f: string) => { try { return readFileSync(f, "utf8") } catch { return "" } }

const ago = (ms: number | undefined, now: number) => (ms === undefined ? "never" : `${age((now - ms) / 1000)} ago`)
const secs = (s: number | undefined) => (s === undefined ? "–" : s < 90 ? `${s.toFixed(1)}s` : age(s))

const flat = (s: string) => s.replace(/\s+/g, " ").trim()
const cut = (s: string, w: number) => (s.length > w ? s.slice(0, Math.max(0, w - 1)) + "…" : s)

export function deskLines(d: Desk, nowMs: number, width = 100, height = 40): Line[] {
  const up = d.unit === "active"
  const row = (label: string, value: Seg[]): Line => [{ text: `  ${label.padEnd(18)}`, fg: theme.muted }, ...value]
  const v = (text: string, fg = theme.text, bold = false): Seg => ({ text, fg, bold })
  const m = (text: string): Seg => v(text, theme.muted)
  const retries = d.retries === null ? "journal unreadable" : d.retrying ? `${d.retries} (${d.retrying} item${d.retrying > 1 ? "s" : ""} retrying)` : "0"
  const stale = d.oldestPendingMs !== undefined && nowMs - d.oldestPendingMs > 120_000
  const head: Line[] = [
    [v(" "), v(up ? "● bridge up" : `○ bridge down (${d.unit})`, up ? theme.ok : theme.error, true), m(`   last desk log ${ago(d.lastLogMs, nowMs)}`)],
    [],
    row("pending bubbles", [v(`${d.pending}`, d.pending ? theme.warn : theme.muted, d.pending > 0)]),
    row("oldest pending", [d.oldestPendingMs === undefined ? m("none") : v(age((nowMs - d.oldestPendingMs) / 1000), stale ? theme.error : theme.warn)]),
    row("retries", [d.retries ? v(retries, theme.warn) : m(retries)]),
    row("sent, last 24h", [v(`${d.sent24h}`, d.sent24h ? theme.ok : theme.muted), m(`   last ${ago(d.lastSentMs, nowMs)}`)]),
    row("failed, last 24h", [v(`${d.dead24h}`, d.dead24h ? theme.error : theme.muted, d.dead24h > 0), m(`   ${d.deadTotal} dead in all, last ${ago(d.lastDeadMs, nowMs)}`)]),
    [],
    row("desk reply, 24h", [v(`${d.latency.n}`), m(` replies   last ${secs(d.latency.last)}   median ${secs(d.latency.median)}   p95 ${secs(d.latency.p95)}`)]),
  ]
  // Two rows per turn, newest first, as many as fit; text is cut to the pane width.
  const room = Math.max(0, Math.floor((height - head.length - 2) / 2))
  const shown = d.turns.slice(-room).reverse()
  if (!shown.length) return head
  return [...head, [], [v(" recent turns", theme.accent, true), m("   in, route, out; newest first")], ...shown.flatMap((t): Line[] => {
    const tag = `[${cut(t.route, 24)}]`
    return [
      [m(`  ${age((nowMs - t.at) / 1000).padStart(5)} `), v("in ", theme.muted), v(cut(flat(t.text), Math.max(10, width - 11 - tag.length - 1)), theme.text), v(" "), v(tag, t.route === "pending" ? theme.warn : theme.accent)],
      [m("        "), v("out ", theme.muted), t.reply ? v(cut(flat(t.reply), Math.max(10, width - 12)), theme.ok) : m("–")],
    ]
  })]
}

export const deskFooter = (): Line => [{ text: " r reload  m back  t tasks  d queue  q quit   read-only", fg: theme.muted }]

export const deskSnapshot = (d: Desk, nowMs: number, width = 100, height = 40) => plain(deskLines(d, nowMs, width, height))
