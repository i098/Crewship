#!/usr/bin/env bash
# One command from a fresh Ubuntu 24.04 or 26.04 machine to a Crewship host:
#   curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash
# Arguments go to `./ship.sh dock` (for example `bash -s -- --container`);
# `--help` prints the usage and changes nothing.
# Installs the OS prerequisites, downloads and verifies the selected release
# artifact (no git clone) into ~/.local/share/crewship/releases/TAG, points
# ~/Crewship at it, then runs onboard, dock, inspect, chart and launch. Run it
# again to update: the host's own files (.local/) move to the new release and the
# link switches in one step. An old ~/Crewship git clone is kept as a backup.
# Safe to run again: each step skips or reports no change when its work is done.
set -euo pipefail

# The same text is in tools/npm/crewship.js; tests/test_install.py keeps the two equal.
USAGE='Usage: crewship [update] [--container] [--with NAMES] [--user NAME] [--home DIR]
Installs Crewship on this Ubuntu 24.04 or 26.04 machine (bunx crewship, npx crewship or install.sh).
The options go to ./ship.sh dock, which writes the host config on the first run.
  update        install the newest release over this host, keeping its .local/ files
  --with NAMES  turn on these opt-in features, comma separated, and skip the checklist (--with none: none)
                public_skills agent_instructions development docker chat gateway jj fdu fleet_guards project_databases fleet_browsers forgejo tailscale koncreet desktop board
  -h, --help    print this help and exit'

# Runs before any install step, so --help and a bad option change nothing.
check_args() {
  local arg
  for arg; do
    case $arg in -h | --help) printf '%s\n' "$USAGE"; exit 0 ;; esac
  done
  while (($#)); do
    case $1 in
      --container | --with=* | --user=?* | --home=?*) shift ;;
      --user | --home | --with) (($# > 1)) || break; shift 2 ;;
      *) break ;;
    esac
  done
  (($# == 0)) || { printf 'install.sh: bad option: %s\n%s\n' "$1" "$USAGE" >&2; exit 2; }
}
# `update` is the rerun itself (it only names it): the newest release, .local/ carried over.
[ "${1:-}" != update ] || shift
check_args "$@"

work=
log_dir=$HOME/.local/state/crewship-install
mkdir -p -m 700 "$log_dir"
export CREWSHIP_INSTALL_LOG
CREWSHIP_INSTALL_LOG=$(mktemp "$log_dir/install-XXXXXX.log")
exec 3>&1 4>&2
exec > >(tee -a "$CREWSHIP_INSTALL_LOG" >&3) 2> >(tee -a "$CREWSHIP_INSTALL_LOG" >&4)
finish() {
  local status=$?
  rm -rf "$work"
  # Write the footer synchronously before the terminal session can close.
  if ((status)); then
    printf 'Crewship installation failed (exit %s).\nFull install log: %s\n' "$status" "$CREWSHIP_INSTALL_LOG" | tee -a "$CREWSHIP_INSTALL_LOG" >&4
  else
    printf 'Full install log: %s\n' "$CREWSHIP_INSTALL_LOG" | tee -a "$CREWSHIP_INSTALL_LOG" >&3
  fi
}
trap finish EXIT

run_step() {
  local label=$1 started=$SECONDS status=0
  shift
  printf '%s...\n' "$label"
  "$@" >>"$CREWSHIP_INSTALL_LOG" 2>&1 || status=$?
  if ((status)); then
    printf '%s: failed (exit %s)\n' "$label" "$status" >&2
    return "$status"
  fi
  printf '%s: done (%ss)\n' "$label" "$((SECONDS - started))"
}

# Saves URL $1 to file $2. Returns 22 on HTTP 404 (the caller decides what that means).
download() {
  local code
  code=$(curl -sSL -o "$2" -w '%{http_code}' "$1") || return 1
  case $code in
    200) ;;
    404) return 22 ;;
    *) echo "install.sh: download of $1 failed (HTTP $code)" >&2; return 1 ;;
  esac
}

