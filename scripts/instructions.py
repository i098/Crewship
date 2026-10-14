#!/usr/bin/env python3
"""Install blueprint/config/AGENTS.md as the global instructions of Claude Code, omp and Codex.

Claude Code and Codex get the text; Claude Code also gets the @RTK.md import
when ~/.claude/RTK.md exists. omp reads ~/.claude/CLAUDE.md through one import
line, because its own AGENTS.md shadows that file. A file that already exists is
handled by --mode: skip leaves it alone, overwrite moves it to
<target>.<UTC time>.bak and writes the text, append (the default) puts the text
in one <!-- crewship:begin --> ... <!-- crewship:end --> block that a re-run
replaces in place. A manifest records the SHA-256 of each whole file this script
wrote; a file that still matches it is Crewship's own and needs no backup.
--enabled auto installs only on a host that already has managed files. stdout is
one JSON result.
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

TEXT = Path(__file__).resolve().parents[1] / "blueprint/config/AGENTS.md"
CLAUDE, OMP, CODEX = ".claude/CLAUDE.md", ".omp/agent/AGENTS.md", ".codex/AGENTS.md"
TARGETS = (CLAUDE, OMP, CODEX)
OMP_IMPORT = f"@~/{CLAUDE}\n"
RTK = ".claude/RTK.md"
MANIFEST = ".local/share/crewship/instructions.json"
BEGIN, END = "<!-- crewship:begin -->", "<!-- crewship:end -->"
MODES = ("skip", "overwrite", "append")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def wanted(home, text):
    body = text.read_text()
    rtk = "\n@RTK.md\n" if (home / RTK).exists() else ""
    return {CLAUDE: body + rtk, OMP: OMP_IMPORT, CODEX: body}


def with_block(current, want):
    """current with the Crewship block set to want; None when the markers are broken."""
    block = f"{BEGIN}\n{want}{END}\n"
    if BEGIN not in current and END not in current:
        return current + ("" if not current else "\n" if current.endswith("\n") else "\n\n") + block
    start, end = current.find(BEGIN), current.find(END)
    if current.count(BEGIN) != 1 or current.count(END) != 1 or end < start:
        return None
    return current[:start] + block.rstrip("\n") + current[end + len(END):]


def place(target, rel, want, mode, written, stamp):
    """Bring one target to want; return (changed, backup, note)."""
    exists = target.exists() or target.is_symlink()
    current = target.read_text() if target.is_file() else None
    if exists and mode == "skip":
        return False, None, None
    own = current is not None and sha(current) == written.get(rel)
    if mode == "overwrite":
        if current == want:
            written[rel] = sha(want)
            return False, None, None
        backup = None
        if exists:
            if own:
                target.unlink()  # never write through a link into its target
            else:
                backup = target.with_name(f"{target.name}.{stamp}.bak")
                os.replace(target, backup)  # a rename keeps a symlink a symlink
        content, written[rel] = want, sha(want)
    else:
        if exists and current is None:
            return False, None, f"{target} is not a regular file; left alone"
        written.pop(rel, None)
        backup = None
        content = with_block("" if own or not exists else current, want)
        if content is None:
            return False, None, f"{target} has a broken {BEGIN} marker; left alone"
        if content == current:
            return False, None, None
        if own:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return True, backup, None


def install(home, text=TEXT, mode="append", enabled="yes"):
    record = home / MANIFEST
    written = json.loads(record.read_text()) if record.is_file() else {}
    if enabled == "auto":  # a host that already has managed files keeps them current
        enabled = "yes" if record.is_file() or any(
            (home / rel).is_file() and BEGIN in (home / rel).read_text() for rel in TARGETS
        ) else "no"
    result = {"changed": False, "installed": [], "backups": [], "skipped": []}
    if enabled == "no":
        return result
    before = dict(written)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:  # a later target failing must not leave an earlier write unrecorded
        for rel, want in wanted(home, text).items():
            changed, backup, note = place(home / rel, rel, want, mode, written, stamp)
            result["changed"] |= changed
            result["installed"].append(str(home / rel))
            result["backups"] += [str(backup)] if backup else []
            result["skipped"] += [note] if note else []
    finally:
        if written != before:
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(json.dumps(written, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--mode", choices=MODES, default="append")
    parser.add_argument("--enabled", choices=("yes", "no", "auto"), default="yes")
    args = parser.parse_args()
    print(json.dumps(install(args.home.resolve(strict=True), mode=args.mode, enabled=args.enabled)))
