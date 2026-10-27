import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/runs-tui/runs-tui.ts"
SCHEMA = """
create table repos (id text primary key, working_path text, upstream_url text);
create table runs (id text primary key, repo_id text, branch text, status text, pr_url text,
                   awaiting_agent_since integer, created_at integer, updated_at integer, worktree_dir text);
create table step_results (id text primary key, run_id text, step_name text, step_order integer,
                           status text, ci_fix_attempts integer default 0);
create table step_rounds (id text primary key, step_result_id text, trigger_type text);
"""
STEPS = ["intent", "rebase", "review", "test", "document", "lint", "push", "pr", "ci"]
NOW = int(time.time())
HOUR = 3600


def add_run(
    db,
    run,
    repo,
    branch,
    status,
    age,
    duration,
    states,
    fixes=(),
    pr=None,
    awaiting=None,
    worktree=None,
):
    db.execute(
        "insert into runs values (?,?,?,?,?,?,?,?,?)",
        (run, repo, branch, status, pr, awaiting, NOW - age, NOW - age + duration, worktree),
    )
    for order, name in enumerate(STEPS, 1):
        sid = f"{run}-{name}"
        db.execute(
            "insert into step_results values (?,?,?,?,?,0)",
            (sid, run, name, order, states.get(name, "pending")),
        )
        db.execute("insert into step_rounds values (?,?,'initial')", (sid + "-0", sid))
        for i in range(dict(fixes).get(name, 0)):
            db.execute("insert into step_rounds values (?,?,'auto_fix')", (f"{sid}-{i + 1}", sid))


@pytest.fixture
def host(tmp_path):
    if not shutil.which("bun"):
        pytest.skip("needs Bun")
    main = tmp_path / "Dev/firstmate"
    mate_home = tmp_path / "firstmate-ab12/3/firstmate"
    for home in (main, mate_home):
        (home / "state").mkdir(parents=True)
    project = f"{mate_home}/projects/widgets"
    (main / "state/widgets-mate-w1.meta").write_text(
        f"endpoint_task_id=widgets-mate-w1\nkind=secondmate\nhome={mate_home}\n"
    )
    (mate_home / "state/fix-widgets.meta").write_text(
        f"endpoint_task_id=fix-widgets\nproject={project}\nbranch=fm/fix-widgets\n"
    )
    (main / "state/oss-task.meta").write_text(
        "endpoint_task_id=oss-task\nproject=/elsewhere/gadgets\nbranch=fm/oss-task\n"
    )
    db_path = tmp_path / "state.sqlite"
    db = sqlite3.connect(db_path)
    db.executescript(SCHEMA)
    db.execute(
        "insert into repos values ('r1', ?, 'https://github.com/acme/widgets.git')", (project,)
    )
    db.execute(
        "insert into repos values ('r2', '/elsewhere/gadgets', 'https://github.com/acme/gadgets')"
    )
    db.execute(
        "insert into repos values ('r3', '/nowhere/gizmos', 'https://github.com/acme/gizmos')"
    )
    done = {n: "completed" for n in STEPS}
    add_run(
        db,
        "01TESTOLDPASS",
        "r2",
        "fm/oss-task",
        "completed",
        30 * HOUR,
        600,
        done,
        pr="https://github.com/acme/gadgets/pull/7",
    )
    add_run(
        db, "01TESTOLDFAIL", "r1", "fm/ancient", "failed", 50 * HOUR, 60, {**done, "test": "failed"}
    )
    add_run(
        db,
        "01TESTFAIL",
        "r1",
        "fm/gone-task",
        "failed",
        5 * HOUR,
        HOUR + 100,
        {**done, "test": "failed", "document": "pending", "ci": "pending"},
        fixes=[("review", 2), ("test", 1)],
        worktree="/x/.treehouse_firstmate-ab12_3_firstmate_projects_widgets/run",
    )
    add_run(
        db,
        "01TESTLIVE",
        "r1",
        "fm/fix-widgets",
        "running",
        100,
        100,
        {**done, "ci": "fixing"},
        fixes=[("review", 1)],
        pr="https://github.com/acme/widgets/pull/42",
    )
    add_run(
        db,
        "01TESTPARKED",
        "r3",
        "fm/p",
        "running",
        300,
        100,
        {**done, "review": "awaiting_approval", "test": "pending"},
        awaiting=NOW - 50,
    )
    db.commit()
    db.close()
    return {
        "RUNS_TUI_DB": str(db_path),
        "RUNS_TUI_HOMES": f"{main}:{mate_home}",
        "CREWSHIP_POSTMORTEM_PATHS": "",
    }


