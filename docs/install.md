# Install, update and migrate

`install.sh` (also `npx crewship`, `bunx crewship`, `pnpm dlx crewship`) installs a release of Crewship. It never clones the repository.

## Install

The installer:

1. Installs the OS packages it needs.
2. Finds the latest release from the `https://github.com/<repo>/releases/latest` redirect, which has no rate limit (`npx crewship` uses the release with its own version, so it needs no lookup).
3. Downloads `crewship-<tag>.tar.gz` and `crewship-<tag>.tar.gz.sha256` from `https://github.com/<repo>/releases/download/<tag>/`. If either is missing, it stops with `the release <tag> has no install artifact yet; try again in a few minutes`. The release workflow builds both with `scripts/build-release-artifact.sh`; the tarball is a `git archive` of the tag, so it has no `.git`.
4. Refuses to continue unless the SHA-256 of the tarball equals the `.sha256` file. It also compares the digest the GitHub API shows for the release asset. If the API does not answer (for example HTTP 403 or 429 at the 60 requests an hour limit; set `GH_TOKEN` or `GITHUB_TOKEN` to raise it), it prints a message and continues with the `.sha256` check alone.
5. Unpacks it to `~/.local/share/crewship/releases/<tag>` and points the symlink `~/Crewship` at it, so `cd ~/Crewship && ./ship.sh ...` works as before.
6. Runs `onboard.sh`, `ship.sh dock` (first run only), `inspect`, `chart` and `launch`.

Download and checks happen in a temporary directory first; a failure leaves the current install untouched.

## Update

Run the installer again: `npx crewship@latest`, or the `curl` line from the README. It fetches and verifies the next release the same way, then:

- copies the host's own files into it: `.local/` (including `host.yml`), `skills/private/` and `rules/private/`;
- switches `~/Crewship` to the new release in one step (`mv -T` of a new symlink);
- removes the release it replaced, after the switch worked.

If the latest release is already installed, the download is skipped. Edits to other files in a release directory are not carried across; put host settings in `.local/host.yml` or the private directories.

## Migrate a git install

If `~/Crewship` is a git clone from an older installer, the next run:

1. downloads and verifies the latest release;
2. copies every untracked file of the clone into it (`.local/host.yml`, private skills and rules, other local state), except `.venv`, `node_modules` and caches, which `uv` rebuilds, and prints each file;
3. moves the clone to `~/Crewship.git-backup-<date>` and points `~/Crewship` at the release.

The backup is never deleted: unpushed commits and edits to tracked files stay there (the installer warns when a tracked file has local edits). A second run finds the symlink and does nothing to the layout. A `~/Crewship` that is neither a symlink nor a git clone makes the installer stop.

## Settings

`CREWSHIP_REF` selects a tag. `CREWSHIP_REPO` (default `i098/Crewship`) selects another GitHub repository.

## Attach the artifact to an existing release

The `release-artifact` workflow runs when a release is published. For a release that has no artifact, or after a failed run, start it by hand: Actions, `release-artifact`, Run workflow, with the tag (for example `v1.2.3`) as input. It builds the artifact from that tag and uploads it with `--clobber`; it creates no release, tag or version.
