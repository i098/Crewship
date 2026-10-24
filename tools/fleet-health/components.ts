// Every component Crewship installs, mirrored from scripts/provisions.py
// (GITHUB_LATEST, NPM_LATEST, OMP_PLUGINS) plus the sources Ansible or provisions.py
// install themselves. tests/test_fleet_health_components.py fails when the two drift.
import { existsSync, readdirSync, readFileSync, readlinkSync, realpathSync, statSync } from "node:fs"
import { basename, join } from "node:path"

export const HOME = process.env.HOME ?? ""
const BIN = `${HOME}/.local/bin`
// Off-PATH homes: cargo installs (sgrep), bun links, and the fleet browser tier (obscura).
const PATH = `${BIN}:${HOME}/.cargo/bin:${HOME}/.bun/bin:${process.env.PATH}:/usr/local/bin:${HOME}/oss-fleet/browsers`

export type Source =
  | { kind: "github"; repo: string; prefix?: string; prerelease?: boolean }
  | { kind: "npm"; pkg: string }
  | { kind: "node" }
  | { kind: "rustup" }
  | { kind: "pypi"; pkg: string }
  | { kind: "forgejo" }
  | { kind: "head"; repo: string } // built from the default branch: compared by commit

// bin: the command (or file) whose access time shows the last use; absent when no file is evidence of use.
// trace: a file or directory whose newest access time shows use when the command itself is not the evidence.
// custom: an installed version matching it is the owner's own build, never outdated.
export type Component = { name: string; group: string; source: Source; installed: () => Promise<string | null>; bin?: string; trace?: string; custom?: RegExp }

// Executable paths and names of every live process, from /proc exe and argv.
export function liveProcesses(): Set<string> {
  const live = new Set<string>()
  const add = (path: string) => { live.add(path); live.add(basename(path)) }
  for (const pid of readdirSync("/proc").filter(p => /^\d+$/.test(p))) {
    try { add(readlinkSync(`/proc/${pid}/exe`).replace(/ \(deleted\)$/, "")) } catch {}
    try { const argv = readFileSync(`/proc/${pid}/cmdline`, "utf8").split("\0"); for (const arg of argv.slice(0, 2)) if (arg) add(arg) } catch {}
  }
  return live
}

export const isRunning = (bin: string, path: string | null, live: Set<string>) =>
  live.has(bin) || live.has(basename(bin)) || (path !== null && live.has(path))

// Newest access time under a path (files up to 3 levels deep, at most 500 entries): reading any file counts as use.
export function newestAtime(path: string, depth = 3, budget = { n: 500 }): number | null {
  try {
    const st = statSync(path)
    if (!st.isDirectory() || depth === 0) return st.atimeMs
    let best = st.atimeMs
    for (const entry of readdirSync(path)) {
      if (budget.n-- <= 0) break
      best = Math.max(best, newestAtime(join(path, entry), depth - 1, budget) ?? 0)
    }
    return best
  } catch {
    return null
  }
}

// Newest access time that shows this component in use: its trace path (a plugin narrows to its own install dir), else its binary.
export function traceFor(c: Component, binary: string | null): number | null {
  let trace = c.trace
  if (trace && c.group === "omp plugin") {
    const dir = existsSync(trace) ? readdirSync(trace).filter(d => d.startsWith(`${c.name}___${c.name}___`)).sort().pop() : undefined
    trace = dir ? join(trace, dir) : undefined
  }
  const target = trace ?? binary
  return target ? newestAtime(target) : null
}

// Real path of a command, or null. relatime keeps atime within a day of the last read; a running process is checked separately.
export const binPath = (bin: string): string | null => {
  try {
    const found = bin.startsWith("/") ? bin : Bun.which(bin, { PATH })
    return found ? realpathSync(found) : null
  } catch {
    return null
  }
}

const VERSION = /\d+(?:\.\d+)+(?:-(?:alpha|beta|rc)(?:\.\d+)*)?/

async function run(argv: string[]): Promise<string> {
  const proc = Bun.spawn(argv, { stdout: "pipe", stderr: "pipe", env: { ...process.env, PATH } })
  const timer = setTimeout(() => proc.kill(), 10_000)
  const [out, err] = await Promise.all([new Response(proc.stdout).text(), new Response(proc.stderr).text()])
  clearTimeout(timer)
  return out + err
}

// `<command> --version`, first version-like token on the first line that has one.
const cmd = (command: string, ...args: string[]) => async () => {
  const path = Bun.which(command, { PATH })
  if (!path) return null
  try {
    for (const line of (await run([path, ...(args.length ? args : ["--version"])])).split("\n")) {
      if (/warning|error/i.test(line)) continue
      const found = line.match(VERSION)
      if (found) return found[0]
    }
  } catch {}
  return null
}

const readVersion = (file: string): string | null => {
  try {
    return JSON.parse(readFileSync(file, "utf8")).version ?? null
  } catch {
    return null
  }
}

// bun installs each npm tool into node_modules/<package>; read the version it recorded.
const npmInstalled = (command: string, pkg: string) => async () => {
  try {
    const real = realpathSync(`${BIN}/${command}`)
    const at = real.indexOf(`/node_modules/${pkg}/`)
    if (at >= 0) {
      const prefix = real.slice(0, at)
      // provisions.py installs each version into <name>/<version>/; the directory name keeps a custom build's suffix.
      const dir = basename(prefix)
      if (/^\d+(\.\d+)+(-[0-9A-Za-z.]+)?$/.test(dir)) return dir
      const version = readVersion(join(prefix, "node_modules", pkg, "package.json"))
      if (version) return version
    }
  } catch {}
  return cmd(command)()
}

