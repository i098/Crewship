# Set up Crewship (for an AI agent)

Ask the user first: "Do you already have a server for Crewship?"
Follow the steps below in order.
Stop and ask the user where a step says STOP.
Never guess a login, a code, or a choice.
Report each result in one line.
If a command fails, remove private data before showing its last lines.
Do not skip a step to hide a failure.

## Before installation: choose the server

Run the guided setup on the laptop, with Node.js 18 or newer and npm:

```bash
npx crewship init
```

Or use `bunx crewship init` with Bun and Node.js installed.
The guide does not install Crewship on the laptop.
If no launcher runtime exists, guide the user through the choices below without installing a runtime.

1. If the user has a server, ask for its OS, CPU, RAM, free disk, and SSH access details.
   Check it against [Capacity](docs/capacity.md); do not start a purchase interview.
2. If the user has no server, ask how many agents will work at once and how many will run browsers and dev servers.
   Ask for the monthly server budget, currency, region, expected sustained load, and extra storage needs.
   Keep model API costs separate.
   Recommend the smallest documented preset that meets the CPU, RAM, and disk needs.
   Treat the estimates as planning figures, not a concurrency guarantee.
3. STOP: after recommending a purchase, ask whether the user has purchased or provisioned a suitable server.
   Continue only after an explicit yes.
   Do not buy a server or start setup for the user before confirmation.
4. Ask whether to connect from the laptop over SSH or show a command to run manually on the server.
   For SSH, use an existing alias or the hostname, non-root user, and optional port.
   Use existing SSH keys only; never request, copy, or store a private key or SSH password.
   Keep host-key checks on and agent forwarding off.
   Ask the user to verify a new fingerprint through the provider console; stop on a changed key.
   If no usable key exists, show the manual server command from step 0.
   Choose optional features with the checklist in step 0 before requesting installation permission.
5. STOP: show the target server, chosen features, and install action; ask for permission before connecting or installing.
   Let the user enter any sudo password directly in the terminal.
   On a failed connection or target check, stop and offer the manual route.
   Never fall back to installing on the laptop.

