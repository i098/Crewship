#!/usr/bin/env bun
// Every no-mistakes validation run on this host (read-only): local run records plus each firstmate home's state/*.meta.
// `--once` prints plain text and exits; `--json` prints one JSON document (runs with post-mortems, unmatched lines) and exits; without either the table refreshes from local files.
// Default view: running and parked runs plus runs finished in the last 24h; `--all` (key `a`) shows every run.
// `--anonymize` replaces home, mate, task, repo and PR with stable placeholders (for screenshots).
// Post-mortem lines (validation-postmortems.md files, read-only) show under the run they name; key `p` lists the rest.
import { Database } from "bun:sqlite"
import { existsSync, readdirSync, readFileSync } from "node:fs"
import { resolve } from "node:path"
import { theme } from "../tui-theme/theme.ts"

const HOME = process.env.HOME ?? ""
const DB_PATH = process.env.RUNS_TUI_DB ?? `${HOME}/.no-mistakes/state.sqlite`
const REFRESH_MS = 5_000
const RECENT_SEC = 24 * 3600
const MAXW = 160
const ANON = process.argv.includes("--anonymize")

// ---- homes, mates and task mapping --------------------------------------
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

const HOME_RE = /firstmate-([^/_]+)[/_](\d+)[/_]firstmate/
// Treehouse homes are `<suffix>/<n>`; any other root is the main firstmate home.
const homeLabel = (root: string) => root.match(HOME_RE)?.slice(1, 3).join("/") ?? "main"

type Meta = { root: string; task: string }
type Registry = { byProject: Map<string, Meta>; byBranch: Map<string, Meta>; projectRoot: Map<string, string>; mates: Map<string, string> }

function loadRegistry(): Registry {
  const reg: Registry = { byProject: new Map(), byBranch: new Map(), projectRoot: new Map(), mates: new Map() }
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
      const id = kv.endpoint_task_id || f.slice(0, -5)
      // A second mate's meta names the home it owns.
      if (kv.kind === "secondmate" && kv.home) reg.mates.set(kv.home.replace(/\/$/, ""), id.replace(/-mate(-[a-z0-9]+)?$/, ""))
      else if (kv.branch) {
        const meta = { root, task: id }
        reg.byProject.set(`${kv.project}\n${kv.branch}`, meta)
        if (!reg.byBranch.has(kv.branch)) reg.byBranch.set(kv.branch, meta)
        if (kv.project && !reg.projectRoot.has(kv.project)) reg.projectRoot.set(kv.project, root)
      }
    }
  }
  return reg
}

