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
- The configuration directory `~/.config/crewship/forgejo`, mode 700. It holds `app.ini`, the generated `secret-key`, `internal-token` and `jwt-secret` files, and `admin-password`. Apply writes each secret one time and never prints it.
- An admin account with the name of the target account and a generated password in `admin-password`, mode 600.
- `~/.local/bin/forgejo-github-push` and its post-receive hook. See [GitHub push](#github-push).

When Tailscale runs with HTTPS certificates, `tailscale serve` publishes Forgejo at `https://<tailnet host>:20250/`.
Without HTTPS certificates, apply does not use `tailscale serve`, and Forgejo stays on `http://127.0.0.1:20250/`.
Apply does not change an HTTPS port 20250 that `tailscale serve` gives to a different service; it stops with an error.

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

## GitHub push

`forgejo-github-push` pushes feature branches from a Forgejo repository to GitHub.
It acts only on a repository that you enable:

```sh
forgejo-github-push enable OWNER/REPO https://github.com/OWNER/REPO.git
forgejo-github-push disable OWNER/REPO
```

After each push to an enabled repository, the hook pushes the branches that the push created or updated.
It pushes every branch except `main`, `master` and the repository's default branch, which it reads from the repository `HEAD`.
It force-pushes each branch to the same name on GitHub.
It never pushes `main`, `master`, the default branch, tags or a deletion, so it never deletes a GitHub branch.
The push runs in a transient user unit with three tries and uses the account's git credential helper.
A unit that fails all three tries stays as a failed unit.
To find failed pushes, run `systemctl --user list-units --failed 'forgejo-github-push-*'`; `journalctl --user -u <unit>` shows the error.
`systemctl --user reset-failed 'forgejo-github-push-*'` removes them.

Forgejo mirrors are off, in the web UI and in the API.
A push mirror deletes every GitHub branch that it does not push.
