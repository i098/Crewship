#!/usr/bin/env bun
// Every running browser on the host (headed and headless) with its CDP pages; close a page or stop a browser after a y/n prompt.
import { BoxRenderable, StyledText, TextRenderable, bg, bold, createCliRenderer, fg, type CliRenderer, type TextChunk } from "@opentui/core"
import { theme } from "../tui-theme/theme.ts"

export type Page = { id: string; title: string; url: string }
export type Browser = { pid: number | null; name: string; kind: "headed" | "headless"; port: number | null; ageSec: number | null; rssKb: number; pages: Page[]; viewer?: string }
type Proc = { pid: number; ppid: number; age: number; rss: number; args: string }
type Probe = { ua: string; pages: Page[] }

const REFRESH_MS = 3_000
// Process names of browser engines. Playwright and puppeteer ship their Chromium as `chrome` or `headless_shell`.
const BROWSER_EXES = new Set(["chrome", "chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome-headless-shell", "headless_shell", "obscura", "obscura-worker"])
// The fleet-browser ladder (fleet/browsers/fleet-browser): its tier names, and its noVNC port for the headed tier.
const FLEET: Record<number, string> = { 9222: "fleet obscura", 9522: "fleet chrome", 9523: "fleet vnc (noVNC)" }
const VNC_CDP_PORT = 9523
// CDP ports probed even when the socket owner is not visible (another user's or a system service's browser).
const KNOWN_PORTS = [9222, 9223, 9224, 9225, 9226, 9227, 9228, 9229, 9522, 9523]

// ---- discovery -------------------------------------------------------------
// shortcut: argv is split on spaces, so a browser binary under a path with spaces is missed; read /proc/<pid>/cmdline if that appears.
const exe = (p: Proc) => p.args.split(" ")[0].split("/").pop() ?? ""
const isBrowser = (p: Proc | undefined) => !!p && BROWSER_EXES.has(exe(p)) && !p.args.includes(" --type=")

export function parsePs(out: string): Proc[] {
  return out.split("\n").flatMap(l => {
    // Four numeric columns, then args verbatim. Linear scan: no backtracking regex on process-supplied text.
    let rest = l.trimStart()
    const n: number[] = []
    for (let i = 0; i < 4; i++) {
      const end = rest.search(/\s/)
      if (end < 1 || !/^\d+$/.test(rest.slice(0, end))) return []
      n.push(+rest.slice(0, end))
      rest = rest.slice(end).trimStart()
    }
    return rest ? [{ pid: n[0], ppid: n[1], age: n[2], rss: n[3], args: rest }] : []
  })
}

// `ss -ltnpH` lines: listening TCP sockets on loopback or any address, with owner pids when visible.
export function parseListens(out: string): { port: number; pids: number[] }[] {
  return out.split("\n").flatMap(l => {
    const m = l.match(/^\S+\s+\d+\s+\d+\s+(\S+):(\d+)\s/)
    if (!m || !/^(127\.0\.0\.1|\[::1\]|\*|0\.0\.0\.0|\[::\])$/.test(m[1])) return []
    return [{ port: +m[2], pids: [...l.matchAll(/pid=(\d+)/g)].map(x => +x[1]) }]
  })
}

function nameOf(p: Proc, port: number | null) {
  if (port && FLEET[port]) return FLEET[port]
  const origin = p.args.includes("ms-playwright") ? "playwright" : p.args.includes("puppeteer") ? "puppeteer" : exe(p)
  const profile = p.args.match(/--user-data-dir=(\S+)/)?.[1]
  return profile ? `${origin} · ${profile.replace(/\/$/, "").split("/").pop()}` : origin
}

type Listen = { port: number; pids: number[] }
type ProbeFn = (port: number) => Promise<Probe | null>

