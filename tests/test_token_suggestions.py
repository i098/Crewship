import importlib
import json
import os
import signal
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = datetime(2026, 10, 20, 16, tzinfo=UTC)
CANARY = "PRIVATE-CONTENT-MUST-NOT-APPEAR"


@pytest.fixture
def report(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    return importlib.import_module("token_suggestions")


def ledger_fixture(path, bounds, *, unknown=True, duplicate=False):
    history, start, end = bounds
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE events (producer TEXT,event TEXT,kind TEXT,sequence INTEGER,"
                   "at REAL,payload TEXT,sequence_through INTEGER,retired_completions INTEGER)")

        def add(key, kind, at, sequence=None, **values):
            payload = {"schema": 1, "kind": kind, **values}
            record = (CANARY, key, kind, sequence, at.timestamp(), json.dumps(payload), 4, 0)
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", record)
            if duplicate and kind in ("start", "complete"):
                db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", record)

        add("register", "register", history, producer_kind="chat")
        add("checkpoint", "checkpoint", end, sequence=4)
        for n, at, basis, value, read in (
            (1, start - timedelta(hours=1), "inclusive", 100, 50),
            (2, start + timedelta(hours=1), "inclusive", 100, 60),
            (3, start + timedelta(hours=2), "exclusive", 30, 60),
        ):
            add(str(n), "start", at, n, provider=CANARY, model=CANARY)
            add(str(n), "complete", at, n, usage_present=True, input_basis=basis,
                input=value, cache_read=read, cache_write=10)
        add("4", "start", start + timedelta(hours=3), 4, provider=CANARY, model=CANARY)
        add("4", "complete", start + timedelta(hours=3), 4,
            usage_present=None if unknown else True,
            input_basis="unknown" if unknown else "inclusive",
            input=None if unknown else 100, cache_read=None if unknown else 60,
            cache_write=None if unknown else 10)


def snapshot_fixture(bounds):
    window = dict(zip(("from", "to"), (t.isoformat() for t in bounds[1:])))
    return {"schema": "caveman.learn.v1", "basis": "inferred", "window": window,
            "caveats": [], "unknown": CANARY,
            "sinks": [
                {"sink_id": "recurring_context:repaste:" + CANARY,
                 "title": CANARY, "suggestion": CANARY,
                 "evidence": {"recurrence_sessions": 3, "occurrences_total": 5,
                              "block_tokens": 200, "occurrence_tokens_total": 1000,
                              "locators": [CANARY]}},
                {"sink_id": "tool_output_portfolio", "title": CANARY,
                 "evidence": {"tool_output_tokens": 3000,
                              "signature_token_basis": "estimated_local",
                              "top_signatures": [{"signature": CANARY, "calls": 5,
                                                  "tokens": 3000, "largest_call": 1000,
                                                  "error_calls": 2}]}},
                {"sink_id": "learning_loop:error_loop:" + CANARY,
                 "tokens_observed": 800, "evidence": {"calls": 4,
                    "observed_output_token_floor": 800, "tokens_observed_basis": "bytes4_estimate",
                    "session_ref": CANARY}},
                {"sink_id": "subagent_pressure", "evidence": {"agent_count": 900}},
                {"sink_id": "no_commits", "evidence": {"sessions": 100}},
            ],
            "retro": {"basis": "inferred", "families": [
                {"id": "tool_outputs", "tokens": 400},
                {"id": "repeated_blocks", "tokens": 250}]},
            "confirmed": [{"before": 200, "after": 150, "unit": "config_tokens_per_turn",
                           "verdict": "improved", "sessions_after": 4,
                           "applied_at": window["from"], "sink_id": CANARY,
                           "attribution": {"method": "deterministic_remeasure",
                                           "provenance": "intact", "target_path": CANARY,
                                           "confounders": [CANARY]}}]}


def test_full_cli_cycle_is_private_read_only_and_deduplicated(tmp_path, report):
    bounds = report.windows(CUTOFF)
    ledger = tmp_path / "usage.sqlite"
    ledger_fixture(ledger, bounds, duplicate=True)
    snapshot = tmp_path / "saved.json"
    snapshot.write_text(json.dumps(snapshot_fixture(bounds)))
    config = tmp_path / "config.json"
    home = tmp_path / "home"
    config.write_text(json.dumps({"fm_home": str(home), "ledger": str(ledger),
                                 "snapshots": [str(snapshot), str(snapshot),
                                               str(tmp_path / "missing.json")]}))
    before = ledger.read_bytes(), snapshot.read_bytes()
    result = subprocess.run([sys.executable, str(ROOT / "scripts/token_suggestions.py"),
                             "--config", str(config), "--cutoff", CUTOFF.isoformat()],
                            env={**os.environ, "HOME": str(home)}, text=True,
                            capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    directory = home / "data/token-savings"
    content = (directory / "latest.md").read_text()
    assert CANARY not in content + result.stdout + result.stderr
    assert "known input 200 tokens" in content
    assert "Cache-read share 60.00%" in content
    assert "cache-write share 10.00%" in content
    assert "3 completions; 1 excluded rows" in content
    assert "Seven-day comparison unavailable" in content
    assert content.count("**Repeated context**") == 1
    assert content.count("**Large tool outputs**") == 1
    assert content.count("**Retry loops**") == 1
    assert "Observed tokens: 800" in content
    assert "Estimated retrospective reduction" in content
    assert "Achieved stream savings remain unknown" in content
    assert "Saved report 3 source_unavailable" in content
    assert directory.stat().st_mode & 0o777 == 0o700
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in directory.iterdir())
    assert before == (ledger.read_bytes(), snapshot.read_bytes())
    assert not ledger.with_name("usage.sqlite-wal").exists()
    assert not ledger.with_name("usage.sqlite-shm").exists()


def test_complete_cache_windows_compare_only_matching_models(tmp_path, report):
    path = tmp_path / "usage.sqlite"
    bounds = report.windows(CUTOFF)
    ledger_fixture(path, bounds, unknown=False)
    rows, coverage = report.read_ledger(path, bounds)
    assert not any(c["partial"] for c in coverage)
    result = report.cache_candidates(rows, coverage, bounds)
    assert "Previous seven complete days: cache-read share 50.00%" in result[0]["signal"]
    with sqlite3.connect(path) as db:
        db.execute("UPDATE events SET payload=json_set(payload,'$.model','other') "
                   "WHERE event='1' AND kind='start'")
    rows, coverage = report.read_ledger(path, bounds)
    assert "Seven-day comparison unavailable" in report.cache_candidates(rows, coverage, bounds)[0]["signal"]


def test_partial_coverage_blocks_cache_comparison(tmp_path, report):
    path = tmp_path / "usage.sqlite"
    bounds = report.windows(CUTOFF)
    ledger_fixture(path, bounds, unknown=False)
    with sqlite3.connect(path) as db:
        db.execute("DELETE FROM events WHERE kind='checkpoint'")
    rows, coverage = report.read_ledger(path, bounds)
    assert all(c["partial"] for c in coverage)
    assert "Seven-day comparison unavailable" in report.cache_candidates(rows, coverage, bounds)[0]["signal"]


def test_zero_denominator_is_unknown_not_zero_savings(tmp_path, report):
    path = tmp_path / "usage.sqlite"
    bounds = report.windows(CUTOFF)
    ledger_fixture(path, bounds, unknown=False)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE events SET payload=json_set(payload,'$.input',0,'$.cache_read',0,"
                   "'$.cache_write',0) WHERE kind='complete'")
    rows, coverage = report.read_ledger(path, bounds)
    candidates = report.cache_candidates(rows, coverage, bounds)
    assert candidates == []
    collected = report.collect({"ledger": str(path)}, bounds)
    assert "no known nonzero input denominator" in collected[3][3]
    assert "No measured candidates" in report.markdown(bounds, collected, False)


@pytest.mark.parametrize("mutation", ["version", "number", "window", "basis"])
def test_invalid_snapshots_never_create_findings(tmp_path, report, mutation):
    bounds = report.windows(CUTOFF)
    snapshot = snapshot_fixture(bounds)
    if mutation == "version":
        snapshot["schema"] = "future"
    elif mutation == "number":
        snapshot["sinks"][0]["evidence"]["recurrence_sessions"] = True
    elif mutation == "window":
        snapshot["window"]["to"] = (bounds[2] + timedelta(seconds=1)).isoformat()
    else:
        snapshot["sinks"][1]["evidence"]["signature_token_basis"] = CANARY
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot))
    candidates, sources, _, statuses, available = report.collect({"snapshots": [str(path)]}, bounds)
    assert not candidates and not sources and not available
    assert all(s.startswith("unavailable") for s in statuses)


