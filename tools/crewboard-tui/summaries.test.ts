import { expect, test } from "bun:test"
import { chmodSync, mkdtempSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { fetchSummaries } from "./summaries.ts"

// A fake `crewboard` that prints `reply` and exits with `code`.
function fake(reply: string, code = 0) {
  const path = join(mkdtempSync(join(tmpdir(), "cbtui-")), "crewboard")
  writeFileSync(path, `#!/bin/sh\n[ "$*" = "topics --summary --json" ] || exit 9\ncat <<'EOF'\n${reply}\nEOF\nexit ${code}\n`)
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
