#!/usr/bin/env python3
"""Close empty Herdr panes (docs/herdr.md#empty-pane-pruner).

Run by herdr-prune-empty.timer. A pane is closed only when ALL hold:

  * Herdr reports no agent in it;
  * its foreground process is its own shell and that shell has no child;
  * nothing in it changed for IDLE seconds (screen text, title, directory),
    tracked in a small state file between runs;
  * no `state/*.meta` of any Firstmate home records it (`window=`,
    `herdr_pane_id=`, `hiatus_window=`);
  * it is not MAIN_PANE and its tab is not named in KEEP_TABS;
  * it is not the last pane of the session.

Any read failure or doubt keeps the pane. After closing, tabs and workspaces
left with no pane are closed too. A pane running any process is never touched.

Environment (set by the unit): FM_HOME (main Firstmate home, required), its
data/secondmates.md lists the other local homes ("home: <path>"; entries with a
"host:" are on another machine and skipped); EXTRA_HOMES (colon separated);
MAIN_PANE (pane id); KEEP_TABS (comma separated, case-insensitive, default
Concord,crewboard,monitoring); IDLE (seconds, default 600); HERDR_BIN_PATH;
HERDR_SESSION; PRUNE_STATE (state file).

  --dry-run   list every empty pane and what would be closed; close nothing
              (the idle-clock state file is still written). Also forced when
              MAIN_PANE is unset.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_KEEP_TABS = "Concord,crewboard,monitoring"
RECORD_KEYS = ("window", "herdr_pane_id", "hiatus_window")


class Abort(Exception):
    """A read failed: the run keeps every pane."""


def pane_key(value: str) -> str:
    """`default:w1:p2` and `w1:p2` name the same pane."""
    parts = value.strip().split(":")
    return ":".join(parts[-2:]) if len(parts) >= 3 else value.strip()


def read_homes(main: Path, extra: list[str]) -> list[Path]:
    homes = [main, *(Path(p) for p in extra if p)]
    try:
        text = (main / "data/secondmates.md").read_text()
    except FileNotFoundError:
        text = ""
    except OSError as exc:
        raise Abort(f"cannot read secondmates.md: {exc}") from exc
    for line in text.splitlines():
        if re.search(r"\bhost:", line):
            continue
        # Only an absolute or ~ path counts: prose after "home:" in a description is not a home.
        for found in re.finditer(r"\bhome:\s*([/~][^;)]*)", line):
            homes.append(Path(found.group(1).strip()).expanduser())
    return homes


def recorded_panes(homes: list[Path]) -> set[str]:
    """Pane ids recorded by any home's meta; an unreadable state dir aborts."""
    ids: set[str] = set()
    for home in homes:
        try:
            metas = sorted((home / "state").glob("*.meta"))
            if not (home / "state").is_dir():
                raise Abort(f"no state directory in a listed home: {home.name}")
            for meta in metas:
                for line in meta.read_text().splitlines():
                    key, _, value = line.partition("=")
                    if key in RECORD_KEYS and value.strip():
                        ids.add(pane_key(value))
        except OSError as exc:
            raise Abort(f"cannot read state of {home.name}: {exc}") from exc
    return ids


def children(pid: int) -> list[int]:
    """Direct children of pid from /proc; any read failure raises OSError."""
    out: list[int] = []
    for task in Path(f"/proc/{pid}/task").iterdir():
        out += [int(c) for c in (task / "children").read_text().split()]
    return out


def keep_reason(pane, info, tab_label, ctx) -> str | None:
    """Why this pane must stay, or None when it is an empty bare shell."""
    pid = pane_key(pane["pane_id"])
    if pid in ctx["recorded"]:
        return "recorded by a home's meta"
    if pid == ctx["main_pane"]:
        return "main firstmate pane"
    if tab_label.lower() in ctx["keep_tabs"]:
        return f"tab {tab_label} is kept"
    if pane.get("agent") or pane.get("agent_status") not in (None, "unknown"):
        return "agent in pane"
    shell = info.get("shell_pid")
    fg = info.get("foreground_processes")
    if not shell or not isinstance(fg, list) or [p.get("pid") for p in fg] != [shell]:
        return "foreground process is not the bare shell"
    try:
        if ctx["children"](shell):
            return "shell has a child process"
    except (OSError, ValueError):
        return "cannot read shell children"
    return None


def fingerprint(pane, text: str) -> str:
    seen = [pane.get("terminal_id"), pane.get("cwd"), pane.get("terminal_title"), text]
    return hashlib.sha256(json.dumps(seen).encode()).hexdigest()


