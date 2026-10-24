#!/usr/bin/env bun
// Token usage TUI over omp's stats store (read-only). Periods use America/Los_Angeles calendar boundaries.
import { BoxRenderable, StyledText, TextRenderable, bg, bold, createCliRenderer, fg, type TextChunk } from "@opentui/core"
import { Database } from "bun:sqlite"
import { theme } from "../tui-theme/theme.ts"
import { BAR_W, QUOTA_MIN_MS, buildRows, cells, loadQuota, quotaText, type QuotaInput, type QuotaRow } from "./quota.ts"

const TZ = "America/Los_Angeles"
const DB_PATH = `${process.env.HOME}/.omp/stats.db`
const REFRESH_MS = 10_000
const SYNC_MS = 120_000

const fmtParts = new Intl.DateTimeFormat("en-US", {
  timeZone: TZ, hourCycle: "h23", year: "numeric", month: "numeric", day: "numeric",
  hour: "numeric", minute: "numeric", second: "numeric", weekday: "short",
})

function laParts(ms: number) {
  const p = Object.fromEntries(fmtParts.formatToParts(ms).map(x => [x.type, x.value]))
  return { y: +p.year, m: +p.month, d: +p.day, wd: p.weekday, h: +p.hour, mi: +p.minute, s: +p.second }
}

// Epoch ms of 00:00 LA time on the given calendar date (day may overflow/underflow).
function laMidnight(y: number, m: number, d: number): number {
  const guess = Date.UTC(y, m - 1, d)
  for (const off of [8, 7]) {
    const t = guess + off * 3_600_000
    const p = laParts(t)
    if (p.h === 0 && p.mi === 0 && p.d === new Date(guess).getUTCDate()) return t
  }
  throw new Error("midnight not found")
}

function periodStarts(now: number) {
  const p = laParts(now)
  const dow = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(p.wd)
  return [
    { name: "All time", start: 0 },
    { name: "This year", start: laMidnight(p.y, 1, 1) },
    { name: "This month", start: laMidnight(p.y, p.m, 1) },
    { name: "This week", start: laMidnight(p.y, p.m, p.d - dow) },
    { name: "Today", start: laMidnight(p.y, p.m, p.d) },
  ]
}

const n = (v: number) => Math.round(v).toLocaleString("en-US")
function compact(v: number) {
  for (const [div, s] of [[1e12, "T"], [1e9, "B"], [1e6, "M"], [1e3, "K"]] as const) if (v >= div) return `${(v / div).toFixed(2)}${s}`
  return String(Math.round(v))
}
const usd = (v: number) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const usdShort = (v: number) => "$" + (v >= 1000 ? compact(v) : v.toFixed(v >= 10 ? 0 : 2))

// ---- styled-text helpers -------------------------------------------------
type Line = TextChunk[]
type Style = { bg?: string; b?: boolean }
function s(text: string, color: string = theme.text, o: Style = {}): TextChunk {
  let c = fg(color)(text)
  if (o.bg) c = bg(o.bg)(c)
  return o.b ? bold(c) : c
}
const rep = (ch: string, k: number) => ch.repeat(Math.max(0, k))
const center = (t: string, w: number) => {
  t = t.slice(0, w)
  const l = Math.floor((w - t.length) / 2)
  return rep(" ", l) + t + rep(" ", w - t.length - l)
}
function styled(lines: Line[]): StyledText {
  const out: TextChunk[] = []
  lines.forEach((l, i) => {
    if (i) out.push(s("\n"))
    out.push(...l)
  })
  return new StyledText(out)
}

// ---- data ----------------------------------------------------------------
type Row = { t: number; model: string; i: number; o: number; cr: number; cw: number; r: number; c: number }
type Sum = { i: number; o: number; cr: number; cw: number; r: number; c: number }
const zero = (): Sum => ({ i: 0, o: 0, cr: 0, cw: 0, r: 0, c: 0 })
const add = (a: Sum, r: Row) => {
  a.i += r.i; a.o += r.o; a.cr += r.cr; a.cw += r.cw; a.r += r.r; a.c += r.c
}
const sumFrom = (rows: Row[], from: number, to = Infinity) => {
  const a = zero()
  for (const r of rows) if (r.t >= from && r.t < to) add(a, r)
  return a
}

