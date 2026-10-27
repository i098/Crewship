import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TUI = ROOT / "tools/lavish-tui/lavish-tui.ts"
KEEP = ROOT / "tools/lavish-keep/lavish-keep"
BUN = shutil.which("bun")
needs_bun = pytest.mark.skipif(not BUN, reason="bun not installed")
A, B, C, D, E, F, G = ("a1" * 8, "b2" * 8, "c3" * 8, "d4" * 8, "e5" * 8, "f6" * 8, "a7" * 8)


def board(path, title=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<html><head><title>{title}</title></head></html>" if title else "<html></html>"
    )
    return str(path)


@pytest.fixture
def host(tmp_path):
    """A fixture host: one firstmate home, a worker pool, and a lavish state.json."""
    home = tmp_path / ".treehouse/firstmate-abc123/1/firstmate"
    pool = tmp_path / ".treehouse/shop-def456"
    (home / "state").mkdir(parents=True)
    (home / "state/live-task.meta").write_text(f"kind=ship\nworktree={pool}/1/shop\n")
    (home / "state/plan-live.meta").write_text("kind=ship\n")
    files = {
        A: (board(home / "data/plan-live/board.html", "Live plan"), "open"),
        B: (board(home / "data/plan-gone/board.html", "Gone plan &amp; notes"), "open"),
        C: (board(pool / "1/shop/.lavish/ui/review.html", "Running review"), "feedback"),
        D: (board(pool / "2/shop/.lavish/review.html", "Torn-down review"), "open"),
        E: (str(pool / "3/shop/.lavish/deleted.html"), "open"),
        F: (board(home / ".lavish/home-board.html"), "open"),
        G: (board(home / "data/plan-gone/old.html", "Old plan"), "ended"),
    }
    sessions = {
        key: {
            "key": key,
            "file": f,
            "url": f"http://lavish.test/session/{key}",
            "status": st,
            "updated_at": f"2026-10-2{i}T10:00:00.000Z",
            "chat": [],
        }
        for i, (key, (f, st)) in enumerate(files.items())
    }
    (tmp_path / "lavish").mkdir()
    (tmp_path / "lavish/state.json").write_text(json.dumps({"sessions": sessions}, indent=2) + "\n")
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "LAVISH_AXI_STATE_DIR": str(tmp_path / "lavish"),
        "LAVISH_KEEP_DIR": str(tmp_path / "keep"),
        "LAVISH_TUI_HOMES": str(home),
        # No lavish-public on PATH: the link column falls back to the plain URL.
        "PATH": f"{Path(BUN).resolve().parent}:/usr/bin:/bin" if BUN else "/usr/bin:/bin",
    }
    return tmp_path, pool, env


def tui(env, *args):
    """(header, {key: row}, key order) from --once."""
    lines = subprocess.run(
        [BUN, str(TUI), "--once", *args], env=env, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    rows = {
        next(w for w in line.split() if len(w) == 16): line for line in lines[2:] if "  " in line
    }
    return lines[0], rows, list(rows)


def keep(env, *args):
    return subprocess.run(
        [str(KEEP), *args], env=env, capture_output=True, text=True, check=True
    ).stdout


@needs_bun
def test_gone_workers_sort_first_with_owner_and_reason(host):
    head, rows, order = tui(host[2])
    assert head.endswith("6 open · 3 open with worker gone · 1 ended")
    assert order[:3] == [E, D, B]  # open with worker gone, newest first
    assert rows[E].split()[:4] == ["open", "GONE", "deleted", "shop/3"]
    assert rows[D].split()[:5] == ["open", "GONE", "torn", "down", "shop/2"]
    assert rows[B].split()[:5] == ["open", "GONE", "torn", "down", "plan-gone"]
    assert "Gone plan & notes" in rows[B] and rows[B].endswith(f"http://lavish.test/session/{B}")
    assert rows[C].split()[:3] == ["feedback", "live", "live-task"]
    assert rows[A].split()[:3] == ["open", "live", "plan-live"]
    assert rows[F].split()[:3] == ["open", "live", "abc123/1"] and "home-board" in rows[F]
    assert G not in rows


@needs_bun
def test_all_shows_ended_and_anonymize_hides_names(host):
    head, rows, order = tui(host[2], "--all", "--anonymize")
    text = "\n".join(rows.values())
    assert len(rows) == 7 and rows[order[-1]].startswith("ended")
    for private in ("plan-gone", "shop", "Torn-down", "lavish.test", B):
        assert private not in text
    assert "task-1" in text and "Board 1" in text and "https://boards.example/session/" in text


@needs_bun
def test_missing_state_is_an_empty_list(tmp_path):
    env = {**os.environ, "LAVISH_AXI_STATE_DIR": str(tmp_path), "LAVISH_TUI_HOMES": ""}
    out = subprocess.run(
        [BUN, str(TUI), "--once"], env=env, capture_output=True, text=True, check=True
    ).stdout
    assert (
        "0 open · 0 open with worker gone · 0 ended" in out
        and "No lavish boards in this view." in out
    )


def test_keep_copies_boards_and_changes_only_file(host):
    tmp, pool, env = host
    state = tmp / "lavish/state.json"
    backup = tmp / "lavish/state.json.lavish-keep.bak"
    before = json.loads(state.read_text())["sessions"]

    assert "would keep" in keep(env, "--list", str(pool / "2/shop"))
    assert json.loads(state.read_text())["sessions"] == before and not (tmp / "keep").exists()

    assert "missing" in keep(env, str(pool / "2/shop"), str(pool / "3/shop/.lavish/deleted.html"))
    after = json.loads(state.read_text())["sessions"]
    kept = tmp / "keep" / D / ".lavish/review.html"
    assert after == {**before, D: {**before[D], "file": str(kept)}}
    assert json.loads(backup.read_text())["sessions"] == before

    # The worker copy goes away; the durable copy still holds the board, and a second keep leaves the first backup.
    shutil.rmtree(pool / "2")
    assert "Torn-down review" in kept.read_text()
    keep(env, str(pool / "1/shop"))
    assert json.loads(backup.read_text())["sessions"] == before
    assert json.loads(state.read_text())["sessions"][D]["file"] == str(kept)
    if BUN:
        assert tui(env)[1][D].split()[:4] == ["open", "GONE", "kept", "shop/2"]
