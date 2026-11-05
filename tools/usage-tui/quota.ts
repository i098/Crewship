// Remaining-quota rows for usage-tui: parsing, percent-left maths, colors, reset formatting, loaders.
// Sources: `omp usage --json` (Claude, Codex), the Z.ai quota endpoint, omp session files (Mercury per key),
// the reseller's quotaMe call (DeepSeek plan quota).
// Accounts are labelled by position ("claude 2", "mercury key 1"), never by email, id or key text.
import { Database } from "bun:sqlite"
import { mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { theme } from "../tui-theme/theme.ts"

export const MERCURY_LIMIT = 100_000_000
export const QUOTA_MIN_MS = 60_000

export type QuotaRow = {
  account: string
  window: string
  usedPct: number | null // null = the source did not report this window
  leftPct: number | null
  resetsAt: number | null
  note?: string // shown instead of the numbers, e.g. "balance $12.00"
}

const PROVIDER_NAME: Record<string, string> = { anthropic: "claude", "openai-codex": "codex" }
// Windows every Claude and Codex account should report; a missing one is shown as "not reported".
const EXPECTED: Record<string, string[]> = { claude: ["5h", "7d"], codex: ["5h", "7d"] }

const clamp = (v: number) => Math.max(0, Math.min(100, v))
const finite = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v)

export function leftOf(used: number, limit: number): { usedPct: number; leftPct: number } | null {
  if (!finite(used) || !finite(limit) || limit <= 0) return null
  const usedPct = clamp((100 * used) / limit)
  return { usedPct, leftPct: 100 - usedPct }
}

// ---- omp usage --json -----------------------------------------------------
type OmpLimit = {
  scope?: { windowId?: string; tier?: string }
  window?: { id?: string; resetsAt?: number }
  amount?: { used?: number; limit?: number; remainingFraction?: number; usedFraction?: number }
}
export type OmpUsage = { reports?: { provider: string; limits?: OmpLimit[] }[] }

export function parseOmp(json: OmpUsage): QuotaRow[] {
  const rows: QuotaRow[] = []
  const seen: Record<string, number> = {}
  for (const rep of json.reports ?? []) {
    const provider = PROVIDER_NAME[rep.provider] ?? rep.provider
    const account = `${provider} ${(seen[provider] = (seen[provider] ?? 0) + 1)}`
    const byWindow = new Map<string, QuotaRow>()
    for (const l of rep.limits ?? []) {
      const win = l.scope?.windowId ?? l.window?.id ?? "?"
      const name = l.scope?.tier ? `${win} ${l.scope.tier}` : win
      const a = l.amount ?? {}
      // Prefer the reported fraction; fall back to used/limit.
      const m = finite(a.usedFraction) ? { usedPct: clamp(100 * a.usedFraction), leftPct: 100 - clamp(100 * a.usedFraction) } : leftOf(a.used as number, a.limit as number)
      byWindow.set(name, { account, window: name, usedPct: m?.usedPct ?? null, leftPct: m?.leftPct ?? null, resetsAt: finite(l.window?.resetsAt) ? l.window.resetsAt : null })
    }
    const names = [...(EXPECTED[provider] ?? []), ...[...byWindow.keys()].filter(k => !(EXPECTED[provider] ?? []).includes(k))]
    for (const w of names) rows.push(byWindow.get(w) ?? { account, window: w, usedPct: null, leftPct: null, resetsAt: null })
  }
  return rows
}

// ---- Z.ai (GLM) -----------------------------------------------------------
export type ZaiQuota = { data?: { limits?: { unit: number; number: number; usage: number; remaining: number; nextResetTime?: number }[] } }

// unit 3 = hours, 6 = weeks, as observed from the endpoint; anything else keeps its raw unit.
const zaiWindow = (unit: number, n: number) => (unit === 3 ? `${n}h` : unit === 6 ? `${7 * n}d` : `u${unit}x${n}`)

