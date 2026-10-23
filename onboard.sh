#!/usr/bin/env bash
# Bootstrap repository tooling only; no host provisioning without ./ship.sh launch.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
command -v python3 >/dev/null 2>&1 || { echo 'Install Python 3.12+ (Ubuntu 24.04/26.04) first.' >&2; exit 1; }
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else "Python 3.12+ required")'
export PATH="$HOME/.local/bin:$PATH"
# The latest uv release, checksum-verified; a no-op when it is already installed.
python3 "$ROOT/scripts/provisions.py" --home "$HOME" --tools uv >/dev/null
uv sync --project "$ROOT" --locked
REPO_PYTHON="$(uv run --project "$ROOT" --no-sync python -c 'import sys; print(sys.executable)')"
python3 "$ROOT/scripts/provisions.py" --home "$HOME" --python-env "$REPO_PYTHON" >/dev/null
if (($#)); then
  exec "$ROOT/ship.sh" "$@"
fi
printf '%s\n' 'Repository tooling installed. Next: ./ship.sh dock; review .local/host.yml; ./ship.sh chart; ./ship.sh launch.'
