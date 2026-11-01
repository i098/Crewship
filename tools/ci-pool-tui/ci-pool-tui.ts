#!/usr/bin/env bun
// CI pool TUI: slots, GitHub runners, queued and running workflow runs, and what is held up. Read only.
// The model (first half) is pure and tested in pool.test.ts; the rest reads systemd, docker and GitHub.
import { BoxRenderable, StyledText, TextRenderable, bg, bold, createCliRenderer, fg, type TextChunk } from "@opentui/core"
import { accessSync, constants, readFileSync } from "node:fs"
import { theme } from "../tui-theme/theme.ts"

// ---- model ----------------------------------------------------------------
export const HELD_AFTER_S = 300 // a queued job older than this is held up
export const LONG_JOB_S = 6 * 3600 // a job running longer than this is worth a look
export const SETTLE_S = 120 // a slot problem must last this long to count as stuck: a job ends, its runner leaves GitHub, then its container exits
export const STALL_S = 300 // a slot older than this must have a container and a registered runner (same rule as ci-pool.py watch)
export const CALLS_PER_MIN = 20 // GitHub REST budget
export const CALL_GAP_MS = 60_000 / CALLS_PER_MIN
export const MIN_AGE_MS = 60_000 // one GitHub read is never repeated sooner
const JOB_RUNS_PER_REPO = 8 // job reads per repo and kind (queued, in progress)

export type PoolEntry = { repo: string; slots: number; labels: string[]; name?: string }
export type Slot = { slot: string; repo: string }
export type Unit = { state: string; age: number }
export type Box = { state: string; status: string }
export type Runner = { name: string; status: string; busy: boolean; labels: { name: string }[] }
export type Run = { id: number; display_title?: string; name?: string; head_branch?: string; status: string; created_at: string; run_started_at?: string }
export type Job = { id: number; run_id: number; name: string; status: string; created_at: string; started_at?: string | null; runner_name?: string | null; labels: string[] }

export type Snapshot = {
  now: number
  slots: Slot[]
  units: Record<string, Unit>
  containers: Record<string, Box> | null // null: docker did not answer
  runners: Record<string, Runner[]> // by repo; a repo not yet read has no key
  queued: Record<string, Run[]>
  progress: Record<string, Run[]>
  jobs: Record<string, Job[]> // by run id
  errors: string[]
  firstSeen?: Record<string, number> // slot → ms when its current problem was first seen; a missing key means "seen long enough"
}

export const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")

export function poolSlots(pool: { repos: PoolEntry[] }): Slot[] {
  return pool.repos.flatMap(e => Array.from({ length: e.slots }, (_, i) => ({ slot: `${slug(e.name ?? e.repo)}-${i + 1}`, repo: e.repo })))
}

/** `systemctl --user show ci-runner@*.service -p Id -p ActiveState -p ActiveEnterTimestampMonotonic`; bootSeconds is the monotonic clock now. */
export function parseUnits(text: string, bootSeconds: number): Record<string, Unit> {
  const units: Record<string, Unit> = {}
  for (const block of text.split("\n\n")) {
    const f = Object.fromEntries(block.split("\n").filter(l => l.includes("=")).map(l => [l.slice(0, l.indexOf("=")), l.slice(l.indexOf("=") + 1)]))
    const m = /^ci-runner@(.+)\.service$/.exec(f.Id ?? "")
    if (m) units[m[1]] = { state: f.ActiveState, age: Math.max(0, bootSeconds - Number(f.ActiveEnterTimestampMonotonic) / 1e6) }
  }
  return units
}

/** `docker ps --all --format '{{.Names}}\t{{.State}}\t{{.Status}}'` */
export function parseContainers(text: string): Record<string, Box> {
  const out: Record<string, Box> = {}
  for (const line of text.split("\n")) {
    const [name, state, status] = line.split("\t")
    if (name && state) out[name] = { state, status: status ?? "" }
  }
  return out
}

const secs = (iso: string | null | undefined, now: number) => (iso ? Math.max(0, (now - Date.parse(iso)) / 1000) : null)

