// Pure model for the tasks view: parse tasks-axi + status logs, build agents, group, filter, flatten to visible rows.
export type Task = { id: string; state: string; kind: string; repo: string; title: string; held: boolean; holdReason: string }
export type Event = { state: string; at: number | null; key: string; text: string }
export type Progress = { last: Event | null; decision: Event | null; mtime: number }
export type HomeData = { mate: string; tasks: Task[]; progress: Map<string, Progress> }
export type Agent = {
  mate: string; repo: string; id: string; title: string
  last: Event | null; lastAt: number | null; quiet: number // seconds since last progress; Infinity when never
  decision: Event | null; next: Task[]; moreNext: number; stalled: boolean
}
export type Counts = { agents: number; stalled: number; decisions: number; queued: number; mates: number }
export type Row =
  | { kind: "stalled"; key: string; n: number; shown: number }
  | { kind: "mate" | "repo"; key: string; depth: number; name: string; n: number; stalled: number; decisions: number; open: boolean }
  | { kind: "agent"; key: string; depth: number; agent: Agent; open: boolean }
  | { kind: "detail"; key: string; depth: number; label: string; text: string; tone: "text" | "muted" | "warn" | "ok" }
export type View = { expanded: Set<string>; filter: string; stalledOnly: boolean; all?: boolean }

export const DEFAULT_STALL_SEC = 30 * 60
const NEXT_SHOWN = 3
const STALLED_SHOWN = 10 // the pinned list stays short at 1000s of agents; Enter on its head shows all
const QUIET_STATES = new Set(["paused", "done", "failed"]) // a declared wait or a finished task is not a stall

// Split one tasks-axi row; fields may be double-quoted and contain commas.
function splitRow(line: string): string[] {
  const out: string[] = []
  let cur = "", q = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (q) {
      if (c === "\\" && i + 1 < line.length) cur += line[++i]
      else if (c === '"') { if (line[i + 1] === '"') { cur += '"'; i++ } else q = false }
      else cur += c
    } else if (c === '"') q = true
    else if (c === ",") { out.push(cur); cur = "" }
    else cur += c
  }
  out.push(cur)
  return out
}

const decodeHold = (s: string) => {
  const m = s.match(/^fm-hold-v1:(.+)$/)
  if (!m) return s === "-" ? "" : s
  try { return Buffer.from(m[1], "base64").toString("utf8") } catch { return "" }
}

// Reads `tasks[N]{a,b,c}:` followed by indented rows.
export function parseTasks(text: string): Task[] {
  const lines = text.split("\n")
  const h = lines.findIndex(l => /^tasks\[\d*\]\{.*\}:\s*$/.test(l))
  if (h < 0) return []
  const cols = lines[h].match(/\{(.*)\}/)![1].split(",")
  const out: Task[] = []
  for (const l of lines.slice(h + 1)) {
    if (!/^ {2}\S/.test(l)) break
    const f = splitRow(l.trim())
    const get = (c: string) => f[cols.indexOf(c)] ?? ""
    const holdReason = decodeHold(get("hold_reason"))
    out.push({ id: get("id"), state: get("state"), kind: get("kind"), repo: get("repo") || "-", title: get("title"), held: get("held") === "yes", holdReason })
  }
  return out
}

// `state [key=K] [at=epoch]: text`; bracket order varies. A line without a state prefix is ignored.
export function parseStatus(text: string, mtime: number): Progress {
  let last: Event | null = null
  const open = new Map<string, Event>()
  for (const raw of text.split("\n")) {
    const m = raw.match(/^([a-z-]+)((?:\s+\[[a-z]+=[^\]]*\])*)\s*:\s*(.*)$/)
    if (!m) continue
    const attrs = Object.fromEntries([...m[2].matchAll(/\[([a-z]+)=([^\]]*)\]/g)].map(x => [x[1], x[2]]))
    const ev: Event = { state: m[1], at: /^\d+$/.test(attrs.at ?? "") ? Number(attrs.at) : null, key: attrs.key ?? "", text: m[3] }
    last = ev
    if (ev.state === "needs-decision" || ev.state === "blocked") { open.delete(ev.key); open.set(ev.key, ev) }
    else if (ev.state === "resolved") open.delete(ev.key)
    else if (ev.key === "") open.delete("") // a later plain line closes only a keyless decision
  }
  const decision = [...open.values()].pop() ?? null
  return { last, decision, mtime }
}

export function buildAgents(homes: HomeData[], now: number, stallSec = DEFAULT_STALL_SEC): { agents: Agent[]; queued: number } {
  const agents: Agent[] = []
  let queued = 0
  for (const h of homes) {
    const nextByRepo = new Map<string, Task[]>()
    for (const t of h.tasks) {
      if (t.state !== "queued") continue
      queued++
      if (t.held) continue
      let l = nextByRepo.get(t.repo)
      if (!l) nextByRepo.set(t.repo, (l = []))
      l.push(t)
    }
    for (const t of h.tasks) {
      if (t.state !== "in_flight") continue
      const p = h.progress.get(t.id)
      const lastAt = p ? (p.last?.at ?? p.mtime) : null
      const quiet = lastAt === null ? Infinity : Math.max(0, now - lastAt)
      const nexts = nextByRepo.get(t.repo) ?? []
      const stalled = quiet > stallSec && !QUIET_STATES.has(p?.last?.state ?? "")
      agents.push({ mate: h.mate, repo: t.repo, id: t.id, title: t.title, last: p?.last ?? null, lastAt, quiet, decision: p?.decision ?? null, next: nexts.slice(0, NEXT_SHOWN), moreNext: Math.max(0, nexts.length - NEXT_SHOWN), stalled })
    }
  }
  return { agents, queued }
}