def test_missing_sources_preserve_previous_success(tmp_path, report):
    home = tmp_path / "home"
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot_fixture(report.windows(CUTOFF))))
    config = {"fm_home": str(home), "snapshots": [str(path)]}
    report.publish(config, CUTOFF)
    latest = home / "data/token-savings/latest.md"
    before = latest.read_bytes()
    path.unlink()
    with pytest.raises(ValueError):
        report.publish(config, CUTOFF)
    assert latest.read_bytes() == before
    state = json.loads(latest.with_name("status.json").read_text())
    assert state["state"] == "failed"
    path.write_text(json.dumps(snapshot_fixture(report.windows(CUTOFF))))
    report.publish(config, CUTOFF)
    assert "previous cycle failed" in latest.read_text()


def test_alarm_preserves_report_and_releases_lock(tmp_path, report, monkeypatch):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snapshot_fixture(report.windows(CUTOFF))))
    config = {"fm_home": str(tmp_path / "home"), "snapshots": [str(path)]}
    report.publish(config, CUTOFF)
    latest = tmp_path / "home/data/token-savings/latest.md"
    before = latest.read_bytes()

    def expire(*_):
        os.kill(os.getpid(), signal.SIGALRM)

    with monkeypatch.context() as m:
        m.setattr(report, "read_snapshot", expire)
        with pytest.raises(TimeoutError):
            report.publish(config, CUTOFF)
    assert latest.read_bytes() == before
    report.publish(config, CUTOFF)


