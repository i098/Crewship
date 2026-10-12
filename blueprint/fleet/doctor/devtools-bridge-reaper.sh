#!/usr/bin/env bash
# devtools-bridge-reaper.sh - stop unused attached chrome-devtools-axi bridges.
#
# Why: every chrome-devtools-axi session starts a bridge that detaches to init
# by design, plus a chrome-devtools-mcp child. The agent forgets
# `chrome-devtools-axi stop`, and the session that started it can end without
# it. On 2026-09-24 nine idle bridges, up to 98 hours old, held about 18 GB,
# almost all of it swap. With swap full the host sat near load 179 for six
# hours. mem-guardian never saw them: they are neither fleet repo processes nor
# agent panes.
#
# Scope: attached bridges only, CHROME_DEVTOOLS_AXI_BROWSER_URL set in the
# bridge's environment, as the fleet browser ladder sets it for every agent.
# chrome-autoprune refuses those and stops only the disposable ones.
# Every other bridge is skipped: a headed or persistent-profile bridge runs its
# own Chrome inside the tree.
#
# Idle signal: CPU time. A bridge serves every CLI command over its local port
# and forwards it to its MCP child, so a bridge nobody calls accumulates no
# CPU. Measured 2026-09-24 across 20 live bridges over 90 s: idle ones moved 0
# or 1 ticks, bridges in use moved 45 to 4400. Each run records the summed CPU
# ticks of the bridge's whole process tree. A run that sees the tree move more
# than NOISE_TICKS, or the session's own state files change, marks it busy. A
# bridge not busy for IDLE_MIN minutes is reaped. A bridge seen for the first
# time counts as busy at that moment, so nothing is reaped on its first run.
#
# A reaped bridge is cheap to get back: the next chrome-devtools-axi command in
# that session starts a fresh one. Only its MCP connection and page selection
# are dropped; the shared ladder browser keeps its pages and cookies.
#
# Reaping: TERM to the bridge, whose own handler closes its MCP client and
# signals its group; after a 5 s grace, KILL for whatever is left of that exact
# process tree. Every pid is re-validated by start time before it is
# signalled, so a recycled pid is never hit.
#
# Usage: devtools-bridge-reaper.sh [--dry-run]
#   --dry-run prints every attached bridge with its idle time and verdict, and
#   changes nothing (no signal, no state write).
# Runs every 10 minutes from crewship-devtools-bridge-reaper.timer.
# Every reap: devtools-bridge-reaper.log here, one line in COMMS.md for the
# orchestrator, notify-master.sh when present.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
LOG=$HERE/devtools-bridge-reaper.log
COMMS=$HERE/COMMS.md
STATE=$HERE/devtools-bridge-reaper.state
AXI_STATE_DIR=${BRIDGE_REAPER_AXI_STATE_DIR:-$HOME/.chrome-devtools-axi}
IDLE_MIN=${REAPER_IDLE_MIN:-60}
NOISE_TICKS=${REAPER_NOISE_TICKS:-10}
DRY=${REAPER_DRY_RUN:-0}
# The test suite overrides the marker so it never matches a real bridge.
BRIDGE_MARK=${BRIDGE_REAPER_MARK:-chrome-devtools-axi-bridge.js}

case "${1:-}" in
'') ;;
--dry-run) DRY=1 ;;
-h | --help)
  sed -n '2,41p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
  ;;
*)
  printf 'usage: %s [--dry-run]\n' "$0" >&2
  exit 64
  ;;
esac

log() { printf '[%s] %s\n' "$(date -u +%FT%TZ)" "$*" >>"$LOG"; }
comms() { printf '\n## [devtools-bridge-reaper -> orchestrator] %s %s\n' "$(date '+%Y-%m-%d %H:%M')" "$*" >>"$COMMS"; }
notify() {
  [ -x "$HERE/notify-master.sh" ] && "$HERE/notify-master.sh" "$1" "devtools-bridge-reaper" >/dev/null 2>&1
  return 0
}

