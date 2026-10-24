#!/usr/bin/env bun
// Read-only viewer for the crewboard message board. Only runs `crewboard sub`; never publishes.
import { BoxRenderable, TextRenderable, StyledText, RGBA, createCliRenderer, type TextChunk } from "@opentui/core"
import { theme } from "../tui-theme/theme.ts"

type Msg = { seq: number; ts: string; topic: string; from: string | null; body: string }
type Topic = { name: string; msgs: Msg[]; unread: number; newest: number }
type Row = { kind: "head"; group: string; unread: number } | { kind: "topic"; topic: Topic }

const TZ = "America/Los_Angeles"
const LEFT_W = 38
const MAX_BODY_LINES = 40
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
    for (const t of ts) out.push({ kind: "topic", topic: t })
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
root.add(main); root.add(footer); renderer.root.add(root)

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
  const lines: TextChunk[][] = []
  if (!t) lines.push([ch(connected ? "No messages yet." : "Waiting for the board…", theme.muted)])
  else
    for (const m of t.msgs) {
      const from = m.from ?? "unknown"
      lines.push([ch(from, senderColor(from), { bold: true }), ch("  " + stamp(m.ts), theme.muted), ch(`  #${m.seq}`, theme.muted)])
      for (const l of wrap(m.body, rw - 2)) lines.push([ch("  " + l, theme.text)])
      lines.push([ch("", theme.text)])
    }
  const maxScroll = Math.max(0, lines.length - innerH)
  scroll = Math.min(Math.max(0, scroll), maxScroll)
  const end = lines.length - scroll
  const view = lines.slice(Math.max(0, end - innerH), end)
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
    ch("   ↑↓/jk topic  PgUp/PgDn scroll  g/G oldest/newest  q quit", theme.muted),
  ])
}

function draw() {
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
  if (si >= listTop + innerH) listTop = si - innerH + 1
  listTop = Math.max(0, listTop)
  leftPane(list, innerH)
  rightPane(innerH)
  drawFooter()
  renderer.requestRender()
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
renderer.keyInput.on("keypress", (k: { name: string; shift?: boolean }) => {
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

draw()
follow()
