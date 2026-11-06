#!/bin/sh
# One JIT runner per container: run.sh exits when the single job ends, which stops the container.
[ -n "$JITCONFIG" ] || { echo "no JITCONFIG" >&2; exit 2; }
exec /home/runner/run.sh --jitconfig "$JITCONFIG"
