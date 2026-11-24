#!/bin/sh
# Retires the CI pool: stops and disables the units an earlier crewship.ci_pool apply made.
# The files stay on the host. Prints one line per unit it changed, so a second run prints nothing.
set -eu
dir="$HOME/.config/systemd/user"
seen=$(mktemp)
trap 'rm -f "$seen"' EXIT

retire() {
  if grep -qxF "$1" "$seen" 2>/dev/null; then return 0; fi
  printf '%s\n' "$1" >> "$seen"
  systemctl --user disable --now "$1" >/dev/null 2>&1 || systemctl --user stop "$1"
  systemctl --user reset-failed "$1" >/dev/null 2>&1 || true
  echo "$1"
}

# A timer still armed can fire between a listing and its own stop and start its service again.
# Stop the timers first, then list everything once more, so that service is seen and stopped.
systemctl --user list-units --plain --no-legend --state=active,activating,failed 'ci-pool-*.timer' \
  | awk '{print $1}' | sort -u | while read -r unit; do
  [ -n "$unit" ] || continue
  retire "$unit"
done
{
  systemctl --user list-units --plain --no-legend --state=active,activating,failed \
    'ci-runner@*.service' 'ci-pool-*' | awk '{print $1}'
  find "$dir" -path '*.wants/*' \( -name 'ci-runner@*' -o -name 'ci-pool-*' \) -exec basename {} \; 2>/dev/null
} | sort -u | while read -r unit; do
  [ -n "$unit" ] || continue
  retire "$unit"
done
