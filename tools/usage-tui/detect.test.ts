import { expect, test } from "bun:test"
import { Database } from "bun:sqlite"
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { chmodSync } from "node:fs"
import { apply, detect, readProviders, type ProviderList } from "./detect.ts"

function home(creds: [string, string | null][], codex = false) {
  const h = mkdtempSync(join(tmpdir(), "detect-"))
  mkdirSync(join(h, ".omp/agent"), { recursive: true })
  const db = new Database(join(h, ".omp/agent/agent.db"))
  db.run("pragma journal_mode=off")
  db.run("pragma synchronous=off")
  db.run("create table auth_credentials (id integer primary key, provider text, data text, disabled_cause text)")
  for (const [p, d] of creds) db.run("insert into auth_credentials (provider, data, disabled_cause) values (?, 'SECRET-TOKEN', ?)", [p, d])
  db.close()
  if (codex) {
    mkdirSync(join(h, ".codex"))
    writeFileSync(join(h, ".codex/auth.json"), "{}")
  }
  return h
}

test("counts enabled omp accounts per provider, skips disabled and mcp rows, never stores secrets", () => {
  const h = home([["anthropic", null], ["anthropic", null], ["anthropic", "revoked"], ["mcp_oauth:x", null], ["xiaomi", null], ["deepseek", null]])
  const { changed } = apply({ home: h, env: {} })
  expect(changed).toBe(true)
  const text = readFileSync(join(h, ".config/crewship/usage-providers.json"), "utf8")
  expect(text).not.toContain("SECRET")
  const byId = Object.fromEntries((JSON.parse(text) as ProviderList).providers.map(p => [p.id, p]))
  expect(Object.keys(byId)).toEqual(["anthropic", "deepseek", "xiaomi"])
  expect(byId.anthropic).toMatchObject({ label: "claude", accounts: 2, source: "omp-usage" })
  expect(byId.xiaomi).toMatchObject({ label: "xiaomi", source: "none" })
})

test("a second apply reports unchanged, and --check writes nothing", () => {
  const h = home([["inception", null]])
  const e = { home: h, env: {} }
  expect(apply(e, true).changed).toBe(true)
  expect(() => readFileSync(join(h, ".config/crewship/usage-providers.json"))).toThrow()
  expect(apply(e).changed).toBe(true)
  expect(apply(e).changed).toBe(false)
})

test("merges codex login and env keys with omp accounts without double counting", () => {
  const h = home([["openai-codex", null]], true)
  const list = detect({ home: h, env: { INCEPTION_API_KEY: "x", ZAI_API_KEY: "y" } })
  expect(list.providers.map(p => p.id)).toEqual(["inception", "openai-codex", "zai"])
  expect(list.providers[1]).toMatchObject({ accounts: 1, found: ["omp", "codex-cli"] })
  expect(list.providers[2]).toMatchObject({ label: "glm", source: "zai", found: ["env"] })
})

test("a host with no omp database yields an empty list", () => {
  const h = mkdtempSync(join(tmpdir(), "detect-"))
  expect(detect({ home: h, env: {} }).providers).toEqual([])
})

test("rtk is a provider only when `rtk gain` exits 0", () => {
  const h = mkdtempSync(join(tmpdir(), "detect-"))
  const bin = join(h, "bin")
  mkdirSync(bin)
  const env = { PATH: `${bin}:/usr/bin:/bin` }
  expect(detect({ home: h, env }).providers).toEqual([])
  writeFileSync(join(bin, "rtk"), "#!/bin/sh\n[ \"$1\" = gain ]\n")
  chmodSync(join(bin, "rtk"), 0o755)
  expect(detect({ home: h, env }).providers).toEqual([expect.objectContaining({ id: "rtk", source: "rtk-gain" })])
  writeFileSync(join(bin, "rtk"), "#!/bin/sh\nexit 1\n")
  expect(detect({ home: h, env }).providers).toEqual([])
})

test("readProviders prefers the saved list and falls back to detection without writing", () => {
  const h = home([["anthropic", null]])
  const e = { home: h, env: { PATH: "/nonexistent" } }
  expect(readProviders(e).providers.map(p => p.id)).toEqual(["anthropic"])
  expect(() => readFileSync(join(h, ".config/crewship/usage-providers.json"))).toThrow()
  apply(e)
  writeFileSync(join(h, ".config/crewship/usage-providers.json"), JSON.stringify({ version: 1, providers: [] }))
  expect(readProviders(e).providers).toEqual([])
})

test("a zai-glm provider in models.yml counts as GLM without reading its key", () => {
  const h = home([])
  writeFileSync(join(h, ".omp/agent/models.yml"), "providers:\n  zai-glm:\n    apiKey: SECRET-KEY\n")
  const list = detect({ home: h, env: { PATH: "/nonexistent" } })
  expect(list.providers).toEqual([{ id: "zai", label: "glm", accounts: 1, source: "zai", found: ["models.yml"] }])
})

test("a DeepSeek key alone has no reseller source; a deepseekv4pro.com session in the fleet jar does", () => {
  const h = home([["deepseek", null]])
  const e = { home: h, env: { DEEPSEEK_API_KEY: "k", PATH: "/nonexistent" } }
  expect(detect(e).providers).toEqual([expect.objectContaining({ id: "deepseek", source: "none" })])
  mkdirSync(join(h, ".fleet-browser"))
  writeFileSync(join(h, ".fleet-browser/cookies.json"), JSON.stringify({ a: { name: "n", value: "v", domain: ".deepseekv4pro.com" } }))
  const p = detect(e).providers
  expect(p).toEqual([expect.objectContaining({ id: "deepseek", source: "deepseek" })])
  expect(JSON.stringify(p)).not.toContain('"v"')
})

test("codex CLI login alone has no quota source, a corrupt agent.db is ignored, and the fallback skips rtk", () => {
  const h = home([], true)
  const bin = join(h, "bin")
  mkdirSync(bin)
  writeFileSync(join(bin, "rtk"), "#!/bin/sh\nexit 0\n")
  chmodSync(join(bin, "rtk"), 0o755)
  const e = { home: h, env: { PATH: bin } }
  expect(readProviders(e).providers).toEqual([expect.objectContaining({ id: "openai-codex", source: "none" })])
  writeFileSync(join(h, ".omp/agent/agent.db"), "not a database")
  expect(detect(e).providers.map(p => p.id)).toEqual(["openai-codex", "rtk"])
})
