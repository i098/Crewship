"""Fail closed on Herdr: a test that forgets its stub must not reach the live session.

Each pytest process puts a refusing `herdr` first in PATH and drops the variables
that point Herdr calls elsewhere. Tests that stub Herdr put their stub before it.
A real Herdr is reached only through tests/herdr-lab (CONTRIBUTING.md).
"""

import os
import subprocess
import tempfile
from pathlib import Path

from sharding import assign, load_durations

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

# CREWSHIP_TEST_TIMEOUT_SCALE (float) multiplies every subprocess timeout (the 10 s and 30 s limits), the wait_for limits
# and the bridge's voice-call limit. Unset, it follows the load: a host whose run queue is longer than its CPU count starves
# every bun and python child, so each limit stretches by that ratio (at most 8). An idle host or CI keeps 1.
_SCALE = float(os.environ.get("CREWSHIP_TEST_TIMEOUT_SCALE") or min(8.0, max(1.0, os.getloadavg()[0] / (os.cpu_count() or 1))))
os.environ["CREWSHIP_TEST_TIMEOUT_SCALE"] = str(_SCALE)  # xdist workers and the tests' own limits read the same value
if _SCALE != 1:
    _communicate, _wait = subprocess.Popen.communicate, subprocess.Popen.wait

    def _scale(timeout):
        return None if timeout is None else timeout * _SCALE

    def _communicate_scaled(self, input=None, timeout=None):
        self._in_communicate = True
        try:
            return _communicate(self, input, _scale(timeout))
        finally:
            self._in_communicate = False

    def _wait_scaled(self, timeout=None):
        return _wait(self, timeout if getattr(self, "_in_communicate", False) else _scale(timeout))

    subprocess.Popen.communicate = _communicate_scaled
    subprocess.Popen.wait = _wait_scaled


def pytest_collection_modifyitems(config, items):
    """CI shards the suite: CREWSHIP_TEST_SHARD=K/N keeps the tests assigned to shard K of N (see tests/sharding.py)."""
    shard = os.environ.get("CREWSHIP_TEST_SHARD")
    if not shard:
        return
    index, count = (int(part) for part in shard.split("/"))
    assert 1 <= index <= count, f"CREWSHIP_TEST_SHARD={shard} is not K/N with 1 <= K <= N"
    owners = assign([item.nodeid for item in items], load_durations(), count)
    items[:] = [item for item, owner in zip(items, owners) if owner == index - 1]


try:
    from testmon.process_code import Module, get_source_sha
    from testmon.testmon_core import SourceTree
except ImportError:  # pytest-testmon is a dev dependency; the plugin may be absent
    pass
else:
    _get_file = SourceTree.get_file

    def _get_file_any_extension(self, filename):
        """pytest-testmon 2.3.0 crashes on a traced file without an extension (an
        extensionless script such as tools/herdr-patch/herdr-patch). Track it as a whole file."""
        try:
            return _get_file(self, filename)
        except IndexError:
            code, fsha = get_source_sha(directory=self.rootdir, filename=filename)
            mtime = os.path.getmtime(os.path.join(self.rootdir, filename))
            module = Module(
                source_code=code,
                mtime=mtime,
                ext="txt",
                fs_fsha=fsha,
                filename=filename,
                rootdir=self.rootdir,
            )
            self.cache[filename] = module
            return module

    SourceTree.get_file = _get_file_any_extension
