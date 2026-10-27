// Read-only loaders for the tasks view: `tasks-axi list` per home plus state/*.status. Never writes to a home.
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs"
import { homedir } from "node:os"
import { basename, dirname, join } from "node:path"
import { parseStatus, parseTasks, type HomeData, type Progress } from "./tasks-model.ts"

const FIELDS = "held,hold_reason,hold_kind"
const PARALLEL = 8
const SPAWN_TIMEOUT_MS = 10_000

// Homes: CLI paths, else $CREWBOARD_TASKS_HOMES (colon list), else this host's firstmate homes (~/.treehouse/firstmate-*/<n>/firstmate).
export function findHomes(args: string[], env = process.env, root = join(homedir(), ".treehouse")): string[] {
  if (args.length) return args
  if (env.CREWBOARD_TASKS_HOMES) return env.CREWBOARD_TASKS_HOMES.split(":").filter(Boolean)
  const out: string[] = []
  try {
    for (const d of readdirSync(root)) {
      if (!d.startsWith("firstmate-")) continue
      for (const n of readdirSync(join(root, d))) {
        const home = join(root, d, n, "firstmate")
        if (existsSync(join(home, "state"))) out.push(home)
      }
    }
  } catch {}
  return out.sort()
}

// A home is named after its pool dir (".../firstmate-8bf1b0/6/firstmate" -> "firstmate-8bf1b0/6"), else its own folder.
export const mateName = (home: string) => (basename(home) === "firstmate" ? `${basename(dirname(dirname(home)))}/${basename(dirname(home))}` : basename(home))

function readProgress(home: string): Map<string, Progress> {
  const out = new Map<string, Progress>()
  const dir = join(home, "state")
  let names: string[] = []
  try { names = readdirSync(dir) } catch {}
  for (const f of names) {
    if (!f.endsWith(".status")) continue
    try {
      const p = join(dir, f)
      out.set(f.slice(0, -".status".length), parseStatus(readFileSync(p, "utf8"), Math.floor(statSync(p).mtimeMs / 1000)))
    } catch {}
  }
  return out
}

async function loadHome(home: string, bin: string, timeout: number): Promise<HomeData> {
  let tasks: HomeData["tasks"] = []
  try {
    const p = Bun.spawn([bin, "list", "--fields", FIELDS], { cwd: home, stdout: "pipe", stderr: "ignore", timeout })
    const text = await new Response(p.stdout).text()
    if ((await p.exited) === 0) tasks = parseTasks(text)
  } catch {}
  return { mate: mateName(home), tasks, progress: readProgress(home) }
}

export async function loadHomes(homes: string[], bin = process.env.TASKS_AXI_BIN || "tasks-axi", timeout = SPAWN_TIMEOUT_MS): Promise<HomeData[]> {
  const out: HomeData[] = new Array(homes.length)
  let next = 0
  await Promise.all(Array.from({ length: Math.min(PARALLEL, homes.length) }, async () => {
    for (let i = next++; i < homes.length; i = next++) out[i] = await loadHome(homes[i], bin, timeout)
  }))
  return out
}
