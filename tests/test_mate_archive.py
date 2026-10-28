"""mate-archive: incremental indexing, ranking, zoom window and secret mask, on fixture sessions only."""

import importlib.machinery
import importlib.util
import json
import stat
from pathlib import Path

import pytest

MAINT = Path(__file__).parents[1] / "blueprint/maintenance"


@pytest.fixture
def ma(tmp_path, monkeypatch):
    monkeypatch.setenv("MATE_ARCHIVE_SESSIONS", str(tmp_path / "sessions"))
    monkeypatch.setenv("MATE_ARCHIVE_DB", str(tmp_path / "data/archive.db"))
    (tmp_path / "sessions").mkdir()
    loader = importlib.machinery.SourceFileLoader("mate_archive", str(MAINT / "mate-archive"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(mod)
    return mod


def line(obj):
    return json.dumps(obj) + "\n"


def msg(role, text, n=0):
    return line({"type": "message", "timestamp": f"2026-10-2{n}T00:00:00Z", "message": {"role": role, "content": [{"type": "text", "text": text}]}})


def write_session(ma, name, sid, texts, mode="w"):
    path = ma.SESSIONS / f"{name}.jsonl"
    with open(path, mode) as f:
        if mode == "w":
            f.write(line({"type": "session", "id": sid}))
        for i, t in enumerate(texts):
            f.write(msg("user" if i % 2 == 0 else "assistant", t))
    return path


def run(ma, capsys, *argv):
    ma.main(list(argv))
    return capsys.readouterr().out


def test_incremental_index_reads_only_new_lines_and_keeps_turn_numbers(ma, capsys):
    path = write_session(ma, "a", "sess-a", ["alpha one", "beta two"])
    assert run(ma, capsys, "index") == "indexed 2 turns\n"
    assert run(ma, capsys, "index") == "indexed 0 turns\n"
    write_session(ma, "a", "sess-a", ["gamma three"], mode="a")
    with open(path, "a") as f:
        f.write('{"type":"message","half')  # half-written line is left for the next run
    assert run(ma, capsys, "index") == "indexed 1 turns\n"
    assert "sess-a turn 3 user" in run(ma, capsys, "search", "gamma")


def test_search_ranks_denser_match_first_and_filters(ma, capsys):
    write_session(ma, "a", "sess-a", ["deploy once, then lunch", "unrelated"])
    write_session(ma, "b", "sess-b", ["deploy deploy deploy rollback"])
    out = run(ma, capsys, "search", "deploy")
    assert out.index("sess-b") < out.index("sess-a")
    assert "sess-b" not in run(ma, capsys, "search", "deploy", "--session", "sess-a")
    assert run(ma, capsys, "search", "deploy", "--since", "2026-12-01") == "no match\n"
    assert run(ma, capsys, "search", "deploy", "--limit", "1").count("turn") == 1


def test_zoom_returns_window_around_turn(ma, capsys):
    write_session(ma, "a", "sess-a", [f"line number {i}" for i in range(1, 8)])
    out = run(ma, capsys, "zoom", "sess-", "4", "--before", "2", "--after", "1")
    assert [f"turn {n}" for n in (2, 3, 4, 5)] == [f"turn {l.split(' turn ')[1].split()[0]}" for l in out.splitlines() if l.startswith("---")]
    assert "line number 4" in out and "line number 6" not in out


def test_secret_lines_are_masked_and_db_is_private(ma, capsys):
    write_session(ma, "a", "sess-a", ["keep this\nAPI_KEY=hunter2hunter2\nPASSWORD: swordfish\nused sk-abcdefghijklmnop1234 here\nplain end"])
    assert run(ma, capsys, "search", "hunter2hunter2") == "no match\n"
    assert run(ma, capsys, "search", "swordfish") == "no match\n"
    out = run(ma, capsys, "zoom", "sess-a", "1")
    assert "keep this" in out and "plain end" in out
    assert "hunter2" not in out and "sk-abc" not in out and out.count("[secret line masked]") == 3
    assert stat.S_IMODE(ma.DB.stat().st_mode) == 0o600