# Prints the sha256 digest GitHub lists for asset $3 of release $2 in repo $1. The API is
# rate limited (60 requests an hour per IP without GH_TOKEN or GITHUB_TOKEN); when it
# does not answer, the .sha256 asset stays the only check.
asset_digest() {
  local token=${GH_TOKEN:-${GITHUB_TOKEN:-}} auth=() meta code
  [ -z "$token" ] || auth=(-H "Authorization: Bearer $token")
  meta=$work/release.json
  code=$(curl -sS "${auth[@]}" -o "$meta" -w '%{http_code}' "https://api.github.com/repos/$1/releases/tags/$2") || code=000
  if [ "$code" = 200 ]; then
    jq -r --arg name "$3" '.assets[] | select(.name == $name) | .digest // empty' "$meta"
  else
    echo "install.sh: the GitHub API answered HTTP $code, so the asset digest is not checked; the .sha256 check still applies (set GH_TOKEN to raise the rate limit)" >&2
  fi
}

# Releases are immutable, so a release made without the artifact never gets one. Then the
# source archive GitHub builds for the tag (no .git) is installed, after its commit (the
# pax header comment of the archive) is checked against the commit of the tag.
verify_source_archive() {
  local repo=$1 tag=$2 file=$3 want got
  want=$(git ls-remote "https://github.com/$repo" "refs/tags/$tag^{}" "refs/tags/$tag" | awk 'END {print $1}')
  got=$(gzip -dc "$file" 2>/dev/null | head -c 1024 | tr -d '\0' | grep -ao 'comment=[0-9a-f]*' | head -1 | cut -d= -f2 || true)
  [ -n "$want" ] && [ "$want" = "$got" ] || { echo "install.sh: the source archive of $tag is not commit '$want' of the tag (got '$got'); refusing to install" >&2; return 1; }
}

# Downloads, verifies and unpacks release $2 of repo $1 into $work/tree: the release artifact
# and its .sha256 (plus the asset digest $3), or the verified source archive when the release
# has no artifact. Nothing outside $work changes, so a failure leaves the install alone.
fetch_release() {
  local repo=$1 tag=$2 digest=$3 name=crewship-$2.tar.gz want got rc=0
  local base=https://github.com/$1/releases/download/$2
  download "$base/$name" "$work/$name" || rc=$?
  if [ "$rc" = 0 ]; then
    download "$base/$name.sha256" "$work/$name.sha256" || { echo "install.sh: the release $tag has no $name.sha256; refusing to install" >&2; return 1; }
    want=$(awk '{print $1; exit}' "$work/$name.sha256")
    got=$(sha256sum "$work/$name" | awk '{print $1}')
    [ -n "$want" ] && [ "$want" = "$got" ] || { echo "install.sh: $name does not match its .sha256; refusing to install" >&2; return 1; }
    [ -z "$digest" ] || [ "$digest" = "sha256:$got" ] || { echo "install.sh: $name does not match the release asset digest; refusing to install" >&2; return 1; }
  elif [ "$rc" = 22 ]; then
    echo "install.sh: the release $tag has no install artifact; using GitHub's source archive of the tag" >&2
    name=source.tar.gz
    download "https://github.com/$repo/archive/refs/tags/$tag.tar.gz" "$work/$name" || { echo "install.sh: no release $tag in $repo" >&2; return 1; }
    verify_source_archive "$repo" "$tag" "$work/$name"
  else
    return 1
  fi
  mkdir "$work/tree"
  tar -xzf "$work/$name" -C "$work/tree" --strip-components=1
  [ -x "$work/tree/ship.sh" ] || { echo "install.sh: $name is not a Crewship release" >&2; return 1; }
}

# Copies the host's own files from the current install $1 into the new tree.
# A git install has no list of them, so every untracked file counts (caches and
# the .venv, which uv rebuilds, excepted); a release install keeps a fixed set.
# Before the blueprint/ layout the private skills and rules lived in skills/ and
# rules/ at the top; both places are carried, and the old one moves to the new one.
carry_host_files() {
  local old=$1 list=$work/carry
  if [ -d "$old/.git" ]; then
    git -C "$old" ls-files -z --others | { grep -zvE '(^|/)(\.venv|node_modules|__pycache__|\.[a-z_]*cache)(/|$)' || true; } >"$list"
  else
    (cd "$old" && find .local skills/private rules/private blueprint/skills/private blueprint/rules/private -type f -print0 2>/dev/null) >"$list" || true
  fi
  rsync -a --ignore-existing --from0 --files-from="$list" "$old/" "$work/tree/"
  local kind
  for kind in skills rules; do
    [ -d "$work/tree/$kind" ] || continue
    mkdir -p "$work/tree/blueprint/$kind"
    rsync -a --ignore-existing "$work/tree/$kind/" "$work/tree/blueprint/$kind/"
    rm -rf "${work:?}/tree/$kind"
  done
  tr '\0' '\n' <"$list" | sed 's/^/  carried /'
}

