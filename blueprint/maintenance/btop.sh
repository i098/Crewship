#!/bin/sh
# btop that fits its pane, installed as ~/.local/bin/btop (docs/herdr.md#btop).
# All four boxes need 80x24 in btop 1.4 (cpu 60 wide, proc 44 beside mem/net
# 36); a Herdr phone pane is about 50 columns. Smaller panes get preset 4 from
# btop.conf (processes only, 44x16), others preset 0 (all boxes). A resize that
# crosses 80x24 restarts btop with the other preset.
# Herdr stops reading the pty of a tab nobody views. btop then blocks in write(2)
# and, once the stall passes about 5 s, never repaints its boxes again even
# after the pty is read (only the clock moves). So a btop blocked in a tty
# write for 3 polls is killed (it cannot exit cleanly), and the next start waits
# until the pty drains.
preset() {
    set -- $(stty size)
    if [ "$1" -ge 24 ] && [ "$2" -ge 80 ]; then echo 0; else echo 4; fi
}
# No job control here, so a background command reads /dev/null unless given
# stdin explicitly. Not </dev/tty: btop takes a /dev/tty* stdin for a Linux
# console and drops to 16-color tty mode.
exec 3<&0
while :; do
    p=$(preset) again=
    "${0%/*}/btop-bin" -p "$p" "$@" <&3 3<&- &
    pid=$!
    trap '[ "$(preset)" = "$p" ] || { again=1; kill -INT "$pid"; }' WINCH
    # A trap runs between sleeps, so a resize is handled within a second.
    stuck=0
    while kill -0 "$pid" 2>/dev/null; do
        sleep 1
        if cat /proc/$pid/task/*/wchan 2>/dev/null | grep -q wait_woken; then stuck=$((stuck + 1)); else stuck=0; fi
        [ "$stuck" -lt 3 ] || { again=1; kill -KILL "$pid"; break; }
    done
    wait "$pid"; rc=$?
    [ "$again" ] || exit "$rc"
    # stty sets with TCSADRAIN: blocks until a client has read all queued output,
    # so btop restarts only once the pty drains.
    stty "$(stty -g)"
    printf '\033[2J\033[H'
done