// One browser from its root process: the whole tree's memory, and the first port in the tree that answers CDP.
async function describe(r: Proc, kids: Map<number, Proc[]>, listens: Listen[], probe: ProbeFn, viewer: string): Promise<Browser> {
  const tree: Proc[] = []
  for (const stack = [r]; stack.length; ) {
    const p = stack.pop()!
    tree.push(p)
    stack.push(...(kids.get(p.pid) ?? []))
  }
  const pids = new Set(tree.map(p => p.pid))
  const argPort = Number(r.args.match(/--(?:remote-debugging-)?port[= ](\d+)/)?.[1] ?? 0)
  const ports = [...new Set([argPort, ...listens.filter(l => l.pids.some(p => pids.has(p))).map(l => l.port)])].filter(Boolean)
  let port: number | null = null
  let info: Probe | null = null
  for (const p of ports) if ((info = await probe(p))) { port = p; break }
  const headless = exe(r).startsWith("obscura") || r.args.includes("--headless") || !!info?.ua.includes("Headless")
  return {
    pid: r.pid, name: nameOf(r, port), kind: headless ? "headless" : "headed", port, ageSec: r.age,
    rssKb: tree.reduce((s, p) => s + p.rss, 0), pages: info?.pages ?? [],
    ...(port === VNC_CDP_PORT ? { viewer } : {}),
  }
}

// Browser roots from ps, plus CDP endpoints on known ports whose owner is not visible. `probe` reads one CDP port.
export async function discover(psOut: string, ssOut: string, probe: ProbeFn, viewer: string): Promise<Browser[]> {
  const procs = parsePs(psOut)
  const byPid = new Map(procs.map(p => [p.pid, p]))
  const kids = new Map<number, Proc[]>()
  for (const p of procs) kids.set(p.ppid, [...(kids.get(p.ppid) ?? []), p])
  const listens = parseListens(ssOut)
  const roots = procs.filter(p => isBrowser(p) && !isBrowser(byPid.get(p.ppid)))
  const found = await Promise.all(roots.map(r => describe(r, kids, listens, probe, viewer)))
  const taken = new Set(found.map(b => b.port))
  const orphans = listens.filter(l => !l.pids.length && KNOWN_PORTS.includes(l.port) && !taken.has(l.port)).map(l => l.port)
  for (const port of [...new Set(orphans)]) {
    const info = await probe(port)
    if (info) found.push({ pid: null, name: FLEET[port] ?? "cdp", kind: info.ua.includes("Headless") ? "headless" : "headed", port, ageSec: null, rssKb: 0, pages: info.pages, ...(port === VNC_CDP_PORT ? { viewer } : {}) })
  }
  return found.sort((a, b) => a.kind.localeCompare(b.kind) || a.name.localeCompare(b.name) || (a.pid ?? 0) - (b.pid ?? 0))
}

// Connection: close, so a pooled socket does not count as a client and keep a fleet tier from its idle stop.
const cdp = (port: number, path: string) => fetch(`http://127.0.0.1:${port}${path}`, { headers: { Connection: "close" }, signal: AbortSignal.timeout(800) })

async function probeCdp(port: number): Promise<Probe | null> {
  try {
    const v = await (await cdp(port, "/json/version")).json()
    if (!v?.Browser) return null
    const list = (await (await cdp(port, "/json/list")).json()) as { id: string; type: string; title: string; url: string }[]
    return { ua: v["User-Agent"] ?? "", pages: list.filter(t => t.type === "page").map(t => ({ id: t.id, title: t.title, url: t.url })) }
  } catch {
    return null
  }
}

// The noVNC page as tailnet devices open it (docs/fleet-guards.md); loopback when the host is not on a tailnet.
function vncViewer() {
  try {
    const dns = JSON.parse(Bun.spawnSync(["tailscale", "status", "--json"]).stdout.toString()).Self?.DNSName?.replace(/\.$/, "")
    if (dns) return `https://${dns}:6909/vnc.html`
  } catch {}
  return "http://127.0.0.1:6909/vnc.html"
}

