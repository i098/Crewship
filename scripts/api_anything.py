#!/usr/bin/env python3
"""Set up api-anything for every agent on the host; stdout is one JSON result.

The catalog and sessions live in one private state directory. Sharing is off:
settings.json is written only when absent, so an owner who turns sharing on keeps it.
No browser profile is ever read (API_ANYTHING_BROWSER_ROOTS is empty). omp gets the MCP
server in ~/.omp/agent/mcp.json, and omp and Claude Code get the skill with the
Crewship addendum.
"""

import argparse
import json
from pathlib import Path

ADDENDUM = Path(__file__).resolve().parents[1] / "blueprint/config/api-anything-skill.md"
# askedAt makes the "no" an answer: unanswered, the MCP server asks the user to share.
SETTINGS = {"share": False, "askedAt": "2026-11-05T00:00:00.000Z"}
ENV = {"API_ANYTHING_BROWSER_ROOTS": "[]"}
SKILLS = (".omp/agent/skills/api-anything", ".claude/skills/api-anything")
MCP = ".omp/agent/mcp.json"


def write(path, text, mode):
    if path.is_file() and path.read_text() == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return True


def install(home, state):
    state.mkdir(parents=True, exist_ok=True)
    state.chmod(0o700)
    changed = []
    settings = state / "settings.json"
    if not settings.exists():
        changed.append(write(settings, json.dumps(SETTINGS, indent=2) + "\n", 0o600))
    binary = home / ".local/bin/api-anything"
    package = binary.resolve().parents[1]  # <package>/dist/cli.js
    skill = (package / "skills/api-anything/SKILL.md").read_text() + ADDENDUM.read_text()
    for rel in SKILLS:
        changed.append(write(home / rel / "SKILL.md", skill, 0o644))
    config = home / MCP
    servers = json.loads(config.read_text()) if config.is_file() else {}
    entry = {
        "type": "stdio",
        "command": str(binary),
        "args": ["mcp"],
        "env": {"API_ANYTHING_HOME": str(state), **ENV},
    }
    servers.setdefault("mcpServers", {})["api-anything"] = entry
    changed.append(write(config, json.dumps(servers, indent=2) + "\n", 0o600))
    return {"changed": any(changed)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(install(args.home.resolve(strict=True), args.state)))
