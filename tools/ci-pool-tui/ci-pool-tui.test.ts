import { expect, test } from "bun:test"
import { dueCalls, findings, heldCause, nextCall, parseUnits, poolSlots, slotRows, type Cache, type Snapshot } from "./ci-pool-tui.ts"

const NOW = Date.parse("2026-11-01T12:00:00Z")
const ago = (s: number) => new Date(NOW - s * 1000).toISOString()
const runner = (n: number, status: string, busy: boolean, labels: string[]) => ({ name: `pool-o-r-${n}-1`, status, busy, labels: labels.map(name => ({ name })) })
const base = (): Snapshot => ({
  now: NOW, slots: poolSlots({ repos: [{ repo: "o/r", slots: 3, labels: [] }] }),
  units: { "o-r-1": { state: "active", age: 900 }, "o-r-2": { state: "active", age: 900 }, "o-r-3": { state: "active", age: 900 } },
  containers: { "ci-runner-o-r-1": { state: "running", status: "Up 15 minutes" }, "ci-runner-o-r-2": { state: "running", status: "Up 15 minutes" }, "ci-runner-o-r-3": { state: "running", status: "Up 15 minutes" } },
  runners: { "o/r": [runner(1, "online", true, ["self-hosted", "x"]), runner(2, "online", false, ["self-hosted", "x"]), runner(3, "online", false, ["self-hosted", "x"])] },
  queued: {}, progress: {}, jobs: {}, errors: [],
})

test("a healthy pool has no finding and names the job a busy slot runs", () => {
  const s = base()
  s.progress["o/r"] = [{ id: 7, display_title: "build it", status: "in_progress", created_at: ago(60) }]
  s.jobs[7] = [{ id: 1, run_id: 7, name: "test", status: "in_progress", created_at: ago(60), runner_name: "pool-o-r-1-1", labels: ["self-hosted"] }]
  const rows = slotRows(s)
  expect(rows.map(r => r.state)).toEqual(["busy", "idle", "idle"])
  expect(rows[0].job).toBe("build it / test")
  expect(findings(s, rows)).toEqual([])
})

test("a slot with no container, an offline runner or a dead container is stuck only after the grace period", () => {
  const s = base()
  delete s.containers!["ci-runner-o-r-1"]
  s.runners["o/r"][1].status = "offline"
  s.containers!["ci-runner-o-r-3"].state = "exited"
  expect(slotRows(s).map(r => r.stuck)).toEqual(["no container for 15 min", "runner offline on GitHub", "container exited"])
  for (const u of Object.values(s.units)) u.age = 60
  expect(slotRows(s).filter(r => r.stuck)).toEqual([])
})

test("a slot problem seen for under 2 minutes is ending, not stuck", () => {
  const s = base()
  s.containers!["ci-runner-o-r-1"].state = "dead"
  s.firstSeen = { "o-r-1": NOW - 30_000 }
  expect(slotRows(s)[0]).toMatchObject({ state: "ending", level: "idle", problem: "container dead" })
  expect(slotRows(s)[0].stuck).toBeUndefined()
  s.firstSeen["o-r-1"] = NOW - 130_000
  expect(slotRows(s)[0]).toMatchObject({ state: "STUCK", level: "bad", stuck: "container dead" })
})

test("a self-hosted job queued over 5 minutes is held with its cause; younger and GitHub-hosted jobs are not", () => {
  const s = base()
  s.queued["o/r"] = [{ id: 8, display_title: "t", status: "queued", created_at: ago(700) }]
  const job = (id: number, age: number, labels: string[]) => ({ id, run_id: 8, name: `j${id}`, status: "queued", created_at: ago(age), labels })
  s.jobs[8] = [job(1, 700, ["self-hosted", "x"]), job(2, 100, ["self-hosted", "x"]), job(3, 900, ["ubuntu-latest"]), job(4, 700, ["self-hosted", "nope"])]
  const f = findings(s, slotRows(s))
  expect(f.map(x => [x.where, Math.round(x.age!), x.cause])).toEqual([
    ["r j1 · t", 700, "2 idle matching runner(s) online; GitHub has not assigned the job"],
    ["r j4 · t", 700, "no runner has labels self-hosted,nope"],
  ])
})

test("old queued runs with unread jobs become one finding per repo; a job running over 6 hours is flagged, a long-idle slot is not", () => {
  const s = base()
  s.queued["o/r"] = [1, 2, 3].map(id => ({ id, display_title: "t", status: "queued", created_at: ago(400 * id) }))
  s.units["o-r-1"].age = 40 * 3600 // the slot waited long for this job: not a long job
  s.progress["o/r"] = [{ id: 7, display_title: "slow", status: "in_progress", created_at: ago(8 * 3600) }]
  s.jobs[7] = [{ id: 1, run_id: 7, name: "test", status: "in_progress", created_at: ago(8 * 3600), started_at: ago(7 * 3600), runner_name: "pool-o-r-1-1", labels: ["self-hosted"] }]
  expect(findings(s, slotRows(s)).map(x => [x.where, x.what])).toEqual([["o-r-1", "job running long"], ["r", "3 runs queued"]])
  s.jobs[7][0].started_at = ago(3600)
  expect(findings(s, slotRows(s)).map(x => x.what)).toEqual(["3 runs queued"])
})

test("held cause separates busy from offline matching runners", () => {
  const rs = [runner(1, "online", true, ["self-hosted"]), runner(2, "offline", false, ["self-hosted"])]
  expect(heldCause(["self-hosted"], rs)).toBe("all 1 matching online runner(s) busy")
  expect(heldCause(["self-hosted"], [rs[1]])).toBe("all 1 matching runner(s) offline")
})

test("systemd output becomes slot unit ages", () => {
  const u = parseUnits("Id=ci-runner@o-r-1.service\nActiveState=active\nActiveEnterTimestampMonotonic=100000000\n\nId=ci-runner@o-r-2.service\nActiveState=failed\nActiveEnterTimestampMonotonic=0\n", 400)
  expect(u).toEqual({ "o-r-1": { state: "active", age: 300 }, "o-r-2": { state: "failed", age: 400 } })
})

test("the GitHub budget allows 20 calls a minute, 3 s apart, oldest read first", () => {
  const repos = Array.from({ length: 30 }, (_, i) => `o/r${i}`)
  const cache: Cache = new Map()
  const sent: number[] = []
  let t = NOW
  for (let i = 0; i < 200; i++, t += 1000) {
    const c = nextCall(repos, cache, sent, t)
    if (c) { sent.push(t); cache.set(c.key, { at: t, data: { runners: [] } }) }
  }
  expect(sent.filter(x => x > NOW + 60_000 - 1 && x < NOW + 120_000).length).toBeLessThanOrEqual(20)
  expect(sent.length).toBeLessThanOrEqual(67)
  expect(sent.slice(1).every((x, i) => x - sent[i] >= 3000)).toBe(true)
  // every key was read once before any is read twice
  expect(new Set(cache.keys()).size).toBe(sent.length)
  expect(dueCalls(repos, cache, t).length).toBeGreaterThan(0)
})
