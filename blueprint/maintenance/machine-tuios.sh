#!/bin/sh
# The machine TUIs in one tuios session, one window each, so a single pane shows
# them all and an agent drives them with the tuios control commands.
# Usage: machine-tuios [--no-attach]
# Only a missing window is opened, so a second run changes nothing.
# MACHINE_TUIOS_SESSION names another session, so a test never touches the live one.
set -eu
session=${MACHINE_TUIOS_SESSION:-machine}
# A TUI installed beside this launcher runs from there; the others come from PATH.
case $0 in */*) here=${0%/*} ;; *) here= ;; esac
# window name|command, where the first word is the executable and the rest its arguments.
windows='usage|usage-tui
fleet-health|fleet-health-tui
schedules|crewship schedules
crewboard|crewboard-tui
runs|runs-tui
lavish|lavish-tui
btop|btop'

has_window() {
    tuios list-windows -s "$session" --json |
        jq -e --arg n "$1" 'any(.windows[]; .custom_name == $n or .display_name == $n)' >/dev/null
}

shell=
status=0
tuios ls --json >/dev/null || status=$?
if [ "$status" -eq 3 ]; then
    # No daemon: ls listed only the sessions saved on disk, which a start restores.
    tuios start-server >/dev/null
elif [ "$status" -ne 0 ]; then
    exit "$status"
fi
if ! tuios ls --json | jq -e --arg s "$session" 'any(.[]; .name == $s)' >/dev/null; then
    tuios new "$session" --detach >/dev/null
    shell=$(tuios list-windows -s "$session" --json | jq -r '.windows[0].window_id')
fi

printf '%s\n' "$windows" | while IFS='|' read -r name cmd; do
    if has_window "$name"; then continue; fi
    # shellcheck disable=SC2086 # the command is literal: its words are the executable and its arguments
    set -- $cmd
    exe=$1
    shift
    if [ -n "$here" ] && [ -x "$here/$exe" ]; then
        exe=$here/$exe
    else
        onpath=$(command -v "$exe") || {
            echo "machine-tuios: skipping $name, $exe is not installed" >&2
            continue
        }
        exe=$onpath
    fi
    tuios new-window "$name" -s "$session" --no-focus -- "$exe" "$@" >/dev/null
done

# The one window a new session starts with is a bare shell; it goes once a TUI
# window stands beside it, and stays when no TUI is installed.
if [ -n "$shell" ] &&
    [ "$(tuios list-windows -s "$session" --json | jq '.windows | length')" -gt 1 ]; then
    tuios close-window "$shell" -s "$session" >/dev/null
fi
[ "${1:-}" = --no-attach ] || exec tuios attach "$session"
