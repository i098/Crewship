#!/usr/bin/env bash
# Prune regenerable data and alert when disk or RAM use exceeds PRESSURE_PCT (70).
# Disk: the filesystems holding /, the home and Docker's data root. RAM: used =
# MemTotal - MemAvailable. Above the threshold, only these safe targets go:
#   all docker builder cache and all unused images (builder prune -af, image
#   prune -af); finished /tmp/pytest-of-* dirs (idle for
#   PRESSURE_SCRATCH_MIN_AGE_MIN minutes, nothing holding an open file under them,
#   no .git inside); uv cache prune and bun pm cache rm while no uv or bun process runs.
# Never: docker volume prune, worktrees, git checkouts, anything with an open fd.
# Then one alert (fm-inbox note, else notify-master.sh, else wall), repeated at
# most every PRESSURE_REPEAT_MIN minutes while pressure lasts. When a reading is
# still over after every prune, it also texts the owner one sentence through
# PRESSURE_TEXT_CMD (default fm-imessage).
# --dry-run prints what would run and writes, deletes and alerts nothing.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
THRESH=${PRESSURE_PCT:-70}
TEXT_CMD=${PRESSURE_TEXT_CMD:-fm-imessage}
SCRATCH_MIN=${PRESSURE_SCRATCH_MIN_AGE_MIN:-60}
REPEAT_MIN=${PRESSURE_REPEAT_MIN:-30}
TMP_ROOT=${PRESSURE_TMP_ROOT:-/tmp}
MEMINFO=${PRESSURE_MEMINFO:-/proc/meminfo}
STATE=${PRESSURE_STATE_DIR:-${STORAGE_DATA_DIR:+$STORAGE_DATA_DIR/pressure-guard}}
STATE=${STATE:-$HERE/.pressure-guard}
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  '') ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
for v in THRESH SCRATCH_MIN REPEAT_MIN; do
  [[ ${!v} =~ ^[0-9]+$ ]] || { echo "pressure-guard: $v=${!v} is not a whole number" >&2; exit 2; }
done
{ [ "$THRESH" -ge 1 ] && [ "$THRESH" -le 100 ]; } || { echo "pressure-guard: PRESSURE_PCT must be 1-100" >&2; exit 2; }

# Plain docker when the account may use the socket, else passwordless sudo.
DOCKER=(docker)
if command -v docker >/dev/null 2>&1 && ! timeout 20 docker info >/dev/null 2>&1 \
  && timeout 20 sudo -n docker info >/dev/null 2>&1; then DOCKER=(sudo -n docker); fi

ram_pct() { awk '/^MemTotal:/ { t = $2 } /^MemAvailable:/ { a = $2 } END { if (t > 0) printf "%d", (t - a) * 100 / t }' "$MEMINFO"; }
disk_pct() { df --output=pcent -- "$1" 2>/dev/null | awk 'NR == 2 { sub(/%/, ""); print $1 + 0 }'; }
# "label pct" lines: each distinct filesystem once, plus RAM.
readings() {
  local p root seen=" " m
  root=$(timeout 20 "${DOCKER[@]}" info -f '{{.DockerRootDir}}' 2>/dev/null) || root=
  for p in / "$HOME" ${root:+"$root"}; do
    m=$(df --output=target -- "$p" 2>/dev/null | awk 'NR == 2') || continue
    [ -n "$m" ] && [[ $seen != *" $m "* ]] || continue
    seen+="$m "; echo "disk:$m $(disk_pct "$p")"
  done
  echo "ram $(ram_pct)"
}
over() { awk -v t="$THRESH" '$2 + 0 > t { printf "%s%s %s%%", (n++ ? ", " : ""), $1, $2 } END { exit !n }'; }

before=$(readings)
hot=$(over <<<"$before") || {
  if [ "$DRY" = 1 ]; then echo "pressure-guard: below ${THRESH}%: $(tr '\n' ' ' <<<"$before")"; else rm -f "$STATE/last-text"; fi  # recovered: re-arm the text
  exit 0
}
[ "$DRY" = 1 ] && echo "pressure-guard --dry-run: over ${THRESH}%: $hot"

done_steps=()
step() {  # <label> <command...>
  local label=$1; shift
  if [ "$DRY" = 1 ]; then echo "would: $label ($*)"; done_steps+=("$label"); return 0; fi
  if timeout 600 "$@" >/dev/null 2>&1; then done_steps+=("$label"); else echo "pressure-guard: $label failed" >&2; fi
}
have() { command -v "$1" >/dev/null 2>&1; }

