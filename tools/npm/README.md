# crewship

Turn a fresh Ubuntu 24.04 or 26.04 machine into an AI-agent coding host with [Crewship](https://github.com/i098/Crewship).

```sh
bunx crewship
```

`npx crewship` and `pnpm dlx crewship` work too.
These bare commands run the installer on the current Ubuntu server.
The package bundles only the launcher.
Installation arguments go to `./ship.sh dock`.
See [Install, update and migrate](https://github.com/i098/Crewship/blob/main/docs/install.md) for release selection and updates.

## Guided setup

Run the guide on your laptop with Node.js 18 or later and npm:

```sh
npx crewship init
```

The guide works on macOS, Windows, and Linux.
It installs nothing on the laptop.
It first asks whether you have a server.
For an existing server, enter its vCPU count, RAM, and total disk capacity in GB.
RAM and disk values can include decimals.
The minimum nominal size is 4 vCPU, 16 GB RAM, and 100 GB total disk.
The guide accepts reported RAM and disk capacity at 90% of the nominal size.
Otherwise, enter the simultaneous light and UI lane counts, or explicitly choose the two-light-lane starter.
Select the required features and enter the number of extra idle browser bridges and extra storage in GB.
Each extra browser adds 2 GB RAM; extra storage adds to the workload preset's disk capacity.
The guide selects the smallest [documented preset](https://github.com/i098/Crewship/blob/main/docs/capacity.md) that meets CPU, RAM, and disk requirements.
For loads above the presets, the guide shows both formulas with your values before requesting a larger quote.
Use SSD or NVMe storage.
Start with a VPS; compare dedicated hardware for sustained 16 vCPU / 64 GB load.
Only an explicit `yes` confirms that you have purchased or provisioned the recommended server.
No, Enter, or end of input stops before setup.

Choose the printed server command, or choose SSH with an existing key.
SSH accepts an existing alias or a hostname, non-root username, and optional port.
Leave the port blank to use the SSH configuration.
It checks Ubuntu 24.04 or 26.04, systemd, sudo, CPU, RAM, and total disk before installation.
SSH permits only public-key authentication and does not forward your agent.
For an unknown host key, first use your SSH client to verify the fingerprint against the provider console.
Enter any sudo password directly in the native terminal.
The guide does not read or save passwords or keys.

Both routes preserve an existing Crewship config through the update path.
Feature choices apply only to a new config.
Both routes install curl when it is absent.
New installations use the release matching this package version; updates use the latest release.
After installation, run `"$HOME/Crewship/ship.sh" setup` on the server and complete the manual sign-in steps.
Run `npx crewship update` on the Crewship server for later updates.
