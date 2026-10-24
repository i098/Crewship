// Every component Crewship installs, mirrored from scripts/provisions.py
// (GITHUB_LATEST, NPM_LATEST, OMP_PLUGINS) plus the sources Ansible or provisions.py
// install themselves. tests/test_fleet_health_components.py fails when the two drift.
import { existsSync, readdirSync, readFileSync, realpathSync } from "node:fs"
import { join } from "node:path"

export const HOME = process.env.HOME ?? ""
const BIN = `${HOME}/.local/bin`
const PATH = `${BIN}:${process.env.PATH}:/usr/local/bin:${HOME}/oss-fleet/browsers` // the fleet browser tier keeps obscura outside ~/.local/bin

export type Source =
  | { kind: "github"; repo: string; prefix?: string; prerelease?: boolean }
  | { kind: "npm"; pkg: string }
  | { kind: "node" }
  | { kind: "rustup" }
  | { kind: "pypi"; pkg: string }
  | { kind: "forgejo" }
  | { kind: "none"; note: string }

export type Component = { name: string; group: string; source: Source; installed: () => Promise<string | null> }

const VERSION = /\d+(?:\.\d+)+/

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
      const version = readVersion(join(real.slice(0, at), "node_modules", pkg, "package.json"))
      if (version) return version
    }
  } catch {}
  return cmd(command)()
}

const github = (name: string, repo: string, prefix = "v", opts: { prerelease?: boolean; command?: string } = {}): Component => ({
  name, group: "native", source: { kind: "github", repo, prefix, prerelease: opts.prerelease }, installed: cmd(opts.command ?? name),
})
const npm = (name: string, pkg: string): Component => ({
  name, group: "npm", source: { kind: "npm", pkg }, installed: npmInstalled(name, pkg),
})

const plugin = (name: string, repo: string): Component => ({
  name, group: "omp plugin", source: { kind: "github", repo, prefix: "v" },
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
  github("concord", "chojs23/concord"),
  github("slk", "gammons/slk"),
  github("obscura", "h4ckf0r0day/obscura"),
  github("koncreet", "jimididit/koncreet"),
  github("jj", "jj-vcs/jj"),
  github("gws", "googleworkspace/cli"),
  { name: "node", group: "runtime", source: { kind: "node" }, installed: cmd("node") },
  { name: "rustup-init", group: "runtime", source: { kind: "rustup" }, installed: cmd("rustup") },
  npm("omp", "@oh-my-pi/pi-coding-agent"),
  npm("chrome-devtools-axi", "chrome-devtools-axi"),
  npm("gh-axi", "gh-axi"),
  npm("lavish-axi", "lavish-axi"),
  npm("quota-axi", "quota-axi"),
  npm("tasks-axi", "tasks-axi"),
  npm("acpx", "acpx"),
  npm("chrome-devtools-mcp", "chrome-devtools-mcp"),
  npm("forgejo-axi", "forgejo-axi"),
  npm("ondine", "ondine"),
  {
    name: "spectrum-ts", group: "npm", source: { kind: "npm", pkg: "spectrum-ts" },
    installed: async () => readVersion(`${HOME}/.local/share/code-factory/imessage/node_modules/spectrum-ts/package.json`),
  },
  {
    name: "psutil", group: "python", source: { kind: "pypi", pkg: "psutil" },
    installed: async () => {
      const py = `${HOME}/.local/share/code-factory/pruner-venv/bin/python`
      return existsSync(py) ? (await run([py, "-c", "import psutil;print(psutil.__version__)"])).trim().match(VERSION)?.[0] ?? null : null
    },
  },
  { name: "fdu", group: "python", source: { kind: "pypi", pkg: "fdu" }, installed: cmd("fdu") },
  { name: "sgrep", group: "source", source: { kind: "none", note: "tracks default branch" }, installed: cmd("sgrep") },
  { name: "forgejo", group: "native", source: { kind: "forgejo" }, installed: async () => newestDir(`${HOME}/.local/share/crewship/forgejo`) },
  plugin("ponytail", "DietrichGebert/ponytail"),
  plugin("i-have-adhd", "ayghri/i-have-adhd"),
  plugin("caveman", "JuliusBrussee/caveman"),
]
