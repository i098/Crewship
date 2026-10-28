// Read-only decision queue view: state/decision-queue/*.rec per home (format: blueprint/patches/firstmate/0006-decision-queue.patch).
import { readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { age } from "./tasks-model.ts"
import { mateName } from "./tasks-source.ts"
import { fit, plain, type Line, type Seg } from "./tasks-view.ts"

export const STATES = ["open", "in progress", "answered", "closed", "stuck"] as const
export type QState = (typeof STATES)[number]
export type Rec = { mate: string; origin: string; key: string; note: string; state: QState; since: number }
export type QRow = { kind: "mate"; key: string; mate: string; n: Record<QState, number> } | { kind: "rec"; key: string; rec: Rec }

const COLOR: Record<QState, string> = { open: theme.warn, "in progress": theme.accent, answered: theme.ok, closed: theme.muted, stuck: theme.error }
const MARK: Record<QState, string> = { open: "?", "in progress": "●", answered: "✓", closed: "·", stuck: "⚠" }

// A record is key=value lines; the first value wins, as dq_get reads it. Unknown states are skipped.
export function parseRec(text: string, mate: string): Rec | null {
  const f: Record<string, string> = {}
  for (const l of text.split("\n")) {
    const i = l.indexOf("=")
    if (i > 0 && !(l.slice(0, i) in f)) f[l.slice(0, i)] = l.slice(i + 1)
  }
  const state: QState | undefined = f.state === "queued" ? "open" : f.state === "dispatched" ? "in progress" : f.state === "stuck" ? "stuck"
    : f.state === "closed" ? (f.close_reason === "answered" ? "answered" : "closed") : undefined
  if (!state) return null
  const since = Number((state === "answered" || state === "closed" ? f.closed_at : undefined) || f.enqueued_at) || 0
  return { mate, origin: f.origin ?? "", key: f.key ?? "", note: f.note ?? "", state, since }
}

export function loadQueue(homes: string[]): Rec[] {
  const out: Rec[] = []
  for (const home of homes) {
    const dir = join(home, "state", "decision-queue")
    let names: string[] = []
    try { names = readdirSync(dir) } catch {}
    for (const n of names) {
      if (!n.endsWith(".rec")) continue
      try {
        const r = parseRec(readFileSync(join(dir, n), "utf8"), mateName(home))
        if (r) out.push(r)
      } catch {}
    }
  }
  return out
}

export function totals(recs: Rec[]): Record<QState, number> {
  const n = Object.fromEntries(STATES.map(s => [s, 0])) as Record<QState, number>
  for (const r of recs) n[r.state]++
  return n
}

// One head per mate (its counts), then its records by state order, oldest first.
export function queueRows(recs: Rec[]): QRow[] {
  const byMate = new Map<string, Rec[]>()
  for (const r of recs) byMate.get(r.mate)?.push(r) ?? byMate.set(r.mate, [r])
  const rows: QRow[] = []
  for (const mate of [...byMate.keys()].sort()) {
    const list = byMate.get(mate)!.sort((a, b) => STATES.indexOf(a.state) - STATES.indexOf(b.state) || a.since - b.since)
    rows.push({ kind: "mate", key: `m:${mate}`, mate, n: totals(list) })
    for (const r of list) rows.push({ kind: "rec", key: `${mate}/${r.origin}+${r.key}`, rec: r })
  }
  return rows
}

const countSegs = (n: Record<QState, number>, bg?: string): Seg[] =>
  STATES.flatMap(s => [{ text: `${n[s]}`, fg: n[s] ? COLOR[s] : theme.muted, bg, bold: n[s] > 0 }, { text: ` ${s}   `, fg: theme.muted, bg }])

export const queueHeader = (recs: Rec[]): Line[] => [[{ text: " ", fg: theme.text }, ...countSegs(totals(recs))]]

function rowLine(r: QRow, w: number, now: number, on: boolean): Line {
  const bg = on ? theme.border : undefined
  if (r.kind === "mate") return fit([{ text: `▾ ${r.mate}`, fg: theme.accent, bg, bold: true }], countSegs(r.n, bg), w)
  const x = r.rec
  return fit([
    { text: `  ${MARK[x.state]} `, fg: COLOR[x.state], bg, bold: true },
    { text: x.state.padEnd(12), fg: COLOR[x.state], bg },
    { text: `${x.origin} · ${x.key}`, fg: on ? theme.text : theme.highlight, bg, bold: on },
    { text: `  ${x.note}`, fg: theme.muted, bg },
  ], [{ text: ` ${x.since ? age(now - x.since) : "?"} `, fg: theme.muted, bg }], w)
}

// Rows [top, top+h) as lines. Cost is O(h).
export function queueViewport(rows: QRow[], top: number, h: number, w: number, now: number, cursor: number): Line[] {
  const out: Line[] = []
  for (let i = top; i < Math.min(rows.length, top + h); i++) out.push(rowLine(rows[i], w, now, i === cursor))
  return out
}

export function queueFooter(rows: number, cursor: number): Line {
  return [{ text: ` ${rows ? cursor + 1 : 0}/${rows}  ↑↓ move  r reload  d back  q quit   read-only`, fg: theme.muted }]
}

export function queueSnapshot(recs: Rec[], now: number, width: number): string {
  const rows = queueRows(recs)
  return plain([...queueHeader(recs), ...queueViewport(rows, 0, rows.length, width, now, -1)]) + (rows.length ? "" : "\n  no queued decisions")
}
