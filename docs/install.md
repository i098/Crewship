# Install, update and migrate

`install.sh` (also `bunx crewship`, `npx crewship`, `pnpm dlx crewship`) installs a release of Crewship. It never clones the repository.

## Install

Use the curl installer on a fresh server.
It does not need Node.js, npm, pnpm, or Bun:

```bash
curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash
```

The script on `main` selects and downloads a released installer.
It follows GitHub's latest stable release, verifies `install.sh` against its `.sha256`, and runs that copy.
It also compares the digest from GitHub's release API when the API is available.
If the selected release has no installer asset, the bootstrap uses the installer from the verified, approved `i098/Crewship` release `v0.4.7`.
That installer installs the requested tag and repository, not `v0.4.7`, from a checked archive.
It verifies GitHub's source archive against the tag's commit when the requested release has no archive asset.
It does not run the cloning installer inside old releases, and it does not use installer code from `main`.
Changes to the full installer in `scripts/install.sh` do not reach stable users until an approved stable release includes them.
The small download script itself still comes from `main`.

If `curl` is missing, install it with `sudo apt-get update && sudo apt-get install -y curl`.

Other launchers need an existing runtime:

| Launcher | Prerequisite | Release selection |
| --- | --- | --- |
| `bunx crewship` | Bun and Node.js 18 or newer; Bun's Linux installer needs `unzip` | Installs the selected npm package's matching Crewship release |
| `npx crewship` | Node.js 18 or newer and npm | Installs the selected npm package's matching Crewship release |
| `pnpm dlx crewship` | pnpm and a compatible Node.js runtime | May select an older npm package under pnpm's release-age policy |