def test_spool_and_missing_ledger_never_become_history(tmp_path, report):
    missing = tmp_path / "missing.sqlite"
    bounds = report.windows(CUTOFF)
    with pytest.raises(sqlite3.Error):
        report.read_ledger(missing, bounds)
    assert not missing.exists()
    path = tmp_path / "spool.sqlite"
    ledger_fixture(path, bounds)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE packs (body BLOB)")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="spool"):
        report.read_ledger(path, bounds)
    assert path.read_bytes() == before


def test_no_candidates_is_an_explicit_empty_report(tmp_path, report):
    bounds = report.windows(CUTOFF)
    path = tmp_path / "saved.json"
    data = snapshot_fixture(bounds)
    data["sinks"] = []
    path.write_text(json.dumps(data))
    text = report.markdown(bounds, report.collect({"snapshots": [str(path)]}, bounds), False)
    assert "No measured candidates" in text
    assert "**Repeated context**" not in text


def test_snapshot_and_response_limits(tmp_path, report):
    source = importlib.import_module("token_suggestions_sources")
    path = tmp_path / "too-large.json"
    path.write_bytes(b" " * (source.MIB + 1))
    with pytest.raises(ValueError, match="limit"):
        source.read_json(path)
    with pytest.raises(ValueError, match="limit"):
        source.bounded_rows([{"value": "long"}], 1)


