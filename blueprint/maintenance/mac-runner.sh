#!/bin/bash
# GitHub Actions just-in-time (JIT) runners on a Mac: one launchd user agent per
# repository, one job per runner, every file in the folder that holds this script.
#
#   mac-runner.sh install OWNER/NAME...   download the latest official runner (SHA-256
#                                         checked) and start one agent per repository
#   mac-runner.sh run OWNER/NAME          the agent's program: register a JIT runner, run one job
#   mac-runner.sh remove                  stop every agent, delete its plist and this folder
#
# Put the script in ~/actions-runner-<name>/ first. Jobs get labels self-hosted, macOS,
# ARM64 and mac-<NAME>. docs/ci-pool.md#macos-runner has the operator guide.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
AGENTS="$HOME/Library/LaunchAgents"
PREFIX=com.crewship.mac-runner

die() { echo "mac-runner: $*" >&2; exit 1; }

case "$ROOT" in "$HOME"/actions-runner-?*) ;; *) die "put this script in ~/actions-runner-<name>/, not $ROOT" ;; esac

install() {
  [ $# -gt 0 ] || die "name at least one OWNER/NAME"
  [ "$(uname -m)" = arm64 ] || die "Apple silicon only"
  local gh asset url digest repo slug dir plist
  gh=$(command -v gh) || die "gh is not on PATH"
  asset=$(gh api repos/actions/runner/releases/latest --jq \
    '.assets[] | select(.name | test("^actions-runner-osx-arm64-[0-9.]+[.]tar[.]gz$")) | .browser_download_url + " " + .digest')
  url=${asset% *} digest=${asset#* sha256:}
  curl -fsSL -o "$ROOT/runner.tar.gz" "$url"
  echo "$digest  $ROOT/runner.tar.gz" | shasum -a 256 -c - >/dev/null || die "checksum mismatch for $url"

  # Refuse a job whose code comes from outside the repository: a fork's pull request,
  # or a workflow_run that one started. Killing the process group ends the runner,
  # so no later step runs, not even `if: always()`; launchd then starts a new runner.
  cat >"$ROOT/job-started.sh" <<'HOOK'
#!/bin/bash
head=$(/usr/bin/jq -r 'if .pull_request then (.pull_request.head.repo.full_name // "a deleted fork")
  elif .workflow_run then (.workflow_run.head_repository.full_name // "a deleted fork")
  else env.GITHUB_REPOSITORY end' "$GITHUB_EVENT_PATH")
[ "$head" = "$GITHUB_REPOSITORY" ] && exit 0
echo "mac-runner: refused, the code comes from ${head:-an unreadable event}, not $GITHUB_REPOSITORY" >&2
kill -KILL 0
HOOK
  chmod +x "$ROOT/job-started.sh"

  mkdir -p "$AGENTS"
  for repo in "$@"; do
    slug=${repo/\//-} && dir="$ROOT/$slug" plist="$AGENTS/$PREFIX.$slug.plist"
    launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
    mkdir -p "$dir"
    tar -xzf "$ROOT/runner.tar.gz" -C "$dir"
    cat >"$plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$PREFIX.$slug</string>
  <key>ProgramArguments</key>
  <array><string>/bin/bash</string><string>$ROOT/mac-runner.sh</string><string>run</string><string>$repo</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>$(dirname "$gh"):/usr/bin:/bin:/usr/sbin:/sbin</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>$dir/agent.log</string>
  <key>StandardErrorPath</key><string>$dir/agent.log</string>
</dict>
</plist>
PLIST
    launchctl bootstrap "gui/$(id -u)" "$plist"
    echo "started $PREFIX.$slug: runs-on [self-hosted, macOS, mac-${repo#*/}]"
  done
  rm "$ROOT/runner.tar.gz"
}

run() {
  local repo=$1 dir="$ROOT/${1/\//-}" body jit id
  body=$(printf '{"name": "mac-%s-%s", "runner_group_id": 1, "work_folder": "_work", "labels": ["self-hosted", "macOS", "ARM64", "mac-%s"]}' \
    "${repo#*/}" "$(date +%s)" "${repo#*/}")
  # The Mac's own gh login, read at run time; no token is stored.
  jit=$(gh api --method POST "repos/$repo/actions/runners/generate-jitconfig" --input - <<<"$body") \
    || { sleep 60; die "generate-jitconfig failed for $repo"; }
  id=$(/usr/bin/jq -r .runner.id <<<"$jit")
  echo "$(date '+%F %T') runner $id for $repo"
  rm -rf "$dir/_work" "$dir/_diag" "$dir/tmp"
  mkdir -p "$dir/tmp" "$ROOT/home"
  # Jobs see a HOME inside this folder, so toolchains and caches they install
  # (rustup, npm, the tool cache) stay here and never touch the account's own files.
  env -i USER="$USER" LOGNAME="$USER" LANG=en_US.UTF-8 PATH=/usr/bin:/bin:/usr/sbin:/sbin \
    HOME="$ROOT/home" TMPDIR="$dir/tmp" RUNNER_TOOL_CACHE="$ROOT/home/toolcache" \
    ACTIONS_RUNNER_HOOK_JOB_STARTED="$ROOT/job-started.sh" \
    ACTIONS_RUNNER_INPUT_JITCONFIG="$(/usr/bin/jq -r .encoded_jit_config <<<"$jit")" \
    "$dir/run.sh" && return
  # GitHub removes a runner after its job; this one never ran, so remove it here.
  gh api --method DELETE "repos/$repo/actions/runners/$id" >/dev/null 2>&1 || true
  sleep 60
  return 1
}

remove() {
  local plist
  for plist in "$AGENTS/$PREFIX".*.plist; do
    grep -qF "$ROOT/mac-runner.sh" "$plist" 2>/dev/null || continue
    launchctl bootout "gui/$(id -u)" "$plist" 2>/dev/null || true
    rm "$plist"
  done
  rm -rf "$ROOT"
}

case "${1:-}" in
  install) shift; install "$@" ;;
  run) [ $# -eq 2 ] || die "usage: run OWNER/NAME"; run "$2" ;;
  remove) [ $# -eq 1 ] || die "usage: remove"; remove ;;
  *) sed -n '2,11p' "$0" >&2; exit 2 ;;
esac
