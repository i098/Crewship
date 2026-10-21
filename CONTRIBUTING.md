# Contributing to Crewship

## How it works

Crewship is an Ansible playbook with a Python CLI wrapper (`scripts/ship.py`). The source of truth is:

- `blueprint/config/default.yml` — ship defaults (every field the schema requires)
- `blueprint/schemas/crewship.schema.json` — JSON Schema for the host config
- `blueprint/ansible/group_vars/all/*.yml` — Jinja vars consumed by tasks, one file per topic
- `blueprint/ansible/tasks/*.yml` — the tasks themselves (one file per concern)
- `blueprint/ansible/templates/*.j2` — systemd unit templates
- `scripts/ship.py` - CLI; see [Commands](docs/configuration.md#commands)
- `scripts/provisions.py` — latest-release tool installer (idempotent)
- `blueprint/fleet/` — runtime scripts deployed to `~/oss-fleet/` on the target host
- `blueprint/config/` — per-tool config templates deployed to Firstmate homes

## Design rules

Every task is idempotent.
An unchanged `launch` reports `changed=0` when no upstream tool has published a new release or source update since the last apply.
A newer release or source update shows as an expected change in the toolchain step.

Keep every task check-mode safe; follow the [`chart` contract](docs/configuration.md#commands).
Remote-source copies need existing parent directories even in check mode.

Follow [Dependencies](docs/dependencies.md) for tool release selection, download verification, and exceptions.
Only the repository's own development environments (`uv.lock`, `apps/crewboard/Cargo.lock`) stay locked.
CI pins each GitHub Action to the commit SHA of its latest release, kept current by Dependabot.

Do not add unconditional restarts or bare commands.

`start_services: false` suppresses every linger, daemon-reload, and systemd start action while still writing unit files and enabling them via static symlinks.

## Working on Crewship itself

Users install Crewship with the one-line installers in [SETUP.md](SETUP.md). Clone the repository only to change Crewship or to run the playbook from a checkout.

You need Ubuntu 24.04 or 26.04 on x86_64 or aarch64 with systemd, a non-root account with sudo, Python 3.12+, `git`, and `gh`. [`blueprint/cloud-init/user-data.yaml`](blueprint/cloud-init/user-data.yaml) can preinstall the OS packages on first boot.

1. Authenticate GitHub (for private repositories and gh-axi):

   ```bash
   gh auth login
   ```

2. Clone the repository:

   ```bash
   git clone https://github.com/i098/Crewship.git
   cd Crewship
   ```

3. Install the repository tooling (the latest uv, then the locked Python environment with Ansible):

   ```bash
   ./onboard.sh
   ```

4. Create your host config, then review its profiles, user, and paths:

   ```bash
   ./ship.sh dock
   ${EDITOR:-nano} .local/host.yml
   ```

5. Validate the config and preview the changes.
   `chart` uses Ansible check mode; the first config read can rewrite old keys and keep a backup:

   ```bash
   ./ship.sh inspect
   ./ship.sh chart
   ```

6. Launch to provision the host; this step may ask for your sudo password. With the `firstmate` profile on, the first successful interactive apply after you sign in to omp opens the [new-host questions](docs/configuration.md#new-host-questions); a fresh host's first apply installs omp, so sign in to omp after it and rerun apply:

   ```bash
   ./ship.sh launch
   ```

7. Check [setup readiness](docs/configuration.md#commands):

   ```bash
   ./ship.sh setup
   ```

Follow the printed commands and the [manual sign-in steps](SETUP.md#1-sign-in-to-github), then repeat `setup`.
Credentials are never copied from another host; see [Migration and recovery](docs/recovery.md).

## Development

```bash
# Install dev deps
uv sync --group dev

# Lint
uv run ruff check .

# Test, in parallel as CI runs it (the Koncreet apply tests need root or fakeroot; unprivileged without it they skip)
uv run pytest -n auto --dist worksteal

# Ansible syntax check
uv run ansible-playbook -i blueprint/ansible/inventory.yml blueprint/ansible/site.yml --syntax-check
```

See the [CI reference](docs/agents/architecture.md#ci) for documentation-only skips, required check reporting, and event exceptions.

### Testing against Herdr

The operator's Herdr runs the `default` session on the same host, and its workspace labels route Firstmate's work.
A test or smoke must never send a call to that session.

- In pytest, stub `herdr` (put the stub first in `PATH`, or set `HERDR_BIN_PATH`). [`tests/conftest.py`](tests/conftest.py) puts a `herdr` that refuses every call first in `PATH`, so a test without a stub fails and changes nothing.
- For a real Herdr, use a named lab session `fm-lab-*`. Start it with Firstmate's `bin/fm-herdr-lab.sh provision <session>` and remove it with `bin/fm-herdr-lab.sh teardown <session>`.
- Send every other call through [`tests/herdr-lab`](tests/herdr-lab) `<session> <herdr arguments...>`, including `workspace create`, `rename` and `close`. For a script such as the Spaces reporter, set `HERDR_BIN_PATH` to a wrapper that runs `exec env -u HERDR_BIN_PATH <checkout>/tests/herdr-lab <session> "$@"`: `tests/herdr-lab` runs `HERDR_BIN_PATH` itself, so the wrapper must clear it.
  It adds `--session <session>` and clears `HERDR_SOCKET_PATH`. It refuses, before it runs Herdr, a session that is empty, `default` or not `fm-lab-*`, an `HERDR_SESSION` that names another session, a leading option, a `--session` of your own, and `server` or `session` operations.
- [`tests/container-smoke.sh`](tests/container-smoke.sh) runs its real Herdr server in a named `fm-lab-*` session inside the smoke image, and refuses `--in-container` outside that image.
- Do not isolate with `HOME`, `XDG_CONFIG_HOME`, `HERDR_CONFIG_PATH`, `HERDR_SESSION` or an environment file. One call that runs without them reaches the `default` session.

## Adding a new tool

1. Add it to `GITHUB_LATEST` (a GitHub release whose assets carry a SHA-256 digest; when the release publishes its own `<asset>.sha256` files, also list it in `SHA256_FILE` to verify against those) or `NPM_LATEST` in `scripts/provisions.py`. A tool from elsewhere needs its own resolver in `resolve_latest` that reads the checksum its publisher posts for the release.
2. Register where it installs: `crewship_core_tools` in `blueprint/ansible/group_vars/all/tools.yml` for every host, `AGENT_TOOLS` in `scripts/provisions.py` for the `agents` profile's native tools (npm tools in `NPM_LATEST` need no step), or `crewship_installer_also` in `blueprint/ansible/group_vars/all/` for a source Ansible installs itself.
3. If it needs a systemd unit, add a `.j2` template in `blueprint/ansible/templates/` and wire it in the relevant task file.
4. If it needs environment variables, add them to `blueprint/ansible/group_vars/all/` (not to shell rc files).
5. Update `docs/architecture.md` diagrams and `docs/agents/architecture.md` details if the tool changes the host's architecture.
6. Add or update a test in `tests/`.

## Adding a new fleet guard

Fleet guards (`blueprint/fleet/`) are runtime scripts deployed to `~/oss-fleet/` on the box. They are not Ansible modules — they are plain shell/TypeScript that systemd units run.

1. Write the script in `blueprint/fleet/doctor/` or `blueprint/fleet/browsers/`.
2. Add a `.j2` unit template in `blueprint/ansible/templates/`.
3. Wire it in `blueprint/ansible/tasks/fleet_guards.yml` (or `fleet-browsers.yml`).
4. Add guard units to `crewship_fleet_guard_units` and enabled units to `crewship_fleet_guard_enabled_units` in `blueprint/ansible/group_vars/all/fleet.yml`.
   Use `crewship_fleet_browser_units` and `crewship_fleet_browser_enabled_units` for the browser ladder.
5. Update `docs/fleet-guards.md`.

## Commits and branches

Commits follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/):

- The subject line is `type(scope): subject`. The type is `feat`, `fix`, `docs`, `refactor`, `test`, `ci`, or `chore`; the scope is optional.
- Mark a breaking change with `!` after the type or scope, or with a `BREAKING CHANGE:` footer.
- Write the subject in the imperative, in 72 characters or fewer, with no period at the end.
- Wrap the body at 72 characters and tell why the change is necessary.

A good commit:

```text
fix(provisions): check the digest before install

The installer moved the binary into place and then checked its
SHA-256 digest. A bad download could replace a good tool before
the check failed. Check the digest first and stop on a mismatch.
```

Branch names are `type/short-description`, with a type from the list above, for example `feat/one-command-install`.

## Issues

These issue and pull request rules apply to people and agents.
Use a plain sentence-case issue title, such as `Explain the fresh-server install requirements`.
Do not use a commit prefix such as `docs:` in an issue title.

Use the [bug report](.github/ISSUE_TEMPLATE/bug_report.yml) or [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) form:

| Form | Label | Required fields | Optional fields |
| --- | --- | --- | --- |
| Bug report | `bug` | `what-happened`, `steps`, `version` | `host`, `logs` |
| Feature request | `enhancement` | `problem`, `proposal` | None |

For bugs, describe the actual and expected results, reproduction commands, and the release tag or commit.
Include the operating system and logs when useful; remove secrets first.
For features, describe the problem and the proposed change.
Ask questions in [Discussions Q&A](https://github.com/i098/Crewship/discussions/categories/q-a), not an issue.

Agents must use `scripts/new-issue`; people can use it or the web forms.
Run these examples from the repository with the development dependencies installed:

```bash
uv run scripts/new-issue bug --title "The installer stops before setup" \
  --field "what-happened=Setup stops; I expected it to finish." \
  --field "steps=Run the README install command on a fresh server." \
  --field "version=vX.Y.Z" --field "host=Ubuntu 24.04" --dry-run

uv run scripts/new-issue feature --title "Explain the fresh-server install requirements" \
  --field "problem=New users cannot find the server requirements." \
  --field "proposal=List the requirements before the install command." --dry-run
```

Replace the example values with observed facts.
Review the printed title, labels, and body, then remove `--dry-run` to create the issue.
Use `--field logs=@/path/to/redacted-log.txt` to read a field from a file.
The script applies the form's label and rejects missing required fields or commit-prefixed titles.

## Pull requests

- One concern per PR.
- The title uses the commit format, for example `docs(contributing): add git conventions and branch rules`.
- The body starts with `Closes #N` for the issue that the PR resolves. The [PR template](.github/PULL_REQUEST_TEMPLATE.md) fills in the other sections.
  Put the opening reference on its own line, outside a code block.
  Fill all four template sections: `Summary`, `What changed and why`, `Test evidence`, and `Checklist`.
  Name the commands you ran and their results under `Test evidence`; do not claim checks you did not run.
  Keep each checklist item and mark completed items with `[x]`.
  Leave an inapplicable item unchecked and explain why beside it, such as `Not applicable: no Ansible files changed`.
  Use visible text in sections and reasons; comments, empty markup, link definitions, and whitespace entities alone do not count.
  Inline and fenced code can supply content.
- Tests pass (`uv run pytest`).
- Lint clean (`uv run ruff check`).
- Ansible syntax clean (`--syntax-check`).
- Idempotent: an unchanged second `launch` reports `changed=0` when no upstream tool has published a new release or source update since the last apply.
  A newer release or source update shows as an expected change in the toolchain step.
- Describe what changed and why in the PR body.
- Add a changelog fragment, `changelog.d/<issue>.<type>.md`, and never edit [CHANGELOG.md](CHANGELOG.md) (see [Changelog and releases](#changelog-and-releases)). Fragments are separate files, so PRs that run at the same time do not conflict. CI fails a PR without a fragment, unless the PR has the `no changelog` label.
- PRs merge with a merge commit; squash and rebase merging are off.

The no-mistakes pipeline uses `.github/PULL_REQUEST_TEMPLATE.md` through `.no-mistakes.yaml`.
It omits generated intent and puts validation evidence in a collapsed section after the public body.
The pipeline reads these settings from the default branch.

The required `pull request body` check validates the opening issue reference, filled sections, and completed or explained checklist items.
It runs for every PR, including Dependabot and release PRs.
Body edits rerun this small check without restarting the full build.
Check a body file before publication:

```bash
python3 scripts/check_pr_body.py /tmp/pr-body.md
```

## Branch rules

GitHub rulesets enforce these rules, with no bypass:

- `main` changes only through a pull request.
  Before a merge, `pull request body`, `configuration and python checks`, `quality gate`, and `worker image behavior smoke` must pass or report an allowed skip.
  See the [CI reference](docs/agents/architecture.md#ci) for skip conditions.
  No approval is necessary.
- `main` cannot be force-pushed or deleted.
- GitHub deletes the head branch after the merge.
- A `v*` tag cannot be deleted or moved.

## Changelog and releases

[CHANGELOG.md](CHANGELOG.md) follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html). Releases are [GitHub releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) on `vX.Y.Z` tags.

1. Every PR adds one fragment file, `changelog.d/<issue>.<type>.md`, where `<issue>` is the number of the issue it resolves and `<type>` is the section that fits: `added`, `changed`, `deprecated`, `removed`, `fixed`, or `security`. The file holds one sentence, without the issue link; the release step adds the link. For example, `changelog.d/58.fixed.md`:

   ```text
   `scripts/stow-secrets.sh` no longer fails once `super.env` has more than 100 variables.
   ```

   A PR with nothing to note, for example a test-only change, gets the `no changelog` label instead.
2. To cut a release, run `uv run towncrier build --version X.Y.Z` on a new branch and open a PR with the result. The command writes a new `## [X.Y.Z] - YYYY-MM-DD` section (today's ISO 8601 date) under `## [Unreleased]` in Keep a Changelog order and deletes the fragments it used; `uv run towncrier build --draft --version X.Y.Z` shows the section first and changes nothing. In the same PR, update the link references at the bottom of the file and set `version` in `tools/npm/package.json` to `X.Y.Z`. Bump the patch number for every release, and batch changes; release at most once per day.

   Bump the minor or major number only with the owner's approval.
3. After that PR merges, tag its merge commit on `main` as `vX.Y.Z`. Never move or reuse a published tag.
4. Create a **draft** GitHub release for the tag, named `vX.Y.Z`, with that version's changelog section as the notes, for example `gh release create vX.Y.Z --draft --verify-tag --title vX.Y.Z --notes-file <section.md>`. Releases are immutable, so the install artifact must be on the draft before it is published: run `gh workflow run release-artifact.yml -f tag=vX.Y.Z` (or `scripts/build-release-artifact.sh vX.Y.Z dist` and `gh release upload vX.Y.Z dist/*`), then check the draft lists `crewship-vX.Y.Z.tar.gz` and its `.sha256`. `install.sh` installs the source archive of the tag when a release has no artifact, but the artifact adds the checksum check.
5. Publish the draft (`gh release edit vX.Y.Z --draft=false`). Publishing the release runs `.github/workflows/npm-publish.yml`, which publishes the `crewship` npm package as version `X.Y.Z`. The workflow fails before the publish when `tools/npm/package.json` does not have that version.
6. The release starts the `release-image` workflow. It builds the `worker` image and pushes it to the GitHub Container Registry as `ghcr.io/i098/crewship:X.Y.Z` and `ghcr.io/i098/crewship:latest`. When the package is public, anyone can pull it without a login: `docker pull ghcr.io/i098/crewship:X.Y.Z`.

   The first push creates the package as private, and the REST API cannot change package visibility. Do this one time: on the [crewship package](https://github.com/users/i098/packages/container/package/crewship), click **Package settings**, then under **Danger Zone** click **Change visibility**, select **Public**, and confirm with the package name.
