#!/usr/bin/env node
// Fetch install.sh from the Crewship release that matches this package version and
// run it (`update`: from the newest release); it downloads the release artifact of the same version. Arguments go to `./ship.sh dock`.
// --help prints the usage of install.sh here, without a fetch; install.sh rejects bad options.
const { spawnSync } = require("node:child_process");
const { version } = require("./package.json");
const { createInterface } = require("node:readline");
const { isIP } = require("node:net");

// Kept equal to scripts/ship.py OPT_IN by tests/test_npm_package.py.
const optIn = {
  public_skills: [], agent_instructions: [], development: [], docker: [],
  chat: [], gateway: [], jj: [], fdu: [], fleet_guards: ["docker"],
  project_databases: ["docker"], fleet_browsers: [], forgejo: [], tailscale: [],
  koncreet: [], desktop: [], board: ["development"], sgrep: [],
};
const presets = [
  { cpu: 4, ram: 16, disk: 100, swap: 8 },
  { cpu: 8, ram: 32, disk: 200, swap: 16 },
  { cpu: 16, ram: 64, disk: 300, swap: 32 },
];

function recommend(light, ui) {
  const ram = 11 + 2 * light + 8 * ui;
  const cpu = light + 2 * ui;
  return { ram, cpu, preset: presets.find((size) => size.ram >= ram && size.cpu >= cpu) };
}

function features(answer) {
  const selected = answer.toLowerCase().split(/[\s,]+/).filter(Boolean);
  if (selected.length === 0 || answer.toLowerCase() === "none") return "none";
  if (selected.some((name) => !Object.hasOwn(optIn, name))) throw new Error("Choose only listed feature names.");
  return [...new Set(selected.flatMap((name) => [name, ...optIn[name]]))].join(",");
}

function sshArgs({ alias, host, user, port }) {
  const name = /^[a-zA-Z0-9][a-zA-Z0-9._-]*$/;
  if (alias ? !name.test(alias) : (
    !(name.test(host) || isIP(host)) || !/^[a-z_][a-z0-9_-]*$/i.test(user) || user === "root"
  )) throw new Error("Use an SSH alias, or a hostname and a non-root username. Shell syntax is not allowed.");
  if (!/^\d+$/.test(port) || Number(port) < 1 || Number(port) > 65535) throw new Error("Use a port from 1 to 65535.");
  return [
    "-a", "-o", "ForwardAgent=no", "-o", "BatchMode=yes",
    "-o", "PasswordAuthentication=no", "-o", "KbdInteractiveAuthentication=no",
    "-o", "StrictHostKeyChecking=ask", "-o", "ControlPath=none",
    "-o", "ConnectTimeout=10", "-p", port, ...(alias ? [] : ["-l", user]),
    "--", alias || host,
  ];
}

function installCommand(selected) {
  return `if [ -f "$HOME/Crewship/.local/host.yml" ]; then
  curl -fsSL https://raw.githubusercontent.com/${repo}/main/install.sh | bash
else
  curl -fsSL https://raw.githubusercontent.com/${repo}/v${version}/install.sh | bash -s -- --with ${selected}
fi`;
}

function serverScript(size, selected) {
  return `set -euo pipefail
. /etc/os-release
[ "$ID" = ubuntu ] && { [ "$VERSION_ID" = 24.04 ] || [ "$VERSION_ID" = 26.04 ]; } || { echo "Use Ubuntu 24.04 or 26.04."; exit 1; }
[ -d /run/systemd/system ] || { echo "The server needs systemd."; exit 1; }
[ "$(id -u)" -ne 0 ] || { echo "Use a non-root account."; exit 1; }
command -v sudo >/dev/null || { echo "The account needs sudo."; exit 1; }
[ "$(nproc)" -ge ${size.cpu} ] || { echo "The server needs ${size.cpu} vCPU."; exit 1; }
awk '/^MemTotal:/ { exit (int($2 / 1048576 + 0.5) < ${size.ram}) }' /proc/meminfo || { echo "The server needs ${size.ram} GB RAM."; exit 1; }
df -Pk "$HOME" | awk 'NR == 2 { exit ($4 < ${size.disk} * 1000000) }' || { echo "The server needs ${size.disk} GB free disk."; exit 1; }
sudo -v
${installCommand(selected)}`;
}