export function newestRunner(list: Runner[] | undefined, slot: string): Runner | undefined {
  const own = (list ?? []).filter(r => new RegExp(`^pool-${slot.replace(/[^a-z0-9-]/g, "")}-\\d+$`).test(r.name))
  return own.sort((a, b) => Number(b.name.split("-").pop()) - Number(a.name.split("-").pop()))[0]
}

export type SlotRow = { slot: string; repo: string; level: "ok" | "idle" | "bad"; state: string; container: string; age: number | null; runner: string; job: string; jobAge: number | null; problem?: string; stuck?: string }

const repoJobs = (s: Snapshot, repo: string) => [...(s.queued[repo] ?? []), ...(s.progress[repo] ?? [])].flatMap(r => s.jobs[r.id] ?? [])

export function slotRows(s: Snapshot): SlotRow[] {
  return s.slots.map(({ slot, repo }) => {
    const unit = s.units[slot]
    const box = s.containers?.[`ci-runner-${slot}`]
    const runner = newestRunner(s.runners[repo], slot)
    const known = repo in s.runners
    const job = runner && repoJobs(s, repo).find(j => j.status === "in_progress" && j.runner_name === runner.name)
    const row: SlotRow = {
      slot, repo, level: "idle", state: "idle",
      container: s.containers === null ? "?" : box ? `${box.state}${box.state === "running" ? " " + box.status.replace(/^Up /, "") : ""}` : "none",
      age: unit ? unit.age : null,
      runner: !known ? "…" : !runner ? "none" : runner.status === "online" ? (runner.busy ? "busy" : "online") : runner.status,
      jobAge: secs(job?.started_at, s.now),
      job: job ? `${(s.progress[repo] ?? []).find(r => r.id === job.run_id)?.display_title ?? "run " + job.run_id} / ${job.name}` : runner?.busy ? "(job not read yet)" : "",
    }
    let stuck = ""
    if (!unit) stuck = "no ci-runner@ unit"
    else if (unit.state === "failed") stuck = "unit failed"
    else if (unit.state !== "active") { row.state = unit.state; row.level = "idle" } // activating, stopped (drained)
    else if (unit.age > STALL_S) {
      if (box && box.state !== "running") stuck = `container ${box.state}`
      else if (s.containers && !box) stuck = `no container for ${Math.round(unit.age / 60)} min`
      else if (known && !runner) stuck = "runner never registered on GitHub"
      else if (runner && runner.status !== "online" && !runner.busy) stuck = `runner ${runner.status} on GitHub`
    }
    if (stuck) {
      row.problem = stuck
      const first = s.firstSeen?.[slot]
      if (first !== undefined && s.now - first < SETTLE_S * 1000) { row.state = "ending"; row.job = stuck }
      else { row.level = "bad"; row.state = "STUCK"; row.stuck = stuck }
    }
    else if (unit?.state === "active") {
      row.level = runner?.busy ? "ok" : "idle"
      row.state = runner?.busy ? "busy" : runner?.status === "online" ? "idle" : known ? "starting" : "up"
    }
    return row
  })
}

export type Finding = { sev: "bad" | "warn"; where: string; what: string; age: number | null; cause: string }

/** Why a queued job that wants these labels has no runner. */
export function heldCause(labels: string[], runners: Runner[] | undefined): string {
  if (!runners) return "runners of this repo not read yet"
  const want = labels.map(l => l.toLowerCase())
  const match = runners.filter(r => want.every(l => r.labels.some(x => x.name.toLowerCase() === l)))
  if (!match.length) return `no runner has labels ${labels.join(",")}`
  const free = match.filter(r => r.status === "online" && !r.busy)
  if (free.length) return `${free.length} idle matching runner(s) online; GitHub has not assigned the job`
  const online = match.filter(r => r.status === "online")
  return online.length ? `all ${online.length} matching online runner(s) busy` : `all ${match.length} matching runner(s) offline`
}

