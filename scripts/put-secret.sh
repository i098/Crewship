#!/usr/bin/env bash
# Create or update one secret, NAME, in the Secrets Store named default_secrets_store.
# Usage: scripts/put-secret.sh NAME <file      See docs/secrets.md.
# The value comes only from stdin (one trailing newline dropped), never argv or the environment,
# and nothing prints it. Uses CLOUDFLARE_ACCOUNT_ID and CF_API_TOKEN_GLOBAL from ~/super.env.
# Changes no other secret, deletes nothing, and does not deploy the fleet-secrets Worker.
set -euo pipefail
umask 077

if [[ $# != 1 || ! $1 =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "usage: scripts/put-secret.sh NAME <file   (NAME: letters, digits, _)" >&2
  exit 2
fi
if [[ -t 0 ]]; then
  echo "Pipe the value on stdin; a terminal would show it." >&2
  exit 2
fi
name=$1
dir=$(cd "$(dirname "$0")/../apps/fleet-secrets" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

jq -Rs '{value: (if endswith("\n") then .[:-1] else . end)}
  | if .value == "" then error("empty value on stdin") else . end' >"$tmp/value.json"
jq -Rs -f "$dir/split.jq" "$HOME/super.env" >"$tmp/split.json"
account=$(jq -er .vars.CLOUDFLARE_ACCOUNT_ID "$tmp/split.json")
jq -j '"Authorization: Bearer \(.vars.CF_API_TOKEN_GLOBAL // error("no CF_API_TOKEN_GLOBAL"))\n"' \
  "$tmp/split.json" >"$tmp/auth"

api_base=${CF_API_BASE:-https://api.cloudflare.com/client/v4}
api() { # METHOD PATH [curl args...]; prints the response, fails on success=false
  local method=$1 path=$2 out
  shift 2
  out=$(curl -sS -X "$method" -H @"$tmp/auth" "$@" \
    "$api_base/accounts/$account$path")
  jq -e .success <<<"$out" >/dev/null || {
    jq -c .errors <<<"$out" >&2
    return 1
  }
  printf '%s\n' "$out"
}

store=$(api GET /secrets_store/stores | jq -er '[.result[] | select(.name == "default_secrets_store")]
  | if length == 1 then .[0].id else error("no single store named default_secrets_store") end')
secrets=/secrets_store/stores/$store/secrets
# ponytail: one page; the store holds at most 100 secrets per account during the beta.
id=$(api GET "$secrets?per_page=100" | jq -r --arg n "$name" '[.result[] | select(.name == $n)]
  | if length > 1 then error("more than one secret named \($n)")
    elif length == 0 then ""
    elif .[0].comment == "super.env" then error("\($n) belongs to stow-secrets.sh, refusing")
    else .[0].id end')

if [[ -z $id ]]; then
  jq --arg n "$name" '[. + {name: $n, scopes: ["workers"], comment: "put-secret.sh"}]' \
    "$tmp/value.json" >"$tmp/body"
  api POST "$secrets" -H 'Content-Type: application/json' --data-binary @"$tmp/body" >/dev/null
  echo "Created $name in default_secrets_store."
else
  api PATCH "$secrets/$id" -H 'Content-Type: application/json' \
    --data-binary @"$tmp/value.json" >/dev/null
  echo "Updated $name in default_secrets_store."
fi
