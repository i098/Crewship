#!/usr/bin/env python3
"""Save `secret NAME=value` notes from Signal's Note to Self into a secrets file.

Runs `signal-cli jsonRpc` for a linked account. Only a Note to Self from that same
account, in the exact form `secret NAME=value`, is acted on; every other message is
dropped unread. The value goes into the secrets file as `export NAME='value'` and
nowhere else: not stdout, stderr, an exception text, a log or a reply. The reply is
`saved NAME`. See apps/signal/README.md.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

# One line, so the line-based replace in merge() stays exact; no NUL.
SECRET = re.compile(r"secret ([A-Z][A-Z0-9_]*)=([^\r\n\0]+)")


def log(message: str) -> None:
    """Log text that never holds a message body; callers pass key names and error classes only."""
    print(message, file=sys.stderr, flush=True)


def describe(error: BaseException) -> str:
    """An error as its class and, for OS errors, the system reason; never its arguments."""
    reason = error.strerror if isinstance(error, OSError) and error.strerror else ""
    return f"{type(error).__name__} {reason}".strip()


def parse_secret(text: str) -> tuple[str, str] | None:
    match = SECRET.fullmatch(text)
    return (match[1], match[2]) if match else None


def note_to_self(envelope: dict[str, Any], account: str) -> str | None:
    """The text of a Note to Self sent from `account`; None for any other message."""
    sent = (envelope.get("syncMessage") or {}).get("sentMessage")
    if not isinstance(sent, dict) or "groupInfo" in sent or not isinstance(sent.get("message"), str):
        return None
    sources = {envelope.get(k) for k in ("source", "sourceNumber", "sourceUuid")} - {None}
    targets = {sent.get(k) for k in ("destination", "destinationNumber", "destinationUuid")} - {None}
    # Own sync copies name the account as both sender and recipient; a note to anyone else does not.
    return sent["message"] if account in sources and sources & targets else None


def merge(old: bytes, name: str, value: str) -> bytes:
    """`old` with `export NAME='value'` set; every other byte stays as it was."""
    quoted = "'" + value.replace("'", "'\\''") + "'"
    line = f"export {name}={quoted}\n".encode()
    assignment = re.compile(rb"(?:export[ \t]+)?" + re.escape(name.encode()) + rb"=")
    lines = old.splitlines(keepends=True)
    if not any(assignment.match(each) for each in lines):
        return old + (b"\n" if old and not old.endswith(b"\n") else b"") + line
    # shortcut: a replaced assignment is one line; a value an editor spread over lines keeps its tail.
    return b"".join(line if assignment.match(each) else each for each in lines)


def write_secret(path: Path, name: str, value: str) -> None:
    """Replace `path` atomically, mode 600; a symlinked secrets file stays a symlink."""
    target = Path(os.path.realpath(path))
    try:
        old = target.read_bytes()
    except FileNotFoundError:
        old = b""
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")  # mode 600
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(merge(old, name, value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def handle(line: str, account: str, secrets: Path, reply: Callable[[str], None]) -> None:
    try:
        message = json.loads(line)
        if message.get("method") != "receive":
            if "error" in message:
                log(f"signal-cli request failed, code {(message['error'] or {}).get('code')}")
            return
        text = note_to_self((message.get("params") or {}).get("envelope") or {}, account)
        parsed = parse_secret(text) if text is not None else None
        if parsed is None:
            return
        name, value = parsed
        write_secret(secrets, name, value)
        log(f"saved {name}")
        reply(f"saved {name}")
    except Exception as error:  # one bad message must not stop the bridge; log the class only
        log(f"dropped a message: {describe(error)}")


def serve(signal_cli: str, account: str, secrets: Path) -> int:
    command = [signal_cli, "-a", account, "jsonRpc", "--ignore-attachments", "--ignore-stories",
               "--ignore-avatars", "--ignore-stickers"]
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8"
    )
    requests = 0

    def reply(text: str) -> None:
        nonlocal requests
        requests += 1
        params = {"noteToSelf": True, "message": text}
        request = {"jsonrpc": "2.0", "id": requests, "method": "send", "params": params}
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.flush()

    log("listening for Note to Self")
    for line in process.stdout:
        handle(line, account, secrets, reply)
    return process.wait() or 1  # signal-cli ended: exit nonzero so systemd restarts the bridge


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account", required=True, help="the linked account: +E164 number or ACI")
    parser.add_argument("--secrets-file", type=Path, default=Path("~/super.env").expanduser())
    parser.add_argument("--signal-cli", default="signal-cli")
    args = parser.parse_args(argv)
    return serve(args.signal_cli, args.account, args.secrets_file)


if __name__ == "__main__":
    sys.exit(main())
