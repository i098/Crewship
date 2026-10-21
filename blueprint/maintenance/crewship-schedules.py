#!/usr/bin/env python3
"""Browse local schedules without running or changing jobs."""

import argparse
import curses
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import textwrap
import time
import unicodedata
from pathlib import Path

UNKNOWN = "Unknown"
PROPERTIES = (
    "Id,Description,Unit,FragmentPath,TimersCalendar,TimersMonotonic,"
    "NextElapseUSecRealtime,NextElapseUSecMonotonic,LastTriggerUSec,"
    "ActiveState,SubState,ExecStart,WorkingDirectory,Result,ExecMainCode,ExecMainStatus,"
    "ExecMainStartTimestamp,ExecMainExitTimestamp,SuccessExitStatus,"
    "AccuracyUSec,RandomizedDelayUSec,Persistent"
)
PURPOSES = {
    "swarms-daily-run.sh": "Publish the merged daily item",
    "swarms-daily-tick.sh": "Advance daily item delivery",
    "automations-status.py": "Refresh the automation board",
    "swarms-contrib.py": "Refresh contribution history",
    "sweep-nm-targets.sh": "Remove finished run build output",
    "sweep_cgx_targets.py": "Remove unused finished build output",
    "contributions.check.sh": "Check contribution changes",
    "prune-idle.check.sh": "Find workers idle over ten minutes",
    "weekly-focus.check.sh": "Check weekly focus status",
    **{f"cron.{period}": f"Run {period} maintenance"
       for period in ("hourly", "daily", "weekly", "monthly")},
}


def text(value):
    return "".join(c if c.isprintable() and not unicodedata.category(c).startswith("C")
                   else c.encode("unicode_escape").decode("ascii") for c in str(value))


def run(argv):
    result = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=8,
                            env={**os.environ, "LC_ALL": "C", "TZ": "UTC", "SYSTEMD_COLORS": "0"})
    if result.returncode:
        if argv == ["crontab", "-l"] and "no crontab for" in result.stderr:
            return ""
        raise OSError(text(result.stderr.strip() or f"exit {result.returncode}"))
    return result.stdout


def properties(output):
    result = []
    for block in output.strip().split("\n\n"):
        values = {}
        for line in block.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                values[key] = values[key] + "; " + value if key in values else value
        if values:
            result.append(values)
    return result


def timestamp(value):
    if not value or value in ("0", "n/a", "[n/a]", "infinity"):
        return UNKNOWN
    return value


def compact_time(value):
    match = re.search(r"\d{4}-(\d\d-\d\d) (\d\d:\d\d)", value)
    return " ".join(match.groups()) if match else value


def compact_schedule(value):
    match = re.match(r"On(\w+)=(.*?)(?:;|$)", value)
    if not match:
        return value
    kind, interval = match.groups()
    return interval.removeprefix("*-*-* ") + (" repeat" if kind != "Calendar" else "")


def result_kind(value):
    if value.startswith("OK "):
        return "ok"
    if value == "Running":
        return "running"
    return "unknown" if value in (UNKNOWN, "No record") else "failed"


