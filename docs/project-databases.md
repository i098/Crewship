# Project databases

`crewship.profiles.project_databases` is off by default.
The key was called `shared_postgres` before. A host config that still uses that name keeps working, and apply prints a note to rename it.
It gives each project one dev database container of the engine that the project already uses.
All worktrees of the project share that container.
There is no host-wide database.

## Enable

Set these profiles in your host config:

```yaml
crewship:
  profiles:
    docker: true
    firstmate: true
    project_databases: true
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
Apply installs the `crewship-db` helper, records the Firstmate projects directory and enables the seeder timer.
It starts no database. The seeder creates each project's container on its next run.
An unchanged second apply reports no changes for this service.
With `start_services: false`, apply does not start the timer.
Run apply with service starts enabled when the host is ready, or run `crewship-db --seed` yourself.

## Engine and container

The helper reads the project's own compose file (`compose.yaml`, `compose.yml`, `docker-compose.yaml` or `docker-compose.yml`) in a checkout of the project.
It looks at each `image:` line and picks the engine from the image name.
Only official images count: the bare name, `library/<name>` or `docker.io/library/<name>`, plus `pgvector/pgvector` for Postgres:

| Engine | Image names | Variable in `.env.local` |
| --- | --- | --- |
| `postgres` | `postgres`, `pgvector/pgvector` | `DATABASE_URL` (`postgresql://`) |
| `mysql` | `mysql` | `DATABASE_URL` (`mysql://`) |
| `mariadb` | `mariadb` | `DATABASE_URL` (`mysql://`) |
| `redis` | `redis` | `REDIS_URL` |

If the compose file names several engines, the first row of the table wins, so a project with Postgres and Redis gets Postgres.
A project with no supported engine gets no container and no change.
The container runs the image the compose file names, including its tag. An image tag with an unresolved `${VARIABLE}` falls back to the engine's `latest` tag, or `lts` for MySQL and MariaDB.
Any other namespace, such as `bitnami/mysql` or `postgis/postgis`, is unsupported. The helper skips it, prints `unsupported image <image>` on stderr and does not guess another engine, because those images use other environment variables, data paths and start commands.
Add a row to `ENGINES` in `blueprint/fleet/bin/crewship-db` for another engine.

The helper decides the engine, the image and the port once, and writes them to `~/.local/state/code-factory/project-db/<project>/meta.json`.
Later changes to the compose file do not change the container.
To change the image, stop the container and edit `meta.json`. Keep the same engine and a compatible major version.

For each project the helper creates:

| Item | Value |
| --- | --- |
| Container | `crewship-db-<project>` (project name in lower case) |
| Volume | `crewship-db-<project>-data` |
| Port | one free port on `127.0.0.1`, starting at 25432, kept for the life of the project |
| User and database | `app` and `app` (Redis uses a password only) |
| Configuration | `~/.local/state/code-factory/project-db/<project>/compose.json` |

Postgres keeps its cluster in `<mount>/pgdata` on the volume for every major version, so the volume holds the data for images older than 18 too.
Passwords never appear in a process argument list: Redis reads the password from a mode `0600` config file in the container, and the MySQL and MariaDB health check passes it in the environment.
The container uses `restart: unless-stopped`.
The health check waits for the final TCP server, not the temporary server used during initialization.
Compose mounts the password as a file secret; no password enters the repository, command arguments or apply output.
Docker group members and accounts with Docker sudo access can read all container data and secrets.
These services are development databases, not a security boundary between untrusted agents.

## Worktree environment

`crewship-postgres-env-seed.timer` first runs ten seconds after the user service manager starts, then two minutes after each service activation.
Its service runs `crewship-db --seed` to discover checkouts in Treehouse pools and Firstmate project directories.
The seeder reads `root` from `~/.config/treehouse/config.toml` without a login-shell export.
`TREEHOUSE_ROOT`, when nonempty, overrides that setting.
It expands environment variables in the root, then scans `<root>/.treehouse` and the legacy `~/.treehouse` pools.
Unset variables expand to empty text, as they do in Treehouse.
It removes `.` and `..` segments before it resolves symlinks and removes duplicate physical roots.
It scans each physical root once and each physical checkout once per project name, including Firstmate project clones inside either pool location.
Relative roots need a repository context, so the seeder skips them instead of using its current directory.
Repository-local `treehouse.toml` files and per-command `treehouse --root` values are not global discovery settings.
Apply records the configured `<workspace>/firstmate/projects` directory, so custom workspace paths also receive database settings.
It finds each checkout by its `.git` entry and uses the checkout directory name as the project name.
For a linked checkout, the link name stays the project name.
For multiple paths to the same named checkout, it keeps the first path in sorted order.
It ignores names that start with anything but a letter or have more than 48 letters, digits, underscores or hyphens.
Projects with the same directory name share a container, even when they come from different repositories.
The seeder starts or updates one container per project, then writes the project's variable into `.env.local` of every checkout of that project, with mode `0600`.
Every checkout of one project gets the same URL.
The seeder replaces an existing `DATABASE_URL` or `REDIS_URL` but keeps other environment entries.
It skips checkout file errors and continues without recreating removed checkout directories.
If Docker fails for one project, the seeder still serves the other projects, then exits with an error.
Save an existing database URL before you enable this profile.
Do not commit `.env.local` or the password files.
Run `crewship-db --seed` before you start an app when you cannot wait for the timer.

