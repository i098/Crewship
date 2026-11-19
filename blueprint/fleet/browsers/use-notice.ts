#!/usr/bin/env bun
// Texts the owner once when an agent starts using a browser: which one, what for, and the open tabs in each.
// Usage: use-notice.ts <obscura|chrome|voxl|dia>
// Env: FLEET_BROWSER_AGENT, FLEET_BROWSER_PURPOSE, FLEET_BROWSER_SEND (default `fm-imessage`, text on stdin),
//      FLEET_BROWSER_NOTICE_WINDOW_MIN (default 30), FLEET_BROWSER_STATE (default ~/.fleet-browser), DIA_COOKIES_HOST (default mac).
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { join } from "node:path"

export type Tier = "obscura" | "chrome" | "voxl" | "dia"
export type Counts = Record<Tier, number | null> // null: not running or not reachable
export const TIERS: Tier[] = ["obscura", "chrome", "voxl", "dia"]
const PORT = { obscura: 9222, chrome: 9522, voxl: 9523 }
const KIND: Record<Tier, string> = { obscura: "headless", chrome: "headless Chrome", voxl: "headed Chrome", dia: "your Mac" }
const MAX = 80

export const clean = (s: string) => {
  const t = s.replace(/\s+/g, " ").trim()
  return t.length > MAX ? `${t.slice(0, MAX)}...` : t
}

export function notice(tier: Tier, agent: string, purpose: string, counts: Counts): string {
  const tabs = TIERS.map(t => `${t === "dia" ? "Dia" : t} ${counts[t] ?? "off"}`).join(", ")
  return `Browser: ${clean(agent) || "an agent"} started using ${tier === "dia" ? "Dia" : tier} (${KIND[tier]}). Purpose: ${clean(purpose) || "not given"}. Open tabs: ${tabs}.`
}

// True once per (tier, agent) inside the window; records the send time before the text goes out.
export function claim(stateDir: string, tier: Tier, agent: string, now: number, windowMin: number): boolean {
  const file = join(stateDir, `notice-${tier}-${agent.replace(/[^\w.-]/g, "_") || "agent"}`)
  const last = existsSync(file) ? Number(readFileSync(file, "utf8")) : 0
  if (now - last < windowMin * 60) return false
  mkdirSync(stateDir, { recursive: true })
  writeFileSync(file, String(now))
  return true
}

const pages = (json: string) => (JSON.parse(json) as { type: string }[]).filter(t => t.type === "page").length

async function count(t: Tier): Promise<number | null> {
  try {
    if (t === "dia") {
      const p = Bun.spawn(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", process.env.DIA_COOKIES_HOST ?? "mac", "curl", "-s", "-m", "5", "http://127.0.0.1:9222/json/list"], { stdout: "pipe", stderr: "ignore" })
      const out = await new Response(p.stdout).text()
      return (await p.exited) === 0 ? pages(out) : null
    }
    const r = await fetch(`http://127.0.0.1:${PORT[t]}/json/list`, { signal: AbortSignal.timeout(3000) })
    return pages(await r.text())
  } catch {
    return null
  }
}

if (import.meta.main) {
  try {
    const tier = process.argv[2] as Tier
    const agent = process.env.FLEET_BROWSER_AGENT ?? ""
    const state = process.env.FLEET_BROWSER_STATE ?? join(homedir(), ".fleet-browser")
    const win = Number(process.env.FLEET_BROWSER_NOTICE_WINDOW_MIN ?? 30)
    if (TIERS.includes(tier) && claim(state, tier, agent, Math.floor(Date.now() / 1000), win)) {
      const c = await Promise.all(TIERS.map(count))
      const counts = Object.fromEntries(TIERS.map((t, i) => [t, c[i]])) as Counts
      const text = notice(tier, agent, process.env.FLEET_BROWSER_PURPOSE ?? "", counts)
      const cmd = (process.env.FLEET_BROWSER_SEND ?? "fm-imessage").split(" ")
      await Bun.spawn(["timeout", "15", ...cmd], { stdin: new Blob([text]), stdout: "ignore", stderr: "ignore" }).exited
    }
  } catch {} // a failed notice never blocks the browser start
}