def test_pacific_days_keep_dst_boundaries(report):
    bounds = report.windows(datetime(2026, 11, 2, 16, tzinfo=UTC))
    assert bounds[2] - bounds[1] == timedelta(hours=25)


def test_sql_query_timeout_interrupts_the_source(tmp_path, report, monkeypatch):
    source = importlib.import_module("token_suggestions_sources")
    path = tmp_path / "usage.sqlite"
    bounds = report.windows(CUTOFF)
    ledger_fixture(path, bounds)
    with sqlite3.connect(path) as db:
        for _ in range(8):
            db.execute("INSERT INTO events SELECT * FROM events")
    clock = iter([0])
    monkeypatch.setattr(source.time, "monotonic", lambda: next(clock, 21))
    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        source.read_ledger(path, bounds)


def test_five_candidate_limit_keeps_same_basis_ranking(tmp_path, report):
    bounds = report.windows(CUTOFF)
    data = snapshot_fixture(bounds)
    base = data["sinks"][0]
    data["sinks"] = [
        {**base, "sink_id": f"recurring_context:repaste:{i}",
         "evidence": {**base["evidence"], "occurrence_tokens_total": 1000 + i}}
        for i in range(8)
    ]
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(data))
    text = report.markdown(bounds, report.collect({"snapshots": [str(path)]}, bounds), False)
    assert text.count("**Repeated context**") == 5
    assert text.index("Observed tokens: 1007") < text.index("Observed tokens: 1003")
    assert "Observed tokens: 1002" not in text


def test_reports_keep_only_eight_dated_snapshots(tmp_path, report):
    path = tmp_path / "saved.json"
    config = {"fm_home": str(tmp_path / "home"), "snapshots": [str(path)]}
    for day in range(10):
        cutoff = CUTOFF + timedelta(days=day)
        path.write_text(json.dumps(snapshot_fixture(report.windows(cutoff))))
        report.publish(config, cutoff)
    directory = tmp_path / "home/data/token-savings"
    assert sorted(p.name for p in directory.glob("????-??-??.md")) == [
        f"2026-10-{day}.md" for day in range(21, 29)
    ]


def native_ledger(path, bounds):
    usage = importlib.import_module("usage")
    ledger = usage.Ledger(path)

    def accept(kind, identifier, at, producer=1, **fields):
        return ledger.accept({"schema": 1, "kind": kind, "producer": str(UUID(int=producer)),
                              "event": str(UUID(int=identifier)), "at": at.isoformat(), **fields},
                             CUTOFF)

    accept("register", 100, bounds[0], producer_kind="chat")
    for sequence, at in enumerate((bounds[1] - timedelta(hours=1),
                                   bounds[1] + timedelta(hours=1)), 1):
        accept("start", sequence, at, sequence=sequence, provider="example", model="model")
        accept("complete", sequence, at, sequence=sequence, outcome="success",
               usage_present=True, input_basis="inclusive", input=100, cache_read=60,
               cache_write=10, output=20, reasoning=5)
    accept("checkpoint", 101, bounds[2], sequence=2)
    return ledger, accept


def test_later_native_activity_does_not_change_closed_windows(tmp_path, report):
    path = tmp_path / "native.sqlite"
    bounds = report.windows(CUTOFF)
    ledger, accept = native_ledger(path, bounds)
    try:
        before = report.read_ledger(path, bounds)
        accept("start", 3, CUTOFF, sequence=3, provider="example", model="model")
        accept("checkpoint", 103, CUTOFF, sequence=3)
        accept("register", 200, CUTOFF, producer=2, producer_kind="helper")
        after = report.read_ledger(path, bounds)
    finally:
        ledger.db.close()
    assert not any(c["partial"] for c in before[1])
    assert after == before
    assert "Previous seven complete days" in report.cache_candidates(*after, bounds)[0]["signal"]


