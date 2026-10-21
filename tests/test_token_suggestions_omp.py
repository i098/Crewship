import importlib
import json
import os
import subprocess
import sys
from datetime import timedelta

import pytest
from test_token_suggestions import CANARY, CUTOFF, ROOT
from test_token_suggestions import report as report


def message(key, at, role, content, **fields):
    return {"type": "message", "id": key, "parentId": None,
            "timestamp": at.isoformat(), "message": {
                "role": role, "content": content, "timestamp": int(at.timestamp() * 1000),
                **fields}}


def session(root, name, rows):
    directory = root / "project"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.jsonl"
    header = {"type": "session", "version": 3, "id": name,
              "timestamp": rows[0]["timestamp"], "cwd": CANARY}
    path.write_text("\n".join(json.dumps(row) for row in [header, *rows]) + "\n")
    return path


def omp_fixture(root, bounds):
    at = bounds[1] + timedelta(hours=1)
    for index in range(3):
        rows = [message(f"context-{index}", at, "user", [
            {"type": "text", "text": CANARY * 40}])]
        for call in range(3 if index == 0 else 0):
            rows.append(message(f"assistant-{index}-{call}", at, "assistant", [
                {"type": "toolCall", "id": f"call-{call}", "name": CANARY,
                 "arguments": {"path": CANARY}}], provider=CANARY, model=CANARY,
                usage={"input": 100, "cacheRead": 60, "cacheWrite": 40,
                       "output": 20, "totalTokens": 220,
                       "cost": {"total": 0.1}}, stopReason="toolUse"))
            rows.append(message(f"result-{index}-{call}", at, "toolResult", [
                {"type": "text", "text": CANARY * 80}], toolCallId=f"call-{call}",
                toolName=CANARY, isError=call < 2, details={"secret": CANARY}))
        session(root, f"session-{index}", rows)


def test_omp_only_cli_cycle_is_private_and_read_only(tmp_path, report):
    root = tmp_path / "sessions"
    omp_fixture(root, report.windows(CUTOFF))
    before = {p: p.read_bytes() for p in root.rglob("*.jsonl")}
    config = tmp_path / "config.json"
    home = tmp_path / "home"
    config.write_text(json.dumps({"fm_home": str(home), "omp_sessions": str(root)}))
    result = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/token_suggestions.py"),
                             "--config", str(config), "--cutoff", CUTOFF.isoformat()],
                            text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    directory = home / "data/token-savings"
    text = (directory / "latest.md").read_text()
    assert CANARY not in text + result.stdout + result.stderr
    assert str(root) not in text
    assert all(f"| {name} | available" in text for name in report.DETECTORS)
    assert "known input 600 tokens" in text
    assert "Cache-read share 30.00%" in text
    assert "Seven-day comparison unavailable" in text
    assert "partial" in text
    assert json.loads((directory / "status.json").read_text())["state"] == "complete"
    assert before == {p: p.read_bytes() for p in root.rglob("*.jsonl")}
    report.require_completed_cycle(report.settings(config))
    changed = json.loads(config.read_text())
    changed["omp_sessions"] = str(tmp_path / "other")
    with pytest.raises(ValueError, match="completed cycle"):
        report.require_completed_cycle(changed)


def test_omp_window_and_unknown_usage_stay_separate(tmp_path, report):
    bounds = report.windows(CUTOFF)
    rows = []
    for key, at, usage in [
        ("prior", bounds[1] - timedelta(seconds=1), {"input": 300, "cacheRead": 0, "cacheWrite": 0}),
        ("start", bounds[1], {"input": 100, "cacheRead": 100, "cacheWrite": 0}),
        ("unknown", bounds[1], {"input": 900}),
        ("end", bounds[2], {"input": 9999, "cacheRead": 0, "cacheWrite": 0}),
    ]:
        rows.append(message(key, at, "assistant", [], provider=CANARY, model=CANARY, usage=usage))
    session(tmp_path, "window", rows)
    collected = report.collect({"omp_sessions": str(tmp_path)}, bounds)
    text = report.markdown(bounds, collected, False)
    assert "2 completions; 1 excluded rows" in text
    assert "known input 200 tokens" in text
    assert "Cache-read share 50.00%" in text
    assert "Previous seven complete days:" not in text


@pytest.mark.parametrize("copy", ["complete", "shorter"])
def test_omp_copied_entries_do_not_duplicate_measurements(tmp_path, report, copy):
    bounds = report.windows(CUTOFF)
    omp_fixture(tmp_path, bounds)
    before = report.collect({"omp_sessions": str(tmp_path)}, bounds)[0]
    path = tmp_path / "project/session-0.jsonl"
    copied = path.parent / "copied.jsonl"
    lines = path.read_text().splitlines()
    copied.write_text("\n".join(lines if copy == "complete" else lines[:6]) + "\n")
    os.utime(copied, (path.stat().st_mtime + 60,) * 2)
    after = report.collect({"omp_sessions": str(tmp_path)}, bounds)[0]
    assert sorted((row["detector"], row["tokens"], row["signal"]) for row in before) == sorted(
        (row["detector"], row["tokens"], row["signal"]) for row in after)


