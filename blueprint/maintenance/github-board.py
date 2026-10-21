#!/usr/bin/env python3
"""GitHub board: mirror Firstmate work items to issues and a Project.

  github-board.py <firstmate-home> <owner/repo> <project-number>

Run by github-board.timer. Reads <home>/data/backlog.md and
<home>/state/<id>.status read-only: one issue per work item, the Project's
Status field follows the item (Queued, In progress, In review, Done), and new
status lines go to the issue as one comment per item and run. Its own record
is ~/.local/state/github-board/state.json, so an unchanged backlog and
unchanged status files make no GitHub calls. Every call uses the host's gh
login. docs/github-board.md has the operator guide.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

STATE = Path.home() / ".local/state/github-board/state.json"
SECTIONS = {"queued": "Queued", "in flight": "In progress", "done": "Done"}
ITEM = re.compile(r"^- \[[ x]\] ([A-Za-z0-9][\w.-]*) - (.*)$")
# Trailing tasks-axi metadata such as "(repo: x) (kind: ship) (since 2026-01-01)".
METADATA = re.compile(r"(\s*\([\w-]+:? [^)]*\))+$")
# A comment carries at most this many status lines; older ones in the batch are dropped.
COMMENT_LINES = 50


def gh(args):
    """One `gh api` call; a pause after each keeps the run well inside GitHub's limits."""
    try:
        result = subprocess.run(["gh", "api", *args], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as error:
        sys.exit(f"gh api {args[0]} failed: {error.stderr.strip()}")
    time.sleep(1)
    return json.loads(result.stdout or "null")


def read_backlog(text):
    """{id: {title, status, note}} from a tasks-axi markdown backlog."""
    items, status, current = {}, None, None
    for line in text.splitlines():
        if line.startswith("## "):
            status, current = SECTIONS.get(line[3:].strip().lower()), None
        elif status and (match := ITEM.match(line)):
            title = METADATA.sub("", match[2])[:200]
            current = items[match[1]] = {"title": title, "status": status, "note": ""}
        elif current and line.startswith("  "):
            current["note"] += line.strip() + "\n"
    return items


def snapshot(home):
    backlog = home / "data/backlog.md"
    items = read_backlog(backlog.read_text()) if backlog.exists() else {}
    for key, item in items.items():
        status = home / "state" / f"{key}.status"
        item["lines"] = status.read_text().splitlines() if status.exists() else []
        # A worker's `done:` line hands the work to review; the backlog moves it to Done later.
        if item["status"] == "In progress" and item["lines"] and item["lines"][-1].startswith("done"):
            item["status"] = "In review"
    return items


def code_block(lines):
    # Indented, so status text never renders as markdown or pings an @name.
    return "".join(f"    {line}\n" for line in lines)


def listing(gh, path):
    """Every entry of a paginated REST list; --slurp wraps each page in one outer array."""
    pages = gh([f"{path}?per_page=100", "--paginate", "--slurp"])
    return [entry for page in pages for entry in page]


def set_statuses(gh, repo, project, moves):
    """Put each issue on the Project once and set its Status. moves: {issue number: status}."""
    owner, name = repo.split("/")
    kind = "orgs" if gh([f"users/{owner}"])["type"] == "Organization" else "users"
    base = f"{kind}/{owner}/projectsV2/{project}"
    field = next((field for field in listing(gh, f"{base}/fields")
                  if field["name"] == "Status" and field["data_type"] == "single_select"), None)
    if not field:
        raise SystemExit(f"github-board: project {project} of {owner} has no Status field")
    options = {option["name"]["raw"].lower(): option["id"] for option in field["options"]}
    missing = sorted({status for status in moves.values() if status.lower() not in options})
    if missing:
        raise SystemExit(f"github-board: add these options to the Status field: {', '.join(missing)}")
    present = {item["content"]["url"].lower().split("/repos/")[-1]: item["id"]
               for item in listing(gh, f"{base}/items")
               if item["content_type"] == "Issue" and item["content"]}
    for number, status in moves.items():
        item = present.get(f"{repo}/issues/{number}".lower()) or gh([
            f"{base}/items", "-f", "type=Issue", "-f", f"owner={owner}", "-f", f"repo={name}",
            "-F", f"number={number}"])["id"]
        gh(["-X", "PATCH", f"{base}/items/{item}", "-F", f"fields[][id]={field['id']}",
            "-f", f"fields[][value]={options[status.lower()]}"])


def sync(home, repo, project, gh=gh):
    target = {"repo": repo, "project": project}
    saved = json.loads(STATE.read_text()) if STATE.exists() else {}
    state = saved["items"] if {key: saved.get(key) for key in target} == target else {}

    def save():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({**target, "items": state}, indent=1, sort_keys=True))

    moves = {}
    for key, item in snapshot(home).items():
        known = state.get(key)
        if known is None:
            if item["status"] == "Done":
                continue  # finished before the board saw it
            issue = gh([f"repos/{repo}/issues", "-f", f"title={key}: {item['title']}",
                        "-f", f"body={code_block(item['note'].splitlines())}"])
            known = state[key] = {"issue": issue["number"], "status": None, "posted": 0}
            save()
        new = item["lines"][known["posted"]:]
        if new:
            gh([f"repos/{repo}/issues/{known['issue']}/comments",
                "-f", f"body={code_block(new[-COMMENT_LINES:])}"])
        if len(item["lines"]) != known["posted"]:
            known["posted"] = len(item["lines"])
            save()
        if item["status"] != known["status"]:
            if (item["status"] == "Done") != (known["status"] == "Done"):
                state_name = "closed" if item["status"] == "Done" else "open"
                gh(["-X", "PATCH", f"repos/{repo}/issues/{known['issue']}", "-f", f"state={state_name}"])
            moves[key] = item["status"]
    if moves:
        issues = {state[key]["issue"]: status for key, status in moves.items()}
        set_statuses(gh, repo, project, issues)
        for key, status in moves.items():
            state[key]["status"] = status
        save()


def main(argv):
    if len(argv) != 3 or not argv[2].isdigit():
        sys.exit(__doc__)
    sync(Path(argv[0]), argv[1], int(argv[2]))


if __name__ == "__main__":
    main(sys.argv[1:])
