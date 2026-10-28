import { afterAll, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, utimesSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { deskSnapshot, latencyStats, loadDesk, parseLog, replyLatencies, retryCounts } from "./desk.ts"

const dirs: string[] = []
afterAll(() => dirs.forEach(d => rmSync(d, { recursive: true, force: true })))
const NOW = Date.parse("2026-10-28T12:00:00Z")
const iso = (secAgo: number) => new Date(NOW - secAgo * 1000).toISOString()

test("reply latency pairs inbox-accepted with the first later response-confirmed per message and skips older replies", () => {
  const log = parseLog([
    `${iso(500)} a inbox-accepted`, `${iso(498)} a typing-start`, `${iso(490)} a response-confirmed`, `${iso(480)} a response-confirmed`, // second bubble: not counted
    `${iso(100)} b inbox-accepted`, `${iso(70)} b response-confirmed`,
    `${iso(60)} c response-confirmed`, // no inbox-accepted: not a desk turn
    `${iso(50)} d inbox-accepted`, // unanswered
    "garbage line", `${iso(40)} 2026 skip (line stopped)`,
    `${iso(200000)} e inbox-accepted`, `${iso(199990)} e response-confirmed`, // before the 24 h window
  ].join("\n"))
  expect(log).toHaveLength(11)
  expect(replyLatencies(log, NOW - 86_400_000)).toEqual([10, 30])
})

test("median and p95 use nearest rank; an empty list has none", () => {
  expect(latencyStats([5, 1, 3, 2, 4, 100, 7, 8, 9, 6])).toEqual({ n: 10, last: 6, median: 5, p95: 100 })
  expect(latencyStats([])).toEqual({ n: 0, last: undefined, median: undefined, p95: undefined })
})

test("retry counts keep the highest try per outbox item and ignore other queues", () => {
  const j = "fm-imessage: outbox item 7 failed (try 1), next try in 0.7 s: X\nfm-imessage: outbox item 7 failed (try 3), next\nfm-imessage: attachment download 7 failed (try 9), next\nfm-imessage: outbox item 8 failed (try 2), next"
  expect([...retryCounts(j)]).toEqual([[7, 3], [8, 2]])
})

// Folders as the bridge lays them out: outbox/<seq>.json, outbox-dead/<buried ms>-<seq>.json.
function state(): string {
  const dir = mkdtempSync(join(tmpdir(), "cbdesk-"))
  dirs.push(dir)
  for (const f of ["outbox", "outbox-dead"]) mkdirSync(join(dir, f))
  const put = (path: string, secAgo: number) => {
    writeFileSync(join(dir, path), "{}")
    utimesSync(join(dir, path), (NOW - secAgo * 1000) / 1000, (NOW - secAgo * 1000) / 1000)
  }
  put("outbox/10.json", 400); put("outbox/11.json", 30); put("outbox/12.json.tmp", 900) // a temp file is not an item
  put("outbox-dead/" + `${NOW - 7200_000}-5.json`, 0); put("outbox-dead/" + `${NOW - 200_000_000}-4.json`, 0)
  writeFileSync(join(dir, "desk.log"), `${iso(200000)} z transport-accepted\n${iso(100)} a inbox-accepted\n${iso(80)} a transport-accepted\n${iso(70)} a response-confirmed\n${iso(20)} b typing-start\n`)
  return dir
}

test("loadDesk counts pending, sent and failed bubbles, ages and retries from the folders", () => {
  const d = loadDesk(state(), NOW, { unit: "active", journal: "outbox item 10 failed (try 4), next" })
  expect(d).toMatchObject({ unit: "active", pending: 2, oldestPendingMs: NOW - 400_000, retries: 4, retrying: 1, sent24h: 1, lastSentMs: NOW - 80_000, dead24h: 1, deadTotal: 2, lastLogMs: NOW - 20_000 })
  expect(d.latency).toEqual({ n: 1, last: 30, median: 30, p95: 30 })
})

test("snapshot shows bridge down and an unreadable journal, and an empty state shows zeros", () => {
  const empty = mkdtempSync(join(tmpdir(), "cbdesk-"))
  dirs.push(empty)
  const out = deskSnapshot(loadDesk(empty, NOW, { unit: "inactive", journal: null }), NOW).split("\n")
  expect(out[0].trim()).toBe("○ bridge down (inactive)   last desk log never")
  expect(out.find(l => l.includes("retries"))).toMatch(/journal unreadable/)
  expect(out.find(l => l.includes("oldest pending"))).toMatch(/none/)
  expect(out.find(l => l.includes("desk reply"))).toMatch(/0 replies +last – +median – +p95 –/)
})
