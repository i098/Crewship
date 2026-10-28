import { afterAll, expect, test } from "bun:test"
import { chmodSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fetchReadSeqs, fetchSummaries, unreadCount } from "./summaries.ts"

const dirs: string[] = []
afterAll(() => dirs.forEach(d => rmSync(d, { recursive: true, force: true })))

// A fake `crewboard` that prints `reply` and exits with `code`.
function fake(reply: string, code = 0) {
  const dir = mkdtempSync(join(tmpdir(), "cbtui-"))
  dirs.push(dir)
  const path = join(dir, "crewboard")
  writeFileSync(path, `#!/bin/sh\n[ "$*" = "topics --summary --json" ] || [ "$*" = "topics --json" ] || exit 9\ncat <<'EOF'\n${reply}\nEOF\nexit ${code}\n`)
  chmodSync(path, 0o755)
  return path
}

test("maps topics to their non-empty summaries", async () => {
  const reply = JSON.stringify([
    { topic: "task/a", count: 2, summary: "Ana asks Bo for a review", summary_seq: 2 },
    { topic: "fleet", count: 1, summary: "", summary_seq: 0 },
    { topic: "old", count: 1 },
  ])
  expect(await fetchSummaries(fake(reply))).toEqual(new Map([["task/a", "Ana asks Bo for a review"]]))
})

test("an absent board, a failing command or bad output gives no summaries", async () => {
  expect((await fetchSummaries("/nonexistent/crewboard")).size).toBe(0)
  expect((await fetchSummaries(fake("[]", 3))).size).toBe(0)
  expect((await fetchSummaries(fake("not json"))).size).toBe(0)
})

test("unread counts the messages above the board's read_seq, which only agents move", async () => {
  const reply = JSON.stringify([{ topic: "task/a", read_seq: 2 }, { topic: "fleet", read_seq: 0 }, { topic: "old" }])
  const seqs = await fetchReadSeqs(fake(reply))
  expect(seqs).toEqual(new Map([["task/a", 2], ["fleet", 0]]))
  const msgs = [{ seq: 1 }, { seq: 2 }, { seq: 3 }, { seq: 5 }]
  expect(unreadCount(msgs, seqs.get("task/a"))).toBe(2)
  expect(unreadCount(msgs, seqs.get("fleet"))).toBe(4)
  // Not yet reported: no false unread.
  expect(unreadCount(msgs, seqs.get("old"))).toBe(0)
  expect((await fetchReadSeqs(fake("[]", 3))).size).toBe(0)
})
