import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "blueprint/maintenance/herdr-prune-empty.py"
spec = importlib.util.spec_from_file_location("herdr_prune_empty", SCRIPT)
pruner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pruner)

SHELL = 100


class FakeHerdr:
    """Panes: id -> dict(tab, fg=[pids], kids=[pids], agent, text)."""

    def __init__(self, panes, tabs):
        self.panes_by_id = panes
        self.tab_labels = tabs
        self.closed = []

    def panes(self):
        return [
            {
                "pane_id": pid,
                "tab_id": p["tab"],
                "workspace_id": "w1",
                "agent_status": "idle" if p.get("agent") else "unknown",
                "terminal_id": "t-" + pid,
            }
            for pid, p in self.panes_by_id.items()
            if pid not in self.closed
        ]

    def tabs(self):
        return [
            {"tab_id": t, "label": label, "pane_count": 1} for t, label in self.tab_labels.items()
        ]

    def workspaces(self):
        return []

    def process_info(self, pid):
        p = self.panes_by_id[pid]
        return {
            "shell_pid": SHELL,
            "foreground_processes": [{"pid": x} for x in p.get("fg", [SHELL])],
        }

    def read(self, pid):
        return self.panes_by_id[pid].get("text", "$ ")

    def close(self, kind, ident):
        self.closed.append(ident)


def ctx(recorded=(), main="", keep=("concord", "crewboard", "monitoring"), kids=()):
    return {
        "recorded": set(recorded),
        "main_pane": main,
        "keep_tabs": set(keep),
        "children": lambda pid: list(kids),
    }


def run(herdr, context, state=None, now=1000, idle=600, dry=False):
    state = {} if state is None else state
    out = []
    closed = pruner.prune(herdr, context, state, now, idle, dry, log=lambda m, **_: out.append(m))
    return closed, state, out


def fleet(**overrides):
    panes = {"w1:p1": {"tab": "t1"}}
    panes.update(overrides)
    return FakeHerdr(panes, {"t1": "work", "t2": "Concord", "t3": "work"})


def aged(herdr, context):
    """State as left by a run 11 minutes ago."""
    _, state, _ = run(herdr, context, now=0)
    return state


def test_idle_empty_shell_is_closed_only_after_it_stayed_unchanged():
    herdr = fleet(**{"w1:p2": {"tab": "t3"}})
    context = ctx()
    closed, state, _ = run(herdr, context, now=0)
    assert closed == []
    closed, _, out = run(herdr, context, state=state, now=700)
    assert closed == ["w1:p1"]  # the last pane of the session stays
    assert any("idle 700s" in line for line in out)


def test_screen_change_restarts_the_idle_clock():
    herdr = fleet(**{"w1:p2": {"tab": "t3"}})
    context = ctx()
    state = aged(herdr, context)
    herdr.panes_by_id["w1:p2"]["text"] = "$ ls\nfile\n$ "
    closed, _, _ = run(herdr, context, state=state, now=700)
    assert closed == ["w1:p1"]


@pytest.mark.parametrize(
    "pane,context",
    [
        ({"tab": "t3", "fg": [SHELL, 555]}, ctx()),
        ({"tab": "t3", "fg": [555]}, ctx()),
        ({"tab": "t3"}, ctx(kids=[777])),
        ({"tab": "t3", "agent": True}, ctx()),
        ({"tab": "t3"}, ctx(recorded=["w1:p2"])),
        ({"tab": "t3"}, ctx(main="w1:p2")),
        ({"tab": "t2"}, ctx()),
    ],
    ids=["fg-job", "fg-other", "child", "agent", "recorded", "main", "kept-tab"],
)
def test_panes_with_any_reason_to_stay_are_kept(pane, context):
    herdr = fleet(**{"w1:p2": pane})
    state = aged(herdr, context)
    closed, _, _ = run(herdr, context, state=state, now=5000)
    assert "w1:p2" not in closed


def test_unreadable_children_keep_the_pane():
    def boom(pid):
        raise PermissionError

    herdr = fleet(**{"w1:p2": {"tab": "t3"}})
    context = ctx()
    context["children"] = boom
    state = aged(herdr, context)
    assert run(herdr, context, state=state, now=5000)[0] == []


def test_dry_run_lists_and_changes_nothing():
    herdr = fleet(**{"w1:p2": {"tab": "t3"}})
    context = ctx()
    state = aged(herdr, context)
    closed, _, out = run(herdr, context, state=state, now=5000, dry=True)
    assert herdr.closed == [] and closed == ["w1:p1"]
    assert out[0].startswith("would close pane w1:p1")


def test_never_closes_the_last_pane_of_the_session():
    herdr = FakeHerdr({"w1:p1": {"tab": "t1"}}, {"t1": "work"})
    context = ctx()
    state = aged(herdr, context)
    assert run(herdr, context, state=state, now=5000)[0] == []


