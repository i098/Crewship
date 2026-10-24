import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/runs-tui/runs-tui.ts"
SCHEMA = """
create table repos (id text primary key, working_path text, upstream_url text);
create table runs (id text primary key, repo_id text, branch text, status text, pr_url text,
                   awaiting_agent_since integer, created_at integer, updated_at integer);
create table step_results (id text primary key, run_id text, step_name text, step_order integer,
                           status text, ci_fix_attempts integer default 0);
create table step_rounds (id text primary key, step_result_id text, trigger_type text);
"""
STEPS = ["intent", "rebase", "review", "test", "document", "lint", "push", "pr", "ci"]


def add_run(db, run, repo, branch, status, created, updated, states, fixes=(), pr=None, awaiting=None):
    db.execute("insert into runs values (?,?,?,?,?,?,?,?)", (run, repo, branch, status, pr, awaiting, created, updated))
    for order, name in enumerate(STEPS, 1):
        sid = f"{run}-{name}"
        db.execute("insert into step_results values (?,?,?,?,?,0)", (sid, run, name, order, states.get(name, "pending")))
        db.execute("insert into step_rounds values (?,?,'initial')", (sid + "-0", sid))
        for i in range(dict(fixes).get(name, 0)):
            db.execute("insert into step_rounds values (?,?,'auto_fix')", (f"{sid}-{i + 1}", sid))


@pytest.fixture
def host(tmp_path):
    if not shutil.which("bun"):
        pytest.skip("needs Bun")
    home = tmp_path / "firstmate-ab12/3/firstmate"
    (home / "state").mkdir(parents=True)
    project = f"{home}/projects/widgets"
    (home / "state/fix-widgets.meta").write_text(f"endpoint_task_id=fix-widgets\nproject={project}\nbranch=fm/fix-widgets\n")
    db_path = tmp_path / "state.sqlite"
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    db.execute("insert into repos values ('r1', ?, 'https://github.com/acme/widgets.git')", (project,))
    db.execute("insert into repos values ('r2', '/elsewhere/gadgets', 'https://github.com/acme/gadgets')")
    done = {n: "completed" for n in STEPS}
    add_run(db, "old-pass", "r2", "fm/other", "completed", 1000, 1600, done, pr="https://github.com/acme/gadgets/pull/7")
    add_run(db, "fail", "r1", "fm/gone-task", "failed", 2000, 2000 + 3700,
            {**done, "test": "failed", "document": "pending", "ci": "pending"}, fixes=[("review", 2), ("test", 1)])
    add_run(db, "live", "r1", "fm/fix-widgets", "running", 4000, 4100, {**done, "ci": "fixing"},
            fixes=[("review", 1)], pr="https://github.com/acme/widgets/pull/42")
    add_run(db, "parked", "r2", "fm/p", "running", 3000, 3100, {**done, "review": "awaiting_approval", "test": "pending"}, awaiting=3050)
    db.commit()
    db.close()
    return {"RUNS_TUI_DB": str(db_path), "RUNS_TUI_HOMES": str(home)}


def rows(env):
    out = subprocess.run(["bun", str(TOOL), "--once"], env={**os.environ, **env},
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return out[0], [line.split() for line in out[2:]]


def test_maps_runs_to_home_task_repo_pr_and_counts_fix_loops(host):
    summary, table = rows(host)
    assert "4 runs · 1 running · 1 parked · 1 passed · 1 failed" in summary
    live = table[0]
    assert live[:5] == ["ab12/3", "fix-widgets", "widgets", "#42", "ci"] and live[5] == "fix"
    assert live[6:8] == ["review", "1"] and live[-1] == "running"
    assert table[2][:3] == ["ab12/3", "unknown", "widgets"]
    assert table[2][4:11] == ["test", "review", "2", "·", "test", "1", "1h01m"]


def test_sorts_running_first_and_shows_unmapped_runs_as_unknown(host):
    _, table = rows(host)
    assert [r[-1] for r in table] == ["running", "parked", "failed", "passed"]
    assert table[1][:2] == ["unknown", "unknown"] and table[3][:3] == ["unknown", "unknown", "gadgets"]
