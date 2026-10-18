#!/usr/bin/env bash
# Sync ~/super.env into Cloudflare Secrets Store and redeploy the fleet-secrets Worker.
# Usage: scripts/stow-secrets.sh      See docs/secrets.md.
# Uses CLOUDFLARE_ACCOUNT_ID and CF_API_TOKEN_GLOBAL from the file itself. Secret values only
# travel through mode-600 temp files, never argv, and nothing prints them.
set -euo pipefail
umask 077

src=$HOME/super.env
worker=fleet-secrets
host=fleet-secrets.iterative.sh
dir=$(cd "$(dirname "$0")/../apps/$worker" && pwd)
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

jq -Rs -f "$dir/split.jq" "$src" >"$tmp/split.json"
# Chunk names carry the file's hash, so a push never changes a chunk a running Worker reads:
# it adds the new set, redeploys, then deletes the old set.
# The Worker checks the Access JWT's client id against FLEET_SECRETS_ACCESS_CLIENT_ID.
jq --arg v "$(sha256sum <"$src" | cut -c1-12)" '
    [(.chunks | to_entries[] | {name: "super_env_\($v)_\(.key)", value}),
     {name: "FLEET_SECRETS_ACCESS_CLIENT_ID",
      value: (.vars.FLEET_SECRETS_ACCESS_CLIENT_ID // error("no FLEET_SECRETS_ACCESS_CLIENT_ID"))}]
    | map(. + {scopes: ["workers"], comment: "super.env"})' "$tmp/split.json" >"$tmp/entries.json"
account=$(jq -er .vars.CLOUDFLARE_ACCOUNT_ID "$tmp/split.json")
jq -j '"Authorization: Bearer \(.vars.CF_API_TOKEN_GLOBAL // error("no CF_API_TOKEN_GLOBAL"))\n"' \
  "$tmp/split.json" >"$tmp/auth"

api_base=${CF_API_BASE:-https://api.cloudflare.com/client/v4}
cap=100
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
send() { api "$1" "$2" -H 'Content-Type: application/json' --data-binary @"$3" >/dev/null; }

# The Worker checks the Access JWT against these, so they are looked up, never hand-set.
team=$(api GET /access/organizations | jq -er .result.auth_domain)
aud=$(api GET /access/apps | jq -er --arg h "$host" '[.result[] | select(.domain == $h)] | .[0].aud')
store=$(api GET /secrets_store/stores | jq -er '[.result[] | select(.name == "default_secrets_store")]
  | if length == 1 then .[0].id else error("no single store named default_secrets_store") end')
secrets=/secrets_store/stores/$store/secrets
# ponytail: one page; the store holds at most 100 secrets per account during the beta.
api GET "$secrets?per_page=100" | jq '[.result[] | {(.name): {id, comment}}] | add // {}' \
  >"$tmp/existing.json"
# The secret that put-secret.sh stored and hosts may read at GET /NAME: the one name in
# FLEET_SECRETS_READABLE, bound as read_NAME. Never a list, a super.env secret or a missing one.
jq --slurpfile have "$tmp/existing.json" '
    [.vars.FLEET_SECRETS_READABLE // "" | select(. != "")]
    | map(if test("^[A-Za-z0-9_]+$") | not
          then error("FLEET_SECRETS_READABLE: one name of letters, digits and _")
          elif $have[0][.] and $have[0][.].comment != "super.env" then .
          else error("FLEET_SECRETS_READABLE: no secret \(.) outside super.env") end)' \
  "$tmp/split.json" >"$tmp/readable.json"

jq -r --slurpfile have "$tmp/existing.json" \
  'map(select($have[0][.name] and $have[0][.name].comment != "super.env") | .name)
   | if length > 0 then error("not created by this script, refusing to overwrite: \(join(" "))")
     else empty end' "$tmp/entries.json"
jq --slurpfile have "$tmp/existing.json" 'map(select($have[0][.name] == null))' \
  "$tmp/entries.json" >"$tmp/create.json"
# Delete what an earlier push stored and this one no longer binds (older chunk sets, the old
# one-secret-per-variable layout). Only secrets with comment super.env, never one that is bound now.
jq -r --slurpfile want "$tmp/entries.json" \
  '($want[0] | map({(.name): true}) | add) as $w
   | to_entries[] | select(.value.comment == "super.env" and ($w[.key] | not)) | .value.id' \
  "$tmp/existing.json" >"$tmp/stale"
# A full store has no room for the new chunks, so the first stale secrets go before the create.
# That breaks the running Worker's bindings until the redeploy: a gap of a few seconds, once.
room=$((cap - $(jq length "$tmp/existing.json")))
early=$(($(jq length "$tmp/create.json") - room))
((early > 0)) || early=0
head -n "$early" "$tmp/stale" >"$tmp/early"
tail -n +$((early + 1)) "$tmp/stale" >"$tmp/late"
while read -r id; do api DELETE "$secrets/$id" >/dev/null; done <"$tmp/early"
[[ $(jq length "$tmp/create.json") == 0 ]] || send POST "$secrets" "$tmp/create.json"
jq -r --slurpfile have "$tmp/existing.json" \
  '.[] | select($have[0][.name]) | "\($have[0][.name].id) \(.name)"' "$tmp/entries.json" |
  while read -r id name; do
    jq --arg n "$name" '.[] | select(.name == $n) | del(.name)' "$tmp/entries.json" >"$tmp/body"
    send PATCH "$secrets/$id" "$tmp/body"
  done

jq --arg store "$store" --arg team "$team" --arg aud "$aud" \
  --slurpfile readable "$tmp/readable.json" '{
    main_module: "index.js",
    compatibility_date: "2026-09-01",
    observability: {enabled: false},
    logpush: false,
    bindings: (map({type: "secrets_store_secret", store_id: $store, secret_name: .name,
                    name: (.name | sub("^super_env_[0-9a-f]{12}_"; "super_env_"))})
      + [{type: "plain_text", name: "team_domain", text: $team},
         {type: "plain_text", name: "aud", text: $aud}]
      + ($readable[0] | map({type: "secrets_store_secret", store_id: $store, secret_name: .,
                             name: "read_\(.)"})))
  }' "$tmp/entries.json" >"$tmp/metadata.json"
api PUT "/workers/scripts/$worker" \
  -F "metadata=@$tmp/metadata.json;type=application/json" \
  -F "index.js=@$dir/index.js;type=application/javascript+module" >/dev/null
echo '{"enabled": false, "previews_enabled": false}' >"$tmp/subdomain.json"
send POST "/workers/scripts/$worker/subdomain" "$tmp/subdomain.json"

# The rest of the stale secrets go once the redeploy has reached every edge.
[[ ! -s $tmp/late ]] || sleep 30 # ponytail: fixed wait; old Worker versions served for ~15 s in tests
while read -r id; do api DELETE "$secrets/$id" >/dev/null; done <"$tmp/late"
echo "Pushed $(jq length "$tmp/entries.json") secrets, deployed $worker, deleted $(wc -l <"$tmp/stale") stale."