type Data = { now: number; rows: Row[]; periods: { name: string; start: number }[] }

// One scan of messages, grouped by UTC hour and model. LA offsets are whole hours, so every
// LA day/hour boundary falls on a bucket edge and all views derive from these rows.
function load(): Data {
  const db = new Database(DB_PATH, { readonly: true })
  try {
    const now = Date.now()
    const rows = (
      db
        .query(
          "select timestamp/3600000*3600000 t, model, sum(input_tokens) i, sum(output_tokens) o, sum(cache_read_tokens) cr, sum(cache_write_tokens) cw, count(*) r, sum(cost_total) c from messages group by 1, model",
        )
        .all() as Row[]
    )
    return { now, rows, periods: periodStarts(now) }
  } finally {
    db.close()
  }
}

// ---- panels --------------------------------------------------------------
const legend = (): Line => [s("■ ", theme.input), s("input   "), s("■ ", theme.output), s("output   "), s("■ ", theme.cache), s("cache", theme.muted)]

function tablePanel(d: Data, w: number): Line[] {
  const wide = w >= 115
  const f = wide ? n : compact
  const cols = wide ? [15, 15, 18, 15, 18, 10, 13] : [9, 9, 10, 10, 10, 9, 11]
  const head = ["Input", "Output", "Cache read", "Cache write", "Total", "Requests", "Cost USD"]
  const color = [theme.input, theme.output, theme.cache, theme.cache, theme.text, theme.muted, theme.highlight]
  const lines: Line[] = [[s("Period".padEnd(11), theme.muted, { b: true }), ...head.map((h, k) => s(h.padStart(cols[k]), color[k], { b: true }))]]
  lines.push([s(rep("─", 11 + cols.reduce((a, b) => a + b, 0)), theme.border)])
  d.periods.forEach((p, idx) => {
    const x = sumFrom(d.rows, p.start)
    const today = idx === d.periods.length - 1
    const vals = [f(x.i), f(x.o), f(x.cr), f(x.cw), f(x.i + x.o + x.cr + x.cw), f(x.r), wide ? usd(x.c) : usdShort(x.c)]
    lines.push([
      s(p.name.padEnd(11), today ? theme.accent : theme.text, { b: true }),
      ...vals.map((v, k) => s(v.padStart(cols[k]), color[k], { b: k === 4 || k === 6 || today })),
    ])
  })
  return lines
}

