#!/usr/bin/env bun
// Usage notifier: texts one line when remaining quota crosses a 10% step down, and once per window when the burn rate accelerates.
// Reads the same rows as the Usage TUI (../usage-tui/quota.ts). Reads only the snapshot the TUI writes; a systemd path unit runs it once per snapshot change (see README).
import { mkdirSync, readFileSync, statSync, writeFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, join } from "node:path"
import { buildRows, clockAt, type QuotaInput, type QuotaRow } from "../usage-tui/quota.ts"

const HOUR = 3_600_000
const DAY = 24 * HOUR
const MIN_SPAN = 2 * HOUR // shortest history before a 24h average means anything
const MIN_HOUR_USE = 2 // percentage points used in the last hour before "accelerating" is worth a text
const WINDOWS = ["5h", "7d"]

export type Sample = { t: number; used: number }
export type Entry = { step: number; resetsAt: number | null; fast: boolean; samples: Sample[] }
export type State = Record<string, Entry>

const stepOf = (left: number) => Math.ceil(left / 10) * 10

function isReset(prev: Entry | undefined, r: QuotaRow): boolean {
  if (!prev) return true
  const lastUsed = prev.samples.at(-1)?.used ?? 0
  const moved = r.resetsAt != null && prev.resetsAt != null && r.resetsAt > prev.resetsAt + 60_000
  return moved || r.leftPct! > 100 - lastUsed + 1
}

// Returns the acceleration text when the last hour's rate is at least 2x the average over the kept history.
function accelText(samples: Sample[], used: number, now: number, label: string, tail: string): string | null {
  const first = samples[0]
  const hourAgo = [...samples].reverse().find(s => now - s.t >= HOUR)
  if (!first || !hourAgo || now - first.t < MIN_SPAN) return null
  const hourRate = (used - hourAgo.used) / ((now - hourAgo.t) / HOUR)
  const avgRate = (used - first.used) / ((now - first.t) / HOUR)
  if (hourRate < MIN_HOUR_USE || avgRate <= 0 || hourRate < 2 * avgRate) return null
  return `Usage: ${label} is burning fast, ${hourRate.toFixed(1)}% per hour against a 24h average of ${avgRate.toFixed(1)}% per hour, ${tail}.`
}

function evaluateRow(prev: Entry | undefined, r: QuotaRow, now: number, tz: string): { entry: Entry; messages: string[] } {
  const left = r.leftPct!
  const step = stepOf(left)
  const base: Entry = isReset(prev, r) ? { step, resetsAt: r.resetsAt, fast: false, samples: [] } : { ...prev!, resetsAt: r.resetsAt ?? prev!.resetsAt }
  const e: Entry = { ...base, samples: [...base.samples, { t: now, used: r.usedPct! }].filter(s => now - s.t <= DAY) }
  const label = `${r.account} ${r.window}`
  const when = r.resetsAt ? `, resets ${clockAt(r.resetsAt, tz)}` : ""
  const messages: string[] = []
  if (step < e.step) {
    messages.push(`Usage: ${label} is at ${Math.round(left)}% left, at or below the ${step}% step${when}.`)
    e.step = step
  }
  const fast = e.fast ? null : accelText(e.samples, r.usedPct!, now, label, `${Math.round(left)}% left${when}`)
  if (fast) {
    messages.push(fast)
    e.fast = true
  }
  return { entry: e, messages }
}

export function evaluate(state: State, rows: QuotaRow[], now: number, tz: string): { state: State; messages: string[] } {
  const next: State = { ...state }
  const messages: string[] = []
  for (const r of rows) {
    if (!WINDOWS.includes(r.window) || r.leftPct == null || r.usedPct == null || r.note) continue
    const key = `${r.account}|${r.window}`
    const out = evaluateRow(state[key], r, now, tz)
    next[key] = out.entry
    messages.push(...out.messages)
  }
  return { state: next, messages }
}

export type Saved = { snap: string; windows: State }

export function processSnapshot(saved: Saved, snap: string, input: QuotaInput, now: number, tz: string): { saved: Saved; messages: string[] } | null {
  if (saved.snap === snap) return null
  const out = evaluate(saved.windows, buildRows(input), now, tz)
  return { saved: { snap, windows: out.state }, messages: out.messages }
}

async function send(cmd: string[], text: string) {
  const p = Bun.spawn(["timeout", "60", ...cmd], { stdin: new Blob([text]), stdout: "ignore", stderr: "inherit" })
  if ((await p.exited) !== 0) throw new Error(`send failed: ${cmd.join(" ")}`)
}

if (import.meta.main) {
  const statePath = process.env.USAGE_NOTIFY_STATE ?? join(homedir(), ".local/state/usage-notify/state.json")
  const sendCmd = (process.env.USAGE_NOTIFY_SEND ?? "fm-imessage").split(" ")
  const fx = process.argv.indexOf("--fixture")
  const snapPath = fx > 0 ? process.argv[fx + 1] : (process.env.USAGE_SNAPSHOT ?? join(homedir(), ".local/state/usage-tui/snapshot.json"))
  const st = statSync(snapPath)
  let saved: Saved = { snap: "", windows: {} }
  try { saved = JSON.parse(readFileSync(statePath, "utf8")) } catch {}
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  const out = processSnapshot(saved, `${st.mtimeMs}:${st.size}`, JSON.parse(readFileSync(snapPath, "utf8")), Date.now(), tz)
  if (out) {
    // State is saved only after every text is sent, so a failed send is retried on the next run.
    for (const m of out.messages) await send(sendCmd, m)
    mkdirSync(dirname(statePath), { recursive: true })
    writeFileSync(statePath, JSON.stringify(out.saved))
  }
}
