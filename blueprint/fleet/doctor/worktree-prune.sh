#!/usr/bin/env bash
# worktree-prune.sh - remove stale gitignored build output from Treehouse pools.
#
# Why: a pool worktree keeps node_modules, .venv, target, dist and .next after
# its lane ends, and on a fleet host these directories are the biggest disk
# user after Docker. storage-guard.sh runs this at CRIT; it also runs by hand.
#
# Candidates are directories named in WORKTREE_PRUNE_NAMES, inside a pool
# worktree ($WORKTREE_PRUNE_POOLS/<pool>/<n>/<repo>, default ~/.treehouse),
# that are gitignored and where nothing changed for WORKTREE_PRUNE_AGE_DAYS (7).
# `find` discovers them, by name and age: it stops at the first build directory
# instead of walking the files inside it, which beat `fdu --ignored only` four
# times over on a 165-worktree host (23 s against 94 s). A candidate then goes
# only when the nearest enclosing git repository
#   - ignores it (`git check-ignore`, all rules, not only .gitignore files),
#   - tracks no file in it and has no untracked, non-ignored file in it,
#   - and no nested git repository sits inside it (it may hold unpushed work).
# It is a real directory (never a symlink), its resolved path is still inside
# the worktree, and the worktree is a real directory inside the pools.
#
# Never touched: tracked files, untracked files outside an ignored build
# directory, uncommitted or unpushed work, any path outside the pools, and any
# directory whose name is not in the list.
#
# fdu is optional and never decides what is removed: when it is installed, the
# size in each report line comes from `fdu --view summary` (faster than du on big
# trees), else from du, and the same when fdu fails.
#
# --dry-run prints what a real run would remove and removes nothing.
set -u
export LC_ALL=C
POOLS=${WORKTREE_PRUNE_POOLS:-$HOME/.treehouse}
AGE_D=${WORKTREE_PRUNE_AGE_DAYS:-7}
NAMES=${WORKTREE_PRUNE_NAMES:-node_modules .venv venv target dist build .next .nuxt .turbo .parcel-cache __pycache__ .pytest_cache .mypy_cache .ruff_cache}
DRY=0
case "${1:-}" in
  --dry-run) DRY=1 ;;
  '') ;;
  *) echo "usage: $0 [--dry-run]" >&2; exit 2 ;;
esac
[[ $AGE_D =~ ^[0-9]+$ ]] || { echo "worktree-prune: WORKTREE_PRUNE_AGE_DAYS=$AGE_D is not a whole number" >&2; exit 2; }
read -ra NAME_LIST <<<"$NAMES"
[ ${#NAME_LIST[@]} -gt 0 ] || { echo "worktree-prune: WORKTREE_PRUNE_NAMES is empty" >&2; exit 2; }
for n in "${NAME_LIST[@]}"; do
  [[ $n =~ ^[A-Za-z0-9._-]+$ && $n != . && $n != .. && $n != .git ]] \
    || { echo "worktree-prune: '$n' is not a plain directory name" >&2; exit 2; }
done
POOLS_REAL=$(realpath -e -- "$POOLS" 2>/dev/null) || { echo "worktree-prune: no pools at $POOLS"; exit 0; }
CUTOFF=$(($(date +%s) - AGE_D * 86400))
FDU=0
command -v fdu >/dev/null 2>&1 && FDU=1

human() { numfmt --to=iec --suffix=B "$1" 2>/dev/null || echo "${1}B"; }

# <worktree> -> relative paths of directories matched by name where nothing inside is newer than the cutoff.
candidates_find() {
  local wt=$1 d args=() n
  for n in "${NAME_LIST[@]}"; do args+=(-o -name "$n"); done
  while IFS= read -r -d '' d; do
    [ -z "$(find "$d" -newermt "@$CUTOFF" -print -quit 2>/dev/null)" ] && printf '%s\n' "${d#"$wt"/}"
  done < <(find "$wt" -name .git -prune -o -type d \( -false "${args[@]}" \) -print0 -prune 2>/dev/null)
}

# <directory> -> apparent size in bytes: fdu when installed, du otherwise or when fdu gives nothing.
size_of() {
  local b=
  # --cache off: a snapshot cache must never report a directory it has not just read.
  [ "$FDU" = 1 ] && b=$(fdu "$1" --cache off -q --view summary --size apparent --format json 2>/dev/null \
    | grep -o '"bytes": *[0-9]*' | head -n 1 | grep -o '[0-9]*$')
  [[ $b =~ ^[0-9]+$ ]] || b=$(du -sb -- "$1" 2>/dev/null | cut -f1)
  echo "${b:-0}"
}

# <worktree> <relative path> -> 0 only when every guard in the header holds.
safe() {
  local wt=$1 rel=${2#./} abs real parent base n parts=()
  abs=$wt/$rel base=${rel##*/} parent=${abs%/*}
  # Cheap name checks first: pnpm alone leaves thousands of node_modules inside node_modules.
  [[ " ${NAME_LIST[*]} " == *" $base "* ]] || return 1
  # Only the outermost build directory: a stale directory inside a live node_modules
  # (pnpm keeps node_modules/.pnpm/<pkg>/node_modules) is part of that live tree.
  [[ $rel == */* ]] && IFS=/ read -ra parts <<<"${rel%/*}"
  for n in "${parts[@]}"; do
    [[ " ${NAME_LIST[*]} " == *" $n "* ]] && return 1
  done
  [ -d "$abs" ] && [ ! -L "$abs" ] || return 1
  real=$(realpath -e -- "$abs" 2>/dev/null) || return 1
  [ "$real" = "$(realpath -e -- "$wt")/$rel" ] || return 1
  git -C "$parent" check-ignore -q -- "$base" 2>/dev/null || return 1
  [ -z "$(git -C "$parent" ls-files --cached --others --exclude-standard -- "$base" 2>/dev/null | head -n 1)" ] || return 1
  [ -z "$(find "$abs" -name .git -print -quit 2>/dev/null)" ] || return 1
}

count=0 total=0 skipped=0 scanned=0
for wt in "$POOLS"/*/[0-9]*/*/; do
  wt=${wt%/}
  [ -d "$wt" ] && [ ! -L "$wt" ] && [ -e "$wt/.git" ] || continue
  [ "$(realpath -e -- "$wt" 2>/dev/null)" = "$POOLS_REAL/${wt#"$POOLS"/}" ] || continue
  scanned=$((scanned + 1))
  list=$(candidates_find "$wt")
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    rel=${rel#./}
    if ! safe "$wt" "$rel"; then skipped=$((skipped + 1)); continue; fi
    size=$(size_of "$wt/$rel")
    if [ "$DRY" = 1 ]; then
      echo "would remove $wt/$rel ($(human "$size"))"
    elif rm -rf --one-file-system -- "$wt/$rel"; then
      echo "removed $wt/$rel ($(human "$size"))"
    else
      echo "could not remove $wt/$rel" >&2; continue
    fi
    count=$((count + 1)) total=$((total + size))
  done < <(printf '%s\n' "$list" | sort)
done
echo "worktree-prune: $([ "$DRY" = 1 ] && echo "would remove" || echo removed) $count director$([ "$count" = 1 ] && echo y || echo ies), $(human "$total"), older than ${AGE_D}d, in $scanned worktree(s) under $POOLS (sizes: $([ "$FDU" = 1 ] && echo fdu || echo du), $skipped candidate(s) skipped by the checks)"
exit 0
