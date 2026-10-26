#!/usr/bin/env bun
// Read-only viewer for the crewboard message board. Only runs `crewboard sub` and `crewboard topics`; never publishes.
import { BoxRenderable, TextRenderable, StyledText, RGBA, createCliRenderer, type TextChunk } from "@opentui/core"
import { theme } from "../tui-theme/theme.ts"
import { fetchSummaries, type Summaries } from "./summaries.ts"
import { buildAgents, counts, DEFAULT_STALL_SEC, flatten, type Agent, type Row as TaskRow, type View } from "./tasks-model.ts"
import { findHomes, loadHomes } from "./tasks-source.ts"
import { footer as tasksFooter, header as tasksHeader, snapshot, viewport, type Line } from "./tasks-view.ts"

// Flags: --once (plain tasks snapshot, then exit), --tasks (open on the tasks view), --expand, --filter TEXT, --stall-min N, --width N; other args are firstmate home paths.
const argv = process.argv.slice(2)
const flag = (n: string) => argv.includes(n)
const flagVal = (n: string) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : undefined }
const VALUE_FLAGS = ["--filter", "--stall-min", "--width"]
const homeArgs = argv.filter((a, i) => !a.startsWith("--") && !VALUE_FLAGS.includes(argv[i - 1]))
const stallMin = Number(flagVal("--stall-min") ?? DEFAULT_STALL_SEC / 60)
const REFRESH_TASKS_MS = 15_000

if (flag("--once")) {
  const { agents, queued } = buildAgents(await loadHomes(findHomes(homeArgs)), Math.floor(Date.now() / 1000), stallMin * 60)
  console.log(snapshot(agents, queued, { expanded: new Set(), filter: flagVal("--filter") ?? "", stalledOnly: false }, { width: Number(flagVal("--width") ?? 100), stallMin, expandAll: flag("--expand") }))
  process.exit(0)
}

type Msg = { seq: number; ts: string; topic: string; from: string | null; body: string }
type Topic = { name: string; msgs: Msg[]; unread: number; newest: number }
type Row = { kind: "head"; group: string; unread: number } | { kind: "topic"; topic: Topic } | { kind: "summary"; text: string }

const TZ = "America/Los_Angeles"
const LEFT_W = 38
const MAX_BODY_LINES = 40
const SUMMARY_EVERY_MS = 10_000
let summaries: Summaries = new Map()
const topics = new Map<string, Topic>()
let connected = false
let boot: string | null = null
let lastSeq = 0
let headSeq = -1 // seqs <= headSeq were history at connect time and count as read
let selected: string | null = null
let picked = false // until the user moves, the selection tracks the newest topic
let scroll = 0 // lines above the bottom; 0 follows the newest message
let total = 0

// ---- board feed ----
function ingest(line: string) {
  let o: any
  try { o = JSON.parse(line) } catch { return }
  if (o.boot !== undefined && o.topic === undefined) {
    if (boot !== o.boot) { boot = o.boot; lastSeq = 0 }
    if (headSeq < 0) headSeq = o.seq
    return
  }
  if (o.topic === undefined || o.seq <= lastSeq) return
  lastSeq = o.seq
  let t = topics.get(o.topic)
  if (!t) topics.set(o.topic, (t = { name: o.topic, msgs: [], unread: 0, newest: 0 }))
  t.msgs.push(o)
  t.newest = o.seq
  total++
  if (o.seq > headSeq && o.topic !== selected) t.unread++
}

async function follow() {
  for (;;) {
    const args = ["crewboard", "sub", "*", "--json"]
    args.push("--since", String(lastSeq))
    if (boot) args.push("--boot", boot)
    try {
      const p = Bun.spawn(args, { stdout: "pipe", stderr: "ignore" })
      connected = true
      let buf = ""
      const dec = new TextDecoder()
      for await (const chunk of p.stdout) {
        buf += dec.decode(chunk, { stream: true })
        let i
        while ((i = buf.indexOf("\n")) >= 0) { ingest(buf.slice(0, i)); buf = buf.slice(i + 1) }
        draw()
      }
    } catch {}
    connected = false
    draw()
    await Bun.sleep(2000)
  }
}

async function followSummaries() {
  for (;;) {
    summaries = await fetchSummaries()
    draw()
    await Bun.sleep(SUMMARY_EVERY_MS)
  }
}