function manualSetup(selected) {
  console.log("Run this command ON THE SERVER as a non-root sudo user, with Ubuntu 24.04 or 26.04 and systemd:");
  console.log(installCommand(selected));
  console.log('After installation, run "$HOME/Crewship/ship.sh" setup and complete the manual sign-in steps.');
  console.log("Recovery: https://github.com/i098/Crewship/blob/main/docs/install.md");
}

async function setup(ask, { size, selected }, terminal) {
  const route = (await ask("Print a server command (A), or use SSH with existing keys (B)? [A/B]")).toLowerCase();
  if (route === "a") return manualSetup(selected);
  if (route !== "b") return;
  const alias = await ask("Existing SSH alias? [Enter to use host/user/port]");
  const host = alias ? "" : await ask("Server hostname or IP address?");
  const user = alias ? "" : await ask("Non-root server username?");
  const port = (await ask("SSH port? [Enter for 22]")) || "22";
  const connection = sshArgs({ alias, host, user, port });
  console.log(`Target: ${alias || `${user}@${host}`}:${port}. New-host features: ${selected}. Existing config: update only.`);
  console.log("Verify the SSH host fingerprint against the provider console. Unknown or changed keys stop setup.");
  console.log("SSH will check the server, then run the installer. Enter sudo answers only in the native terminal.");
  if ((await ask("Start setup on this server? [yes/no]")).toLowerCase() !== "yes") return;
  terminal.close();
  process.stdin.pause();
  const probe = spawnSync("ssh", [...connection, "true"], { stdio: ["ignore", "ignore", "inherit"] });
  if (probe.status !== 0) {
    console.log("SSH key authentication failed. Check the key and host fingerprint with your SSH client, or use the manual command.");
    return manualSetup(selected);
  }
  const script = serverScript(size, selected);
  const result = spawnSync("ssh", ["-t", ...connection, `bash -c '${script.replaceAll("'", "'\\''")}'`], { stdio: "inherit" });
  if (result.status !== 0) {
    manualSetup(selected);
    throw new Error("Remote setup stopped. Check the server and installation log before retrying.");
  }
  console.log('Run "$HOME/Crewship/ship.sh" setup on the server and complete the manual sign-in steps.');
}

async function init() {
  const terminal = createInterface({ input: process.stdin, output: process.stdout });
  const lines = terminal[Symbol.asyncIterator]();
  const ask = async (question) => {
    process.stdout.write(`${question} `);
    const line = await lines.next();
    if (line.done) throw new Error("Cancelled. No setup started.");
    return line.value.trim();
  };
  const number = async (question, minimum) => {
    const answer = await ask(question);
    if (!/^\d+$/.test(answer) || !Number.isSafeInteger(Number(answer)) || Number(answer) < minimum) {
      throw new Error(`Enter a whole number of at least ${minimum}.`);
    }
    return Number(answer);
  };
  const askFeatures = async () => {
    for (const [name, needs] of Object.entries(optIn)) {
      console.log(`  ${name}${needs.length ? ` (needs ${needs.join(", ")})` : ""}`);
    }
    return features(await ask("Which features do you need? [names, or Enter for none]"));
  };
  let selected = "none";
  try {
    const existing = (await ask("Do you already have a server for Crewship? [yes/no]")).toLowerCase();
    let size;
    if (existing === "yes") {
      const cpu = await number("How many vCPU does it have?", 1);
      const ram = await number("How much RAM does it have, in GB?", 1);
      const disk = await number("How much free disk does it have, in GB?", 1);
      if (cpu < 4 || ram < 16 || disk < 100) throw new Error("Use at least 4 vCPU, 16 GB RAM, and 100 GB free disk.");
      size = presets.filter((preset) => cpu >= preset.cpu && ram >= preset.ram && disk >= preset.disk).pop();
      console.log(`The server meets the ${size.cpu} vCPU / ${size.ram} GB RAM / ${size.disk} GB disk preset.`);
    } else if (existing === "no") {
      console.log("Count active lanes, not queued jobs. Count each UI lane separately from light lanes.");
      const light = await number("How many simultaneous light lanes?", 0);
      const ui = await number("How many simultaneous UI lanes?", 0);
      selected = await askFeatures();
      const estimate = recommend(light, ui);
      console.log(`Estimate: ${estimate.ram} GB RAM and ${estimate.cpu} vCPU. These are estimates, not guarantees.`);
      if (!estimate.preset) {
        console.log("The load exceeds the documented presets. Obtain a larger server quote before setup.");
        return;
      }
      size = estimate.preset;
      console.log(`Buy or provision: ${size.cpu} vCPU, ${size.ram} GB RAM, ${size.disk} GB disk, ${size.swap} GB swap.`);
      console.log("Swap is not capacity. Allow extra space for data and extra RAM for other services.");
      if ((await ask("Have you purchased or provisioned a server that meets this recommendation? [yes/no]")).toLowerCase() !== "yes") return;
    } else {
      return;
    }
    if (existing === "yes") selected = await askFeatures();
    await setup(ask, { size, selected }, terminal);
  } finally {
    terminal.close();
  }
}