const run = (cmd: string[]) => Bun.spawnSync(cmd, { stderr: "ignore" }).stdout.toString()
const scan = (viewer: string) => discover(run(["ps", "-eo", "pid=,ppid=,etimes=,rss=,args="]), run(["ss", "-ltnpH"]), probeCdp, viewer)

// ---- rows ----------------------------------------------------------------------
export type Row = { b: Browser; page?: Page }
export const keyOf = (b: Browser) => (b.pid ? `pid:${b.pid}` : `port:${b.port}`)
export const flatten = (bs: Browser[], open: Set<string>): Row[] =>
  bs.flatMap(b => [{ b }, ...(open.has(keyOf(b)) ? b.pages.map(page => ({ b, page })) : [])])

export function age(sec: number | null) {
  if (sec === null) return "?"
  return sec < 60 ? `${sec}s` : sec < 3600 ? `${Math.floor(sec / 60)}m` : sec < 86400 ? `${Math.floor(sec / 3600)}h` : `${Math.floor(sec / 86400)}d`
}
export const mem = (kb: number) => (!kb ? "?" : kb < 1024 * 1024 ? `${Math.round(kb / 1024)}M` : `${(kb / 1024 / 1024).toFixed(1)}G`)
const clip = (t: string, w: number) => (t.length > w ? t.slice(0, Math.max(0, w - 1)) + "…" : t.padEnd(w))
const RIGHT_W = 33

export function columns(w: number) {
  return "  " + clip("KIND      NAME", w - RIGHT_W - 2) + "PID".padStart(8) + "PORT".padStart(6) + "AGE".padStart(6) + "MEM".padStart(7) + "PAGES".padStart(6)
}

type Seg = { text: string; fg: string; b?: boolean }
export function rowSegs(r: Row, w: number, open: boolean): Seg[] {
  if (r.page) {
    const t = r.page.title || "(untitled)"
    const tw = Math.min(t.length, Math.floor((w - 6) / 2))
    return [{ text: "      " + clip(t, tw), fg: theme.text }, { text: "  " + clip(r.page.url, Math.max(0, w - 8 - tw)), fg: theme.muted }]
  }
  const b = r.b
  const right = `${b.pid ?? "?"}`.padStart(8) + `${b.port ?? "-"}`.padStart(6) + age(b.ageSec).padStart(6) + mem(b.rssKb).padStart(7) + `${b.pages.length}`.padStart(6)
  return [
    { text: open ? "▾ " : "▸ ", fg: theme.muted },
    { text: b.kind.padEnd(10), fg: b.kind === "headed" ? theme.highlight : theme.accent, b: true },
    { text: clip(b.name, Math.max(0, w - RIGHT_W - 12)), fg: theme.text, b: true },
    { text: right, fg: theme.muted },
  ]
}

// Plain listing for `--once` and for agents.
export const snapshot = (bs: Browser[], w: number) =>
  [columns(w), ...flatten(bs, new Set(bs.map(keyOf))).map(r => rowSegs(r, w, true).map(s => s.text).join("").trimEnd()),
    ...bs.filter(b => b.viewer).map(b => `viewer ${b.name}: ${b.viewer}`)].join("\n")

// ---- terminal view -----------------------------------------------------------
// Flags: --once (print the list and exit), --fixture FILE (read a recorded Browser[] JSON; page and browser actions are not sent).
type Ui = { renderer: CliRenderer; header: TextRenderable; list: TextRenderable; footer: TextRenderable }
let ui: Ui
let fixture: string | undefined
let viewer = ""
let browsers: Browser[] = []
let loaded = false
let updated = ""
let note = ""
let error = ""
const open = new Set<string>()
let cursor = { key: "", page: "" }
let top = 0
let confirm: { text: string; act: () => Promise<string> } | null = null
let busy = false

