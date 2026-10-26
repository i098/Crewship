import { afterAll, expect, test } from "bun:test"
import { mkdtempSync, rmSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { writeFixture } from "./fixture.ts"
import { age, buildAgents, counts, flatten, parseStatus, parseTasks, type View } from "./tasks-model.ts"
import { loadHomes, mateName } from "./tasks-source.ts"
import { snapshot, viewport } from "./tasks-view.ts"

const dirs: string[] = []
afterAll(() => dirs.forEach(d => rmSync(d, { recursive: true, force: true })))
const NOW = 1_800_000_000
const fixture = async (agents: number, mates: number) => {
  const dir = mkdtempSync(join(tmpdir(), "cbtasks-"))
  dirs.push(dir)
  const homes = writeFixture(dir, { agents, mates, now: NOW })
  return buildAgents(await loadHomes(homes, join(dir, "tasks-axi")), NOW)
}
const view = (o: Partial<View> = {}): View => ({ expanded: new Set(), filter: "", stalledOnly: false, ...o })

test("parses tasks-axi rows with quoted commas and base64 hold reasons", () => {
  const text = `count: 2\ntasks[2]{id,state,kind,repo,title,held,hold_reason}:\n  a-1,in_flight,ship,r,"Fix, then ship",no,-\n  a-2,queued,task,r,Wait,yes,fm-hold-v1:${Buffer.from("need owner").toString("base64")}\nhelp[1]:\n  - x\n`
  const t = parseTasks(text)
  expect(t.map(x => x.title)).toEqual(["Fix, then ship", "Wait"])
  expect(t[1]).toMatchObject({ held: true, holdReason: "need owner" })
})

test("an open decision is the latest keyed needs-decision/blocked without a matching resolved", () => {
  const log = [
    "working [at=10]: go",
    "needs-decision [at=20] [key=a]: pick A",
    "blocked [key=b] [at=30]: waiting on B",
    "resolved [at=40] [key=b]: B cleared",
    "done [at=50]: later done does not close keyed a",
  ].join("\n")
  expect(parseStatus(log, 0).decision).toMatchObject({ key: "a", text: "pick A" })
  expect(parseStatus(log + "\nresolved [at=60] [key=a]: ok", 0).decision).toBeNull()
  expect(parseStatus("needs-decision [at=1]: keyless\nworking [at=2]: back", 0).decision).toBeNull()
})

test("stall: quiet past threshold while in flight, except declared waits; no log means stalled", () => {
  const task = (id: string) => ({ id, state: "in_flight", kind: "ship", repo: "r", title: id, held: false, holdReason: "" })
  const progress = new Map([
    ["old", parseStatus(`working [at=${NOW - 3600}]: x`, 0)],
    ["fresh", parseStatus(`working [at=${NOW - 60}]: x`, 0)],
    ["wait", parseStatus(`paused [at=${NOW - 7200}]: ci`, 0)],
  ])
  const { agents } = buildAgents([{ mate: "m", tasks: ["old", "fresh", "wait", "none"].map(task), progress }], NOW)
  expect(Object.fromEntries(agents.map(a => [a.id, a.stalled]))).toEqual({ old: true, fresh: false, wait: false, none: true })
  expect(agents.find(a => a.id === "none")!.quiet).toBe(Infinity)
})

test("groups by mate and repo, collapsed by default, stalled pinned first and longest-quiet first", async () => {
  const { agents, queued } = await fixture(60, 3)
  const rows = flatten(agents, view({ expanded: new Set(["stalled-all"]) }))
  const c = counts(agents, queued)
  expect(rows[0]).toMatchObject({ kind: "stalled", n: c.stalled })
  const stalled = rows.slice(1, 1 + c.stalled)
  expect(stalled.every(r => r.kind === "agent" && r.agent.stalled)).toBe(true)
  const quiet = stalled.map(r => (r.kind === "agent" ? r.agent.quiet : 0))
  expect(quiet).toEqual([...quiet].sort((a, b) => b - a))
  const rest = rows.slice(1 + c.stalled)
  expect(rest.every(r => r.kind === "mate")).toBe(true) // collapsed: mates only
  expect(rest).toHaveLength(3)
  expect(c).toMatchObject({ agents: 60, mates: 3 })
  expect(c.stalled).toBeGreaterThan(0)
  expect(c.decisions).toBeGreaterThan(0)
})

test("expanding a mate shows repos, then agents, then details with next items and the decision", async () => {
  const { agents } = await fixture(60, 1)
  const mate = flatten(agents, view()).find(r => r.kind === "mate")!
  const l1 = flatten(agents, view({ expanded: new Set([mate.key]) }))
  const repo = l1.find(r => r.kind === "repo")!
  expect(l1.filter(r => r.kind === "repo").length).toBeGreaterThan(1)
  const l2 = flatten(agents, view({ expanded: new Set([mate.key, repo.key]) }))
  const ag = l2.find(r => r.kind === "agent" && !r.key.startsWith("s:"))!
  const l3 = flatten(agents, view({ expanded: new Set([mate.key, repo.key, ag.key]) }))
  const labels = l3.filter(r => r.kind === "detail").map(r => (r.kind === "detail" ? r.label : ""))
  expect(labels).toContain("now")
  expect(labels).toContain("last")
  expect(labels.some(l => l === "next")).toBe(true)
  const withDecision = agents.find(a => a.decision)!
  const d = flatten([withDecision], view({ expanded: new Set([`m:${withDecision.mate}`, `r:${withDecision.mate}/${withDecision.repo}`, agentKeyOf(withDecision)]) }))
  expect(d.some(r => r.kind === "detail" && r.label === "decision")).toBe(true)
})
const agentKeyOf = (a: { mate: string; id: string }) => `${a.mate}/${a.id}`

test("filter matches across id, title, repo and decision text, and opens matching groups", async () => {
  const { agents } = await fixture(60, 2)
  const rows = flatten(agents, view({ filter: "lantern" }))
  const agentRows = rows.filter(r => r.kind === "agent" && !r.key.startsWith("s:"))
  expect(agentRows.length).toBeGreaterThan(0)
  expect(agentRows.every(r => r.kind === "agent" && r.agent.repo === "lantern")).toBe(true)
  expect(flatten(agents, view({ filter: "zzz-no-match" }))).toEqual([])
  const two = flatten(agents, view({ filter: "lantern choose" })).filter(r => r.kind === "agent")
  expect(two.every(r => r.kind === "agent" && r.agent.decision !== null)).toBe(true)
  expect(flatten(agents, view({ stalledOnly: true })).filter(r => r.kind === "agent").every(r => r.kind === "agent" && r.agent.stalled)).toBe(true)
})

test("age formats", () => {
  expect([45, 600, 3600 * 2 + 300, 86400 * 3, Infinity].map(age)).toEqual(["45s", "10m", "2h05m", "3d", "never"])
  expect(mateName("/x/.treehouse/firstmate-ab12/6/firstmate")).toBe("firstmate-ab12/6")
})

test("5000 agents: flatten and a viewport render stay fast and the viewport formats only its rows", async () => {
  const { agents } = await fixture(5000, 20)
  const t0 = performance.now()
  const all = new Set(agents.flatMap(a => [`m:${a.mate}`, `r:${a.mate}/${a.repo}`, agentKeyOf(a)]))
  const rows = flatten(agents, view({ expanded: all }))
  const lines = viewport(rows, 100, 40, 120, 105)
  const ms = performance.now() - t0
  console.log(`5000 agents: ${rows.length} rows, flatten+viewport ${ms.toFixed(1)} ms`)
  expect(lines).toHaveLength(40)
  expect(ms).toBeLessThan(500)
  const collapsed = flatten(agents, view())
  expect(collapsed.length).toBeLessThan(40) // 20 mates + stalled head + 10 pinned
}, 30_000)

test("--once snapshot shows counts, the stalled section, and every row when expanded", async () => {
  const { agents, queued } = await fixture(30, 2)
  const text = snapshot(agents, queued, view(), { width: 100, stallMin: 30, expandAll: false })
  expect(text).toMatch(/30 agents/)
  expect(text).toContain("⚠ STALLED")
  const full = snapshot(agents, queued, view(), { width: 100, stallMin: 30, expandAll: true })
  expect(full).toContain("next")
  expect(full.split("\n").length).toBeGreaterThan(text.split("\n").length)
}, 30_000)

test("the stalled head shows the top 10 until opened, then all", async () => {
  const { agents } = await fixture(200, 2)
  const n = counts(agents, 0).stalled
  expect(n).toBeGreaterThan(10)
  const count = (v: View) => flatten(agents, v).filter(r => r.kind === "agent" && r.key.startsWith("s:")).length
  expect(count(view())).toBe(10)
  expect(flatten(agents, view())[0]).toMatchObject({ kind: "stalled", n, shown: 10 })
  expect(count(view({ expanded: new Set(["stalled-all"]) }))).toBe(n)
})
