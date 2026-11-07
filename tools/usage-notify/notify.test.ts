import { expect, test } from "bun:test"
import { evaluate, processSnapshot, type State } from "./notify.ts"
import type { QuotaRow } from "./../usage-tui/quota.ts"

const H = 3_600_000
const row = (left: number, resetsAt: number | null = 10 * 24 * H): QuotaRow => ({ account: "claude a", window: "5h", usedPct: 100 - left, leftPct: left, resetsAt })
const run = (s: State, left: number, t: number, resetsAt?: number | null) => evaluate(s, [row(left, resetsAt)], t, "UTC")

test("one text per 10% step, none on the same step", () => {
  let r = run({}, 95, 0)
  expect(r.messages).toEqual([])
  r = run(r.state, 89, 1); expect(r.messages).toHaveLength(1)
  expect(r.messages[0]).toContain("at or below the 90% step")
  r = run(r.state, 86, 2); expect(r.messages).toEqual([])
  r = run(r.state, 79, 3); expect(r.messages).toHaveLength(1)
  r = run(r.state, 51, 4); expect(r.messages).toHaveLength(1) // jumped several steps: one text
})

test("window reset re-arms the steps", () => {
  let r = run({}, 40, 0, 1000)
  r = run(r.state, 25, 1, 1000); expect(r.messages).toHaveLength(1)
  r = run(r.state, 99, 2, 1000 + 5 * H); expect(r.messages).toEqual([])
  r = run(r.state, 85, 3, 1000 + 5 * H); expect(r.messages).toHaveLength(1)
})

test("acceleration texts once per window", () => {
  let r = run({}, 100, 0)
  for (let h = 1; h <= 3; h++) r = run(r.state, 100 - h, h * H) // 1%/h
  expect(r.messages).toEqual([])
  r = run(r.state, 90, 4 * H) // 7 pp in the last hour, average ~2.25
  expect(r.messages.filter(m => m.includes("burning fast"))).toHaveLength(1)
  r = run(r.state, 80, 5 * H)
  expect(r.messages.filter(m => m.includes("burning fast"))).toEqual([])
})

test("rows without numbers or other windows are ignored", () => {
  const rows: QuotaRow[] = [{ account: "x", window: "5h", usedPct: null, leftPct: null, resetsAt: null }, { ...row(50), window: "30d" }]
  expect(evaluate({}, rows, 0, "UTC").state).toEqual({})
})

test("a window missing for one run keeps its latch and step", () => {
  let r = run({}, 100, 0)
  for (let h = 1; h <= 3; h++) r = run(r.state, 100 - h, h * H)
  r = run(r.state, 90, 4 * H)
  expect(r.messages.filter(m => m.includes("burning fast"))).toHaveLength(1)
  const gap = evaluate(r.state, [{ ...row(0), usedPct: null, leftPct: null }], 5 * H, "UTC")
  expect(gap.state).toEqual(r.state)
  r = run(gap.state, 80, 6 * H)
  expect(r.messages.filter(m => m.includes("burning fast"))).toEqual([])
})

test("a changed snapshot is processed once, an unchanged one is skipped", () => {
  const input = { claude: [{ name: "a", five_hour: { utilization: 15, resets_at: "2030-01-01T00:00:00Z" } }] } as any
  const empty = { snap: "", windows: {} }
  const first = processSnapshot(empty, "1:10", input, 0, "UTC")!
  expect(first.saved.snap).toBe("1:10")
  expect(processSnapshot(first.saved, "1:10", input, H, "UTC")).toBeNull()
  expect(processSnapshot(first.saved, "2:10", input, H, "UTC")).not.toBeNull()
})
