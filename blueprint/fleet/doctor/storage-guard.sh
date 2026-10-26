#!/usr/bin/env bash
# Alert on disk pressure before diagnostics or guarded reclaim.
# Save failed alerts with stable inbox request IDs and retry them next run.
# --dry-run measures and previews without writing or delivering anything.
#
# CRIT also runs worktree-prune.sh on filesystems holding native and legacy home
# Treehouse pools ($WORKTREE_PRUNE_POOLS replaces both roots), before Docker:
# it removes only gitignored build output (node_modules, .venv, target, dist,
# .next, ...) that nothing changed for WORKTREE_PRUNE_AGE_DAYS (7), found with
# find; fdu, when installed, only reports the sizes.
# Tracked files, uncommitted or unpushed work and anything outside the pools
# stay; see that script for each guard. Firstmate's orphan sweep still owns
# whole leaked worktrees and /tmp litter.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
DATA_DIR=${STORAGE_DATA_DIR:-}
STATE=${DATA_DIR:+$DATA_DIR/storage-guard}
STATE=${STATE:-$HERE/.storage-guard}
LOG=$STATE/storage-guard.log
COMMS=$STATE/COMMS.md
NOTIFY_TIMEOUT=${STORAGE_NOTIFY_TIMEOUT:-5}
FAILED=0
STATE_OWNED=0
WARN=${STORAGE_WARN_PCT:-85}
CRIT=${STORAGE_CRIT_PCT:-92}
HYST=${STORAGE_HYSTERESIS_PCT:-3}
AGE_H=${STORAGE_IMAGE_AGE_HOURS:-168}
HORIZON_H=${STORAGE_FILL_HORIZON_HOURS:-6}
FILL_MIN=${STORAGE_FILL_MIN_PCT:-70}
REPEAT_MIN=${STORAGE_REPEAT_MIN:-30}
SCAN_TIMEOUT=${STORAGE_SCAN_TIMEOUT:-300}
PRUNE_TIMEOUT=${STORAGE_PRUNE_TIMEOUT:-300}
if [ -n "${WORKTREE_PRUNE_POOLS:-}" ]; then
  POOL_ROOTS=("$WORKTREE_PRUNE_POOLS")
else
  mapfile -t POOL_ROOTS < <(python3 "$HERE/treehouse-roots.py")
fi
PRUNE_CMD=${WORKTREE_PRUNE_CMD:-$HERE/worktree-prune.sh}  # takes [--dry-run] like worktree-prune.sh
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  '') ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
for v in WARN CRIT HYST AGE_H HORIZON_H FILL_MIN REPEAT_MIN SCAN_TIMEOUT PRUNE_TIMEOUT NOTIFY_TIMEOUT; do
  [[ ${!v} =~ ^[0-9]+$ ]] || { echo "storage-guard: $v=${!v} is not a whole number" >&2; exit 2; }
done
[ "$HYST" -lt "$WARN" ] && [ "$WARN" -lt "$CRIT" ] && [ "$CRIT" -le 100 ] \
  || { echo "storage-guard: need HYSTERESIS < WARN < CRIT <= 100, got $HYST/$WARN/$CRIT" >&2; exit 2; }
[ "$NOTIFY_TIMEOUT" -gt 0 ] || { echo "storage-guard: notification timeout must be positive" >&2; exit 2; }

