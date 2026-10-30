import { expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { buildRows, cells, clockAt, deepseek, deepseekPlanRows, deepseekRow, leftColor, leftOf, mercuryRows, parseOmp, parseZai, relReset, resellerRow, type DeepseekPlans, type QuotaInput } from "./quota.ts"

const NOW = Date.UTC(2026, 0, 10, 12, 0, 0)
const MIN = 60_000
const limit = (windowId: string, used: number, resetsAt?: number, tier?: string) => ({
  scope: { windowId, ...(tier ? { tier } : {}) },
  window: { id: windowId, ...(resetsAt ? { resetsAt } : {}) },
  amount: { used, limit: 100, usedFraction: used / 100 },
})
// Invented numbers and provider names only.
// Recorded from the site's own /api/quota/me response; subscription ids replaced.
const PLANS = JSON.parse(readFileSync(join(import.meta.dir, "fixtures/deepseek-quota-me.json"), "utf8")) as DeepseekPlans
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
  deepseek: { normal_wallets: [{ currency: "USD", balance: "12.5" }] },
  deepseekPlans: PLANS,
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
  expect(raw.map(l => l.slice(0, 30).replace(/\s+/g, " ").trim())).toEqual([
    "claude 1 5h", "7d", "7d fable", "claude 2 5h", "7d", "codex 1 5h", "7d", "glm 5h", "7d", "mercury key 1 100M", "mercury key 2 100M",
    "ds coding plan max 5h", "7d", "ds coding plan 5h", "7d", "deepseek -", "deepseek (reseller) -",
  ])
  const lines = raw.map(l => l.replace(/\s+/g, " "))
  expect(lines).toContain("claude 1 5h ████████████████░░░░ 20% left 1h 30m Sat 05:30")
  expect(lines).toContain("mercury key 2 100M ████████████████████ 0% left 150.0M / 100M")
  expect(out).toContain("balance $12.50")
  expect(out).toContain("not reported")
})

test("deepseekRow shows the site balance labelled with its wallet currency", () => {
  expect(deepseekRow({ normal_wallets: [{ currency: "USD", balance: "12.5" }] }).note).toBe("balance $12.50")
  expect(deepseekRow({ normal_wallets: [{ currency: "CNY", balance: "100" }] }).note).toBe("balance CNY 100.00")
  expect(deepseekRow({ normal_wallets: [{ currency: "CNY", balance: "10" }, { currency: "USD", balance: "-0.005077804" }] }).note).toBe("balance -$0.0051")
  expect(deepseekRow({ normal_wallets: [{ currency: "USD", balance: 0 }] }).note).toBe("balance $0.00")
  expect(deepseekRow({}).note).toBe("no balance reported")
})

test("deepseekPlanRows reports both plans with 5h and 7d windows from credits", () => {
  const rows = deepseekPlanRows(PLANS)
  expect(rows.map(r => `${r.account} ${r.window}`)).toEqual(["ds coding plan max 5h", "ds coding plan max 7d", "ds coding plan 5h", "ds coding plan 7d"])
  expect(rows[0]).toMatchObject({ usedPct: 0, leftPct: 100, resetsAt: Date.parse("2026-10-31T01:28:25.412641Z") })
  const used = deepseekPlanRows({ plans: [{ planName: "DeepSeek Coding Plan", quota: { fiveHour: { limitCredits: 200, usedCredits: 50, resetAt: "2026-10-31T00:00:00Z" } } }] })
  expect(used[0]).toMatchObject({ usedPct: 25, leftPct: 75 })
  expect(used[1]).toMatchObject({ window: "7d", usedPct: null, resetsAt: null }) // a window the site omits stays "not reported"
  expect(deepseekPlanRows({ plans: [{ planName: "DeepSeek Coding Plan", quotaStatus: "pending" }] })[0]).toMatchObject({ leftPct: null, note: "pending" })
})

test("buildRows shows an error row when the plan read fails", () => {
  expect(buildRows({ deepseekPlansError: "Mac not reachable" }).find(r => r.account === "deepseek plans")?.note).toBe("unavailable: Mac not reachable")
})

test("a failed DeepSeek read holds its error, so no second ssh runs within 10 minutes", async () => {
  // The probe runs as a child with the stub first on PATH: Bun.spawn resolves commands from the
  // PATH a process starts with, so an in-test process.env.PATH edit would still reach the real Mac.
  const dir = mkdtempSync(join(tmpdir(), "usage-tui-ds-"))
  const log = join(dir, "ssh.log")
  writeFileSync(join(dir, "ssh"), `#!/bin/sh\necho called >> "${log}"\necho "ssh: connect to host mac port 22: Connection refused" >&2\nexit 255\n`)
  chmodSync(join(dir, "ssh"), 0o755)
  const probe = join(dir, "probe.ts")
  writeFileSync(probe, [
    `const { deepseek } = await import(${JSON.stringify(join(import.meta.dir, "quota.ts"))})`,
    "const a = await deepseek()",
    "const b = await deepseek()",
    `console.log(JSON.stringify({ error: a.error ?? null, heldTwice: b === a }))`,
    "",
  ].join("\n"))
  const p = Bun.spawn(["bun", probe], { env: { ...process.env, PATH: `${dir}:${process.env.PATH}` }, stdout: "pipe", stderr: "ignore" })
  const out = JSON.parse(await new Response(p.stdout).text()) as { error: string | null; heldTwice: boolean }
  expect(await p.exited).toBe(0)
  expect(out.error).toBe("Mac not reachable") // ssh's stderr names the host; the panel must not
  expect(out.heldTwice).toBe(true)
  expect(readFileSync(log, "utf8")).toBe("called\n")
}, 30_000)

test("buildRows shows an error row when the DeepSeek site read fails", () => {
  const rows = buildRows({ deepseekError: "connection refused" })
  expect(rows.find(r => r.account === "deepseek")).toMatchObject({ leftPct: null, note: "unavailable: connection refused" })
})

test("resellerRow shows the key's cumulative spend and its own account label", () => {
  expect(resellerRow({ spend: 6.609482 })).toMatchObject({ account: "deepseek (reseller)", leftPct: null, note: "spent $6.61" })
  expect(resellerRow({ spend: NaN }).note).toBe("no spend reported")
})

test("buildRows keeps the reseller row when the Dia read fails, and shows its own error", () => {
  const rows = buildRows({ deepseekError: "connection refused", reseller: { spend: 1.5 } })
  expect(rows.find(r => r.account === "deepseek")?.note).toBe("unavailable: connection refused")
  expect(rows.find(r => r.account === "deepseek (reseller)")?.note).toBe("spent $1.50")
  expect(buildRows({ resellerError: "reseller HTTP 401" }).find(r => r.account === "deepseek (reseller)")?.note).toBe("unavailable: reseller HTTP 401")
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