def run_once(env, *flags):
    return subprocess.run(
        ["bun", str(TOOL), "--once", *flags],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()


def rows(env, *flags):
    """Summary line and table rows; post-mortem lines and the unmatched section are skipped."""
    out = run_once(env, *flags)
    end = out.index("") if "" in out else len(out)
    return out[0], [line.split() for line in out[2:end] if not line.lstrip().startswith("↳")]


def test_maps_runs_to_home_mate_task_repo_pr_and_counts_fix_loops(host):
    summary, table = rows(host)
    assert (
        "3 of 5 runs: live + last 24h" in summary
        and "1 running · 1 parked · 0 passed · 1 failed" in summary
    )
    assert table[0][:6] == ["ab12/3", "widgets", "fix-widgets", "widgets", "#42", "ci"]
    assert table[0][6:9] == ["fix", "review", "1"] and table[0][-1] == "running"
    # No meta: the task is the branch name and the home comes from the worktree path.
    failed = table[2]
    assert failed[:4] == ["ab12/3", "widgets", "gone-task", "widgets"]
    assert failed[4:12] == ["-", "test", "review", "2", "·", "test", "1", "1h01m"]


def test_default_view_hides_old_finished_runs_and_all_shows_them(host):
    _, table = rows(host)
    assert [r[-1] for r in table] == ["running", "parked", "failed"]
    summary, table = rows(host, "--all")
    assert "all 5 runs" in summary
    assert [r[-1] for r in table] == ["running", "parked", "failed", "failed", "passed"]
    # A meta in the main home matches the repo path, so that home and its mate "main" own the run.
    assert table[4][:3] == ["main", "main", "oss-task"]
    # Truly unmappable: no meta names the repo or branch; the task still falls back to the branch.
    assert table[1][:3] == ["unknown", "unknown", "p"]


def test_anonymize_hides_names_but_keeps_structure(host):
    _, table = rows(host, "--all", "--anonymize")
    text = " ".join(" ".join(r) for r in table)
    for private in ("widgets", "gadgets", "fix-widgets", "ab12", "#42", "oss-task"):
        assert private not in text
    assert table[0][:5] == ["home-1", "mate-1", "task-1", "repo-1", "#100"]


def test_postmortem_lines_show_under_the_run_they_name(host, tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/validation-postmortems.md").write_text(
        "# Validation post-mortems\n\n"
        "| Date (UTC) | Run or link | Failed step | Root cause | Fix | Prevention change |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        "| 2026-10-27 | 01TESTFAIL | test | flaky a&#124;b | retry | [check](x.py) |\n"
        "| 2026-10-27 | https://github.com/acme/widgets/pull/421 | ci | other PR | - | - |\n"
    )
    home = tmp_path / "h1/data"
    home.mkdir(parents=True)
    (home / "validation-postmortems.md").write_text(
        "2026-10-27 | PR: https://github.com/acme/widgets/pull/42 | clippy failed.\n"
        "2026-10-26 | PR: #7 | body check failed.\n"
        "2026-10-25: paragraph entry\n"
        "continues here.\n\n"
        "not an entry\n"
    )
    paths = (
        f"{tmp_path}/docs/validation-postmortems.md:{tmp_path}/h*/data/*.md:{tmp_path}/missing.md"
    )
    out = run_once({**host, "CREWSHIP_POSTMORTEM_PATHS": paths}, "--all")
    end = out.index("")
    under, task = {}, None
    for line in out[2:end]:
        if line.lstrip().startswith("↳"):
            under.setdefault(task, []).append(line.split("↳ ", 1)[1])
        else:
            task = line.split()[2]
    assert under == {
        "fix-widgets": [
            "2026-10-27 | PR: https://github.com/acme/widgets/pull/42 | clippy failed."
        ],
        "gone-task": ["2026-10-27 | 01TESTFAIL | test | flaky a|b | retry | [check](x.py)"],
        "oss-task": ["2026-10-26 | PR: #7 | body check failed."],
    }
    # pull/421 is not PR #42; a paragraph's next line joins its entry; undated lines are ignored.
    # Subset: the repo's own docs/validation-postmortems.md is always read too.
    assert out[end + 1].startswith("POST-MORTEMS NOT MATCHED TO A RUN")
    loose = out[end + 2 :]
    assert (
        "• 2026-10-27 | https://github.com/acme/widgets/pull/421 | ci | other PR | - | -" in loose
    )
    assert "• 2026-10-25: paragraph entry continues here." in loose
    assert not any("not an entry" in line for line in loose)