Before installing Bun on Ubuntu, run `sudo apt-get update && sudo apt-get install -y unzip`.
Follow [Bun's installation instructions](https://bun.sh/docs/installation), then use a new shell with `bunx` on `PATH`.
The Crewship launcher uses a Node.js shebang, so plain `bunx crewship` also needs Node.js on `PATH`.
Do not install a JavaScript runtime only to run Crewship; use curl instead.

Recent pnpm versions can exclude newly published packages through [`minimumReleaseAge`](https://pnpm.io/settings/dependency-resolution#minimumreleaseage).
Thus `pnpm dlx crewship` can install an older Crewship release even when a newer release is available.
The default delay in pnpm 12 is 1,440 minutes.
For stable releases, the pnpm launcher checks the registry and explains this policy if it finds a newer release.
It keeps the selected release and does not change your pnpm settings.
The check does not run for `update`; a failed check does not stop installation.
Check the release printed by the installer.
Keep pnpm's safety policy; use the curl installer to select the latest stable Crewship release directly.
See [Update](#update) for an existing installation.

The installer:

1. Finds and prints the selected Crewship release before the main package setup.
   `install.sh` follows the `https://github.com/<repo>/releases/latest` redirect unless [`CREWSHIP_REF`](#settings) selects a tag.
   If needed, the download script first installs curl, CA certificates, and jq for the release checks.
   The npm launchers use their package version unless you pass `update`, which follows the same redirect.
2. Installs the OS packages it needs.
3. Downloads `crewship-<tag>.tar.gz` and `crewship-<tag>.tar.gz.sha256` from `https://github.com/<repo>/releases/download/<tag>/`. The tarball is a `git archive` of the tag (built by `scripts/build-release-artifact.sh` and attached to the draft release before it is published), so it has no `.git`. Releases are immutable, so a release made without the artifact never gets one. For such a release, the installer uses GitHub's source archive of the tag (`https://github.com/<repo>/archive/refs/tags/<tag>.tar.gz`, also without `.git`) and refuses it unless the commit in its header equals the commit of the tag (`git ls-remote`, no clone). It never runs `git clone`.
4. For a release asset, refuses to continue unless the tarball's SHA-256 equals the `.sha256` file.
   It also compares the digest from GitHub's release API.
   If the API does not answer, it prints a message and continues with the `.sha256` check alone.
   Set `GH_TOKEN` or `GITHUB_TOKEN` to raise the API rate limit.
5. Unpacks it to `~/.local/share/crewship/releases/<tag>` and points the symlink `~/Crewship` at it, so `cd ~/Crewship && ./ship.sh ...` works as before.
6. Runs `onboard.sh`, `ship.sh dock` (first run only), `inspect`, and `launch`.
   In a terminal, `dock` shows a checklist of opt-in features.
   `--with NAMES` answers it; `--with none` installs only the core.
   On an existing host, set profiles in `.local/host.yml`; a rerun refuses `--with`.
   If the [Firstmate memory check](configuration.md#commands) fails, the installer stops before its final completion message.

The one-command installer does not run a separate full preview before applying.
Run `./ship.sh chart` from `~/Crewship` when you want to inspect a preview yourself.
Follow the [`chart` contract](configuration.md#commands) for preview behavior and side effects.
The apply still validates the configuration, verifies downloads, and checks its outputs.

The full installer shows short progress lines and keeps its output in `~/.local/state/crewship-install/install-*.log`.
It prints the log path when it finishes or fails.
Log files have mode `0600`; check them for private data before sharing them.
Interactive setup questions stay visible.
Ansible apply output stays visible when sudo needs a password.
Bootstrap failures appear in the terminal before the full installer creates a log.

During OS package setup, each `apt-get update` or `apt-get install` step waits up to ten minutes for package locks.
If a lock does not clear, the installer stops with an error.
Let the other package manager finish, then run the installer again.
Other package errors stop the installer without a retry.

Downloads and archive checks happen in a temporary directory before the release switch.
A failure at that stage leaves the current Crewship installation unchanged.

## Update

Run `bunx crewship update` or `npx crewship update` to select the latest stable release, regardless of the npm package version.
Alternatively, run `bunx crewship@latest` or the curl command under [Install](#install).
The installer fetches and verifies the selected release, then:

- copies the host's own files into it: `.local/` (including `host.yml`), `blueprint/skills/private/` and `blueprint/rules/private/`; a release from before the `blueprint/` folder kept the private files in `skills/private/` and `rules/private/`, and the installer moves them to the new place;
- switches `~/Crewship` to the new release in one step (`mv -T` of a new symlink);
- removes the release it replaced, after the switch worked.

A host still on v0.4.0 gets a one-time migration before the re-apply: links in `~/.local/bin` into the old `~/.local/share/code-factory` tree are removed and the installer links the tools again under `crewship`; the old tree itself is left in place for the rename step of the re-apply, and the `fleet` keys v0.4.1 removed (`supabase_project_id`, `fixture_archive`, `worktree_pools`) are dropped from `.local/host.yml`, one line each, with the original kept as `host.yml.v0.4.0`. Comments in `host.yml` are not preserved in the rewritten file.

If the selected release is already installed, the full installer skips the release download.
The bootstrap still downloads and verifies its installer.
Edits to other files in a release directory are not carried across; put host settings in `.local/host.yml` or the private directories.

## Prerelease opt-in

The default installer and `update` follow GitHub's latest stable release, never a prerelease.
To install the npm `next` channel, run `npx crewship@next` without `update`.
To select an exact prerelease, run `npx crewship@0.4.8-rc.1`, or select the tag with the existing `CREWSHIP_REF` setting:

```bash
curl -fsSL https://raw.githubusercontent.com/i098/Crewship/v0.4.8-rc.1/install.sh | CREWSHIP_REF=v0.4.8-rc.1 bash
```

These are version examples; select an available prerelease tag.
`npx crewship@next update` returns to the latest stable release.
See [Release channels](../CONTRIBUTING.md#release-channels) for publication rules.

## Migrate a git install

If `~/Crewship` is a git clone from an older installer, the next run:

1. downloads and verifies the selected release;
2. copies every untracked file of the clone into it (`.local/host.yml`, private skills and rules, other local state), except `.venv`, `node_modules` and caches, which `uv` rebuilds, and records each copied file in the install log;
3. moves the clone to `~/Crewship.git-backup-<date>` and points `~/Crewship` at the release.

The backup is never deleted: unpushed commits and edits to tracked files stay there (the installer warns when a tracked file has local edits). A second run finds the symlink and does nothing to the layout. A `~/Crewship` that is neither a symlink nor a git clone makes the installer stop.

## Settings

`CREWSHIP_REF` selects a tag. `CREWSHIP_REPO` (default `i098/Crewship`) selects another GitHub repository.

## Attach the artifact to a draft release

Follow the [release steps](../CONTRIBUTING.md#release-steps) for draft creation, channel selection, artifact attachment, and publication.
