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
const rank = { outdated: 0, unknown: 1, "up to date": 2 } as const

const renderer = await createCliRenderer({ exitOnCtrlC: true })
const column = new BoxRenderable(renderer, { flexDirection: "column", width: "100%" })
const header = new TextRenderable(renderer, { content: "", flexShrink: 0 })
const panel = new BoxRenderable(renderer, {
  border: true, borderStyle: "rounded", borderColor: theme.border, titleColor: theme.text,
  title: " Components · installed vs latest ", titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexShrink: 0,
})
const body = new TextRenderable(renderer, { content: "" })
panel.add(body)
column.add(header)
column.add(panel)
renderer.root.add(column)

let sel = 0
let top = 0

function draw() {
  const W = Math.min(130, renderer.width)
  column.width = W
  const list = rows().sort((a, b) => rank[a.state] - rank[b.state] || a.name.localeCompare(b.name))
  const count = (st: State) => list.filter(r => r.state === st).length
  const ok = count("up to date"), old = count("outdated"), unk = count("unknown")
  const inner = W - 4
  const barOk = Math.round((ok / list.length) * inner), barOld = Math.round((old / list.length) * inner)
  const view = Math.max(3, renderer.height - 8)
  sel = Math.max(0, Math.min(sel, list.length - 1))
  top = Math.max(0, Math.min(sel < top ? sel : sel >= top + view ? sel - view + 1 : top, list.length - view))
  const stamp = checkedAt ? new Date(checkedAt).toTimeString().slice(0, 8) : "…"
  header.content = styled([
    [s(" FLEET HEALTH ", theme.bg, { bg: theme.accent, b: true }), s("  "), s(`${ok} up to date`, theme.ok, { b: true }), s("  "), s(`${old} outdated`, theme.warn, { b: true }), s("  "), s(`${unk} unknown`, theme.muted, { b: true })],
    [s("█".repeat(barOk), theme.ok), s("█".repeat(barOld), theme.warn), s("█".repeat(Math.max(0, inner - barOk - barOld)), theme.border)],
    [s(`checked ${stamp}${busy ? " · fetching…" : ""} · installed every ${SLOW_MS / 60_000}m · latest cached ${CACHE_MS / 60_000}m · `, theme.muted), s("↑↓", theme.text, { b: true }), s(" scroll  ", theme.muted), s("r", theme.text, { b: true }), s(" refresh  ", theme.muted), s("q", theme.text, { b: true }), s(" quit", theme.muted)],
  ])
  const nameW = Math.max(...list.map(r => r.name.length), 9)
  const groupW = Math.max(...list.map(r => r.group.length), 5)
  const out: Line[] = [[s("  " + "COMPONENT".padEnd(nameW + 2) + "KIND".padEnd(groupW + 2) + "INSTALLED".padEnd(16) + "LATEST".padEnd(16) + "STATE", theme.muted, { b: true })]]
  list.slice(top, top + view).forEach((r, i) => {
    const chosen = top + i === sel
    const o = chosen ? { bg: theme.border } : {}
    out.push([
      s(chosen ? "▌ " : "  ", theme.accent, o),
      s(r.name.padEnd(nameW + 2), theme.text, { ...o, b: true }),
      s(r.group.padEnd(groupW + 2), theme.muted, o),
      s((r.installed ?? "—").slice(0, 14).padEnd(16), theme.text, o),
      s((r.latest ?? "—").slice(0, 14).padEnd(16), theme.text, o),
      s("● " + r.state, stateColor[r.state], o),
      s(r.note ? "  " + r.note : "", theme.muted, o),
    ])
  })
  body.content = styled(out)
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
