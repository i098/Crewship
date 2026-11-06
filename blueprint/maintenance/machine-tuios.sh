#!/bin/sh
# One tuios session, "machine", holding every machine TUI as a window, so a
# single Herdr tab shows them all and an agent drives them with the tuios
# control commands (docs/herdr.md#tuios-machine-tab). Idempotent: an existing
# session keeps its windows; only a missing window is opened again.
# Usage: machine-tuios [--no-attach]
set -eu
bin=${0%/*}
session=machine
# window name, then the command with its arguments
windows='usage|usage-tui
fleet-health|fleet-health-tui
schedules|crewship schedules|crewship-schedules-view
crewboard|crewboard-tui
runs|runs-tui
lavish|lavish-tui
btop|btop'

if ! tuios ls --json | jq -e --arg s "$session" 'any(.[]; .name == $s)' >/dev/null; then
    tuios new "$session" --detach >/dev/null
    first=$(tuios list-windows -s "$session" --json | jq -r '.windows[0].window_id')
fi
printf '%s\n' "$windows" | while IFS='|' read -r name cmd alt; do
    tuios list-windows -s "$session" --json | jq -e --arg n "$name" 'any(.windows[]; .display_name == $n)' >/dev/null && continue
    found=
    for c in "$cmd" "$alt"; do
        [ -n "$c" ] || continue
        exe=${c%% *}
        if [ -x "$bin/$exe" ]; then found="$bin/$c"; break; fi
        if command -v "$exe" >/dev/null; then found=$c; break; fi
    done
    [ -n "$found" ] || { echo "machine-tuios: skipping $name, ${cmd%% *} not installed" >&2; continue; }
    # shellcheck disable=SC2086
    tuios new-window "$name" -s "$session" --no-focus -- $found >/dev/null
done
# The session's first window is a bare shell; drop it once the TUIs are open.
if [ -n "${first:-}" ] && [ "$(tuios list-windows -s "$session" --json | jq '.windows | length')" -gt 1 ]; then
    tuios close-window "$first" -s "$session" >/dev/null
fi
[ "${1:-}" = --no-attach ] || exec tuios attach "$session"