// A repo under a home's projects/ dir, or a worktree named after one, belongs to that home even when its task meta is gone.
function homeRootOf(workingPath: string, worktreeDir: string | null): string | undefined {
  const fromProject = workingPath.match(/^(.*\/firstmate)\/projects\//)?.[1]
  if (fromProject) return fromProject
  const w = worktreeDir?.match(/\.treehouse_(firstmate-[^_/]+)_(\d+)_firstmate_projects/)
  return w ? `${HOME}/.treehouse/${w[1]}/${w[2]}/firstmate` : undefined
}

// ---- data ----------------------------------------------------------------
export type Outcome = "running" | "parked" | "failed" | "passed" | "cancelled"
export type Run = {
  id: string; home: string; mate: string; task: string; repo: string; pr: string; prUrl: string | null; step: string
  loops: Record<string, number>; elapsed: number; outcome: Outcome; updated: number; notes: string[]
}

const ORDER: Record<Outcome, number> = { running: 0, parked: 1, failed: 2, passed: 3, cancelled: 4 }
const isLive = (o: Outcome) => o === "running" || o === "parked"

function outcomeOf(status: string, steps: { status: string }[], awaiting: number | null): Outcome {
  if (status === "completed") return "passed"
  if (status === "failed") return "failed"
  if (status === "cancelled") return "cancelled"
  return awaiting || steps.some(s => s.status === "awaiting_approval" || s.status === "fix_review") ? "parked" : "running"
}

type RunRow = { id: string; branch: string; status: string; pr_url: string | null; awaiting: number | null; created_at: number; updated_at: number; working_path: string; upstream_url: string; worktree_dir: string | null }
type StepRow = { run_id: string; step_name: string; step_order: number; status: string; fixes: number; ci_fix_attempts: number }

export function load(now = Date.now() / 1000): Run[] {
  const db = new Database(DB_PATH, { readonly: true })
  try {
    const runs = db.query(`select r.id, r.branch, r.status, r.pr_url, r.awaiting_agent_since awaiting, r.created_at, r.updated_at, r.worktree_dir, p.working_path, p.upstream_url
      from runs r join repos p on p.id = r.repo_id`).all() as RunRow[]
    const steps = db.query(`select s.run_id, s.step_name, s.step_order, s.status, s.ci_fix_attempts, coalesce(f.n, 0) fixes
      from step_results s
      left join (select step_result_id, count(*) n from step_rounds where trigger_type = 'auto_fix' group by 1) f on f.step_result_id = s.id
      order by s.step_order`).all() as StepRow[]
    const byRun = new Map<string, StepRow[]>()
    for (const s of steps) (byRun.get(s.run_id) ?? byRun.set(s.run_id, []).get(s.run_id)!).push(s)
    const reg = loadRegistry()
    return runs.map(r => {
      const st = byRun.get(r.id) ?? []
      const outcome = outcomeOf(r.status, st, r.awaiting)
      const meta = reg.byProject.get(`${r.working_path}\n${r.branch}`) ?? reg.byBranch.get(r.branch)
      const root = meta?.root ?? homeRootOf(r.working_path, r.worktree_dir) ?? reg.projectRoot.get(r.working_path)
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
      const label = root ? homeLabel(root) : "unknown"
      return {
        id: r.id, home: label,
        mate: !root ? "unknown" : label === "main" ? "main" : reg.mates.get(root) ?? "unknown",
        // Torn-down tasks have no meta; their branch (fm/<task>) still names the task.
        task: meta?.task ?? (r.branch.replace(/^[^/]*\//, "") || "unknown"),
        repo: r.upstream_url.match(/([^/]+?)(?:\.git)?$/)?.[1] ?? "unknown",
        pr: pr ? `#${pr}` : "-", prUrl: r.pr_url, notes: [],
        step: cur ? cur.step_name + (cur.status === "fixing" ? " fix" : "") : "-",
        loops, outcome, updated: r.updated_at,
        elapsed: Math.max(0, (isLive(outcome) ? now : r.updated_at) - r.created_at),
      }
    }).sort((a, b) => ORDER[a.outcome] - ORDER[b.outcome] || b.updated - a.updated)
  } finally {
    db.close()
  }
}

export function visible(runs: Run[], all: boolean, now = Date.now() / 1000): Run[] {
  return all ? runs : runs.filter(r => isLive(r.outcome) || now - r.updated <= RECENT_SEC)
}

// ---- post-mortems ----------------------------------------------------------
const DATED = /^\d{4}-\d{2}-\d{2}\b/
// Two formats: markdown table rows whose first cell is a date, and free-text lines starting with a date
// (`2026-10-27 | PR: <url> | text`); plain lines right after a free-text entry continue it.
export function parsePostmortems(text: string): string[] {
  const out: string[] = []
  let open = false
  for (const raw of text.split("\n")) {
    const line = raw.trim()
    if (line.startsWith("|")) {
      const cells = line.replace(/^\||\|$/g, "").split("|").map(c => c.trim().replaceAll("&#124;", "|"))
      if (DATED.test(cells[0])) out.push(cells.filter(Boolean).join(" | "))
      open = false
    } else if (DATED.test(line)) {
      out.push(line)
      open = true
    } else if (open && line && !line.startsWith("#")) out[out.length - 1] += " " + line
    else open = false
  }
  return out.map(s => s.replace(/\s+/g, " "))
}

// The repo log plus CREWSHIP_POSTMORTEM_PATHS (":"-separated paths or globs); missing files are skipped.
export function readPostmortems(): string[] {
  const patterns = [resolve(import.meta.dir, "../../docs/validation-postmortems.md"), ...(process.env.CREWSHIP_POSTMORTEM_PATHS ?? "").split(":").filter(Boolean)]
  // Bun.Glob finds nothing for a literal absolute path, so only real patterns go through it.
  const files = new Set(patterns.flatMap(p => (/[*?[{]/.test(p) ? [...new Bun.Glob(p).scanSync({ absolute: true, onlyFiles: true })] : existsSync(p) ? [resolve(p)] : [])))
  return [...files].flatMap(f => parsePostmortems(readFileSync(f, "utf8")))
}

// A line belongs to every run whose id, PR URL or PR number (`#42`) it names; returns the lines no run claims.
export function attachPostmortems(runs: Run[], notes: string[]): string[] {
  for (const r of runs) r.notes = []
  return notes.filter(n => {
    // Whole tokens, so `#421` or `/pull/421` never names PR 42.
    const refs = new Set(n.match(/#\d+/g))
    const namesUrl = (u: string) => n.split(u).slice(1).some(rest => !/^\d/.test(rest))
    const hits = runs.filter(r => n.includes(r.id) || refs.has(r.pr) || (r.prUrl !== null && namesUrl(r.prUrl)))
    for (const r of hits) r.notes.push(n)
    return !hits.length
  })
}

// Stable placeholders per distinct value, in first-seen order.
export function anonymize(runs: Run[]): Run[] {
  const seen: Record<string, Map<string, string>> = {}
  const alias = (kind: string, v: string) => {
    if (v === "unknown" || v === "-" || (kind === "mate" && v === "main") || (kind === "home" && v === "main")) return v
    const m = (seen[kind] ??= new Map())
    return m.get(v) ?? m.set(v, kind === "pr" ? `#${100 + m.size * 37}` : `${kind}-${m.size + 1}`).get(v)!
  }
  return runs.map(r => ({ ...r, home: alias("home", r.home), mate: alias("mate", r.mate), task: alias("task", r.task), repo: alias("repo", r.repo), pr: alias("pr", r.pr) }))
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
  const hw = 9, mw = 12, rw = 16, pw = 6, sw = 10, ew = 8, ow = 9
  const rest = Math.max(20, inner - (hw + mw + rw + pw + sw + ew + ow + 8 * 2))
  const tw = Math.floor(rest * 0.45), lw = rest - tw
  const w = [hw, mw, tw, rw, pw, sw, lw, ew, ow]
  const row = (c: string[], color: (i: number) => string, bold = false): Line =>
    c.map((t, i): Seg => [fit(t, w[i]) + (i < c.length - 1 ? "  " : ""), color(i), bold])
  const lines = [row(["HOME", "MATE", "TASK", "REPO", "PR", "STEP", "LOOPS", "ELAPSED", "OUTCOME"], () => theme.muted, true)]
  for (const r of runs) {
    const cells = [r.home, r.mate, r.task, r.repo, r.pr, r.step, loopText(r.loops), fmtElapsed(r.elapsed), r.outcome]
    lines.push(row(cells, i => (i === 8 ? outcomeColor[r.outcome] : i === 6 && cells[6] !== "-" ? theme.highlight : cells[i] === "unknown" ? theme.muted : theme.text)))
    for (const n of r.notes) lines.push([["  ↳ ", theme.warn], [fit(n, inner - 4), theme.muted]])
  }
  if (!runs.length) lines.push([["No validation runs in this view.", theme.muted]])
  return lines
}

export function unmatchedLines(notes: string[], inner: number): Line[] {
  return notes.length ? notes.map(n => [["• ", theme.warn], [fit(n, inner - 2), theme.text]]) : [[["Every post-mortem line names a run.", theme.muted]]]
}

function counts(runs: Run[]): Record<Outcome, number> {
  const c: Record<Outcome, number> = { running: 0, parked: 0, failed: 0, passed: 0, cancelled: 0 }
  for (const r of runs) c[r.outcome]++
  return c
}

const scope = (shown: number, total: number, all: boolean) => (all ? `all ${total} runs` : `${shown} of ${total} runs: live + last 24h`)

export function once(runs: Run[], all: boolean, unmatched: string[], width = MAXW): string {
  const shown = visible(runs, all)
  const c = counts(shown)
  const head = `VALIDATION RUNS  ${scope(shown.length, runs.length, all)} · ${c.running} running · ${c.parked} parked · ${c.passed} passed · ${c.failed} failed · ${c.cancelled} cancelled`
  const text = (lines: Line[]) => lines.map(l => l.map(s => s[0]).join("").trimEnd())
  const loose = unmatched.length ? ["", `POST-MORTEMS NOT MATCHED TO A RUN  ${unmatched.length}`, ...text(unmatchedLines(unmatched, width - 4))] : []
  return [head, ...text(tableLines(shown, width - 4)), ...loose].join("\n") + "\n"
}

// `--json`: one document for agents. Date, ref and text are split from the parsed line; `raw` is the line itself.
export type Postmortem = { date: string; ref: string; text: string; raw: string }
export function postmortemJson(raw: string): Postmortem {
  const cells = raw.slice(10).replace(/^[:\s|]+/, "").split(" | ")
  const [ref, ...rest] = cells.length > 1 ? cells : ["", cells[0]]
  return { date: raw.slice(0, 10), ref: ref.replace(/^PR:\s*/, ""), text: rest.join(" | "), raw }
}

export function json(runs: Run[], all: boolean, unmatched: string[]): string {
  const shown = visible(runs, all).map(({ notes, ...r }) => ({ ...r, postmortems: notes.map(postmortemJson) }))
  return JSON.stringify({ runs: shown, unmatched: unmatched.map(postmortemJson) }) + "\n"
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
    title: " Validation runs · running first, then newest ", titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexShrink: 0,
  })
  const body = new TextRenderable(renderer, { content: "" })
  box.add(body)
  column.add(header)
  column.add(box)
  renderer.root.add(column)

  let runs: Run[] = []
  let postmortemNotes: string[] = []
  let unmatched: string[] = []
  let error = ""
  let top = 0
  let all = startAll
  let postmortems = false
  const styled = (lines: Line[]) => new StyledText(lines.flatMap((l, i) => [...(i ? [chunk(["\n", theme.text])] : []), ...l.map(chunk)]))

  function draw() {
    const W = Math.min(MAXW, renderer.width)
    column.width = W
    const shown = visible(runs, all)
    unmatched = ANON ? [] : attachPostmortems(shown, postmortemNotes)
    const c = counts(shown)
    const page = Math.max(1, renderer.height - 6)
    const lines = postmortems ? unmatchedLines(unmatched, W - 4) : tableLines(shown, W - 4)
    const fixed = postmortems ? 0 : 1 // the column header stays put while rows scroll
    top = Math.max(0, Math.min(top, lines.length - fixed - page))
    box.title = postmortems ? ` Post-mortems not matched to a run · ${unmatched.length} ` : " Validation runs · running first, then newest "
    header.content = styled([
      [[" VALIDATION RUNS ", theme.bg, true, theme.accent], ["  ", theme.text], [`${c.running} running`, theme.accent], [` · ${c.parked} parked`, theme.warn], [` · ${c.passed} passed`, theme.ok], [` · ${c.failed} failed`, theme.error], [` · ${c.cancelled} cancelled`, theme.muted]],
      [[`${scope(shown.length, runs.length, all)} · every ${REFRESH_MS / 1000}s · `, theme.muted], ["a", theme.text, true], [" all/24h  ", theme.muted], ["p", theme.text, true], [` unmatched post-mortems (${unmatched.length})  `, theme.muted], ["↑↓", theme.text, true], [" scroll  ", theme.muted], ["q", theme.text, true], [" quit  ", theme.muted], ["r", theme.text, true], [" refresh", theme.muted], ...(error ? [["  " + error, theme.error] as Seg] : [])],
    ])
    body.content = styled([...lines.slice(0, fixed), ...lines.slice(fixed + top, fixed + top + page)])
    renderer.requestRender()
  }

  function refresh() {
    try {
      runs = load()
      postmortemNotes = readPostmortems()
      if (ANON) runs = anonymize(runs)
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
    if (k.name === "a") { all = !all; top = 0; draw() }
    if (k.name === "p") { postmortems = !postmortems; top = 0; draw() }
    if (k.name === "down" || k.name === "j") { top++; draw() }
    if (k.name === "up" || k.name === "k") { top--; draw() }
  })
}

if (import.meta.main) {
  const all = process.argv.includes("--all")
  if (process.argv.includes("--once") || process.argv.includes("--json")) {
    try {
      const runs = load()
      const shown = visible(runs, all)
      const unmatched = ANON ? [] : attachPostmortems(shown, readPostmortems())
      const view = ANON ? anonymize(runs) : runs
      process.stdout.write(process.argv.includes("--json") ? json(view, all, unmatched) : once(view, all, unmatched))
    } catch (e) {
      console.error(`Cannot read ${DB_PATH}: ${(e as Error).message}`)
      process.exit(1)
    }
  } else {
    await live(all)
  }
}