const github = (name: string, repo: string, prefix = "v", opts: { prerelease?: boolean; command?: string } = {}): Component => ({
  name, group: "native", source: { kind: "github", repo, prefix, prerelease: opts.prerelease }, installed: cmd(opts.command ?? name), bin: opts.command ?? name,
})
const npm = (name: string, pkg: string): Component => ({
  name, group: "bun", source: { kind: "npm", pkg }, installed: npmInstalled(name, pkg), bin: name,
})

const plugin = (name: string, repo: string): Component => ({
  name, group: "omp plugin", source: { kind: "github", repo, prefix: "v" },
  trace: `${HOME}/.omp/plugins/cache/plugins`, // narrowed to this plugin's install dir in scanUsage
  installed: async () => {
    try {
      const registry = JSON.parse(readFileSync(`${HOME}/.omp/plugins/installed_plugins.json`, "utf8"))
      return registry.plugins?.[`${name}@${name}`]?.[0]?.version ?? null
    } catch {
      return null
    }
  },
})

const newestDir = (dir: string): string | null => {
  try {
    return readdirSync(dir).filter(d => VERSION.test(d)).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })).pop() ?? null
  } catch {
    return null
  }
}

export const components: Component[] = [
  github("herdr", "herdrdev/herdr"),
  github("bun", "oven-sh/bun", "bun-v"),
  github("gh", "cli/cli"),
  github("nvim", "neovim/neovim"),
  github("no-mistakes", "kunchenguid/no-mistakes", "v", { prerelease: true }),
  github("treehouse", "kunchenguid/treehouse"),
  github("uv", "astral-sh/uv", ""),
  github("btop", "aristocratos/btop", "v", { command: "btop-bin" }),
  github("sentrux", "sentrux/sentrux"),
  github("fallow", "fallow-rs/fallow"),
  github("cloudflared", "cloudflare/cloudflared", ""),
  github("pyrefly", "facebook/pyrefly", ""),
  github("slk", "gammons/slk"),
  github("obscura", "h4ckf0r0day/obscura"),
  github("koncreet", "jimididit/koncreet"),
  github("jj", "jj-vcs/jj"),
  github("gws", "googleworkspace/cli"),
  { name: "node", group: "runtime", source: { kind: "node" }, installed: cmd("node"), bin: "node" },
  { name: "rustup-init", group: "runtime", source: { kind: "rustup" }, installed: cmd("rustup"), bin: "rustup" },
  npm("omp", "@oh-my-pi/pi-coding-agent"),
  npm("chrome-devtools-axi", "chrome-devtools-axi"),
  npm("gh-axi", "gh-axi"),
  { ...npm("lavish-axi", "lavish-axi"), custom: /sketch/ },
  npm("quota-axi", "quota-axi"),
  npm("tasks-axi", "tasks-axi"),
  npm("acpx", "acpx"),
  npm("chrome-devtools-mcp", "chrome-devtools-mcp"),
  npm("forgejo-axi", "forgejo-axi"),
  npm("ondine", "ondine"),
  npm("concord", "@chojs23/concord"),
  {
    name: "spectrum-ts", group: "bun", source: { kind: "npm", pkg: "spectrum-ts" },
    installed: async () => readVersion(`${HOME}/.local/share/code-factory/imessage/node_modules/spectrum-ts/package.json`),
    trace: `${HOME}/.local/share/code-factory/imessage/node_modules/spectrum-ts`,
  },
  {
    name: "psutil", group: "python", source: { kind: "pypi", pkg: "psutil" },
    trace: `${HOME}/.local/share/code-factory/pruner-venv/lib`, // the pruner imports it; its __pycache__ is read on each import
    installed: async () => {
      const py = `${HOME}/.local/share/code-factory/pruner-venv/bin/python`
      return existsSync(py) ? (await run([py, "-c", "import psutil;print(psutil.__version__)"])).trim().match(VERSION)?.[0] ?? null : null
    },
  },
  { name: "fdu", group: "python", source: { kind: "pypi", pkg: "fdu" }, installed: cmd("fdu"), bin: "fdu" },
  {
    name: "sgrep", group: "source", source: { kind: "head", repo: "context-dot-dev/sgrep" }, bin: "sgrep",
    // cargo records the commit it built in .crates2.json: "sgrep 0.3.0 (git+https://...#<sha>)".
    installed: async () => {
      try {
        const crates = JSON.parse(readFileSync(`${HOME}/.cargo/.crates2.json`, "utf8")).installs ?? {}
        const key = Object.keys(crates).find(k => k.startsWith("sgrep "))
        return key?.match(/#([0-9a-f]{7})[0-9a-f]*\)/)?.[1] ?? null
      } catch {
        return null
      }
    },
  },
  { name: "forgejo", group: "native", source: { kind: "forgejo" }, installed: async () => newestDir(`${HOME}/.local/share/crewship/forgejo`), bin: `${HOME}/.local/share/crewship/forgejo/${newestDir(`${HOME}/.local/share/crewship/forgejo`)}/forgejo` },
  plugin("ponytail", "DietrichGebert/ponytail"),
  plugin("i-have-adhd", "ayghri/i-have-adhd"),
  plugin("caveman", "JuliusBrussee/caveman"),
]
