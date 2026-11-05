import { expect, test } from "bun:test"
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"
import { buildRows, cells, clockAt, deepseekRows, leftColor, leftOf, mercuryRows, parseOmp, parseZai, readUsageCommand, relReset, resellerRow, type QuotaInput } from "./quota.ts"

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
  expect(raw.map(l => l.slice(0, 30).replace(/\s+/g, " ").trim())).toEqual([
    "claude 1 5h", "7d", "7d fable", "claude 2 5h", "7d", "codex 1 5h", "7d", "glm 5h", "7d", "mercury key 1 100M", "mercury key 2 100M", "deepseek Basic 5h", "deepseek (reseller) -",
  ])
  const lines = raw.map(l => l.replace(/\s+/g, " "))
  expect(lines).toContain("claude 1 5h ████████████████░░░░ 20% left 1h 30m Sat 05:30")
  expect(lines).toContain("mercury key 2 100M ████████████████████ 0% left 150.0M / 100M")
  expect(lines).toContain("deepseek Basic 5h █████░░░░░░░░░░░░░░░ 75% left 1h 30m Sat 05:30")
  expect(out).toContain("not reported")
})

test("deepseekRows turns usage rows into bars and shows n/a for unreadable ones", () => {
  const rows = deepseekRows({ rows: [{ plan: "Basic", window: "5h", used: 25, limit: 100, resets_at: 1000 }, { plan: "Basic", window: "7d", used: null, limit: 100 }, { window: "x" }] })
  expect(rows.map(r => [r.account, r.window, r.leftPct, r.resetsAt, r.note])).toEqual([["deepseek Basic", "5h", 75, 1_000_000, undefined], ["deepseek Basic", "7d", null, null, "n/a"]])
  expect(deepseekRows({}).map(r => r.note)).toEqual(["n/a"])
})

const commandDir = () => mkdtempSync(join(tmpdir(), "usage-tui-cmd-"))
const script = (dir: string, body: string) => {
  const f = join(dir, "usage.sh")
  writeFileSync(f, `#!/bin/sh\n${body}\n`)
  chmodSync(f, 0o755)
  return f
}

test("readUsageCommand reports an absent command without running anything", async () => {
  expect(await readUsageCommand(undefined)).toEqual({ error: "no usage command set" })
  expect(await readUsageCommand("  ")).toEqual({ error: "no usage command set" })
})

test("readUsageCommand reports a failing command and invalid output", async () => {
  const dir = commandDir()
  expect(await readUsageCommand(script(dir, "echo secret-detail >&2; exit 3"))).toEqual({ error: "command exited 3" })
  expect(await readUsageCommand(script(dir, "echo not-json"))).toEqual({ error: "command printed invalid JSON" })
  expect(await readUsageCommand(join(dir, "missing"))).toEqual({ error: "command failed" })
})

test("readUsageCommand parses a valid JSON result", async () => {
  const out = await readUsageCommand(script(commandDir(), `echo '{"rows":[{"plan":"Basic","window":"5h","used":1,"limit":4}]}'`))
  expect(out.error).toBeUndefined()
  expect(deepseekRows(out.value!)[0]).toMatchObject({ account: "deepseek Basic", leftPct: 75 })
})

test("buildRows shows n/a when the DeepSeek command is absent or fails", () => {
  expect(buildRows({}).find(r => r.account === "deepseek")?.note).toBe("n/a")
  expect(buildRows({ deepseekError: "command exited 3" }).find(r => r.account === "deepseek")?.note).toBe("n/a: command exited 3")
})

test("resellerRow shows the key's cumulative spend and its own account label", () => {
  expect(resellerRow({ spend: 6.609482 })).toMatchObject({ account: "deepseek (reseller)", leftPct: null, note: "spent $6.61" })
  expect(resellerRow({ spend: NaN }).note).toBe("no spend reported")
})

test("buildRows keeps the reseller row when the DeepSeek read fails, and shows its own error", () => {
  const rows = buildRows({ deepseekError: "connection refused", reseller: { spend: 1.5 } })
  expect(rows.find(r => r.account === "deepseek")?.note).toBe("n/a: connection refused")
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