const repo = "i098/Crewship";
const args = process.argv.slice(2);
// `update` takes the newest release (not this package's version), so an old package can still update.
const update = args[0] === "update";
if (update) args.shift();

// Prints the tag the releases/latest redirect points to (no API, no rate limit).
async function latestTag() {
  const response = await fetch(`https://github.com/${repo}/releases/latest`, { redirect: "manual" });
  const tag = (response.headers.get("location") || "").split("/").pop();
  if (!/^v[0-9][0-9A-Za-z._-]*$/.test(tag)) throw new Error(`no release found in ${repo}`);
  return tag;
}

async function explainPnpmRelease(ref) {
  if (!process.env.npm_config_user_agent?.startsWith("pnpm/") || update) return;
  try {
    const response = await fetch("https://registry.npmjs.org/crewship/latest", { signal: AbortSignal.timeout(5000) });
    if (!response.ok) return;
    const latest = (await response.json()).version;
    if (!/^\d+\.\d+\.\d+$/.test(latest) || !/^v\d+\.\d+\.\d+$/.test(ref)) return;
    const selectedParts = ref.slice(1).split(".").map(Number);
    const difference = latest.split(".").map(Number).map((part, index) => part - selectedParts[index]).find((part) => part !== 0);
    if (!(difference > 0)) return;
    console.log(`pnpm selected Crewship ${ref}; the registry latest is v${latest}.`);
    console.log("pnpm's minimumReleaseAge policy can exclude recent releases (1,440 minutes by default in pnpm 12).");
    console.log("Crewship keeps your pnpm policy unchanged.");
  } catch {
    // Registry availability must not block an already resolved release.
  }
}

async function main() {
  if (args[0] === "init") {
    if (args.length !== 1) throw new Error("Usage: crewship init");
    return init();
  }

  if (args.some((arg) => arg === "-h" || arg === "--help")) {
    console.log(`Usage: crewship [update] [--container] [--with NAMES] [--user NAME] [--home DIR]
Installs Crewship on this Ubuntu 24.04 or 26.04 machine (bunx crewship, npx crewship or install.sh).
The options go to ./ship.sh dock, which writes the host config on the first run.
  update        install the newest release over this host, keeping its .local/ files
  --with NAMES  turn on these opt-in features, comma separated, and skip the checklist (--with none: none)
                public_skills agent_instructions development docker chat gateway jj fdu fleet_guards project_databases fleet_browsers forgejo tailscale koncreet desktop board sgrep
  -h, --help    print this help and exit`);
    process.exit(0);
  }

  if (args.some((arg) => arg === "--version" || arg === "-v")) {
    console.log(version);
    process.exit(0);
  }

  // The package installs on any OS; only Ubuntu can run the installer.
  if (process.platform !== "linux") {
    console.error(
      `crewship: Crewship installs on an Ubuntu 24.04 or 26.04 server, not on ${process.platform}. Run \`npx crewship\` on that server, for example over ssh.`,
    );
    process.exit(1);
  }

  const ref = update ? await latestTag() : `v${version}`;
  await explainPnpmRelease(ref);
  const url = `https://raw.githubusercontent.com/${repo}/${ref}/install.sh`;
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  // The script goes in on stdin, never into the command line, the way `curl | bash` runs it.
  const result = spawnSync("bash", ["-s", "--", ...args], {
    input: await response.text(),
    stdio: ["pipe", "inherit", "inherit"],
    env: { ...process.env, CREWSHIP_REF: ref },
  });
  process.exit(result.status ?? 1);
}

if (require.main === module) main().catch((error) => {
  console.error(`crewship: ${error.message}`);
  process.exitCode = 1;
});

module.exports = { optIn, presets, recommend, features, sshArgs, serverScript };