const load = async (): Promise<Browser[]> => (fixture ? JSON.parse(await Bun.file(fixture).text()) : scan(viewer))
const rows = () => flatten(browsers, open)
const cur = (rs: Row[]) => Math.max(0, rs.findIndex(r => keyOf(r.b) === cursor.key && (r.page?.id ?? "") === cursor.page))

function s(text: string, color: string = theme.text, o: { bg?: string; b?: boolean } = {}): TextChunk {
  let c = fg(color)(text)
  if (o.bg) c = bg(o.bg)(c)
  return o.b ? bold(c) : c
}
const styled = (lines: TextChunk[][]) => new StyledText(lines.flatMap((l, i) => (i ? [s("\n"), ...l] : l)))

function drawHeader() {
  const headed = browsers.filter(b => b.kind === "headed").length
  ui.header.content = styled([
    [s(" BROWSERS ", theme.bg, { bg: theme.accent, b: true }), s(`  ${browsers.length} running  `, theme.text, { b: true }), s(`${headed} headed`, theme.highlight), s("  ·  ", theme.muted), s(`${browsers.length - headed} headless`, theme.accent)],
    [s(loaded ? `updated ${updated} · every ${REFRESH_MS / 1000}s${fixture ? " · fixture" : ""}` : "Scanning…", theme.muted), ...(error ? [s("  " + error, theme.error)] : [])],
  ])
}

// Formats only rows [top, top+h); the cursor stays in view.
function drawList(rs: Row[], c: number) {
  const inner = Math.max(20, ui.renderer.width - 4)
  const innerH = Math.max(1, ui.renderer.height - 2 - 2 - 2 - 1) // header, footer, box border, column titles
  top = Math.max(0, Math.min(c < top ? c : c >= top + innerH ? c - innerH + 1 : top, Math.max(0, rs.length - innerH)))
  const lines: TextChunk[][] = [[s(columns(inner), theme.muted, { b: true })]]
  for (let i = top; i < Math.min(rs.length, top + innerH); i++) {
    const on = i === c
    lines.push(rowSegs(rs[i], inner, open.has(keyOf(rs[i].b))).map(x => s(x.text, x.fg, { b: x.b || on, bg: on ? theme.border : undefined })))
  }
  if (loaded && !rs.length) lines.push([s("  No browsers are running.", theme.muted)])
  ui.list.content = styled(lines)
}

function drawFooter(sel: Browser | undefined) {
  const info = sel ? [s(` ${sel.name}`, theme.text, { b: true }), s(sel.port ? `  CDP http://127.0.0.1:${sel.port}` : "  no CDP port", theme.muted), ...(sel.viewer ? [s("  viewer ", theme.muted), s(sel.viewer, theme.highlight)] : [])] : [s(" ")]
  const keys = confirm
    ? [s(` ${confirm.text} `, theme.warn, { b: true }), s("y", theme.text, { b: true }), s(" yes  any other key no", theme.muted)]
    : [s(" ↑↓ move  ⏎ pages  r reload  c copy CDP URL  x close page  K stop browser  q quit", theme.muted), ...(note ? [s("   " + note, theme.text, { b: true })] : [])]
  ui.footer.content = styled([info, keys])
}

function draw() {
  const rs = rows()
  const c = cur(rs)
  drawHeader()
  drawList(rs, c)
  drawFooter(rs[c]?.b)
  ui.renderer.requestRender()
}

async function refresh() {
  if (busy) return
  busy = true
  try {
    browsers = await load()
    error = ""
    loaded = true
    updated = new Date().toLocaleTimeString("en-US", { hourCycle: "h23" })
  } catch (e) {
    error = (e as Error).message
  } finally {
    busy = false
    draw()
  }
}

// A y/n prompt guards every action that changes a browser. Fixture mode only reports what it would do.
function ask(text: string, act: () => Promise<string>) {
  confirm = { text, act: fixture ? async () => "fixture: nothing sent" : act }
}

