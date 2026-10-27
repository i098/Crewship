#!/usr/bin/env bun
// Every lavish board on this host (read-only): lavish-axi's state.json sessions, with the worker that owns each board.
// A board is GONE when its worker is torn down: a durable lavish-keep copy is in use, the board file is deleted,
// or no live task meta owns its worktree or firstmate data dir. Open boards of gone workers sort first.
// `--once` prints plain text and exits; `--all` (key `a`) adds ended boards; `--anonymize` replaces names (for screenshots).
// Never writes state.json.
import { closeSync, existsSync, openSync, readdirSync, readFileSync, readSync } from "node:fs"
import { basename } from "node:path"
import { theme } from "../tui-theme/theme.ts"

const HOME = process.env.HOME ?? ""
const STATE = `${process.env.LAVISH_AXI_STATE_DIR || `${HOME}/.lavish-axi`}/state.json`
const KEEP = process.env.LAVISH_KEEP_DIR || `${HOME}/.local/share/lavish-keep`
const REFRESH_MS = 10_000
const MAXW = 220
const ANON = process.argv.includes("--anonymize")

// ---- homes and task metas -------------------------------------------------
// LAVISH_TUI_HOMES (":"-separated firstmate home roots) overrides discovery.
function homeRoots(): string[] {
  if (process.env.LAVISH_TUI_HOMES !== undefined) return process.env.LAVISH_TUI_HOMES.split(":").filter(Boolean)
  const roots = [`${HOME}/Dev/firstmate`]
  const base = `${HOME}/.treehouse`
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    if (!d.startsWith("firstmate-")) continue
    for (const n of readdirSync(`${base}/${d}`)) roots.push(`${base}/${d}/${n}/firstmate`)
  }
  return roots
}

const HOME_RE = /firstmate-([^/_]+)[/_](\d+)[/_]firstmate/
const homeLabel = (root: string) => root.match(HOME_RE)?.slice(1, 3).join("/") ?? "main"

type Live = { worktrees: Map<string, string>; tasks: Set<string> } // worktree -> task; "<home root>\n<task>"

function liveTasks(): Live {
  const live: Live = { worktrees: new Map(), tasks: new Set() }
  for (const root of homeRoots()) {
    const dir = `${root}/state`
    if (!existsSync(dir)) continue
    for (const f of readdirSync(dir)) {
      if (!f.endsWith(".meta")) continue
      const task = f.slice(0, -5)
      live.tasks.add(`${root}\n${task}`)
      const wt = readFileSync(`${dir}/${f}`, "utf8").match(/^worktree=(.+)$/m)?.[1]
      if (wt) live.worktrees.set(wt.replace(/\/$/, ""), task)
    }
  }
  return live
}

// ---- data ----------------------------------------------------------------
export type Board = {
  key: string; title: string; status: string; updated: number; owner: string
  gone: "" | "kept" | "deleted" | "torn down"; url: string; link: string
}

type Session = { key: string; file?: string; url?: string; status?: string; updated_at?: string }