export const agentKey = (a: Agent) => `${a.mate}/${a.id}`

const matches = (a: Agent, q: string) => {
  if (!q) return true
  const hay = `${a.mate} ${a.repo} ${a.id} ${a.title} ${a.decision?.text ?? ""} ${a.last?.text ?? ""}`.toLowerCase()
  return q.toLowerCase().split(/\s+/).every(w => hay.includes(w))
}

export function counts(agents: Agent[], queued: number): Counts {
  let stalled = 0, decisions = 0
  const mates = new Set<string>()
  for (const a of agents) { mates.add(a.mate); if (a.stalled) stalled++; if (a.decision) decisions++ }
  return { agents: agents.length, stalled, decisions, queued, mates: mates.size }
}

const byQuietDesc = (a: Agent, b: Agent) => (a.quiet === b.quiet ? a.id.localeCompare(b.id) : b.quiet - a.quiet)

const stat = (l: Agent[]) => ({ n: l.length, stalled: l.filter(a => a.stalled).length, decisions: l.filter(a => a.decision).length })
const byStalledThenName = <T>(items: [string, T, Agent[]][]) => items.sort((x, y) => stat(y[2]).stalled - stat(x[2]).stalled || x[0].localeCompare(y[0]))

function groupByMate(pool: Agent[]): Map<string, Map<string, Agent[]>> {
  const mates = new Map<string, Map<string, Agent[]>>()
  for (const a of pool) {
    const repos = mates.get(a.mate) ?? new Map<string, Agent[]>()
    mates.set(a.mate, repos)
    const list = repos.get(a.repo) ?? []
    repos.set(a.repo, list)
    list.push(a)
  }
  return mates
}

// Stalled agents pinned first, then mate > repo > agent groups. Groups are collapsed unless expanded or a filter is set.
export function flatten(agents: Agent[], v: View): Row[] {
  const pool = agents.filter(a => matches(a, v.filter) && (!v.stalledOnly || a.stalled))
  const rows: Row[] = []
  const stalled = pool.filter(a => a.stalled).sort(byQuietDesc)
  const isOpen = (k: string) => v.filter.trim() !== "" || v.all || v.expanded.has(k)
  const pushAgent = (a: Agent, depth: number, key: string) => {
    const open = !!v.all || v.expanded.has(key)
    rows.push({ kind: "agent", key, depth, agent: a, open })
    if (open) agentDetails(a, depth + 1, key, rows)
  }
  if (stalled.length) {
    const shown = v.expanded.has("stalled-all") ? stalled.length : Math.min(stalled.length, STALLED_SHOWN)
    rows.push({ kind: "stalled", key: "stalled", n: stalled.length, shown })
    for (const a of stalled.slice(0, shown)) pushAgent(a, 1, `s:${agentKey(a)}`)
  }
  const mates = [...groupByMate(pool)].map(([name, repos]) => [name, repos, [...repos.values()].flat()] as [string, Map<string, Agent[]>, Agent[]])
  for (const [mate, repos, all] of byStalledThenName(mates)) {
    const mk = `m:${mate}`, mopen = isOpen(mk)
    rows.push({ kind: "mate", key: mk, depth: 0, name: mate, ...stat(all), open: mopen })
    if (!mopen) continue
    for (const [repo, list] of byStalledThenName([...repos].map(([n, l]) => [n, l, l] as [string, Agent[], Agent[]]))) {
      const rk = `r:${mate}/${repo}`, ropen = isOpen(rk)
      rows.push({ kind: "repo", key: rk, depth: 1, name: repo, ...stat(list), open: ropen })
      if (ropen) for (const a of list.sort(byQuietDesc)) pushAgent(a, 2, agentKey(a))
    }
  }
  return rows
}

function agentDetails(a: Agent, depth: number, key: string, rows: Row[]) {
  const d = (label: string, text: string, tone: "text" | "muted" | "warn" | "ok", n: number) => rows.push({ kind: "detail", key: `${key}#${label}${n}`, depth, label, text, tone })
  d("now", a.title, "text", 0)
  if (a.decision) d(a.decision.state === "blocked" ? "blocked" : "decision", a.decision.text || a.decision.key, "warn", 0)
  a.next.forEach((t, i) => d("next", `${t.title}  (${t.id})`, "muted", i))
  if (a.moreNext) d("next", `+${a.moreNext} more queued`, "muted", 9)
  if (!a.next.length && !a.moreNext) d("next", "nothing queued", "muted", 0)
  d("last", a.last ? `${a.last.state}: ${a.last.text}` : "no status events", a.stalled ? "warn" : "muted", 0)
}

export function age(sec: number): string {
  if (!Number.isFinite(sec)) return "never"
  if (sec < 90) return `${Math.floor(sec)}s`
  if (sec < 5400) return `${Math.round(sec / 60)}m`
  if (sec < 172800) return `${Math.floor(sec / 3600)}h${String(Math.floor((sec % 3600) / 60)).padStart(2, "0")}m`
  return `${Math.floor(sec / 86400)}d`
}
