import { expect, test } from "bun:test"
import { chmodSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs"
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
