# Install, update and migrate

`install.sh` (also `bunx crewship`, `npx crewship`, `pnpm dlx crewship`) installs a release of Crewship. It never clones the repository.

## Install

The installer:

1. Finds and prints the selected Crewship release before the main package setup.
   `install.sh` follows the `https://github.com/<repo>/releases/latest` redirect.
   If needed, it first installs curl and CA certificates for the release lookup.
   The npm launchers use their package version unless you pass `update`, which follows the same redirect.
2. Installs the OS packages it needs.
3. Downloads `crewship-<tag>.tar.gz` and `crewship-<tag>.tar.gz.sha256` from `https://github.com/<repo>/releases/download/<tag>/`. The tarball is a `git archive` of the tag (built by `scripts/build-release-artifact.sh` and attached to the draft release before it is published), so it has no `.git`. Releases are immutable, so a release made without the artifact never gets one. For such a release, the installer uses GitHub's source archive of the tag (`https://github.com/<repo>/archive/refs/tags/<tag>.tar.gz`, also without `.git`) and refuses it unless the commit in its header equals the commit of the tag (`git ls-remote`, no clone). It never runs `git clone`.
4. Refuses to continue unless the SHA-256 of the tarball equals the `.sha256` file. It also compares the digest the GitHub API shows for the release asset. If the API does not answer (for example HTTP 403 or 429 at the 60 requests an hour limit; set `GH_TOKEN` or `GITHUB_TOKEN` to raise it), it prints a message and continues with the `.sha256` check alone.
5. Unpacks it to `~/.local/share/crewship/releases/<tag>` and points the symlink `~/Crewship` at it, so `cd ~/Crewship && ./ship.sh ...` works as before.
6. Runs `onboard.sh`, `ship.sh dock` (first run only), `inspect`, `chart` and `launch`. On a first run in a terminal, `dock` shows one checklist of the opt-in features (everything beyond the Firstmate core); `--with NAMES` answers it, and `--with none` installs the core only. A rerun on an existing host refuses `--with`: set the profile in `.local/host.yml`.

With `pnpm dlx crewship`, pnpm can select an older release under its `minimumReleaseAge` policy.
The default delay in pnpm 12 is 1,440 minutes.
When the registry lists a newer release, the launcher explains this policy and keeps the selected release.
It does not change your pnpm settings.

During OS package setup, each `apt-get update` or `apt-get install` step waits up to ten minutes for package locks.
If a lock does not clear, the installer stops with an error.
Let the other package manager finish, then run the installer again.
Other package errors stop the installer without a retry.

Download and checks happen in a temporary directory first; a failure leaves the current install untouched.

## Update

Run `bunx crewship update` (or `npx crewship update`; it takes the newest release, whatever the version of the npm package), or run the installer again: `bunx crewship@latest`, or the `curl` line from the README. It fetches and verifies the next release the same way, then:

- copies the host's own files into it: `.local/` (including `host.yml`), `blueprint/skills/private/` and `blueprint/rules/private/`; a release from before the `blueprint/` folder kept the private files in `skills/private/` and `rules/private/`, and the installer moves them to the new place;
- switches `~/Crewship` to the new release in one step (`mv -T` of a new symlink);
- removes the release it replaced, after the switch worked.

A host still on v0.4.0 gets a one-time migration before the re-apply: links in `~/.local/bin` into the old `~/.local/share/code-factory` tree are removed and the installer links the tools again under `crewship`; the old tree itself is left in place for the rename step of the re-apply, and the `fleet` keys v0.4.1 removed (`supabase_project_id`, `fixture_archive`, `worktree_pools`) are dropped from `.local/host.yml`, one line each, with the original kept as `host.yml.v0.4.0`. Comments in `host.yml` are not preserved in the rewritten file.

If the latest release is already installed, the download is skipped. Edits to other files in a release directory are not carried across; put host settings in `.local/host.yml` or the private directories.

## Migrate a git install

If `~/Crewship` is a git clone from an older installer, the next run:

1. downloads and verifies the latest release;
2. copies every untracked file of the clone into it (`.local/host.yml`, private skills and rules, other local state), except `.venv`, `node_modules` and caches, which `uv` rebuilds, and prints each file;
3. moves the clone to `~/Crewship.git-backup-<date>` and points `~/Crewship` at the release.

The backup is never deleted: unpushed commits and edits to tracked files stay there (the installer warns when a tracked file has local edits). A second run finds the symlink and does nothing to the layout. A `~/Crewship` that is neither a symlink nor a git clone makes the installer stop.

## Settings

`CREWSHIP_REF` selects a tag. `CREWSHIP_REPO` (default `i098/Crewship`) selects another GitHub repository.

## Attach the artifact to a draft release

Part of the release steps in [CONTRIBUTING.md](../CONTRIBUTING.md#changelog-and-releases). Create the release as a draft, then run the `release-artifact` workflow by hand (Actions, `release-artifact`, Run workflow, with the tag, for example `v1.2.3`, as input) or `gh workflow run release-artifact.yml -f tag=v1.2.3`. It builds the artifact from the tag and uploads it with `--clobber`; it refuses a release that is already published, because immutable releases accept no new assets. It creates no release, tag or version. Publish the draft afterwards.
