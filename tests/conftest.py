"""Fail closed on Herdr: a test that forgets its stub must not reach the live session.

Each pytest process puts a refusing `herdr` first in PATH and drops the variables
that point Herdr calls elsewhere. Tests that stub Herdr put their stub before it.
A real Herdr is reached only through tests/herdr-lab (CONTRIBUTING.md).
"""

import os
import tempfile
from pathlib import Path

REFUSE = Path(tempfile.mkdtemp(prefix="crewship-no-herdr-")) / "herdr"
REFUSE.write_text(
    "#!/bin/sh\n"
    'echo "herdr: refused under pytest; stub it or use tests/herdr-lab: $*" >&2\n'
    "exit 97\n"
)
REFUSE.chmod(0o755)
os.environ["PATH"] = f"{REFUSE.parent}{os.pathsep}{os.environ.get('PATH', '')}"
for name in ("HERDR_BIN_PATH", "HERDR_SESSION", "HERDR_SOCKET_PATH"):
    os.environ.pop(name, None)


def pytest_collection_modifyitems(config, items):
    """CI shards the suite: CREWSHIP_TEST_SHARD=K/N keeps every Nth collected test, starting at K."""
    shard = os.environ.get("CREWSHIP_TEST_SHARD")
    if not shard:
        return
    index, count = (int(part) for part in shard.split("/"))
    assert 1 <= index <= count, f"CREWSHIP_TEST_SHARD={shard} is not K/N with 1 <= K <= N"
    items[:] = items[index - 1 :: count]