# One-time fixes for a v0.4.0 host, run before the re-apply (both are no-ops on a newer one):
# v0.4.0 kept its tools under share/code-factory (tools/, omp, npm packages); v0.4.1 uses share/crewship and refuses the
# old ~/.local/bin links. The links into that tree go (provisions recreates them); the tree itself is
# left for ansible's rename step, since running units still use it. v0.4.1 also rejects three fleet keys
# of host.yml; they are dropped, one line each, and the original is kept as host.yml.v0.4.0.
migrate_v040() {
  local old link
  old=$(readlink -f "$HOME/.local/share/code-factory")
  if [ -d "$old" ]; then
    for link in "$HOME"/.local/bin/*; do
      [ -L "$link" ] && [[ $(readlink -f "$link") == "$old"/* ]] && { echo "  relinking $link"; rm -f "$link"; }
    done
  fi
  [ -f .local/host.yml ] || return 0
  python3 - <<'PY'
import shutil, yaml
path = ".local/host.yml"
document = yaml.safe_load(open(path))
# v0.4.0 names the root "factory"; ship.sh renames it to "crewship" and needs host.yml.bak free for that.
root = next((document[k] for k in ("factory", "crewship") if isinstance(document, dict) and isinstance(document.get(k), dict)), {})
fleet = root.get("fleet")
dropped = [key for key in ("supabase_project_id", "fixture_archive", "worktree_pools") if isinstance(fleet, dict) and key in fleet]
if dropped:
    shutil.copy2(path, path + ".v0.4.0")
    for key in dropped:
        del fleet[key]
        print(f"  dropped fleet.{key} from {path} (removed in v0.4.1; the original is {path}.v0.4.0)")
    yaml.safe_dump(document, open(path, "w"), sort_keys=False)
PY
}

# APT waits for dpkg locks itself; update also needs a retry for the lists lock.
apt_get() {
  local deadline=$((SECONDS + 600)) output status remaining
  echo 'Waiting up to 600 seconds for package locks...'
  while :; do
    remaining=$((deadline - SECONDS))
    ((remaining > 0)) || remaining=0
    if output=$($sudo env LC_ALL=C DEBIAN_FRONTEND=noninteractive \
      apt-get -o "DPkg::Lock::Timeout=$remaining" "$@" 2>&1); then
      printf '%s\n' "$output"
      return 0
    else
      status=$?
    fi
    case $output in
      *'E: Could not get lock '*) ;;
      *'E: Unable to acquire the dpkg frontend lock ('*'), is another process using it?'*) ;;
      *) printf '%s\n' "$output" >&2; return "$status" ;;
    esac
    if ((SECONDS >= deadline)); then
      printf '%s\n' "$output" >&2
      echo 'install.sh: package locks did not clear within 600 seconds; retry after the other package manager finishes.' >&2
      return "$status"
    fi
    sleep 1
  done
}

resolve_release() {
  local repo=$1 ref=$2
  if [ -z "$ref" ]; then
    if ! command -v curl >/dev/null || ! dpkg-query -W -f='${db:Status-Status}' ca-certificates 2>/dev/null | grep -qx installed; then
      echo 'Installing HTTPS prerequisites to find the Crewship release...' >&2
      apt_get update -q >&2 || return
      apt_get install -y -q curl ca-certificates >&2 || return
    fi
    ref=$(curl -sS -o /dev/null -w '%{redirect_url}' "https://github.com/$repo/releases/latest") || return
    ref=${ref##*/}
  fi
  [[ $ref =~ ^v[0-9][0-9A-Za-z._-]*$ ]] || { echo "install.sh: no release found in $repo (got '$ref')" >&2; return 1; }
  printf '%s\n' "$ref"
}

