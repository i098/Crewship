#!/usr/bin/env bun
// Every no-mistakes validation run on this host (read-only): local run records plus each firstmate home's state/*.meta.
// `--once` prints plain text and exits; without it the table refreshes from local files.
import { Database } from "bun:sqlite"
import { existsSync, readdirSync, readFileSync } from "node:fs"
import { theme } from "../tui-theme/theme.ts"

const HOME = process.env.HOME ?? ""
const DB_PATH = process.env.RUNS_TUI_DB ?? `${HOME}/.no-mistakes/state.sqlite`
const REFRESH_MS = 5_000
const MAXW = 150

// ---- homes and task mapping ---------------------------------------------
// RUNS_TUI_HOMES (":"-separated firstmate home roots) overrides discovery.
function homeRoots(): string[] {
  if (process.env.RUNS_TUI_HOMES !== undefined) return process.env.RUNS_TUI_HOMES.split(":").filter(Boolean)
  const roots = [`${HOME}/Dev/firstmate`]
  const base = `${HOME}/.treehouse`
  for (const d of existsSync(base) ? readdirSync(base) : []) {
    if (!d.startsWith("firstmate-")) continue
    for (const n of readdirSync(`${base}/${d}`)) roots.push(`${base}/${d}/${n}/firstmate`)
  }
  return roots
}

function homeLabel(root: string): string {
  const m = root.match(/firstmate-([^/]+)\/([^/]+)\/firstmate$/)
  return m ? `${m[1]}/${m[2]}` : "dev"
}

