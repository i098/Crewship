#!/usr/bin/env python3
"""Install blueprint/config/AGENTS.md as the global instructions of Claude Code, omp and Codex.

The text goes to every target in TARGETS; Claude Code also gets the @RTK.md
import when ~/.claude/RTK.md exists. A manifest records the SHA-256 of what
this script last wrote to each target. A target that matches neither that
record nor the new text was changed by the user, so it is moved to
<target>.<UTC time>.bak before the write and listed under `backups`. stdout is
one JSON result.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

TEXT = Path(__file__).resolve().parents[1] / "blueprint/config/AGENTS.md"
TARGETS = (".claude/CLAUDE.md", ".omp/agent/AGENTS.md", ".codex/AGENTS.md")
RTK = ".claude/RTK.md"
MANIFEST = ".local/share/crewship/instructions.json"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def install(home, text=TEXT):
    record = home / MANIFEST
    written = json.loads(record.read_text()) if record.is_file() else {}
    before = dict(written)
    changed, backups = False, []
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:  # a later target failing must not leave an earlier write unrecorded
        for rel in TARGETS:
            target = home / rel
            want = text.read_bytes()
            if rel == ".claude/CLAUDE.md" and (home / RTK).exists():
                want += b"\n@RTK.md\n"
            current = target.read_bytes() if target.is_file() else None
            if current != want:
                if current is not None or target.is_symlink():
                    if current is None or sha(current) != written.get(rel):
                        backup = target.with_name(f"{target.name}.{stamp}.bak")
                        os.replace(target, backup)  # a rename keeps a symlink a symlink
                        backups.append(str(backup))
                    else:
                        target.unlink()  # never write through a link into its target
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(want)
                changed = True
            written[rel] = sha(want)
    finally:
        if written != before:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps(written, sort_keys=True) + "\n")
    return {"changed": changed, "installed": [str(home / rel) for rel in TARGETS], "backups": backups}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    print(json.dumps(install(parser.parse_args().home.resolve(strict=True))))
