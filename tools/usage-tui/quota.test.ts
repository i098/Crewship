import { expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { AuthExpired, buildRows, cells, clockAt, deepseekRows, leftColor, leftOf, mercuryRows, parseOmp, parseQuotaMe, parseZai, readQuotaMe, relReset, type QuotaInput } from "./quota.ts"

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
  deepseek: { rows: [{ plan: "Basic", window: "5h", used: 25, limit: 100, resets_at: (NOW + 90 * MIN) / 1000 }] },
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
  const raw = out.trimEnd().split("\n")
  expect(raw.map(l => l.slice(0, 40).replace(/\s+/g, " ").trim())).toEqual([
    "claude 1 5h", "7d", "7d fable", "claude 2 5h", "7d", "codex 1 5h", "7d", "glm 5h", "7d", "mercury key 1 100M", "mercury key 2 100M", "deepseek (reseller) Basic 5h",
  ])
  const lines = raw.map(l => l.replace(/\s+/g, " "))
  expect(lines).toContain("claude 1 5h ████████████████░░░░ 20% left 1h 30m Sat 05:30")
  expect(lines).toContain("mercury key 2 100M ████████████████████ 0% left 150.0M / 100M")
  expect(lines).toContain("deepseek (reseller) Basic 5h █████░░░░░░░░░░░░░░░ 75% left 1h 30m Sat 05:30")
  expect(out).toContain("not reported")
})

test("deepseekRows turns usage rows into bars and shows n/a for unreadable ones", () => {
  const rows = deepseekRows({ rows: [{ plan: "Basic", window: "5h", used: 25, limit: 100, resets_at: 1000 }, { plan: "Basic", window: "7d", used: null, limit: 100 }, { plan: "x" }] })
  expect(rows.map(r => [r.account, r.window, r.leftPct, r.resetsAt, r.note])).toEqual([["deepseek (reseller) Basic", "5h", 75, 1_000_000, undefined], ["deepseek (reseller) Basic", "7d", null, null, "n/a"]])
  expect(deepseekRows({}).map(r => r.note)).toEqual(["n/a"])
})

// Oracle: the quotaMe shape of deepseekv4pro.com plan quota (credits, ISO resetAt); invented numbers.
const QUOTA_ME = [
  { planName: "Basic", quota: { fiveHour: { usedCredits: 25, limitCredits: 100, resetAt: "2026-01-10T13:30:00Z" }, sevenDay: { usedCredits: 90, limitCredits: 120 } } },
  { planName: "Max", quota: { fiveHour: { usedCredits: 10, limitCredits: 400, resetAt: "2026-01-10T14:00:00Z" }, sevenDay: { usedCredits: 0, limitCredits: 1000 } } },
]

test("parseQuotaMe gives 5h and 7d rows with epoch-second resets and nulls for missing fields", () => {
  expect(parseQuotaMe(QUOTA_ME).rows).toEqual([
    { plan: "Basic", window: "5h", used: 25, limit: 100, resets_at: Date.UTC(2026, 0, 10, 13, 30) / 1000 },
    { plan: "Basic", window: "7d", used: 90, limit: 120, resets_at: null },
    { plan: "Max", window: "5h", used: 10, limit: 400, resets_at: Date.UTC(2026, 0, 10, 14, 0) / 1000 },
    { plan: "Max", window: "7d", used: 0, limit: 1000, resets_at: null },
  ])
  expect(parseQuotaMe("junk").rows).toEqual([])
  expect(deepseekRows(parseQuotaMe(QUOTA_ME)).map(r => [r.account, r.window, r.leftPct])).toEqual([["deepseek (reseller) Basic", "5h", 75], ["deepseek (reseller) Basic", "7d", 25], ["deepseek (reseller) Max", "5h", 97.5], ["deepseek (reseller) Max", "7d", 100]])
})

test("readQuotaMe renews the login once on auth and reports failures without throwing", async () => {
  let calls = 0
  let refreshed = 0
  const refresh = async () => { refreshed++ }
  const expired = async () => { if (calls++ === 0) throw new AuthExpired("auth"); return QUOTA_ME }
  expect((await readQuotaMe(expired, refresh)).value?.rows?.length).toBe(4)
  expect(refreshed).toBe(1)
  expect(await readQuotaMe(async () => { throw new AuthExpired("auth") }, async () => { throw new Error("signed out") })).toEqual({ error: "signed out" })
  expect(await readQuotaMe(async () => { throw new Error("rate-limited") }, refresh)).toEqual({ error: "rate-limited" })
})

test("buildRows has one reseller row, n/a with the reason when the quota call fails", () => {
  expect(buildRows({}).filter(r => r.account.startsWith("deepseek")).map(r => [r.account, r.note])).toEqual([["deepseek (reseller)", "n/a"]])
  expect(buildRows({ deepseekError: "signed out" }).find(r => r.account === "deepseek (reseller)")?.note).toBe("n/a: signed out")
})

test("buildRows shows an error row when Mercury fails to load", () => {
  const rows = buildRows({ mercuryError: "database is locked" })
  expect(rows.find(r => r.account === "mercury")).toMatchObject({ leftPct: null, note: "unavailable: database is locked" })
})

test("buildRows says no accounts reported when omp returns an empty reports list", () => {
  const rows = buildRows({ omp: { reports: [] } })
  expect(rows.find(r => r.account === "omp usage")).toMatchObject({ leftPct: null, note: "no accounts reported" })
})

// The runner inherits this process's group and session, as the TUI inherits the pane's.
// Oracle: a stub omp reports its own pgid and sid through the JSON that loadQuota returns.
test("quota load runs omp outside the TUI's process group and session", async () => {
  const dir = mkdtempSync(join(tmpdir(), "usage-tui-"))
  const bin = join(dir, "bin")
  mkdirSync(bin)
  writeFileSync(join(bin, "omp"), `#!/bin/sh\nprintf '{"probe":"%s"}\\n' "$(ps -o pid=,pgid=,sid= -p $$)"\n`)
  chmodSync(join(bin, "omp"), 0o755)
  const runner = join(dir, "runner.ts")
  // Static import cannot work here: quota.ts reads HOME when it loads, so the runner needs
  // this test's temporary HOME already in place before the module is imported.
  writeFileSync(runner, `const { loadQuota } = await import(${JSON.stringify(join(import.meta.dir, "quota.ts"))})\nconsole.log(JSON.stringify(await loadQuota()))\n`)
  const p = Bun.spawn(["bun", runner], { env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, HOME: dir }, stdout: "pipe", stderr: "ignore", stdin: "ignore" })
  try {
    const out = await new Response(p.stdout).text()
    expect(await p.exited).toBe(0)
    const omp: unknown = JSON.parse(out).omp
    if (!omp || typeof omp !== "object" || !("probe" in omp) || typeof omp.probe !== "string") throw new Error("stub omp reported no process ids")
    const probe = omp.probe.trim().split(/\s+/).map(Number)
    const parent = Bun.spawnSync(["ps", "-o", "pgid=,sid=", "-p", String(process.pid)]).stdout.toString().trim().split(/\s+/).map(Number)
    expect(probe).toHaveLength(3)
    expect(parent).toHaveLength(2)
    expect(probe[1]).not.toBe(parent[0])
    expect(probe[2]).not.toBe(parent[1])
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}, 60_000)
