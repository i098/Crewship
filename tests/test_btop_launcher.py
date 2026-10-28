"""The btop launcher restarts a btop that wedged on an unread pty."""

import os
import pty
import select
import shutil
import signal
import stat
import time
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "blueprint" / "maintenance" / "btop.sh"


def wait_until(condition, what, fd=None):
    """Poll for a state; the deadline only bounds a hang, no assertion depends on it."""
    seen = b""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if fd is not None and select.select([fd], [], [], 0.05)[0]:
            seen += os.read(fd, 65536)
        else:
            time.sleep(0.05)
        if condition(seen):
            return seen
    raise AssertionError(f"never reached: {what}")


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_btop_blocked_on_an_unread_pty_restarts_once_the_pty_is_read(tmp_path):
    shutil.copy(LAUNCHER, tmp_path / "btop")
    log = tmp_path / "starts"
    fake = tmp_path / "btop-bin"
    fake.write_text(f"#!/bin/sh\necho $$ >> {log}\nexec yes\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    starts = lambda: log.read_text().split() if log.exists() else []  # noqa: E731
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(tmp_path / "btop", [str(tmp_path / "btop")])
    try:
        # Nobody reads the pty, so the stand-in blocks in write until the launcher kills it.
        wait_until(lambda _: starts(), "first start")
        first = int(starts()[0])
        wait_until(lambda _: not alive(first), "watchdog kills the blocked stand-in")
        # The launcher now waits for the pty to drain: no second start while unread.
        assert len(starts()) == 1
        output = wait_until(lambda seen: b"\x1b[2J" in seen, "clear after drain", fd)
        assert b"\x1b[2J" in output
        wait_until(lambda _: len(starts()) >= 2, "restart after drain", fd)
    finally:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
