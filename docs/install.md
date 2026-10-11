# Install, update and migrate

`install.sh` (also `npx crewship`, `bunx crewship`, `pnpm dlx crewship`) installs a release of Crewship. It never clones the repository.

## Install

The installer:

1. Installs the OS packages it needs.
2. Finds the latest release through the GitHub API (`npx crewship` uses the release with its own version).
3. Downloads `crewship-<tag>.tar.gz` and `crewship-<tag>.tar.gz.sha256` from that release. The release workflow builds both with `scripts/build-release-artifact.sh`; the tarball is a `git archive` of the tag, so it has no `.git`.
4. Refuses to continue unless the SHA-256 of the tarball equals the `.sha256` file and the digest GitHub shows for the release asset.
5. Unpacks it to `~/.local/share/crewship/releases/<tag>` and points the symlink `~/Crewship` at it, so `cd ~/Crewship && ./ship.sh ...` works as before.
6. Runs `onboard.sh`, `ship.sh dock` (first run only), `inspect`, `chart` and `launch`.

Download and checks happen in a temporary directory first; a failure leaves the current install untouched.

## Update

Run the installer again: `npx crewship@latest`, or the `curl` line from the README. It fetches and verifies the next release the same way, then:

- copies the host's own files into it: `.local/` (including `host.yml`), `skills/private/` and `rules/private/`;
- switches `~/Crewship` to the new release in one step (`mv -T` of a new symlink);
- keeps the release it replaced for a rollback (`ln -sfn <old release> ~/Crewship`) and removes older ones.

If the latest release is already installed, the download is skipped. Edits to other files in a release directory are not carried across; put host settings in `.local/host.yml` or the private directories.

## Migrate a git install

If `~/Crewship` is a git clone from an older installer, the next run:

1. downloads and verifies the latest release;
2. copies every untracked file of the clone into it (`.local/host.yml`, private skills and rules, other local state), except `.venv`, `node_modules` and caches, which `uv` rebuilds, and prints each file;
3. moves the clone to `~/Crewship.git-backup-<date>` and points `~/Crewship` at the release.

The backup is never deleted: unpushed commits and edits to tracked files stay there (the installer warns when a tracked file has local edits). A second run finds the symlink and does nothing to the layout. A `~/Crewship` that is neither a symlink nor a git clone makes the installer stop.

## Test and mirror settings

`CREWSHIP_REF` selects a tag, and `CREWSHIP_RELEASE_URL` names a directory (`file://` works) that holds the two release files, which skips the API lookup and the digest check; the checksum file is still required. `CREWSHIP_REPO` (default `i098/Crewship`) selects another GitHub repository.