// A repo registered under a home's projects/ dir belongs to that home even when its task meta is gone.
function homeOfProject(path: string): string {
  const root = path.match(/^(.*\/firstmate)\/projects\//)?.[1]
  return root ? homeLabel(root) : "unknown"
}

type Meta = { home: string; task: string }
const metaKey = (project: string, branch: string) => `${project}\n${branch}`

function loadMetas(): Map<string, Meta> {
  const out = new Map<string, Meta>()
  for (const root of homeRoots()) {
    const dir = `${root}/state`
    if (!existsSync(dir)) continue
    for (const f of readdirSync(dir)) {
      if (!f.endsWith(".meta")) continue
      const kv: Record<string, string> = {}
      for (const line of readFileSync(`${dir}/${f}`, "utf8").split("\n")) {
        const i = line.indexOf("=")
        if (i > 0) kv[line.slice(0, i)] = line.slice(i + 1)
      }
      if (kv.project && kv.branch) out.set(metaKey(kv.project, kv.branch), { home: homeLabel(root), task: kv.endpoint_task_id || f.slice(0, -5) })
    }
  }
  return out
}

// ---- data ----------------------------------------------------------------
export type Outcome = "running" | "parked" | "failed" | "passed" | "cancelled"
export type Run = {
  id: string; home: string; task: string; repo: string; pr: string; step: string
  loops: Record<string, number>; elapsed: number; outcome: Outcome; updated: number
}

const ORDER: Record<Outcome, number> = { running: 0, parked: 1, failed: 2, passed: 3, cancelled: 4 }

function outcomeOf(status: string, steps: { status: string }[], awaiting: number | null): Outcome {
  if (status === "completed") return "passed"
  if (status === "failed") return "failed"
  if (status === "cancelled") return "cancelled"
  return awaiting || steps.some(s => s.status === "awaiting_approval" || s.status === "fix_review") ? "parked" : "running"
}

type RunRow = { id: string; branch: string; status: string; pr_url: string | null; awaiting: number | null; created_at: number; updated_at: number; working_path: string; upstream_url: string }
type StepRow = { run_id: string; step_name: string; step_order: number; status: string; fixes: number; ci_fix_attempts: number }

export function load(now = Date.now() / 1000): Run[] {
  const db = new Database(DB_PATH, { readonly: true })
  try {
    const runs = db.query(`select r.id, r.branch, r.status, r.pr_url, r.awaiting_agent_since awaiting, r.created_at, r.updated_at, p.working_path, p.upstream_url
      from runs r join repos p on p.id = r.repo_id`).all() as RunRow[]
    const steps = db.query(`select s.run_id, s.step_name, s.step_order, s.status, s.ci_fix_attempts, coalesce(f.n, 0) fixes
      from step_results s
      left join (select step_result_id, count(*) n from step_rounds where trigger_type = 'auto_fix' group by 1) f on f.step_result_id = s.id
      order by s.step_order`).all() as StepRow[]
    const byRun = new Map<string, StepRow[]>()
    for (const s of steps) (byRun.get(s.run_id) ?? byRun.set(s.run_id, []).get(s.run_id)!).push(s)
    const metas = loadMetas()
    return runs.map(r => {
      const st = byRun.get(r.id) ?? []
      const outcome = outcomeOf(r.status, st, r.awaiting)
      const meta = metas.get(metaKey(r.working_path, r.branch))
      const live = st.find(s => s.status === "running" || s.status === "fixing" || s.status === "awaiting_approval" || s.status === "fix_review")
      const bad = st.find(s => s.status === "failed")
      const last = [...st].reverse().find(s => s.status === "completed")
      const cur = outcome === "failed" ? bad ?? last : live ?? last
      const loops: Record<string, number> = {}
      for (const s of st) {
        const n = Math.max(s.fixes, s.ci_fix_attempts)
        if (n) loops[s.step_name] = n
      }
      const pr = r.pr_url?.match(/\/pull\/(\d+)/)?.[1]
      return {
        id: r.id, home: meta?.home ?? homeOfProject(r.working_path), task: meta?.task ?? "unknown",
        repo: (r.upstream_url.match(/([^/]+?)(?:\.git)?$/)?.[1]) ?? "unknown",
        pr: pr ? `#${pr}` : "-",
        step: cur ? cur.step_name + (cur.status === "fixing" ? " fix" : "") : "-",
        loops, outcome, updated: r.updated_at,
        elapsed: Math.max(0, (outcome === "running" || outcome === "parked" ? now : r.updated_at) - r.created_at),
      }
    }).sort((a, b) => ORDER[a.outcome] - ORDER[b.outcome] || b.updated - a.updated)
  } finally {
    db.close()
  }
}

// ---- rendering -----------------------------------------------------------
type Seg = [text: string, color: string, bold?: boolean, background?: string]
type Line = Seg[]

const fit = (t: string, w: number) => (t.length > w ? t.slice(0, Math.max(0, w - 1)) + "…" : t.padEnd(w))
export function fmtElapsed(sec: number): string {
  const s = Math.floor(sec)
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m${String(s % 60).padStart(2, "0")}s`
  if (s < 86400) return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`
  return `${Math.floor(s / 86400)}d${String(Math.floor((s % 86400) / 3600)).padStart(2, "0")}h`
}
const loopText = (l: Record<string, number>) => Object.entries(l).map(([k, v]) => `${k} ${v}`).join(" · ") || "-"
const outcomeColor: Record<Outcome, string> = { running: theme.accent, parked: theme.warn, failed: theme.error, passed: theme.ok, cancelled: theme.muted }

export function tableLines(runs: Run[], inner: number): Line[] {
  const hw = 10, rw = 16, pw = 6, sw = 10, ew = 8, ow = 9
  const rest = Math.max(20, inner - (hw + rw + pw + sw + ew + ow + 7 * 2))
  const tw = Math.floor(rest * 0.4), lw = rest - tw
  const row = (c: string[], color: (i: number) => string, bold = false): Line => {
    const w = [hw, tw, rw, pw, sw, lw, ew, ow]
    return c.map((t, i): Seg => [fit(t, w[i]) + (i < c.length - 1 ? "  " : ""), color(i), bold])
  }
  const lines = [row(["HOME", "TASK", "REPO", "PR", "STEP", "LOOPS", "ELAPSED", "OUTCOME"], () => theme.muted, true)]
  for (const r of runs) {
    lines.push(row([r.home, r.task, r.repo, r.pr, r.step, loopText(r.loops), fmtElapsed(r.elapsed), r.outcome],
      i => (i === 7 ? outcomeColor[r.outcome] : i === 5 && Object.keys(r.loops).length ? theme.highlight : r.home === "unknown" && i < 2 ? theme.muted : theme.text), false))
  }
  if (!runs.length) lines.push([["No validation runs recorded.", theme.muted]])
  return lines
}

function counts(runs: Run[]): Record<Outcome, number> {
  const c: Record<Outcome, number> = { running: 0, parked: 0, failed: 0, passed: 0, cancelled: 0 }
  for (const r of runs) c[r.outcome]++
  return c
}

export function once(runs: Run[], width = MAXW): string {
  const c = counts(runs)
  const head = `VALIDATION RUNS  ${runs.length} runs · ${c.running} running · ${c.parked} parked · ${c.passed} passed · ${c.failed} failed · ${c.cancelled} cancelled`
  return [head, ...tableLines(runs, width - 4).map(l => l.map(s => s[0]).join("").trimEnd())].join("\n") + "\n"
}

// ---- live view -----------------------------------------------------------
async function live() {
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
    title: " Validation runs · running first, then newest ", titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexShrink: 0,
  })
  const body = new TextRenderable(renderer, { content: "" })
  box.add(body)
  column.add(header)
  column.add(box)
  renderer.root.add(column)

  let runs: Run[] = []
  let error = ""
  let top = 0
  const styled = (lines: Line[]) => new StyledText(lines.flatMap((l, i) => [...(i ? [chunk(["\n", theme.text])] : []), ...l.map(chunk)]))

  function draw() {
    const W = Math.min(MAXW, renderer.width)
    column.width = W
    const c = counts(runs)
    const page = Math.max(1, renderer.height - 6)
    top = Math.max(0, Math.min(top, runs.length - page))
    const lines = tableLines(runs.slice(top, top + page), W - 4)
    header.content = styled([
      [[" VALIDATION RUNS ", theme.bg, true, theme.accent], ["  ", theme.text], [`${c.running} running`, theme.accent], [` · ${c.parked} parked`, theme.warn], [` · ${c.passed} passed`, theme.ok], [` · ${c.failed} failed`, theme.error], [` · ${c.cancelled} cancelled`, theme.muted]],
      [[`${runs.length} runs · every ${REFRESH_MS / 1000}s · `, theme.muted], ["↑↓", theme.text, true], [" scroll  ", theme.muted], ["q", theme.text, true], [" quit  ", theme.muted], ["r", theme.text, true], [" refresh", theme.muted], ...(error ? [["  " + error, theme.error] as Seg] : [])],
    ])
    body.content = styled(lines)
    renderer.requestRender()
  }


  function refresh() {
    try {
      runs = load()
      error = ""
    } catch (e) {
      error = `Cannot read ${DB_PATH}: ${(e as Error).message}`
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
    if (k.name === "down" || k.name === "j") { top++; draw() }
    if (k.name === "up" || k.name === "k") { top--; draw() }
  })
}

if (import.meta.main) {
  if (process.argv.includes("--once")) {
    try {
      process.stdout.write(once(load()))
    } catch (e) {
      console.error(`Cannot read ${DB_PATH}: ${(e as Error).message}`)
      process.exit(1)
    }
  } else {
    await live()
  }
}
