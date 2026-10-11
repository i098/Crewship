# Contributing to Crewship

## How it works

Crewship is an Ansible playbook with a Python CLI wrapper (`scripts/ship.py`). The source of truth is:

- `config/default.yml` — ship defaults (every field the schema requires)
- `schemas/crewship.schema.json` — JSON Schema for the host config
- `ansible/group_vars/all.yml` — Jinja vars consumed by tasks
- `ansible/tasks/*.yml` — the tasks themselves (one file per concern)
- `ansible/templates/*.j2` — systemd unit templates
- `scripts/ship.py` — CLI (`dock`, `inspect`, `chart`, `launch`, `survey`)
- `scripts/provisions.py` — latest-release tool installer (idempotent)
- `fleet/` — runtime scripts deployed to `~/oss-fleet/` on the target host
- `config/` — per-tool config templates deployed to Firstmate homes

## Design rules

Every task is idempotent; a second unchanged `launch` reports `changed=0`.

Every task is check-mode safe: `chart` (Ansible `--check`) previews without mutating.

Follow [Dependencies](docs/dependencies.md) for tool release selection, download verification, and exceptions.
Only the repository's own development environments (`uv.lock`, `crewboard/Cargo.lock`) stay locked.
CI pins each GitHub Action to the commit SHA of its latest release, kept current by Dependabot.

No unconditional restarts, daemon-reloads, or bare commands.

`start_services: false` suppresses every linger, daemon-reload, and systemd start action while still writing unit files and enabling them via static symlinks.

## Development

```bash
# Install dev deps
uv sync --group dev

# Lint
uv run ruff check scripts tests

# Test (the Koncreet apply tests need root or fakeroot; unprivileged without it they skip)
uv run pytest

# Ansible syntax check
uv run ansible-playbook -i ansible/inventory.yml ansible/site.yml --syntax-check

# Full CI (runs all of the above + Docker worker smoke)
./scripts/ci-local.sh
```

## Adding a new tool

1. Add it to `GITHUB_LATEST` (a GitHub release whose assets carry a SHA-256 digest; when the release publishes its own `<asset>.sha256` files, also list it in `SHA256_FILE` to verify against those) or `NPM_LATEST` in `scripts/provisions.py`. A tool from elsewhere needs its own resolver in `resolve_latest` that reads the checksum its publisher posts for the release.
2. Register where it installs: `crewship_core_tools` in `group_vars/all.yml` for every host, `AGENT_TOOLS` in `scripts/provisions.py` for the `agents` profile's native tools (npm tools in `NPM_LATEST` need no step), or `crewship_installer_also` in `group_vars/all.yml` for a source Ansible installs itself.
3. If it needs a systemd unit, add a `.j2` template in `ansible/templates/` and wire it in the relevant task file.
4. If it needs environment variables, add them to `group_vars/all.yml` (not to shell rc files).
5. Update `docs/architecture.md` diagrams and `docs/agents/architecture.md` details if the tool changes the host's architecture.
6. Add or update a test in `tests/`.

## Adding a new fleet guard

Fleet guards (`fleet/`) are runtime scripts deployed to `~/oss-fleet/` on the box. They are not Ansible modules — they are plain shell/TypeScript that systemd units run.

1. Write the script in `fleet/doctor/` or `fleet/browsers/`.
2. Add a `.j2` unit template in `ansible/templates/`.
3. Wire it in `ansible/tasks/fleet_guards.yml` (or `fleet-browsers.yml`).
4. Add guard units to `crewship_fleet_guard_units` and enabled units to `crewship_fleet_guard_enabled_units` in `ansible/group_vars/all.yml`.
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

## Pull requests

- One concern per PR.
- The title uses the commit format, for example `docs(contributing): add git conventions and branch rules`.
- The body starts with `Closes #N` for the issue that the PR resolves. The [PR template](.github/PULL_REQUEST_TEMPLATE.md) fills in the other sections.
- Tests pass (`uv run pytest`).
- Lint clean (`uv run ruff check`).
- Ansible syntax clean (`--syntax-check`).
- Idempotent: `launch` → `launch` = `changed=0` on the second run.
- Describe what changed and why in the PR body.
- Add a changelog fragment, `changelog.d/<issue>.<type>.md`, and never edit [CHANGELOG.md](CHANGELOG.md) (see [Changelog and releases](#changelog-and-releases)). Fragments are separate files, so PRs that run at the same time do not conflict. CI fails a PR without a fragment, unless the PR has the `no changelog` label.
- PRs merge with a merge commit; squash and rebase merging are off.

Open an issue with the [bug report](.github/ISSUE_TEMPLATE/bug_report.yml) or the [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) form. Ask questions in the [Discussions Q&A category](https://github.com/i098/Crewship/discussions/categories/q-a) ([SUPPORT.md](SUPPORT.md)).

## Branch rules

GitHub rulesets enforce these rules, with no bypass:

- `main` changes only through a pull request. Before a merge, the checks `configuration and python checks`, `quality gate`, and `worker image behavior smoke` must pass. No approval is necessary.
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
2. To cut a release, run `uv run towncrier build --version X.Y.Z` on a new branch and open a PR with the result. The command writes a new `## [X.Y.Z] - YYYY-MM-DD` section (today's ISO 8601 date) under `## [Unreleased]` in Keep a Changelog order and deletes the fragments it used; `uv run towncrier build --draft --version X.Y.Z` shows the section first and changes nothing. In the same PR, update the link references at the bottom of the file and set `version` in `npm/package.json` to `X.Y.Z`. Bump the patch number for every release, and batch changes; release at most once per day.

   Bump the minor or major number only with the owner's approval.
3. After that PR merges, tag its merge commit on `main` as `vX.Y.Z`. Never move or reuse a published tag.
4. Publish a GitHub release for the tag, named `vX.Y.Z`, with that version's changelog section as the notes, for example `gh release create vX.Y.Z --target <merge-sha> --title vX.Y.Z --notes-file <section.md>`. Publishing the release runs `.github/workflows/npm-publish.yml`, which publishes the `crewship` npm package as version `X.Y.Z`. The workflow fails before the publish when `npm/package.json` does not have that version.
5. The release starts the `release-image` workflow. It builds the `worker` image and pushes it to the GitHub Container Registry as `ghcr.io/i098/crewship:X.Y.Z` and `ghcr.io/i098/crewship:latest`. When the package is public, anyone can pull it without a login: `docker pull ghcr.io/i098/crewship:X.Y.Z`.

   The first push creates the package as private, and the REST API cannot change package visibility. Do this one time: on the [crewship package](https://github.com/users/i098/packages/container/package/crewship), click **Package settings**, then under **Danger Zone** click **Change visibility**, select **Public**, and confirm with the package name.
