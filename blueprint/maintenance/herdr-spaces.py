#!/usr/bin/env python3
"""Report per-home rollups to the Herdr Spaces sidebar (docs/herdr.md).

Run by herdr-spaces.timer every second. For every Herdr workspace it finds
the orchestrator home from its panes' directories and reports display-only
workspace tokens under the source `crewship:spaces`:

  short      short name ("webapp" for "2ndmate-webapp-mate-s4")
  decisions  "⚑ N"  fresh open decisions (parked captain-hold-* keys left out):
                    a second-level home's own, or the primary home's own workers';
                    only while a workspace is labelled firstmate
  crew       "▶ N"  live worker task records (state/*.meta, homes excluded)
  queue      "◷ N"  queued tasks ready to start (bin/fm-tasks-axi.sh ready),
                    recounted when data/backlog.md changes, else once a minute
  res        "⚙ 29%  ▤ 8%  ⛁ 2%"  CPU, RAM and disk, as shares of the machine
  alert      "⚠ watcher silent" when the home's supervision is unhealthy
  host       "⌂ ⚙ 41% ▤ 18.2/31.0G 59% ⛁ 402/937G 43%"  the whole machine,
             on the primary home (labelled firstmate, else the first listed),
             only while no workspace is labelled machine
  machine    the same line, on the workspace labelled machine

Zero counts are cleared. Disk is cached 15 minutes, and the queue count as
above, in ~/.cache/crewship/herdr-spaces.json. A source that fails keeps
its previous value, and the script always exits 0.

Herdr's mobile layout ignores sidebar rows, so the same data also goes where
it shows. A home's agent pane (one with a `who` token) gets its session topic
as its display agent, and every agent pane's state label (all but blocked)
carries a compact form of its home's counts, CPU/RAM/disk shares and alert
(home panes only) and its pull request line. The machine workspace's first
tab is renamed to the machine's shares, at most every TAB_TTL seconds, and
only while its label is Herdr's own number or the reporter's last text.
"""

import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

SOURCE = "crewship:spaces"
HERDR = os.environ.get("HERDR_BIN_PATH", "herdr")
CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "crewship"
TOKENS = ("short", "decisions", "crew", "queue", "res", "alert", "host", "machine")
DISK_TTL = 15 * 60
QUEUE_TTL = 60  # "ready" also moves with date gates, so recount at least once a minute
TAB_TTL = 30  # seconds between looks at the machine tab: its shares move every second
TICK = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")
STATES = ("idle", "working", "done", "unknown")  # "blocked" keeps Herdr's own word
GLYPH = re.compile(r"([⚑▶◷⎇✎]) ")


def short_name(label: str) -> str:
    """Same mapping as config/herdr-sidebar.ts shortName; "" means none."""
    if "-afk-daemon-" in label:
        return "☾ afk"
    if label.startswith("└"):
        return label.split(" · ")[0]
    if label.startswith("2ndmate-"):
        return re.sub(r"-mate-[^-]+$", "", label[len("2ndmate-") :])
    return label if label == "firstmate" else ""


