#!/usr/bin/env bash
# docker-guard.sh - clear the containers that agents leave behind.
#
# Agents start containers for tests, databases and previews and seldom remove
# them. Stopped ones pile up and pin their images and anonymous volumes;
# forgotten running ones hold memory. Every run:
#   REMOVE  a stopped container (exited, created or dead) whose exit - or its
#           creation, when it never ran - is DOCKER_GUARD_STOPPED_HOURS (24)
#           or more ago: plain `docker rm`, so its volumes stay and a
#           container that started again in the meantime is refused.
#   REPORT  a running container started DOCKER_GUARD_RUNNING_HOURS (48) or
#           more ago that nothing claims. Never stopped or removed. One log
#           line, COMMS.md line and notify-master.sh alert per container.
# A container is claimed, and never touched or reported, when it carries the
# label crewship.keep (any value) or a restart policy other than "no".
# Never touched: volumes, images, networks.
#
# --dry-run prints each verdict and changes nothing: no removal, state, log,
# COMMS.md line or alert.
# Runs every hour from crewship-docker-guard.timer.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
LOG=$HERE/docker-guard.log
COMMS=$HERE/COMMS.md
STATE=$HERE/.docker-guard-reported
STOPPED_H=${DOCKER_GUARD_STOPPED_HOURS:-24}
RUNNING_H=${DOCKER_GUARD_RUNNING_HOURS:-48}
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  '') ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
for v in STOPPED_H RUNNING_H; do
  [[ ${!v} =~ ^[1-9][0-9]*$ ]] || { echo "docker-guard: $v=${!v} is not a whole number of hours" >&2; exit 2; }
done

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }
say() { if [ "$DRY" = 1 ]; then printf '%s\n' "$*"; else log "$*"; fi; }
comms() { printf '\n## [docker-guard -> orchestrator] %s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$*" >> "$COMMS"; }
notify() { [ -x "$HERE/notify-master.sh" ] && "$HERE/notify-master.sh" "$1" "docker-guard" >/dev/null 2>&1; return 0; }
# Docker reports the zero time 0001-01-01T00:00:00Z for "never".
epoch() { case "$1" in 0001-*) echo 0 ;; *) date -d "$1" +%s 2>/dev/null || echo 0 ;; esac; }

docker info >/dev/null 2>&1 || { say "docker unreachable - skipped"; exit 0; }
now=$(date +%s)
mapfile -t ids < <(docker ps -aq --no-trunc 2>/dev/null)
reported=()
[ -f "$STATE" ] && mapfile -t reported < "$STATE"
flagged=() fresh=()
if [ "${#ids[@]}" -gt 0 ]; then
  while IFS='|' read -r id name status created started finished restart keep; do
    [ -n "$id" ] || continue
    name=${name#/}
    if [ -n "$keep" ] || { [ -n "$restart" ] && [ "$restart" != no ]; }; then
      continue
    fi
    case "$status" in
      exited|created|dead)
        since=$(epoch "$finished"); [ "$since" -gt 0 ] || since=$(epoch "$created")
        [ "$since" -gt 0 ] && [ $((now - since)) -ge $((STOPPED_H * 3600)) ] || continue
        hours=$(((now - since) / 3600))
        if [ "$DRY" = 1 ]; then
          say "would remove $name ($status ${hours}h)"
        elif docker rm "$id" >/dev/null 2>&1; then
          log "REMOVED $name ($status ${hours}h)"
        else
          log "FAILED to remove $name ($id)"
        fi
        ;;
      running|paused)
        since=$(epoch "$started")
        [ "$since" -gt 0 ] && [ $((now - since)) -ge $((RUNNING_H * 3600)) ] || continue
        flagged+=("$id")
        printf '%s\n' "${reported[@]}" | grep -qxF -- "$id" && continue
        fresh+=("$name ($(((now - since) / 3600))h)")
        say "REPORT $name running $(((now - since) / 3600))h, unclaimed - not removed"
        ;;
    esac
  done < <(docker inspect --format \
    '{{.Id}}|{{.Name}}|{{.State.Status}}|{{.Created}}|{{.State.StartedAt}}|{{.State.FinishedAt}}|{{.HostConfig.RestartPolicy.Name}}|{{range $k, $v := .Config.Labels}}{{if eq $k "crewship.keep"}}keep{{end}}{{end}}' \
    "${ids[@]}" 2>/dev/null)
fi
[ "$DRY" = 1 ] && exit 0
# The state holds what is flagged now, so a container that stops, gets claimed
# or goes away is reported again if it ever qualifies again.
printf '%s\n' "${flagged[@]}" | sed '/^$/d' > "$STATE"
if [ "${#fresh[@]}" -gt 0 ]; then
  list=$(printf '%s, ' "${fresh[@]}"); list=${list%, }
  comms "Long-running containers nothing claims: $list. Not removed. Stop them, or claim one with the label crewship.keep or a restart policy."
  notify "docker-guard: ${#fresh[@]} long-running unclaimed container(s): $list"
fi
exit 0