function dayPanel(d: Data, w: number, H: number): Line[] {
  const DAYS = 14
  const p = laParts(d.now)
  const starts = Array.from({ length: DAYS + 1 }, (_, k) => laMidnight(p.y, p.m, p.d - (DAYS - 1) + k))
  const days = starts.slice(0, DAYS).map((st, k) => ({ st, ...sumFrom(d.rows, st, starts[k + 1]) }))
  const gut = 9
  const slot = Math.max(5, Math.min(10, Math.floor((w - gut) / DAYS)))
  const bw = slot - 2
  const max = Math.max(1, ...days.map(x => x.i + x.o))
  const units = H * 8
  const T = days.map(x => Math.round(((x.i + x.o) / max) * units))
  const I = days.map((x, k) => Math.min(T[k], Math.round((x.i / max) * units)))
  const BLK = " ▁▂▃▄▅▆▇█"
  const axis = (r: number) => (r === H - 1 ? compact(max) : r === Math.floor((H - 1) / 2) ? compact(max / 2) : r === 0 ? "0" : "")
  const lines: Line[] = []
  for (let r = H - 1; r >= 0; r--) {
    const line: Line = [s(axis(r).padStart(gut - 2) + " │", theme.muted)]
    days.forEach((_, k) => {
      const f = Math.max(0, Math.min(8, T[k] - 8 * r))
      const b = Math.max(0, Math.min(8, I[k] - 8 * r))
      let cell: TextChunk
      if (f === 0) cell = s(rep(" ", bw))
      else if (f < 8) cell = s(rep(BLK[f], bw), T[k] > I[k] && b < f ? theme.output : theme.input)
      else if (b >= 8) cell = s(rep("█", bw), theme.input)
      else if (b <= 0) cell = s(rep("█", bw), theme.output)
      else cell = s(rep(BLK[b], bw), theme.input, { bg: theme.output })
      line.push(cell, s("  "))
    })
    lines.push(line)
  }
  const row = (label: string, cell: (x: (typeof days)[number], k: number) => TextChunk): Line => [
    s(label.padStart(gut - 2) + "  ", theme.muted),
    ...days.map((x, k) => cell(x, k)),
  ]
  const last = DAYS - 1
  lines.push([s(rep(" ", gut - 1) + "└" + rep("─", slot * DAYS - 1), theme.border)])
  lines.push(row("", (x, k) => s(center(String(laParts(x.st + 12 * 3.6e6).d), slot), k === last ? theme.accent : theme.text, { b: k === last })))
  lines.push(row("", (x, k) => s(center(laParts(x.st + 12 * 3.6e6).wd.slice(0, 3), slot), k === last ? theme.accent : theme.muted)))
  lines.push(row("cache", x => s(center(compact(x.cr + x.cw), slot - 1) + " ", theme.cache)))
  lines.push(row("cost", x => s(center(usdShort(x.c), slot - 1) + " ", theme.highlight)))
  return lines
}

function hourPanel(d: Data, w: number): Line[] {
  const start = d.periods[4].start
  const hours = Array.from({ length: 24 }, (_, h) => sumFrom(d.rows, start + h * 3.6e6, start + (h + 1) * 3.6e6))
  const nowH = Math.min(23, Math.floor((d.now - start) / 3.6e6))
  const gut = 9
  const tail = 26
  const cell = Math.max(2, Math.min(5, Math.floor((w - gut - tail) / 24)))
  const BLK = "▁▂▃▄▅▆▇█"
  const series: [string, string, (x: Sum) => number][] = [
    ["input", theme.input, x => x.i],
    ["output", theme.output, x => x.o],
    ["cache", theme.cache, x => x.cr + x.cw],
  ]
  const lines: Line[] = series.map(([label, color, pick]) => {
    const vals = hours.map(pick)
    const max = Math.max(1, ...vals)
    const line: Line = [s(label.padStart(gut - 2) + "  ", color)]
    vals.forEach((v, h) => {
      if (h > nowH) line.push(s(rep("·", cell - 1) + " ", theme.border))
      else line.push(s(rep(v === 0 ? "▁" : BLK[Math.min(7, Math.ceil((v / max) * 8) - 1)], cell - 1) + " ", v === 0 ? theme.border : color, { b: h === nowH }))
    })
    line.push(s(`  ${compact(vals.reduce((a, b) => a + b, 0)).padStart(7)} peak ${compact(max)}`, theme.muted))
    return line
  })
  const step = cell >= 3 ? 1 : 2
  const ticks: Line = [s(rep(" ", gut), theme.muted)]
  for (let h = 0; h < 24; h += step) ticks.push(s(String(h).padStart(2, "0").padEnd(step * cell), h === nowH || (step === 2 && h + 1 === nowH) ? theme.accent : theme.muted, { b: h === nowH }))
  lines.push(ticks)
  return lines
}

