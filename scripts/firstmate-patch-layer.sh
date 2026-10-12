#!/usr/bin/env bash
# Keep a Firstmate checkout on branch main at upstream origin/main plus the
# patch layer in blueprint/patches/firstmate/ (docs/dependencies.md#firstmate-patch-layer).
#
# usage: firstmate-patch-layer.sh apply|check|verify <checkout> <target> <patch-dir>
#   apply   move main to <target> + layer when needed; the last line is
#           "changed" or "unchanged"
#   check   the same decisions and refusals as apply, but move nothing
#   verify  exit 0 only when main is exactly <target> + layer
#
# The layer is built to one side, in a temporary index with git commit-tree, and
# main moves only once the whole layer exists: a patch that stops the run leaves
# the checkout as it was. Each commit takes its author, committer, date and
# message from the patch file, plus a Crewship-Patch trailer naming it, so
# one target and one set of patches always give the same sha. That is what makes
# an unchanged host a no-op.
set -euo pipefail

mode=$1 dir=$2 target=$3
patch_dir=$(cd "$4" && pwd)
g() { git -C "$dir" "$@"; }
die() {
  printf '%s\n' "$*" >&2
  exit 1
}

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
gi() { GIT_INDEX_FILE=$tmp/index git -C "$dir" "$@"; }
# Print the tree of <patch> applied to <commit>. A three-way apply uses the blob
# ids the patch records, so upstream edits near a hunk do not break it.
apply_on() { # <commit> <patch>
  gi read-tree "$1" && gi apply --cached --3way "$2" 2>/dev/null && gi write-tree
}

shopt -s nullglob
patches=("$patch_dir"/*.patch)

# Build <target> + layer. A patch whose change upstream already has is skipped:
# applying it changes nothing, or it applies only in reverse. A patch that
# applies neither way stops the run.
layer=$target
for patch in "${patches[@]}"; do
  name=${patch##*/}
  if tree=$(apply_on "$layer" "$patch") && [ "$tree" != "$(g rev-parse "$layer^{tree}")" ]; then
    info=$(g mailinfo "$tmp/msg" /dev/null <"$patch")
    field() { sed -n "s/^$1: //p" <<<"$info"; }
    export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_AUTHOR_DATE \
      GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL GIT_COMMITTER_DATE
    GIT_AUTHOR_NAME=$(field Author) GIT_COMMITTER_NAME=$GIT_AUTHOR_NAME
    GIT_AUTHOR_EMAIL=$(field Email) GIT_COMMITTER_EMAIL=$GIT_AUTHOR_EMAIL
    GIT_AUTHOR_DATE=$(field Date) GIT_COMMITTER_DATE=$GIT_AUTHOR_DATE
    layer=$({
      field Subject
      if [ -s "$tmp/msg" ]; then
        echo
        cat "$tmp/msg"
      fi
      printf '\nCrewship-Patch: %s\n' "$name"
    } | g commit-tree --no-gpg-sign "$tree" -p "$layer")
    echo "applied: $name"
  elif [ -n "${tree:-}" ] ||
    { gi read-tree "$layer" && gi apply --cached --check --reverse "$patch" 2>/dev/null; }; then
    echo "skipped, upstream already has it: $name"
  else
    die "blueprint/patches/firstmate/$name no longer applies to origin/main ($target)." \
      "The checkout is unchanged. Update the patch for the new upstream code," \
      "or delete it if upstream fixed the problem another way, then re-run."
  fi
done

head=$(g rev-parse HEAD)
branch=$(g symbolic-ref -q --short HEAD || echo 'detached HEAD')

if [ "$mode" = verify ]; then
  [ "$head" = "$layer" ] && [ "$branch" = main ] ||
    die "$dir is at $head on $branch, not main at $layer: origin/main" \
      "($target) plus the patch layer."
  echo "$layer"
  exit 0
fi

if [ "$head" = "$layer" ]; then
  [ "$branch" = main ] ||
    echo "$dir matches origin/main plus the patch layer, but it is on $branch." \
      "Firstmate expects a named branch and verification requires main; run" \
      "\`git checkout main\` there. Provisioning does not change the branch."
  echo unchanged
  exit 0
fi

[ "$branch" = main ] ||
  die "$dir is checked out on $branch instead of main. Switch to main yourself;" \
    "provisioning will not move another branch or a detached HEAD."

# Every commit main has beyond upstream must be a layer commit, marked by its
# Crewship-Patch trailer. The rebuilt layer replaces them all, so an edited,
# added or dropped patch needs no manual reset and nothing else can be lost.
# Migration: layers built before the Crewship rename carry Code-Factory-Patch;
# the first apply replaces them with Crewship-Patch commits.
base=$(g merge-base "$head" "$target") ||
  die "$dir at $head shares no history with origin/main ($target)."
for commit in $(g rev-list "$base..$head"); do
  [ -n "$(g log -1 --format='%(trailers:key=Crewship-Patch,valueonly)%(trailers:key=Code-Factory-Patch,valueonly)' "$commit")" ] ||
    die "$dir carries local commit $commit, which is not upstream and not a" \
      "patch layer commit (no Crewship-Patch trailer). Provisioning never" \
      "discards local work. Push or move that commit, then re-run."
done

if [ "$mode" = check ]; then
  echo "would move main from $head to $layer"
  echo changed
  exit 0
fi

# Not a forced checkout: the tree is clean, git still refuses to overwrite a
# local change, and the old layer commits stay in the reflog.
g checkout --quiet -B main "$layer"
echo "moved main from $head to $layer"
echo changed
