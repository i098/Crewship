#!/usr/bin/env bash
# Builds the release artifact install.sh installs: crewship-TAG.tar.gz, a `git archive`
# of TAG (so no .git, one top-level directory), and crewship-TAG.tar.gz.sha256 in OUTDIR.
# REV (default TAG) is the commit to archive; the release workflow and the tests share this script.
# Usage: scripts/build-release-artifact.sh TAG OUTDIR [REV]
set -euo pipefail
tag=${1:?usage: build-release-artifact.sh TAG OUTDIR [REV]}
out=${2:?usage: build-release-artifact.sh TAG OUTDIR [REV]}
name=crewship-$tag.tar.gz
mkdir -p "$out"
git archive --format=tar.gz --prefix="crewship-$tag/" -o "$out/$name" "${3:-$tag}"
(cd "$out" && sha256sum "$name" >"$name.sha256")