function modelPanel(d: Data, w: number): Line[] {
  const month = d.periods[2].start
  const by = new Map<string, Sum>()
  for (const r of d.rows) {
    if (r.t < month) continue
    const a = by.get(r.model) ?? zero()
    add(a, r)
    by.set(r.model, a)
  }
  const list = [...by.entries()].sort((a, b) => b[1].i + b[1].o - (a[1].i + a[1].o))
  const shown = list.slice(0, 6)
  const other = zero()
  for (const [, v] of list.slice(6)) for (const k of Object.keys(other) as (keyof Sum)[]) other[k] += v[k]
  if (list.length > 6) shown.push([`other (${list.length - 6})`, other])
  const palette = [theme.highlight, theme.ok, theme.error, theme.text, theme.muted, theme.border, theme.border]
  const tot = shown.reduce((a, [, v]) => a + v.i + v.o, 0) || 1
  const width = w
  const bar: Line = []
  let cum = 0
  let drawn = 0
  shown.forEach(([, v], k) => {
    cum += v.i + v.o
    const end = Math.round((cum / tot) * width)
    bar.push(s(rep("█", end - drawn), palette[k]))
    drawn = end
  })
  const nameW = Math.min(28, Math.max(...shown.map(([m]) => m.length), 5))
  const lines: Line[] = [bar, [s("")]]
  shown.forEach(([m, v], k) => {
    lines.push([
      s("■ ", palette[k]),
      s(m.slice(0, nameW).padEnd(nameW + 2)),
      s(((100 * (v.i + v.o)) / tot).toFixed(1).padStart(5) + "%  ", theme.muted),
      s(compact(v.i).padStart(9), theme.input),
      s(" in   ", theme.muted),
      s(compact(v.o).padStart(9), theme.output),
      s(" out   ", theme.muted),
      s(usd(v.c).padStart(14), theme.highlight),
    ])
  })
  if (!shown.length) lines.push([s("no messages this month", theme.muted)])
  return lines
}

function quotaPanel(rows: QuotaRow[], now: number, w: number): Line[] {
  const lines: Line[] = [[s("Account".padEnd(15) + "Window".padEnd(10) + "Used".padEnd(BAR_W + 2) + "Left".padEnd(10) + "Resets in".padEnd(10) + "At (LA)", theme.muted, { b: true })]]
  lines.push([s(rep("─", Math.min(w, 15 + 10 + BAR_W + 2 + 10 + 10 + 11)), theme.border)])
  let last = ""
  for (const r of rows) {
    const c = cells(r, now, TZ)
    const acct = r.account === last ? "" : r.account
    last = r.account
    const head = [s(acct.padEnd(15), theme.accent, { b: true }), s(r.window.padEnd(10))]
    if (r.leftPct === null) lines.push([...head, s(c.note, theme.muted)])
    else lines.push([...head, s(c.bar.padEnd(BAR_W + 2), c.color), s(c.left.padEnd(10), c.color, { b: true }), s(c.reset.padEnd(10)), s(c.clock.padEnd(11), theme.muted), ...(c.note ? [s(c.note, theme.muted)] : [])])
  }
  return lines
}

// ---- layout --------------------------------------------------------------
// --once prints the quota rows as text and exits; --fixture <file> reads the inputs from a recorded JSON instead of the live sources.
if (process.argv.includes("--once")) {
  const fx = process.argv.indexOf("--fixture")
  const input: QuotaInput = fx > 0 ? JSON.parse(await Bun.file(process.argv[fx + 1]).text()) : await loadQuota()
  console.log(quotaText(buildRows(input), input.now ?? Date.now(), TZ))
  process.exit(0)
}

const renderer = await createCliRenderer({ exitOnCtrlC: true })
const MAXW = 150
const column = new BoxRenderable(renderer, { flexDirection: "column", width: "100%" })
const mkPanel = (title: string) => {
  const box = new BoxRenderable(renderer, {
    border: true, borderStyle: "rounded", borderColor: theme.border, titleColor: theme.text,
    title, titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexShrink: 0,
  })
  const text = new TextRenderable(renderer, { content: "" })
  box.add(text)
  column.add(box)
  return { box, text }
}
const header = new TextRenderable(renderer, { content: "", flexShrink: 0 })
column.add(header)
const pTable = mkPanel(" Usage by period ")
const pDays = mkPanel(" Last 14 days · input + output tokens per day ")
const pHours = mkPanel(" Today by hour ")
const pQuota = mkPanel(" Quota left · reset times in LA · refreshed every 60s ")
const pModels = mkPanel(" This month by model · input + output tokens ")

