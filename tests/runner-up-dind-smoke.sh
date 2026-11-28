#!/bin/sh
set -eu

if [ "${1-}" = --host ]; then
  processes=$(docker top "${2:?Specify the outer runner-up container}" -eo pid,comm,args)
  daemon=$(printf '%s\n' "$processes" | awk '$2 == "dockerd" {print $1}')
  nested=$(printf '%s\n' "$processes" | awk '$2 == "sleep" && $4 == "73" {print $1}')
  test -n "$daemon"
  test -n "$nested"
  for pid in "$daemon" "$nested"; do
    grep -E '^0::/runnerup\.slice/' "/proc/$pid/cgroup"
  done
  exit 0
fi

if [ "${1-}" = --host-network ]; then
  shim=${2:?Specify the installed runner-up Docker shim}
  read -r image < "$(dirname "$shim")/dind-image"
  first=runner-up-network-smoke-$$-first
  second=runner-up-network-smoke-$$-second
  trap '"$shim" rm -f "$first" "$second" >/dev/null 2>&1 || :; wait || :' EXIT
  RUNNER_UP_BUILD_GATE='' "$shim" run --rm --name "$first" --entrypoint /bin/sh "$image" -ec '
    /home/runner/run.sh --check-dind-runtime
    docker run --rm -d -p 8080:8080 busybox:1.37.0 sh -ec "
      mkdir /site; echo runner-up-network-ok >/site/index.html
      exec httpd -f -p 8080 -h /site"
    exec sleep 180
  ' &
  first_pid=$!
  RUNNER_UP_BUILD_GATE='' "$shim" run --rm --name "$second" --entrypoint /bin/sh "$image" -ec '
    /home/runner/run.sh --check-dind-runtime
    exec sleep 180
  ' &
  second_pid=$!

  for place in "$first" "$second"; do
    ready=
    for _ in $(seq 90); do
      if "$shim" exec "$place" docker info >/dev/null 2>&1; then
        ready=yes
        break
      fi
      sleep 1
    done
    test "$ready" = yes
  done
  template="{{range \$name, \$net := .NetworkSettings.Networks}}{{\$name}} {{\$net.IPAddress}}{{end}}"
  first_net=$("$shim" inspect -f "$template" "$first")
  second_net=$("$shim" inspect -f "$template" "$second")
  test "${first_net%% *}" != "${second_net%% *}"
  url=http://${first_net#* }:8080/
  response=$("$shim" exec "$first" curl --noproxy '*' -fsS --retry 30 --retry-connrefused \
    --retry-max-time 60 --max-time 3 "$url")
  test "$response" = runner-up-network-ok
  if "$shim" exec "$second" curl --noproxy '*' -sS --max-time 3 "$url"; then
    echo 'The second place reached the first place service.' >&2
    exit 1
  else
    status=$?
    test "$status" = 7 || test "$status" = 28
  fi
  "$shim" rm -f "$first" "$second" >/dev/null
  wait "$first_pid" || :
  wait "$second_pid" || :
  trap - EXIT
  networks=$("$shim" network ls --format '{{.Name}}')
  for network in "${first_net%% *}" "${second_net%% *}"; do
    if printf '%s\n' "$networks" | grep -Fx "$network"; then exit 1; fi
  done
  exit 0
fi

work=$(mktemp -d)
cd "$work"
trap 'docker compose down --volumes >/dev/null 2>&1 || :; rm -rf "$work"' EXIT

daemon=$(docker info --format '{{.ID}}')
test -n "$daemon"
containers=$(docker ps -aq)
test -z "$containers"
printf 'daemon=%s\n' "$daemon"
if [ -n "${GITHUB_OUTPUT-}" ]; then
  printf 'id=%s\n' "$daemon" >> "$GITHUB_OUTPUT"
fi

cat > compose.yml <<'EOF'
services:
  check:
    build: .
EOF
cat > Dockerfile <<'EOF'
FROM alpine:3.23
COPY expected /expected
CMD ["sh", "-ec", "grep -x runner-up-dind-ok /expected; exec sleep 73"]
EOF
printf '%s\n' runner-up-dind-ok > expected
docker buildx build --load --tag runner-up-buildx-smoke .
docker run --rm runner-up-buildx-smoke grep -qx runner-up-dind-ok /expected
docker compose up --build --abort-on-container-exit --exit-code-from check
