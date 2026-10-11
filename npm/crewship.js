#!/usr/bin/env node
// Fetch install.sh from the Crewship release that matches this package version and
// run it; it downloads the release artifact of the same version. Arguments go to `./ship.sh dock`.
// --help prints the usage of install.sh here, without a fetch; install.sh rejects bad options.
const { spawnSync } = require("node:child_process");
const { version } = require("./package.json");

const ref = `v${version}`;
const url = `https://raw.githubusercontent.com/i098/Crewship/${ref}/install.sh`;

if (process.argv.slice(2).some((arg) => arg === "-h" || arg === "--help")) {
  console.log(`Usage: crewship [--container] [--user NAME] [--home DIR]
Installs Crewship on this Ubuntu 24.04 or 26.04 machine (npx crewship or install.sh).
The options go to ./ship.sh dock, which writes the host config on the first run.
  -h, --help  print this help and exit`);
  process.exit(0);
}

fetch(url)
  .then((response) => {
    if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
    return response.text();
  })
  .then((script) => {
    // The script goes in on stdin, never into the command line, the way `curl | bash` runs it.
    const result = spawnSync("bash", ["-s", "--", ...process.argv.slice(2)], {
      input: script,
      stdio: ["pipe", "inherit", "inherit"],
      env: { ...process.env, CREWSHIP_REF: ref },
    });
    process.exit(result.status ?? 1);
  })
  .catch((error) => {
    console.error(`crewship: ${error.message}`);
    process.exit(1);
  });