log() {
  if [ "$STATE_OWNED" != 1 ]; then printf '%s\n' "$*" >&2; return; fi
  printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >> "$LOG"
}
show() { [ "$DRY" = 1 ] && printf '%s\n' "$*"; return 0; }  # dry-run narration only
say() { if [ "$DRY" = 1 ]; then printf '%s\n' "$*"; else log "$*"; fi; }  # events
comms() { printf '\n## [storage-guard -> orchestrator] %s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$*" >> "$COMMS"; }
valid_receipt() {
  jq -e --arg id "$1" '
    .schema == "fm-inbox-note.v1" and .request_id == $id and .saved == true
    and (.announced == true or .acknowledged == true)
    and (.outcome == "created" or .outcome == "replay")
    and (.id | type == "string" and length > 0)' >/dev/null 2>&1
}
attempt_delivery() {
  local id=$1 msg=$2 file=${3:-} receipt= fm=${FM_HOME:-}
  if [ -n "$fm" ] && [ -x "$fm/bin/fm-inbox.sh" ] \
    && receipt=$(FM_HOME=${fm%/} timeout -k 2 "$NOTIFY_TIMEOUT" "$fm/bin/fm-inbox.sh" \
      note --request-id "$id" --json -- "$msg" 2>&1) \
    && valid_receipt "$id" <<<"$receipt"; then
    printf '%s\n' "$receipt"
    return 0
  fi
  printf 'storage-guard: delivery pending %s: %s\n' "$id" "${receipt:-inbox unavailable}" >&2
  if [ -z "$file" ] || [ ! -f "$file.broadcast" ]; then
    if { [ -x "$HERE/notify-master.sh" ] \
      && timeout -k 1 3 "$HERE/notify-master.sh" "$msg" storage-guard; } \
      || printf '%s\n' "$msg" "${file:+Pending: $file}" | timeout -k 1 3 wall -n -t 2; then
      [ -z "$file" ] || [ "$STATE_OWNED" != 1 ] || printf '%s\n' "$id" > "$file.broadcast"
    fi
  fi
  return 1
}
deliver_pending() {
  local file=$1 id event_state msg receipt ack=
  read -r id event_state < "$file" || return 1
  msg=$( { IFS= read -r _; cat; } < "$file")
  [ ! -f "$file.ack" ] || read -r ack _ < "$file.ack"
  if [ "$ack" != "$id" ]; then
    if receipt=$(attempt_delivery "$id" "$msg" "$file"); then
      [ "$STATE_OWNED" = 1 ] || return 1
      printf '%s%s\n%s\n' "$id" "${event_state:+ $event_state}" "$receipt" > "$file.ack.tmp" \
        && mv -f -- "$file.ack.tmp" "$file.ack" || return 1
      log "DELIVERED $id $receipt"
    else
      return 1
    fi
  fi
  [ "$STATE_OWNED" = 1 ] || return 1
  rm -f -- "$file" "$file.broadcast"
}
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
# one level under <mount> and one level under its biggest entry, and under the
# home and /var/log when they live on it.
# Sets SCAN_OUT to "bytes<TAB>path" lines, largest first, and SCAN_PARTIAL=1
# when the timeout cut the walk short. No temp files: the disk may be full.
scan() {  # <mount>
  local m=$1 r rel depth=2 roots=$1 raw
  for r in "$HOME" /var/log; do
    [ "$r" != "$m" ] && [ "$(mount_of "$r")" = "$m" ] || continue
    roots+=$'\n'$r
    rel=${r#"${m%/}"}; rel=${rel//[!\/]/}
    [ $((${#rel} + 1)) -gt "$depth" ] && depth=$((${#rel} + 1))
  done
  raw=$(timeout "$SCAN_TIMEOUT" du -x -a -B1 -d "$depth" -- "$m" 2>/dev/null)
  [ $? = 124 ] && SCAN_PARTIAL=1 || SCAN_PARTIAL=0
  # du prints a directory after everything under it, so the level-2 lines seen
  # since the previous level-1 entry are the children of the next one: keep them
  # only when that entry is the biggest so far.
  SCAN_OUT=$(printf '%s\n' "$raw" | awk -F'\t' -v roots="$roots" -v m="$m" '
    BEGIN { n = split(roots, a, "\n"); for (i = 1; i <= n; i++) keep[a[i]] = 1
      ml = length(m) - (m ~ /\/$/) }
    NF == 2 { p = $2; sub(/\/[^\/]*$/, "", p); if (p == "") p = "/"
      if ($2 != "/" && p in keep) print
      if (p == m) { if ($1 + 0 > big) { big = $1 + 0; kids = buf } buf = "" }
      else if (!(p in keep)) { rel = substr($2, ml + 1); if (gsub(/\//, "/", rel) == 2) buf = buf $0 "\n" } }
    END { printf "%s", kids }' \
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
# the (up to 5) entries that grew most between them, "<age>: path +size, ...".
# An entry is skipped when a child carries at least half of its growth (the
# child is the more precise answer). Entries absent from a partial old scan
# are not counted as growth.
growers() {  # <old-scan-file>
  awk -F'\t' "$HUMAN_AWK"'
    NR == FNR { if (FNR == 1) { split($0, f, " "); t0 = f[1]; whole = (f[2] == 1) } else old[$2] = $1; next }
    FNR == 1 { split($0, f, " "); t1 = f[1]; next }
    ($2 in old || whole) && $1 > old[$2] + 0 { d[$2] = $1 - old[$2] }
    END { for (p in d) { ok = 1
        for (q in d) if (index(q, p "/") == 1 && 2 * d[q] >= d[p]) ok = 0
        if (ok) k[p] = d[p] }
      for (i = 0; i < 5; i++) { best = ""
        for (p in k) if (best == "" || k[p] > k[best]) best = p
        if (best == "") break
        out = out (i ? ", " : "") best " +" h(k[best]); delete k[best] }
      if (out == "") exit
      m = (t1 - t0) / 60
      printf "%s since the previous scan: %s", (m >= 120 ? sprintf("%dh", m / 60) : sprintf("%dm", m)), out }' "$1" -
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

if [ "$DRY" != 1 ]; then
  if [ -n "$DATA_DIR" ]; then
    data_mount=$(findmnt -nro TARGET -T "$DATA_DIR") || data_mount=
    data_device=$(findmnt -nro MAJ:MIN -T "$DATA_DIR") || data_device=
    root_device=$(findmnt -nro MAJ:MIN -T /) || root_device=
    if [ ! -d "$DATA_DIR" ] || [ -z "$data_mount" ] || [ "$data_mount" = / ] \
      || [ -z "$data_device" ] || [ -z "$root_device" ] || [ "$data_device" = "$root_device" ] \
      || ! mountpoint -q "$data_mount"; then
      printf 'storage-guard: configured data mount unavailable: %s\n' "$DATA_DIR" >&2
      printf 'storage-guard cannot save alerts: data mount unavailable\n' | timeout -k 1 3 wall -n -t 2
      exit 1
    fi
  fi
  umask 077
  if mkdir -p "$STATE" && { exec 9>>"$STATE/lock"; }; then
    flock -n -E 75 9
    case $? in
      0) STATE_OWNED=1 ;;
      75) exit 0 ;;
    esac
  fi
  if [ "$STATE_OWNED" != 1 ]; then
    FAILED=1
    printf 'storage-guard: state unavailable; continuing without state changes\n' >&2
  fi
  shopt -s nullglob
  for pending in "$STATE"/*.pending; do deliver_pending "$pending" || FAILED=1; done
fi

# --- which filesystems ----------------------------------------------------------
DOCKER_ROOT=$(timeout 20 docker info -f '{{.DockerRootDir}}' 2>/dev/null) || DOCKER_ROOT=
DOCKER_MOUNT=
declare -A pool_mounts=()
POOL_DIRS=()
for p in "${POOL_ROOTS[@]}"; do
  [ -d "$p" ] || continue
  m=$(mount_of "$p")
  [ -n "$m" ] || continue
  POOL_DIRS+=("$p"); pool_mounts[$p]=$m
done
declare -A holds=()
mounts=()
for p in / /var/log "$HOME" ${DOCKER_ROOT:+"$DOCKER_ROOT"} "${POOL_DIRS[@]}"; do
  m=$(mount_of "$p")
  [ -n "$m" ] || { say "cannot measure the filesystem holding $p"; continue; }
  [ "$p" = "$DOCKER_ROOT" ] && DOCKER_MOUNT=$m
  [ -n "${holds[$m]+x}" ] || mounts+=("$m")
  holds[$m]+="${holds[$m]:+ and }$p"
done
# Every other real block filesystem, once per device (a bind mount or btrfs
# subvolume of a device already listed adds nothing). findmnt -r escapes spaces.
declare -A dev_of=() dev_seen=()
real=()
while read -r t ft src; do
  [[ $ft =~ ^(ext[234]|xfs|btrfs|zfs|vfat|exfat|ntfs3?|f2fs|jfs|reiserfs|fuseblk)$ ]] || continue
  [[ $src == /dev/loop* ]] && continue
  printf -v t '%b' "$t"
  dev_of[$t]=${src%%\[*}; real+=("$t")
done < <(findmnt -rno TARGET,FSTYPE,SOURCE 2>/dev/null)
for m in "${mounts[@]}"; do [ -n "${dev_of[$m]+x}" ] && dev_seen[${dev_of[$m]}]=1; done
for m in "${real[@]}"; do
  [ -z "${dev_seen[${dev_of[$m]}]+x}" ] || continue
  dev_seen[${dev_of[$m]}]=1
  mounts+=("$m"); holds[$m]="the mount ${dev_of[$m]}"
done

show "storage-guard --dry-run: WARN ${WARN}% (re-armed below $((WARN - HYST))%), CRIT ${CRIT}%, fill horizon ${HORIZON_H}h, image age ${AGE_H}h, repeat ${REPEAT_MIN}m"
declare -A needs_scan=() reclaim_eligible=()

for m in "${mounts[@]}"; do
  key=$(printf '%s' "$m" | tr -c 'A-Za-z0-9' '_')
  p_t=0 p_used=0 warn_on=0 crit_at=0 fill_at=0 alert_seq=0
  [ -f "$STATE/$key" ] && read -r p_t p_used warn_on crit_at fill_at alert_seq < "$STATE/$key"
  for v in p_t p_used warn_on crit_at fill_at alert_seq; do [[ ${!v} =~ ^[0-9]+$ ]] || printf -v "$v" 0; done
  # Receipts also keep episode state if the sample replacement failed.
  for record in "$STATE/$key".*.pending "$STATE/$key".*.pending.ack; do
    [ -f "$record" ] || continue
    read -r _ r_warn r_crit r_fill r_seq < "$record"
    [[ $r_warn:$r_crit:$r_fill:$r_seq =~ ^[0-9]+:[0-9]+:[0-9]+:[0-9]+$ ]] || continue
    [ "$r_seq" -gt "$alert_seq" ] || continue
    warn_on=$r_warn crit_at=$r_crit fill_at=$r_fill alert_seq=$r_seq
  done
  read -r used avail pct _ <<<"$(measure "$m")"
  [[ $used$avail$pct =~ ^[0-9]+$ ]] || { say "cannot measure $m"; continue; }
  now=$(date +%s) notes=() keep_sample=0
  show "" && show "$m (holds ${holds[$m]}): ${pct}% used, $(human "$used") of $(human $((used + avail))), $(human "$avail") free"

  dt=$((now - p_t)) grow=$((used - p_used))

  # Measure growth before reclaim. Gaps under a minute keep the older sample.
  if [ "$p_t" -gt 0 ] && [ "$dt" -lt 60 ]; then
    keep_sample=1
    show "  previous sample ${dt}s old; no rate from so short a gap"
  elif [ "$p_t" -gt 0 ] && [ "$grow" -gt 0 ]; then
    eta=$((avail * dt / grow))
    fill="+$(human "$grow") in $((dt / 60))m ($(human $((grow * 60 / dt)))/min), full in ~$(dur "$eta")"
    if [ "$pct" -lt "$FILL_MIN" ]; then
      show "  growing $fill - below FILL floor ${FILL_MIN}%"
    elif [ "$eta" -lt $((HORIZON_H * 3600)) ]; then
      say "  FILL $m $fill - inside the ${HORIZON_H}h horizon"
      if [ $((now - fill_at)) -ge $((REPEAT_MIN * 60)) ]; then
        notes+=("filling: $fill"); fill_at=$now
      fi
    else
      show "  growing $fill - outside the ${HORIZON_H}h horizon"
    fi
  elif [ "$p_t" -gt 0 ]; then
    show "  not growing: $(human "$grow") in $((dt / 60))m"
  else
    show "  no previous sample; the fill projection starts next run"
  fi

  if [ "$pct" -ge "$CRIT" ]; then
    lvl=CRIT
    reclaim_eligible[$m]=1
    show "  tier CRIT: ${pct}% >= ${CRIT}%"
    if [ $((now - crit_at)) -ge $((REPEAT_MIN * 60)) ]; then
      n="at ${pct}% (CRIT ${CRIT}%) - needs a human; eligible safe reclaim follows this alert"
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

  pending=
  if [ ${#notes[@]} -gt 0 ]; then
    needs_scan[$m]=1
    msg="[storage-guard $(hostname -s)] $lvl $m ${pct}% used, $(human "$avail") free: $(join '; ' "${notes[@]}"). Diagnostics follow in $STATE/$key.scan"
    if [ "$DRY" = 1 ]; then
      show "  a real run would alert: $msg"
    else
      file="$STATE/$key.$lvl.pending"
      if [ ! -f "$file" ]; then
        alert_seq=$((alert_seq + 1))
        digest=$(printf '%s' "$m" | sha256sum); digest=${digest:0:24}
        id="storage-${HOSTNAME:0:24}-$digest-$lvl-$alert_seq"
        if [ "$STATE_OWNED" != 1 ] || ! { printf '%s %s %s %s %s\n%s\n' "$id" "$warn_on" "$crit_at" "$fill_at" "$alert_seq" "$msg" > "$file.tmp" \
          && mv -f -- "$file.tmp" "$file"; }; then
          FAILED=1
          printf 'storage-guard: cannot retain alert %s; attempting notification without saved state\n' "$id" >&2
          attempt_delivery "$id" "$msg" >/dev/null
          continue
        fi
        pending=$file
        log "ALERT $id $msg"
        comms "$msg"
      fi
    fi
  fi

  if [ "$DRY" = 1 ] || [ "$STATE_OWNED" != 1 ]; then continue; fi
  [ "$keep_sample" = 1 ] && now=$p_t used=$p_used
  printf '%s %s %s %s %s %s\n' "$now" "$used" "$warn_on" "$crit_at" "$fill_at" "$alert_seq" \
    > "$STATE/$key.tmp" && mv -f -- "$STATE/$key.tmp" "$STATE/$key" || FAILED=1
  [ -z "$pending" ] || deliver_pending "$pending" || FAILED=1
done

# Attempt every alert before consumer scans and reclaim.
for m in "${mounts[@]}"; do
  key=$(printf '%s' "$m" | tr -c 'A-Za-z0-9' '_')
  read -r used avail pct _ <<<"$(measure "$m")"
  [[ $used$avail$pct =~ ^[0-9]+$ ]] || continue
  before_reclaim=$used reclaimed=
  # CRIT, first: stale gitignored build output in the Treehouse pools. worktree-prune.sh
  # holds every safety check; this only decides when it runs and reports what it freed.
  wt_note=
  for pool in "${POOL_DIRS[@]}"; do
    [ "$m" = "${pool_mounts[$pool]}" ] && [ -x "$PRUNE_CMD" ] || continue
    if [ "$DRY" = 1 ]; then
      [ -n "${reclaim_eligible[$m]+x}" ] && [ "$pct" -ge "$CRIT" ] && when="would run now" || when="would run only at >= ${CRIT}%"
      show "  CRIT worktree step ($when, stopping once under ${CRIT}%): $(basename "$PRUNE_CMD") - stale gitignored build output in $pool:"
      WORKTREE_PRUNE_POOLS=$pool timeout "$PRUNE_TIMEOUT" "$PRUNE_CMD" --dry-run 2>&1 | sed 's/^/    /'
    elif [ -n "${reclaim_eligible[$m]+x}" ] && [ "$pct" -ge "$CRIT" ]; then
      before=$used
      out=$(WORKTREE_PRUNE_POOLS=$pool timeout "$PRUNE_TIMEOUT" "$PRUNE_CMD" 2>&1)
      read -r used avail pct _ <<<"$(measure "$m")"
      log "  CRIT $m worktree-prune: freed $(human $((before - used))), now ${pct}%"
      while IFS= read -r line; do log "    $line"; done <<<"$out"
      [ "$before" -gt "$used" ] && wt_note="${wt_note:+$wt_note, then }reclaiming $(human $((before - used))) of stale gitignored worktree output"
    fi
  done

  # CRIT: reclaim regenerable Docker data, cheapest first.
  if [ "$m" = "$DOCKER_MOUNT" ]; then
    if [ "$DRY" = 1 ]; then
      read -r e1 e2 e3 <<<"$(estimates)"
      [ -n "${reclaim_eligible[$m]+x}" ] && [ "$pct" -ge "$CRIT" ] && when="would run now" || when="would run only at >= ${CRIT}%"
      i=0
      for e in "${e1:-0}" "${e2:-0}" "${e3:-0}"; do
        s=${STEPS[$i]}; i=$((i + 1))
        show "  CRIT step $i ($when, stopping once under ${CRIT}%): docker ${s#*|} - ${s%%|*}, frees ~$(human "$e")"
      done
    elif [ -n "${reclaim_eligible[$m]+x}" ] && [ "$pct" -ge "$CRIT" ]; then
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

  # Worktree output leads the combined note; Docker data follows.
  [ -n "$wt_note" ] && reclaimed="$wt_note${reclaimed:+, then $reclaimed}"
  if [ "$STATE_OWNED" = 1 ] && [ "$used" -lt "$before_reclaim" ] && [ -f "$STATE/$key" ]; then
    read -r sample_time sample_used saved_warn saved_crit saved_fill saved_seq < "$STATE/$key"
    printf '%s %s %s %s %s %s\n' "$(date +%s)" "$used" "$saved_warn" "$saved_crit" "$saved_fill" "$saved_seq" \
      > "$STATE/$key.tmp" && mv -f -- "$STATE/$key.tmp" "$STATE/$key" || FAILED=1
  fi
  if [ -n "${needs_scan[$m]+x}" ] || [ "$DRY" = 1 ]; then
    show "  scanning $m consumers (du, up to ${SCAN_TIMEOUT}s)..."
    scan "$m"
    top="top: $(printf '%s\n' "$SCAN_OUT" | top_consumers)"
    [ "$SCAN_PARTIAL" = 1 ] && top+=" (partial: du hit ${SCAN_TIMEOUT}s)"
    [ "$m" = "$DOCKER_MOUNT" ] && top+="; docker: $(docker_df)"
    snapshot=$(printf '%s %s\n%s\n' "$(date +%s)" $((1 - SCAN_PARTIAL)) "$SCAN_OUT")
    if [ -f "$STATE/$key.scan" ]; then
      g=$(printf '%s\n' "$snapshot" | growers "$STATE/$key.scan")
      [ -z "$g" ] || top+="; grew most in the $g"
    fi
    say "DIAGNOSTICS $m $top${reclaimed:+; $reclaimed}"
    if [ "$STATE_OWNED" = 1 ]; then
      printf '%s\n' "$snapshot" > "$STATE/$key.scan.tmp" \
        && mv -f -- "$STATE/$key.scan.tmp" "$STATE/$key.scan" || FAILED=1
    fi
  fi
done
exit "$FAILED"