def run(*args, cwd=None, env=None, timeout=20) -> str:
    return subprocess.run(
        [str(a) for a in args],
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def find_home(cwd: str) -> Path | None:
    """The orchestrator home: the git top-level holding state/ and data/."""
    for d in (Path(cwd), *Path(cwd).parents):
        if (d / ".git").exists() and (d / "state").is_dir() and (d / "data").is_dir():
            return d
    return None


def open_keys(home: Path, log: Path, cached: dict, folds: dict) -> int:
    """Fresh open decisions in one status log: bin/fm-classify-lib.sh's read-only
    status_open_decisions, minus parked captain holds (keys captain-hold-*).
    Cached until the log changes; folds keeps only the logs read this run."""
    stamp = [log.stat().st_mtime_ns, log.stat().st_size]
    hit = cached.get(str(log))
    if not hit or hit["stamp"] != stamp or "fresh" not in hit:
        script = '. "$1" && status_open_decisions "$2"'
        out = run("bash", "-c", script, "_", home / "bin/fm-classify-lib.sh", log, timeout=60)
        keys = [line.split("\t", 1)[0] for line in out.splitlines() if line.strip()]
        hit = {
            "stamp": stamp,
            "fresh": sum(not k.startswith("captain-hold-") for k in keys),
        }
    folds[str(log)] = hit
    return hit["fresh"]


def decisions(primary: Path, wid: str, is_primary: bool, cached: dict, folds: dict) -> int:
    """Decisions waiting on the operator, counted where they can be acted on.

    Every count comes from the primary home's status logs. A second-level home's
    Space shows the fresh escalations in its own log (state/<mate>.status, the meta
    whose herdr_workspace_id is this Space). The primary Space shows only its own
    workers' logs. Parked holds never count, and a second-level home with no live
    Space (closed or not running) is not shown anywhere.

    The flag means waiting on the operator. A second-level home decides for its
    own workers, and escalates anything it cannot decide into its log in the
    primary home, which is exactly what is counted here.
    """
    total = 0
    for meta in (primary / "state").glob("*.meta"):
        fields = dict(line.split("=", 1) for line in meta.read_text().splitlines() if "=" in line)
        mate = fields.get("kind") == "secondmate"
        if (mate and fields.get("herdr_workspace_id") != wid) or (not mate and not is_primary):
            continue
        log = meta.with_suffix(".status")
        if log.exists():
            total += open_keys(primary, log, cached, folds)
    return total


def crew(home: Path) -> int:
    metas = (m.read_text() for m in (home / "state").glob("*.meta"))
    return sum("\nkind=secondmate\n" not in f"\n{text}\n" for text in metas)


def queue(home: Path, saved: dict) -> int:
    """fm-tasks-axi's ready count. The call is most of a run's time and the timer
    fires every second, so the count is reused until the backlog changes or
    QUEUE_TTL passes."""
    backlog = home / "data/backlog.md"
    mtime = backlog.stat().st_mtime_ns if backlog.exists() else 0
    hit = saved.get(str(home))
    if hit and hit[0] == mtime and time.time() - hit[1] < QUEUE_TTL:
        return hit[2]
    env = {**os.environ, "FM_HOME": str(home)}
    out = run(home / "bin/fm-tasks-axi.sh", "ready", cwd=home, env=env)
    n = int(re.search(r"^count: (\d+)", out, re.M)[1])
    saved[str(home)] = [mtime, time.time(), n]
    return n


def watcher_silent(home: Path) -> bool:
    """bin/fm-supervision-lib.sh's verdict: work needs a watcher, none is beating."""
    lib = home / "bin/fm-supervision-lib.sh"
    if not lib.is_file():
        raise FileNotFoundError(lib)
    script = '. "$1" && fm_supervision_unhealthy "$2"'
    rc = subprocess.run(["bash", "-c", script, "_", lib, home / "state"], timeout=20).returncode
    return rc == 0


def disk_paths(home: Path, other_homes: set[Path]) -> list[Path]:
    """The home plus its projects' worktree pools, as treehouse reports them."""
    paths = [home]
    for project in sorted((home / "projects").glob("*/")):
        try:
            pool = json.loads(run("treehouse", "status", "--json", cwd=project))
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        paths += [Path(w["path"]) for w in pool if Path(w["path"]) not in other_homes]
    return paths


def disk_bytes(paths: list[Path]) -> int:
    out = subprocess.run(
        ["du", "-sxbc", "--", *map(str, paths)],
        capture_output=True,
        text=True,
        timeout=300,
    ).stdout
    return int(out.splitlines()[-1].split()[0])


def processes() -> dict[str, list[tuple[int, int, int]]]:
    """(pid, own cpu ticks, rss bytes) per HERDR_WORKSPACE_ID, for readable processes."""
    found: dict[str, list[tuple[int, int, int]]] = {}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            env = (proc / "environ").read_bytes()
            m = re.search(rb"(?:^|\0)HERDR_WORKSPACE_ID=([^\0]*)", env)
            if not m:
                continue
            stat = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            rss = int((proc / "statm").read_text().split()[1]) * PAGE
        except OSError:
            continue
        ticks = int(stat[11]) + int(stat[12])
        found.setdefault(m[1].decode(), []).append((int(proc.name), ticks, rss))
    return found


def meminfo() -> tuple[int, int]:
    """(MemTotal, MemAvailable) in bytes."""
    lines = Path("/proc/meminfo").read_text().splitlines()
    info = dict(line.split(":", 1) for line in lines)
    return int(info["MemTotal"].split()[0]) * 1024, int(info["MemAvailable"].split()[0]) * 1024


def cpu_times() -> list[int]:
    """[busy, total] jiffies of the whole machine, from /proc/stat."""
    fields = [int(f) for f in Path("/proc/stat").read_text().split("\n", 1)[0].split()[1:9]]
    return [sum(fields) - fields[3] - fields[4], sum(fields)]


def fs_size(path: Path | str) -> int:
    st = os.statvfs(path)
    return st.f_blocks * st.f_frsize


def pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:.0f}%"


