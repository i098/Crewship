import { afterAll, expect, test } from "bun:test"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { loadQueue, parseRec, queueRows } from "./queue.ts"

const dirs: string[] = []
afterAll(() => dirs.forEach(d => rmSync(d, { recursive: true, force: true })))
const NOW = Math.floor(Date.now() / 1000) // the --once run reads the real clock

// Record lines as fm-decision-queue.sh writes them (dq_enqueue, then dq_set appends or rewrites fields).
const rec = (origin: string, key: string, extra: string) =>
  `origin=${origin}\nkey=${key}\nverb=needs-decision\nnote=pick a=b or c\nenqueued_at=${NOW - 600}\n${extra}`

// Two homes laid out like ~/.treehouse/firstmate-x/<n>/firstmate, so each is named "firstmate-x/<n>".
function homes(): string[] {
  const root = mkdtempSync(join(tmpdir(), "cbqueue-"))
  dirs.push(root)
  const files: Record<string, Record<string, string>> = {
    "1": {
      "sm-a+k1.rec": rec("sm-a", "k1", "state=queued\nattempts=0\n"),
      "sm-a+k2.rec": rec("sm-a", "k2", "state=dispatched\nattempts=1\ncrewmate=dq-d1\n"),
      "cm+k3.rec": rec("cm", "k3", `state=closed\nattempts=1\nclosed_at=${NOW - 60}\nclose_reason=answered\n`),
      "cm+k4.rec": rec("cm", "k4", "state=closed\nattempts=0\nclose_reason=stale\n"),
      ".rec.Ab12Cd": rec("cm", "tmp", "state=queued\n"), // dq_set's temp file, mid-write
      "x+bad.rec": rec("x", "bad", "state=weird\n"),
    },
    "2": { "sm-b+k5.rec": rec("sm-b", "k5", "state=stuck\nattempts=3\n") },
    "3": {}, // queue never enabled: no decision-queue dir
  }
  return Object.entries(files).map(([n, recs]) => {
    const home = join(root, "firstmate-x", n, "firstmate")
    const dir = join(home, "state", ...(Object.keys(recs).length ? ["decision-queue"] : []))
    mkdirSync(dir, { recursive: true })
    for (const [f, body] of Object.entries(recs)) writeFileSync(join(dir, f), body)
    return home
  })
}

test("record states map to open, in progress, answered, closed, stuck; the first value of a field wins", () => {
  const states = ["queued", "dispatched", "closed\nclose_reason=answered", "closed\nclose_reason=stale", "stuck"]
    .map(s => parseRec(`origin=o\nkey=k\nstate=${s}\nenqueued_at=5`, "m")!.state)
  expect(states).toEqual(["open", "in progress", "answered", "closed", "stuck"])
  expect(parseRec("state=queued\nstate=closed\nnote=a=b", "m")).toMatchObject({ state: "open", note: "a=b" })
  expect(parseRec("state=weird", "m")).toBeNull()
  expect(parseRec(`state=closed\nenqueued_at=5\nclosed_at=9`, "m")!.since).toBe(9)
})

test("per-mate counts and rows skip temp files, unknown states and homes without a queue", () => {
  const rows = queueRows(loadQueue(homes()))
  const heads = rows.filter(r => r.kind === "mate")
  expect(heads.map(h => [h.mate, h.n])).toEqual([
    ["firstmate-x/1", { open: 1, "in progress": 1, answered: 1, closed: 1, stuck: 0 }],
    ["firstmate-x/2", { open: 0, "in progress": 0, answered: 0, closed: 0, stuck: 1 }],
  ])
  expect(rows.map(r => (r.kind === "rec" ? `${r.rec.origin}+${r.rec.key}` : r.mate)))
    .toEqual(["firstmate-x/1", "sm-a+k1", "sm-a+k2", "cm+k3", "cm+k4", "firstmate-x/2", "sm-b+k5"])
})

test("--once --queue prints the snapshot without starting the TUI", async () => {
  const p = Bun.spawn(["bun", join(import.meta.dir, "crewboard-tui.ts"), "--once", "--queue", "--width", "120", ...homes()], { stdout: "pipe" })
  const out = await new Response(p.stdout).text()
  expect(await p.exited).toBe(0)
  const lines = out.trimEnd().split("\n")
  expect(lines[0].trim()).toBe("1 open   1 in progress   1 answered   1 closed   1 stuck")
  expect(lines.find(l => l.includes("sm-b · k5"))).toMatch(/⚠ stuck\s+sm-b · k5 {2}pick a=b or c\s+10m$/)
})