// Owner task of a board path, and whether that owner still runs.
export function ownerOf(path: string, live: Live): { owner: string; alive: boolean } {
  const data = path.match(/^(.*\/firstmate)\/data\/([^/]+)\//)
  if (data) return { owner: data[2], alive: live.tasks.has(`${data[1]}\n${data[2]}`) }
  for (const [wt, task] of live.worktrees) if (path.startsWith(wt + "/")) return { owner: task, alive: true }
  const home = path.match(/^(.*\/firstmate)\//)
  if (home) return { owner: homeLabel(home[1]), alive: true }
  // A treehouse slot <pool>/<n>/<repo> with no meta naming it: its task was torn down (the slot may be reused).
  const slot = path.match(/\/\.treehouse\/([^/]+?)(?:-[0-9a-f]{6})?\/(\d+)\/[^/]+\//)
  if (slot) return { owner: `${slot[1]}/${slot[2]}`, alive: false }
  return { owner: "-", alive: true }
}

function titleOf(file: string): string {
  // Boards run to megabytes; the title sits in the head, so read only the first 16 KB.
  const head = Buffer.alloc(16384)
  try {
    const fd = openSync(file, "r")
    const n = readSync(fd, head, 0, head.length, 0)
    closeSync(fd)
    const t = head.toString("utf8", 0, n).match(/<title[^>]*>([^<]*)<\/title>/i)?.[1].trim()
    if (t) return t.replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'")
  } catch {}
  return basename(file).replace(/\.html?$/, "")
}

const RANK = (b: Board) => (b.status === "ended" ? 2 : 0) + (b.gone ? 0 : 1)

export function load(now = Date.now() / 1000): Board[] {
  if (!existsSync(STATE)) return [] // lavish-axi has not run yet
  const sessions: Record<string, Session> = JSON.parse(readFileSync(STATE, "utf8")).sessions ?? {}
  const live = liveTasks()
  return Object.values(sessions).filter(s => s && s.file).map((s): Board => {
    const file = s.file!
    const kept = file.startsWith(KEEP + "/")
    let origin = file
    if (kept) try { origin = JSON.parse(readFileSync(`${KEEP}/${s.key}/keep.json`, "utf8")).source } catch {}
    const { owner, alive } = ownerOf(origin, live)
    const updated = Date.parse(s.updated_at ?? "") / 1000
    return {
      key: s.key, title: titleOf(file), status: s.status ?? "open", updated: Number.isNaN(updated) ? now : updated, owner,
      gone: kept ? "kept" : !existsSync(file) ? "deleted" : alive ? "" : "torn down",
      url: s.url ?? "", link: s.url ?? "",
    }
  }).sort((a, b) => RANK(a) - RANK(b) || b.updated - a.updated)
}

// `lavish-public link <key>` signs a public link; about 0.1s each, so run in parallel and cache per key.
const links = new Map<string, string>()
export async function resolveLinks(boards: Board[]): Promise<void> {
  const cmd = Bun.which("lavish-public")
  if (!cmd) return
  const todo = boards.filter(b => !links.has(b.key) && /^[0-9a-f]{16}$/.test(b.key))
  for (const b of todo) links.set(b.key, b.url) // a refresh during this run must not spawn the same keys again
  for (let i = 0; i < todo.length; i += 16) {
    await Promise.all(todo.slice(i, i + 16).map(async b => {
      const p = Bun.spawn([cmd, "link", b.key], { stdout: "pipe", stderr: "ignore" })
      const out = (await new Response(p.stdout).text()).trim()
      links.set(b.key, (await p.exited) === 0 && out ? out : b.url)
    }))
  }
}
const withLinks = (boards: Board[]) => boards.map(b => ({ ...b, link: links.get(b.key) ?? b.url }))

export const visible = (boards: Board[], all: boolean) => (all ? boards : boards.filter(b => b.status !== "ended"))

// Stable placeholders per distinct value, in first-seen order.
export function anonymize(boards: Board[]): Board[] {
  const seen: Record<string, Map<string, string>> = {}
  const alias = (kind: string, v: string, make: (n: number) => string) => {
    const m = (seen[kind] ??= new Map())
    return m.get(v) ?? m.set(v, make(m.size + 1)).get(v)!
  }
  return boards.map(b => {
    const key = alias("key", b.key, n => n.toString(16).padStart(16, "0"))
    return {
      ...b, key, title: alias("title", b.title, n => `Board ${n}`),
      owner: b.owner === "-" ? b.owner : alias("owner", b.owner, n => `task-${n}`),
      url: `https://boards.example/session/${key}`, link: `https://boards.example/session/${key}`,
    }
  })
}

// ---- rendering -----------------------------------------------------------
type Seg = [text: string, color: string, bold?: boolean, background?: string]
type Line = Seg[]

const fit = (t: string, w: number) => (t.length > w ? t.slice(0, Math.max(0, w - 1)) + "…" : t.padEnd(w))
export function fmtAge(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  if (s < 86400) return `${Math.floor(s / 3600)}h`
  return `${Math.floor(s / 86400)}d`
}

export function tableLines(boards: Board[], inner: number, now = Date.now() / 1000): Line[] {
  const sw = 8, gw = 14, ow = 22, kw = 16, uw = 7
  const rest = Math.max(30, inner - (sw + gw + ow + kw + uw + 6 * 2))
  const tw = Math.min(40, Math.floor(rest * 0.4)), lw = rest - tw
  const w = [sw, gw, ow, kw, uw, tw, lw]
  const row = (c: string[], color: (i: number) => string, bold = false): Line =>
    c.map((t, i): Seg => [fit(t, w[i]) + (i < c.length - 1 ? "  " : ""), color(i), bold])
  const lines = [row(["STATUS", "WORKER", "OWNER", "KEY", "UPDATED", "TITLE", "LINK"], () => theme.muted, true)]
  for (const b of boards) {
    const open = b.status !== "ended"
    lines.push(row([b.status, b.gone ? `GONE ${b.gone}` : "live", b.owner, b.key, fmtAge(now - b.updated), b.title, b.link], i =>
      i === 0 ? (open ? theme.ok : theme.muted) : i === 1 ? (b.gone ? (open ? theme.error : theme.warn) : theme.muted) : i === 6 ? theme.accent : theme.text))
  }
  if (!boards.length) lines.push([["No lavish boards in this view.", theme.muted]])
  return lines
}

const counts = (boards: Board[]) => {
  const open = boards.filter(b => b.status !== "ended")
  return { open: open.length, gone: open.filter(b => b.gone).length, ended: boards.length - open.length }
}
const scope = (all: boolean) => (all ? "all boards" : "open boards")

export function once(boards: Board[], all: boolean, width = MAXW): string {
  const c = counts(boards)
  const head = `LAVISH BOARDS  ${scope(all)} · ${c.open} open · ${c.gone} open with worker gone · ${c.ended} ended`
  return [head, ...tableLines(visible(boards, all), width - 4).map(l => l.map(s => s[0]).join("").trimEnd())].join("\n") + "\n"
}

// ---- live view -----------------------------------------------------------
async function live(startAll: boolean) {
  // Dynamic: --once must run on a host where `bun install` has not been run.
  const { BoxRenderable, StyledText, TextRenderable, bg, bold, createCliRenderer, fg } = await import("@opentui/core")
  const chunk = ([t, color, b, back]: Seg) => {
    let c = fg(color)(t)
    if (back) c = bg(back)(c)
    return b ? bold(c) : c
  }
  const renderer = await createCliRenderer({ exitOnCtrlC: true })
  const column = new BoxRenderable(renderer, { flexDirection: "column", width: "100%" })
  const header = new TextRenderable(renderer, { content: "", flexShrink: 0 })
  const box = new BoxRenderable(renderer, {
    border: true, borderStyle: "rounded", borderColor: theme.border, titleColor: theme.text,
    title: " Lavish boards · open boards of gone workers first ", titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexShrink: 0,
  })
  const body = new TextRenderable(renderer, { content: "" })
  box.add(body)
  column.add(header)
  column.add(box)
  renderer.root.add(column)

  let boards: Board[] = []
  let error = ""
  let top = 0
  let all = startAll
  const styled = (lines: Line[]) => new StyledText(lines.flatMap((l, i) => [...(i ? [chunk(["\n", theme.text])] : []), ...l.map(chunk)]))

  function draw() {
    const W = Math.min(MAXW, renderer.width)
    column.width = W
    const shown = visible(boards, all)
    const c = counts(boards)
    const page = Math.max(1, renderer.height - 6)
    top = Math.max(0, Math.min(top, shown.length - page))
    header.content = styled([
      [[" LAVISH BOARDS ", theme.bg, true, theme.accent], ["  ", theme.text], [`${c.open} open`, theme.ok], [` · ${c.gone} open with worker gone`, theme.error], [` · ${c.ended} ended`, theme.muted]],
      [[`${scope(all)} · every ${REFRESH_MS / 1000}s · `, theme.muted], ["a", theme.text, true], [" all/open  ", theme.muted], ["↑↓", theme.text, true], [" scroll  ", theme.muted], ["q", theme.text, true], [" quit  ", theme.muted], ["r", theme.text, true], [" refresh", theme.muted], ...(error ? [["  " + error, theme.error] as Seg] : [])],
    ])
    body.content = styled(tableLines(shown.slice(top, top + page), W - 4))
    renderer.requestRender()
  }

  function refresh() {
    try {
      const raw = load()
      boards = ANON ? anonymize(raw) : withLinks(raw)
      error = ""
      if (!ANON) resolveLinks(raw).then(() => { boards = withLinks(raw); draw() })
    } catch (e) {
      error = `Cannot read ${STATE}: ${(e as Error).message}`
    }
    draw()
  }

  refresh()
  const t = setInterval(refresh, REFRESH_MS)
  renderer.on("resize", draw)
  renderer.keyInput.on("keypress", (k: { name: string }) => {
    if (k.name === "q") {
      clearInterval(t)
      renderer.destroy()
      process.exit(0)
    }
    if (k.name === "r") refresh()
    if (k.name === "a") { all = !all; top = 0; draw() }
    if (k.name === "down" || k.name === "j") { top++; draw() }
    if (k.name === "up" || k.name === "k") { top--; draw() }
  })
}

if (import.meta.main) {
  const all = process.argv.includes("--all")
  if (process.argv.includes("--once")) {
    try {
      const raw = load()
      if (!ANON) await resolveLinks(visible(raw, all))
      process.stdout.write(once(ANON ? anonymize(raw) : withLinks(raw), all))
    } catch (e) {
      console.error(`Cannot read ${STATE}: ${(e as Error).message}`)
      process.exit(1)
    }
  } else {
    await live(all)
  }
}
