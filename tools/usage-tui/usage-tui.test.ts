import { expect, test } from "bun:test"
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, rmSync, watch, type FSWatcher } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

// Runs the real TUI with the real `setsid` and a stub `omp` that records its args, pgid and sid.
// Oracle: `ps` on the TUI pid. The stats-sync omp child must be in a different process group and session.
test("stats sync runs omp outside the TUI's process group and session", async () => {
  const dir = mkdtempSync(join(tmpdir(), "usage-tui-"))
  const log = join(dir, "calls.log")
  writeFileSync(join(dir, "omp"), `#!/bin/sh\necho "$* $(ps -o pgid=,sid= -p $$)" >> "${log}"\n`)
  chmodSync(join(dir, "omp"), 0o755)

  const tui = Bun.spawn(["bun", join(import.meta.dir, "usage-tui.ts")], {
    env: { ...process.env, PATH: `${dir}:${process.env.PATH}`, HOME: dir },
    stdin: "ignore",
    stdout: "ignore",
    stderr: "ignore",
  })

  // Integration test: wait for the stub's log write as a filesystem event, not a delay.
  const { promise, resolve } = Promise.withResolvers<void>()
  const onChange = () => {
    // Only the stats sync uses setsid; the usage read shares the TUI's group, so wait for its own line.
    if (existsSync(log) && readFileSync(log, "utf8").split("\n").some(l => l.startsWith("stats "))) resolve()
  }
  let watcher: FSWatcher | undefined
  try {
    watcher = watch(dir, onChange)
    onChange()
    await promise
    const child = readFileSync(log, "utf8").split("\n").find(l => l.startsWith("stats "))!.split(/\s+/).slice(-2)
    const parent = Bun.spawnSync(["ps", "-o", "pgid=,sid=", "-p", String(tui.pid)]).stdout.toString().trim().split(/\s+/)
    expect(parent).toHaveLength(2)
    expect(child).toHaveLength(2)
    expect(child[0]).not.toBe(parent[0])
    expect(child[1]).not.toBe(parent[1])
  } finally {
    watcher?.close()
    tui.kill()
    await tui.exited
    rmSync(dir, { recursive: true, force: true })
  }
}, 60_000)