def test_fractional_gap_overlap_is_partial_in_native_and_read_only_reports(tmp_path, report):
    path = tmp_path / "native.sqlite"
    bounds = report.windows(CUTOFF)
    ledger, accept = native_ledger(path, bounds)
    try:
        accept("gap", 102, bounds[1] - timedelta(seconds=1),
               end=(bounds[1] + timedelta(microseconds=500_000)).isoformat(), reason="delivery")
        assert ledger.summary(bounds[1], bounds[2], CUTOFF)["partial"]
        _, coverage = report.read_ledger(path, bounds)
    finally:
        ledger.db.close()
    current = next(row for row in coverage if row["current"])
    assert current["gaps"] == 1 and current["partial"]


@pytest.mark.parametrize("tokens", ["missing", None])
@pytest.mark.parametrize("floor", [0, 800])
def test_unknown_output_retry_stays_unranked(tmp_path, report, tokens, floor):
    bounds = report.windows(CUTOFF)
    data = snapshot_fixture(bounds)
    retry = data["sinks"][2]
    if tokens == "missing":
        retry.pop("tokens_observed")
    else:
        retry["tokens_observed"] = tokens
    retry["evidence"]["observed_output_token_floor"] = floor
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(data))
    collected = report.collect({"snapshots": [str(path)]}, bounds)
    rows, _, _, statuses, available = collected
    assert available and all(statuses[i].startswith("available") for i in range(3))
    assert {r["detector"] for r in rows} == {0, 1, 2}
    assert next(r for r in rows if r["detector"] == 2)["tokens"] is None
    text = report.markdown(bounds, collected, False)
    observations = text.split("### Count-only retry observations:", 1)[1]
    assert "- **Retry loops**" in observations
    assert "Observed tokens: unknown" in observations
    assert "Observed tokens: 0" not in observations


@pytest.mark.parametrize("current", [False, True])
def test_checkpoint_missing_requests_block_cache_comparison(tmp_path, report, current):
    path = tmp_path / "native.sqlite"
    bounds = report.windows(CUTOFF)
    native_bounds = bounds if current else (bounds[0], bounds[0] + timedelta(days=1), bounds[1])
    ledger, accept = native_ledger(path, native_bounds)
    try:
        accept("checkpoint", 102, native_bounds[2], sequence=3)
        if not current:
            at = bounds[1] + timedelta(hours=1)
            accept("start", 4, at, sequence=4, provider="example", model="model")
            accept("complete", 4, at, sequence=4, outcome="success", usage_present=True,
                   input_basis="inclusive", input=100, cache_read=60, cache_write=10,
                   output=20, reasoning=5)
            accept("checkpoint", 103, bounds[2], sequence=4)
        assert ledger.summary(bounds[1], bounds[2], CUTOFF)["partial"]
        rows, coverage = report.read_ledger(path, bounds)
    finally:
        ledger.db.close()
    period = next(row for row in coverage if row["current"] == current)
    assert period["incomplete"] == 1 and period["partial"]
    assert all("Seven-day comparison unavailable" in row["signal"]
               for row in report.cache_candidates(rows, coverage, bounds))


@pytest.mark.parametrize("current", [False, True])
@pytest.mark.parametrize("kind, counter", [("gap", "gaps"), ("shutdown", "shutdowns")])
def test_duplicate_coverage_records_count_once(tmp_path, report, current, kind, counter):
    path = tmp_path / "usage.sqlite"
    bounds = report.windows(CUTOFF)
    ledger_fixture(path, bounds, unknown=False, duplicate=True)
    at = bounds[int(current)] + timedelta(hours=1)
    payload = {"schema": 1, "kind": kind, "end": (at + timedelta(hours=1)).isoformat()}
    record = (CANARY, "coverage-event", kind, None, at.timestamp(), json.dumps(payload), 4, 0)
    with sqlite3.connect(path) as db:
        db.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", [record, record])
    _, coverage = report.read_ledger(path, bounds)
    assert {row["current"]: row[counter] for row in coverage} == {
        int(current): 1, int(not current): 0,
    }