// ---- model ----
const groupOf = (name: string) => {
  const id = name.replace(/^task\//, "")
  const m = id.match(/^([a-z0-9]+)-/)
  return name === "fleet" || name === "fm" || !m ? "shared" : m[1]
}
const label = (name: string) => name.replace(/^task\//, "")

function rows(): Row[] {
  const groups = new Map<string, Topic[]>()
  for (const t of topics.values()) {
    const g = groupOf(t.name)
    if (!groups.has(g)) groups.set(g, [])
    groups.get(g)!.push(t)
  }
  const out: Row[] = []
  const ordered = [...groups.entries()].map(([g, ts]) => {
    ts.sort((a, b) => b.newest - a.newest)
    return { g, ts, newest: ts[0].newest }
  }).sort((a, b) => b.newest - a.newest)
  for (const { g, ts } of ordered) {
    out.push({ kind: "head", group: g, unread: ts.reduce((s, t) => s + t.unread, 0) })
    for (const t of ts) {
      out.push({ kind: "topic", topic: t })
      const text = summaries.get(t.name)
      if (text) out.push({ kind: "summary", text })
    }
  }
  return out
}

// ---- rendering ----
const hex = (c: string) => RGBA.fromHex(c)
const ch = (text: string, fg: string, o: { bg?: string; bold?: boolean } = {}): TextChunk =>
  ({ __isChunk: true, text, fg: hex(fg), bg: o.bg ? hex(o.bg) : undefined, attributes: o.bold ? 1 : 0 }) as TextChunk
const NL = ch("\n", theme.text)
const clip = (s: string, w: number) => (s.length > w ? s.slice(0, Math.max(0, w - 1)) + "…" : s)

const fmt = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hourCycle: "h23", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
function stamp(ts: string) {
  const p = Object.fromEntries(fmt.formatToParts(new Date(ts)).map(x => [x.type, x.value]))
  const today = fmt.formatToParts(new Date()).find(x => x.type === "day")!.value === p.day
  return `${today ? "" : `${p.month}-${p.day} `}${p.hour}:${p.minute}:${p.second}`
}

function wrap(body: string, w: number): string[] {
  const out: string[] = []
  for (const raw of body.replace(/\t/g, "  ").split("\n")) {
    if (raw === "") { out.push(""); continue }
    let s = raw
    while (s.length > w) {
      let cut = s.lastIndexOf(" ", w)
      if (cut < w / 2) cut = w
      out.push(s.slice(0, cut).trimEnd())
      s = s.slice(cut).trimStart()
    }
    out.push(s)
  }
  return out.length > MAX_BODY_LINES ? [...out.slice(0, MAX_BODY_LINES), `… (+${out.length - MAX_BODY_LINES} lines)`] : out
}

const colors = [theme.accent, theme.output, theme.highlight, theme.ok, theme.warn]
const senderColor = (s: string) => colors[[...s].reduce((a, c) => a + c.charCodeAt(0), 0) % colors.length]

const renderer = await createCliRenderer({ exitOnCtrlC: true })
const root = new BoxRenderable(renderer, { flexDirection: "column", width: "100%", height: "100%" })
const main = new BoxRenderable(renderer, { flexDirection: "row", flexGrow: 1 })
const left = new BoxRenderable(renderer, { border: true, borderColor: theme.border, title: " Topics ", titleColor: theme.accent, width: LEFT_W, titleAlignment: "left" })
const right = new BoxRenderable(renderer, { border: true, borderColor: theme.border, title: " Messages ", titleColor: theme.accent, flexGrow: 1 })
const leftText = new TextRenderable(renderer, { content: "", fg: theme.text })
const rightText = new TextRenderable(renderer, { content: "", fg: theme.text })
const footer = new TextRenderable(renderer, { content: "", height: 1, fg: theme.muted })
left.add(leftText); right.add(rightText); main.add(left); main.add(right)
const tasksBox = new BoxRenderable(renderer, { border: true, borderColor: theme.border, title: " Tasks ", titleColor: theme.accent, flexGrow: 1, visible: false })
const tasksText = new TextRenderable(renderer, { content: "", fg: theme.text })
tasksBox.add(tasksText)
root.add(main); root.add(tasksBox); root.add(footer); renderer.root.add(root)

let listTop = 0

function leftPane(list: Row[], innerH: number) {
  const lw = LEFT_W - 2
  const lc: TextChunk[] = []
  list.slice(listTop, listTop + innerH).forEach((r, i) => {
    if (i) lc.push(NL)
    if (r.kind === "head") {
      const u = r.unread ? ` ${r.unread} new` : ""
      lc.push(ch(clip(`▾ ${r.group}`, lw - u.length).padEnd(lw - u.length), theme.accent, { bold: true }))
      if (u) lc.push(ch(u, theme.warn, { bold: true }))
    } else if (r.kind === "summary") {
      lc.push(ch("    " + clip(r.text, lw - 4), theme.muted))
    } else {
      const t = r.topic, on = t.name === selected
      const u = t.unread ? ` ${t.unread}` : ""
      const cnt = ` ${t.msgs.length}`
      const nameW = lw - 2 - u.length - cnt.length
      const bg = on ? theme.border : undefined
      lc.push(ch("  " + clip(label(t.name), nameW).padEnd(nameW), on ? theme.text : theme.muted, { bg, bold: on }))
      lc.push(ch(cnt, theme.muted, { bg }))
      if (u) lc.push(ch(u, theme.bg, { bg: theme.warn, bold: true }))
    }
  })
  leftText.content = new StyledText(lc)
}

function rightPane(innerH: number) {
  const rw = Math.max(10, renderer.width - LEFT_W - 2)
  const t = selected ? topics.get(selected) : undefined
  right.title = t ? ` ${t.name}  (${t.msgs.length}) ` : " Messages "
  const header: TextChunk[][] = []
  const summary = t && summaries.get(t.name)
  if (summary) {
    for (const l of wrap(summary, rw - 2)) header.push([ch("  " + l, theme.highlight)])
    header.push([ch("", theme.text)])
  }
  const lines: TextChunk[][] = []
  if (!t) lines.push([ch(connected ? "No messages yet." : "Waiting for the board…", theme.muted)])
  else
    for (const m of t.msgs) {
      const from = m.from ?? "unknown"
      lines.push([ch(from, senderColor(from), { bold: true }), ch("  " + stamp(m.ts), theme.muted), ch(`  #${m.seq}`, theme.muted)])
      for (const l of wrap(m.body, rw - 2)) lines.push([ch("  " + l, theme.text)])
      lines.push([ch("", theme.text)])
    }
  header.splice(Math.max(0, innerH - 1))
  const bodyH = Math.max(1, innerH - header.length)
  const maxScroll = Math.max(0, lines.length - bodyH)
  scroll = Math.min(Math.max(0, scroll), maxScroll)
  const end = lines.length - scroll
  const view = [...header, ...lines.slice(Math.max(0, end - bodyH), end)]
  const rc: TextChunk[] = []
  view.forEach((l, i) => { if (i) rc.push(NL); rc.push(...l) })
  rightText.content = new StyledText(rc)
}

function drawFooter() {
  const unreadAll = [...topics.values()].reduce((s, x) => s + x.unread, 0)
  const status = connected ? ch("● live", theme.ok, { bold: true }) : ch("○ board off, retrying", theme.error, { bold: true })
  footer.content = new StyledText([
    ch(" ", theme.muted), status,
    ch(`  ${topics.size} topics  ${total} msgs${unreadAll ? `  ${unreadAll} unread` : ""}${scroll ? `  ↑${scroll} lines up` : ""}`, theme.muted),
    ch("   ↑↓/jk topic  PgUp/PgDn scroll  g/G oldest/newest  t tasks  q quit", theme.muted),
  ])
}

function draw() {
  main.visible = mode === "board"
  tasksBox.visible = mode === "tasks"
  if (mode === "tasks") return drawTasks()
  const innerH = Math.max(1, renderer.height - 3) // main box minus border; footer takes 1
  const list = rows()
  if (!picked) {
    let best: Topic | undefined
    for (const t of topics.values()) if (!best || t.newest > best.newest) best = t
    selected = best?.name ?? null
    if (best) best.unread = 0
  }
  const si = list.findIndex(r => r.kind === "topic" && r.topic.name === selected)
  if (si < listTop) listTop = si - (si > 0 && list[si - 1].kind === "head" ? 1 : 0)
  const end = si + (list[si + 1]?.kind === "summary" ? 1 : 0) // keep the summary row under the topic in view
  if (end >= listTop + innerH) listTop = end - innerH + 1
  listTop = Math.max(0, listTop)
  leftPane(list, innerH)
  rightPane(innerH)
  drawFooter()
  renderer.requestRender()
}

// ---- tasks view ----
let mode: "board" | "tasks" = flag("--tasks") ? "tasks" : "board"
let allAgents: Agent[] = []
let queuedCount = 0
let tasksLoaded = false
let typing = false
const view: View = { expanded: new Set(), filter: "", stalledOnly: false }
let cursorKey = ""
let taskTop = 0
let taskRows: TaskRow[] = []
let taskTimer: ReturnType<typeof setInterval> | undefined

async function reloadTasks() {
  const r = buildAgents(await loadHomes(findHomes(homeArgs)), Math.floor(Date.now() / 1000), stallMin * 60)
  allAgents = r.agents; queuedCount = r.queued; tasksLoaded = true
  draw()
}

const chunks = (lines: Line[]): TextChunk[] => lines.flatMap((l, i) => [...(i ? [NL] : []), ...l.map(s => ch(s.text, s.fg, { bg: s.bg, bold: s.bold }))])

function drawTasks() {
  const innerW = Math.max(10, renderer.width - 2)
  const innerH = Math.max(1, renderer.height - 3)
  const head = tasksHeader(counts(allAgents, queuedCount), { filter: view.filter, typing, stalledOnly: view.stalledOnly, stallMin })
  const bodyH = Math.max(1, innerH - head.length)
  taskRows = flatten(allAgents, view)
  let cur = taskRows.findIndex(r => r.key === cursorKey)
  if (cur < 0) { cur = 0; cursorKey = taskRows[0]?.key ?? "" }
  if (cur < taskTop) taskTop = cur
  if (cur >= taskTop + bodyH) taskTop = cur - bodyH + 1
  taskTop = Math.max(0, Math.min(taskTop, Math.max(0, taskRows.length - bodyH)))
  const body = viewport(taskRows, taskTop, bodyH, innerW, cur)
  if (!taskRows.length) body.push([{ text: tasksLoaded ? "  no agents match" : "  loading…", fg: theme.muted }])
  tasksText.content = new StyledText(chunks([...head, ...body]))
  footer.content = new StyledText(chunks([tasksFooter(taskRows.length, cur, tasksLoaded)]))
  renderer.requestRender()
}

function setMode(m: "board" | "tasks") {
  mode = m
  clearInterval(taskTimer)
  if (m === "tasks") { reloadTasks(); taskTimer = setInterval(reloadTasks, REFRESH_TASKS_MS) }
  draw()
}

function tasksKey(k: { name: string; sequence?: string; shift?: boolean }) {
  const cur = Math.max(0, taskRows.findIndex(r => r.key === cursorKey))
  const go = (i: number) => { cursorKey = taskRows[Math.min(taskRows.length - 1, Math.max(0, i))]?.key ?? "" }
  const page = Math.max(1, renderer.height - 6)
  if (typing) {
    if (k.name === "return" || k.name === "escape") { typing = false; if (k.name === "escape") view.filter = "" }
    else if (k.name === "backspace") view.filter = view.filter.slice(0, -1)
    else if (k.sequence && k.sequence.length === 1 && k.sequence >= " ") view.filter += k.sequence
    return draw()
  }
  const row = taskRows[cur]
  switch (k.name) {
    case "q": renderer.destroy(); process.exit(0)
    case "t": return setMode("board")
    case "down": case "j": go(cur + 1); break
    case "up": case "k": go(cur - 1); break
    case "pagedown": go(cur + page); break
    case "pageup": go(cur - page); break
    case "home": go(0); break
    case "end": go(1e9); break
    case "g": go(k.shift ? 1e9 : 0); break
    case "return": case "space": case "right": case "left":
      if (row && row.kind !== "detail") {
        const sk = row.kind === "stalled" ? "stalled-all" : row.key // the stalled head toggles top-10 / all
        const open = view.expanded.has(sk)
        if (k.name === "left" ? open : k.name === "right" ? !open : true) { if (view.expanded.has(sk)) view.expanded.delete(sk); else view.expanded.add(sk) }
      }
      break
    case "e": if (k.shift) view.expanded.clear(); else for (const a of allAgents) { view.expanded.add(`m:${a.mate}`); view.expanded.add(`r:${a.mate}/${a.repo}`) }; break
    case "/": typing = true; break
    case "s": view.stalledOnly = !view.stalledOnly; break
    case "escape": view.filter = ""; view.stalledOnly = false; break
    case "r": reloadTasks(); break
    default: return
  }
  draw()
}

function move(d: number) {
  const ts = rows().filter((r): r is Extract<Row, { kind: "topic" }> => r.kind === "topic")
  const i = ts.findIndex(r => r.topic.name === selected)
  const n = ts[Math.min(ts.length - 1, Math.max(0, i + d))]
  if (!n) return
  picked = true
  selected = n.topic.name
  n.topic.unread = 0
  scroll = 0
  draw()
}

renderer.on("resize", draw)
renderer.keyInput.on("keypress", (k: { name: string; sequence?: string; shift?: boolean }) => {
  if (mode === "tasks") return tasksKey(k)
  if (k.name === "t") return setMode("tasks")
  const page = Math.max(1, renderer.height - 5)
  switch (k.name) {
    case "q": renderer.destroy(); process.exit(0)
    case "down": case "j": return move(1)
    case "up": case "k": return move(-1)
    case "pageup": scroll += page; break
    case "pagedown": scroll -= page; break
    case "g": if (k.shift) scroll = 0; else scroll = 1e9; break
    case "home": scroll = 1e9; break
    case "end": scroll = 0; break
    default: return
  }
  draw()
})

if (mode === "tasks") setMode("tasks")
draw()
follow()
followSummaries()
