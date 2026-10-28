// Renders the tasks view as colored segments. Only the visible slice of rows is ever formatted.
import { theme } from "../tui-theme/theme.ts"
import { age, counts, flatten, type Agent, type Counts, type Row, type View } from "./tasks-model.ts"

export type Seg = { text: string; fg: string; bg?: string; bold?: boolean }
export type Line = Seg[]

const clip = (s: string, w: number) => (s.length > w ? s.slice(0, Math.max(0, w - 1)) + "…" : s)
const TONE = { text: theme.text, muted: theme.muted, warn: theme.warn, ok: theme.ok }

// Fit left text and right text into width w; the left side is clipped first.
export function fit(left: Seg[], right: Seg[], w: number): Line {
  const rl = right.reduce((s, x) => s + x.text.length, 0)
  const room = Math.max(0, w - rl - 1)
  const out: Line = []
  let used = 0
  for (const s of left) {
    if (used >= room) break
    const t = clip(s.text, room - used)
    out.push({ ...s, text: t })
    used += t.length
  }
  if (used < room + 1) out.push({ text: " ".repeat(Math.max(0, w - used - rl)), fg: theme.text })
  return [...out, ...right]
}

export function header(c: Counts, o: { filter: string; typing: boolean; stalledOnly: boolean; stallMin: number }): Line[] {
  const n = (v: number, label: string, fg: string, bold = false): Seg[] => [{ text: `${v}`, fg, bold }, { text: ` ${label}   `, fg: theme.muted }]
  const counts: Line = [
    { text: " ", fg: theme.text },
    ...n(c.agents, "agents", theme.accent, true),
    ...n(c.stalled, `stalled >${o.stallMin}m`, c.stalled ? theme.error : theme.muted, c.stalled > 0),
    ...n(c.decisions, "decisions", c.decisions ? theme.warn : theme.muted, c.decisions > 0),
    ...n(c.queued, "queued", theme.text),
    ...n(c.mates, "mates", theme.text),
  ]
  const q: Line = [
    { text: " / ", fg: theme.muted },
    { text: o.filter || (o.typing ? "" : "filter"), fg: o.filter ? theme.text : theme.muted },
    ...(o.typing ? [{ text: "▏", fg: theme.accent }] : []),
    ...(o.stalledOnly ? [{ text: "   [stalled only]", fg: theme.error }] : []),
  ]
  return [counts, q]
}

type Mk = (text: string, fg: string, bold?: boolean) => Seg

function groupLine(r: Extract<Row, { kind: "mate" | "repo" }>, ind: string, seg: Mk, w: number): Line {
  const flags: Seg[] = []
  if (r.stalled) flags.push(seg(` ⚠${r.stalled}`, theme.error, true))
  if (r.decisions) flags.push(seg(` ?${r.decisions}`, theme.warn, true))
  flags.push(seg(` ${r.n} `, theme.muted))
  return fit([seg(`${ind}${r.open ? "▾" : "▸"} ${r.name}`, r.kind === "mate" ? theme.accent : theme.highlight, true)], flags, w)
}

function agentLine(r: Extract<Row, { kind: "agent" }>, ind: string, seg: Mk, w: number, on: boolean): Line {
  const a = r.agent
  const mark = a.stalled ? seg("⚠ ", theme.error, true) : a.decision ? seg("? ", theme.warn, true) : seg("● ", theme.ok)
  const where = r.key.startsWith("s:") ? `${a.mate} · ${a.repo} · ` : ""
  const when = seg(` ${age(a.quiet)} `, a.stalled ? theme.error : theme.muted, a.stalled)
  return fit([seg(ind, theme.text), mark, seg(r.open ? "▾ " : "▸ ", theme.muted), seg(`${where}${a.id}`, on ? theme.text : theme.muted, on), seg("  " + a.title, theme.muted)], [when], w)
}

function rowLine(r: Row, w: number, on: boolean): Line {
  const bg = on ? theme.border : undefined
  const ind = "  ".repeat("depth" in r ? r.depth : 0)
  const seg: Mk = (text, fg, bold = false) => ({ text, fg, bg, bold })
  if (r.kind === "stalled") return fit([seg(`⚠ STALLED  ${r.n}`, theme.error, true)], r.shown < r.n ? [seg(` top ${r.shown} · ⏎ shows all `, theme.muted)] : [], w)
  if (r.kind === "agent") return agentLine(r, ind, seg, w, on)
  if (r.kind === "detail") return fit([seg(ind + "  ", theme.text), seg(r.label.padEnd(9), theme.muted), seg(r.text, TONE[r.tone])], [], w)
  return groupLine(r, ind, seg, w)
}

// Rows [top, top+h) as lines. Cost is O(h), never O(rows).
export function viewport(rows: Row[], top: number, h: number, w: number, cursor: number): Line[] {
  const out: Line[] = []
  for (let i = top; i < Math.min(rows.length, top + h); i++) out.push(rowLine(rows[i], w, i === cursor))
  return out
}

export const plain = (lines: Line[]) => lines.map(l => l.map(s => s.text).join("").trimEnd()).join("\n")

export function footer(rows: number, cursor: number, loaded: boolean): Line {
  const m = (t: string): Seg => ({ text: t, fg: theme.muted })
  return [m(` ${loaded ? `${rows ? cursor + 1 : 0}/${rows}` : "loading…"}  ↑↓ move  ⏎ open  e/E all  / find  s stalled  r reload  d queue  t board  q quit`)]
}

// Plain-text snapshot for `--once`; `expandAll` opens every group and agent.
export function snapshot(agents: Agent[], queued: number, view: View, o: { width: number; stallMin: number; expandAll: boolean }): string {
  const rows = flatten(agents, { ...view, all: o.expandAll })
  const head = header(counts(agents, queued), { filter: view.filter, typing: false, stalledOnly: view.stalledOnly, stallMin: o.stallMin })
  return plain([...head, ...viewport(rows, 0, rows.length, o.width, -1)]) + (rows.length ? "" : "\n  no agents match")
}