renderer.root.add(column)

let data: Data | null = null
let error = ""

function draw() {
  const W = Math.min(MAXW, renderer.width)
  const inner = W - 4
  column.width = W
  const quotaHeight = 4 + (quota ? buildRows(quota).length : 0)
  const H = Math.max(3, Math.min(10, renderer.height - 44 - quotaHeight))
  if (data) {
    const p = laParts(data.now)
    const stamp = `${p.y}-${String(p.m).padStart(2, "0")}-${String(p.d).padStart(2, "0")} ${String(p.h).padStart(2, "0")}:${String(p.mi).padStart(2, "0")} LA`
    const today = sumFrom(data.rows, data.periods[4].start)
    const month = sumFrom(data.rows, data.periods[2].start)
    header.content = styled([
      [s(" TOKEN USAGE ", theme.bg, { bg: theme.accent, b: true }), s("  "), ...legend(), s("   today ", theme.muted), s(usd(today.c), theme.highlight, { b: true }), s("   month ", theme.muted), s(usd(month.c), theme.highlight, { b: true })],
      [s(`updated ${stamp} · every ${REFRESH_MS / 1000}s · week starts Monday · `, theme.muted), s("q", theme.text, { b: true }), s(" quit  ", theme.muted), s("r", theme.text, { b: true }), s(" refresh", theme.muted), ...(error ? [s("  " + error, theme.error)] : [])],
    ])
    pTable.text.content = styled(tablePanel(data, inner))
    pDays.text.content = styled(dayPanel(data, inner, H))
    pHours.text.content = styled(hourPanel(data, inner))
    pModels.text.content = styled(modelPanel(data, inner))
  } else {
    header.content = styled([[s(error || "Loading…", error ? theme.error : theme.muted)]])
  }
  if (quota) pQuota.text.content = styled(quotaPanel(buildRows(quota), Date.now(), inner))
  renderer.requestRender()
}

function refresh() {
  try {
    data = load()
    error = ""
  } catch (e) {
    error = `Cannot read ${DB_PATH}: ${(e as Error).message}`
  }
  draw()
}

// Quota comes from omp usage and a few HTTP/file reads; never fetched more often than QUOTA_MIN_MS.
let quota: QuotaInput | null = null
let quotaAt = 0
let quotaBusy = false
function refreshQuota() {
  if (quotaBusy || Date.now() - quotaAt < QUOTA_MIN_MS) return
  quotaBusy = true
  quotaAt = Date.now()
  loadQuota()
    .then(q => { quota = q })
    .catch(e => { error = `Quota: ${(e as Error).message}` })
    .finally(() => { quotaBusy = false; draw() })
}

function syncStore() {
  // omp owns the store; its own command ingests new session files.
  Bun.spawn(["omp", "stats", "--summary"], { stdout: "ignore", stderr: "ignore" })
}

draw()
setTimeout(refresh, 0)
syncStore()
refreshQuota()
const t1 = setInterval(refresh, REFRESH_MS)
const t2 = setInterval(syncStore, SYNC_MS)
const t3 = setInterval(refreshQuota, QUOTA_MIN_MS + 1000)
renderer.on("resize", draw)
renderer.keyInput.on("keypress", (k: { name: string }) => {
  if (k.name === "q") {
    clearInterval(t1)
    clearInterval(t2)
    clearInterval(t3)
    renderer.destroy()
    process.exit(0)
  }
  if (k.name === "r") {
    refresh()
    refreshQuota()
  }
})
