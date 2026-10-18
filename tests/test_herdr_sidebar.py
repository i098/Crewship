"""Herdr sidebar feeders: blueprint/config/herdr-sidebar.ts and blueprint/maintenance/herdr-spaces.py.

The reporter runs against a fixture home and a stub `herdr` command that
records what would be reported, so the live Herdr session is never touched.
"""

import importlib.util
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
REPORTER = ROOT / "blueprint/maintenance/herdr-spaces.py"
BLANK = "\u2800"

spec = importlib.util.spec_from_file_location("herdr_spaces", REPORTER)
spaces = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spaces)

LABELS = {
    "firstmate": "firstmate",
    "2ndmate-webapp-mate-s4": "webapp",
    "2ndmate-api-mate-b8": "api",
    "firstmate-afk-daemon-1587287-6940-1790642036": "☾ afk",
    "└ fix-login · p:Qm3vX8kT2aLp9RwZcN4yHd": "└ fix-login",
    "scratch": "",
}


def ts(expr: str):
    """Evaluate an expression against the extension's exports with bun."""
    code = f"import * as m from {json.dumps(str(ROOT / 'blueprint/config/herdr-sidebar.ts'))};"
    code += f"console.log(JSON.stringify({expr}));"
    env = {k: v for k, v in os.environ.items() if k != "FM_TASK_ID"}
    out = subprocess.run(["bun", "-e", code], capture_output=True, text=True, check=True, env=env)
    return json.loads(out.stdout)


needs_bun = pytest.mark.skipif(not shutil.which("bun"), reason="needs bun")


def test_short_names():
    assert {label: spaces.short_name(label) for label in LABELS} == LABELS


@needs_bun
def test_extension_short_names_match_the_reporter():
    assert (
        ts(f"Object.fromEntries({json.dumps(list(LABELS))}.map(l => [l, m.shortName(l)]))")
        == LABELS
    )


@needs_bun
def test_pr_parts():
    full = {"pr": 1537, "issue": "1529", "add": 12847, "del": 3902, "files": 214}
    assert ts(f"m.prParts({json.dumps(full)}, 4)") == {
        "pr": BLANK * 4 + "⎇ 1537",
        "issue": "○ 1529",
        "add": "+12847",
        "del": "−3902",
        "files": "✎ 214",
    }
    # A worker with an issue but no pull request: the issue carries the indent.
    assert ts('m.prParts({issue: "88"}, 2)') == {
        "pr": "",
        "issue": BLANK * 2 + "○ 88",
        "add": "",
        "del": "",
        "files": "",
    }
    assert ts("m.shortstat(' 3 files changed, 84 insertions(+), 12 deletions(-)')") == {
        "files": 3,
        "add": 84,
        "del": 12,
    }
    assert ts("m.shortstat(' 1 file changed, 2 deletions(-)')") == {"files": 1, "add": 0, "del": 2}


@needs_bun
def test_issue_sources():
    assert ts('m.closingIssue("Adds X.\\n\\nFixes #1529 and closes #7")') == "1529"
    assert ts('m.closingIssue("See #12")') == ""
    record = [
        "- [ ] fix-login - app: fix login (repo: app) (kind: ship)",
        "Implement https://github.com/o/app/issues/1383 in full. Split #1229 first.",
    ]
    assert ts(f"m.recordIssue({json.dumps(record)})") == "1383"
    assert ts('m.recordIssue(["- [ ] x - y (issue 1523) (repo: r)"])') == "1523"
    assert ts('m.recordIssue(["no issue here", ""])') == ""


@needs_bun
def test_pr_owners_from_remotes():
    remotes = (
        "fork\tgit@github.com:alice/webapp.git (fetch)\n"
        "fork\tgit@github.com:alice/webapp.git (push)\n"
        "origin\thttps://github.com/acme/webapp.git (fetch)\n"
        "origin\thttps://github.com/acme/webapp.git (push)\n"
        "mirror\tssh://git@github.com/alice/webapp (fetch)\n"
        "other\thttps://gitlab.com/someone/webapp.git (fetch)\n"
    )
    assert ts(f"m.prOwners({json.dumps(remotes)})") == [
        "{owner}",
        "alice",
        "acme",
    ]
    assert ts('m.prOwners("")') == ["{owner}"]


