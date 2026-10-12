#!/bin/sh
# btop that fits its pane, installed as ~/.local/bin/btop (docs/herdr.md#btop).
# All four boxes need 80x24 in btop 1.4 (cpu 60 wide, proc 44 beside mem/net
# 36); a Herdr phone pane is about 50 columns. Smaller panes get preset 4 from
# btop.conf (processes only, 44x16), others preset 0 (all boxes). A resize that
# crosses 80x24 restarts btop with the other preset.
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
    # wait returns early when WINCH runs the trap; keep waiting until btop exits.
    while wait "$pid"; rc=$?; kill -0 "$pid" 2>/dev/null; do :; done
    [ "$again" ] || exit "$rc"
done