main() {
  local repo=${CREWSHIP_REPO:-i098/Crewship} ref=${CREWSHIP_REF:-}
  local dir=$HOME/Crewship releases=$HOME/.local/share/crewship/releases
  local sudo=sudo
  [ "$(id -u)" -ne 0 ] || sudo=
  command -v apt-get >/dev/null || { echo 'install.sh: needs Ubuntu 24.04 or 26.04 (apt-get)' >&2; return 1; }

  ref=$(resolve_release "$repo" "$ref")
  echo "Installing Crewship $ref"

  # The blueprint/cloud-init/user-data.yaml packages, plus python3-apt for chart's check mode and python3-yaml for migrate_v040.
  local packages=(ca-certificates curl gnupg openssl git rsync tar unzip xz-utils zstd
    python3 python3-venv python3-apt python3-yaml jq procps acl sudo) missing=() package
  for package in "${packages[@]}"; do
    dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -qx installed ||
      missing+=("$package")
  done
  if ((${#missing[@]})); then
    run_step 'Updating OS packages' apt_get update -q
    run_step 'Installing OS packages' apt_get install -y -q "${missing[@]}"
  fi

  if [ -e "$dir" ] && [ ! -L "$dir" ] && [ ! -d "$dir/.git" ]; then
    echo "install.sh: $dir exists but is not a Crewship install; move it away and rerun" >&2
    return 1
  fi

  local target=$releases/$ref
  if [ -L "$dir" ] && [ "$(readlink "$dir")" = "$target" ] && [ -x "$target/ship.sh" ]; then
    echo "Crewship $ref is already installed in $dir"
  else
    mkdir -p "$releases"
    work=$(mktemp -d "$releases/.tmp.XXXXXX")
    echo 'Downloading and verifying the release...'
    fetch_release "$repo" "$ref" "$(asset_digest "$repo" "$ref" "crewship-$ref.tar.gz")"
    local old backup= prev=
    if [ -e "$dir" ]; then
      prev=$(readlink "$dir" || true)
      old=$(readlink -f "$dir")
      echo "Carrying the host files of $old:"
      carry_host_files "$old" >>"$CREWSHIP_INSTALL_LOG" 2>&1
      if [ -d "$dir/.git" ]; then
        git -C "$dir" diff --quiet HEAD 2>/dev/null || echo "install.sh: tracked files in $dir have local edits; they stay in the backup only" >&2
        backup=$dir.git-backup-$(date +%Y%m%d-%H%M%S)
      fi
    fi
    rm -rf "$target"
    mv "$work/tree" "$target"
    ln -sfn "$target" "$dir.new"
    if [ -n "$backup" ]; then
      mv "$dir" "$backup"
      mv -T "$dir.new" "$dir" || { mv "$backup" "$dir"; return 1; }
      echo "The git clone moved to $backup (kept; delete it when you no longer need it)."
    else
      mv -T "$dir.new" "$dir"
      if [[ $prev == "$releases"/* && $prev != "$target" ]]; then rm -rf "$prev"; fi
    fi
  fi
  echo "Crewship $ref in $dir"

  cd "$dir"
  echo 'Migrating host settings...'
  migrate_v040 >>"$CREWSHIP_INSTALL_LOG" 2>&1
  run_step 'Installing repository tools' ./onboard.sh
  if [ ! -f .local/host.yml ]; then
    ./ship.sh dock "$@"
  else
    for arg; do
      case $arg in --with | --with=*)
        # The options shape a new host config only.
        echo 'install.sh: --with applies to a new host config; set the profile in .local/host.yml and rerun' >&2
        return 1 ;;
      esac
    done
  fi
  run_step 'Checking host settings' ./ship.sh inspect
  # Some tasks need installed tools that check mode cannot supply.
  # See docs/configuration.md#commands for preview behavior and side effects.
  echo 'Previewing changes...'
  ./ship.sh chart || echo 'install.sh: chart could not preview every change (normal on a fresh host); launching' >&2
  echo 'Applying host configuration...'
  ./ship.sh launch
  echo 'Crewship is installed. Next: gh auth login, then sign in to omp (docs/omp.md#sign-in) and rerun install.sh.'
  local url home
  if url=$(blueprint/maintenance/crewship-gateway url 2>/dev/null); then
    echo "Open this host's web pages at $url; \`crewship-gateway url\` prints the URL again."
    home=$(python3 -c 'import yaml; print(yaml.safe_load(open(".local/host.yml"))["crewship"]["home"])')
    if [ -f "$home/.config/crewship/gateway/initial-password" ]; then
      echo "The first gateway password is in $home/.config/crewship/gateway/initial-password (mode 600): read it yourself over SSH, then delete the file. \`crewship-gateway password\` in your own terminal sets a new one."
    fi
  fi
}

# Under `curl | bash` the script is stdin, so prompts (sudo, the new-host
# questions) read the terminal instead; without one, launch needs passwordless sudo.
if { : </dev/tty; } 2>/dev/null; then main "$@" </dev/tty; else main "$@" </dev/null; fi