def test_omp_invalid_unicode_preserves_valid_observations(tmp_path, report):
    source = importlib.import_module("token_suggestions_sources")
    bounds = report.windows(CUTOFF)
    omp_fixture(tmp_path, bounds)
    before = source.read_omp(tmp_path, bounds)
    session(tmp_path, "malformed", [
        message("invalid-unicode", bounds[1], "user", [{"type": "text", "text": "\ud800"}])])
    after = source.read_omp(tmp_path, bounds)
    assert after[2]["malformed"] == 1
    assert sorted((row["detector"], row["tokens"]) for row in before[0]) == sorted(
        (row["detector"], row["tokens"]) for row in after[0])
    assert before[1] == after[1]


def test_omp_different_calls_do_not_become_retry_loops(tmp_path, report):
    bounds = report.windows(CUTOFF)
    at = bounds[1]
    rows = []
    for index in range(3):
        rows.extend([
            message(f"a-{index}", at, "assistant", [{"type": "toolCall", "id": str(index),
                    "name": CANARY, "arguments": {"path": str(index)}}]),
            message(f"t-{index}", at, "toolResult", [{"type": "text", "text": CANARY}],
                    toolCallId=str(index), toolName=CANARY, isError=True),
        ])
    session(tmp_path, "different", rows)
    assert not any(row["detector"] == 2 for row in report.collect({"omp_sessions": str(tmp_path)}, bounds)[0])


def test_omp_parallel_calls_are_not_retries(tmp_path, report):
    bounds = report.windows(CUTOFF)
    calls = [{"type": "toolCall", "id": str(index), "name": CANARY,
              "arguments": {"path": CANARY}} for index in range(3)]
    rows = [message("parallel", bounds[1], "assistant", calls)]
    rows.extend(message(f"result-{index}", bounds[1], "toolResult",
                        [{"type": "text", "text": CANARY}], toolCallId=str(index),
                        toolName=CANARY, isError=True) for index in range(3))
    session(tmp_path, "parallel", rows)
    assert not any(row["detector"] == 2 for row in report.collect({"omp_sessions": str(tmp_path)}, bounds)[0])


@pytest.mark.parametrize("limit", ["OMP_MAX_FILES", "OMP_MAX_BYTES", "OMP_MAX_ENTRIES",
                                  "OMP_MAX_RECORDS", "OMP_MAX_FILE_BYTES", "OMP_MAX_LINE_BYTES"])
def test_omp_limits_bound_observations(tmp_path, report, monkeypatch, limit):
    source = importlib.import_module("token_suggestions_sources")
    omp_fixture(tmp_path, report.windows(CUTOFF))
    monkeypatch.setattr(source, limit, 1)
    rows, _, counts = source.read_omp(tmp_path, report.windows(CUTOFF))
    assert counts["limited"] == 1
    if limit == "OMP_MAX_FILES":
        assert counts["files"] == 1
    else:
        assert counts["messages"] == 0
        assert rows == []


def test_omp_deadline_is_bounded(tmp_path, report, monkeypatch):
    source = importlib.import_module("token_suggestions_sources")
    omp_fixture(tmp_path, report.windows(CUTOFF))
    clock = iter([0, 100])
    monkeypatch.setattr(source.time, "monotonic", lambda: next(clock, 100))
    with pytest.raises(ValueError, match="deadline"):
        source.read_omp(tmp_path, report.windows(CUTOFF))


def test_omp_symlinks_and_malformed_lines_do_not_leak(tmp_path, report):
    bounds = report.windows(CUTOFF)
    outside = tmp_path / "outside"
    omp_fixture(outside, bounds)
    root = tmp_path / "sessions"
    root.mkdir()
    (root / "linked").symlink_to(outside / "project", target_is_directory=True)
    project = root / "project"
    project.mkdir()
    (project / "link.jsonl").symlink_to(next(outside.rglob("*.jsonl")))
    (project / "bad.jsonl").write_text(CANARY + "\n")
    collected = report.collect({"omp_sessions": str(root)}, bounds)
    assert not collected[-1]
    assert CANARY not in report.markdown(bounds, collected, False)
    assert not any(row["detector"] == 1 for row in collected[0])
    os.utime(project / "bad.jsonl", (0, 0))
    assert not report.collect({"omp_sessions": str(root)}, bounds)[-1]
