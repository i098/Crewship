# Set up Crewship (for an AI agent)

You are an AI agent. A user has a fresh Ubuntu machine and asked you to set up Crewship on it. Do the steps below in order. Run each command yourself. Stop and ask the user where a step says STOP. Never guess a login, a code, or a choice.

You need Ubuntu 24.04 or 26.04 with systemd, and a non-root account that has sudo. Check with `lsb_release -rs`, `id -u` (not 0), and `sudo -n true`. If the machine does not fit, STOP and tell the user.

Report each result to the user in one line. If a command fails, show its last lines, then fix it or ask. Do not skip a step to hide a failure.

## Setup flow

```mermaid
flowchart TD
    box["Fresh Ubuntu 24.04 or 26.04"] --> boot["./onboard.sh: latest uv, Ansible"]
    boot --> init["./ship.sh dock: writes .local/host.yml"]
    init --> check["./ship.sh inspect, then chart"]
    check --> apply["./ship.sh launch"]
    lock["toolchain: latest releases, checksum-verified (omp plugins excepted)"] --> apply
    apply --> profiles["Ansible profiles"]
    subgraph host["Finished host"]
        herdr["Herdr workspace"]
        fm["Firstmate orchestrator"]
        agents["omp agents"]
        guards["Fleet guards"]
        docker["Docker engine"]
        chat["Concord and slk chat clients"]
        gateway["Password gateway and Cloudflare tunnel"]
    end
    profiles --> herdr
    profiles --> fm
    profiles --> agents
    profiles --> guards
    profiles --> docker
    profiles --> chat
    profiles --> gateway
```

## 0. Choose features and install Crewship

Crewship installs a core, the omp agents and Firstmate. Everything else is opt-in and off until the user chooses it. `docker` comes with `fleet_guards` and `shared_postgres`, and `development` comes with `board`.

- STOP: show the user this checklist and ask which names to turn on. The default is none.

| Name | Adds |
| --- | --- |
| `public_skills` | the public skills and rules for omp and Claude Code ([Skills](docs/omp.md#skills)) |
| `development` | the Rust toolchain and build tools |
| `docker` | the Docker engine and Compose |
| `chat` | the Discord and Slack terminal clients |
| `gateway` | one password for the host's web pages over a Cloudflare Quick Tunnel ([Web pages from anywhere](docs/gateway.md)) |
| `fdu` | fdu, a fast gitignore-aware `du` for large worktrees |
| `fleet_guards` | Docker guard, dev-server reaper, storage guard, browser ladder |
| `shared_postgres` | one dev database container per project, in the engine its compose file names |
| `jj` | the Jujutsu (`jj`) version control tool for agents, colocated with git ([Jujutsu](docs/jj.md)) |
| `fleet_browsers` | the browser ladder only |
| `tailscale` | the Tailscale daemon (login is manual); an option beside the gateway |
| `koncreet` | the Koncreet host hardening toolkit, installed as root and never run ([Security](docs/security.md#host-hardening)) |
| `desktop` | a loopback-only XFCE desktop over noVNC |
| `board` | the crew message board ([Board](docs/board.md)); it brings `development` |

Run the installer with the chosen names, comma separated. Use `--with none` for none. You have no terminal for the installer's own checklist, so always pass `--with`:

```bash
curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash -s -- --with public_skills,docker
```

`bunx crewship` does the same when bun is installed; `npx crewship` and `pnpm dlx crewship` work too. Do not clone the repository.

The installer installs the OS packages, downloads and verifies the latest release into `~/Crewship`, and runs `onboard.sh`, `ship.sh dock --with …`, `inspect`, `chart`, and `launch` ([Install, update and migrate](docs/install.md)). `--with` applies to a new host only. The later steps sign in, then apply again.

- STOP: if `sudo` asks for a password, the user must type it in the terminal. Never store or echo it.
- Check: `ls ~/Crewship/ship.sh ~/Crewship/.local/host.yml` lists both files, and the installer ended without an error.
- STOP: if the installer's output ends with a web address ([Web pages from anywhere](docs/gateway.md)), the gateway is on. Give the user only that address. Tell the user to get the password without you: read `~/.config/crewship/gateway/initial-password` over SSH, or run `crewship-gateway password` in their own terminal. Never read, print, or relay the password.
- Then run `cd ~/Crewship` for every later step.

## 1. Sign in to GitHub

```bash
gh auth status
```

- If it says you are logged in, go to step 2.
- Otherwise run `gh auth login`.
- STOP: the user must choose the options and finish the browser or device-code step. Show the one-time code and the URL that `gh` prints. Wait until the user says the login is done.
- Check: `gh auth status` prints a logged-in account.

## 2. Sign in to omp

omp is the agent harness. Crewship needs a provider login ([Sign in](docs/omp.md#sign-in)).

```bash
omp models --json
```

- If the output lists models, a login exists. Go to step 3.
- Otherwise start `omp`, and ask the user which provider they use. For Anthropic, type `/login anthropic`. `/login` with no argument lists every provider.
- STOP: the user must finish the browser or device-code step. Show the URL or code that omp prints. Wait until the user says it is done.
- Check: `omp models --json` lists at least one model. Never copy a credentials file from another host.

## 3. Review the profiles

`.local/host.yml` holds the host config. Open it and show the user the `profiles` block. Step 0 already set the user's choices. To change one later, set its key to `true` or `false`.

The full list and the rules between profiles are in [Profiles](docs/configuration.md#profiles).

- STOP: ask the user which profiles to change, if any. Change only the keys the user chose.
- Never put secrets, host names, or personal details in `.local/host.yml` that the user did not give you.
- Check:

```bash
./ship.sh inspect
```

It must print no error. If it names a key, fix that key and run it again.

## 4. Preview the change

```bash
./ship.sh chart
```

This runs Ansible in check mode and changes nothing. Tell the user what it would change, in a few lines.

- STOP: ask the user to approve the launch.

## 5. Apply again

The installer already applied the default profiles. This run applies your changes and the new sign-ins.

```bash
./ship.sh launch
```

- It may ask for the sudo password. STOP and let the user type it. Never store or echo it.
- Run it in an interactive terminal. With the `firstmate` profile on and omp signed in, the first launch then opens omp with the new-host questions ([New-host questions](docs/configuration.md#new-host-questions)). Relay each question to the user and pass on the answer.
- If omp was not signed in at the first launch, the questions are skipped. Run `./ship.sh launch` again after step 2.
- Check: the command ends with no failed task. A second `./ship.sh launch` reports `changed=0`.

## 6. Verify and report

```bash
./ship.sh survey
```

- Check: each expected tool runs, and `gh` shows as authenticated.
- Check: with the gateway on, `crewship-gateway url` prints an `https://….trycloudflare.com` address.
- Tell the user what passed and what failed, and which step to repeat for each failure.
- Do not mark the setup as done while a check fails.

## Where to look when stuck

- [Configuration](docs/configuration.md): commands, profiles, and the host config
- [Migration and recovery](docs/recovery.md): new devices and upgrades
- [Security](docs/security.md): what you must never copy or export