class Herdr:
    def __init__(self, binary: str, session: str | None):
        self.base = [binary] + (["--session", session] if session else [])

    def call(self, *args, parse=True):
        cmd = [self.base[0], *args, *self.base[1:]]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True).stdout
            return json.loads(out)["result"] if parse else out
        except (OSError, subprocess.SubprocessError, ValueError, KeyError) as exc:
            raise Abort(f"herdr {' '.join(args[:2])} failed: {exc}") from exc

    def panes(self):
        return self.call("pane", "list")["panes"]

    def tabs(self):
        return self.call("tab", "list")["tabs"]

    def workspaces(self):
        return self.call("workspace", "list")["workspaces"]

    def process_info(self, pane_id):
        return self.call("pane", "process-info", "--pane", pane_id)["process_info"]

    def read(self, pane_id):
        return self.call(
            "pane", "read", pane_id, "--source", "recent", "--lines", "200", parse=False
        )

    def close(self, kind, ident):
        self.call(kind, "close", ident)


def load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}  # no record means the idle clock starts over: panes stay


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state))
    tmp.replace(path)


def prune(herdr, ctx, state, now, idle, dry_run, log=print):
    """Close every empty pane idle for `idle` seconds; return the closed ids."""
    panes = herdr.panes()
    labels = {t["tab_id"]: str(t.get("label", "")) for t in herdr.tabs()}
    seen: dict[str, dict] = {}
    closed: list[str] = []
    for pane in panes:
        pid = pane["pane_id"]
        tab = labels.get(pane["tab_id"], "")
        try:
            info = herdr.process_info(pid)
            why = keep_reason(pane, info, tab, ctx)
            if why:
                continue
            print_ = fingerprint(pane, herdr.read(pid))
        except Abort as exc:
            log(f"keep {pid}: {exc}", file=sys.stderr)
            continue
        before = state.get(pid)
        since = before["since"] if before and before["print"] == print_ else now
        seen[pid] = {"print": print_, "since": since}
        age = int(now - since)
        if age < idle:
            if dry_run:
                log(f"keep {pid} tab={tab}: empty shell, idle {age}s of {idle}s")
            continue
        if len(panes) - len(closed) <= 1:
            log(f"keep {pid} tab={tab}: last pane of the session")
            continue
        log(
            f"{'would close' if dry_run else 'close'} pane {pid} tab={tab} "
            f"workspace={pane['workspace_id']} reason=bare shell, no child, idle {age}s"
        )
        if not dry_run:
            herdr.close("pane", pid)
        closed.append(pid)
    state.clear()
    state.update(seen)
    return closed


def sweep(herdr, ctx, dry_run, log=print):
    """Close tabs and workspaces that hold no pane."""
    for tab in herdr.tabs():
        if tab.get("pane_count") == 0 and str(tab.get("label", "")).lower() not in ctx["keep_tabs"]:
            log(f"{'would close' if dry_run else 'close'} tab {tab['tab_id']} reason=no pane")
            if not dry_run:
                herdr.close("tab", tab["tab_id"])
    for ws in herdr.workspaces():
        if ws.get("pane_count") == 0:
            log(
                f"{'would close' if dry_run else 'close'} workspace {ws['workspace_id']} reason=no pane"
            )
            if not dry_run:
                herdr.close("workspace", ws["workspace_id"])


def main(argv) -> int:
    dry_run = "--dry-run" in argv
    if not os.environ.get("MAIN_PANE", "").strip():
        print("MAIN_PANE is not set: closing nothing (dry run)", file=sys.stderr)
        dry_run = True
    env = os.environ
    try:
        main_home = Path(env["FM_HOME"])
        homes = read_homes(main_home, env.get("EXTRA_HOMES", "").split(":"))
        ctx = {
            "recorded": recorded_panes(homes),
            "main_pane": pane_key(env.get("MAIN_PANE", "")),
            "keep_tabs": {
                t.strip().lower()
                for t in env.get("KEEP_TABS", DEFAULT_KEEP_TABS).split(",")
                if t.strip()
            },
            "children": children,
        }
        herdr = Herdr(env.get("HERDR_BIN_PATH", "herdr"), env.get("HERDR_SESSION"))
        state_path = Path(
            env.get("PRUNE_STATE") or Path.home() / ".local/state/crewship/herdr-prune-empty.json"
        )
        state = load_state(state_path)
        prune(herdr, ctx, state, time.time(), int(env.get("IDLE", "600")), dry_run)
        sweep(herdr, ctx, dry_run)
        save_state(state_path, state)
    except (Abort, KeyError) as exc:
        print(f"keep everything: {exc!r}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
