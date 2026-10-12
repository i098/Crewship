# Shared Postgres

`crewship.profiles.shared_postgres` is off by default.
It adds one official Postgres container for all project lanes on a host.

## Enable

Set these profiles in your host config:

```yaml
crewship:
  profiles:
    docker: true
    firstmate: true
    shared_postgres: true
```

Before convergence, give the configured target account explicit Docker access by an administrator's choice.
The helper requires a writable `/var/run/docker.sock` or working `sudo -n docker` access, and a running Docker daemon.
Both options give root-equivalent access; Crewship grants neither by default.
If you explicitly configure `crewship_docker_group_users`, start a new login session before you apply this profile.
Run `python3 blueprint/fleet/bin/crewship-db --check-docker` from the repository as the target account to check access without changing resources.
The profile checks this prerequisite before convergence, including previews and deferred service starts.
Project creation and automatic seeding use the same account and require the same access.

Run `./ship.sh chart` to preview, then `./ship.sh launch` to apply.
Follow [New-host questions](configuration.md#new-host-questions) for guided setup.
An unchanged second apply reports no changes for this service.
With `start_services: false`, apply writes the configuration, secrets and enabled timer but does not pull images or start services.
Run apply with service starts enabled when the host is ready.

The container is `crewship-shared-postgres`.
It publishes only `127.0.0.1:25432`, uses `restart: unless-stopped`, and stores data in `crewship-shared-postgres-data`.
See [Container images](dependencies.md#container-images) for the image and pull policy.
The health check waits for the final TCP server, not the temporary Unix-socket server used during initialization.
The configuration is `~/.local/state/code-factory/shared-postgres/compose.json`.
The superuser password is generated once in `~/.local/state/code-factory/secrets/shared-postgres/superuser`, with mode `0600`.
Compose mounts that password as a file secret; no password enters the repository, command arguments or apply output.
Docker group members and accounts with Docker sudo access can read all container data and secrets.
This service is a development database, not a security boundary between untrusted agents.

## Project databases

Run `crewship-db example-app` to create a project's role and database and print its environment file path.
Project names start with a letter and contain at most 48 letters, digits, underscores or hyphens.
Names are case-sensitive.
The role and database both use the name `crewship_<project>`.
The helper creates missing objects and keeps the same password on later calls.
A host file lock serializes concurrent requests.
Each project role owns its database, has no superuser or database-creation rights, and cannot connect to other project databases.
Lanes of the same project share the same role and database.
Projects with the same directory name share a database, even when they come from different repositories.

Project passwords stay in `~/.local/state/code-factory/secrets/shared-postgres/<project>.password`, with mode `0600`.
Do not delete these files while you keep the volume.
The helper writes `DATABASE_URL` to `~/.local/state/code-factory/secrets/shared-postgres/<project>.env`, with mode `0600`.
The helper prints only that file's path, never the connection string.

## Worktree environment

`crewship-postgres-env-seed.timer` first runs ten seconds after the user service manager starts, then two minutes after each service activation.
Its service runs `crewship-db --seed` to discover checkouts in Treehouse pools and Firstmate project directories.
Apply records the configured `<workspace>/firstmate/projects` directory, so custom workspace paths also receive database settings.
It finds each checkout by its `.git` entry and uses the checkout directory name as the project name.
It ignores names that do not meet the helper's name rules.
It writes `DATABASE_URL` into `.env.local`, with mode `0600`.
The seeder replaces an existing `DATABASE_URL` but keeps other environment entries.
The seeder skips checkout file errors and continues without recreating removed checkout directories.
Lock, credential, and database errors remain fatal.
Save an existing database URL before you enable this profile.
Do not commit `.env.local` or the password files.
Run `crewship-db --seed` before you start an app when you cannot wait for the timer.
Outside these managed directories, copy the environment file returned by `crewship-db <project>` into the app's local environment.
Apps that do not load `.env.local` must load `DATABASE_URL` themselves.

## Data and upgrades

Back up the database and password files together.
Apply never removes the data volume.
The latest image can change the Postgres major version.
Postgres does not automatically upgrade an older data directory; a new major version can prevent the container from starting.
Before a major upgrade, dump the databases with the old image and restore them into a new volume with the new image.
Keep the old volume until you verify the restore.
No automatic migration or data deletion runs here.

## Disable and remove

Set `shared_postgres: false` and apply to stop managing this profile.
This leaves the existing container, volume, timer, environment files and secrets unchanged.
The container and timer can continue to run; disabling the profile does not stop them.

To stop the service manually, run these commands as the host owner:

```sh
systemctl --user disable --now crewship-postgres-env-seed.timer
systemctl --user stop crewship-postgres-env-seed.service
docker compose -f "$HOME/.local/state/code-factory/shared-postgres/compose.json" down
```

Use `sudo -n docker` instead of `docker` if the account has no Docker group access.
The `down` command above keeps the named volume.
Remove the helper and seeder units manually if you no longer need them.
Remove the managed `DATABASE_URL` entries from worktrees before you use another database.

**Warning:** The following command permanently deletes every project database in this volume.
Run it only after you save and verify a backup:

```sh
docker volume rm crewship-shared-postgres-data
```

## Verification

Run `bash tests/shared-postgres-smoke.sh` from the repository to exercise the service tests and Ansible syntax check.
The same command runs in CI.
It creates a disposable privileged Docker-in-Docker container and removes it when the command exits.
The lab receives a read-only repository mount, not the host Docker socket.
All database containers, volumes and Ansible task runs stay inside the lab.
