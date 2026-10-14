#!/usr/bin/env node
// Fetch install.sh from the Crewship release that matches this package version and
// run it (`update`: from the newest release); it downloads the release artifact of the same version. Arguments go to `./ship.sh dock`.
// --help prints the usage of install.sh here, without a fetch; install.sh rejects bad options.
const { spawnSync } = require("node:child_process");
const { version } = require("./package.json");

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

if (args.some((arg) => arg === "-h" || arg === "--help")) {
  console.log(`Usage: crewship [update] [--container] [--with NAMES] [--user NAME] [--home DIR]
Installs Crewship on this Ubuntu 24.04 or 26.04 machine (bunx crewship, npx crewship or install.sh).
The options go to ./ship.sh dock, which writes the host config on the first run.
  update        install the newest release over this host, keeping its .local/ files
  --with NAMES  turn on these opt-in features, comma separated, and skip the checklist (--with none: none)
                public_skills development docker chat gateway jj fleet_guards shared_postgres fleet_browsers tailscale desktop board
  -h, --help    print this help and exit`);
  process.exit(0);
}

if (args.some((arg) => arg === "--version" || arg === "-v")) {
  console.log(version);
  process.exit(0);
}

// The package installs on any OS (no "os" field, so npm never refuses it); only Ubuntu can run the install.
if (process.platform !== "linux") {
  console.error(
    `crewship: Crewship installs on an Ubuntu 24.04 or 26.04 server, not on ${process.platform}. Run \`npx crewship\` on that server, for example over ssh.`,
  );
  process.exit(1);
}

(async () => {
  const ref = update ? await latestTag() : `v${version}`;
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
})().catch((error) => {
  console.error(`crewship: ${error.message}`);
  process.exit(1);
});