export function findings(s: Snapshot, rows: SlotRow[]): Finding[] {
  const out: Finding[] = rows.filter(r => r.stuck).map(r => ({ sev: "bad", where: r.slot, what: "runner stuck", age: r.age, cause: r.stuck! }))
  for (const repo of Object.keys(s.queued)) {
    const short = repo.split("/")[1] ?? repo
    const unread: number[] = []
    for (const run of s.queued[repo]) {
      const jobs = s.jobs[run.id]
      const queued = jobs ? jobs.filter(j => j.status === "queued") : null
      for (const j of queued ?? []) {
        const age = secs(j.created_at, s.now)
        if (!j.labels.some(l => l.toLowerCase() === "self-hosted") || age === null || age < HELD_AFTER_S) continue
        out.push({ sev: "bad", where: `${short} ${j.name} · ${run.display_title ?? run.name ?? run.id}`, what: "job queued", age, cause: heldCause(j.labels, s.runners[repo]) })
      }
      const age = secs(run.created_at, s.now)
      if (!jobs && age !== null && age >= HELD_AFTER_S) unread.push(age)
    }
    if (unread.length) out.push({ sev: "warn", where: short, what: `${unread.length} runs queued`, age: Math.max(...unread), cause: `jobs of these runs not read yet (${JOB_RUNS_PER_REPO} reads per repo and kind)` })
  }
  for (const r of rows) if (r.jobAge !== null && r.jobAge > LONG_JOB_S) out.push({ sev: "warn", where: r.slot, what: "job running long", age: r.jobAge, cause: r.job })
  if (s.errors.length) out.push({ sev: "warn", where: "GitHub", what: `${s.errors.length} read(s) failed`, age: null, cause: s.errors[0] })
  return out.sort((a, b) => (a.sev === b.sev ? 0 : a.sev === "bad" ? -1 : 1) || (b.age ?? 0) - (a.age ?? 0))
}

export type RunRow = { repo: string; status: "queued" | "running"; title: string; branch: string; age: number | null; held: boolean }

export function runRows(s: Snapshot): RunRow[] {
  const mk = (status: RunRow["status"], pick: (r: Run) => string | undefined) => (repo: string, r: Run): RunRow => {
    const age = secs(pick(r), s.now)
    return { repo, status, title: r.display_title ?? r.name ?? String(r.id), branch: r.head_branch ?? "", age, held: status === "queued" && age !== null && age >= HELD_AFTER_S }
  }
  const rows = [
    ...Object.entries(s.queued).flatMap(([repo, rs]) => rs.map(r => mk("queued", r => r.created_at)(repo, r))),
    ...Object.entries(s.progress).flatMap(([repo, rs]) => rs.map(r => mk("running", r => r.run_started_at ?? r.created_at)(repo, r))),
  ]
  return rows.sort((a, b) => (a.status === b.status ? 0 : a.status === "queued" ? -1 : 1) || (b.age ?? 0) - (a.age ?? 0))
}

// ---- GitHub read scheduler ------------------------------------------------
export type Cache = Map<string, { at: number; data: unknown }>
export type Call = { key: string; path: string }

/** The calls that could be made now, oldest read first (never-read first). */
export function dueCalls(repos: string[], cache: Cache, now: number): Call[] {
  const calls: Call[] = []
  for (const repo of repos) {
    calls.push({ key: `runners:${repo}`, path: `repos/${repo}/actions/runners?per_page=100` })
    calls.push({ key: `queued:${repo}`, path: `repos/${repo}/actions/runs?status=queued&per_page=100` })
    calls.push({ key: `progress:${repo}`, path: `repos/${repo}/actions/runs?status=in_progress&per_page=100` })
    for (const kind of ["progress", "queued"]) {
      const runs = ((cache.get(`${kind}:${repo}`)?.data as { workflow_runs?: Run[] } | undefined)?.workflow_runs ?? [])
        .slice().sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at)).slice(0, JOB_RUNS_PER_REPO)
      for (const r of runs) calls.push({ key: `jobs:${r.id}`, path: `repos/${repo}/actions/runs/${r.id}/jobs?filter=latest&per_page=100` })
    }
  }
  return calls.filter(c => now - (cache.get(c.key)?.at ?? 0) >= MIN_AGE_MS).sort((a, b) => (cache.get(a.key)?.at ?? 0) - (cache.get(b.key)?.at ?? 0))
}

/** The next call within the budget: at most CALLS_PER_MIN in any 60 s, at least CALL_GAP_MS apart. `sent` holds call times. */
export function nextCall(repos: string[], cache: Cache, sent: number[], now: number): Call | null {
  const recent = sent.filter(t => now - t < 60_000)
  if (recent.length >= CALLS_PER_MIN || (recent.length && now - Math.max(...recent) < CALL_GAP_MS)) return null
  return dueCalls(repos, cache, now)[0] ?? null
}

