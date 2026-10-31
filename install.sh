#!/usr/bin/env bash
# Download and verify a released installer before running it.
set -euo pipefail

# The same text is in tools/npm/crewship.js; tests/test_install.py keeps the two equal.
USAGE='Usage: crewship [update] [--container] [--with NAMES] [--user NAME] [--home DIR]
       crewship init
       crewship schedules [--home DIR]

Run npx crewship init on your laptop for guided server setup.
The guide does not install Crewship on the laptop.

Run crewship schedules on the server to view local schedules without changing jobs.
Installs Crewship on this Ubuntu 24.04 or 26.04 machine (bunx crewship, npx crewship or install.sh).
The options go to ./ship.sh dock, which writes the host config on the first run.
  update        install the newest release over this host, keeping its .local/ files
  --with NAMES  turn on these opt-in features, comma separated, and skip the checklist (--with none: none)
                public_skills agent_instructions development docker chat gateway jj fdu vphone fleet_guards project_databases fleet_browsers forgejo tailscale koncreet desktop board sgrep
  -h, --help    print this help and exit'

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
[ "${1:-}" != update ] || shift
check_args "$@"

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

check_asset() {
  local name=$1 repo=$2 ref=$3 want got digest
  local base=https://github.com/$repo/releases/download/$ref
  curl -fsSL "$base/$name.sha256" -o "$work/$name.sha256"
  want=$(awk '{print $1; exit}' "$work/$name.sha256")
  got=$(sha256sum "$work/$name")
  got=${got%% *}
  [ -n "$want" ] && [ "$want" = "$got" ] || { echo "install.sh: $name does not match its .sha256; refusing to install" >&2; return 1; }
  digest=$(asset_digest "$repo" "$ref" "$name")
  [ -z "$digest" ] || [ "$digest" = "sha256:$got" ] || { echo "install.sh: $name does not match the release asset digest; refusing to install" >&2; return 1; }
}

repo=${CREWSHIP_REPO:-i098/Crewship}
ref=${CREWSHIP_REF:-}
if ! command -v curl >/dev/null || ! command -v jq >/dev/null || ! dpkg-query -W -f='${db:Status-Status}' ca-certificates 2>/dev/null | grep -qx installed; then
  sudo=
  [ "$(id -u)" -eq 0 ] || sudo=sudo
  apt_get update -q
  apt_get install -y -q curl ca-certificates jq
fi
if [ -z "$ref" ]; then
  ref=$(curl -fsS -o /dev/null -w '%{redirect_url}' "https://github.com/$repo/releases/latest")
  ref=${ref##*/}
fi
[[ $ref =~ ^v[0-9][0-9A-Za-z._-]*$ ]] || { echo "install.sh: no release found in $repo (got '$ref')" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
base=https://github.com/$repo/releases/download/$ref
code=$(curl -sSL -o "$work/install.sh" -w '%{http_code}' "$base/install.sh")
case $code in
  200)
    check_asset install.sh "$repo" "$ref"
    installer=$work/install.sh
    ;;
  404)
    name=crewship-v0.4.7.tar.gz
    curl -fsSL "https://github.com/i098/Crewship/releases/download/v0.4.7/$name" -o "$work/$name"
    check_asset "$name" i098/Crewship v0.4.7
    mkdir "$work/tree"
    tar -xzf "$work/$name" -C "$work/tree" --strip-components=1
    installer=$work/tree/install.sh
    ;;
  *) echo "install.sh: installer download failed (HTTP $code)" >&2; exit 1 ;;
esac
CREWSHIP_REF="$ref" bash "$installer" "$@"
