import { expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { ACCOUNT_W, AuthExpired, fitName, buildRows, cells, clockAt, deepseekRows, leftColor, leftOf, mercuryRows, parseOmp, parseQuotaMe, parseZai, readQuotaMe, quotaText, relReset, rtkRows, type QuotaInput } from "./quota.ts"

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
    "claude 1 5h", "7d", "7d fable", "claude 2 5h", "7d", "codex 1 5h", "7d", "glm 5h", "7d", "mercury key 1 100M", "mercury key 2 100M", "deepseek basic 5h",
  ])
  const lines = raw.map(l => l.replace(/\s+/g, " "))
  expect(lines).toContain("claude 1 5h ████████████████░░░░ 20% left 1h 30m Sat 05:30")
  expect(lines).toContain("mercury key 2 100M ████████████████████ 0% left 150.0M / 100M")
  expect(lines).toContain("deepseek basic 5h █████░░░░░░░░░░░░░░░ 75% left 1h 30m Sat 05:30")
  expect(out).toContain("not reported")
})

test("deepseekRows turns usage rows into bars and shows n/a for unreadable ones", () => {
  const rows = deepseekRows({ rows: [{ plan: "Basic", window: "5h", used: 25, limit: 100, resets_at: 1000 }, { plan: "Basic", window: "7d", used: null, limit: 100 }, { plan: "x" }] })
  expect(rows.map(r => [r.account, r.window, r.leftPct, r.resetsAt, r.note])).toEqual([["deepseek basic", "5h", 75, 1_000_000, undefined], ["deepseek basic", "7d", null, null, "n/a"]])
  expect(deepseekRows({}).map(r => r.note)).toEqual(["n/a"])
})

// Oracle: the quotaMe shape of deepseekv4pro.com plan quota (credits, ISO resetAt); invented numbers.
const QUOTA_ME = [
  { planName: "Basic", quota: { fiveHour: { usedCredits: 25, limitCredits: 100, resetAt: "2026-01-10T13:30:00Z" }, sevenDay: { usedCredits: 90, limitCredits: 120 } } },
  { planName: "Max", quota: { fiveHour: { usedCredits: 10, limitCredits: 400, resetAt: "2026-01-10T14:00:00Z" }, sevenDay: { usedCredits: 0, limitCredits: 1000 } } },
  { planName: "Idle", quota: null },
]

test("parseQuotaMe gives 5h and 7d rows with epoch-second resets and nulls for missing fields", () => {
  expect(parseQuotaMe(QUOTA_ME).rows).toEqual([
    { plan: "Basic", window: "5h", used: 25, limit: 100, resets_at: Date.UTC(2026, 0, 10, 13, 30) / 1000 },
    { plan: "Basic", window: "7d", used: 90, limit: 120, resets_at: null },
    { plan: "Max", window: "5h", used: 10, limit: 400, resets_at: Date.UTC(2026, 0, 10, 14, 0) / 1000 },
    { plan: "Max", window: "7d", used: 0, limit: 1000, resets_at: null },
    { plan: "Idle", window: "5h", used: null, limit: null, resets_at: null },
    { plan: "Idle", window: "7d", used: null, limit: null, resets_at: null },
  ])
  expect(parseQuotaMe("junk").rows).toEqual([])
  expect(deepseekRows(parseQuotaMe(QUOTA_ME)).map(r => [r.account, r.window, r.leftPct])).toEqual([["deepseek basic", "5h", 75], ["deepseek basic", "7d", 25], ["deepseek max", "5h", 97.5], ["deepseek max", "7d", 100], ["deepseek idle", "5h", null], ["deepseek idle", "7d", null]])
})