/** Builds the snapshot from the read cache. A repo whose runner read failed or has not happened has no `runners` key. */
export function fromCache(cache: Cache, slots: Slot[], local: Pick<Snapshot, "units" | "containers">, errors: string[], now: number, firstSeen?: Record<string, number>): Snapshot {
  const repos = [...new Set(slots.map(s => s.repo))]
  const snap: Snapshot = { now, slots, ...local, runners: {}, queued: {}, progress: {}, jobs: {}, errors, firstSeen }
  for (const repo of repos) {
    const runners = (cache.get(`runners:${repo}`)?.data as { runners?: Runner[] } | undefined)?.runners
    if (runners) snap.runners[repo] = runners
    for (const kind of ["queued", "progress"] as const) {
      const runs = (cache.get(`${kind}:${repo}`)?.data as { workflow_runs?: Run[] } | undefined)?.workflow_runs
      if (runs) snap[kind][repo] = runs
      for (const r of runs ?? []) {
        const jobs = (cache.get(`jobs:${r.id}`)?.data as { jobs?: Job[] } | undefined)?.jobs
        if (jobs) snap.jobs[r.id] = jobs
      }
    }
  }
  return snap
}

// ---- view and I/O ---------------------------------------------------------
const POOL = process.env.CI_POOL_CONFIG ?? `${process.env.HOME}/.config/ci-pool/pool.json`
const LOCAL_MS = 5_000
const FORGEJO_MS = 60_000
const MAXW = 170

type Seg = { t: string; c?: string; b?: boolean; k?: string }
type Line = Seg[]
const seg = (t: string, c: string = theme.text, b = false): Seg => ({ t, c, b })
const plain = (lines: Line[]) => lines.map(l => l.map(x => x.t).join("").trimEnd()).join("\n")
const styled = (lines: Line[]) => {
  const out: TextChunk[] = []
  lines.forEach((l, i) => {
    if (i) out.push(fg(theme.text)("\n"))
    for (const x of l) {
      let chunk = fg(x.c ?? theme.text)(x.t)
      if (x.k) chunk = bg(x.k)(chunk)
      out.push(x.b ? bold(chunk) : chunk)
    }
  })
  return new StyledText(out)
}

const dur = (s: number | null) => (s === null ? "-" : s < 90 ? `${Math.round(s)}s` : s < 5400 ? `${Math.round(s / 60)}m` : s < 172800 ? `${(s / 3600).toFixed(1)}h` : `${Math.round(s / 86400)}d`)
const fit = (t: string, w: number) => (t.length > w ? t.slice(0, w - 1) + "…" : t.padEnd(w))
const head = (cols: [string, number][]): Line[] => [[seg(cols.map(([n, w]) => n.padEnd(w)).join(""), theme.muted, true)]]
const levelColor = { ok: theme.ok, idle: theme.muted, bad: theme.error } as const

// ---- panels ---------------------------------------------------------------
export function attentionPanel(s: Snapshot, w: number): Line[] {
  const found = findings(s, slotRows(s))
  if (!found.length) return [[seg("● ", theme.ok), seg(`nothing held up: no stuck slot, no job queued longer than ${HELD_AFTER_S / 60} min`)]]
  return found.map(f => [
    seg(f.sev === "bad" ? "▲ " : "△ ", f.sev === "bad" ? theme.error : theme.warn, true),
    seg(fit(f.where, 56), theme.accent), seg(fit(f.what, 16)), seg(fit(dur(f.age), 7), theme.warn, true), seg(fit(f.cause, Math.max(20, w - 87)), theme.muted),
  ])
}

export function slotPanel(s: Snapshot, w: number): Line[] {
  const cols: [string, number][] = [["SLOT", 30], ["STATE", 10], ["CONTAINER", 22], ["AGE", 7], ["RUNNER", 10], ["JOB", 0]]
  const lines = head(cols)
  for (const r of slotRows(s)) {
    lines.push([
      seg(fit(r.slot, 30), theme.accent), seg(fit(r.state, 10), levelColor[r.level], r.level !== "idle"), seg(fit(r.container, 22)),
      seg(fit(dur(r.age), 7)), seg(fit(r.runner, 10), r.runner === "offline" ? theme.error : theme.text),
      seg(fit(r.stuck ?? r.job, Math.max(10, w - 79)), r.stuck ? theme.error : theme.muted),
    ])
  }
  return lines
}