def write(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".git").mkdir(parents=True)
    (home / "data").mkdir()
    write(home / "state/fix-login.meta", "kind=ship\n")
    write(home / "state/fix-docs.meta", "kind=ship\n")
    write(home / "state/old.meta", "kind=ship\n")
    # The stub fold lists each status log's own lines as its open decisions.
    # w1, labelled firstmate, is the primary Space: its worker has one fresh
    # decision and one parked hold, which never counts.
    write(
        home / "state/fix-login.status",
        "ask\tneeds-decision\tx\ncaptain-hold-deploy\tneeds-decision\ty\n",
    )
    # Second-level homes: one with a live Space (w4) and one without (w9).
    write(home / "state/api-mate-a1.meta", "kind=secondmate\nherdr_workspace_id=w4\n")
    write(home / "state/gone-mate-g1.meta", "kind=secondmate\nherdr_workspace_id=w9\n")
    write(home / "state/api-mate-a1.status", "a\tneeds-decision\tx\nb\tblocked\ty\n")
    write(
        home / "state/gone-mate-g1.status",
        "c\tneeds-decision\tx\nd\tneeds-decision\ty\ne\tblocked\tz\n",
    )
    write(home / "bin/fm-classify-lib.sh", 'status_open_decisions() { cat "$1"; }\n')
    write(home / "bin/fm-tasks-axi.sh", "#!/bin/sh\n[ \"$1\" = ready ] && echo 'count: 4'\n", 0o755)
    write(home / "bin/fm-supervision-lib.sh", "fm_supervision_unhealthy() { return 0; }\n")

    stub = tmp_path / "stub"
    write(
        stub / "omp",
        '#!/bin/sh\nprintf \'%s\\n\' \'{"reports":[],"accountsWithoutUsage":[]}\'\n',
        0o755,
    )
    log = tmp_path / "reports.jsonl"
    workspaces = tmp_path / "workspaces.json"
    workspaces.write_text(
        json.dumps(
            [
                {"workspace_id": "w1", "label": "firstmate"},
                {"workspace_id": "w2", "label": "firstmate-afk-daemon-1-2-3"},
                {"workspace_id": "w3", "label": "scratch"},
                {"workspace_id": "w4", "label": "2ndmate-api-mate-a1"},
            ]
        )
    )
    panes = [
        {"workspace_id": "w1", "cwd": str(home / "projects/app")},
        {"workspace_id": "w2", "cwd": str(home)},
        {"workspace_id": "w4", "cwd": str(home / "projects/api")},
        # Agent panes, for the mobile layout: the primary home's own omp, one
        # of its workers (Firstmate set its display agent), a pane with
        # nothing to show, one whose labels went stale and one up to date.
        {
            "workspace_id": "w1",
            "pane_id": "w1:p2",
            "agent": "omp",
            "terminal_title": "Planning the release",
            "tokens": {
                "who": "firstmate",
                "pr": "⎇ 1561",
                "add": "+84",
                "del": "−12",
                "files": "✎ 3",
            },
        },
        {
            "workspace_id": "w1",
            "pane_id": "w1:p3",
            "agent": "omp",
            "display_agent": "└ fix-login",
            "tokens": {"pr": BLANK * 4 + "⎇ 1537", "add": "+5"},
        },
        {"workspace_id": "w3", "pane_id": "w3:p1", "agent": "claude"},
        {"workspace_id": "w3", "pane_id": "w3:p2", "agent": "omp", "state_labels": {"idle": "old"}},
        # Herdr stores a display agent trimmed and capped at 80 characters.
        # These sit in the helper space, which has no counts or shares.
        {
            "workspace_id": "w2",
            "pane_id": "w2:p3",
            "agent": "omp",
            "terminal_title": f"  {'t' * 100}  ",
            "display_agent": "t" * 80,
            "tokens": {"who": "firstmate"},
        },
        {
            "workspace_id": "w2",
            "pane_id": "w2:p4",
            "agent": "omp",
            "terminal_title": f"  {'u' * 100}  ",
            "tokens": {"who": "firstmate"},
        },
        {
            "workspace_id": "w2",
            "pane_id": "w2:p5",
            "agent": "omp",
            "terminal_title": "word " * 20 + "tail",
            "display_agent": "word " * 15 + "word",
            "tokens": {"who": "firstmate"},
        },
        {
            "workspace_id": "w2",
            "pane_id": "w2:p6",
            "agent": "omp",
            "terminal_title": "fix\x1b login",
            "display_agent": "fix login",
            "tokens": {"who": "firstmate"},
        },
        {
            "workspace_id": "w2",
            "pane_id": "w2:p7",
            "agent": "omp",
            "terminal_title": " \x00\x07 ",
            "tokens": {"who": "firstmate"},
        },
        {
            "workspace_id": "w2",
            "pane_id": "w2:p8",
            "agent": "omp",
            "terminal_title": "plan\x07 it",
            "tokens": {"who": "firstmate"},
        },
        {
            "workspace_id": "w4",
            "pane_id": "w4:p2",
            "agent": "omp",
            "tokens": {"add": "+1"},
            "state_labels": dict.fromkeys(spaces.STATES, "+1"),
        },
    ]
    state = tmp_path / "panes.json"
    tabs_file = tmp_path / "tabs.json"
    machine_tabs = [
        {
            "agent_status": "unknown",
            "focused": False,
            "label": "1",
            "number": 1,
            "pane_count": 1,
            "tab_id": "w0:t1",
            "workspace_id": "w0",
        },
        {
            "agent_status": "unknown",
            "focused": True,
            "label": "2",
            "number": 2,
            "pane_count": 1,
            "tab_id": "w0:t2",
            "workspace_id": "w0",
        },
    ]
    write(
        stub / "herdr",
        f"""#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
state = {str(state)!r}
tabs_file = {str(tabs_file)!r}

def panes():
    return json.load(open(state)) if os.path.exists(state) else {json.dumps(panes)}

def tabs():
    return json.load(open(tabs_file)) if os.path.exists(tabs_file) else {machine_tabs!r}

if a[:2] == ["workspace", "list"]:
    print(json.dumps({{"result": {{"workspaces": json.load(open({str(workspaces)!r}))}}}}))
elif a[:2] == ["pane", "list"]:
    print(json.dumps({{"result": {{"panes": panes()}}}}))
elif a[:2] == ["tab", "list"]:
    print(json.dumps({{"result": {{"tabs": [t for t in tabs() if t["workspace_id"] == a[3]]}}}}))
elif a[:2] == ["workspace", "report-metadata"]:
    with open({str(log)!r}, "a") as f:
        f.write(json.dumps(a[2:]) + "\\n")
else:
    with open({str(tmp_path / "mobile.jsonl")!r}, "a") as f:
        f.write(json.dumps(a) + "\\n")
    if a[:2] == ["pane", "report-metadata"]:
        # Herdr replaces the reporter's pane record unless the report has a --clear-*
        # flag. A worker's display agent is Firstmate's own record, so it stays.
        every = panes()
        pane = next(p for p in every if p.get("pane_id") == a[2])
        flags = a[5:]
        if not any(f.startswith("--clear-") for f in flags):
            pane.pop("state_labels", None)
            if (pane.get("tokens") or {{}}).get("who"):
                pane.pop("display_agent", None)
        for flag, value in zip(flags, flags[1:]):
            if flag == "--display-agent":
                pane["display_agent"] = value
            if flag == "--state-label":
                key, _, text = value.partition("=")
                pane.setdefault("state_labels", {{}})[key] = text
        if "--clear-state-labels" in flags:
            pane.pop("state_labels", None)
        with open(state, "w") as f:
            json.dump(every, f)
    if a[:2] == ["tab", "rename"]:
        every = tabs()
        next(t for t in every if t["tab_id"] == a[2])["label"] = a[3]
        with open(tabs_file, "w") as f:
            json.dump(every, f)
""",
        0o755,
    )
    monkeypatch.setenv("PATH", f"{stub}:{os.environ['PATH']}")
    monkeypatch.setenv("HERDR_BIN_PATH", str(stub / "herdr"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    monkeypatch.setattr(spaces, "HERDR", str(stub / "herdr"))
    monkeypatch.setattr(spaces, "CACHE", tmp_path / "cache/crewship")

    def run(
        reporter=lambda: subprocess.run(["python3", str(REPORTER)], check=True, timeout=120),
    ) -> dict[str, dict[str, str | None]]:
        log.unlink(missing_ok=True)
        reporter()
        reported = {}
        for line in log.read_text().splitlines():
            args = json.loads(line)
            tokens = reported.setdefault(args[0], {})
            for flag, value in zip(args[3::2], args[4::2]):
                key, _, text = value.partition("=")
                tokens[key] = text if flag == "--token" else None
        return reported

    return home, run


def test_reporter_counts_from_a_fixture_home(fixture):
    home, run = fixture
    reported = run()
    docs = reported["w1"]
    res = docs.pop("res")
    host = docs.pop("host")
    assert docs == {
        "short": "firstmate",
        # Its own worker's fresh decision only: not the parked hold, not the
        # second-level homes' decisions.
        "decisions": "⚑ 1",
        "crew": "▶ 0/2",
        "queue": "◷ 4",
        "alert": "⚠ watcher silent",
        # No machine workspace: the machine line is its host row instead.
        "machine": None,
        "usage": "✳ ░░░?░░░░   ?%  ◎ ░░░?░░░░   ?%",
    }
    # Shares of the machine; CPU needs a baseline, so it waits for run two.
    # Herdr's own continuation indent puts it under the name: no padding.
    assert re.fullmatch(r"▤ \d+%  ⛁ \d+%", res)
    # The primary carries the whole-machine line with the agent count. Its
    # width can pass the 40 columns Herdr shows on a continuation row at width 46.
    size = r"[\d.]+/[\d.]+[GT] \d+%"
    assert re.fullmatch(rf"⌂ ▤ {size} ⛁ {size} ◉ \d+/\d+", host)
    # A helper space shows its short name only; everything else is cleared.
    assert reported["w2"] == {"short": "☾ afk"} | dict.fromkeys(spaces.TOKENS[1:])
    # A space with no home is not the primary: CPU and RAM only.
    assert reported["w3"]["res"].startswith("▤ ") and reported["w3"]["host"] is None
    # A second-level home with a live Space counts its own log there; the one
    # without a live Space is counted nowhere.
    assert reported["w4"]["decisions"] == "⚑ 2"

    # Second run: CPU has a baseline now, a zero count is cleared, and a failed
    # source keeps its previous value.
    write(home / "bin/fm-classify-lib.sh", "status_open_decisions() { return 1; }\n")
    (home / "state/fix-login.status").write_text("new\tneeds-decision\tz\n")
    write(home / "bin/fm-supervision-lib.sh", "fm_supervision_unhealthy() { return 1; }\n")
    docs = run()["w1"]
    assert docs["decisions"] == "⚑ 1"
    assert docs["alert"] is None
    assert re.fullmatch(r"⚙ \d+%  ▤ \d+%  ⛁ \d+%", docs["res"])
    assert re.fullmatch(r"⌂ ⚙ \d+% ▤ .+", docs["host"])


def test_host_line_counts_working_agent_panes(fixture, tmp_path):
    home, run = fixture
    panes = [
        {
            "workspace_id": "w1",
            "pane_id": "w1:p1",
            "cwd": str(home),
            "agent": "omp",
            "agent_status": "working",
        },
        {
            "workspace_id": "w1",
            "pane_id": "w1:p2",
            "cwd": str(home),
            "agent": "omp",
            "agent_status": "idle",
        },
        {"workspace_id": "w1", "pane_id": "w1:p3", "cwd": str(home)},
    ]
    (tmp_path / "panes.json").write_text(json.dumps(panes))
    # Agent panes only: the plain shell pane is left out of both counts.
    assert run()["w1"]["host"].endswith(" ◉ 1/2")
    assert run()["w1"]["crew"] == "▶ 1/2"


def test_reporter_forgets_status_logs_it_no_longer_reads(fixture):
    home, run = fixture
    cache_file = home.parent / "cache/crewship/herdr-spaces.json"
    run()
    assert str(home / "state/fix-login.status") in json.loads(cache_file.read_text())["folds"]
    (home / "state/fix-login.meta").unlink()
    run()
    assert set(json.loads(cache_file.read_text())["folds"]) == {
        str(home / "state/api-mate-a1.status")
    }


def test_reporter_counts_no_decisions_without_a_firstmate_space(fixture, tmp_path):
    _, run = fixture
    workspaces = tmp_path / "workspaces.json"
    listed = json.loads(workspaces.read_text())
    listed[0]["label"] = "2ndmate-docs-mate-d1"
    workspaces.write_text(json.dumps(listed))
    reported = run()
    assert {wid: tokens["decisions"] for wid, tokens in reported.items()} == dict.fromkeys(reported)
    # The first listed still carries the machine line.
    assert reported["w1"]["host"].startswith("⌂ ")


def test_a_machine_workspace_carries_the_machine_line_alone(fixture, tmp_path):
    _, run = fixture
    workspaces = tmp_path / "workspaces.json"
    listed = json.loads(workspaces.read_text())
    machine_ws = {"workspace_id": "w0", "label": "machine", "active_tab_id": "w0:t2"}
    workspaces.write_text(json.dumps([machine_ws, *listed]))
    reported = run()
    machine = reported["w0"]
    assert machine.pop("machine").startswith("⌂ ")
    assert machine.pop("usage") == "✳ ░░░?░░░░   ?%  ◎ ░░░?░░░░   ?%"
    assert machine == dict.fromkeys(k for k in spaces.TOKENS if k not in ("machine", "usage"))
    # Never both: no Space carries the host row under its resource line.
    assert all(tokens["host"] is None for tokens in reported.values())
    assert all(tokens["machine"] is None for wid, tokens in reported.items() if wid != "w0")
    # The mobile layout shows no sidebar rows; the machine's first tab carries
    # the shares instead, though the second is the focused one.
    calls = (tmp_path / "mobile.jsonl").read_text().splitlines()
    renames = [json.loads(c) for c in calls if c.startswith('["tab"')]
    assert len(renames) == 1 and renames[0][:3] == ["tab", "rename", "w0:t1"]
    assert re.fullmatch(r"▤\d+% ⛁\d+%", renames[0][3])


def test_the_machine_tab_is_pinned_throttled_and_never_takes_over_a_name(fixture, tmp_path):
    _, run = fixture
    workspaces = tmp_path / "workspaces.json"
    listed = json.loads(workspaces.read_text())
    machine_ws = {"workspace_id": "w0", "label": "machine", "active_tab_id": "w0:t2"}
    workspaces.write_text(json.dumps([machine_ws, *listed]))
    tabs_file = tmp_path / "tabs.json"
    cache_file = tmp_path / "cache/crewship/herdr-spaces.json"
    calls = tmp_path / "mobile.jsonl"

    def renames():
        lines = calls.read_text().splitlines() if calls.exists() else []
        calls.unlink(missing_ok=True)
        return [c for c in map(json.loads, lines) if c[:2] == ["tab", "rename"]]

    def labels():
        return {t["tab_id"]: t["label"] for t in json.loads(tabs_file.read_text())}

    def set_label(tab_id, label):
        tabs = json.loads(tabs_file.read_text())
        next(t for t in tabs if t["tab_id"] == tab_id)["label"] = label
        tabs_file.write_text(json.dumps(tabs))

    def elapse():
        cache = json.loads(cache_file.read_text())
        cache["machine_tab"]["at"] -= spaces.TAB_TTL
        cache_file.write_text(json.dumps(cache))

    # The first tab, though the second is the focused one; Herdr's own number
    # on it is the reporter's to replace.
    run()
    [rename] = renames()
    assert rename[:3] == ["tab", "rename", "w0:t1"]
    assert re.fullmatch(r"▤\d+% ⛁\d+%", rename[3])
    assert labels() == {"w0:t1": rename[3], "w0:t2": "2"}

    # The shares move every second; the tab waits out the throttle.
    run()
    assert renames() == []

    # Then it follows them, on the same tab whatever the tab order.
    tabs_file.write_text(json.dumps(json.loads(tabs_file.read_text())[::-1]))
    elapse()
    run()
    [rename] = renames()
    assert rename[2] == "w0:t1" and re.fullmatch(r"⚙\d+% ▤\d+% ⛁\d+%", rename[3])

    # A name an operator chose is left alone, however long it has been.
    set_label("w0:t1", "htop")
    elapse()
    run()
    assert renames() == [] and labels()["w0:t1"] == "htop"

    # Back to Herdr's own number, the tab is the reporter's again.
    set_label("w0:t1", "1")
    elapse()
    run()
    assert [r[2] for r in renames()] == ["w0:t1"]
    assert labels()["w0:t2"] == "2"


def test_mobile_layout_carries_the_same_data(fixture, tmp_path):
    _, run = fixture
    run()
    calls = [json.loads(c) for c in (tmp_path / "mobile.jsonl").read_text().splitlines()]
    reports = {c[2]: c[3:] for c in calls if c[:2] == ["pane", "report-metadata"]}

    def labels(text):
        return [a for s in spaces.STATES for a in ("--state-label", f"{s}={text}")]

    home = reports.pop("w1:p2")
    assert home[:6] == [
        "--source",
        "crewship:spaces",
        "--agent",
        "omp",
        "--display-agent",
        "Planning the release",
    ]
    # The home's shares sit between its counts and its alert; CPU waits for
    # the second run's baseline.
    sent = home[6:]
    assert sent[::2] == ["--state-label"] * len(spaces.STATES)
    states, texts = zip(*(s.split("=", 1) for s in sent[1::2]))
    assert list(states) == list(spaces.STATES) and len(set(texts)) == 1
    assert re.fullmatch(r"⚑1 ▶0/2 ◷4 ▤\d+% ⛁\d+% ⚠watcher ⎇1561 \+84 −12 ✎3", texts[0])
    # A worker keeps Firstmate's display agent and shows its size only.
    source = ["--source", "crewship:spaces", "--agent", "omp"]
    assert reports == {
        "w1:p3": source + labels("⎇1537 +5"),
        "w3:p2": source + ["--clear-state-labels"],
        "w2:p4": source + ["--display-agent", "u" * 80],
        "w2:p8": source + ["--display-agent", "plan it"],
    }


def test_mobile_reports_settle_and_follow_a_changed_pane(fixture, tmp_path, monkeypatch):
    _, report = fixture
    calls = tmp_path / "mobile.jsonl"
    state = tmp_path / "panes.json"
    # Live processes can share the fixture's workspace IDs and change its CPU labels.
    monkeypatch.setattr(spaces, "processes", lambda: {})

    def run():
        return report(spaces.main)

    def reports():
        lines = calls.read_text().splitlines() if calls.exists() else []
        calls.unlink(missing_ok=True)
        return {c[2]: c[3:] for c in map(json.loads, lines) if c[:2] == ["pane", "report-metadata"]}

    run()
    assert reports()
    # CPU joins the shares on the second run; after that nothing moves.
    run()
    assert set(reports()) == {"w1:p2"}
    run()
    assert reports() == {}

    # The pane's pull request size changes; its topic stays.
    panes = json.loads(state.read_text())
    next(p for p in panes if p.get("pane_id") == "w1:p2")["tokens"]["add"] = "+90"
    state.write_text(json.dumps(panes))
    run()
    sent = reports()
    assert list(sent) == ["w1:p2"]
    assert sent["w1:p2"][:6] == [
        "--source",
        "crewship:spaces",
        "--agent",
        "omp",
        "--display-agent",
        "Planning the release",
    ]
    texts = {s.partition("=")[2] for s in sent["w1:p2"][7::2]}
    assert len(texts) == 1
    assert re.fullmatch(r"⚑1 ▶0/2 ◷4 ⚙\d+% ▤\d+% ⛁\d+% ⚠watcher ⎇1561 \+90 −12 ✎3", texts.pop())
    run()
    assert reports() == {}


@pytest.mark.parametrize(
    "line, short",
    [
        ("⌂ ⚙ 41% ▤ 18.2/31.0G 59% ⛁ 402/937G 43%", "⚙41% ▤59% ⛁43%"),
        ("⌂ ▤ 1.4/1.9T 100% ⛁ 12/20T 60%", "▤100% ⛁60%"),
    ],
)
def test_machine_tab_shares(line, short):
    assert spaces.shares(line) == short


def test_queue_count_is_cached_until_the_backlog_changes_or_a_minute_passes(tmp_path):
    home = tmp_path / "home"
    calls = tmp_path / "calls"
    write(
        home / "bin/fm-tasks-axi.sh",
        f'#!/bin/sh\necho x >> {calls}\necho "count: $(cat {tmp_path / "ready"})"\n',
        0o755,
    )
    (tmp_path / "ready").write_text("4")
    backlog = home / "data/backlog.md"
    write(backlog, "- [ ] a\n")
    saved = {}

    def calls_made() -> int:
        return len(calls.read_text().splitlines())

    assert spaces.queue(home, saved) == 4 and calls_made() == 1
    # Hit: the ready set moved, but the backlog did not and the minute is not up.
    (tmp_path / "ready").write_text("5")
    assert spaces.queue(home, saved) == 4 and calls_made() == 1
    # The backlog changed: recount.
    os.utime(backlog, ns=(0, backlog.stat().st_mtime_ns + 10**9))
    assert spaces.queue(home, saved) == 5 and calls_made() == 2
    # A minute passed with the backlog unchanged: recount.
    (tmp_path / "ready").write_text("6")
    saved[str(home)][1] -= spaces.QUEUE_TTL + 1
    assert spaces.queue(home, saved) == 6 and calls_made() == 3


def test_space_cpu_leaves_out_a_reaped_child(fixture):
    # A worker in the docs space runs a 6-second build on one core. The reporter
    # samples the build mid-way, then the worker reaps it: the next run counts
    # only live processes' own time, never the build's lifetime again through
    # the worker's child time.
    _, run = fixture
    busy = "import time\nt = time.time()\nwhile time.time() - t < 6: pass"
    worker = subprocess.Popen(
        [
            "python3",
            "-c",
            f"import subprocess, sys, time; subprocess.run([sys.executable, '-c', {busy!r}]); print(flush=True); time.sleep(30)",
        ],
        env={**os.environ, "HERDR_WORKSPACE_ID": "w1"},
        stdout=subprocess.PIPE,
    )
    try:
        time.sleep(5)
        run()
        worker.stdout.readline()
        res = run()["w1"]["res"]
    finally:
        worker.kill()
        worker.wait()
    assert int(re.search(r"⚙ (\d+)%", res)[1]) / 100 * os.cpu_count() < 1.5


@pytest.mark.parametrize(("before", "share"), [(-(10**12), "100%"), (10**12, "0%")])
def test_space_cpu_share_stays_within_0_and_100(fixture, tmp_path, before, share):
    _, run = fixture
    worker = subprocess.Popen(["sleep", "30"], env={**os.environ, "HERDR_WORKSPACE_ID": "w1"})
    try:
        cache = tmp_path / "cache/crewship/herdr-spaces.json"
        write(
            cache,
            json.dumps({"cpu": {"w1": {str(worker.pid): before}}, "cpu_at": time.time() - 10}),
        )
        res = run()["w1"]["res"]
    finally:
        worker.kill()
        worker.wait()
    assert re.search(r"⚙ (\d+%)", res)[1] == share


@pytest.mark.parametrize(
    ("used", "total", "fine", "text"),
    [
        (7.1, 7.8, True, "7.1/7.8G"),
        (18.2, 31.0, True, "18.2/31.0G"),
        (99.9, 99.9, True, "99.9/99.9G"),
        (45.0, 93.1, False, "45/93G"),
        (402, 937, False, "402/937G"),
        (402, 937, True, "402/937G"),
        (1433.6, 1945.6, False, "1.4/1.9T"),
        (12288, 20480, True, "12/20T"),
    ],
)
def test_machine_sizes_stay_short(used, total, fine, text):
    assert spaces.used_of(used * 2**30, total * 2**30, fine) == text


@pytest.mark.parametrize("ram", [9.96, 15.6, 31.0, 99.9, 999.6, 9.96 * 1024])
@pytest.mark.parametrize("disk", [9.96, 93.1, 100.0, 999.0, 9.96 * 1024, 99 * 1024])
def test_machine_line_fits_a_continuation_spaces_row(ram, disk):
    # The 40 columns Herdr shows on a continuation row of a Spaces entry at
    # sidebar width 46, with CPU at 100% and memory and disk at 99%.
    mem = spaces.used_of(ram * 2**30, ram * 2**30, fine=True)
    root = spaces.used_of(disk * 2**30, disk * 2**30)
    assert len(f"⌂ ⚙ 100% ▤ {mem} 99% ⛁ {root} 99%") <= 40


def test_reporter_waits_out_a_failed_disk_measurement(fixture, tmp_path):
    _, run = fixture
    calls = tmp_path / "du-calls"
    write(tmp_path / "stub/du", f"#!/bin/sh\necho x >> {calls}\nexit 1\n", 0o755)
    assert " ⛁ " not in run()["w1"]["res"]
    assert " ⛁ " not in run()["w1"]["res"]
    assert len(calls.read_text().splitlines()) == 1


def worker_log(tmp_path, origin_head=True, commit=True, setup=None, live=""):
    """A worker pane with no pull request: its `report-metadata` calls in order,
    and the `--- <name>` lines that `live` marks. `live` is JS run after session
    start, with the checkout `work`, `tick()` for the 10-second size timer,
    `settled()` to wait out the reports, `mark(name)`, and `fail`, a file whose
    presence makes the stub herdr exit 1."""
    git_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    origin, work = tmp_path / "origin", tmp_path / "work"

    def git(*args, cwd=work):
        subprocess.run(["git", *args], cwd=cwd, env=git_env, check=True, capture_output=True)

    origin.mkdir()
    git("init", "-q", "-b", "main", cwd=origin)
    (origin / "base").write_text("a\nb\n")
    git("add", "base", cwd=origin)
    git("commit", "-q", "-m", "base", cwd=origin)
    git("clone", "-q", str(origin), str(work), cwd=tmp_path)
    if not origin_head:
        git("remote", "set-head", "origin", "-d")
    git("checkout", "-q", "-b", "task")
    if commit:
        (work / "f").write_text("x\n")
        git("add", "f")
        git("commit", "-q", "-m", "work")
    if setup:
        setup(work, git)
    log, fail = tmp_path / "herdr.log", tmp_path / "fail"
    log.write_text("")
    write(
        tmp_path / "stub/herdr",
        f'#!/bin/sh\necho "$@" >> {log}\n[ -e {fail} ] && exit 1\necho "{{}}"\n',
        0o755,
    )
    write(tmp_path / "stub/gh", "#!/bin/sh\necho '[]'\n", 0o755)
    ctx = "{hasUI: true, cwd: work, ui: {setTitle() {}}}"
    code = f"""
import ext from {json.dumps(str(ROOT / "blueprint/config/herdr-sidebar.ts"))};
import {{ appendFileSync, readFileSync, rmSync, writeFileSync }} from "node:fs";
const work = {json.dumps(str(work))};
const fail = {json.dumps(str(fail))};
const lines = () => readFileSync({json.dumps(str(log))}, "utf8").split("\\n").length;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const settled = async () => {{ let n; do {{ n = lines(); await sleep(800); }} while (lines() !== n); }};
const mark = (name) => appendFileSync({json.dumps(str(log))}, `--- ${{name}}\\n`);
const ticks = [];
const setInterval0 = globalThis.setInterval;
globalThis.setInterval = (f, ms) => (ms === 10000 ? (ticks.push(f), {{ unref() {{}} }}) : setInterval0(f, ms));
const tick = () => ticks.forEach((f) => f());
const on = {{}};
ext({{ on: (e, f) => (on[e] = f) }});
on.session_start({{}}, {ctx});
{live}
"""
    env = {k: v for k, v in os.environ.items() if k != "OMPCODE"}
    env.update(
        HERDR_ENV="1",
        HERDR_PANE_ID="p1",
        HERDR_WORKSPACE_ID="w1",
        FM_TASK_ID="t1",
        HERDR_BIN_PATH=str(tmp_path / "stub/herdr"),
        PATH=f"{tmp_path / 'stub'}:{os.environ['PATH']}",
    )
    subprocess.run(["bun", "-e", code], env=env, check=True, timeout=60)
    return [
        line
        for line in log.read_text().splitlines()
        if "report-metadata" in line or line.startswith("---")
    ]


def worker_report(tmp_path, **kwargs):
    """The last report of a worker's pane with no pull request."""
    return worker_log(tmp_path, **kwargs)[-1]


@needs_bun
def test_worker_shows_its_size_before_a_pull_request(tmp_path):
    report = worker_report(tmp_path)
    assert f"add={BLANK * 2}+1" in report
    assert "del=−0" in report
    assert "files=✎ 1" in report
    assert "--clear-token pr" in report


@needs_bun
def test_worker_without_origin_head_falls_back_to_origin_main(tmp_path):
    report = worker_report(tmp_path, origin_head=False)
    assert "files=✎ 1" in report


@needs_bun
def test_worker_without_any_base_ref_shows_no_size(tmp_path):
    def drop_main(work, git):
        git("update-ref", "-d", "refs/remotes/origin/main")

    report = worker_report(tmp_path, origin_head=False, setup=drop_main)
    for part in ("add", "del", "files"):
        assert f"--clear-token {part}" in report


@needs_bun
def test_worker_with_an_empty_diff_shows_no_size(tmp_path):
    report = worker_report(tmp_path, commit=False)
    for part in ("add", "del", "files"):
        assert f"--clear-token {part}" in report


@needs_bun
def test_worker_size_counts_uncommitted_staged_and_untracked_work(tmp_path):
    def edit(work, git):
        (work / "base").write_text("a\nc\nd\n")  # unstaged: +2 −1
        (work / "staged").write_text("s\n")
        git("add", "staged")  # staged: +1
        (work / "new").write_text("n1\nn2")  # untracked, no final newline: +2
        (work / ".gitignore").write_text("ignored\n")  # untracked: +1
        (work / "ignored").write_text("skip\n")
        (work / "binary").write_bytes(b"\0\n")  # untracked binary: a file, no lines
        (work / "link").symlink_to("new")  # untracked symlink: one line

    report = worker_report(tmp_path, setup=edit)
    # f (committed), base, staged, new, .gitignore, binary, link
    assert f"add={BLANK * 2}+8" in report
    assert "del=−1" in report
    assert "files=✎ 7" in report


@needs_bun
def test_worker_size_never_rewrites_the_index(tmp_path):
    before = []

    def touch(work, git):
        os.utime(
            work / "base", (1, 1)
        )  # stale stat info: a plain `git diff` would refresh the index
        before.append((work / ".git/index").read_bytes())

    worker_report(tmp_path, setup=touch)
    assert (tmp_path / "work/.git/index").read_bytes() == before[0]


@needs_bun
def test_worker_size_follows_edits_without_a_turn_end(tmp_path):
    live = """
await settled();
writeFileSync(`${work}/live`, "l1\\nl2\\n");
mark("edited");
tick();
await settled();
mark("idle");
tick();
await settled();
"""
    log = worker_log(tmp_path, live=live)
    edited, idle = log.index("--- edited"), log.index("--- idle")
    assert "files=✎ 1" in log[edited - 1]
    assert len(log[edited + 1 : idle]) == 1
    assert f"add={BLANK * 2}+3" in log[edited + 1]
    assert "files=✎ 2" in log[edited + 1]
    assert log[idle + 1 :] == []


@needs_bun
def test_worker_retries_a_size_report_that_failed(tmp_path):
    live = """
await settled();
writeFileSync(`${work}/live`, "l\\n");
writeFileSync(fail, "");
mark("failing");
tick();
await settled();
rmSync(fail);
mark("recovered");
tick();
await settled();
"""
    log = worker_log(tmp_path, live=live)
    failing, recovered = log.index("--- failing"), log.index("--- recovered")
    assert len(log[failing + 1 : recovered]) == 1
    assert len(log[recovered + 1 :]) == 1
    assert "files=✎ 2" in log[recovered + 1]


client_spec = importlib.util.spec_from_file_location(
    "sidebar_to_client", ROOT / "blueprint/maintenance/herdr-sidebar-to-client.py"
)
to_client = importlib.util.module_from_spec(client_spec)
client_spec.loader.exec_module(to_client)

HOST_CONFIG = """[ui]
sidebar_width = 46
sidebar_max_width = 56

[ui.sidebar.agents]
rows = [
  [
    { token = "$who", fg = "#cba6f7" },
  ],
]

[ui.sidebar.spaces]
rows = [
  [
    { token = "$short", bold = true },
  ],
]

[theme.custom]
sidebar_bg = "reset"
"""


@pytest.mark.parametrize(
    "local",
    [
        "",
        'onboarding = false\n\n[ui]\nsidebar_width = 30\nagent_panel_sort = "spaces"\n\n'
        '[ui.sidebar.agents]\nrows = [["state_icon"]]\n\n[theme.custom]\naccent = "#ffffff"\n\n[keys]\nprefix = "ctrl+b"\n',
    ],
)
def test_client_gets_the_host_sidebar_layout_and_keeps_its_own_settings(local):
    merged = to_client.merge(local, HOST_CONFIG)
    assert to_client.merge(merged, HOST_CONFIG) == merged
    got, host = tomllib.loads(merged), tomllib.loads(HOST_CONFIG)
    assert got["ui"]["sidebar"] == host["ui"]["sidebar"]
    assert got["ui"]["sidebar_width"] == 46
    assert got["ui"]["sidebar_max_width"] == 56
    assert got["theme"]["custom"]["sidebar_bg"] == "reset"
    if local:
        assert got["onboarding"] is False
        assert got["ui"]["agent_panel_sort"] == "spaces"
        assert got["theme"]["custom"]["accent"] == "#ffffff"
        assert got["keys"] == {"prefix": "ctrl+b"}


def test_client_script_creates_the_config_dir_and_surfaces_ssh_errors(tmp_path):
    stub = tmp_path / "bin"
    stub.mkdir()
    (tmp_path / "host.toml").write_text(HOST_CONFIG)
    ssh = stub / "ssh"
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}"}
    target = tmp_path / "fresh" / "herdr" / "config.toml"
    script = [
        "python3",
        str(ROOT / "blueprint/maintenance/herdr-sidebar-to-client.py"),
        "host",
        str(target),
    ]

    ssh.write_text(f"#!/bin/sh\ncat {tmp_path / 'host.toml'}\n")
    ssh.chmod(0o755)
    subprocess.run(script, env=env, check=True, capture_output=True)
    assert tomllib.loads(target.read_text())["ui"]["sidebar_width"] == 46

    ssh.write_text("#!/bin/sh\necho 'ssh: Could not resolve hostname host' >&2\nexit 255\n")
    failed = subprocess.run(script, env=env, capture_output=True, text=True)
    assert failed.returncode == 1
    assert failed.stderr == "ssh: Could not resolve hostname host\n"


def usage_account(provider, key, *fractions):
    return {
        "provider": provider,
        "metadata": {"accountId": key},
        "limits": [{"amount": {"usedFraction": f}, "status": "ok"} for f in fractions],
    }


def test_provider_mean_uses_each_accounts_tightest_window_not_a_window_average():
    a = usage_account("anthropic", "work", 0.1, 0.8)
    b = usage_account("anthropic", "personal", 0.2, 0.3)
    assert spaces.usage_average([a, b]) == pytest.approx(55)


def test_duplicate_aliases_do_not_add_account_capacity():
    a = usage_account("anthropic", "work", 0.8)
    alias = usage_account("anthropic", "work", 0.9)
    b = usage_account("anthropic", "personal", 0.2)
    assert spaces.usage_average([a, alias, b]) == pytest.approx(55)


def test_distinct_organization_subscriptions_stay_separate():
    a, b = usage_account("anthropic", "a", 0.8), usage_account("anthropic", "a", 0.2)
    a["metadata"]["orgId"], b["metadata"]["orgId"] = "work", "personal"
    assert spaces.usage_average([a, b]) == 50


@pytest.mark.parametrize("fraction", [None, -0.1, 1.01, True, "0.4", float("nan")])
def test_unmeasured_account_never_becomes_zero_usage(fraction):
    assert spaces.usage_average([usage_account("anthropic", "a", fraction)]) is None


def test_one_unknown_limit_withholds_the_provider_mean():
    a, b = usage_account("openai-codex", "a", 0.8), usage_account("openai-codex", "b", 0.2)
    b["limits"][0]["status"] = "unknown"
    assert spaces.usage_average([a, b]) is None


def test_workspace_counts_exclude_idle_blocked_shells_and_other_workspaces(fixture, tmp_path):
    home, run = fixture
    panes = [
        {"workspace_id": "w1", "agent": "omp", "agent_status": state, "cwd": str(home)}
        for state in ("working", "idle", "blocked", "unknown")
    ]
    panes += [
        {"workspace_id": "w1", "cwd": str(home), "agent_status": "working"},
        {"workspace_id": "w4", "agent": "omp", "agent_status": "working", "cwd": str(home)},
    ]
    for n, pane in enumerate(panes):
        pane["pane_id"] = f"p{n}"
    (tmp_path / "panes.json").write_text(json.dumps(panes))
    reported = run()
    assert reported["w1"]["crew"] == "▶ 1/4"
    assert reported["w4"]["crew"] == "▶ 1/1"
    assert reported["w1"]["host"].endswith("◉ 2/5")


def test_usage_refresh_is_bounded_and_failure_clears_old_percentages(fixture, tmp_path):
    _, run = fixture
    rows = [
        usage_account("anthropic", "default", 0.25),
        usage_account("openai-codex", "a", 0.2),
        usage_account("openai-codex", "b", 0.8),
    ]
    write(
        tmp_path / "stub/omp",
        f"#!/bin/sh\nprintf '%s\\n' '{json.dumps({'reports': rows})}'\n",
        0o755,
    )
    expected = "✳ ▰▰▱▱▱▱▱▱  25%  ◎ ▰▰▰▰▱▱▱▱  50%"
    assert run()["w1"]["usage"] == expected
    write(tmp_path / "stub/omp", "#!/bin/sh\nexit 2\n", 0o755)
    assert run()["w1"]["usage"] == expected
    path = tmp_path / "cache/crewship/herdr-spaces.json"
    cache = json.loads(path.read_text())
    cache["usage"]["at"] -= spaces.USAGE_TTL
    path.write_text(json.dumps(cache))
    assert run()["w1"]["usage"] == "✳ ░░░?░░░░   ?%  ◎ ░░░?░░░░   ?%"


def test_unreported_account_preserves_unknown_provider_usage(fixture, tmp_path):
    _, run = fixture
    report = {
        "reports": [usage_account("anthropic", "a", 0.1), usage_account("openai-codex", "b", 0)],
        "accountsWithoutUsage": [{"provider": "anthropic", "accountId": "missing"}],
    }
    write(
        tmp_path / "stub/omp",
        f"#!/bin/sh\nprintf '%s\\n' '{json.dumps(report)}'\n",
        0o755,
    )
    assert run()["w1"]["usage"] == "✳ ░░░?░░░░   ?%  ◎ ▱▱▱▱▱▱▱▱   0%"


@pytest.mark.parametrize("width", [46, 38])
@pytest.mark.parametrize("fraction", [0, 0.5, 1, None])
def test_emitted_provider_halves_fit_sidebar_content_width(fixture, tmp_path, width, fraction):
    _, run = fixture
    report = {"reports": [
        usage_account("anthropic", "a", fraction),
        usage_account("openai-codex", "b", fraction),
    ]}
    write(
        tmp_path / "stub/omp",
        f"#!/bin/sh\nprintf '%s\\n' '{json.dumps(report)}'\n",
        0o755,
    )
    row = run()["w1"]["usage"]
    halves = row[:15], row[17:]
    assert len(row) <= width - 6
    assert [len(h) for h in halves] == [15, 15]
    assert [h[0] for h in halves] == ["✳", "◎"]
    assert all(h[1] == h[10] == " " and h[-1] == "%" for h in halves)
    if fraction is None:
        assert [h[2:10] for h in halves] == ["░░░?░░░░"] * 2
        assert [h[11:] for h in halves] == ["  ?%"] * 2
    else:
        filled = round(fraction * 8)
        assert [h[2:10] for h in halves] == ["▰" * filled + "▱" * (8 - filled)] * 2
        assert [h[11:] for h in halves] == [f"{fraction * 100:3.0f}%"] * 2
