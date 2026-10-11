# Moving the agents to a new host

This moves the agent fleet (Firstmate homes, secondmate homes, crew lanes, the no-mistakes gate) from an existing host to a new one, for example a bigger host for higher concurrency. The old host does not have to be retired: it can keep everything that is not an agent.

Apply opens this runbook as the default checklist for the [new-host questions](configuration.md#new-host-questions). To follow your own checklist instead, set `firstmate.checklist` in `.local/host.yml`.

## What stays on the old host

Services that hold state other hosts share, such as a model relay, a monitoring stack, or a project database, stay where they are unless you move them on purpose. A second copy splits their state. A project moves its own data only as a deliberate project decision, with a database-aware backup and restore ([App and fleet state](recovery.md#app-and-fleet-state)).
Follow [Shared Postgres](shared-postgres.md) for optional database setup, backups and upgrades.

`~/super.env` is still edited on one host only ([Shared credentials](secrets.md)).

## Warnings

- **Never push a branch that carries credentials or local-only commits.** Before you push any branch from a home, check it does not carry a commit you know holds credentials: `git merge-base --is-ancestor <commit> <branch>` must exit non-zero. To carry local-only commits to the new host, copy them host to host (`git bundle create` and `scp`), never through a forge.
- **The new host joins the tailnet under its own name.** The old host keeps its tailnet name and its `tailscale serve` and Funnel ports while its services stay. After cutover, links to agent-side pages (desktop, noVNC, dev previews) use the new host's name. Never give the new host the old name: Tailscale renames a duplicate, and links would reach the wrong machine.
- **Never run two copies of one home.** Two watchers on one home's state double-dispatch and fight over its inbox. The old home's agents stop only after the new one is confirmed (see [Cutover](#cutover)).

## 1. Provision the new host

1. Follow the [Working on Crewship itself](../CONTRIBUTING.md#working-on-crewship-itself): `onboard.sh`, then `ship.sh` `dock`, `inspect`, `chart`, `launch`, `survey`. In `.local/host.yml`, enable the same profiles as the old host, plus `fleet_browsers` and `desktop`: the fleet-browser sign-in in [What git does not carry](#2-what-git-does-not-carry) needs the browser ladder, and with `desktop` on the default installs `/usr/bin/google-chrome`, which the fleet-browser finds first. The first apply installs omp; until omp has a provider login it skips the questions and prints a line saying to sign in.
2. Sign in to omp ([Sign in](omp.md#sign-in)), then rerun `./ship.sh launch` in an interactive terminal. It opens Firstmate on omp, which asks the move decisions one question at a time. Later applies skip the questions; to open them again, delete `~/.local/share/crewship/new-host-questions-done` and rerun `./ship.sh launch` interactively.
3. Fetch `~/super.env` as described in [Fetch on a new host](secrets.md#fetch-on-a-new-host). Compare its `sha256sum` with the old host's copy.
4. Join the tailnet as a new device ([Remote access](security.md#remote-access)).

## 2. What git does not carry

| Item | How it moves |
| --- | --- |
| omp, gh and other CLI logins | Sign in again on the new host: [Sign in](omp.md#sign-in), `gh auth login`. Never copy a credential store ([Security](security.md)). |
| Fleet-browser web sessions | Sign in again on the new host through the fleet-browser VNC tier: run `~/oss-fleet/browsers/fleet-browser up vnc`, then open noVNC at `http://127.0.0.1:6909/vnc.html?autoconnect=1` over an SSH tunnel (`ssh -L 6909:127.0.0.1:6909 <host>`). `cookie-sync` then shares that session with every tier ([Browser ladder](fleet-guards.md#browser-ladder)). Sign in to Google by hand in the VNC tier; `cookie-sync` keeps Google cookies in that tier only. |
| Each home's `.env` | Enter it by hand on the new host, in a file with mode `600`. |
| Project clones with unpushed commits | List them on the old host with the loop below. Push each branch to its fork, except branches the [Warnings](#warnings) exclude. |
| `data/` and `config/` of the main home (`~/Dev/firstmate`) | `rsync -a` over SSH after `./ship.sh launch`, as the first pass of the cutover sync ([On a new host](security.md#on-a-new-host)). Add `--exclude secondmates.md`: `data/secondmates.md` holds each host's own secondmate home paths, and only that host's provisioning writes it. The next apply rewrites the seeded names in `config/` from this repository ([Seeded Firstmate and OMP configuration](agents/architecture.md#seeded-firstmate-and-omp-configuration)). Never copy any home's `state/`: its records name host-bound Herdr panes, pids and sockets, so [Cutover](#cutover) step 2 empties it of tasks first. |
| Each home's `projects/` clones | Never copied: they are private project working trees ([Never export](security.md#never-export)). After the pushes above, clone each repository the main home has under `projects/` from its `origin` into the same path on the new host, before provisioning the secondmate homes (next row). |
| `data/` and `config/` of every secondmate home | Provision each home on the new host with Firstmate's secondmate-provisioning (`bin/fm-home-seed.sh`), using the id and `projects:` from its line in the old host's `data/secondmates.md`. That clones the listed projects and registers the new home in the new main home's `data/secondmates.md`; a leased treehouse slot usually has a different path than on the old host. Clone any other repository the old home has under `projects/` from its `origin`. Then `rsync -a` the old home's `data/` and `config/` into the path the new registry gives for the same id. |
| Each home's untracked `.omp/mcp.json` and `.omp/rules/` | `rsync -a` them with the home's `data/` and `config/` when they hold no credentials. Then rewrite the home path in `.omp/mcp.json` with the `sed` of the crontab row. |
| no-mistakes | Apply seeds `~/.no-mistakes/config.yaml` with the gate agent. Merge any other settings from the old host's file by hand, without host-specific paths such as `acpx_path`. Then run `no-mistakes init` in every gated clone on the new host that has no `no-mistakes` remote yet (provisioning initializes the clones it makes). List the gated clones on the old host with `python3 -c "import sqlite3; [print(r[0]) for r in sqlite3.connect('file:$HOME/.no-mistakes/state.sqlite?mode=ro', uri=True).execute('select working_path from repos')]"`, and keep only paths that still exist under a home's `projects/`. Do not copy `state.sqlite` or `repos/`. |
| omp settings (`~/.omp/agent/config.yml`) | Apply writes `config/omp.yml` there only when the file is absent, so the new host starts from the seed. Diff the old host's file against the new one and merge by hand ([Updating an existing host](omp.md#updating-an-existing-host)). Review host-specific keys such as `browser.cdpUrl` before merging them. |
| omp plugins and skill roots | Apply installs ponytail, i-have-adhd and caveman and upgrades them to their latest release. For any other plugin the old host lists in `omp plugin list`, run `omp plugin marketplace add` and `omp plugin install`, then confirm with `omp plugin list` on the new host. `rsync -a` the skill roots `~/.omp/agent/skills`, `~/.omp/agent/managed-skills` and `~/.agents/skills`. |
| systemd user units | Apply writes its own. After apply, list what the new host lacks: `comm -23 <(ssh <old host> 'ls ~/.config/systemd/user' \| sort) <(ls ~/.config/systemd/user \| sort)`. Move only agent-side units from that list. Never move units for services that stay on the old host, and never copy a unit or drop-in that holds an inline credential ([Never export](security.md#never-export)). |
| User crontab | Crontab entries and the scripts they run often name a home's path. After every sync of a home's `data/` to a host where its path differs, run `sed -i 's#<old path>#<new path>#g'` on those scripts there. [Cutover](#cutover) comments the entries out on the old host at step 1, adds them with the new path on the new host at step 6, and deletes them on the old host at step 8. |
| Hand-installed tools in `~/.local/bin` | After apply, list what the new host lacks: `comm -23 <(ssh <old host> 'ls ~/.local/bin' \| sort) <(ls ~/.local/bin \| sort)`. Reinstall each agent-side tool from its source and skip backups. |
| omp rules, extensions and custom models (`~/.omp/agent/rules/`, `extensions/`, `models.yml`) | `rsync -a --exclude herdr-omp-agent-state.ts` them from the old host when they hold no credentials. Apply already installed Herdr's own omp extension for the new host's herdr ([Pane state](herdr.md#pane-state)). |
| omp keys and MCP credentials (`~/.omp/agent/*.key`, `mcp.json`) and each home's `state/secrets/` | Never copy them ([Never export](security.md#never-export)). Recreate each on the new host by hand, mode `600`, entering the keys yourself. |
| `ssh mac` access to the operator Mac | Never copy `~/.ssh/id_ed25519_mac`. Apply on the new host generates a new key. Add the new host's line on the Mac, and remove the old host's line at [Cutover](#cutover) step 8 ([Host move](security.md#host-move)). |
| Concord and slk logins (`~/.local/state/concord/`, `~/.local/share/slk/tokens/`) | Never copy them. Sign in again on the new host ([Sign in](chat.md#sign-in)). Apply seeds each client's config only when it is absent, so add slk's `[workspaces.*]` blocks again by signing in. |

```bash
for g in ~/Dev/*/.git ~/Dev/*/projects/*/.git ~/.treehouse/*/*/*/.git ~/.treehouse/*/*/*/projects/*/.git; do
  d=${g%/.git}; c=$(git -C "$d" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) && echo "$c $d"
done | sort -u -k1,1 | while read -r common d; do
  n=$(git -C "$d" log --branches --not --remotes --oneline | wc -l)
  [ "$n" -gt 0 ] && echo "$n unpushed commits: $d"
done
```

## 3. Check the new host matches

CI runs the `agent-gate` check in `tests/container-smoke.sh` for the gate agent, ponytail-review, and tool floors.

| Check | Command on the new host | Pass |
| --- | --- | --- |
| The VNC browser tier finds a Chrome binary | `test -x /usr/bin/google-chrome` | Exit `0`. |
| Crew advisor calls skip the server-side fallback | `grep -A2 '^providers:' ~/Dev/firstmate/config/omp-crew-overlay.yml` | `serverSideFallback: false` under `anthropic:`. |
| ponytail-review runs | `git -C <Crewship checkout> diff HEAD~1 \| ponytail-review --stdin; echo $?` | Exit `0` or `2`, never `1`. |
| no-mistakes gate agent | `no-mistakes --version`, `no-mistakes doctor`, `~/.no-mistakes/omp-as-pi/omp-as-pi --omp-as-pi-check`, `jq -r .agents.omp.command ~/.acpx/config.json`, `grep -c '^acp_registry_overrides' ~/.no-mistakes/config.yaml` | The version in `~/.local/share/crewship/resolved.json`, doctor reports `pi` runnable (or `acp:omp` when the apply kept it), `omp-as-pi: ok`, `omp acp`, `0`. |
| AXI tool floors | `quota-axi --version; tasks-axi --version` | At least the floors in [Dependencies](dependencies.md#latest-releases). |

## Cutover

1. Pause the fleet: tell each home's Firstmate to dispatch nothing new, and comment out the old host's crontab entries.
2. Quiesce every home. First record the main home's secondmates in `data/host-move-secondmates` (first command below): those that run, and those parked, with each hiatus reason. The move never starts a parked secondmate, not even to quiesce its home: tear its home's tasks down from a shell in that home. Then merge, close or tear down (`bin/fm-teardown.sh`, branch kept) every task. A PR waiting on an outside maintainer is torn down too, and re-adopted on the new host when feedback arrives. Then the second command must print nothing (task records, inbox notes, open pending replies other than those to parked secondmates, queued wakes):

   ```bash
   cd ~/Dev/firstmate/state && { grep -lx kind=secondmate *.meta | xargs -r grep -l '^window=' | xargs -r grep -L '^hiatus=' | sed 's/^/running /; s/\.meta$//'; grep -lx kind=secondmate *.meta | xargs -r grep -H '^hiatus=' | sed 's/^/parked /; s/\.meta:hiatus=/ /'; for f in hiatus/*.meta; do [ -e "$f" ] && echo "parked $(basename "$f" .meta) $(head -1 hiatus/README)"; done; } > ../data/host-move-secondmates
   cd ~/Dev/firstmate && for h in . $(sed -n 's/.*home: \([^;]*\);.*/\1/p' data/secondmates.md); do (cd "$h/state" && grep -L '^kind=secondmate$' *.meta; ls inbox | grep -vx handled; grep -L '^phase=\(resolved\|closed_unacknowledged\)$' pending-replies/* | xargs -r grep -Lx -f <(sed -n 's/^parked \([^ ]*\).*/task_id=\1/p' ~/Dev/firstmate/data/host-move-secondmates); cat .wake-queue) 2>/dev/null | sed "s|^|$h: |"; done
   ```

3. Wait for in-flight no-mistakes runs to finish. On the old host, `python3 -c "import sqlite3; print(sqlite3.connect('file:$HOME/.no-mistakes/state.sqlite?mode=ro', uri=True).execute(\"select count(*) from runs where status='running'\").fetchone()[0])"` must print `0`.
4. Run the final sync of `data/`, `config/` and the untracked `.omp/` files for every home, as in the rows of [What git does not carry](#2-what-git-does-not-carry): without `data/secondmates.md`, each secondmate home into the new path registered for its id, and home paths in crontab scripts and `.omp/mcp.json` rewritten as in the crontab row.
5. In the new main home, confirm `bin/fm-home-seed.sh validate` passes and each `home:` in `data/secondmates.md` holds a `.fm-secondmate-home` file that names its id.
6. Start the agents on the new host: the main home first, then, from the main home, each secondmate listed as `running` in `data/host-move-secondmates` that has no `state/<id>.meta` there yet, with `bin/fm-spawn.sh <id> --secondmate`. A `parked` secondmate stays parked on the new host until the operator restarts it by name. Then add the crontab entries with the new home paths.
7. Confirm each home: its watcher (`bin/fm-watch.sh`) is running, and one steer round trip works (`bin/fm-send.sh` from the main home to each secondmate, which acknowledges it).
8. Only then stop the old homes' agents on the old host and delete the commented crontab entries. Services that stay on the old host keep running.

Rollback: first quiesce the new host's homes as in step 2, stop their agents and remove the new host's crontab entries. Before step 8, uncomment the old host's crontab entries and unpause its homes; nothing else on the old host changed. After step 8, sync `data/`, `config/` and the untracked `.omp/` files back from the new host, the same way in reverse (without `data/secondmates.md`, each secondmate home into its old path for the same id, and the home paths rewritten), then restart the old main home and its `running` secondmates as in step 6, and re-add the crontab entries with the old paths.
