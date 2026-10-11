#!/usr/bin/env bash
# One command from a fresh Ubuntu 24.04 or 26.04 machine to a Crewship host:
#   curl -fsSL https://raw.githubusercontent.com/i098/Crewship/main/install.sh | bash
# Arguments go to `./ship.sh dock` (for example `bash -s -- --container`);
# `--help` prints the usage and changes nothing.
# Installs the OS prerequisites, downloads and verifies the latest release
# artifact (no git clone) into ~/.local/share/crewship/releases/TAG, points
# ~/Crewship at it, then runs onboard, dock, inspect, chart and launch. Run it
# again to update: the host's own files (.local/) move to the new release and the
# link switches in one step. An old ~/Crewship git clone is kept as a backup.
# Safe to run again: each step skips or reports no change when its work is done.
set -euo pipefail

# The same text is in npm/crewship.js; tests/test_install.py keeps the two equal.
USAGE='Usage: crewship [--container] [--user NAME] [--home DIR]
Installs Crewship on this Ubuntu 24.04 or 26.04 machine (npx crewship or install.sh).
The options go to ./ship.sh dock, which writes the host config on the first run.
  -h, --help  print this help and exit'

# Runs before any install step, so --help and a bad option change nothing.
check_args() {
  local arg
  for arg; do
    case $arg in -h | --help) printf '%s\n' "$USAGE"; exit 0 ;; esac
  done
  while (($#)); do
    case $1 in
      --container | --user=?* | --home=?*) shift ;;
      --user | --home) (($# > 1)) || break; shift 2 ;;
      *) break ;;
    esac
  done
  (($# == 0)) || { printf 'install.sh: bad option: %s\n%s\n' "$1" "$USAGE" >&2; exit 2; }
}
check_args "$@"

work=
trap 'rm -rf "$work"' EXIT

# Saves URL $1 to file $2; a 404 means release $3 has no install artifact yet.
download() {
  local code
  code=$(curl -sSL -o "$2" -w '%{http_code}' "$1") || return 1
  case $code in
    200) ;;
    404) echo "install.sh: the release $3 has no install artifact yet; try again in a few minutes" >&2; return 1 ;;
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

# Downloads, verifies and unpacks the release artifact of $tag from $base into
# $work/tree. Nothing outside $work changes, so a failure leaves the install alone.
fetch_release() {
  local base=$1 tag=$2 digest=$3 name=crewship-$2.tar.gz want got
  download "$base/$name" "$work/$name" "$tag"
  download "$base/$name.sha256" "$work/$name.sha256" "$tag"
  want=$(awk '{print $1; exit}' "$work/$name.sha256")
  got=$(sha256sum "$work/$name" | awk '{print $1}')
  [ -n "$want" ] && [ "$want" = "$got" ] || { echo "install.sh: $name does not match its .sha256; refusing to install" >&2; return 1; }
  [ -z "$digest" ] || [ "$digest" = "sha256:$got" ] || { echo "install.sh: $name does not match the release asset digest; refusing to install" >&2; return 1; }
  mkdir "$work/tree"
  tar -xzf "$work/$name" -C "$work/tree" --strip-components=1
  [ -x "$work/tree/ship.sh" ] || { echo "install.sh: $name is not a Crewship release" >&2; return 1; }
}

# Copies the host's own files from the current install $1 into the new tree.
# A git install has no list of them, so every untracked file counts (caches and
# the .venv, which uv rebuilds, excepted); a release install keeps a fixed set.
carry_host_files() {
  local old=$1 list=$work/carry
  if [ -d "$old/.git" ]; then
    git -C "$old" ls-files -z --others | { grep -zvE '(^|/)(\.venv|node_modules|__pycache__|\.[a-z_]*cache)(/|$)' || true; } >"$list"
  else
    (cd "$old" && find .local skills/private rules/private -type f -print0 2>/dev/null) >"$list" || true
  fi
  rsync -a --ignore-existing --from0 --files-from="$list" "$old/" "$work/tree/"
  tr '\0' '\n' <"$list" | sed 's/^/  carried /'
}

main() {
  local repo=${CREWSHIP_REPO:-i098/Crewship} ref=${CREWSHIP_REF:-}
  local dir=$HOME/Crewship releases=$HOME/.local/share/crewship/releases
  local sudo=sudo
  [ "$(id -u)" -ne 0 ] || sudo=
  command -v apt-get >/dev/null || { echo 'install.sh: needs Ubuntu 24.04 or 26.04 (apt-get)' >&2; return 1; }

  # The cloud-init/user-data.yaml packages, plus python3-apt for chart's check mode.
  local packages=(ca-certificates curl gnupg openssl git rsync tar unzip xz-utils zstd
    python3 python3-venv python3-apt jq procps acl sudo) missing=() package
  for package in "${packages[@]}"; do
    dpkg-query -W -f='${db:Status-Status}' "$package" 2>/dev/null | grep -qx installed ||
      missing+=("$package")
  done
  if ((${#missing[@]})); then
    $sudo apt-get update -q
    $sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y -q "${missing[@]}"
  fi

  # The latest tag comes from the unmetered releases/latest redirect, not the API.
  [ -n "$ref" ] || { ref=$(curl -sS -o /dev/null -w '%{redirect_url}' "https://github.com/$repo/releases/latest") && ref=${ref##*/}; }
  [[ $ref =~ ^v[0-9][0-9A-Za-z._-]*$ ]] || { echo "install.sh: no release found in $repo (got '$ref')" >&2; return 1; }
  local base=https://github.com/$repo/releases/download/$ref
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
    fetch_release "$base" "$ref" "$(asset_digest "$repo" "$ref" "crewship-$ref.tar.gz")"
    local old backup= prev=
    if [ -e "$dir" ]; then
      prev=$(readlink "$dir" || true)
      old=$(readlink -f "$dir")
      echo "Carrying the host files of $old:"
      carry_host_files "$old"
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
  ./onboard.sh
  [ -f .local/host.yml ] || ./ship.sh dock "$@"
  ./ship.sh inspect
  # Check mode cannot preview tasks that depend on an earlier install, so chart
  # fails on a fresh host; it changes nothing, and launch reports real failures.
  ./ship.sh chart || echo 'install.sh: chart could not preview every change (normal on a fresh host); launching' >&2
  ./ship.sh launch
  echo 'Crewship is installed. Next: gh auth login, then sign in to omp (docs/omp.md#sign-in) and rerun install.sh.'
}

# Under `curl | bash` the script is stdin, so prompts (sudo, the new-host
# questions) read the terminal instead; without one, launch needs passwordless sudo.
if { : </dev/tty; } 2>/dev/null; then main "$@" </dev/tty; else main "$@" </dev/null; fi
