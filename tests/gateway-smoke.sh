#!/usr/bin/env bash
# End-to-end check of the password gateway (docs/gateway.md) in a clean ubuntu:24.04
# container: a real Cloudflare Quick Tunnel, the login, the allow window, the lockout
# of nothing else, a 502 while the gateway is down, and expiry with the clock moved
# 25 hours ahead by libfaketime. Needs Docker and outbound HTTPS to Cloudflare.
#   bash tests/gateway-smoke.sh     (GH_TOKEN, when set, lifts the GitHub API rate limit)
set -euo pipefail
root=$(git rev-parse --show-toplevel)
lab="crewship-gateway-smoke-$$"
docker=(docker)
if [ ! -w /var/run/docker.sock ]; then docker=(sudo -n docker); fi
trap '"${docker[@]}" rm -f "$lab" >/dev/null 2>&1 || true' EXIT
"${docker[@]}" run --detach --rm --name "$lab" --volume "$root:/src:ro" ubuntu:24.04 sleep infinity >/dev/null
"${docker[@]}" exec --env GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN:-}}" "$lab" bash -euo pipefail -c '
  trap '\''echo "gateway smoke: failed at line $LINENO" >&2'\'' ERR
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q >/dev/null
  apt-get install -y -q python3 curl ca-certificates faketime >/dev/null

  # cloudflared, checked against the SHA-256 GitHub lists for the asset.
  arch=$(dpkg --print-architecture)
  name=cloudflared-linux-$arch
  auth=(); [ -z "$GH_TOKEN" ] || auth=(-H "Authorization: Bearer $GH_TOKEN")
  curl -fsSL "${auth[@]}" https://api.github.com/repos/cloudflare/cloudflared/releases/latest -o /tmp/release.json
  want=$(python3 -c "import json,sys; print(next(a[\"digest\"] for a in json.load(open(\"/tmp/release.json\"))[\"assets\"] if a[\"name\"] == \"$name\").removeprefix(\"sha256:\"))")
  url=$(python3 -c "import json; print(next(a[\"browser_download_url\"] for a in json.load(open(\"/tmp/release.json\"))[\"assets\"] if a[\"name\"] == \"$name\"))")
  curl -fsSL "$url" -o /usr/local/bin/cloudflared
  echo "$want  /usr/local/bin/cloudflared" | sha256sum -c --quiet
  chmod +x /usr/local/bin/cloudflared

  install -m 0755 /src/blueprint/maintenance/crewship-gateway /usr/local/bin/crewship-gateway
  mkdir -p /tmp/site
  echo "hello from port 8000" > /tmp/site/index.html
  (cd /tmp/site && python3 -m http.server 8000 --bind 127.0.0.1 >/dev/null 2>&1 &)

  password=$(crewship-gateway password)
  hash=~/.config/crewship/gateway/password.hash
  grep -q "^scrypt\\$" "$hash"
  ! grep -q "$password" "$hash"
  [ "$(stat -c %a "$hash")" = 600 ] && [ "$(stat -c %a "$(dirname "$hash")")" = 700 ]
  start() { "$@" crewship-gateway serve >/tmp/gateway.log 2>&1 & echo $! >/tmp/gateway.pid
            for _ in $(seq 50); do curl -s -o /dev/null http://127.0.0.1:20240/ && return; sleep 0.1; done; return 1; }
  stop() { kill "$(cat /tmp/gateway.pid)"; wait "$(cat /tmp/gateway.pid)" 2>/dev/null || true; }
  start
  [ "$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:20240/)" = 400 ]  # no CF-Connecting-IP
  # A named-tunnel config must not take over the Quick Tunnel (--config /dev/null).
  mkdir -p ~/.cloudflared && printf "tunnel: x\ncredentials-file: /nonexistent\n" > ~/.cloudflared/config.yml
  cloudflared tunnel --config /dev/null --no-autoupdate --metrics 127.0.0.1:20241 \
    --url http://127.0.0.1:20240 >/tmp/tunnel.log 2>&1 &

  public=
  for _ in $(seq 60); do public=$(crewship-gateway url 2>/dev/null) && break; sleep 1; done
  [ -n "$public" ] || { cat /tmp/tunnel.log; exit 1; }
  echo "tunnel: $public"
  code() { curl -s -o /tmp/body -w "%{http_code}" "$@" || true; }
  # A new trycloudflare name can fail now and then for its first seconds: wait for three answers in a row.
  ok=0
  for _ in $(seq 90); do
    if [ "$(code "$public/8000/")" = 401 ] && grep -q "name=\"password\"" /tmp/body; then ok=$((ok + 1)); else ok=0; fi
    [ "$ok" -lt 3 ] || break; sleep 2
  done
  [ "$ok" = 3 ]
  echo "ok: the tunnel URL answers with the login page"

  [ "$(code -d password=wrong "$public/_gateway/login")" = 401 ]
  # Cloudflare refuses a visitor that sends its own CF-Connecting-IP (error 1000), so it never reaches the gateway.
  [ "$(code -H "CF-Connecting-IP: 192.0.2.77" -d "password=$password" "$public/_gateway/login")" = 403 ]
  ! grep -q 192.0.2.77 /tmp/gateway.log
  [ "$(code -c /tmp/jar -d "password=$password" -d next=/8000/ "$public/_gateway/login")" = 303 ]
  grep -q "#HttpOnly_.*__Host-crewship" /tmp/jar
  [ "$(code "$public/8000/")" = 200 ]; grep -q "hello from port 8000" /tmp/body
  echo "ok: login allows this address without a cookie"

  stop
  [ "$(code "$public/8000/")" = 502 ]; ! grep -q "hello from port 8000" /tmp/body
  echo "ok: with the gateway down the tunnel serves nothing"

  # libfaketime in the gateway process itself (the faketime wrapper forks, so kill would miss it).
  start env LD_PRELOAD="$(dpkg -L libfaketime | grep "/libfaketime.so.1$")" FAKETIME=+25h
  [ "$(code "$public/8000/")" = 401 ]
  [ "$(code -b /tmp/jar "$public/8000/")" = 401 ]
  echo "ok: 25 hours later the address and the cookie are refused"
  stop

  start
  [ "$(code "$public/8000/")" = 200 ]
  crewship-gateway password >/dev/null
  [ "$(code "$public/8000/")" = 401 ]
  [ "$(code -b /tmp/jar "$public/8000/")" = 401 ]
  echo "ok: inside the window it is allowed again; a new password signs everyone out"
'
echo "gateway smoke: passed"
