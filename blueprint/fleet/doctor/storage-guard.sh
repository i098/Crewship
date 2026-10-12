#!/usr/bin/env bash
# storage-guard.sh - watch disk use the way mem-guardian watches memory.
#
# Why: on 2026-09-23 the host's root filesystem reached 95% used (9.8 GB free)
# and nothing alerted. docker-guard acts only on containers,
# mem-guardian only on memory and swap, Firstmate's orphan sweep only on aged
# litter; none of them measures disk. Docker held 45 GB of images (22 GB
# reclaimable). Hours later /var/log/syslog grew to 39 GB at ~17 MB/s from one
# looping process and took / to 100%, again with no alert.
#
# Measures use% of the filesystems holding /, /var/log, $HOME and Docker's
# data root (`docker info`), once per filesystem. For each one:
#   FILL  growth since the previous run projects the free space left after
#         any CRIT reclaim full within STORAGE_FILL_HORIZON_HOURS (6): alert
#         at once, even below WARN, naming the entry that grew most since the
#         previous consumer scan.
#   WARN  STORAGE_WARN_PCT (85): log, one COMMS.md line and one
#         notify-master.sh alert per episode, re-armed only once usage falls
#         below WARN - STORAGE_HYSTERESIS_PCT (3).
#   CRIT  STORAGE_CRIT_PCT (92). On Docker's filesystem only, reclaim
#         regenerable data cheapest first, re-measuring after each step and
#         stopping once under CRIT: build cache, dangling images, then images
#         no container (running or stopped) uses, created more than
#         STORAGE_IMAGE_AGE_HOURS (168) ago (image creation time, not last
#         use). On every filesystem a CRIT alert reports what the reclaim
#         freed, or that a human is needed while still at CRIT, at most once
#         per STORAGE_REPEAT_MIN (30); FILL repeats likewise.
# Alerts name the top consumers: the largest entries one level under the
# filesystem root, and under the home and /var/log when they live on it, from
# one du walk bounded by STORAGE_SCAN_TIMEOUT seconds (300), plus
# `docker system df` on Docker's filesystem.
#
# Never deleted, only reported: volumes, containers, repositories, worktrees,
# /tmp, logs, anything under the home. Firstmate's orphan sweep owns worktree
# and /tmp litter; a runaway log needs whoever owns the process writing it.
#
# --dry-run prints the measurement, the tier, what each CRIT step would free
# and the alert a real run would send, and writes nothing: no state, log,
# COMMS.md line or alert.
# Runs every 5 minutes from crewship-storage-guard.timer.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
LOG=$HERE/storage-guard.log
COMMS=$HERE/COMMS.md
STATE=$HERE/.storage-guard
WARN=${STORAGE_WARN_PCT:-85}
CRIT=${STORAGE_CRIT_PCT:-92}
HYST=${STORAGE_HYSTERESIS_PCT:-3}
AGE_H=${STORAGE_IMAGE_AGE_HOURS:-168}
HORIZON_H=${STORAGE_FILL_HORIZON_HOURS:-6}
REPEAT_MIN=${STORAGE_REPEAT_MIN:-30}
SCAN_TIMEOUT=${STORAGE_SCAN_TIMEOUT:-300}
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  '') ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
for v in WARN CRIT HYST AGE_H HORIZON_H REPEAT_MIN SCAN_TIMEOUT; do
  [[ ${!v} =~ ^[0-9]+$ ]] || { echo "storage-guard: $v=${!v} is not a whole number" >&2; exit 2; }
done
[ "$HYST" -lt "$WARN" ] && [ "$WARN" -lt "$CRIT" ] && [ "$CRIT" -le 100 ] \
  || { echo "storage-guard: need HYSTERESIS < WARN < CRIT <= 100, got $HYST/$WARN/$CRIT" >&2; exit 2; }

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"; }
show() { [ "$DRY" = 1 ] && printf '%s\n' "$*"; return 0; }  # dry-run narration only
say() { if [ "$DRY" = 1 ]; then printf '%s\n' "$*"; else log "$*"; fi; }  # events
comms() { printf '\n## [storage-guard -> orchestrator] %s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$*" >> "$COMMS"; }
notify() { [ -x "$HERE/notify-master.sh" ] && "$HERE/notify-master.sh" "$1" "storage-guard" >/dev/null 2>&1; return 0; }
join() { local sep=$1 out=$2 x; shift 2; for x in "$@"; do out+="$sep$x"; done; printf '%s' "$out"; }
HUMAN_AWK='function h(b,  s, u, i) { s = b < 0 ? "-" : ""; b = b < 0 ? -b : b; split("B K M G T P", u, " ")
  for (i = 1; b >= 1024 && i < 6; i++) b /= 1024
  return s sprintf(i == 1 ? "%d%s" : "%.1f%s", b, u[i]) }'
