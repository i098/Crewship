#!/usr/bin/env bun
// Read-only fleet health TUI: every Crewship component, installed vs latest. Never installs or upgrades.
import { BoxRenderable, StyledText, TextRenderable, bg, bold, createCliRenderer, fg, type TextChunk } from "@opentui/core"
import { theme } from "../tui-theme/theme.ts"
import { components } from "./components.ts"
import { CACHE_MS, compare, loadCache, refreshLatest } from "./latest.ts"

const SLOW_MS = 5 * 60_000
type State = "up to date" | "outdated" | "unknown"
type Row = { name: string; group: string; installed: string | null; latest: string | null; state: State; note: string }

const cache = loadCache()
const installed = new Map<string, string | null>()
let busy = false
let checkedAt = 0

function rows(): Row[] {
  return components.map(c => {
    const have = installed.get(c.name) ?? null
    const latest = cache[c.name]?.version ?? null
    let state: State = "unknown"
    let note = ""
    if (c.source.kind === "none") note = c.source.note
    else if (have === null) note = installed.has(c.name) ? "not installed" : "checking…"
    else if (latest === null) note = cache[c.name]?.error ?? (cache[c.name] ? "no release published" : "checking…")
    else state = compare(have, latest) >= 0 ? "up to date" : "outdated"
    if (state !== "unknown" && cache[c.name]?.error) note = `stale: ${cache[c.name]!.error}`
    return { name: c.name, group: c.group, installed: have, latest, state, note }
  })
}

type Line = TextChunk[]
function s(text: string, color: string = theme.text, o: { bg?: string; b?: boolean } = {}): TextChunk {
  let c = fg(color)(text)
  if (o.bg) c = bg(o.bg)(c)
  return o.b ? bold(c) : c
}
const styled = (lines: Line[]) => {
  const out: TextChunk[] = []
  lines.forEach((l, i) => { if (i) out.push(s("\n")); out.push(...l) })
  return new StyledText(out)
}
const stateColor = { "up to date": theme.ok, outdated: theme.warn, unknown: theme.muted } as const
const chip = (state: State) => s(` ${state.toUpperCase()} `.padEnd(13), theme.bg, { bg: stateColor[state], b: true })
const rank = { outdated: 0, unknown: 1, "up to date": 2 } as const
const SECTIONS: [string, string][] = [
  ["native", "Native tools"], ["runtime", "Runtimes"], ["npm", "npm packages"],
  ["python", "Python packages"], ["omp plugin", "omp plugins"], ["source", "Built from source"],
]

const renderer = await createCliRenderer({ exitOnCtrlC: true })
const column = new BoxRenderable(renderer, { flexDirection: "column", width: "100%" })
const header = new TextRenderable(renderer, { content: "", flexShrink: 0 })
const panel = new BoxRenderable(renderer, {
  border: true, borderStyle: "rounded", borderColor: theme.border, paddingLeft: 1, paddingRight: 1, flexShrink: 0,
})
const body = new TextRenderable(renderer, { content: "" })
const footer = new TextRenderable(renderer, { content: "", flexShrink: 0 })
panel.add(body)
column.add(header)
column.add(panel)
column.add(footer)
renderer.root.add(column)

let sel = 0
let top = 0