test("readQuotaMe renews the login once on auth and reports failures without throwing", async () => {
  let calls = 0
  let refreshed = 0
  const refresh = async () => { refreshed++ }
  const expired = async () => { if (calls++ === 0) throw new AuthExpired("auth"); return QUOTA_ME }
  expect((await readQuotaMe(expired, refresh)).value?.rows?.length).toBe(6)
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
  mkdirSync(join(dir, ".config/crewship"), { recursive: true })
  writeFileSync(join(dir, ".config/crewship/usage-providers.json"), JSON.stringify({ version: 1, providers: [{ id: "anthropic", label: "claude", accounts: 1, source: "omp-usage", found: ["omp"] }] }))
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

test("buildRows shows only the detected sources, plus a row for providers without a quota source", () => {
  const providers = [
    { id: "anthropic", label: "claude", accounts: 2, source: "omp-usage" as const, found: ["omp"] },
    { id: "xiaomi", label: "xiaomi", accounts: 1, source: "none" as const, found: ["omp"] },
  ]
  const rows = buildRows({ ...FIXTURE, providers })
  expect(rows.some(r => /^(glm|mercury|deepseek)/.test(r.account))).toBe(false)
  expect(rows.some(r => r.account.startsWith("claude"))).toBe(true)
  expect(rows.find(r => r.account === "xiaomi")?.note).toBe("1 account, quota not reported")
  expect(buildRows({ providers: [] })).toEqual([])
})

test("deepseekRows shortens long plan names to fit the account column", () => {
  const rows = deepseekRows({ rows: [
    { plan: "DeepSeek Coding Plan Max", window: "5h", used: 0, limit: 10, resets_at: 1 },
    { plan: "DeepSeek Coding Plan", window: "5h", used: 0, limit: 10, resets_at: 1 },
    { plan: "A Very Long Enterprise Plan Name That Overflows", window: "7d", used: 0, limit: 10, resets_at: 1 },
  ] })
  expect(rows.map(r => r.account)).toEqual(["deepseek max", "deepseek", "deepseek a very long enterprise name that overflows"])
})

test("fitName cuts any row name with an ellipsis so the bar column never moves", () => {
  expect(fitName("claude 1")).toBe("claude 1")
  const long = fitName("deepseek a very long enterprise name that overflows")
  expect(long).toBe("deepseek a very long enterpr…")
  expect(long.length).toBeLessThan(ACCOUNT_W)
  const rows = [{ account: "x".repeat(80), window: "5h", usedPct: 10, leftPct: 90, resetsAt: null }, { account: "glm", window: "5h", usedPct: 10, leftPct: 90, resetsAt: null }]
  const [a, b] = quotaText(rows, 0, "UTC").split("\n")
  expect(a.indexOf("█")).toBe(b.indexOf("█"))
  expect(a.indexOf("█")).toBe(ACCOUNT_W + 10)
})

test("rtk shows tokens saved from `rtk gain` only when detected, under the fixed name width", () => {
  const provider = { id: "rtk", label: "rtk", accounts: 1, source: "rtk-gain" as const, found: ["rtk-cli"] }
  const rtk = { summary: { total_saved: 1_234_567, avg_savings_pct: 61.4 } }
  expect(rtkRows(rtk)[0]).toMatchObject({ account: "rtk", leftPct: null, note: "1.2M tokens saved (61%)" })
  expect(rtkRows({ summary: { total_saved: 0, avg_savings_pct: 0 } })[0].note).toBe("0 tokens saved (0%)")
  const saved = (n: number) => rtkRows({ summary: { total_saved: n } })[0].note
  expect(saved(999_949)).toBe("999.9K tokens saved")
  expect(saved(999_950)).toBe("1M tokens saved")
  expect(saved(999_949_999)).toBe("999.9M tokens saved")
  expect(saved(999_950_000)).toBe("1B tokens saved")
  expect(rtkRows({})[0].note).toBe("not reported")
  const line = quotaText(buildRows({ providers: [provider], rtk }), NOW, "UTC")
  expect(line.slice(0, ACCOUNT_W + 10)).toBe("rtk".padEnd(ACCOUNT_W) + "-".padEnd(10))
  expect(line.trimEnd()).toEndWith("1.2M tokens saved (61%)")
  expect(buildRows({ providers: [{ ...provider, id: "x", source: "none" }], rtk })).toHaveLength(1)
  expect(buildRows({ providers: [provider], rtkError: "rtk exited non-zero" })[0].note).toBe("rtk exited non-zero")
})
