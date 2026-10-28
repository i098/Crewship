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


def drain(fd, seconds):
    data, end = b"", time.time() + seconds
    while time.time() < end:
        if select.select([fd], [], [], 0.1)[0]:
            data += os.read(fd, 65536)
    return data


def test_btop_blocked_on_an_unread_pty_restarts_once_the_pty_is_read(tmp_path):
    shutil.copy(LAUNCHER, tmp_path / "btop")
    log = tmp_path / "starts"
    fake = tmp_path / "btop-bin"
    fake.write_text(f"#!/bin/sh\necho start >> {log}\nexec yes\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(tmp_path / "btop", [str(tmp_path / "btop")])
    try:
        time.sleep(7)  # nobody reads the pty: the btop stand-in blocks in write
        assert log.read_text().count("start") == 1
        output = drain(fd, 3)
        assert b"\x1b[2J" in output
        assert log.read_text().count("start") >= 2
    finally:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
