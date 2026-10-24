import { expect, test } from "bun:test"
import { mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { buildRows, cells, clockAt, leftColor, leftOf, mercuryRows, parseOmp, parseZai, relReset, type QuotaInput } from "./quota.ts"

const NOW = Date.UTC(2026, 0, 10, 12, 0, 0)
const MIN = 60_000
const limit = (windowId: string, used: number, resetsAt?: number, tier?: string) => ({
  scope: { windowId, ...(tier ? { tier } : {}) },
  window: { id: windowId, ...(resetsAt ? { resetsAt } : {}) },
  amount: { used, limit: 100, usedFraction: used / 100 },
})
// Invented numbers and provider names only.
const FIXTURE: QuotaInput = {
  now: NOW,
  omp: {
    reports: [
      { provider: "anthropic", limits: [limit("5h", 80, NOW + 90 * MIN), limit("7d", 10, NOW + 3 * 1440 * MIN), limit("7d", 55, NOW + 3 * 1440 * MIN, "fable")] },
      { provider: "anthropic", limits: [limit("5h", 0), limit("7d", 100, NOW + 30 * MIN)] },
      { provider: "openai-codex", limits: [limit("7d", 30, NOW + 5 * 1440 * MIN)] },
    ],
  },
  zai: { data: { limits: [{ unit: 3, number: 5, usage: 1000, remaining: 250, nextResetTime: NOW + 60 * MIN }, { unit: 6, number: 1, usage: 8000, remaining: 8000, nextResetTime: NOW + 6 * 1440 * MIN }] } },
  mercury: { keyIds: [9, 4], tokens: { 4: 25_000_000, 9: 150_000_000 } },
}

test("leftOf computes percent left and clamps overuse", () => {
  expect(leftOf(25, 100)).toEqual({ usedPct: 25, leftPct: 75 })
  expect(leftOf(150, 100)).toEqual({ usedPct: 100, leftPct: 0 })
  expect(leftOf(1, 0)).toBeNull()
})

test("leftColor switches at 50 and 20", () => {
  expect([51, 50, 20, 19.9].map(leftColor)).toEqual([theme.ok, theme.warn, theme.warn, theme.error])
})

test("relReset and clockAt format the reset", () => {
  expect([NOW - 1, NOW + 45 * MIN, NOW + 134 * MIN, NOW + (3 * 1440 + 5 * 60) * MIN].map(t => relReset(t, NOW))).toEqual(["now", "45m", "2h 14m", "3d 5h"])
  expect(clockAt(Date.UTC(2026, 0, 10, 22, 30), "America/Los_Angeles")).toBe("Sat 14:30")
})

test("parseOmp labels accounts by position, keeps tier buckets, and flags a missing window", () => {
  const rows = parseOmp(FIXTURE.omp!)
  expect(rows.map(r => `${r.account}/${r.window}`)).toEqual(["claude 1/5h", "claude 1/7d", "claude 1/7d fable", "claude 2/5h", "claude 2/7d", "codex 1/5h", "codex 1/7d"])
  expect(rows[0]).toMatchObject({ usedPct: 80, leftPct: 20 })
  const codex5h = rows.find(r => r.account === "codex 1" && r.window === "5h")!
  expect(codex5h).toMatchObject({ usedPct: null, leftPct: null, resetsAt: null })
  expect(cells(codex5h, NOW, "UTC").note).toBe("not reported")
})

test("parseZai maps hour and week units and computes left from remaining", () => {
  const rows = parseZai(FIXTURE.zai!)
  expect(rows.map(r => [r.window, r.leftPct])).toEqual([["5h", 25], ["7d", 100]])
})

test("mercuryRows numbers keys by ascending id and reports left of 100M", () => {
  const rows = mercuryRows([9, 4], { 4: 25_000_000, 9: 150_000_000 })
  expect(rows.map(r => [r.account, r.leftPct, r.note])).toEqual([["mercury key 1", 75, "25.0M / 100M"], ["mercury key 2", 0, "150.0M / 100M"]])
})

test("--once prints the fixture without starting the TUI", async () => {
  const dir = mkdtempSync(join(tmpdir(), "usage-tui-"))
  const file = join(dir, "fixture.json")
  writeFileSync(file, JSON.stringify(FIXTURE))
  const p = Bun.spawn(["bun", join(import.meta.dir, "usage-tui.ts"), "--once", "--fixture", file], { stdout: "pipe" })
  const out = await new Response(p.stdout).text()
  expect(await p.exited).toBe(0)
  const lines = out.trimEnd().split("\n").map(l => l.replace(/\s+/g, " "))
  expect(lines).toContain("claude 1 5h ████████████████░░░░ 20% left 1h 30m Sat 05:30")
  expect(lines).toContain("mercury key 2 100M ████████████████████ 0% left 150.0M / 100M")
  expect(out).toContain("no quota API")
  expect(out).toContain("not reported")
})

test("buildRows shows an error row when Mercury fails to load", () => {
  const rows = buildRows({ mercuryError: "database is locked" })
  expect(rows.find(r => r.account === "mercury")).toMatchObject({ leftPct: null, note: "unavailable: database is locked" })
})