export function runPanel(s: Snapshot, w: number, max: number): Line[] {
  const rows = runRows(s)
  if (!rows.length) return [[seg("no queued or running workflow runs", theme.muted)]]
  const lines = head([["STATUS", 9], ["REPO", 24], ["AGE", 7], ["BRANCH", 26], ["RUN", 0]])
  for (const r of rows.slice(0, max)) {
    lines.push([
      seg(fit(r.status, 9), r.held ? theme.error : r.status === "queued" ? theme.warn : theme.ok, true), seg(fit(r.repo, 24), theme.accent),
      seg(fit(dur(r.age), 7), r.held ? theme.error : theme.text, r.held), seg(fit(r.branch, 26), theme.muted), seg(fit(r.title, Math.max(10, w - 66))),
    ])
  }
  if (rows.length > max) lines.push([seg(`… ${rows.length - max} more`, theme.muted)])
  return lines
}

type Forgejo = { note: string; runs: { repo: string; status: string; title: string; branch: string; since: number }[] }
export function forgejoPanel(f: Forgejo, now: number, w: number): Line[] {
  if (f.note) return [[seg(f.note, theme.muted)]]
  if (!f.runs.length) return [[seg("no waiting or running Forgejo runs", theme.muted)]]
  return [...head([["STATUS", 9], ["REPO", 26], ["AGE", 7], ["BRANCH", 24], ["RUN", 0]]), ...f.runs.map((r): Line => [
    seg(fit(r.status, 9), r.status === "waiting" ? theme.warn : theme.ok, true), seg(fit(r.repo, 26), theme.accent),
    seg(fit(dur((now - r.since) / 1000), 7)), seg(fit(r.branch, 24), theme.muted), seg(fit(r.title, Math.max(10, w - 66))),
  ])]
}

function header(s: Snapshot, sent: number[], pending: number): Line[] {
  const rows = slotRows(s)
  const count = (l: string) => rows.filter(r => r.level === l).length
  const stuck = count("bad")
  const held = findings(s, rows).filter(f => f.what !== "runner stuck" && f.sev === "bad").length
  const used = sent.filter(t => s.now - t < 60_000).length
  return [[
    { ...seg(" CI POOL ", theme.bg, true), k: theme.accent }, seg(`  ${rows.length} slots  `, theme.muted), seg(`${count("ok")} busy  `, theme.ok, true), seg(`${count("idle")} idle  `),
    seg(`${stuck} stuck  `, stuck ? theme.error : theme.muted, stuck > 0), seg(`${held} held  `, held ? theme.error : theme.muted, held > 0),
    seg(`GitHub ${used}/${CALLS_PER_MIN} calls/min${pending ? `, ${pending} reads pending` : ""}  `, theme.muted), seg("q", theme.text, true), seg(" quit", theme.muted),
  ]]
}

// ---- data -----------------------------------------------------------------
function loadSlots() {
  const pool = JSON.parse(readFileSync(POOL, "utf8"))
  return poolSlots(pool)
}

async function sh(argv: string[], ms = 20_000) {
  const p = Bun.spawn(["timeout", "--kill-after=5", String(ms / 1000), ...argv], { stdout: "pipe", stderr: "pipe", stdin: "ignore" })
  const [out, err, code] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text(), p.exited])
  return { out, err, code }
}

// Same rule as ci-pool.py: the docker group is opt-in, otherwise sudo.
function docker() {
  try {
    accessSync("/var/run/docker.sock", constants.W_OK)
    return ["docker"]
  } catch {
    return ["sudo", "-n", "docker"]
  }
}

async function readLocal(): Promise<Pick<Snapshot, "units" | "containers">> {
  const [shown, ps] = await Promise.all([
    sh(["systemctl", "--user", "show", "ci-runner@*.service", "-p", "Id", "-p", "ActiveState", "-p", "ActiveEnterTimestampMonotonic"]),
    sh([...docker(), "ps", "--all", "--filter", "name=^/ci-runner-", "--format", "{{.Names}}\t{{.State}}\t{{.Status}}"]),
  ])
  const boot = Number(readFileSync("/proc/uptime", "utf8").split(" ")[0])
  return { units: parseUnits(shown.out, boot), containers: ps.code === 0 ? parseContainers(ps.out) : null }
}

