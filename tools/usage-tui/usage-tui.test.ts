import { expect, test } from "bun:test"
import { mkdtempSync, readFileSync, writeFileSync, chmodSync, existsSync, rmSync, watch, type FSWatcher } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"

// Runs the real TUI with stub `setsid` and `omp` on PATH. The stubs only log their argv.
// Proves the stats sync spawns through `setsid -f`, so the child leaves the pane's process group.
test("stats sync spawns omp through setsid -f", async () => {
  const dir = mkdtempSync(join(tmpdir(), "usage-tui-"))
  const log = join(dir, "calls.log")
  const stub = `#!/bin/sh\necho "\${0##*/} $*" >> "${log}"\n`
  for (const name of ["setsid", "omp"]) {
    writeFileSync(join(dir, name), stub)
    chmodSync(join(dir, name), 0o755)
  }

  const tui = Bun.spawn(["bun", join(import.meta.dir, "usage-tui.ts")], {
    env: { ...process.env, PATH: `${dir}:${process.env.PATH}`, HOME: dir },
    stdin: "ignore",
    stdout: "ignore",
    stderr: "ignore",
  })

  // Integration test: wait for the stub's log write as a filesystem event, not a delay.
  const { promise, resolve } = Promise.withResolvers<void>()
  const onChange = () => {
    if (existsSync(log) && readFileSync(log, "utf8").includes("\n")) resolve()
  }
  let watcher: FSWatcher | undefined
  try {
    watcher = watch(dir, onChange)
    onChange()
    await promise
    const calls = readFileSync(log, "utf8").trim().split("\n")
    expect(calls[0]).toBe("setsid -f omp stats --summary")
  } finally {
    watcher?.close()
    tui.kill()
    await tui.exited
    rmSync(dir, { recursive: true, force: true })
  }
}, 15_000)