function draw() {
  const W = Math.min(120, renderer.width)
  column.width = W
  const all = rows()
  const count = (st: State) => all.filter(r => r.state === st).length
  const ok = count("up to date"), old = count("outdated"), unk = count("unknown")
  const inner = W - 4
  const barOk = Math.round((ok / all.length) * inner), barOld = Math.round((old / all.length) * inner)
  const stamp = checkedAt ? new Date(checkedAt).toTimeString().slice(0, 8) : "…"
  header.content = styled([
    [s(" ◆ FLEET HEALTH ", theme.bg, { bg: theme.accent, b: true }), s(`  ${all.length} components`, theme.muted), s(busy ? "   ⟳ fetching…" : `   checked ${stamp}`, busy ? theme.accent : theme.muted)],
    [s("")],
    [s(` ${ok} `, theme.bg, { bg: theme.ok, b: true }), s(" up to date   ", theme.text), s(` ${old} `, theme.bg, { bg: theme.warn, b: true }), s(" outdated   ", theme.text), s(` ${unk} `, theme.bg, { bg: theme.muted, b: true }), s(" unknown", theme.text)],
    [s("█".repeat(barOk), theme.ok), s("█".repeat(barOld), theme.warn), s("█".repeat(Math.max(0, inner + 2 - barOk - barOld)), theme.border)],
  ])

  const nameW = Math.max(...all.map(r => r.name.length), 9) + 2
  const verW = 14
  const order: Row[] = []
  const lines: { line: Line; index: number }[] = []
  for (const [key, title] of SECTIONS) {
    const group = all.filter(r => r.group === key).sort((a, b) => rank[a.state] - rank[b.state] || a.name.localeCompare(b.name))
    if (!group.length) continue
    const behind = group.filter(r => r.state === "outdated").length
    if (lines.length) lines.push({ line: [s("")], index: -1 })
    lines.push({
      line: [s("▸ ", theme.accent), s(title, theme.text, { b: true }), s(`  ${group.length}`, theme.muted), ...(behind ? [s(`  ${behind} outdated`, theme.warn)] : group.every(r => r.state === "up to date") ? [s("  all current", theme.ok)] : [s("  not comparable", theme.muted)])],
      index: -1,
    })
    lines.push({ line: [s("  " + "COMPONENT".padEnd(nameW) + "INSTALLED".padEnd(verW) + "LATEST".padEnd(verW + 2) + "STATE", theme.muted)], index: -1 })
    for (const r of group) {
      const chosen = order.length === sel
      const o = chosen ? { bg: theme.border } : {}
      const note = r.note ? "  " + r.note : ""
      lines.push({
        index: order.length,
        line: [
          s(chosen ? "▌ " : "  ", theme.accent, o),
          s(r.name.padEnd(nameW), theme.text, { ...o, b: true }),
          s((r.installed ?? "—").slice(0, verW - 2).padEnd(verW), r.installed ? theme.text : theme.muted, o),
          s((r.latest ?? "—").slice(0, verW - 2).padEnd(verW), r.state === "outdated" ? theme.warn : r.latest ? theme.text : theme.muted, o),
          s("  ", theme.text, o),
          chip(r.state),
          s(note.slice(0, Math.max(0, inner - nameW - verW * 2 - 19)), theme.muted, o),
        ],
      })
      order.push(r)
    }
  }
  sel = Math.max(0, Math.min(sel, order.length - 1))
  // Section rows have index -1, so size the view over lines and keep the selected line in it.
  const at = lines.findIndex(l => l.index === sel)
  const view = Math.max(5, renderer.height - 12)
  top = Math.max(0, Math.min(at < top ? at : at >= top + view ? at - view + 1 : top, Math.max(0, lines.length - view)))
  body.content = styled(lines.slice(top, top + view).map(l => l.line))
  const pick = order[sel]
  footer.content = styled([
    [s(pick ? ` ${pick.name} ` : "", theme.text, { b: true }), s(pick?.note ?? "", theme.muted)],
    [s(` installed every ${SLOW_MS / 60_000}m · latest cached ${CACHE_MS / 60_000}m   `, theme.muted), s("↑↓", theme.text, { b: true }), s(" move  ", theme.muted), s("r", theme.text, { b: true }), s(" refresh  ", theme.muted), s("q", theme.text, { b: true }), s(" quit", theme.muted)],
  ])
  renderer.requestRender()
}

async function refresh(): Promise<void> {
  if (busy) return
  busy = true
  draw()
  try {
    await Promise.all(components.map(async c => { installed.set(c.name, await c.installed().catch(() => null)); }))
    checkedAt = Date.now()
    draw()
    await refreshLatest(components, cache, draw)
  } finally {
    busy = false
    draw()
  }
}

draw()
void refresh()
const timer = setInterval(() => void refresh(), SLOW_MS)
renderer.on("resize", draw)
renderer.keyInput.on("keypress", (k: { name: string }) => {
  if (k.name === "q") { clearInterval(timer); renderer.destroy(); process.exit(0) }
  if (k.name === "r") void refresh()
  if (k.name === "down" || k.name === "j") { sel++; draw() }
  if (k.name === "up" || k.name === "k") { sel--; draw() }
})
