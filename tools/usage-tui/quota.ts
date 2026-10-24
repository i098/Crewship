// Remaining-quota rows for usage-tui: parsing, percent-left maths, colors, reset formatting, loaders.
// Sources: `omp usage --json` (Claude, Codex), the Z.ai quota endpoint, omp session files (Mercury per key).
// Accounts are labelled by position ("claude 2", "mercury key 1"), never by email, id or key text.
import { Database } from "bun:sqlite"
import { theme } from "../tui-theme/theme.ts"

export const MERCURY_LIMIT = 100_000_000
export const QUOTA_MIN_MS = 60_000

export type QuotaRow = {
  account: string
  window: string
  usedPct: number | null // null = the source did not report this window
  leftPct: number | null
  resetsAt: number | null
  note?: string // shown instead of the numbers, e.g. "no quota API"
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

// ---- DeepSeek: prepaid balance, read from the platform website ----------------
// DeepSeek has no quota API, and omp's only key is a reseller key that /user/balance refuses.
// The site shows a USD balance, so read the response the signed-in site itself requests.
export type DeepseekSummary = { normal_wallets?: { currency: string; balance: string }[] }

export function deepseekRow(json: DeepseekSummary): QuotaRow {
  const wallets = json.normal_wallets ?? []
  const w = wallets.find(w => w.currency === "USD") ?? wallets[0]
  const bal = w?.balance ? Number(w.balance) : NaN
  return { account: "deepseek", window: "-", usedPct: null, leftPct: null, resetsAt: null, note: finite(bal) ? `balance ${usd(bal)}` : "no balance reported" }
}

const usd = (v: number) => `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(Math.abs(v) < 0.01 && v !== 0 ? 4 : 2)}`

// ---- assembly ---------------------------------------------------------------
export type QuotaInput = {
  now?: number // fixtures pin the clock
  omp?: OmpUsage
  ompError?: string
  zai?: ZaiQuota
  zaiError?: string
  mercury?: { keyIds: number[]; tokens: Record<string, number> }
  mercuryError?: string
  deepseek?: DeepseekSummary
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
  if (inp.deepseek) rows.push(deepseekRow(inp.deepseek))
  else rows.push({ account: "deepseek", window: "-", usedPct: null, leftPct: null, resetsAt: null, note: inp.deepseekError ? `unavailable: ${inp.deepseekError}` : "not reported" })
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
      return `${acct.padEnd(15)}${r.window.padEnd(10)}${c.bar.padEnd(BAR_W + 2)}${c.left.padEnd(10)}${c.reset.padEnd(10)}${c.clock.padEnd(11)}${c.note}`.trimEnd()
    })
    .join("\n")
}

// ---- loaders ------------------------------------------------------------------
const HOME = process.env.HOME ?? ""
const SESSIONS = `${HOME}/.omp/agent/sessions`
const AGENT_DB = `${HOME}/.omp/agent/agent.db`

async function run(cmd: string[]): Promise<string> {
  const p = Bun.spawn(cmd, { stdout: "pipe", stderr: "ignore" })
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

// Reads the balance the signed-in Dia on the Mac loads: a background tab (never focused) replays the
// site's own request, and CDP hands back that response body, so no cookie or token ever leaves Dia.
const DEEPSEEK_CDP = String.raw`
import base64, json, os, socket, struct, sys, time, urllib.request
PORT, WANT = 9222, "/api/v0/users/get_user_summary"
def get(p):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}{p}", timeout=10))
def open_ws(url):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=20)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall(f"GET /{url.split('/', 3)[3]} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        c = s.recv(4096)
        if not c:
            raise OSError("handshake failed")
        buf += c
    return s
def send(s, text):
    data = text.encode()
    n = len(data)
    head = bytes([0x81, 0x80 | n]) if n < 126 else bytes([0x81, 0xFE]) + struct.pack(">H", n)
    mask = os.urandom(4)
    s.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))
def read(s, n):
    out = b""
    while len(out) < n:
        c = s.recv(n - len(out))
        if not c:
            raise EOFError("connection closed")
        out += c
    return out
def recv(s):
    while True:
        b1, b2 = read(s, 2)
        n = b2 & 0x7F
        if n == 126:
            n = struct.unpack(">H", read(s, 2))[0]
        elif n == 127:
            n = struct.unpack(">Q", read(s, 8))[0]
        payload = read(s, n)
        if b1 & 0x0F in (1, 2):
            return payload.decode()
def call(s, i, method, params):
    send(s, json.dumps({"id": i, "method": method, "params": params}))
    while True:
        m = json.loads(recv(s))
        if m.get("id") == i:
            return m
def main():
    browser = open_ws(get("/json/version")["webSocketDebuggerUrl"])
    target = call(browser, 1, "Target.createTarget", {"url": "https://platform.deepseek.com/usage", "background": True})["result"]["targetId"]
    try:
        deadline, page = time.time() + 20, None
        while time.time() < deadline and not page:
            page = next((p["webSocketDebuggerUrl"] for p in get("/json/list") if p.get("id") == target and p.get("type") == "page"), None)
            if not page:
                time.sleep(0.3)
        if not page:
            raise OSError("page target did not appear")
        ws = open_ws(page)
        call(ws, 2, "Network.enable", {})
        call(ws, 3, "Page.enable", {})
        call(ws, 4, "Page.reload", {})
        while time.time() < deadline:
            m = json.loads(recv(ws))
            if m.get("method") == "Network.responseReceived" and WANT in m["params"]["response"]["url"]:
                body = call(ws, 5, "Network.getResponseBody", {"requestId": m["params"]["requestId"]})["result"]["body"]
                return json.loads(body)["data"]["biz_data"]
        raise OSError("balance request not seen")
    finally:
        call(browser, 6, "Target.closeTarget", {"targetId": target})
try:
    biz = main()
    print(json.dumps({"normal_wallets": biz.get("normal_wallets")}))
except Exception as e:
    print(f"deepseek: {e}", file=sys.stderr)
    sys.exit(1)
`

const DEEPSEEK_MIN_MS = 10 * 60_000
let deepseekAt = 0
let deepseekLast: { value?: DeepseekSummary; error?: string } = {}

async function fetchDeepseek(): Promise<DeepseekSummary> {
  const p = Bun.spawn(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "mac", "python3", "-"], {
    stdin: new Blob([DEEPSEEK_CDP]),
    stdout: "pipe",
    stderr: "pipe",
    signal: AbortSignal.timeout(40_000),
  })
  const [out, err] = await Promise.all([new Response(p.stdout).text(), new Response(p.stderr).text()])
  if ((await p.exited) !== 0) throw new Error(err.trim().split("\n").pop() || "CDP read failed")
  return JSON.parse(out) as DeepseekSummary
}

// A read costs a background tab in the owner's browser, so a success holds for 10 minutes; a failure retries next minute.
async function deepseek(): Promise<{ value?: DeepseekSummary; error?: string }> {
  if (deepseekAt && Date.now() - deepseekAt < (deepseekLast.error ? QUOTA_MIN_MS : DEEPSEEK_MIN_MS)) return deepseekLast
  deepseekAt = Date.now()
  try {
    return (deepseekLast = { value: await fetchDeepseek() })
  } catch (e) {
    return (deepseekLast = { error: (e as Error).message })
  }
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