# One pass over the process table per run: "pid ppid ticks start" for every
# process. /proc/<pid>/stat fields after the ")" that closes comm: $2 ppid,
# $12-$15 utime stime cutime cstime, $20 starttime. One cat and one awk keep the
# run cheap on a thrashing host, which is exactly when this has to work: the
# first version forked several tools per process and could not finish in five
# minutes at load 160.
PROCS=$(cat /proc/[0-9]*/stat 2>/dev/null | awk '{pid = $1; line = $0; sub(/^.*\) /, "", line)
  split(line, f, " "); print pid, f[2], f[12] + f[13] + f[14] + f[15], f[20]}')
start_of() { awk -v p="$1" '$1 == p {print $4; exit}' <<<"$PROCS"; }
live_start_of() { sed -E 's/^.*\) //' "/proc/$1/stat" 2>/dev/null | awk '{print $20}'; }
env_of() { tr '\0' '\n' <"/proc/$1/environ" 2>/dev/null | sed -n "s/^$2=//p" | head -1; }
mem_mb_of() { awk '/^(VmRSS|VmSwap):/ {k += $2} END {print int(k / 1024)}' "/proc/$1/status" 2>/dev/null; }

# This account's attached bridges: exactly
# `node <path>/chrome-devtools-axi-bridge.js`, the argv chrome-devtools-axi
# spawns, with CHROME_DEVTOOLS_AXI_BROWSER_URL set. grep only narrows the
# candidates; an editor, pager or shell that merely names the file fails the
# argv check.
bridge_pids() {
  local p args
  grep -l -a -F "$BRIDGE_MARK" /proc/[0-9]*/cmdline 2>/dev/null |
    sed -n 's#^/proc/\([0-9]*\)/cmdline$#\1#p' |
    while read -r p; do
      [ -O "/proc/$p" ] || continue
      mapfile -d '' -t args 2>/dev/null <"/proc/$p/cmdline" || continue
      [ "${#args[@]}" -eq 2 ] && [ "${args[0]##*/}" = node ] &&
        [ "${args[1]##*/}" = "$BRIDGE_MARK" ] &&
        [ -n "$(env_of "$p" CHROME_DEVTOOLS_AXI_BROWSER_URL)" ] && echo "$p"
    done
}

# shellcheck disable=SC2016 # an awk program; awk, not the shell, expands it
TREE_AWK='{kids[$2] = kids[$2] " " $1; t[$1] = $3}
  END {q[1] = root; n = 1; i = 1; s = 0
    while (i <= n) {p = q[i++]; s += t[p]; if (mode == "list") print p
      m = split(kids[p], k, " "); for (j = 1; j <= m; j++) if (k[j] != "") q[++n] = k[j]}
    if (mode == "ticks") print s}'
tree_of() { awk -v root="$1" -v mode=list "$TREE_AWK" <<<"$PROCS"; }
tree_ticks() { awk -v root="$1" -v mode=ticks "$TREE_AWK" <<<"$PROCS"; }
tree_mem() {
  local t=0 p v
  for p in $(tree_of "$1"); do
    v=$(mem_mb_of "$p")
    t=$((t + ${v:-0}))
  done
  echo "$t"
}

session_dir() { # <session-name>
  case "$1" in '' | default) echo "$AXI_STATE_DIR" ;; *) echo "$AXI_STATE_DIR/sessions/$1" ;; esac
}
# Newest mtime of the session's own state files: a snapshot bumps
# snapshot-generation, a (re)start rewrites bridge.pid.
session_mtime() {
  local d f m=0 v
  d=$(session_dir "$1")
  for f in "$d/snapshot-generation" "$d/bridge.pid"; do
    v=$(stat -c %Y "$f" 2>/dev/null) || continue
    [ "$v" -gt "$m" ] && m=$v
  done
  echo "$m"
}

