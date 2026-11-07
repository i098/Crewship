#!/usr/bin/env bun
// Usage notifier: texts one line when remaining quota crosses a 10% step down, and once per window when the burn rate accelerates.
// Reads the same rows as the Usage TUI (../usage-tui/quota.ts). Runs once and exits; a systemd timer triggers it (see README).
import { mkdirSync, readFileSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join } from "node:path"
import { buildRows, clockAt, loadQuota, type QuotaRow } from "../usage-tui/quota.ts"

const HOUR = 3_600_000
const DAY = 24 * HOUR
const MIN_SPAN = 2 * HOUR // shortest history before a 24h average means anything
const MIN_HOUR_USE = 2 // percentage points used in the last hour before "accelerating" is worth a text
const WINDOWS = ["5h", "7d"]

export type Sample = { t: number; used: number }
export type Entry = { step: number; resetsAt: number | null; fast: boolean; samples: Sample[] }
export type State = Record<string, Entry>

const stepOf = (left: number) => Math.ceil(left / 10) * 10

export function evaluate(state: State, rows: QuotaRow[], now: number, tz: string): { state: State; messages: string[] } {
  const next: State = {}
  const messages: string[] = []
  for (const r of rows) {
    if (!WINDOWS.includes(r.window) || r.leftPct == null || r.usedPct == null || r.note) continue
    const key = `${r.account}|${r.window}`
    const step = stepOf(r.leftPct)
    const prev = state[key]
    const reset = prev && (r.leftPct > 100 - (prev.samples.at(-1)?.used ?? 0) + 1 || (r.resetsAt != null && prev.resetsAt != null && r.resetsAt > prev.resetsAt + 60_000))
    let e: Entry = !prev || reset ? { step, resetsAt: r.resetsAt, fast: false, samples: [] } : { ...prev, resetsAt: r.resetsAt ?? prev.resetsAt }
    e.samples = [...e.samples, { t: now, used: r.usedPct }].filter(s => now - s.t <= DAY)
    const label = `${r.account} ${r.window}`
    const when = r.resetsAt ? `, resets ${clockAt(r.resetsAt, tz)}` : ""
    if (step < e.step) {
      messages.push(`Usage: ${label} is at ${Math.round(r.leftPct)}% left, at or below the ${step}% step${when}.`)
      e.step = step
    }
    if (!e.fast) {
      const first = e.samples[0]
      const hourAgo = [...e.samples].reverse().find(s => now - s.t >= HOUR)
      if (first && hourAgo && now - first.t >= MIN_SPAN) {
        const hourRate = (r.usedPct - hourAgo.used) / ((now - hourAgo.t) / HOUR)
        const avgRate = (r.usedPct - first.used) / ((now - first.t) / HOUR)
        if (hourRate >= MIN_HOUR_USE && avgRate > 0 && hourRate >= 2 * avgRate) {
          messages.push(`Usage: ${label} is burning fast, ${hourRate.toFixed(1)}% per hour against a 24h average of ${avgRate.toFixed(1)}% per hour, ${Math.round(r.leftPct)}% left${when}.`)
          e.fast = true
        }
      }
    }
    next[key] = e
  }
  return { state: next, messages }
}

async function send(cmd: string[], text: string) {
  const p = Bun.spawn(["timeout", "60", ...cmd], { stdin: new Blob([text]), stdout: "ignore", stderr: "inherit" })
  if ((await p.exited) !== 0) throw new Error(`send failed: ${cmd.join(" ")}`)
}

if (import.meta.main) {
  const statePath = process.env.USAGE_NOTIFY_STATE ?? join(homedir(), ".local/state/usage-notify/state.json")
  const sendCmd = (process.env.USAGE_NOTIFY_SEND ?? "fm-imessage").split(" ")
  const fx = process.argv.indexOf("--fixture")
  const input = fx > 0 ? JSON.parse(readFileSync(process.argv[fx + 1], "utf8")) : await loadQuota()
  let state: State = {}
  try { state = JSON.parse(readFileSync(statePath, "utf8")) } catch {}
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  const out = evaluate(state, buildRows(input), Date.now(), tz)
  // State is saved only after every text is sent, so a failed send is retried on the next run.
  for (const m of out.messages) await send(sendCmd, m)
  mkdirSync(dirname(statePath), { recursive: true })
  writeFileSync(statePath, JSON.stringify(out.state))
}
