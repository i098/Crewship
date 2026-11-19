import { expect, test } from "bun:test"
import { chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { claim, notice } from "./use-notice.ts"

test("notice names the browser, the purpose and every browser's tab count", () => {
  const t = notice("chrome", "builder-three", "capture the pricing page", { obscura: 2, chrome: 1, voxl: null, dia: 7 })
  expect(t).toBe("Browser: builder-three started using chrome (headless Chrome). Purpose: capture the pricing page. Open tabs: obscura 2, chrome 1, voxl off, Dia 7.")
})

test("a repeat for the same browser and agent inside the window sends nothing", () => {
  const dir = mkdtempSync(join(tmpdir(), "bun-"))
  expect(claim(dir, "voxl", "a", 100000, 30)).toBe(true)
  expect(claim(dir, "voxl", "a", 100000 + 600, 30)).toBe(false)
  expect(claim(dir, "voxl", "b", 100000 + 600, 30)).toBe(true)
  expect(claim(dir, "chrome", "a", 100000 + 600, 30)).toBe(true)
  expect(claim(dir, "voxl", "a", 100000 + 1801, 30)).toBe(true)
})

function run(send: string, dir: string, extra: Record<string, string> = {}) {
  return Bun.spawnSync(["bun", join(import.meta.dir, "use-notice.ts"), "obscura"], {
    env: { ...process.env, FLEET_BROWSER_STATE: dir, FLEET_BROWSER_SEND: send, FLEET_BROWSER_AGENT: "t", DIA_COOKIES_HOST: "invalid.invalid", ...extra },
  })
}

test("first use sends one notice, an immediate repeat sends none, a failing sender does not fail the start", () => {
  const dir = mkdtempSync(join(tmpdir(), "bun-"))
  const out = join(dir, "out")
  const send = join(dir, "send")
  writeFileSync(send, `#!/bin/sh\ncat >> ${out}\n`)
  chmodSync(send, 0o755)
  expect(run(send, dir).exitCode).toBe(0)
  expect(run(send, dir).exitCode).toBe(0)
  expect(readFileSync(out, "utf8").match(/Browser: t started using obscura/g)?.length).toBe(1)
  expect(run("false", mkdtempSync(join(tmpdir(), "bun-"))).exitCode).toBe(0)
})

test("the chrome-devtools-axi wrapper texts once for the session tier, then runs the real client with its arguments", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bun-"))
  const bin = join(dir, "bin")
  mkdirSync(bin)
  const out = join(dir, "out")
  const ran = join(dir, "ran")
  const script = (name: string, body: string) => {
    writeFileSync(join(bin, name), `#!/bin/sh\n${body}\n`)
    chmodSync(join(bin, name), 0o755)
  }
  script("chrome-devtools-axi", `echo "$@" > ${ran}`)
  script("ssh", "exit 1")
  script("send", `cat >> ${out}`)
  const env = {
    ...process.env, HOME: dir, BUN: process.execPath, PATH: `${join(import.meta.dir)}:${bin}:${process.env.PATH}`,
    FLEET_BROWSER_SEND: join(bin, "send"), FLEET_BROWSER_AGENT: "w", FLEET_BROWSER_PURPOSE: "check pricing", FLEET_BROWSER_TIER: "chrome",
  }
  for (let i = 0; i < 2; i++) expect(Bun.spawnSync(["chrome-devtools-axi", "open", "x"], { env }).exitCode).toBe(0)
  for (let i = 0; i < 100 && !existsSync(out); i++) await Bun.sleep(100)
  await Bun.sleep(300)
  expect(readFileSync(ran, "utf8")).toBe("open x\n")
  expect(readFileSync(out, "utf8").match(/Browser: w started using chrome \(headless Chrome\)\. Purpose: check pricing\./g)?.length).toBe(1)
})

test("concurrent first uses by one agent on one browser send exactly one text", async () => {
  const dir = mkdtempSync(join(tmpdir(), "bun-"))
  const out = join(dir, "out")
  const send = join(dir, "send")
  writeFileSync(send, `#!/bin/sh\ncat >> ${out}\n`)
  chmodSync(send, 0o755)
  const env = { ...process.env, FLEET_BROWSER_STATE: dir, FLEET_BROWSER_SEND: send, FLEET_BROWSER_AGENT: "t", DIA_COOKIES_HOST: "invalid.invalid" }
  const procs = Array.from({ length: 8 }, () => Bun.spawn(["bun", join(import.meta.dir, "use-notice.ts"), "obscura"], { env }))
  await Promise.all(procs.map(p => p.exited))
  expect(readFileSync(out, "utf8").match(/Browser: t started using obscura/g)?.length).toBe(1)
})