export function parseZai(json: ZaiQuota): QuotaRow[] {
  const limits = json.data?.limits ?? []
  if (!limits.length) return [{ account: "glm", window: "5h", usedPct: null, leftPct: null, resetsAt: null }]
  return limits.map(l => {
    const m = leftOf(l.usage - l.remaining, l.usage)
    return { account: "glm", window: zaiWindow(l.unit, l.number), usedPct: m?.usedPct ?? null, leftPct: m?.leftPct ?? null, resetsAt: finite(l.nextResetTime) ? l.nextResetTime : null }
  })
}

// ---- Mercury: flat 100M tokens per key ---------------------------------------
export function mercuryRows(keyIds: number[], tokens: Record<string, number>): QuotaRow[] {
  return [...keyIds].sort((a, b) => a - b).map((id, i) => {
    const used = tokens[id] ?? 0
    const m = leftOf(used, MERCURY_LIMIT)!
    return { account: `mercury key ${i + 1}`, window: "100M", ...m, resetsAt: null, note: `${compactTokens(used)} / 100M` }
  })
}
const compactTokens = (v: number) => (v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K` : String(v))

// ---- DeepSeek reseller: plan quota from the reseller's quotaMe call -----------------
// The reseller (deepseekv4pro.com) reports plan credits through quotaMe, read over HTTP via api-anything with the
// saved login, renewed from the fleet cookie jar when it expires. resets_at is epoch seconds. No browser is opened.
export type DeepseekUsage = { rows?: { plan?: string; window?: string; used?: number | null; limit?: number | null; resets_at?: number | null }[] }

const RESELLER = "deepseek (reseller)"
const resellerNote = (note: string): QuotaRow => ({ account: RESELLER, window: "-", usedPct: null, leftPct: null, resetsAt: null, note })

export function deepseekRows(json: DeepseekUsage): QuotaRow[] {
  const rows = (Array.isArray(json.rows) ? json.rows : []).flatMap(r => {
    if (!r || typeof r.window !== "string") return []
    const left = finite(r.used) && finite(r.limit) ? leftOf(r.used, r.limit) : null
    return [{ account: typeof r.plan === "string" && r.plan ? `${RESELLER} ${r.plan}` : RESELLER, window: r.window, usedPct: left?.usedPct ?? null, leftPct: left?.leftPct ?? null, resetsAt: finite(r.resets_at) ? r.resets_at * 1000 : null, note: left ? undefined : "n/a" }]
  })
  return rows.length ? rows : [resellerNote("n/a")]
}

// ---- assembly ---------------------------------------------------------------
export type QuotaInput = {
  now?: number // fixtures pin the clock
  omp?: OmpUsage
  ompError?: string
  zai?: ZaiQuota
  zaiError?: string
  mercury?: { keyIds: number[]; tokens: Record<string, number> }
  mercuryError?: string
  deepseek?: DeepseekUsage
  deepseekError?: string
}

export function buildRows(inp: QuotaInput): QuotaRow[] {
  const rows: QuotaRow[] = []
  const ompRows = inp.omp ? parseOmp(inp.omp) : []
  if (ompRows.length) rows.push(...ompRows)
  else rows.push({ account: "omp usage", window: "-", usedPct: null, leftPct: null, resetsAt: null, note: inp.ompError ?? (inp.omp ? "no accounts reported" : "not reported") })
  if (inp.zai) rows.push(...parseZai(inp.zai))
  else rows.push({ account: "glm", window: "-", usedPct: null, leftPct: null, resetsAt: null, note: inp.zaiError ?? "not reported" })
  if (inp.mercury) rows.push(...mercuryRows(inp.mercury.keyIds, inp.mercury.tokens))
  else if (inp.mercuryError) rows.push({ account: "mercury", window: "-", usedPct: null, leftPct: null, resetsAt: null, note: `unavailable: ${inp.mercuryError}` })
  if (inp.deepseek) rows.push(...deepseekRows(inp.deepseek))
  else rows.push(resellerNote(inp.deepseekError ? `n/a: ${inp.deepseekError}` : "n/a"))
  return rows
}

// ---- presentation -------------------------------------------------------------
// green above 50% left, yellow 20 to 50, red below 20
export function leftColor(left: number): string {
  return left > 50 ? theme.ok : left >= 20 ? theme.warn : theme.error
}

export function relReset(at: number, now: number): string {
  const min = Math.floor((at - now) / 60_000)
  if (min <= 0) return "now"
  const d = Math.floor(min / 1440)
  const h = Math.floor((min % 1440) / 60)
  if (d) return `${d}d ${h}h`
  return h ? `${h}h ${min % 60}m` : `${min}m`
}

export function clockAt(at: number, tz: string): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", weekday: "short", hour: "2-digit", minute: "2-digit" }).formatToParts(at).map(x => [x.type, x.value]))
  return `${p.weekday} ${p.hour}:${p.minute}`
}

export const BAR_W = 20
export const ACCOUNT_W = 30
export type Cells = { bar: string; left: string; reset: string; clock: string; color: string; note: string }

export function cells(r: QuotaRow, now: number, tz: string): Cells {
  if (r.leftPct === null) return { bar: "", left: "", reset: "", clock: "", color: theme.muted, note: r.note ?? "not reported" }
  const filled = Math.round((r.usedPct! / 100) * BAR_W)
  return {
    bar: "█".repeat(filled) + "░".repeat(BAR_W - filled),
    left: `${Math.round(r.leftPct)}% left`,
    reset: r.resetsAt === null ? "" : relReset(r.resetsAt, now),
    clock: r.resetsAt === null ? "" : clockAt(r.resetsAt, tz),
    color: leftColor(r.leftPct),
    note: r.note ?? "",
  }
}

export function quotaText(rows: QuotaRow[], now: number, tz: string): string {
  let last = ""
  return rows
    .map(r => {
      const c = cells(r, now, tz)
      const acct = r.account === last ? "" : r.account
      last = r.account
      return `${acct.padEnd(ACCOUNT_W)}${r.window.padEnd(10)}${c.bar.padEnd(BAR_W + 2)}${c.left.padEnd(10)}${c.reset.padEnd(10)}${c.clock.padEnd(11)}${c.note}`.trimEnd()
    })
    .join("\n")
}

// ---- loaders ------------------------------------------------------------------
const HOME = process.env.HOME ?? ""
const SESSIONS = `${HOME}/.omp/agent/sessions`
const AGENT_DB = `${HOME}/.omp/agent/agent.db`

// setsid -f: the child leaves the pane's foreground group, so herdr does not list the pane as omp.
// setsid -w keeps the child's exit status for the check below.
async function run(cmd: string[]): Promise<string> {
  const p = Bun.spawn(["setsid", "-f", "-w", ...cmd], { stdout: "pipe", stderr: "ignore", stdin: "ignore" })
  const out = await new Response(p.stdout).text()
  if ((await p.exited) !== 0) throw new Error(`${cmd[0]} exited non-zero`)
  return out
}

// The key is read at call time, held in a local, and never logged; errors carry only an HTTP status.
async function fetchZai(): Promise<ZaiQuota> {
  const yml = await Bun.file(`${HOME}/.omp/agent/models.yml`).text()
  const key = yml.match(/zai-glm:[\s\S]*?apiKey:\s*(\S+)/)?.[1] ?? process.env.ZAI_API_KEY
  if (!key) throw new Error("no key")
  const res = await fetch("https://api.z.ai/api/monitor/usage/quota/limit", { headers: { Authorization: `Bearer ${key}`, Accept: "application/json" }, signal: AbortSignal.timeout(15_000) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return (await res.json()) as ZaiQuota
}

// omp session files are append-only JSONL; read each Mercury file once and then only its new bytes.
const files = new Map<string, number>() // path -> bytes already read
const tokens: Record<string, number> = {}
let scannedAt = 0
async function mercuryTokens(): Promise<Record<string, number>> {
  const since = scannedAt ? ["-newermt", `@${Math.floor(scannedAt / 1000) - 5}`] : []
  scannedAt = Date.now()
  // grep exits 1 for xargs batches with no match, so `|| true`.
  const script = 'find "$1" -name "*.jsonl" "${@:2}" -print0 | xargs -0 -r grep -lF \'"provider":"inception"\' || true'
  const found = await run(["bash", "-c", script, "bash", SESSIONS, ...since]).catch(() => "")
  for (const f of found.split("\n").filter(Boolean)) if (!files.has(f)) files.set(f, 0)
  for (const [f, off] of files) {
    const buf = new Uint8Array(await Bun.file(f).slice(off).arrayBuffer().catch(() => new ArrayBuffer(0))) // a deleted session file adds nothing
    const end = buf.lastIndexOf(10) + 1 // complete lines only
    files.set(f, off + end)
    for (const line of new TextDecoder().decode(buf.subarray(0, end)).split("\n")) {
      if (!line.includes('"provider":"inception"')) continue
      try {
        const m = JSON.parse(line).message
        if (m?.provider === "inception" && finite(m.usage?.totalTokens) && finite(m.credentialId)) tokens[m.credentialId] = (tokens[m.credentialId] ?? 0) + m.usage.totalTokens
      } catch {}
    }
  }
  return tokens
}

function mercuryKeyIds(): number[] {
  const db = new Database(AGENT_DB, { readonly: true })
  try {
    return (db.query("select id from auth_credentials where provider = 'inception' and disabled_cause is null order by id").all() as { id: number }[]).map(r => r.id)
  } finally {
    db.close()
  }
}

const DEEPSEEK_MIN_MS = 10 * 60_000
let deepseekAt = 0
let deepseekLast: { value?: DeepseekUsage; error?: string } = {}

const WINDOWS: [string, string][] = [["fiveHour", "5h"], ["sevenDay", "7d"]]
const isObj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v)

// quotaMe answers a plan list: {quota: {fiveHour|sevenDay: {usedCredits, limitCredits, resetAt (ISO)}}}.
export function parseQuotaMe(plans: unknown): DeepseekUsage {
  const rows: NonNullable<DeepseekUsage["rows"]> = []
  for (const plan of Array.isArray(plans) ? plans : []) {
    const p = isObj(plan) ? plan : {}
    const quota = isObj(p.quota) ? p.quota : {}
    for (const [key, window] of WINDOWS) {
      const win = quota[key]
      const w = isObj(win) ? win : {}
      const at = typeof w.resetAt === "string" ? Date.parse(w.resetAt) / 1000 : NaN
      rows.push({ plan: typeof p.planName === "string" && p.planName ? p.planName : "plan", window, used: finite(w.usedCredits) ? w.usedCredits : null, limit: finite(w.limitCredits) ? w.limitCredits : null, resets_at: Number.isFinite(at) ? at : null })
    }
  }
  return { rows }
}

const apiAnythingEnv = () => ({ API_ANYTHING_HOME: `${HOME}/.local/state/crewship/api-anything`, API_ANYTHING_BROWSER_ROOTS: "[]", ...process.env })

async function apiAnything(args: string[]): Promise<{ out: string; code: number }> {
  const p = Bun.spawn(["api-anything", ...args], { stdout: "pipe", stderr: "ignore", stdin: "ignore", env: apiAnythingEnv(), signal: AbortSignal.timeout(90_000) })
  const [out, code] = await Promise.all([new Response(p.stdout).text(), p.exited])
  return { out, code }
}

export class AuthExpired extends Error {}

async function callQuotaMe(): Promise<unknown> {
  let answer: unknown
  try {
    answer = JSON.parse((await apiAnything(["call", "deepseekv4pro.com", "quotaMe"])).out.trim().split("\n").pop() ?? "")
  } catch {
    throw new Error("no answer from api-anything")
  }
  if (!isObj(answer)) throw new Error("bad answer from api-anything")
  if (answer.class === "auth") throw new AuthExpired("auth")
  if (!answer.ok) throw new Error(String(answer.class ?? "call failed"))
  return answer.data
}

// The site's session JWT lives 60 s. Mint a new one from the long-lived Clerk client cookie in the fleet jar and
// save the jar's deepseekv4pro cookies as api-anything's login. Cookie values stay in locals and a 0600 temp file.
async function refreshSession(): Promise<void> {
  let cookies: { name: string; value: string; domain?: string }[]
  let jwt: string
  try {
    const jar = JSON.parse(await Bun.file(`${HOME}/.fleet-browser/cookies.json`).text())
    cookies = Object.values(jar as Record<string, { name: string; value: string; domain?: string }>).filter(c => String(c?.domain ?? "").includes("deepseekv4pro.com"))
    const sid = cookies.find(c => c.name === "clerk_active_context")!.value.split(":")[0]
    const cookie = cookies.filter(c => String(c.domain).includes("clerk") || c.name.startsWith("__client")).map(c => `${c.name}=${c.value}`).join("; ")
    const res = await fetch(`https://clerk.deepseekv4pro.com/v1/client/sessions/${sid}/tokens?__clerk_api_version=2026-08-20`, {
      method: "POST",
      headers: { Cookie: cookie, Origin: "https://deepseekv4pro.com", "User-Agent": "Mozilla/5.0" },
      signal: AbortSignal.timeout(20_000),
    })
    if (!res.ok) throw new Error("clerk")
    jwt = ((await res.json()) as { jwt: string }).jwt
    if (typeof jwt !== "string") throw new Error("clerk")
  } catch {
    throw new Error("signed out: sign in through Dia and sync the fleet jar")
  }
  for (const c of cookies) if (c.name.startsWith("__session")) c.value = jwt
  const dir = mkdtempSync(join(tmpdir(), "usage-tui-ds-"))
  try {
    const file = join(dir, "cookies.json")
    writeFileSync(file, JSON.stringify({ cookies }), { mode: 0o600 })
    if ((await apiAnything(["login", "deepseekv4pro.com", "--cookies", file])).code !== 0) throw new Error("login save failed")
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

// `call` and `refresh` are injectable so tests run without network or login.
export async function readQuotaMe(call: () => Promise<unknown> = callQuotaMe, refresh: () => Promise<void> = refreshSession): Promise<{ value?: DeepseekUsage; error?: string }> {
  try {
    try {
      return { value: parseQuotaMe(await call()) }
    } catch (e) {
      if (!(e instanceof AuthExpired)) throw e
      await refresh()
      return { value: parseQuotaMe(await call()) }
    }
  } catch (e) {
    return { error: e instanceof AuthExpired ? "auth expired" : (e as Error).message }
  }
}

// Any result holds for 10 minutes, so a slow or failing call is not repeated every refresh.
export async function deepseek(): Promise<{ value?: DeepseekUsage; error?: string }> {
  if (deepseekAt && Date.now() - deepseekAt < DEEPSEEK_MIN_MS) return deepseekLast
  deepseekAt = Date.now()
  return (deepseekLast = await readQuotaMe())
}

export async function loadQuota(): Promise<QuotaInput> {
  const msg = (e: unknown) => (e as Error).message
  const [omp, zai, mercury, ds] = await Promise.allSettled([run(["omp", "usage", "--json"]).then(t => JSON.parse(t) as OmpUsage), fetchZai(), mercuryTokens().then(t => ({ keyIds: mercuryKeyIds(), tokens: t })), deepseek()])
  return {
    omp: omp.status === "fulfilled" ? omp.value : undefined,
    ompError: omp.status === "rejected" ? msg(omp.reason) : undefined,
    zai: zai.status === "fulfilled" ? zai.value : undefined,
    zaiError: zai.status === "rejected" ? `unavailable: ${msg(zai.reason)}` : undefined,
    mercury: mercury.status === "fulfilled" ? mercury.value : undefined,
    mercuryError: mercury.status === "rejected" ? msg(mercury.reason) : undefined,
    deepseek: ds.status === "fulfilled" ? ds.value.value : undefined,
    deepseekError: ds.status === "rejected" ? msg(ds.reason) : ds.value.error,
  }
}