if have docker; then
  step "docker builder cache" "${DOCKER[@]}" builder prune -af
  step "unused images" "${DOCKER[@]}" image prune -af
fi

if have lsof; then
  shopt -s nullglob
  for d in "$TMP_ROOT"/pytest-of-*; do
    [ -d "$d" ] && [ ! -L "$d" ] || continue
    [ -z "$(find "$d" -maxdepth 0 -mmin "-$SCRATCH_MIN" 2>/dev/null)" ] || continue
    [ -z "$(find "$d" -maxdepth 4 -name .git -print -quit 2>/dev/null)" ] || continue
    ! timeout 120 lsof -t +D "$d" >/dev/null 2>&1 || continue  # open fd (or lsof failure to look) keeps it
    step "scratch $d" rm -rf --one-file-system -- "$d"
  done
fi

for c in "uv|uv cache prune" "bun|bun pm cache rm"; do
  tool=${c%%|*}; cmd=${c#*|}
  have "$tool" || continue
  ! pgrep -x "$tool" >/dev/null || continue  # a running uv or bun holds the cache
  # shellcheck disable=SC2086  # fixed word list
  step "$tool cache" $cmd
done

[ "$DRY" = 1 ] && exit 0

after=$(readings)
pruned=nothing
((${#done_steps[@]})) && { pruned=$(printf '%s, ' "${done_steps[@]}"); pruned=${pruned%, }; }
msg="pressure-guard: over ${THRESH}%: $hot. Pruned: $pruned. Now: $(tr '\n' ' ' <<<"$after")"
still=0
if over <<<"$after" >/dev/null; then
  still=1; msg+=" Still over ${THRESH}%: needs a human."
  # Biggest entries three levels under each full filesystem, to say what fills it.
  for mnt in $(over <<<"$after" | grep -o 'disk:[^ ]*' | cut -d: -f2-); do
    top=$(nice -n 10 ionice -c3 timeout 120 du -xk -d3 -- "$mnt" 2>/dev/null | awk -v b="$(tr -dc / <<<"${mnt%/}" | wc -c)" \
      '{ n = gsub(/\//, "/", $2) } n == b + 3 { print }' | sort -rn | head -3 \
      | awk '{ k = $1; $1 = ""; printf "%s%s %.1fG", (i++ ? ", " : ""), substr($0, 2), k / 1048576 }')
    [ -z "$top" ] || msg+=" Top under $mnt: $top."
  done
fi

umask 077
mkdir -p "$STATE" 2>/dev/null || STATE=
if [ -n "$STATE" ]; then
  exec 9>>"$STATE/lock"; flock -n 9 || exit 0
  last=$(cat "$STATE/last-alert" 2>/dev/null || echo 0)
  [[ $last =~ ^[0-9]+$ ]] || last=0
  [ $(( $(date +%s) - last )) -ge $((REPEAT_MIN * 60)) ] || { echo "$msg"; exit 0; }
fi
echo "$msg"
fm=${FM_HOME:-}
window=$((REPEAT_MIN * 60)); [ "$window" -gt 0 ] || window=1
id=pressure-guard-$(( $(date +%s) / window ))
if { [ -n "$fm" ] && [ -x "$fm/bin/fm-inbox.sh" ] && FM_HOME=${fm%/} timeout -k 2 5 "$fm/bin/fm-inbox.sh" note --request-id "$id" --json -- "$msg" >/dev/null 2>&1; } \
  || { [ -x "$HERE/notify-master.sh" ] && timeout -k 1 3 "$HERE/notify-master.sh" "$msg" pressure-guard; } \
  || printf '%s\n' "$msg" | timeout -k 1 3 wall -n -t 2; then
  [ -z "$STATE" ] || date +%s > "$STATE/last-alert"
fi
# One text per still-over state: the key is the set of over-threshold readings.
key=$(over <<<"$after" | tr -dc 'a-z:/ ,' | tr -c 'A-Za-z0-9\n' _)
if [ "$still" = 1 ] && [ -z "$STATE" ] || [ "$(cat "$STATE/last-text" 2>/dev/null)" != "$key" ]; then
  timeout 15 "$TEXT_CMD" -- "Disk or RAM is still over ${THRESH}% after pruning; needs you." >/dev/null 2>&1 \
    && { [ -z "$STATE" ] || printf '%s\n' "$key" > "$STATE/last-text"; } \
    || echo "pressure-guard: owner text failed" >&2
fi
