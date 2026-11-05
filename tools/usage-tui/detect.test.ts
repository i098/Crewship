import { expect, test } from "bun:test"
import { Database } from "bun:sqlite"
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { apply, detect, type ProviderList } from "./detect.ts"

function home(creds: [string, string | null][], codex = false) {
  const h = mkdtempSync(join(tmpdir(), "detect-"))
  mkdirSync(join(h, ".omp/agent"), { recursive: true })
  const db = new Database(join(h, ".omp/agent/agent.db"))
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
