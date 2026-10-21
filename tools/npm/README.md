# crewship

Turn a fresh Ubuntu 24.04 or 26.04 machine into an AI-agent coding host with [Crewship](https://github.com/i098/Crewship).

```sh
bunx crewship
```

`npx crewship` and `pnpm dlx crewship` work too. The package fetches `install.sh` from the Crewship release with the same version and runs it; it bundles nothing else. Arguments go to `./ship.sh dock`. `bunx crewship update` takes the newest release instead and updates an installed host ([Update](https://github.com/i098/Crewship/blob/main/docs/install.md#update)).

## Guided setup

Run the guide on your laptop with Node.js 18 or later:

```sh
npx crewship init
```

The guide works on macOS, Windows, and Linux.
It installs nothing on the laptop.
It first asks whether you have a server.
For an existing server, enter its vCPU count, RAM, and free disk space.
The minimum is 4 vCPU, 16 GB RAM, and 100 GB free disk.
Otherwise, enter the simultaneous light and UI lane counts and the required features.
The guide recommends a [documented preset](https://github.com/i098/Crewship/blob/main/docs/capacity.md).
Only an explicit `yes` confirms that you have purchased or provisioned the recommended server.
No, Enter, or end of input stops before setup.

Choose the printed server command, or choose SSH with an existing key.
SSH accepts an existing alias or a hostname, non-root username, and port.
It checks Ubuntu 24.04 or 26.04, systemd, sudo, CPU, RAM, and free disk before installation.
SSH does not forward your agent or accept passwords.
For an unknown host key, first use your SSH client to verify the fingerprint against the provider console.
Enter any sudo password directly in the native terminal.
The guide does not read or save passwords or keys.

Both routes preserve an existing Crewship config through the update path.
Feature choices apply only to a new config.
After installation, run `"$HOME/Crewship/ship.sh" setup` on the server and complete the manual sign-in steps.
Bare `npx crewship` still installs on the current Ubuntu server.
`npx crewship update` still updates that server.