def used_of(used: float, total: float, fine: bool = False) -> str:
    """ "402/937G", "1.4/1.9T", "12/20T": whole G below 1000G, then T with one
    decimal below 10T; `fine` keeps one decimal below 100G ("18.2/31.0G")."""
    size, unit = (2**30, "G") if total < 999.5 * 2**30 else (2**40, "T")
    if unit == "G":
        digits = 1 if fine and total < 99.95 * size else 0
    else:
        digits = 1 if total < 9.95 * size else 0
    return f"{used / size:.{digits}f}/{total / size:.{digits}f}{unit}"


def count(n: int, glyph: str) -> str:
    return f"{glyph}{n}" if n else ""


def tight(*parts: str | None) -> str:
    """Mobile form of sidebar parts: no indent, single spaces, no space after a glyph."""
    return " ".join(GLYPH.sub(r"\1", " ".join(p for p in parts if p).replace("\u2800", "")).split())


def shares(line: str) -> str:
    """ "⚙41% ▤59% ⛁43%" from the machine line."""
    return " ".join(g + p for g, p in re.findall(r"([⚙▤⛁]) (?:\S+ )?(\d+%)", line))


def presentation(text: str) -> str:
    """Herdr's metadata text form: trim, drop control characters, cap at 80, trim."""
    text = "".join(c for c in text.strip() if unicodedata.category(c) != "Cc")
    return text[:80].strip()


def name_machine_tab(wid: str, text: str, pin: dict) -> dict:
    """Name the machine workspace's pinned (first) tab, unless someone else named it."""
    tabs = json.loads(run(HERDR, "tab", "list", "--workspace", wid))["result"]["tabs"]
    if not tabs:
        return pin
    tab = next((t for t in tabs if t["tab_id"] == pin.get("id")), tabs[0])
    label, written = tab["label"], pin.get("text")
    if label != text and (label.isdigit() or label == written):
        run(HERDR, "tab", "rename", tab["tab_id"], text)
        written = text
    return {"id": tab["tab_id"], "text": written}


