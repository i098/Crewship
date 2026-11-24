#!/bin/sh
# Retires the CI pool: stops and disables the units an earlier crewship.ci_pool apply made.
# The files stay on the host. Prints one line per unit it changed, so a second run prints nothing.
set -eu
dir="$HOME/.config/systemd/user"
{
  systemctl --user list-units --plain --no-legend --state=active,activating,failed \
    'ci-runner@*.service' 'ci-pool-*' | awk '{print $1}'
  find "$dir" -path '*.wants/*' \( -name 'ci-runner@*' -o -name 'ci-pool-*' \) -exec basename {} \; 2>/dev/null
} | sort -u | while read -r unit; do
  [ -n "$unit" ] || continue
  systemctl --user disable --now "$unit" >/dev/null 2>&1 || systemctl --user stop "$unit"
  systemctl --user reset-failed "$unit" >/dev/null 2>&1 || true
  echo "$unit"
done