def row_order(item):
    next_run = re.search(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d", item["next"])
    return (result_kind(item["result"]) != "failed",
            next_run[0] if next_run else "9999", item["name"], item["source"])


def owner_for(evidence, owners):
    matches = [(root, name) for root, name in owners.items()
               if re.search(r"(?<![\w./-])" + re.escape(root.rstrip("/")) +
                            r"(?=/|[\s;\"']|$)", evidence)]
    if not matches:
        return UNKNOWN, "No registered home path matches. Worker: Unknown."
    names = {name for _, name in matches}
    if len(names) != 1:
        return UNKNOWN, "Multiple registered owners match. Worker: Unknown."
    root, name = matches[0]
    return name, f"Registry home: {root}. Worker: Unknown."


def row(name, source, schedule, command, purpose, owners, **fields):
    owner, evidence = owner_for(command + " " + fields.get("path", ""), owners)
    return dict(name=name, source=source, schedule=schedule, command=command,
                purpose=purpose, owner=owner, evidence=evidence, next=UNKNOWN,
                last=UNKNOWN, result=UNKNOWN, **fields)


def command_name(command):
    escaped = False
    for index, char in enumerate(command):
        if char == "%" and not escaped:
            command = command[:index]
            break
        escaped = char == "\\" and not escaped
    try:
        tokens = list(shlex.shlex(command, posix=True, punctuation_chars=True))
    except ValueError:
        return "cron"
    arguments, redirect = [], False
    for token in tokens:
        if redirect:
            redirect = False
        elif token and token[0] in "<>":
            redirect = True
        elif token not in (";", "&&", "||", "|", "&"):
            arguments.append(token)
    paths = [token for token in arguments if "/" in token and "=" not in token
             and not token.startswith("/dev/")]
    scripts = [token for token in arguments if token.endswith((".py", ".sh"))]
    return Path((scripts or paths)[-1]).name.rstrip(";") if paths else (tokens[0] if tokens else "cron")


def cron_rows(output, source, owners, system=False):
    rows, comment, timezone = [], "", ""
    for number, line in enumerate(output.splitlines(), 1):
        line = line.strip()
        if not line:
            comment = ""
            continue
        if line.startswith("#"):
            comment = line.removeprefix("# Purpose:").strip() if line.startswith("# Purpose:") else ""
            continue
        if re.match(r"\w+\s*=", line):
            if line.startswith("CRON_TZ="):
                timezone = line.split("=", 1)[1]
            continue
        count = (1 if line.startswith("@") else 5) + int(system)
        parts = line.split(None, count)
        if len(parts) != count + 1:
            raise ValueError(f"Invalid cron entry at line {number}")
        schedule = " ".join(parts[:count - int(system)])
        if timezone:
            schedule += f" (CRON_TZ={timezone})"
        command = parts[-1]
        name = command_name(command)
        rows.append(row(name, source, schedule, command, comment or PURPOSES.get(name, f"Run {name}"), owners,
                        path=f"{source}:{number}", user=parts[-2] if system else "Current login"))
        comment = ""
    return rows


def timer_row(timer, service, source, owners):
    command = service.get("ExecStart", "")
    triggers = re.findall(r"\{\s*(On\w+=.*?)\s*;\s*next_elapse=",
                          timer.get("TimersCalendar", "") + "; " + timer.get("TimersMonotonic", ""))
    policy = [f"{key}={timer[key]}" for key in
              ("AccuracyUSec", "RandomizedDelayUSec", "Persistent") if timer.get(key)]
    schedule = "; ".join(triggers + policy) or UNKNOWN
    item = row(timer["Id"].removesuffix(".timer"), source, schedule, command,
               service.get("Description") or timer.get("Description") or UNKNOWN, owners,
               path=timer.get("FragmentPath", "") + " " + service.get("FragmentPath", "") +
               " " + service.get("WorkingDirectory", ""),
               timer=timer, service=service, unit=service.get("Id", timer.get("Unit", "")))
    item["last"] = timestamp(timer.get("LastTriggerUSec"))
    item["next"] = timestamp(timer.get("NextElapseUSecRealtime"))
    if timer.get("ActiveState") != "active":
        item["next"] = "Not armed"
    elif item["next"] == UNKNOWN:
        item["next"] = "Pending"
    state = service.get("ActiveState")
    started = timestamp(service.get("ExecMainStartTimestamp")) != UNKNOWN
    if state in ("activating", "deactivating") or (state == "active" and service.get("SubState") != "exited"):
        item["result"] = "Running"
    elif started and service.get("ExecMainCode", "0") != "0":
        result, status = service.get("Result", UNKNOWN), service.get("ExecMainStatus", UNKNOWN)
        item["result"] = f"OK {status}" if result == "success" else f"{result} ({status})"
    elif state == "failed" and service.get("Result") not in ("", None, "success"):
        item["result"] = service["Result"]
    else:
        item["result"] = "No record"
    return item


def timer_rows(source, owners):
    argv = ["systemctl"] + (["--user"] if source == "user timer" else [])
    listing = json.loads(run([*argv, "list-timers", "--all", "--no-pager", "--output=json"]))
    units = sorted({entry["unit"] for entry in listing})
    if not units:
        return []
    timers = properties(run([*argv, "show", "--no-pager", f"--property={PROPERTIES}", "--", *units]))
    services = sorted({p["Unit"] for p in timers if p.get("Unit")})
    history = properties(run([*argv, "show", "--no-pager", f"--property={PROPERTIES}", "--", *services])) if services else []
    by_id = {p["Id"]: p for p in history}
    rows = [timer_row(p, by_id.get(p.get("Unit"), {}), source, owners) for p in timers]
    next_runs = {entry["unit"]: entry.get("next") for entry in listing}
    for item in rows:
        due = next_runs.get(item["timer"]["Id"])
        if item["timer"].get("ActiveState") == "active" and isinstance(due, int) and 0 < due < 2**64 - 1:
            item["next"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(due / 1_000_000))
    return rows


def read_registry(registry):
    owners = {}
    for line in registry.read_text().splitlines():
        match = re.search(r"\(home:\s*([^;]+);", line)
        if match:
            root = match[1].strip()
            identity = re.match(r"- ([A-Za-z0-9._-]+) - ", line)
            if not identity or not Path(root).is_absolute() or root in owners:
                raise ValueError("Invalid second-mate registry entry")
            owners[root] = identity[1]
    return owners


def check_row(script, owners):
    state_stat = script.parent.lstat()
    if not stat.S_ISDIR(state_stat.st_mode):
        raise ValueError("Check state is not a plain directory")
    trust = script.with_name(script.name.removesuffix(".check.sh") + ".check-trust")
    for path, mode in ((script, 0o700), (trust, 0o600)):
        file_stat = path.lstat()
        if (not stat.S_ISREG(file_stat.st_mode) or stat.S_IMODE(file_stat.st_mode) != mode
                or file_stat.st_nlink != 1 or file_stat.st_dev != state_stat.st_dev):
            raise ValueError(f"Untrusted check: {script.name}")
    content = script.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if trust.read_text().splitlines() != ["fm-custom-check-v1", digest]:
        raise ValueError(f"Untrusted check: {script.name}")
    description = next((line.lstrip("# ") for line in content.decode(errors="replace").splitlines()
                        if line.startswith("#") and not line.startswith("#!")), "Registered check")
    return row(script.name, f"home check: {script}", "Watcher sweep (default 5m)",
               str(script), PURPOSES.get(script.name, description), owners, path=str(script),
               registration=f"fm-custom-check-v1; SHA256={digest}; script 0700; trust 0600")


class Inventory:
    def __init__(self, home, registry=None):
        self.home, self.saved, self.errors, self.owners = home, {}, {}, {}
        self.registry = registry or (home / "data/secondmates.md" if home else None)

    def collect(self, source, reader):
        try:
            self.saved[source] = reader()
            self.errors.pop(source, None)
        except (OSError, ValueError, subprocess.TimeoutExpired) as error:
            self.errors[source] = text(error)

    def forget_removed(self, prefix, present):
        for source in (self.saved.keys() | self.errors.keys()) - set(present):
            if source.startswith(prefix):
                self.saved.pop(source, None)
                self.errors.pop(source, None)

    def refresh_checks(self):
        try:
            state = self.home / "state"
            if not stat.S_ISDIR(state.lstat().st_mode):
                raise ValueError("Check state is not a plain directory")
            scripts = sorted(p.with_name(p.name.removesuffix(".check-trust") + ".check.sh")
                             for p in state.iterdir() if p.name.endswith(".check-trust"))
            self.errors.pop("Home checks", None)
        except (OSError, ValueError) as error:
            self.errors["Home checks"] = text(error)
            return
        self.forget_removed("home check: ", [f"home check: {p}" for p in scripts])
        for script in scripts:
            self.collect(f"home check: {script}", lambda p=script: [check_row(p, self.owners)])

    def refresh(self):
        if self.registry:
            try:
                self.owners = read_registry(self.registry)
                self.errors.pop("Owner registry", None)
            except (OSError, ValueError) as error:
                self.errors["Owner registry"] = text(error)
        else:
            self.errors["Owner registry"] = "No registry configured; owners are Unknown."
        self.collect("user cron", lambda: cron_rows(run(["crontab", "-l"]), "user cron", self.owners))
        self.collect("/etc/crontab", lambda: cron_rows(Path("/etc/crontab").read_text(), "/etc/crontab", self.owners, True))
        try:
            files = [p for p in Path("/etc/cron.d").iterdir() if re.fullmatch(r"[\w-]+", p.name) and p.is_file()]
            self.forget_removed("/etc/cron.d/", map(str, files))
            self.errors.pop("/etc/cron.d", None)
            for path in sorted(files):
                self.collect(str(path), lambda p=path: cron_rows(p.read_text(), str(p), self.owners, True))
        except OSError as error:
            self.errors["/etc/cron.d"] = text(error)
        for source in ("user timer", "system timer"):
            self.collect(source, lambda s=source: timer_rows(s, self.owners))
        if self.home:
            self.refresh_checks()
        else:
            self.errors["Home checks"] = "No Firstmate home configured; checks are not listed."
        rows = [dict(item, stale=source in self.errors or
                     (source.startswith("/etc/cron.d/") and "/etc/cron.d" in self.errors) or
                     (source.startswith("home check: ") and "Home checks" in self.errors) or
                     ("Owner registry" in self.errors and item["owner"] != UNKNOWN))
                for source, items in self.saved.items() for item in items]
        rows.extend(row("Read error", source, UNKNOWN, "", message, {}, path=source, stale=False)
                    | {"result": "Read error"} for source, message in self.errors.items())
        return sorted(rows, key=row_order)


def details(item):
    service = item.get("service", {})
    command = re.findall(r"argv\[\]=(.*?) ; ignore_errors=", item["command"])
    lines = [item["name"] + (" | STALE" if item["stale"] else ""),
             f"Purpose: {item['purpose']}", f"Owner: {item['owner']} | {item['evidence']}",
             f"Schedule: {item['schedule']}",
             f"Next: {item['next']} | Last trigger: {item['last']}",
             f"Result: {item['result']}"]
    if service:
        lines.append(f"Service: {service.get('ActiveState', UNKNOWN)}/{service.get('SubState', UNKNOWN)}"
                     f" | Exit status: {service.get('ExecMainStatus', UNKNOWN)}")
        lines.append(f"Started: {timestamp(service.get('ExecMainStartTimestamp'))}"
                     f" | Exited: {timestamp(service.get('ExecMainExitTimestamp'))}")
    lines.extend([f"Command: {'; '.join(command) if command else item['command']}",
                  f"Source: {item['source'] if service else item['path']}"])
    return lines


def raw_details(item):
    lines = [f"{kind}.{key}: {value or UNKNOWN}"
             for kind in ("service", "timer") for key, value in item.get(kind, {}).items()]
    if item.get("registration"):
        lines.append(f"Registration: {item['registration']}")
    return lines or ["No systemd properties for this source."]


def put(screen, y, value, attr=0, x=0):
    height, width = screen.getmaxyx()
    if 0 <= y < height and width - x > 1:
        try:
            screen.addnstr(y, x, text(value), width - x - 1, attr)
        except curses.error:
            pass  # A resize or a wide glyph can reach the last terminal cell.


def cycle(current, values):
    return values[(values.index(current) + 1) % len(values)] if current in values else values[0]


def visible_rows(rows, source, owner, search):
    return [r for r in rows if (source == "All" or r["source"] == source)
            and (owner == "All" or r["owner"] == owner)
            and search.casefold() in " ".join(str(v) for v in r.values()).casefold()]


def draw_header(screen, caption, search_line, errors):
    height, _ = screen.getmaxyx()
    accent = curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
    failure = curses.color_pair(2) if curses.has_colors() else curses.A_BOLD
    screen.erase()
    put(screen, 0, caption, accent | curses.A_BOLD)
    put(screen, 1, search_line)
    messages = [f"READ ERROR {name}: {message}" for name, message in errors.items()]
    for y, message in enumerate(messages[:max(1, height // 5)], 2):
        put(screen, y, message, failure)
    return 2 + min(len(messages), max(1, height // 5))


def cell_value(item, key):
    value = item[key]
    if key in ("next", "last"):
        value = compact_time(value)
    elif key == "schedule":
        value = compact_schedule(value)
    if key in ("next", "last", "result") and value in (UNKNOWN, "No record"):
        value = "-"
    return "STALE " + value if key == "result" and item["stale"] else value


def cell_style(item, key):
    if key == "result":
        kind = result_kind(item[key])
        if kind == "unknown":
            return curses.A_DIM
        return curses.color_pair({"ok": 1, "failed": 2, "running": 3}[kind]) if curses.has_colors() else curses.A_BOLD
    return curses.A_DIM if key in ("next", "last") and item[key] == UNKNOWN else 0


def draw_row(screen, y, item, layout, selected):
    base, x = (curses.A_REVERSE if selected else 0), 0
    _, width = screen.getmaxyx()
    put(screen, y, " " * (width - 1), base)
    for index, (key, size) in enumerate(layout):
        value = text(cell_value(item, key))[:size].ljust(size)
        put(screen, y, value, base | cell_style(item, key), x)
        x += size
        if index < len(layout) - 1:
            put(screen, y, " │ ", base | curses.A_DIM, x)
            x += 3


def draw_table(screen, visible, selected, header, expanded):
    height, width = screen.getmaxyx()
    if width >= 120:
        layout = [("name", 22), ("schedule", 16), ("next", 11), ("last", 11), ("result", 13), ("owner", 18), ("purpose", width - 110)]
    elif width >= 75:
        layout = [("name", 23), ("result", 14), ("owner", 17), ("purpose", width - 64)]
    else:
        layout = [("name", max(8, width - 22)), ("result", 18)]
    put(screen, header, " │ ".join(key.title().ljust(size) for key, size in layout), curses.A_BOLD)
    count = min(max(1, len(visible)), max(1, (height - header - 4) // (2 if expanded else 1)))
    start = max(0, selected - count + 1)
    for y, item in enumerate(visible[start:start + count], header + 1):
        draw_row(screen, y, item, layout, y - header - 1 + start == selected)
    return header + count + 2


def draw_details(screen, lines, top, offset):
    height, width = screen.getmaxyx()
    accent = curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
    wrapped = [part for line in lines
               for part in textwrap.wrap(text(line), max(1, width - 2)) or [""]]
    offset = min(offset, max(0, len(wrapped) - max(1, height - top - 2)))
    for y, line in enumerate(wrapped[offset:offset + max(0, height - top - 2)], top):
        put(screen, y, line, accent if y == top else 0)
    return offset


def edit_search(search, key):
    if key in ("\n", "\r", "\x1b"):
        return search, False
    if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
        return search[:-1], True
    return search + key if isinstance(key, str) and key.isprintable() else search, True


def read_journal(item):
    try:
        return ["Journal (last 40 lines):", *run(["journalctl", *(["--user"] if item["source"] == "user timer" else []), "--no-pager", "-n", "40", "-o", "short-iso", "--unit=" + item["unit"]]).splitlines()]
    except (OSError, subprocess.TimeoutExpired) as error:
        return [f"Journal read error: {error}"]


class View:
    def __init__(self, screen, inventory):
        self.screen, self.inventory = screen, inventory
        self.rows = inventory.refresh()
        self.selected, self.expanded, self.offset = 0, True, 0
        self.search, self.source, self.owner = "", "All", "All"
        self.editing, self.journal = False, []
        self.raw_properties = False

    def draw(self, visible):
        height, width = self.screen.getmaxyx()
        self.selected = min(self.selected, max(0, len(visible) - 1))
        header = draw_header(
            self.screen, f"crewship schedules   READ ONLY | UTC | {len(visible)}/{len(self.rows)} records",
            f"{'Search: ' if self.editing else '/ '}{self.search or 'Search name or purpose'} | Source: {self.source} | Owner: {self.owner}",
            self.inventory.errors)
        top = draw_table(self.screen, visible, self.selected, header, self.expanded)
        if self.expanded and visible:
            item = visible[self.selected]
            lines = [item["name"], *self.journal] if self.journal else details(item)
            if self.raw_properties:
                lines.extend(["Properties:", *raw_details(item)])
            self.offset = draw_details(self.screen, lines, top, self.offset)
        put(self.screen, height - 2, "Local login + system only; no other accounts, containers, remote hosts, or cron child scripts.", curses.A_DIM)
        help_line = "q quit  j/k select  Enter details  / search  s source  o owner  r refresh  p properties  J journal  PgUp/Dn scroll"
        accent = curses.color_pair(1) if curses.has_colors() else curses.A_BOLD
        put(self.screen, height - 1, help_line if width >= 115 else "q quit | j/k Enter / s o r p J PgUp/Dn", accent)
        self.screen.refresh()

    def filter_key(self, key):
        if key == "s":
            self.source = cycle(self.source, ["All", *sorted({r["source"] for r in self.rows})])
        elif key == "o":
            self.owner = cycle(self.owner, ["All", *sorted({r["owner"] for r in self.rows})])
        else:
            self.search, self.source, self.owner = "", "All", "All"
        self.selected, self.offset, self.journal = 0, 0, []
        self.raw_properties = False

    def handle_key(self, key, visible):
        if self.editing:
            self.search, self.editing = edit_search(self.search, key)
            self.selected, self.offset, self.journal = 0, 0, []
        elif key in ("j", "k", curses.KEY_DOWN, curses.KEY_UP):
            step = 1 if key in ("j", curses.KEY_DOWN) else -1
            self.selected = max(0, min(self.selected + step, len(visible) - 1))
            self.offset, self.journal = 0, []
        elif key in ("\n", "\r", curses.KEY_ENTER):
            self.expanded = not self.expanded
        elif key == "/":
            self.editing = True
        elif key in ("\x1b", "s", "o"):
            self.filter_key(key)
        elif key == "r":
            self.rows = self.inventory.refresh()
            self.journal = []
        elif key == "p":
            self.raw_properties = not self.raw_properties
            self.offset, self.journal = 0, []
            self.expanded = True
        elif key in (curses.KEY_NPAGE, curses.KEY_PPAGE):
            self.offset = max(0, self.offset + (5 if key == curses.KEY_NPAGE else -5))
        elif key == "J" and visible:
            item = visible[self.selected]
            if item.get("unit"):
                self.journal = read_journal(item)
                self.expanded, self.offset, self.raw_properties = True, 0, False

    def run(self):
        while True:
            visible = visible_rows(self.rows, self.source, self.owner, self.search)
            self.draw(visible)
            key = self.screen.get_wch()
            if key == "q" and not self.editing:
                return
            self.handle_key(key, visible)


def view(screen, inventory):
    curses.curs_set(0)
    screen.keypad(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_RED, -1)
        curses.init_pair(3, curses.COLOR_YELLOW, -1)
    View(screen, inventory).run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, help="Firstmate home with data/secondmates.md")
    parser.add_argument("--registry", type=Path, help="second-mate registry file for owner matching")
    args = parser.parse_args()
    home = args.home or (Path(os.environ["FM_HOME"]) if os.environ.get("FM_HOME") else None)
    if home is None:
        config = Path.home() / ".config/crewship/schedules.json"
        if config.exists():
            configured = json.loads(config.read_text()).get("home")
            home = Path(configured) if configured else None
    if not os.isatty(0) or not os.isatty(1):
        parser.error("Open schedules in a terminal.")
    curses.wrapper(view, Inventory(home, args.registry))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, curses.error) as error:
        raise SystemExit(f"crewship schedules: {text(error)}") from error