human() { awk -v b="$1" "$HUMAN_AWK"' BEGIN { print h(b) }'; }
dur() { printf '%dh%02dm' $(($1 / 3600)) $(($1 % 3600 / 60)); }

# <path> -> "used avail pct mount" (bytes) of the filesystem holding <path>
measure() { df -B1 --output=used,avail,pcent,target -- "$1" 2>/dev/null | awk 'NR == 2 { sub(/%/, "", $3); print }'; }
mount_of() { local m; read -r _ _ _ m <<<"$(measure "$1")"; printf '%s' "$m"; }

# One du walk under SCAN_TIMEOUT: entries (files too - a runaway log is a file)
# one level under <mount>, and under the home and /var/log when they live on it.
# Sets SCAN_OUT to "bytes<TAB>path" lines, largest first, and SCAN_PARTIAL=1
# when the timeout cut the walk short. No temp files: the disk may be full.
scan() {  # <mount>
  local m=$1 r rel depth=1 roots=$1 raw
  for r in "$HOME" /var/log; do
    [ "$r" != "$m" ] && [ "$(mount_of "$r")" = "$m" ] || continue
    roots+=$'\n'$r
    rel=${r#"${m%/}"}; rel=${rel//[!\/]/}
    [ $((${#rel} + 1)) -gt "$depth" ] && depth=$((${#rel} + 1))
  done
  raw=$(timeout "$SCAN_TIMEOUT" du -x -a -B1 -d "$depth" -- "$m" 2>/dev/null)
  [ $? = 124 ] && SCAN_PARTIAL=1 || SCAN_PARTIAL=0
  SCAN_OUT=$(printf '%s\n' "$raw" | awk -F'\t' -v roots="$roots" '
    BEGIN { n = split(roots, a, "\n"); for (i = 1; i <= n; i++) keep[a[i]] = 1 }
    NF == 2 { p = $2; sub(/\/[^\/]*$/, "", p); if (p == "") p = "/"; if ($2 != "/" && p in keep) print }' \
    | sort -t$'\t' -k1,1nr)
}
# Scan lines on stdin -> "under /: home 120.3G, var 40.1G; under /home/u: ..."
top_consumers() {
  awk -F'\t' "$HUMAN_AWK"'
    NF == 2 { p = $2; sub(/\/[^\/]*$/, "", p); if (p == "") p = "/"
      if (!(p in n)) order[++groups] = p
      if (++n[p] <= 5) s[p] = s[p] (n[p] > 1 ? ", " : "") substr($2, length(p) + (p == "/" ? 1 : 2)) " " h($1) }
    END { for (g = 1; g <= groups; g++) printf "%sunder %s: %s", (g > 1 ? "; " : ""), order[g], s[order[g]] }'
}
# Old scan file, new scan on stdin (first line of each: "epoch complete") ->
# the entry that grew most between them, descending into a child that carries
# at least half of that growth. Entries absent from a partial old scan are not
# counted as growth.
fastest() {  # <old-scan-file>
  awk -F'\t' "$HUMAN_AWK"'
    NR == FNR { if (FNR == 1) { split($0, f, " "); t0 = f[1]; whole = (f[2] == 1) } else old[$2] = $1; next }
    FNR == 1 { split($0, f, " "); t1 = f[1]; next }
    ($2 in old || whole) && $1 > old[$2] + 0 { d[$2] = $1 - old[$2] }
    END { for (p in d) if (best == "" || d[p] > d[best]) best = p
      if (best == "") exit
      do { nx = ""; for (p in d) if (index(p, best "/") == 1 && 2 * d[p] >= d[best] && (nx == "" || d[p] > d[nx])) nx = p
        if (nx != "") best = nx } while (nx != "")
      printf "%s +%s in the %dm since the previous scan", best, h(d[best]), (t1 - t0) / 60 }' "$1" -
}

docker_df() { timeout 60 docker system df --format '{{.Type}} {{.Size}}, reclaimable {{.Reclaimable}}' 2>/dev/null | paste -sd';' | sed 's/;/; /g'; }
# What each CRIT step would free: Docker's reclaimable build cache, then the
# unique size of dangling images and of unused images created more than AGE_H
# ago (creation time, not last use). Layers shared only among pruned images
# are in no unique size, so those are floors.
estimates() {  # -> "build dangling old" in bytes
  local build
  build=$(timeout 60 docker system df --format '{{.Type}}|{{.Reclaimable}}' 2>/dev/null | awk -F'|' '$1 == "Build Cache" { print $2 }')
  timeout 120 docker system df -v --format '{{json .}}' 2>/dev/null | jq -r --arg build "${build%% *}" --argjson cutoff $(($(date +%s) - AGE_H * 3600)) '
    def bytes: (capture("^(?<n>[0-9.]+)(?<u>[kKMGTP]?B)") // {n: "0", u: "B"})
      | (.n | tonumber) * {"B": 1, "kB": 1e3, "KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12, "PB": 1e15}[.u];
    def epoch: capture("^(?<t>\\S+ \\S+) (?<s>[+-])(?<h>\\d\\d)(?<m>\\d\\d)")
      | (.t | strptime("%Y-%m-%d %H:%M:%S") | mktime) - (if .s == "-" then -1 else 1 end) * ((.h | tonumber) * 3600 + (.m | tonumber) * 60);
    def unused: (.Containers | tonumber? // 1) == 0;
    def dangling: .Repository == "<none>" and .Tag == "<none>";
    [($build | bytes),
     ([.Images[] | select(dangling and unused) | .UniqueSize | bytes] | add // 0),
     ([.Images[] | select((dangling | not) and unused and (.CreatedAt | epoch) < $cutoff) | .UniqueSize | bytes] | add // 0)]
    | map(floor) | "\(.[0]) \(.[1]) \(.[2])"'
}

# CRIT steps, cheapest first: "label|docker arguments".
STEPS=("build cache|builder prune -f"
       "dangling images|image prune -f"
       "unused images created over ${AGE_H}h ago|image prune -af --filter until=${AGE_H}h")

# --- which filesystems ----------------------------------------------------------
DOCKER_ROOT=$(timeout 20 docker info -f '{{.DockerRootDir}}' 2>/dev/null) || DOCKER_ROOT=
DOCKER_MOUNT=
declare -A holds=()
mounts=()
for p in / /var/log "$HOME" ${DOCKER_ROOT:+"$DOCKER_ROOT"}; do
  m=$(mount_of "$p")
  [ -n "$m" ] || { say "cannot measure the filesystem holding $p"; continue; }
  [ "$p" = "$DOCKER_ROOT" ] && DOCKER_MOUNT=$m
  [ -n "${holds[$m]+x}" ] || mounts+=("$m")
  holds[$m]+="${holds[$m]:+ and }$p"
done

show "storage-guard --dry-run: WARN ${WARN}% (re-armed below $((WARN - HYST))%), CRIT ${CRIT}%, fill horizon ${HORIZON_H}h, image age ${AGE_H}h, repeat ${REPEAT_MIN}m"
if [ "$DRY" != 1 ]; then
  mkdir -p "$STATE" 2>/dev/null
  # Best effort: a full disk must not stop the reclaim for want of a lock file.
  if { exec 9>"$STATE/lock"; } 2>/dev/null; then flock -n 9 || exit 0; fi
fi

for m in "${mounts[@]}"; do
  key=$(printf '%s' "$m" | tr -c 'A-Za-z0-9' '_')
  p_t=0 p_used=0 warn_on=0 crit_at=0 fill_at=0
  [ -f "$STATE/$key" ] && read -r p_t p_used warn_on crit_at fill_at < "$STATE/$key"
  for v in p_t p_used warn_on crit_at fill_at; do [[ ${!v} =~ ^[0-9]+$ ]] || printf -v "$v" 0; done
  read -r used avail pct _ <<<"$(measure "$m")"
  [[ $used$avail$pct =~ ^[0-9]+$ ]] || { say "cannot measure $m"; continue; }
  now=$(date +%s) notes=() filling=0 keep_sample=0 reclaimed=
  show "" && show "$m (holds ${holds[$m]}): ${pct}% used, $(human "$used") of $(human $((used + avail))), $(human "$avail") free"

  dt=$((now - p_t)) grow=$((used - p_used))

  # CRIT: reclaim regenerable Docker data, cheapest first.
  if [ "$m" = "$DOCKER_MOUNT" ]; then
    if [ "$DRY" = 1 ]; then
      read -r e1 e2 e3 <<<"$(estimates)"
      [ "$pct" -ge "$CRIT" ] && when="would run now" || when="would run only at >= ${CRIT}%"
      i=0
      for e in "${e1:-0}" "${e2:-0}" "${e3:-0}"; do
        s=${STEPS[$i]}; i=$((i + 1))
        show "  CRIT step $i ($when, stopping once under ${CRIT}%): docker ${s#*|} - ${s%%|*}, frees ~$(human "$e")"
      done
    elif [ "$pct" -ge "$CRIT" ]; then
      start_used=$used freed=()
      for s in "${STEPS[@]}"; do
        [ "$pct" -ge "$CRIT" ] || break
        before=$used
        # shellcheck disable=SC2086  # the step's own argument words
        out=$(timeout 300 docker ${s#*|} 2>&1 | tail -1)
        read -r used avail pct _ <<<"$(measure "$m")"
        log "  CRIT $m docker ${s#*|}: freed $(human $((before - used))), now ${pct}% - docker: ${out:-no output}"
        freed+=("${s%%|*} $(human $((before - used)))")
      done
      reclaimed="reclaiming $(human $((start_used - used))) of regenerable Docker data ($(join ', ' "${freed[@]}"))"
    fi
  fi

  # FILL: project the growth since the previous run onto the free space left
  # after any reclaim. A rerun within a minute keeps the older sample; its rate
  # would be noise.
  if [ "$p_t" -gt 0 ] && [ "$dt" -lt 60 ]; then
    keep_sample=1
    show "  previous sample ${dt}s old; no rate from so short a gap"
  elif [ "$p_t" -gt 0 ] && [ "$grow" -gt 0 ]; then
    eta=$((avail * dt / grow))
    fill="+$(human "$grow") in $((dt / 60))m ($(human $((grow * 60 / dt)))/min), full in ~$(dur "$eta")"
    if [ "$eta" -lt $((HORIZON_H * 3600)) ]; then
      say "  FILL $m $fill - inside the ${HORIZON_H}h horizon"
      if [ $((now - fill_at)) -ge $((REPEAT_MIN * 60)) ]; then
        notes+=("filling: $fill"); fill_at=$now; filling=1
      fi
    else
      show "  growing $fill - outside the ${HORIZON_H}h horizon"
    fi
  elif [ "$p_t" -gt 0 ]; then
    show "  not growing: $(human "$grow") in $((dt / 60))m"
  else
    show "  no previous sample; the fill projection starts next run"
  fi

  if [ "$pct" -ge "$CRIT" ] || [ -n "$reclaimed" ]; then
    lvl=CRIT
    show "  tier CRIT: ${pct}% >= ${CRIT}%"
    if [ $((now - crit_at)) -ge $((REPEAT_MIN * 60)) ]; then
      if [ "$pct" -lt "$CRIT" ]; then n="back to ${pct}% after $reclaimed"
      else
        n="at ${pct}% (CRIT ${CRIT}%)"
        if [ -n "$reclaimed" ]; then n="still $n after $reclaimed"
        elif [ -z "$DOCKER_MOUNT" ]; then n+=", Docker unreachable so nothing reclaimed"
        elif [ "$m" != "$DOCKER_MOUNT" ]; then n+=", no Docker data here to reclaim"; fi
        n+=" - needs a human"
      fi
      notes+=("$n"); crit_at=$now; warn_on=1
    fi
  elif [ "$pct" -ge "$WARN" ]; then
    lvl=WARN
    show "  tier WARN: ${pct}% >= ${WARN}%$([ "$warn_on" = 1 ] && echo ', episode already alerted')"
    [ "$warn_on" = 1 ] || { notes+=("at ${pct}% (WARN ${WARN}%)"); warn_on=1; }
  else
    lvl=FILL
    show "  tier OK: ${pct}% < ${WARN}%"
    if [ "$warn_on" = 1 ] && [ "$pct" -lt $((WARN - HYST)) ]; then
      say "  WARN episode over for $m at ${pct}% (< $((WARN - HYST))%); re-armed"; warn_on=0
    fi
  fi

  # Name the consumers for an alert, and always in a dry run.
  top=
  if [ ${#notes[@]} -gt 0 ] || [ "$DRY" = 1 ]; then
    show "  scanning consumers (du, up to ${SCAN_TIMEOUT}s)..."
    scan "$m"
    top="top: $(printf '%s\n' "$SCAN_OUT" | top_consumers)"
    [ "$SCAN_PARTIAL" = 1 ] && top+=" (partial: du hit ${SCAN_TIMEOUT}s)"
    [ "$m" = "$DOCKER_MOUNT" ] && top+="; docker: $(docker_df)"
    show "  $top"
    snapshot=$(printf '%s %s\n%s\n' "$now" $((1 - SCAN_PARTIAL)) "$SCAN_OUT")
    if [ "$filling" = 1 ] && [ -f "$STATE/$key.scan" ]; then
      g=$(printf '%s\n' "$snapshot" | fastest "$STATE/$key.scan")
      [ -n "$g" ] && notes[0]+=", grew most: $g"
    fi
    [ "$DRY" = 1 ] || printf '%s\n' "$snapshot" > "$STATE/$key.scan"
  fi

  if [ ${#notes[@]} -gt 0 ]; then
    msg="$lvl $m ${pct}% used, $(human "$avail") free: $(join '; ' "${notes[@]}"). $top"
    if [ "$DRY" = 1 ]; then
      show "  a real run would alert: $msg"
    else
      log "ALERT $msg"
      comms "$msg"
      notify "$msg"
    fi
  fi

  [ "$DRY" = 1 ] && continue
  [ "$keep_sample" = 1 ] && now=$p_t used=$p_used
  echo "$now $used $warn_on $crit_at $fill_at" > "$STATE/$key"
done
exit 0
