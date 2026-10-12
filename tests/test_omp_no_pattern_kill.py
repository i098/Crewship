"""blueprint/config/omp-no-pattern-kill.ts, run under bun: which commands it blocks."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

pytestmark = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")

BLOCKED = [
    "pkill -f 'ponytail-review main'",
    "sleep 1; killall node",
    "pgrep -f omp | xargs kill",
    "kill $(pgrep -f herdr)",
    "kill `pgrep omp`",
]
ALLOWED = [
    'cmd & pid=$!; kill "$pid"',
    "kill 12345",
    "pgrep -f omp",
    "ls ./pkill-notes",
]


def blocked(tool: str, command: str) -> bool:
    ext = json.dumps(str(ROOT / "blueprint/config/omp-no-pattern-kill.ts"))
    code = f"""
import ext from {ext};
let handler;
ext({{ on: (_event, h) => (handler = h) }});
const result = await handler({{ toolName: {json.dumps(tool)}, input: {{ command: {json.dumps(command)} }} }});
console.log(JSON.stringify(result.block === true));
"""
    out = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_pattern_kills(command):
    assert blocked("bash", command)


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_pid_kills_and_mentions(command):
    assert not blocked("bash", command)


def test_ignores_other_tools():
    assert not blocked("read", "pkill -f anything")
