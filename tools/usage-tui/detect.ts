// Detects which subscriptions and accounts exist on this host and writes the Usage TUI provider list.
// Reads only provider names and account counts: never a key, token, email or id. Output is deterministic, so a re-run is a no-op.
// Usage: usage-tui-detect [--check] [--print]   (--check writes nothing; --print shows the list)
// Exit output: "changed" or "unchanged" on stdout, which Ansible reads for changed_when.
import { Database } from "bun:sqlite"
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs"
import { dirname } from "node:path"

export type QuotaSource = "omp-usage" | "zai" | "mercury-tokens" | "deepseek" | "none"
export type DetectedProvider = { id: string; label: string; accounts: number; source: QuotaSource; found: string[] }
export type ProviderList = { version: 1; providers: DetectedProvider[] }

// omp auth provider id -> how the TUI reads its quota. Any other omp provider is listed with source "none".
const KNOWN: Record<string, { label: string; source: QuotaSource }> = {
  anthropic: { label: "claude", source: "omp-usage" },
  "openai-codex": { label: "codex", source: "omp-usage" },
  zai: { label: "glm", source: "zai" },
  "zai-coding-plan": { label: "glm", source: "zai" },
  inception: { label: "mercury", source: "mercury-tokens" },
  deepseek: { label: "deepseek", source: "deepseek" },
}
// API-key environment variables checked by name only; the value is never read into the result.
const ENV_KEYS: Record<string, string[]> = {
  inception: ["INCEPTION_API_KEY", "INCEPTION_API_KEYS"],
  deepseek: ["DEEPSEEK_API_KEY"],
  zai: ["ZAI_API_KEY", "GLM_API_KEY"],
}

export type Env = { home: string; env: Record<string, string | undefined> }

export function configPath(e: Env): string {
  return e.env.USAGE_TUI_PROVIDERS ?? `${e.home}/.config/crewship/usage-providers.json`
}

function ompAccounts(e: Env): Record<string, number> {
  const path = e.env.OMP_AGENT_DB ?? `${e.home}/.omp/agent/agent.db`
  if (!existsSync(path)) return {}
  const db = new Database(path, { readonly: true })
  try {
    const rows = db.query("select provider, count(*) as n from auth_credentials where disabled_cause is null and provider not like 'mcp_oauth%' group by provider").all() as { provider: string; n: number }[]
    return Object.fromEntries(rows.map(r => [r.provider, r.n]))
  } finally {
    db.close()
  }
}

// rtk has no auth store: it counts as a provider when `rtk gain` runs.
function rtkWorks(e: Env): boolean {
  try {
    return Bun.spawnSync(["rtk", "gain"], { env: e.env, stdout: "ignore", stderr: "ignore" }).exitCode === 0
  } catch {
    return false // rtk is not installed
  }
}

export function detect(e: Env): ProviderList {
  const found = new Map<string, DetectedProvider>()
  const add = (id: string, accounts: number, from: string) => {
    const k = KNOWN[id]
    const p = found.get(id) ?? { id, label: k?.label ?? id, accounts: 0, source: k?.source ?? "none", found: [] }
    p.accounts = Math.max(p.accounts, accounts)
    if (!p.found.includes(from)) p.found.push(from)
    found.set(id, p)
  }
  for (const [id, n] of Object.entries(ompAccounts(e))) add(id, n, "omp")
  if (existsSync(`${e.home}/.codex/auth.json`)) add("openai-codex", 1, "codex-cli")
  for (const [id, names] of Object.entries(ENV_KEYS)) if (names.some(n => e.env[n])) add(id, 1, "env")
  // The GLM quota call reads its key from the zai-glm provider in models.yml; only the block's presence counts here.
  const models = `${e.home}/.omp/agent/models.yml`
  if (existsSync(models) && /^\s*zai-glm:/m.test(readFileSync(models, "utf8"))) add("zai", 1, "models.yml")
  if (rtkWorks(e)) add("rtk", 1, "rtk-cli")
  const providers = [...found.values()].sort((a, b) => a.id.localeCompare(b.id))
  return { version: 1, providers }
}

// The saved list, or a fresh detection when setup has not written one. Never writes.
export function readProviders(e: Env): ProviderList {
  try {
    const list = JSON.parse(readFileSync(configPath(e), "utf8")) as ProviderList
    if (list.version === 1 && Array.isArray(list.providers)) return list
  } catch {}
  return detect(e)
}

// Writes the file only when its content differs. Returns whether it changed.
export function apply(e: Env, check = false): { changed: boolean; list: ProviderList } {
  const list = detect(e)
  const text = JSON.stringify(list, null, 2) + "\n"
  const path = configPath(e)
  const old = existsSync(path) ? readFileSync(path, "utf8") : null
  if (old === text) return { changed: false, list }
  if (!check) {
    mkdirSync(dirname(path), { recursive: true, mode: 0o700 })
    writeFileSync(`${path}.tmp`, text, { mode: 0o600 })
    renameSync(`${path}.tmp`, path)
  }
  return { changed: true, list }
}

if (import.meta.main) {
  const args = process.argv.slice(2)
  const { changed, list } = apply({ home: process.env.HOME!, env: process.env }, args.includes("--check"))
  if (args.includes("--print")) console.error(list.providers.map(p => `${p.label.padEnd(12)} ${p.accounts} account(s)  quota: ${p.source}  via ${p.found.join(", ")}`).join("\n") || "no providers found")
  console.log(changed ? "changed" : "unchanged")
}
