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