If `init` completed installation, continue at [Resume setup](#resume-setup) on the server.
Otherwise, follow step 0 on the server.
For an existing Crewship installation, follow [Update](docs/install.md#update); do not pass `--with` again.

## Setup flow

<!-- ondine:eNptUsFu2zAMve8rCJ82IHWLItghhwFFimDHHbqT0YMs0ZYQWRJIKm7-fpDsBt4yXSg98VF8Txx8nLVVJPD2-gUAQGn95sTjAU6EbOF3n4NkYJScgHJg6GMUFlJpBxflnVGCXO7FhZF3oIIBlZJ3yJAoDs4jg0RwgUV5D0fCma1LIDF6rumMdHEauTbQx4-u-evt5337tIdI8Py9fdo37_Dw8KN20TXtYwx9VGRatgfwpRWBfNnBS2DXe2ze15pRKssFV1mlgZYtmKjPB5jJFQ2tj1r5RxtZ2uvkV26hVK62qM9bsgucUMsOxGKA6uLKqamVVJy4bkle5aDtmudjqViM0Fa5cFNA6FEx8m6pxHl6uCC5waGBr3FKkHweXWDAD41J0HxbXanPLf9YdhX7_ISuWU25IWsXnPuRVLJQlHfNyQXHFk09rillWSRDXfOzBJgjnTkpjZuEYSpkYpmUIETSFsucSKRNkhoxCHdNUbHsN5djVmS4a04eUdbT5rr8FlLXvNYIGEYXtg1oq6RrjjHoSGaZLH-uKGjv_n1LCc7q2jW_FPNcCCtSiUcfsxm8IgTJIeDnNGAwNd4muzhcnbmHh-keWyTf44vWe3yRfI8XUf-psij4AzscO0w -->
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://ondine.sh/eNptUsFu2zAMve8rCJ82IHWLItghhwFFimDHHbqT0YMs0ZYQWRJIKm7-fpDsBt4yXSg98VF8Txx8nLVVJPD2-gUAQGn95sTjAU6EbOF3n4NkYJScgHJg6GMUFlJpBxflnVGCXO7FhZF3oIIBlZJ3yJAoDs4jg0RwgUV5D0fCma1LIDF6rumMdHEauTbQx4-u-evt5337tIdI8Py9fdo37_Dw8KN20TXtYwx9VGRatgfwpRWBfNnBS2DXe2ze15pRKssFV1mlgZYtmKjPB5jJFQ2tj1r5RxtZ2uvkV26hVK62qM9bsgucUMsOxGKA6uLKqamVVJy4bkle5aDtmudjqViM0Fa5cFNA6FEx8m6pxHl6uCC5waGBr3FKkHweXWDAD41J0HxbXanPLf9YdhX7_ISuWU25IWsXnPuRVLJQlHfNyQXHFk09rillWSRDXfOzBJgjnTkpjZuEYSpkYpmUIETSFsucSKRNkhoxCHdNUbHsN5djVmS4a04eUdbT5rr8FlLXvNYIGEYXtg1oq6RrjjHoSGaZLH-uKGjv_n1LCc7q2jW_FPNcCCtSiUcfsxm8IgTJIeDnNGAwNd4muzhcnbmHh-keWyTf44vWe3yRfI8XUf-psij4AzscO0w.svg?scheme=dark">
  <img alt="Fresh Ubuntu setup runs bootstrap, validates settings, and applies profiles to install Crewship tools and services" src="https://ondine.sh/eNptUsFu2zAMve8rCJ82IHWLItghhwFFimDHHbqT0YMs0ZYQWRJIKm7-fpDsBt4yXSg98VF8Txx8nLVVJPD2-gUAQGn95sTjAU6EbOF3n4NkYJScgHJg6GMUFlJpBxflnVGCXO7FhZF3oIIBlZJ3yJAoDs4jg0RwgUV5D0fCma1LIDF6rumMdHEauTbQx4-u-evt5337tIdI8Py9fdo37_Dw8KN20TXtYwx9VGRatgfwpRWBfNnBS2DXe2ze15pRKssFV1mlgZYtmKjPB5jJFQ2tj1r5RxtZ2uvkV26hVK62qM9bsgucUMsOxGKA6uLKqamVVJy4bkle5aDtmudjqViM0Fa5cFNA6FEx8m6pxHl6uCC5waGBr3FKkHweXWDAD41J0HxbXanPLf9YdhX7_ISuWU25IWsXnPuRVLJQlHfNyQXHFk09rillWSRDXfOzBJgjnTkpjZuEYSpkYpmUIETSFsucSKRNkhoxCHdNUbHsN5djVmS4a04eUdbT5rr8FlLXvNYIGEYXtg1oq6RrjjHoSGaZLH-uKGjv_n1LCc7q2jW_FPNcCCtSiUcfsxm8IgTJIeDnNGAwNd4muzhcnbmHh-keWyTf44vWe3yRfI8XUf-psij4AzscO0w.svg?scheme=light">
</picture>
<!-- /ondine -->

## 0. Choose features and install Crewship

Run this step and all later setup commands on the server, not the laptop.
Use Ubuntu 24.04 or 26.04 with systemd and a non-root account that has sudo.
Check the OS with `lsb_release -rs` and the account with `id -u` (not 0).
Check CPU, RAM, and free disk with `lscpu`, `free -h`, and `df -h`.
Confirm sudo access; if it needs a password, let the user type it directly in the terminal.
STOP if the server does not meet the OS or [capacity requirements](docs/capacity.md).

Crewship installs a core, the omp agents and Firstmate. Everything else is opt-in and off until the user chooses it. `docker` comes with `fleet_guards` and `project_databases`, and `development` comes with `board`.

- STOP: show the user the [profiles](docs/configuration.md#profiles) and the optional [crew board](docs/board.md).
  Exclude `agents` and `firstmate`; they belong to the core, not the opt-in choices.
  Ask which names to turn on; the default is none.
  If the user chooses `agent_instructions`, check whether a target file exists.
  If one exists, ask whether to `skip`, `overwrite` after a backup, or `append` a marked block (the default).
  See [Global instructions](docs/omp.md#global-instructions) for the target files and mode settings.

Run the installer on the server with the chosen names, comma separated.
Use `--with none` for none.
Without an interactive terminal, always pass `--with` to answer the checklist:

```bash
curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash -s -- --with public_skills,docker
```

Use curl on a fresh server; it does not need a JavaScript runtime.
`bunx crewship` needs Bun and Node.js 18 or newer; Bun's Linux installer also needs `unzip`.
`npx crewship` needs Node.js 18 or newer and npm.
`pnpm dlx crewship` may select an older release because of pnpm's release-age policy.
See [Launcher prerequisites](docs/install.md#install); do not clone the repository.

See [Install, update and migrate](docs/install.md#install) for release selection, installation steps, and optional preview.
`--with` applies to a new host only.
Sign in and apply again in the later steps.

Read the log file at the printed path if installation fails.
Remove private data before showing the log's last lines to the user.
Follow the [recovery instructions](docs/install.md#install).

- STOP: if `sudo` asks for a password, the user must type it in the terminal. Never store or echo it.
- Check: `ls ~/Crewship/ship.sh ~/Crewship/.local/host.yml` lists both files, and the installer ended without an error.
- STOP: if the installer prints a web address ([Web pages from anywhere](docs/gateway.md)), the gateway is on. Give the user only that address. Tell the user to get the password without you: read `~/.config/crewship/gateway/initial-password` over SSH, or run `crewship-gateway password` in their own terminal. Never read, print, or relay the password.

### Resume setup

```bash
"$HOME/Crewship/ship.sh" setup
```

Run each printed command, then repeat `setup`.
Follow the remaining steps below for manual approvals and sign-ins.
GitHub and provider sign-ins still need the user's consent.
See [Setup checks](docs/configuration.md#commands) for the reported states and limits.

The commands below also work from any directory on the server.

## 1. Sign in to GitHub

```bash
gh auth status
```

- If it says you are logged in, go to step 2.
- Otherwise run `gh auth login --hostname github.com --git-protocol https --web` in an interactive terminal.
- STOP: let the user answer any prompt about Git credentials.
  Show the one-time code and `https://github.com/login/device` URL printed by `gh`.
  The user opens that URL in a browser on their own computer or phone, enters the code, and approves access.
  A remote server does not need a browser or clipboard.
  If `gh` cannot copy the code or open a browser, copy the displayed code manually and keep the terminal open.
  Press Enter if prompted to continue; wait for `gh` to report success.
- Check: `gh auth status` prints a logged-in account.

## 2. Sign in to omp

omp is the agent harness. Crewship needs a provider login ([Sign in](docs/omp.md#sign-in)).

```bash
omp models --json
```

- If the output lists models, a login exists. Go to step 3.
- Otherwise start `omp` in an interactive terminal and ask the user which provider they use.
- On first run, finish the theme screen first: let the user choose a theme or use the displayed skip option.
  Then use the provider setup screen to select the user's provider.
  Do not type `/login anthropic` into the theme or provider screen; slash commands work at the normal prompt.
- STOP: show the provider's printed login URL and instructions.
  The user opens the URL in their own browser and completes the login.
  If omp asks for a returned code or redirect URL, let the user enter it directly in the terminal.
  Never invent a callback URL or assume that a browser on the user's computer can reach the server's localhost.
- If the wizard was already completed or skipped, use `/login` at the normal prompt to select a provider.
  For Anthropic, use `/login anthropic`.
  Wait for the login to finish, then leave omp before running the check below in the shell.
- Check: `omp models --json` lists at least one model. Never copy a credentials file from another host.

## 3. Review the profiles

`~/Crewship/.local/host.yml` holds the host config. Open it and show the user the `profiles` block. Step 0 already set the user's choices. To change one later, set its key to `true` or `false`.

The full list and the rules between profiles are in [Profiles](docs/configuration.md#profiles).

- STOP: ask the user which profiles to change, if any. Change only the keys the user chose.
- Never put secrets, host names, or personal details in `~/Crewship/.local/host.yml` that the user did not give you.
- Check:

```bash
"$HOME/Crewship/ship.sh" inspect
```

It must print no error. If it names a key, fix that key and run it again.

## 4. Preview the change

```bash
"$HOME/Crewship/ship.sh" chart
```

Follow the [`chart` contract](docs/configuration.md#commands) for preview behavior and side effects.
Tell the user what it would change, in a few lines.

- STOP: ask the user to approve the launch.

## 5. Apply again

The installer already applied the default profiles. This run applies your changes and the new sign-ins.

```bash
"$HOME/Crewship/ship.sh" launch
```

- It may ask for the sudo password. STOP and let the user type it. Never store or echo it.
- Run `"$HOME/Crewship/ship.sh" launch` in an interactive terminal and follow [New-host questions](docs/configuration.md#new-host-questions).
  Relay each question to the user and pass on the answer.
- Follow the [command checks](docs/configuration.md#commands) if `launch` reports a failure.
- Check: the command exits successfully, with no failed task.
  An unchanged `"$HOME/Crewship/ship.sh" launch` reports `changed=0` when no upstream tool has published a new release or source update since the last apply.
  A newer release or source update shows as an expected change in the toolchain step.

## 6. Verify and report

```bash
"$HOME/Crewship/ship.sh" setup
```

- Check: `setup` exits successfully, software and sign-ins report ready, and the enabled Firstmate checks pass.
- Check: with the gateway on, `crewship-gateway url` prints an `https://….trycloudflare.com` address.
- Report each missing step and its printed command.
- Do not mark setup as done while a check fails or a sign-in is missing.
- Check host capacity and run a real agent task before reporting a working fleet.

## Where to look when stuck

- [Configuration](docs/configuration.md): commands, profiles, and the host config
- [Migration and recovery](docs/recovery.md): new devices and upgrades
- [Security](docs/security.md): what you must never copy or export
