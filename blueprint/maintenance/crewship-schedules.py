#!/usr/bin/env python3
"""Collect read-only schedule metadata for the OpenTUI viewer."""

import argparse
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
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
    return name, f"Registry and home identity: {root}. Worker: Unknown."


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
    owners, errors = {}, {}
    for line in registry.read_text().splitlines():
        match = re.search(r"\(home:\s*([^;]+);", line)
        if match:
            root = match[1].strip()
            identity = re.match(r"- ([A-Za-z0-9._-]+) - ", line)
            if not identity or not Path(root).is_absolute() or root in owners:
                raise ValueError("Invalid second-mate registry entry")
            try:
                if (Path(root) / ".fm-secondmate-home").read_text().strip() != identity[1]:
                    raise ValueError("Home identity does not match the registry")
                owners[root] = identity[1]
            except (OSError, ValueError) as error:
                errors[f"Owner metadata: {root}"] = text(error)
    return owners, errors


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
                self.owners, metadata_errors = read_registry(self.registry)
                self.errors = {key: value for key, value in self.errors.items()
                               if not key.startswith("Owner metadata: ")}
                self.errors.update(metadata_errors)
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


def cell_value(item, key):
    value = item[key]
    if key in ("next", "last"):
        value = compact_time(value)
    elif key == "schedule":
        value = compact_schedule(value)
    if key in ("next", "last", "result") and value in (UNKNOWN, "No record"):
        value = "-"
    return "STALE " + value if key == "result" and item["stale"] else value


def collect_snapshot(home, registry, previous):
    inventory = Inventory(home, registry)
    inventory.saved = previous.get("saved", {})
    inventory.owners = previous.get("owners", {})
    inventory.errors = previous.get("errors", {})
    rows = inventory.refresh()
    for item in rows:
        item["display"] = {key: text(cell_value(item, key)) for key in
                           ("name", "schedule", "next", "last", "result", "owner", "purpose")}
        item["summary"] = list(map(text, details(item)))
        item["properties"] = list(map(text, raw_details(item)))
        item["kind"] = result_kind(item["result"])
    return dict(rows=rows, saved=inventory.saved, owners=inventory.owners, errors=inventory.errors)


def read_journal(unit, user):
    return list(map(text, run(["journalctl", *(["--user"] if user else []),
                              "--no-pager", "-n", "40", "-o", "short-iso",
                              "--unit=" + unit]).splitlines()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, help="Firstmate home with data/secondmates.md")
    parser.add_argument("--registry", type=Path, help="second-mate registry file for owner matching")
    parser.add_argument("--journal", help="read the last 40 journal lines for this unit")
    parser.add_argument("--user", action="store_true", help="read the user manager's journal")
    args = parser.parse_args()
    home = args.home or (Path(os.environ["FM_HOME"]) if os.environ.get("FM_HOME") else None)
    if home is None:
        config = Path.home() / ".config/crewship/schedules.json"
        if config.exists():
            configured = json.loads(config.read_text()).get("home")
            home = Path(configured) if configured else None
    if args.journal:
        result = {"journal": read_journal(args.journal, args.user)}
    else:
        previous = json.loads(sys.stdin.read(8 * 1024 * 1024) or "{}")
        if not isinstance(previous, dict):
            raise ValueError("The prior inventory must be an object")
        result = collect_snapshot(home, args.registry, previous)
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"crewship schedules: {text(error)}") from error