async function readForgejo(): Promise<Forgejo> {
  const repos = (process.env.CI_POOL_TUI_FORGEJO_REPOS ?? "").split(",").map(x => x.trim()).filter(Boolean)
  if (!Bun.which("forgejo-axi")) return { note: "forgejo-axi is not installed on this host", runs: [] }
  if (!repos.length) return { note: "Forgejo repos not set: export CI_POOL_TUI_FORGEJO_REPOS=owner/repo[,owner/repo] (and FORGEJO_BASE_URL or hosts.json for forgejo-axi)", runs: [] }
  const runs: Forgejo["runs"] = []
  for (const repo of repos) {
    for (const status of ["waiting", "running"]) {
      const r = await sh(["forgejo-axi", "run", "list", "--repo", repo, "--status", status, "--json", "--fields", "id,title,status,branch,started_at"])
      let j: FgList | null = null
      try { j = JSON.parse(r.out) as FgList } catch { /* not JSON: reported below */ }
      if (r.code !== 0 || !j || j.error) return { note: `forgejo-axi run list ${repo}: ${j?.error ?? (r.err || r.out).trim().split("\n")[0]}`, runs: [] }
      for (const x of j.runs ?? []) {
        const id = `${repo}#${x.id}`
        if (!forgejoFirstSeen.has(id)) forgejoFirstSeen.set(id, Date.now())
        runs.push({ repo, status, title: x.title ?? String(x.id), branch: x.branch ?? "", since: x.started_at ? Date.parse(x.started_at) : forgejoFirstSeen.get(id)! })
      }
    }
  }
  return { note: "", runs }
}

type FgList = { error?: string; runs?: { id: number; title?: string; branch?: string; started_at?: string | null }[] }
const forgejoFirstSeen = new Map<string, number>() // a waiting Forgejo run has no start time: age counts from our first sighting

const cache: Cache = new Map()
const sent: number[] = []
const errors = new Map<string, string>()

let pausedUntil = 0 // epoch ms: GitHub said the hourly limit is used up
async function gh(path: string, key: string) {
  sent.push(Date.now())
  const r = await sh(["gh", "api", path])
  if (r.code === 0) {
    cache.set(key, { at: Date.now(), data: JSON.parse(r.out) })
    errors.delete(key)
    return
  }
  cache.set(key, { at: Date.now(), data: cache.get(key)?.data })
  const message = r.err.trim().split("\n")[0]
  if (/rate limit/i.test(message)) {
    // The rate_limit endpoint does not count against the limit.
    const reset = Number((await sh(["gh", "api", "rate_limit", "--jq", ".resources.core.reset"])).out) * 1000 || Date.now() + 300_000
    pausedUntil = reset
    errors.set("limit", `GitHub rate limit used up; reads paused until ${new Date(reset).toTimeString().slice(0, 5)}, tables show the last reads`)
  } else errors.set(key, `${key}: ${message}`)
}

const firstSeen: Record<string, number> = {}
function snapshot(slots: Slot[], local: Pick<Snapshot, "units" | "containers">) {
  const now = Date.now()
  for (const r of slotRows(fromCache(cache, slots, local, [], now))) {
    if (r.problem) firstSeen[r.slot] ??= now
    else delete firstSeen[r.slot]
  }
  return fromCache(cache, slots, local, [...errors.values()], now, firstSeen)
}

// ---- main -----------------------------------------------------------------
const flag = (n: string) => process.argv.indexOf(n)

function render(s: Snapshot, f: Forgejo, w: number, h: number) {
  const slotsH = s.slots.length + 2
  return {
    attention: attentionPanel(s, w), runs: runPanel(s, w, Math.max(6, h - slotsH - 24)), forgejo: forgejoPanel(f, s.now, w), slots: slotPanel(s, w),
  }
}