function answer(yes: boolean) {
  const act = confirm!.act
  confirm = null
  if (!yes) note = "cancelled"
  else act().catch(e => `failed: ${(e as Error).message}`).then(m => { note = m }).finally(refresh)
}

function stopBrowser(r: Row | undefined) {
  if (!r) return
  const { pid, name } = r.b
  if (!pid) note = "no visible pid for this browser"
  else ask(`Stop ${name} (pid ${pid})?`, async () => { process.kill(pid, "SIGTERM"); return `sent SIGTERM to ${pid}` })
}

function closePage(r: Row | undefined) {
  const port = r?.b.port
  const page = r?.page
  if (!page || !port) note = "select a page first (⏎ opens a browser)"
  else ask(`Close page "${clip(page.title || page.url, 40).trimEnd()}"?`, async () => {
    // Chrome serves /json/close; Obscura drops the connection.
    const res = await cdp(port, `/json/close/${encodeURIComponent(page.id)}`).catch(() => null)
    return res?.ok ? "page closed" : `close failed: ${res ? `HTTP ${res.status}` : "this browser has no /json/close"}`
  })
}

function copyUrl(r: Row | undefined) {
  if (!r?.b.port) note = "no CDP port"
  else {
    const url = `http://127.0.0.1:${r.b.port}`
    note = ui.renderer.copyToClipboardOSC52(url) ? `copied ${url}` : `clipboard not supported: ${url}`
  }
}

function toggle(r: Row | undefined) {
  if (!r) return
  const key = keyOf(r.b)
  if (open.has(key)) open.delete(key)
  else open.add(key)
  cursor = { key, page: "" }
}

function onKey(k: { name: string; shift?: boolean }) {
  if (confirm) return answer(k.name === "y"), draw()
  note = ""
  const rs = rows()
  const c = cur(rs)
  const page = ui.renderer.height - 8
  const moves: Record<string, number> = { down: c + 1, j: c + 1, up: c - 1, k: c - 1, pagedown: c + page, pageup: c - page }
  const actions: Record<string, (r: Row | undefined) => void> = { K: stopBrowser, x: closePage, c: copyUrl, return: toggle, enter: toggle }
  const name = k.name === "k" && k.shift ? "K" : k.name
  if (name === "q") {
    ui.renderer.destroy()
    process.exit(0)
  }
  if (name === "r") return void refresh()
  if (name in moves) {
    const n = rs[Math.min(rs.length - 1, Math.max(0, moves[name]))]
    if (n) cursor = { key: keyOf(n.b), page: n.page?.id ?? "" }
  } else if (name in actions) actions[name](rs[c])
  else return
  draw()
}

async function main() {
  const argv = process.argv.slice(2)
  const fx = argv.indexOf("--fixture")
  fixture = fx >= 0 ? argv[fx + 1] : undefined
  viewer = fixture ? "" : vncViewer()
  if (argv.includes("--once")) {
    console.log(snapshot(await load(), Math.max(60, process.stdout.columns ?? 120)))
    process.exit(0)
  }
  const renderer = await createCliRenderer({ exitOnCtrlC: true })
  const column = new BoxRenderable(renderer, { flexDirection: "column", width: "100%", height: "100%" })
  const box = new BoxRenderable(renderer, {
    border: true, borderStyle: "rounded", borderColor: theme.border, titleColor: theme.text,
    title: " Browsers · headed and headless ", titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexGrow: 1,
  })
  ui = {
    renderer,
    header: new TextRenderable(renderer, { content: "", flexShrink: 0 }),
    list: new TextRenderable(renderer, { content: "" }),
    footer: new TextRenderable(renderer, { content: "", flexShrink: 0 }),
  }
  box.add(ui.list)
  column.add(ui.header)
  column.add(box)
  column.add(ui.footer)
  renderer.root.add(column)
  renderer.on("resize", draw)
  renderer.keyInput.on("keypress", onKey)
  draw()
  await refresh()
  setInterval(refresh, REFRESH_MS)
}

if (import.meta.main) await main()