def test_copied_exports_do_not_repeat_any_measurement(tmp_path, report):
    bounds = report.windows(CUTOFF)
    data = snapshot_fixture(bounds)
    original, copy = tmp_path / "original.json", tmp_path / "copy.json"
    original.write_text(json.dumps(data))
    copy.write_text(json.dumps(data, sort_keys=True, indent=2))
    collected = report.collect({"snapshots": [str(original), str(copy)]}, bounds)
    rows, sources, _, _, _ = collected
    assert len(rows) == 3 and len(sources) == 1
    text = report.markdown(bounds, collected, False)
    assert text.count("Estimated retrospective reduction (tool_outputs)") == 1
    assert text.count("Estimated retrospective reduction (repeated_blocks)") == 1
    assert text.count("Saved artifact measurement:") == 1
    assert CANARY not in text


def test_distinct_exports_keep_same_key_measurements(tmp_path, report):
    bounds = report.windows(CUTOFF)
    paths = []
    for index, tokens in enumerate((3000, 4000)):
        data = snapshot_fixture(bounds)
        data["sinks"] = [data["sinks"][1]]
        data["sinks"][0]["evidence"]["tool_output_tokens"] = tokens
        path = tmp_path / f"saved-{index}.json"
        path.write_text(json.dumps(data))
        paths.append(str(path))
    collected = report.collect({"snapshots": paths}, bounds)
    assert [row["tokens"] for row in collected[0]] == [3000, 4000]
    text = report.markdown(bounds, collected, False)
    assert text.index("Observed tokens: 4000") < text.index("Observed tokens: 3000")
    assert "Source: saved report 1" in text and "Source: saved report 2" in text


@pytest.mark.parametrize("detector", [0, 1, 2])
@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_findings_are_collapsed_or_rejected(tmp_path, report, detector, conflict):
    bounds = report.windows(CUTOFF)
    data = snapshot_fixture(bounds)
    sink = data["sinks"][detector]
    duplicate = json.loads(json.dumps(sink))
    if conflict:
        field = ("occurrence_tokens_total", "tool_output_tokens", "calls")[detector]
        duplicate["evidence"][field] += 1
    data["sinks"] = [sink, duplicate]
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(data))
    rows, sources, notes, _, available = report.collect({"snapshots": [str(path)]}, bounds)
    if conflict:
        assert not rows and not sources and not available
        assert any("Saved report 1 source_unavailable" in note for note in notes)
    else:
        assert len(rows) == 1 and len(sources) == 1 and available


@pytest.mark.parametrize("errors", ["missing", None])
def test_unknown_tool_error_counts_stay_null(tmp_path, report, errors):
    bounds = report.windows(CUTOFF)
    data = snapshot_fixture(bounds)
    shape = data["sinks"][1]["evidence"]["top_signatures"][0]
    if errors == "missing":
        shape.pop("error_calls")
    else:
        shape["error_calls"] = errors
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(data))
    collected = report.collect({"snapshots": [str(path)]}, bounds)
    tool = next(row for row in collected[0] if row["detector"] == 1)
    assert tool["tool_shapes"][0]["error_calls"] is None
    assert "error_calls unknown" in report.markdown(bounds, collected, False)


def test_tool_shapes_keep_numeric_evidence_without_signatures(tmp_path, report):
    bounds = report.windows(CUTOFF)
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(snapshot_fixture(bounds)))
    collected = report.collect({"snapshots": [str(path)]}, bounds)
    tool = next(row for row in collected[0] if row["detector"] == 1)
    assert tool["tool_shapes"] == [
        {"calls": 5, "tokens": 3000, "largest_call": 1000, "error_calls": 2},
    ]
    text = report.markdown(bounds, collected, False)
    assert "Tool shape 1: calls 5; tokens 3000; largest_call 1000; error_calls 2." in text
    assert CANARY not in text
