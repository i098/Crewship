// Disposable fixture: fake homes (tasks.txt + state/*.status) and a fake `tasks-axi` that prints tasks.txt. Used by tests and screenshots.
// Usage: bun fixture.ts <dir> [agents=40] [mates=4]   then: TASKS_AXI_BIN=<dir>/tasks-axi bun crewboard-tui.ts --tasks <dir>/home-*
import { chmodSync, mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"

const REPOS = ["harbor", "lantern", "quarry", "meadow", "compass", "ledger"]
const VERBS = ["Port the parser", "Trim the cache", "Fix the retry loop", "Add the export", "Cover the edge case", "Split the module", "Index the logs", "Tidy the config"]

export function writeFixture(dir: string, o: { agents: number; mates: number; now: number }): string[] {
  mkdirSync(dir, { recursive: true })
  const bin = join(dir, "tasks-axi")
  writeFileSync(bin, '#!/bin/sh\ncat "$PWD/tasks.txt"\n')
  chmodSync(bin, 0o755)
  const homes: string[] = []
  for (let m = 0; m < o.mates; m++) {
    const home = join(dir, `home-${String(m).padStart(2, "0")}`)
    mkdirSync(join(home, "state"), { recursive: true })
    const rows: string[] = []
    const per = Math.ceil(o.agents / o.mates)
    for (let i = 0; i < per; i++) {
      const n = m * per + i
      const repo = REPOS[n % REPOS.length]
      const id = `${repo.slice(0, 2)}-task-${n}`
      const title = `${VERBS[n % VERBS.length]} #${n}`
      rows.push(`  ${id},in_flight,ship,${repo},"${title}",no,-,-`)
      const quiet = n % 7 === 0 ? 3600 + (n % 5) * 1800 : (n % 11) * 60 // every 7th agent has gone quiet for 1h+
      const at = o.now - quiet
      let log = `working [at=${at - 600}]: started\n`
      if (n % 13 === 0) log += `needs-decision [at=${at}] [key=pick-${n}]: choose A or B for ${repo}\n`
      else if (n % 17 === 0) log += `paused [at=${at}]: waiting for CI\n`
      else log += `working [at=${at}]: step ${n % 5} done\n`
      if (n % 97 !== 0) writeFileSync(join(home, "state", `${id}.status`), log)
      if (i % 3 === 0) for (let q = 0; q < 2; q++) rows.push(`  ${repo.slice(0, 2)}-next-${n}-${q},queued,task,${repo},"Queued follow-up ${q + 1} for ${repo}",no,-,-`)
    }
    writeFileSync(join(home, "tasks.txt"), `count: ${rows.length}\ntasks[${rows.length}]{id,state,kind,repo,title,held,hold_reason,hold_kind}:\n${rows.join("\n")}\n`)
    homes.push(home)
  }
  return homes
}

if (import.meta.main) {
  const [dir, agents = "40", mates = "4"] = process.argv.slice(2)
  if (!dir) { console.error("usage: bun fixture.ts <dir> [agents] [mates]"); process.exit(2) }
  console.log(writeFixture(dir, { agents: Number(agents), mates: Number(mates), now: Math.floor(Date.now() / 1000) }).join("\n"))
}