Run `crewship-db example-app [checkout]` to create one project's container now.
The helper uses the known checkouts of `example-app`, or the `checkout` directory you give, to find the engine.
It prints the path of `~/.local/state/code-factory/secrets/project-db/example-app.env`, with mode `0600`, and never the connection string.
Outside the managed directories, copy that file's entry into the app's local environment.
Apps that do not load `.env.local` must load the variable themselves.

## Data and upgrades

Docker named volumes keep the data.
When `data_dir` is set, they sit on the data disk ([Data disk](configuration.md#data-disk)); otherwise they sit in Docker's root.
Passwords stay in `~/.local/state/code-factory/secrets/project-db/<project>.password`, with mode `0600`.
Back up the database and the password file together, and do not delete the password file while you keep the volume.
Apply never removes a volume.
The seeder never pulls a newer image for a tag that is already on the host, so a floating tag such as `latest` stays on its current version until you pull it yourself.
Postgres and MySQL do not automatically upgrade an older data directory.
Before a major upgrade, dump the database with the old image and restore it into a new volume with the new image.

## Migrate from the host-wide Postgres

Earlier releases ran one `crewship-shared-postgres` container with one database per project.
The new seeder does not touch it, but it replaces `DATABASE_URL` in each worktree's `.env.local` with the project's new, empty database. It also removes the old `# crewship-shared-postgres` marker line and the `DATABASE_URL` line under it, even when the project's engine uses another variable.
To keep the data, copy each project's database before the seeder runs, or restore it afterwards:

```sh
# Old database crewship_<project> to the new container. Use sudo -n docker if needed.
docker exec crewship-shared-postgres pg_dump -U postgres --no-owner --no-privileges crewship_example-app \
  | docker exec -i crewship-db-example-app psql -U app -d app
```

Projects with no compose file that names an engine keep their old `DATABASE_URL` until you remove the old container.
After you verify every restore, remove the old service:

```sh
docker compose -f "$HOME/.local/state/code-factory/shared-postgres/compose.json" down
```

Do not stop the seeder: it now serves the project databases.
The `down` command keeps the volume `crewship-shared-postgres-data`.
Delete the volume and `~/.local/state/code-factory/shared-postgres` and `~/.local/state/code-factory/secrets/shared-postgres` only after a verified backup.

## Disable and remove

Set `project_databases: false` and apply to stop managing this profile.
This leaves the existing containers, volumes, timer, environment files and secrets unchanged.
The containers and timer can continue to run; disabling the profile does not stop them.

To stop the seeder and one project's container manually, run these commands as the host owner:

```sh
systemctl --user disable --now crewship-postgres-env-seed.timer
systemctl --user stop crewship-postgres-env-seed.service
docker compose -f "$HOME/.local/state/code-factory/project-db/example-app/compose.json" down
```

Use `sudo -n docker` instead of `docker` if the account has no Docker group access.
The `down` command keeps the named volume.
Remove the helper and seeder units manually if you no longer need them.
Remove the managed `DATABASE_URL` and `REDIS_URL` entries from worktrees before you use another database.

**Warning:** The following command permanently deletes one project's database.
Run it only after you save and verify a backup:

```sh
docker volume rm crewship-db-example-app-data
```

## Verification

Run `bash tests/project-databases-smoke.sh` from the repository to exercise the service tests and Ansible syntax check.
The same command runs in CI.
It creates a disposable privileged Docker-in-Docker container and removes it when the command exits.
The lab receives a read-only repository mount, not the host Docker socket.
All database containers, volumes and Ansible task runs stay inside the lab.