def write_meta(home, name, body):
    (home / "state").mkdir(parents=True, exist_ok=True)
    (home / "state" / f"{name}.meta").write_text(body)


def test_recorded_panes_cover_every_home_and_key(tmp_path):
    main, mate = tmp_path / "main", tmp_path / "mate"
    write_meta(
        main, "a", "window=default:w1:p1\nherdr_pane_id=w1:p2\nhiatus_window=w9:p9\nmodel=x\n"
    )
    write_meta(mate, "b", "herdr_pane_id=w2:p3\n")
    (main / "data").mkdir()
    (main / "data/secondmates.md").write_text(
        f"- m - role. (home: {mate}; scope: x)\n- r - remote. (host: mac; home: {tmp_path}/gone; scope: y)\n"
    )
    homes = pruner.read_homes(main, [])
    assert pruner.recorded_panes(homes) == {"w1:p1", "w1:p2", "w9:p9", "w2:p3"}


def test_listed_home_without_state_aborts(tmp_path):
    main = tmp_path / "main"
    write_meta(main, "a", "window=w1:p1\n")
    (main / "data").mkdir()
    (main / "data/secondmates.md").write_text(f"- m - role. (home: {tmp_path}/missing; scope: x)\n")
    with pytest.raises(pruner.Abort):
        pruner.recorded_panes(pruner.read_homes(main, []))


def test_session_qualified_pane_ids_match_recorded_and_main_panes():
    herdr = fleet(**{"default:w1:p2": {"tab": "t3"}, "default:w1:p3": {"tab": "t3"}})
    context = ctx(recorded=["w1:p2"], main="w1:p3")
    state = aged(herdr, context)
    closed, _, _ = run(herdr, context, state=state, now=5000)
    assert closed == ["w1:p1"]


FAKE_HERDR = """#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
R = {
    ("pane", "list"): {"panes": [
        {"pane_id": "w1:p1", "tab_id": "t1", "workspace_id": "w1", "agent_status": "unknown"},
        {"pane_id": "w1:p2", "tab_id": "t1", "workspace_id": "w1", "agent_status": "unknown"},
    ]},
    ("tab", "list"): {"tabs": [{"tab_id": "t1", "label": "work", "pane_count": 2}]},
    ("workspace", "list"): {"workspaces": []},
    ("pane", "process-info"): {"process_info": {
        "shell_pid": int(os.environ["SHELL_PID"]),
        "foreground_processes": [{"pid": int(os.environ["SHELL_PID"])}]}},
}
if a[1] == "close":
    open(os.environ["CLOSE_LOG"], "a").write(a[2] + "\\n")
    print(json.dumps({"result": {}}))
elif a[1] == "read":
    print("$ ")
else:
    print(json.dumps({"result": R[(a[0], a[1])]}))
"""


def run_main(tmp_path, monkeypatch, main_pane, argv=(), clock=(1000.0,)):
    """One main() call per clock value; returns the panes the fake herdr closed."""
    import subprocess

    fm = tmp_path / "fm"
    (fm / "state").mkdir(parents=True, exist_ok=True)
    binary = tmp_path / "herdr"
    binary.write_text(FAKE_HERDR)
    binary.chmod(0o755)
    sleeper = subprocess.Popen(["sleep", "30"])
    try:
        for k, v in {
            "FM_HOME": str(fm),
            "HERDR_BIN_PATH": str(binary),
            "PRUNE_STATE": str(tmp_path / "state.json"),
            "CLOSE_LOG": str(tmp_path / "closed"),
            "SHELL_PID": str(sleeper.pid),
            "MAIN_PANE": main_pane,
            "IDLE": "600",
        }.items():
            monkeypatch.setenv(k, v)
        for now in clock:
            monkeypatch.setattr(pruner.time, "time", lambda now=now: now)
            assert pruner.main(list(argv)) == 0
    finally:
        sleeper.kill()
        sleeper.wait()
    log = tmp_path / "closed"
    return log.read_text().split() if log.exists() else []


def test_dry_run_keeps_the_idle_clock_between_runs(tmp_path, monkeypatch, capsys):
    closed = run_main(tmp_path, monkeypatch, "w1:p1", ["--dry-run"], clock=(1000.0, 1700.0))
    assert closed == []
    assert "would close pane w1:p2" in capsys.readouterr().out


def test_unset_main_pane_closes_nothing(tmp_path, monkeypatch, capsys):
    assert run_main(tmp_path, monkeypatch, "", clock=(1000.0, 1700.0)) == []
    captured = capsys.readouterr()
    assert "MAIN_PANE is not set" in captured.err
    assert "would close pane w1:p1" in captured.out


def test_set_main_pane_closes_other_idle_pane_once_aged(tmp_path, monkeypatch):
    assert run_main(tmp_path, monkeypatch, "w1:p1", clock=(1000.0, 1700.0)) == ["w1:p2"]