# TERM goes to the bridge alone; whatever of its tree outlives the grace gets
# KILL. Every pid, the bridge and each descendant, is re-checked against the
# start time recorded in this run's snapshot, so a recycled pid is never
# signalled.
stop_bridge() { # <pid> -> 0 when the whole tree is gone
  local targets=$1 tree p
  tree=$(tree_of "$1")
  for sig in TERM KILL; do
    for p in $targets; do
      [ -d "/proc/$p" ] || continue
      [ "$(live_start_of "$p")" = "$(start_of "$p")" ] || continue
      kill -s "$sig" "$p" 2>/dev/null
    done
    for _ in 1 2 3 4 5; do
      local alive=0
      for p in $tree; do [ -d "/proc/$p" ] && alive=1; done
      [ "$alive" -eq 0 ] && return 0
      sleep 1
    done
    targets=$tree
  done
  return 1
}

now=$(date +%s)
declare -A PREV_TICKS=() PREV_BUSY=()
if [ -f "$STATE" ]; then
  while read -r key ticks busy; do
    [ -n "${key:-}" ] || continue
    PREV_TICKS[$key]=$ticks
    PREV_BUSY[$key]=$busy
  done <"$STATE"
fi

new_state=""
reaped=0 freed=0
for pid in $(bridge_pids); do
  start=$(start_of "$pid")
  [ -n "$start" ] || continue
  key="$pid:$start"
  session=$(env_of "$pid" CHROME_DEVTOOLS_AXI_SESSION)
  session=${session:-default}
  ticks=$(tree_ticks "$pid")
  smtime=$(session_mtime "$session")
  if [ -z "${PREV_TICKS[$key]:-}" ]; then
    busy=$now
    why=new
  elif [ $((ticks - PREV_TICKS[$key])) -gt "$NOISE_TICKS" ]; then
    busy=$now
    why="cpu +$((ticks - PREV_TICKS[$key]))"
  elif [ "$smtime" -gt "${PREV_BUSY[$key]:-0}" ]; then
    busy=$smtime
    why="state files touched"
  else
    busy=${PREV_BUSY[$key]:-$now}
    why="idle"
  fi
  idle_min=$(((now - busy) / 60))
  mem=$(tree_mem "$pid")
  if [ "$idle_min" -ge "$IDLE_MIN" ]; then
    if [ "$DRY" = 1 ]; then
      printf 'would reap bridge %s session=%s idle=%smin mem=%sMB\n' "$pid" "$session" "$idle_min" "$mem"
      new_state+="$key $ticks $busy"$'\n'
      continue
    fi
    if stop_bridge "$pid"; then
      log "REAPED bridge $pid session=$session idle=${idle_min}min freed~${mem}MB"
      reaped=$((reaped + 1))
      freed=$((freed + mem))
    else
      log "FAILED to stop bridge $pid session=$session idle=${idle_min}min mem=${mem}MB"
      new_state+="$key $ticks $busy"$'\n'
    fi
    continue
  fi
  [ "$DRY" = 1 ] && printf 'keep bridge %s session=%s idle=%smin mem=%sMB (%s)\n' "$pid" "$session" "$idle_min" "$mem" "$why"
  new_state+="$key $ticks $busy"$'\n'
done

if [ "$DRY" != 1 ]; then
  printf '%s' "$new_state" >"$STATE.tmp" && mv "$STATE.tmp" "$STATE"
  if [ "$reaped" -gt 0 ]; then
    comms "Stopped $reaped idle chrome-devtools-axi bridge(s) (no CPU and no session activity for ${IDLE_MIN}+ min), freeing about ${freed} MB. A session's next chrome-devtools-axi command starts a fresh bridge."
    notify "devtools-bridge-reaper stopped $reaped idle bridge(s), ~${freed} MB freed"
  fi
fi
exit 0