async function main() {
  if (flag("--once") >= 0) {
    const fx = flag("--fixture")
    let s: Snapshot
    if (fx > 0) s = JSON.parse(readFileSync(process.argv[fx + 1], "utf8"))
    else {
      const slots = loadSlots()
      const repos = [...new Set(slots.map(x => x.repo))]
      let local = await readLocal()
      // One read of each endpoint, at the budgeted pace: a large pool takes a few minutes.
      for (;;) {
        const todo = dueCalls(repos, cache, Infinity).filter(c => !cache.has(c.key))
        if (!todo.length) break
        if (Date.now() < pausedUntil) break
        const c = nextCall(repos, cache, sent, Date.now())
        if (c && !cache.has(c.key)) await gh(c.path, c.key)
        else await Bun.sleep(1000)
      }
      s = snapshot(slots, local)
      const settle = Math.max(0, ...Object.values(firstSeen).map(at => at + SETTLE_S * 1000 - Date.now()))
      if (settle > 0) {
        await Bun.sleep(settle)
        local = await readLocal()
        s = snapshot(slots, local)
      }
    }
    const f: Forgejo = fx > 0 ? { note: "", runs: [] } : await readForgejo()
    const r = render(s, f, 150, 60)
    console.log([plain(header(s, sent, 0)), "", "ATTENTION", plain(r.attention), "", "RUNS", plain(r.runs), "", "FORGEJO", plain(r.forgejo), "", "SLOTS", plain(r.slots)].join("\n"))
    process.exit(0)
  }

  const renderer = await createCliRenderer({ exitOnCtrlC: true })
  const column = new BoxRenderable(renderer, { flexDirection: "column", width: "100%" })
  const top = new TextRenderable(renderer, { content: "", flexShrink: 0 })
  column.add(top)
  const mkPanel = (title: string) => {
    const box = new BoxRenderable(renderer, { border: true, borderStyle: "rounded", borderColor: theme.border, titleColor: theme.text, title, titleAlignment: "left", paddingLeft: 1, paddingRight: 1, flexShrink: 0 })
    const text = new TextRenderable(renderer, { content: "" })
    box.add(text)
    column.add(box)
    return text
  }
  const pAttn = mkPanel(" Held up or stuck ")
  const pRuns = mkPanel(" Workflow runs queued or running · GitHub ")
  const pForgejo = mkPanel(" Forgejo runs ")
  const pSlots = mkPanel(" Runner slots · ci-runner@ ")
  renderer.root.add(column)

  let slots = loadSlots()
  const repos = () => [...new Set(slots.map(x => x.repo))]
  let local: Pick<Snapshot, "units" | "containers"> = { units: {}, containers: null }
  let forgejo: Forgejo | null = null

  function draw() {
    const W = Math.min(MAXW, renderer.width)
    column.width = W
    const s = snapshot(slots, local)
    const r = render(s, forgejo ?? { note: "reading…", runs: [] }, W - 4, renderer.height)
    const pending = dueCalls(repos(), cache, Infinity).filter(c => !cache.has(c.key)).length
    top.content = styled(header(s, sent, pending))
    pAttn.content = styled(r.attention)
    pRuns.content = styled(r.runs)
    pForgejo.content = styled(r.forgejo)
    pSlots.content = styled(r.slots)
    renderer.requestRender()
  }

  let busy = false
  const tick = async () => {
    if (busy) return
    busy = true
    try {
      const c = Date.now() < pausedUntil ? null : nextCall(repos(), cache, sent, Date.now())
      if (c) await gh(c.path, c.key)
    } finally { busy = false; draw() }
  }
  const refreshLocal = async () => { local = await readLocal(); draw() }
  const refreshForgejo = async () => { forgejo = await readForgejo(); draw() }

  draw()
  void refreshLocal()
  void refreshForgejo()
  const timers = [setInterval(refreshLocal, LOCAL_MS), setInterval(refreshForgejo, FORGEJO_MS), setInterval(tick, 1000), setInterval(draw, 1000)]
  renderer.on("resize", draw)
  renderer.keyInput.on("keypress", (k: { name: string }) => {
    if (k.name === "q") {
      timers.forEach(clearInterval)
      renderer.destroy()
      process.exit(0)
    }
    if (k.name === "r") {
      void refreshLocal()
      void refreshForgejo()
    }
  })
}

if (import.meta.main) await main()
