#!/usr/bin/env bash
# Checks that the pi adapter sources of one no-mistakes release still match the
# sources omp-as-pi was proven against (no-mistakes v1.85.3).
# Usage: check-adapter.sh <tag>   (ansible/tasks/agents.yml runs it on every apply)
# Exit 0: every source matches its pin.
# Exit 1: a source differs from its pin, or is gone from the tag (HTTP 404); the
#         adapter moved, so omp-as-pi must be re-proven against this release.
# Exit 2: inconclusive (network error, timeout, any other HTTP status); nothing
#         was proven either way.
# Exit 64: usage.
set -o pipefail
[ $# -eq 1 ] || {
	echo "usage: check-adapter.sh <tag>" >&2
	exit 64
}
tag=$1
declare -A PINNED=(
	["internal/agent/pi.go"]=cd5340ef362585592fc1fdaf856a62cdfa3303dde5d324d93b23998c4c0f8d75
	["internal/agentcfg/pi_profile.go"]=be326b6b756e1075d5bf827cec6e80069cd293a79a751ecc7e6dbf0650d490f0
	["internal/agent/fallback.go"]=7f90d1cab045d805509d470404f4263e3e5c985605e13135e357cbe7773987c4
	["internal/agent/ompgate.go"]=8a598685618334afcb689ea7b1006957855f4c694fc0dcc6447faf086e49aed9
)

body=$(mktemp) || exit 2
trap 'rm -f "$body"' EXIT
inconclusive=0
for f in "${!PINNED[@]}"; do
	code=$(curl -sSL --connect-timeout 10 --max-time 30 -o "$body" -w '%{http_code}' \
		"https://raw.githubusercontent.com/kunchenguid/no-mistakes/$tag/$f") || code=000
	case "$code" in
	200)
		got=$(sha256sum <"$body")
		if [ "${got%% *}" != "${PINNED[$f]}" ]; then
			echo "$f changed in $tag (sha ${got%% *}); re-prove omp-as-pi against $tag first"
			exit 1
		fi
		;;
	404)
		echo "$f is gone from $tag (HTTP 404); re-prove omp-as-pi against $tag first"
		exit 1
		;;
	*)
		echo "could not fetch $f at $tag to verify it (HTTP $code)"
		inconclusive=1
		;;
	esac
done
[ "$inconclusive" = 0 ] || exit 2
echo "pi adapter sources at $tag match the pins"