def main() -> None:
    cache_file = CACHE / "herdr-spaces.json"
    try:
        cache = json.loads(cache_file.read_text())
    except (OSError, ValueError):
        cache = {}
    last = cache.setdefault("tokens", {})
    now = time.time()

    workspaces = json.loads(run(HERDR, "workspace", "list"))["result"]["workspaces"]
    panes = json.loads(run(HERDR, "pane", "list"))["result"]["panes"]
    homes: dict[str, Path] = {}
    for pane in panes:
        home = find_home(pane.get("cwd") or "/")
        if home and pane["workspace_id"] not in homes:
            homes[pane["workspace_id"]] = home

    procs = processes()
    prev_cpu = cache.get("cpu", {})
    dt = now - cache.get("cpu_at", now)
    disk_cache = cache.setdefault("disk", {})
    cached_folds, folds = cache.get("folds", {}), {}
    live_ids = {ws["workspace_id"] for ws in workspaces}

    def save() -> None:
        CACHE.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache))
        tmp.replace(cache_file)

    def res(wid: str, home: Path | None) -> str:
        rows = procs.get(wid, [])
        parts = []
        before = prev_cpu.get(wid)
        if before is not None and dt > 0:
            used = sum(t - before[str(p)] for p, t, _ in rows if str(p) in before)
            cores = os.cpu_count()
            parts.append(f"⚙ {pct(min(max(used / TICK / dt, 0), cores), cores)}")
        parts.append(f"▤ {pct(sum(r for _, _, r in rows), meminfo()[0])}")
        if home:
            hit = disk_cache.get(str(home))
            if not hit or now - hit["at"] >= DISK_TTL:
                others = set(homes.values()) - {home}
                try:
                    size = disk_bytes(disk_paths(home, others))
                except (OSError, subprocess.SubprocessError, ValueError, IndexError) as err:
                    print(f"{home}: disk: {err}", file=sys.stderr)
                    size = hit and hit["bytes"]
                hit = disk_cache[str(home)] = {"at": now, "bytes": size}
                save()
            if hit["bytes"] is not None:
                parts.append(f"⛁ {pct(hit['bytes'], fs_size(home))}")
        return "  ".join(parts)

    def host() -> list[str]:
        busy, total = cpu_times()
        before = cache.get("host_cpu")
        cache["host_cpu"] = [busy, total]
        parts = []
        if before and total > before[1]:
            parts.append(f"⚙ {pct(busy - before[0], total - before[1])}")
        mem_total, mem_free = meminfo()
        mem_used = mem_total - mem_free
        parts.append(f"▤ {used_of(mem_used, mem_total, fine=True)} {pct(mem_used, mem_total)}")
        st = os.statvfs("/")
        disk_total, disk_used = st.f_blocks * st.f_frsize, (st.f_blocks - st.f_bfree) * st.f_frsize
        parts.append(f"⛁ {used_of(disk_used, disk_total)} {pct(disk_used, disk_total)}")
        return ["⌂ " + " ".join(parts)]

    first = workspaces[0] if workspaces else {}
    firstmate = next(
        (ws["workspace_id"] for ws in workspaces if ws.get("label") == "firstmate"), None
    )
    primary = firstmate or first.get("workspace_id")
    primary_home = homes.get(firstmate)
    # An operator-made workspace labelled "machine" carries the machine line as its
    # own entry (pin it first); without one the line sits under the primary home.
    machine = next((ws["workspace_id"] for ws in workspaces if ws.get("label") == "machine"), None)

    for ws in workspaces:
        wid, label = ws["workspace_id"], ws.get("label", "")
        # Helper and per-task spaces get their short name only.
        helper = "-afk-daemon-" in label or label.startswith("└") or label == "machine"
        home = None if helper else homes.get(wid)
        keep = last.get(wid, {})
        values: dict[str, str | None] = dict.fromkeys(TOKENS, "")
        values["short"] = short_name(label)

        def fill(keys, compute):
            """A source that fails keeps its previous value; unknown ones stay untouched."""
            try:
                values.update(zip(keys, compute()))
            except Exception as err:  # noqa: BLE001 - display-only, never fatal
                print(f"{label}: {keys[0]}: {err}", file=sys.stderr)
                values.update({k: keep.get(k) for k in keys})

        if home:
            if primary_home:
                fill(
                    ["decisions"],
                    lambda: [
                        count(
                            decisions(primary_home, wid, wid == firstmate, cached_folds, folds),
                            "⚑ ",
                        )
                    ],
                )
            fill(["crew"], lambda: [count(crew(home), "▶ ")])
            fill(["queue"], lambda: [count(queue(home, cache.setdefault("queue", {})), "◷ ")])
            fill(["alert"], lambda: ["⚠ watcher silent" if watcher_silent(home) else ""])
        if not helper:
            fill(["res"], lambda: [res(wid, home)])
        if wid == machine:
            fill(["machine"], host)
            short, pin = shares(values["machine"] or ""), cache.get("machine_tab") or {}
            if short and now - pin.get("at", 0) >= TAB_TTL:
                try:
                    cache["machine_tab"] = {**name_machine_tab(wid, short, pin), "at": now}
                except Exception as err:  # noqa: BLE001 - display-only, never fatal
                    print(f"{label}: tab: {err}", file=sys.stderr)
        elif wid == primary and not machine:
            fill(["host"], host)

        args = [HERDR, "workspace", "report-metadata", wid, "--source", SOURCE]
        for key, value in values.items():
            if value is not None:
                args += ["--token", f"{key}={value}"] if value else ["--clear-token", key]
        try:
            run(*args)
            last[wid] = values
        except (OSError, subprocess.SubprocessError) as err:
            print(f"{label}: report: {err}", file=sys.stderr)

    # The mobile layout (docs/herdr.md "On a phone"): only agent panes show there.
    for pane in panes:
        if not pane.get("agent"):
            continue
        tokens = pane.get("tokens") or {}
        space, title = {}, ""
        if tokens.get("who"):
            # Firstmate names its task panes through the display agent; home
            # panes are left free, so the topic can go there.
            space = last.get(pane["workspace_id"], {})
            title = presentation(pane.get("terminal_title") or "")
        text = presentation(
            tight(
                *(space.get(k) for k in ("decisions", "crew", "queue")),
                shares(space.get("res") or ""),
                "⚠watcher" if space.get("alert") else "",
                *(tokens.get(k) for k in ("pr", "add", "del", "files")),
            )
        )
        stored = pane.get("state_labels")
        wanted = dict.fromkeys(STATES, text) if text else None
        if stored != wanted or (title and pane.get("display_agent") != title):
            args = ["--display-agent", title] if title else []
            if text:
                args += [a for s in STATES for a in ("--state-label", f"{s}={text}")]
            elif stored is not None:
                args.append("--clear-state-labels")
            pid = pane["pane_id"]
            try:
                run(
                    HERDR,
                    "pane",
                    "report-metadata",
                    pid,
                    "--source",
                    SOURCE,
                    "--agent",
                    pane["agent"],
                    *args,
                )
            except (OSError, subprocess.SubprocessError) as err:
                print(f"{pid}: mobile: {err}", file=sys.stderr)

    cache.update(
        tokens={k: v for k, v in last.items() if k in live_ids},
        cpu={w: {str(pid): t for pid, t, _ in procs.get(w, [])} for w in live_ids},
        cpu_at=now,
        folds=folds,
    )
    save()


if __name__ == "__main__":
    try:
        main()
    except Exception as err:  # noqa: BLE001 - a timer run must never fail loudly
        print(f"herdr-spaces: {err}", file=sys.stderr)
