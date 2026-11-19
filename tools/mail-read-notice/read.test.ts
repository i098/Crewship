import { expect, test } from "bun:test"
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { clean, isMessageRead, notice } from "./read.ts"

const msg = (from: string, subject: string) => JSON.stringify({ snippet: "code 482913", payload: { headers: [{ name: "From", value: from }, { name: "Subject", value: subject }] } })

test("notice names agent, sender and purpose, and never the subject, code or a link", () => {
  const t = notice(msg("Acme <no-reply@acme.com>", "Your code is KQZPLM https://acme.com/v?t=abc"), "builder-three", "finish the Acme sign-in")
  expect(t).toContain("builder-three")
  expect(t).toContain("Acme <no-reply@acme.com>")
  expect(t).toContain("finish the Acme sign-in")
  expect(t).not.toMatch(/KQZPLM|\d|https?:|acme\.com\/v/)
})

test("a read with no purpose says so", () => {
  expect(notice(msg("a@b.co", "hi"), "x", "")).toContain("Purpose: not given.")
})

test("every Gmail call that returns mail content counts as a read", () => {
  const g = (...a: string[]) => isMessageRead(["gmail", "users", ...a, "--params", "{}"])
  for (const c of [["messages", "get"], ["messages", "list"], ["threads", "get"], ["threads", "list"], ["messages", "attachments", "get"]]) expect(g(...c)).toBe(true)
  expect(g("getProfile")).toBe(false)
  expect(g("messages", "send")).toBe(false)
})

test("a thread read takes the sender from its first message", () => {
  const t = JSON.stringify({ messages: [{ payload: { headers: [{ name: "From", value: "a@b.co" }] } }] })
  expect(notice(t, "x", "y")).toContain("from a@b.co")
})

test("long subjects are cut", () => {
  expect(clean("a ".repeat(100)).length).toBeLessThan(90)
})

function run(send: string) {
  const dir = mkdtempSync(join(tmpdir(), "mrn-"))
  const gws = join(dir, "gws")
  writeFileSync(gws, `#!/bin/sh\necho '${msg("a@b.co", "hi")}'\n`)
  chmodSync(gws, 0o755)
  return Bun.spawnSync(["bun", join(import.meta.dir, "read.ts"), "gmail", "users", "messages", "get"], {
    env: { ...process.env, PATH: `${dir}:${process.env.PATH}`, MAIL_READ_SEND: send, MAIL_READ_AGENT: "t" },
  })
}

test("a failing send does not fail or change the read", () => {
  const r = run("false")
  expect(r.exitCode).toBe(0)
  expect(r.stdout.toString()).toContain("payload")
})

test("the send command receives the notice on stdin", () => {
  const dir = mkdtempSync(join(tmpdir(), "mrn-"))
  const out = join(dir, "out")
  const send = join(dir, "send")
  writeFileSync(send, `#!/bin/sh\ncat > ${out}\n`)
  chmodSync(send, 0o755)
  expect(run(send).exitCode).toBe(0)
  expect(readFileSync(out, "utf8")).toContain("Mail read: t read mail from a@b.co")
})
