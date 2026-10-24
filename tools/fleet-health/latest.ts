// Latest published version per component. One request per component, cached on disk.
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { HOME, type Component, type Source } from "./components.ts"

export const CACHE_MS = 30 * 60_000 // unauthenticated GitHub allows 60 requests/hour; ~21 are GitHub
const CACHE_DIR = `${process.env.XDG_CACHE_HOME ?? `${HOME}/.cache`}/fleet-health`
const CACHE_FILE = `${CACHE_DIR}/latest.json`
const RETRY_MS = 5 * 60_000
const GAP_MS = 300

export type Latest = { version: string | null; at: number; error?: string }
export type Cache = Record<string, Latest>

export const loadCache = (): Cache => {
  try {
    return existsSync(CACHE_FILE) ? JSON.parse(readFileSync(CACHE_FILE, "utf8")) : {}
  } catch {
    return {}
  }
}

const getJson = async (url: string) => {
  const response = await fetch(url, { headers: { "user-agent": "crewship-fleet-health", accept: "application/json" }, signal: AbortSignal.timeout(15_000) })
  if (!response.ok) throw new Error(`HTTP ${response.status} ${new URL(url).host}`)
  return response.json() as Promise<any>
}
const parts = (v: string) => v.replace(/^\D+/, "").split(/[.-]/).map(n => parseInt(n, 10) || 0)
export function compare(a: string, b: string) {
  const x = parts(a), y = parts(b)
  for (let i = 0; i < Math.max(x.length, y.length); i++) if ((x[i] ?? 0) !== (y[i] ?? 0)) return (x[i] ?? 0) - (y[i] ?? 0)
  return 0
}
const newest = (versions: string[]) => versions.reduce((a, b) => (compare(a, b) >= 0 ? a : b))

async function fetchLatest(source: Source): Promise<string | null> {
  switch (source.kind) {
    case "github": {
      const api = `https://api.github.com/repos/${source.repo}/releases`
      const release = source.prerelease ? (await getJson(`${api}?per_page=10`)).find((r: any) => !r.draft) : await getJson(`${api}/latest`)
      return release ? String(release.tag_name).slice((source.prefix ?? "").length) : null
    }
    case "npm":
      return (await getJson(`https://registry.npmjs.org/${source.pkg}/latest`)).version
    case "pypi":
      return (await getJson(`https://pypi.org/pypi/${source.pkg}/json`)).info.version
    case "node":
      return newest((await getJson("https://nodejs.org/dist/index.json")).map((r: any) => r.version)).replace(/^v/, "")
    case "rustup": {
      const toml = await (await fetch("https://static.rust-lang.org/rustup/release-stable.toml", { signal: AbortSignal.timeout(15_000) })).text()
      return toml.match(/^version = '([0-9.]+)'$/m)?.[1] ?? null
    }
    case "forgejo": {
      const releases = await getJson("https://codeberg.org/api/v1/repos/forgejo/forgejo/releases?draft=false&pre-release=false&limit=50")
      return newest(releases.map((r: any) => r.tag_name)).replace(/^v/, "")
    }
    case "none":
      return null
  }
}

// Fetches only entries older than CACHE_MS, one at a time; a failure keeps the old value and retries after RETRY_MS.
export async function refreshLatest(list: Component[], cache: Cache, onUpdate: () => void): Promise<void> {
  const now = Date.now()
  for (const c of list) {
    if (c.source.kind === "none") { cache[c.name] = { version: null, at: now }; continue }
    const hit = cache[c.name]
    if (hit && now - hit.at < (hit.error ? RETRY_MS : CACHE_MS)) continue
    try {
      cache[c.name] = { version: await fetchLatest(c.source), at: Date.now() }
    } catch (e) {
      cache[c.name] = { version: hit?.version ?? null, at: Date.now(), error: (e as Error).message }
    }
    onUpdate()
    await Bun.sleep(GAP_MS)
  }
  mkdirSync(CACHE_DIR, { recursive: true })
  writeFileSync(CACHE_FILE, JSON.stringify(cache))
}
