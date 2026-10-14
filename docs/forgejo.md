# Self-hosted Forgejo

`crewship.profiles.forgejo` is off by default.
It runs a Forgejo git server for the target account on the agent host.
It does not move a repository to Forgejo.

## Enable

Set the profile in your host config:

```yaml
crewship:
  profiles:
    forgejo: true
```

Run `./ship.sh chart` to preview, then `./ship.sh launch` to apply.
When you set the profile to `false`, apply stops changes to Forgejo.
The service, its data and its secrets stay on the host.

## What apply installs

- The latest Forgejo release from Codeberg in `~/.local/share/crewship/forgejo/<version>/forgejo`. Apply verifies it against its `.sha256` file and its signature by the Forgejo release key, primary fingerprint `EB114F5E6C0DC2BCDD183550A4B61A2DC5923710`.
- The user units `forgejo.service`, `forgejo-dump.service` and `forgejo-dump.timer`. Forgejo uses SQLite and listens on `127.0.0.1:20250` only.
- The work directory `~/.local/share/forgejo`, with the database and the repositories in `data/`.
- The configuration directory `~/.config/crewship/forgejo`, mode 700. It holds `app.ini`, the generated `secret-key`, `internal-token` and `jwt-secret` files, `admin-password` and, with the `agents` profile, `no-mistakes.env`. Apply writes each secret one time and never prints it.
- An admin account with the name of the target account and a generated password in `admin-password`, mode 600.
- `~/.local/bin/forgejo-github-push` and its post-receive hook. See [GitHub push](#github-push).
- With the `agents` profile, the no-mistakes Forgejo setup. See [no-mistakes](#no-mistakes).

When Tailscale runs with HTTPS certificates, `tailscale serve` publishes Forgejo at `https://<tailnet host>:20250/`.
Without HTTPS certificates, apply does not use `tailscale serve`, and Forgejo stays on `http://127.0.0.1:20250/`.
Apply does not change an HTTPS port 20250 that `tailscale serve` gives to a different service; it stops with an error.
Clone URLs and pull request links use the published URL, or the loopback URL without it.
Apply never uses Funnel, so Forgejo is never on the public internet.

## Admin password recovery

Apply stops when the admin account exists but `admin-password` does not.
To recover, set a new password and save it in that file.
Run these commands as the target account; replace `<version>`:

```sh
cd ~/.config/crewship/forgejo
umask 077
head -c 24 /dev/urandom | base64 > admin-password
~/.local/share/crewship/forgejo/<version>/forgejo --config ~/.config/crewship/forgejo/app.ini \
  --work-path ~/.local/share/forgejo admin user change-password \
  --username "$USER" --password "$(cat admin-password)" --must-change-password=false
```

Then run apply again.

## Backups

`forgejo-dump.timer` runs `forgejo dump` every night at about 03:30.
The dump goes to `<data_dir>/forgejo-dumps` when `crewship.data_dir` is set, else to `~/.local/share/forgejo/dumps`.
Each run writes `forgejo-dump-<time>.tar.zst` and `forgejo-dump-<time>.secrets.tar` beside it, both mode 600.
The dump does not hold the secret files, so a restore needs the secrets tar with the dump.
Put the files from the secrets tar back into `~/.config/crewship/forgejo` with mode 600.
The timer keeps the newest 7 dumps and secrets tars. A failed dump removes nothing and leaves no partial files.
If a dump is stopped while it runs, the next run removes its temporary files.

Before a new Forgejo release first starts, apply runs `forgejo-dump.service` one time with the installed release.
The new release changes the database on its first start, and an older release cannot open the result.
If that dump fails, apply stops and Forgejo keeps the installed release.
`journalctl --user -u forgejo-dump.service` shows the error.

## no-mistakes

Apply installs `forgejo-axi` on every host with the `agents` profile, also without the Forgejo profile.
no-mistakes uses it for Forgejo pull requests and CI.

With the Forgejo profile and the `agents` profile, apply also does these steps:

- It creates the Forgejo token `crewship-no-mistakes` one time, with the scopes `write:repository`, `write:issue`, `read:user` and `read:organization`.
  It writes the token as `FORGEJO_TOKEN` to `~/.config/crewship/forgejo/no-mistakes.env`, mode 600.
- It writes the drop-in `~/.config/systemd/user/no-mistakes-daemon-.service.d/forgejo.conf`.
  The drop-in sets `FORGEJO_BASE_URL` to the Forgejo URL and loads `no-mistakes.env`.

Apply never restarts the no-mistakes daemon, because a restart stops the pipeline runs in progress.
The daemon loads the drop-in only after a restart.
When no pipeline run is active, run `no-mistakes daemon restart`.

Apply creates the token only when `no-mistakes.env` does not exist.
Forgejo refuses a second token with the name `crewship-no-mistakes`, so a removed file alone stops apply at the token task.
To make a new token, do these steps:

1. Sign in to Forgejo as the admin account, with the password in `admin-password`.
2. Delete the token `crewship-no-mistakes` in **Settings** > **Applications**.
3. Remove `~/.config/crewship/forgejo/no-mistakes.env`.
4. Run apply again, then restart the no-mistakes daemon.

## GitHub push

`forgejo-github-push` pushes feature branches from a Forgejo repository to GitHub.
It acts only on a repository that you enable:

```sh
forgejo-github-push enable OWNER/REPO https://github.com/OWNER/REPO.git
forgejo-github-push disable OWNER/REPO
```

After each push to an enabled repository, the hook pushes the branches that the push created or updated.
It pushes every branch except `main`, `master` and the repository's default branch, which it reads from the repository `HEAD`.
It pushes each branch to the same name on GitHub with a lease on the commit that it pushed last for that branch, or on no branch for a new one.
So a rebased or amended branch replaces what the hook pushed before, but a commit that exists only on GitHub is never overwritten.
It never pushes `main`, `master`, the default branch, tags or a deletion, so it never deletes a GitHub branch.
The push runs in a transient user unit and uses the account's git credential helper.
The units of one repository push one at a time.
When GitHub has a commit that the Forgejo branch does not contain, for example from "Update branch", a review suggestion or a web edit, the lease fails and the unit fails.
Until the branch contains that commit, each push of the branch prints a warning and the hook does not push it; `git fetch <GitHub URL> <branch> && git merge FETCH_HEAD` merges it.
When the GitHub branch no longer exists, for example after its PR merged, the hook pushes it again as a new branch.
When the GitHub branch is only behind the Forgejo branch, for example on a branch that existed before `enable`, the hook pushes it again with a lease on the GitHub commit.
The hook keeps its state in the repository's git config, as `crewship-github.<branch>.pushed` and `crewship-github.<branch>.ahead`.
Other push errors get three tries, and a unit that fails all three tries stays as a failed unit.
To find failed pushes, run `systemctl --user list-units --failed 'forgejo-github-push-*'`; `journalctl --user -u <unit>` shows the error.
`systemctl --user reset-failed 'forgejo-github-push-*'` removes them.

Forgejo mirrors are off, in the web UI and in the API.
A push mirror deletes every GitHub branch that it does not push.

## Security

Forgejo runs as `crewship.user`, the account that also runs the agents.
Every agent can read the admin password, the token and the database, so Forgejo is not a security boundary between agents on this host.
It is a working remote that keeps the agents' git traffic off GitHub.

## Turn it off

Set `forgejo: false` and apply.
Apply then stops managing Forgejo: the service, its data, its secrets and the `tailscale serve` entry stay as they are.
To remove Forgejo, stop and disable `forgejo.service` and `forgejo-dump.timer`, delete their unit files, the drop-in and `~/.local/bin/forgejo-github-push`, and run `sudo tailscale serve --https=20250 off`.
Then delete the directories in [What apply installs](#what-apply-installs) after you keep a backup.
