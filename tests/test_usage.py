import gzip
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import zlib
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("usage", ROOT / "scripts/usage.py")
usage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(usage)
CHART_SPEC = importlib.util.spec_from_file_location("usage_dashboard", ROOT / "scripts/usage_dashboard.py")
charts = importlib.util.module_from_spec(CHART_SPEC)
CHART_SPEC.loader.exec_module(charts)
NOW = datetime(2026, 11, 2, 12, tzinfo=UTC)
PRODUCER = str(UUID(int=1))


def event(kind, number=1, **fields):
    return {
        "schema": 1,
        "kind": kind,
        "producer": PRODUCER,
        "event": str(UUID(int=number + {"register": 100, "start": 200,
                                      "complete": 200, "checkpoint": 300,
                                      "gap": 400, "shutdown": 500}[kind])),
        "at": NOW.isoformat(),
        **fields,
    }


def register(ledger, *, now=NOW, **fields):
    ledger.accept(event("register", producer_kind="chat", **fields), now)


def start(ledger, number=1, *, now=NOW, **fields):
    ledger.accept(event("start", number, sequence=number, provider="example", model="model-a",
                        **fields), now)


def complete(ledger, number=1, *, now=NOW, **fields):
    return ledger.accept(event("complete", number, sequence=number, outcome="success",
                               usage_present=True, input_basis="exclusive", input=10,
                               cache_read=20, cache_write=5, output=8, reasoning=3,
                               **fields), now)


@pytest.fixture
def ledger(tmp_path):
    with usage.Ledger(tmp_path / "ledger.sqlite") as result:
        yield result


def test_replays_are_counted_once_and_identity_conflicts_fail(ledger):
    register(ledger)
    start(ledger)
    first, replay = complete(ledger), complete(ledger)
    assert first["accepted"] is True and first["duplicate"] is False
    assert replay["accepted"] is True and replay["duplicate"] is True
    other = event("complete", sequence=1, outcome="success", usage_present=True,
                  input_basis="exclusive", input=99, cache_read=20, cache_write=5,
                  output=8, reasoning=3)
    with pytest.raises(ValueError):
        ledger.accept(other, NOW)
    start(ledger, 2)
    complete(ledger, 2)
    report = ledger.summary(NOW - timedelta(hours=1), NOW + timedelta(seconds=1))
    assert report["requests"] == 2
    assert report["counted_tokens"] == 86


def test_unknown_usage_and_known_zero_remain_distinct(ledger):
    register(ledger)
    start(ledger)
    ledger.accept(event("complete", sequence=1, outcome="error", usage_present=False,
                        input_basis="unknown", **dict.fromkeys(usage.TOKENS)), NOW)
    start(ledger, 2)
    ledger.accept(event("complete", 2, sequence=2, outcome="success", usage_present=True,
                        input_basis="exclusive", **dict.fromkeys(usage.TOKENS, 0)), NOW)
    rows = ledger.db.execute(
        "SELECT total,payload FROM events WHERE kind='complete' ORDER BY sequence").fetchall()
    assert [row["total"] for row in rows] == [None, 0]
    assert [json.loads(row["payload"])["outcome"] for row in rows] == ["error", "success"]
    assert ledger.summary(NOW - timedelta(hours=1), NOW + timedelta(seconds=1))["unknown_tokens"] == 1


def test_cache_inclusive_and_exclusive_totals_agree_without_adding_reasoning():
    exclusive = dict(input_basis="exclusive", usage_present=True, input=10,
                     cache_read=20, cache_write=5, output=8, reasoning=3)
    inclusive = {**exclusive, "input_basis": "inclusive", "input": 35}
    assert usage.normalize(exclusive) == usage.normalize(inclusive) == {
        "uncached_input": 10, "input_total": 35, "total": 43}
    assert usage.normalize({**inclusive, "cache_read": None}) == {
        "uncached_input": None, "input_total": 35, "total": 43}
    with pytest.raises(ValueError):
        usage.normalize({**inclusive, "input": 1})
    with pytest.raises(ValueError):
        usage.normalize({**exclusive, "reasoning": 9})


@pytest.mark.parametrize("cache_read,cache_write", [(20, None), (None, 20)])
def test_known_cache_cannot_exceed_inclusive_input_when_another_bucket_is_unknown(
        cache_read, cache_write):
    counters = dict(usage_present=True, input_basis="inclusive", input=10, output=8,
                    cache_read=cache_read, cache_write=cache_write, reasoning=None)
    with pytest.raises(ValueError):
        usage.normalize(counters)


def test_checkpoint_gaps_close_only_when_the_missing_completions_arrive(ledger):
    register(ledger)
    start(ledger)
    complete(ledger)
    start(ledger, 3)
    complete(ledger, 3)
    ledger.accept(event("checkpoint", sequence=3), NOW)
    assert ledger.coverage(NOW)[0]["missing_sequences"] == [[2, 2]]
    start(ledger, 2)
    complete(ledger, 2)
    assert ledger.coverage(NOW)[0]["missing_sequences"] == []
    ledger.accept(event("gap", end=(NOW + timedelta(minutes=1)).isoformat(), reason="delivery"), NOW)
    assert ledger.coverage(NOW)[0]["gap_intervals"] == 1
    assert ledger.summary(NOW, NOW + timedelta(minutes=1))["partial"] is True


def test_shutdown_never_claims_current_continuous_coverage(ledger):
    register(ledger, at=(NOW - timedelta(hours=2)).isoformat())
    ledger.accept(event("shutdown", sequence=0), NOW)
    assert ledger.summary(NOW, NOW + timedelta(minutes=1))["partial"] is True


def test_pacific_bounds_observe_dst_and_monday_weeks():
    fall = datetime(2026, 11, 1, 20, tzinfo=UTC)
    spring = datetime(2026, 3, 8, 20, tzinfo=UTC)
    for snapshot, expected_start, hours in [
        (fall, datetime(2026, 11, 1, 7, tzinfo=UTC), 25),
        (spring, datetime(2026, 3, 8, 8, tzinfo=UTC), 23),
    ]:
        lower, upper = usage.calendar_bounds("day", snapshot)
        next_start, _ = usage.calendar_bounds("day", snapshot + timedelta(days=1))
        assert (lower, upper) == (expected_start, snapshot)
        assert next_start - lower == timedelta(hours=hours)
    assert usage.calendar_bounds("week", fall) == (datetime(2026, 10, 26, 7, tzinfo=UTC), fall)
    assert usage.calendar_bounds("month", NOW) == (datetime(2026, 11, 1, 7, tzinfo=UTC), NOW)


def test_retention_keeps_identity_and_coverage_for_35_days(ledger):
    register(ledger)
    start(ledger)
    complete(ledger)
    ledger.prune(NOW + timedelta(days=35) - timedelta(microseconds=1))
    assert complete(ledger)["duplicate"] is True
    assert ledger.coverage(NOW)[0]["producer"] == PRODUCER
    ledger.prune(NOW + timedelta(days=35, microseconds=1))
    assert ledger.coverage(NOW + timedelta(days=35, microseconds=1)) == []
    with pytest.raises(ValueError):
        ledger.accept(event("register", producer_kind="chat"),
                      NOW + timedelta(days=36))


@pytest.mark.parametrize("field,value", [("content", "private"), ("headers", {}),
                                         ("error", "private"), ("content_hash", "abc"),
                                         ("attributes", {"secret": "private"})])
def test_capture_rejects_extra_fields_without_storing_them(ledger, field, value):
    with pytest.raises(ValueError):
        ledger.accept(event("register", producer_kind="chat", **{field: value}), NOW)
    assert ledger.db.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_export_retries_keep_the_same_identity_and_do_not_ack_partial_success(ledger):
    register(ledger)
    start(ledger)
    complete(ledger)
    attempts = []

    def reject(payload):
        attempts.append(payload)
        return {"partialSuccess": {"rejectedLogRecords": "1"}}

    with pytest.raises(ValueError):
        ledger.export(reject, NOW)
    delivered = []
    assert ledger.export(lambda payload: delivered.append(payload) or {}, NOW) == 3
    assert attempts == delivered
    assert ledger.export(lambda _: pytest.fail("already acknowledged"), NOW) == 0
    logs = delivered[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    completed = logs[-1]
    attributes = {entry["key"]: entry["value"] for entry in completed["attributes"]}
    assert attributes["usage.total"] == {"intValue": "43"}
    assert attributes["usage.reasoning"] == {"intValue": "3"}
    assert completed["body"] == {"stringValue": "Model request metadata"}


def test_half_open_completion_bounds(ledger):
    register(ledger)
    start(ledger)
    complete(ledger)
    assert ledger.summary(NOW - timedelta(seconds=1), NOW)["requests"] == 0
    assert ledger.summary(NOW, NOW + timedelta(seconds=1))["requests"] == 1


def test_missing_mount_fails_before_creating_a_directory(tmp_path):
    missing = tmp_path / "unmounted"
    process = subprocess.run([sys.executable, str(ROOT / "scripts/usage.py"),
                              "--mount", str(missing), "--data-dir", str(missing / "usage"),
                              "collect"], input="", capture_output=True, text=True)
    assert process.returncode != 0
    assert not missing.exists()


def test_export_revalidates_corrupt_storage_before_sending(ledger):
    register(ledger)
    row = ledger.db.execute("SELECT payload FROM events").fetchone()
    payload = {**json.loads(row[0]), "content": "private"}
    ledger.db.execute("UPDATE events SET payload=?", (json.dumps(payload),))
    ledger.db.commit()
    with pytest.raises(ValueError):
        ledger.export(lambda _: pytest.fail("must not send"), NOW)


def test_separate_connections_serialize_identity_claims(tmp_path):
    path = tmp_path / "concurrent.sqlite"
    with usage.Ledger(path) as first, usage.Ledger(path) as second:
        register(first)
        start(first)
        complete(first)
        assert complete(second)["duplicate"] is True
        assert first.db.execute("SELECT count(*) FROM events WHERE kind='complete'").fetchone()[0] == 1
    assert sqlite3.connect(path).execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_late_completion_keeps_its_start_and_registration_for_the_full_window(ledger):
    register(ledger)
    start(ledger)
    finished = NOW + timedelta(days=2)
    ledger.accept(event("complete", sequence=1, at=finished.isoformat(), outcome="aborted",
                        usage_present=False, input_basis="unknown", **dict.fromkeys(usage.TOKENS)),
                  finished)
    ledger.prune(NOW + timedelta(days=36))
    batches = []
    ledger.export(lambda batch: batches.append(batch) or {}, NOW + timedelta(days=36))
    completed = batches[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][-1]
    attributes = {entry["key"]: entry["value"] for entry in completed["attributes"]}
    assert attributes["usage.provider"] == {"stringValue": "example"}
    assert attributes["usage.started"] == {"doubleValue": NOW.timestamp()}
    assert ledger.coverage(finished)[0]["registered"] == NOW.isoformat()


def test_invalid_export_acknowledgement_does_not_lose_the_outbox(ledger):
    register(ledger)
    with pytest.raises(ValueError):
        ledger.export(lambda _: {"error": "not accepted"}, NOW)
    with pytest.raises(ValueError):
        ledger.export(lambda _: {"partialSuccess": {"rejectedLogRecords": 0.5}}, NOW)
    assert ledger.export(lambda _: {}, NOW) == 1


def test_checkpoint_cannot_regress_time_or_sequence(ledger):
    register(ledger, at=(NOW - timedelta(hours=2)).isoformat())
    start(ledger, 3)
    with pytest.raises(ValueError):
        ledger.accept(event("checkpoint", sequence=2), NOW)
    ledger.accept(event("checkpoint", sequence=3), NOW)
    with pytest.raises(ValueError):
        ledger.accept(event("checkpoint", 2, sequence=3,
                            at=(NOW - timedelta(seconds=1)).isoformat()), NOW)


def test_unknown_native_usage_presence_stays_unknown(ledger):
    register(ledger)
    start(ledger)
    ledger.accept(event("complete", sequence=1, outcome="unknown", usage_present=None,
                        input_basis="unknown", **dict.fromkeys(usage.TOKENS)), NOW)
    row = ledger.db.execute("SELECT total,payload FROM events WHERE kind='complete'").fetchone()
    assert json.loads(row["payload"])["usage_present"] is None
    assert row["total"] is None


def test_late_ingestion_uses_separate_retention_and_completion_instants(ledger):
    earlier = (NOW - timedelta(days=2)).replace(microsecond=123456)
    register(ledger, at=earlier.isoformat())
    start(ledger, at=earlier.isoformat())
    complete(ledger, at=earlier.isoformat())
    batches = []
    ledger.export(lambda batch: batches.append(batch) or {}, NOW)
    completed = batches[0]["resourceLogs"][0]["scopeLogs"][0]["logRecords"][-1]
    attributes = {entry["key"]: entry["value"] for entry in completed["attributes"]}
    assert int(completed["timeUnixNano"]) == int(NOW.timestamp()) * 1_000_000_000
    epoch = earlier - datetime(1970, 1, 1, tzinfo=UTC)
    expected = (epoch.days * 86400 + epoch.seconds) * 1_000_000 + epoch.microseconds
    assert attributes["usage.at_us"] == {"intValue": str(expected)}


def test_report_uses_one_snapshot_while_another_collector_writes(ledger, monkeypatch):
    register(ledger)
    start(ledger)
    complete(ledger)
    database = ledger.db.execute("PRAGMA database_list").fetchone()[2]
    original = ledger.coverage
    with usage.Ledger(database) as writer:
        def write_during_report(now):
            start(writer, 2)
            complete(writer, 2)
            return original(now)

        monkeypatch.setattr(ledger, "coverage", write_during_report)
        snapshot = ledger.summary(NOW, NOW + timedelta(seconds=1))
        assert snapshot["requests"] == 1
        assert snapshot["coverage"][0]["through"] == 1
    monkeypatch.setattr(ledger, "coverage", original)
    assert ledger.summary(NOW, NOW + timedelta(seconds=1))["requests"] == 2


def test_dashboard_layout_places_each_panel_once_with_line_graphs_first():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/usage_dashboard.py")],
                            capture_output=True, text=True, check=True)
    document = json.loads(result.stdout)
    assert document == json.loads((ROOT / "blueprint/usage/dashboard.json").read_text())
    placed = []
    for layout in document["spec"]["layouts"]:
        cells = set()
        for item in layout["spec"]["items"]:
            assert item["width"] >= 1 and 0 <= item["x"] <= 12 - item["width"]
            area = {(item["x"] + column, item["y"] + row)
                    for column in range(item["width"]) for row in range(item["height"])}
            assert not cells & area
            cells |= area
            placed.append(item["content"]["$ref"].rsplit("/", 1)[1])
    assert sorted(placed) == sorted(document["spec"]["panels"])
    usage_items = document["spec"]["layouts"][0]["spec"]["items"]
    assert {item["content"]["$ref"].rsplit("/", 1)[1]
            for item in usage_items if item["y"] == 0} == {"requests", "tokens"}


@pytest.fixture
def clickhouse_ledger():
    endpoint = os.environ.get("CREWSHIP_TEST_CLICKHOUSE_URL")
    receipt = os.environ.get("CREWSHIP_TEST_USAGE_RECEIPT")
    if not endpoint or not receipt:
        pytest.skip("Set CREWSHIP_TEST_CLICKHOUSE_URL and CREWSHIP_TEST_USAGE_RECEIPT for the synthetic lab")
    return endpoint, json.loads(Path(receipt).read_text())


@pytest.mark.parametrize("panel", ["prompts", "calendar"])
def test_generated_queries_match_clickhouse_ledger_receipt(clickhouse_ledger, panel):
    endpoint, receipt = clickhouse_ledger
    query = charts.dashboard()["spec"]["panels"][panel]["spec"]["queries"][0]["spec"]["plugin"]["spec"]["query"]
    query = query.replace("$start_timestamp_nano", str(receipt["start_ns"]))
    query = query.replace("$end_timestamp_nano", str(receipt["end_ns"]))
    request = Request(endpoint.rstrip("/") + "/?readonly=1&output_format_json_quote_64bit_integers=0",
                      data=(query + " FORMAT JSONEachRow").encode())

    with urlopen(request, timeout=30) as response:
        result = [json.loads(line) for line in response if line.strip()]

    if panel == "calendar":
        result.sort(key=lambda row: row["period"])
    assert result == receipt[panel]


def test_completed_call_rates_exclude_clipped_window_edges():
    with sqlite3.connect(":memory:") as connection:
        connection.create_function("intDiv", 2, lambda numerator, denominator: numerator // denominator)
        connection.execute("CREATE TABLE completions(completed_ns INTEGER)")
        connection.executemany("INSERT INTO completions VALUES(?)", [
            (30_000_000_000,), (59_999_999_999,), (60_000_000_000,),
            (119_999_999_999,), (120_000_000_000,), (150_000_000_000,),
        ])
        condition = charts.CLOSED.replace("$start_timestamp_nano", ":lower").replace(
            "$end_timestamp_nano", ":upper")
        rows = connection.execute(f"SELECT completed_ns FROM completions WHERE {condition}",
                                  {"lower": 30_000_000_000, "upper": 155_000_000_000}).fetchall()
    assert [row[0] for row in rows] == [60_000_000_000, 119_999_999_999]


def calendar_rows(gaps, *, missing=0, producers=1):
    pacific = ZoneInfo("America/Los_Angeles")
    upper = datetime(2026, 10, 14, 19, tzinfo=UTC)
    def nano(value):
        return round(value.timestamp() * 1_000_000) * 1000

    def moment(value):
        return datetime.fromtimestamp(value / 1e9, UTC)

    def start(period):
        return lambda value: nano(usage.calendar_bounds(period, moment(value))[0])

    def week_start(value, mode):
        local = moment(value).astimezone(pacific).replace(hour=0, minute=0, second=0, microsecond=0)
        return nano(local - timedelta(days=(local.weekday() + (mode == 0)) % 7))

    class CountIf:
        def __init__(self):
            self.value = 0

        def step(self, condition):
            self.value += bool(condition)

        def finalize(self):
            return self.value

    class SumOrNull:
        def __init__(self):
            self.value = None

        def step(self, value):
            if value is not None:
                self.value = (self.value or 0) + value

        def finalize(self):
            return self.value

    query = charts.calendar_query().replace("INTERVAL 35 DAY", str(35 * 86400 * 1_000_000_000))
    query = re.sub(r"numbers\['([^']+)'\]", r"""json_extract(numbers, '$."\1"')""", query)
    query = query.replace("isNull(", '"isNull"(')
    with sqlite3.connect(":memory:") as connection:
        for name, arity, function in [
            ("if", 3, lambda condition, yes, no: yes if condition else no),
            ("toInt64", 1, int), ("fromUnixTimestamp64Nano", 1, int),
            ("toTimeZone", 2, lambda value, _: value), ("toDateTime64", 3, lambda value, *_: value),
            ("toUnixTimestamp64Nano", 1, int), ("now64", 1, lambda _: nano(upper)),
            ("toStartOfDay", 1, start("day")), ("toStartOfWeek", 2, week_start),
            ("toStartOfMonth", 1, start("month")), ("toNullable", 1, lambda value: value),
            ("toFloat64", 1, float), ("isNull", 1, lambda value: value is None),
            ("toString", 1, lambda value: moment(value).astimezone(pacific).strftime("%Y-%m-%d %H:%M:%S")),
        ]:
            connection.create_function(name, arity, function)
        connection.create_aggregate("countIf", 1, CountIf)
        connection.create_aggregate("sumOrNull", 1, SumOrNull)
        connection.execute("CREATE TABLE records(producer TEXT,kind TEXT,completed_ns INTEGER,numbers TEXT)")
        connection.execute("CREATE TABLE completions(completed_ns INTEGER,tokens REAL)")
        connection.execute("CREATE TABLE coverage(missing INTEGER,gaps INTEGER,registered REAL,checkpoint REAL)")
        connection.executemany("INSERT INTO records VALUES('p','register',?,'{}')",
                               [(nano(datetime(2026, 9, 10, tzinfo=UTC)),)] * producers)
        connection.executemany("INSERT INTO records VALUES('p','gap',?,?)", [
            (nano(at), json.dumps({"usage.at": at.timestamp(), "usage.end": end.timestamp()}))
            for at, end in gaps])
        connection.executemany("INSERT INTO completions VALUES(?,?)", [
            (nano(datetime(2026, 10, day, 18, tzinfo=UTC)), 10.0) for day in (2, 13, 14)])
        connection.executemany("INSERT INTO coverage VALUES(?,?,?,?)", [
            (missing, len(gaps), datetime(2026, 9, 10, tzinfo=UTC).timestamp(), upper.timestamp())] * producers)
        rows = connection.execute(query, {"end_timestamp_nano": nano(upper)}).fetchall()
    return [(period, pacific_start, requests, partial)
            for period, pacific_start, requests, _, _, partial in rows]


def test_calendar_partial_counts_only_gaps_that_overlap_each_pacific_period():
    pacific = ZoneInfo("America/Los_Angeles")
    day, week, month = (datetime(2026, 10, date, tzinfo=pacific) for date in (14, 12, 1))
    upper = datetime(2026, 10, 14, 19, tzinfo=UTC)
    hour = timedelta(hours=1)
    starts = [("Today", "2026-10-14 00:00:00", 1.0), ("This week", "2026-10-12 00:00:00", 2.0),
              ("This month", "2026-10-01 00:00:00", 3.0)]
    for gaps, expected in [
        ([], (0, 0, 0)),
        ([(datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 21, tzinfo=UTC))], (0, 0, 0)),
        ([(month - hour, month)], (0, 0, 0)),
        ([(upper, upper + hour)], (0, 0, 0)),
        ([(month - hour, month + hour)], (0, 0, 1)),
        ([(week - hour, week)], (0, 0, 1)),
        ([(week - hour, week + hour)], (0, 1, 1)),
        ([(day - hour, day + timedelta(seconds=1))], (1, 1, 1)),
        ([(upper - hour, upper + hour)], (1, 1, 1)),
    ]:
        assert calendar_rows(gaps) == [
            (*start, flag) for start, flag in zip(starts, expected)], gaps
    assert [row[3] for row in calendar_rows([], missing=1)] == [1, 1, 1]
    assert [row[3] for row in calendar_rows([], producers=0)] == [1, 1, 1]



def test_expired_producer_history_cannot_make_an_old_period_complete(ledger):
    registered = NOW - timedelta(days=50)
    ledger.accept(event("register", at=registered.isoformat(),
                        producer_kind="chat"), registered)
    checkpoint = NOW - timedelta(days=30)
    ledger.accept(event("checkpoint", 1, at=checkpoint.isoformat(), sequence=0), checkpoint)
    ledger.accept(event("checkpoint", 2, sequence=0), NOW)
    ledger.prune(NOW)
    report = ledger.summary(NOW - timedelta(days=45), NOW - timedelta(days=44), now=NOW)
    assert report["requests"] == 0
    assert report["partial"] is True
    assert report["coverage"][0]["retained_from"] == (NOW - timedelta(days=35)).isoformat()


def test_active_producer_remains_complete_after_old_completions_expire(ledger):
    old = NOW - timedelta(days=36)
    register(ledger, now=old, at=old.isoformat())
    start(ledger, now=old, at=old.isoformat())
    complete(ledger, now=old, at=old.isoformat())
    checkpoint = NOW - timedelta(days=20)
    ledger.accept(event("checkpoint", 1, at=checkpoint.isoformat(), sequence=1), checkpoint)
    ledger.prune(NOW)
    recent = NOW - timedelta(seconds=1)
    start(ledger, 2, at=recent.isoformat())
    complete(ledger, 2, at=recent.isoformat())
    ledger.accept(event("checkpoint", 2, sequence=2), NOW)
    report = ledger.summary(NOW - timedelta(minutes=1), NOW, now=NOW)
    assert report["requests"] == 1 and report["counted_tokens"] == 43
    assert report["partial"] is False
    assert report["coverage"][0]["missing_sequences"] == []
    assert report["coverage"][0]["retired_completions"] == 1
    with pytest.raises(ValueError):
        start(ledger, 1)


def test_late_lower_sequences_do_not_hide_out_of_order_retirement(ledger):
    old = NOW - timedelta(days=36)
    register(ledger, now=old, at=old.isoformat())
    start(ledger, 1, now=old, at=old.isoformat())
    start(ledger, 2, now=old, at=old.isoformat())
    complete(ledger, 2, now=old, at=old.isoformat())
    later = NOW - timedelta(days=20)
    complete(ledger, 1, now=later, at=later.isoformat())
    ledger.prune(NOW)
    ledger.accept(event("checkpoint", sequence=2), NOW)
    report = ledger.summary(NOW - timedelta(days=25), NOW, now=NOW)
    assert report["requests"] == 1
    assert report["partial"] is False
    assert report["coverage"][0]["missing_sequences"] == []
    assert report["coverage"][0]["retired_completions"] == 1


def test_retirement_watermarks_preserve_retry_identity_and_reveal_export_gaps(ledger):
    old = NOW - timedelta(days=35) + timedelta(seconds=5)
    register(ledger, now=old, at=old.isoformat())
    start(ledger, now=old, at=old.isoformat())
    complete(ledger, now=old, at=old.isoformat())
    recent = NOW - timedelta(seconds=1)
    start(ledger, 2, at=recent.isoformat())
    complete(ledger, 2, at=recent.isoformat())
    ledger.accept(event("checkpoint", sequence=2), NOW)
    attempts = []
    with pytest.raises(ValueError):
        ledger.export(lambda batch: attempts.append(batch) or {
            "partialSuccess": {"rejectedLogRecords": "1"}}, NOW)
    later = NOW + timedelta(seconds=10)
    ledger.prune(later)
    ledger.export(lambda batch: attempts.append(batch) or {}, later)

    def metadata(batch):
        result = []
        for row in batch["resourceLogs"][0]["scopeLogs"][0]["logRecords"]:
            fields = {}
            for attribute in row["attributes"]:
                value = attribute["value"]
                fields[attribute["key"]] = (int(value["intValue"]) if "intValue" in value
                                             else next(iter(value.values())))
            result.append((fields, row))
        return result

    first, retry = metadata(attempts[0]), metadata(attempts[1])
    first_row = next(row for fields, row in first
                     if fields["usage.kind"] == "complete" and fields["usage.sequence"] == 2)
    retry_row = next(row for fields, row in retry
                     if fields["usage.kind"] == "complete" and fields["usage.sequence"] == 2)
    assert first_row == retry_row
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE received(event TEXT,kind TEXT,sequence INTEGER,"
                           "through INTEGER,retired INTEGER)")
        connection.executemany("INSERT INTO received VALUES(?,?,?,?,?)", [
            (fields["usage.event"], fields["usage.kind"], fields.get("usage.sequence"),
             fields["usage.sequence_through"], fields["usage.retired_completions"])
            for fields, _ in retry
        ])
        calculation = ("WITH producer AS (SELECT max(through) AS through,max(retired) AS retired,"
                       "count(DISTINCT CASE WHEN kind='complete' THEN sequence END) AS completed_count "
                       "FROM received) SELECT " + charts.COVERAGE_BALANCE + " FROM producer")
        assert connection.execute(calculation).fetchone()[0] == 0
        connection.execute("DELETE FROM received WHERE kind='complete'")
        assert connection.execute(calculation).fetchone()[0] == 1


def test_interleaved_pruners_retire_each_completion_once(tmp_path):
    path = tmp_path / "retirement.sqlite"
    with usage.Ledger(path) as first, usage.Ledger(path) as second:
        old = NOW - timedelta(days=36)
        register(first, now=old, at=old.isoformat())
        start(first, now=old, at=old.isoformat())
        complete(first, now=old, at=old.isoformat())
        recent = NOW - timedelta(seconds=1)
        start(first, 2, at=recent.isoformat())
        start(first, 3, at=recent.isoformat())
        complete(first, 3, at=recent.isoformat())
        first.accept(event("checkpoint", sequence=3), NOW)
        second.db.execute("PRAGMA busy_timeout=0")
        interleaved = []

        class InterleavedCursor(sqlite3.Cursor):
            def fetchall(self):
                rows = super().fetchall()
                if not interleaved:
                    interleaved.append(True)
                    try:
                        second.prune(NOW)
                    except sqlite3.OperationalError as error:
                        assert error.sqlite_errorcode in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
                return rows

        class InterleavedConnection(sqlite3.Connection):
            def execute(self, sql, parameters=()):
                return self.cursor(factory=InterleavedCursor).execute(sql, parameters)

        first.db.close()
        first.db = sqlite3.connect(path, factory=InterleavedConnection)
        first.db.row_factory = sqlite3.Row
        first.prune(NOW)
        second.prune(NOW)
        report = second.summary(NOW - timedelta(minutes=1), NOW, now=NOW)
        assert report["requests"] == 1
        assert report["partial"] is True
        assert report["coverage"][0]["missing_sequences"] == [[2, 2]]
        assert report["coverage"][0]["retired_completions"] == 1
        assert second.db.execute("SELECT count(*) FROM events WHERE kind='retention'").fetchone()[0] == 1
        balance = second.db.execute(
            "WITH producer AS (SELECT max(sequence_through) AS through,"
            "max(retired_completions) AS retired,"
            "count(DISTINCT CASE WHEN kind='complete' THEN sequence END) AS completed_count "
            "FROM events) SELECT " + charts.COVERAGE_BALANCE + " FROM producer").fetchone()[0]
        assert balance == 1


def logs(batch):
    return batch["resourceLogs"][0]["scopeLogs"][0]["logRecords"]


def stored(store):
    return [tuple(row) for row in store.db.execute(
        "SELECT kind,sent IS NULL FROM events ORDER BY rowid")]


def test_spool_exports_ledger_records_and_keeps_only_what_later_records_need(tmp_path):
    records = [event("register", producer_kind="chat"),
               event("start", sequence=1, provider="example", model="model-a"),
               event("complete", sequence=1, outcome="success", usage_present=True,
                     input_basis="exclusive", input=10, cache_read=20, cache_write=5, output=8,
                     reasoning=3),
               event("checkpoint", sequence=1), event("checkpoint", 2, sequence=1),
               event("start", 2, sequence=2, provider="example", model="model-b")]
    sent = {}
    with usage.Ledger(tmp_path / "usage.sqlite") as ledger, \
            usage.Spool(tmp_path / "spool.sqlite") as spool:
        for store in (ledger, spool):
            for record in records:
                store.accept(record, NOW)
            sent[store] = []
            store.export(lambda batch, store=store: sent[store].append(batch) or {}, NOW)
        replaced = event("checkpoint", sequence=1)["event"]
        assert sorted(json.dumps(log, sort_keys=True) for log in logs(sent[ledger][0])
                      if {"key": "usage.event", "value": {"stringValue": replaced}}
                      not in log["attributes"]) \
            == sorted(json.dumps(log, sort_keys=True) for log in logs(sent[spool][0]))
        assert stored(spool) == [("register", 0), ("start", 0)]
        spool.accept(event("complete", 2, sequence=2, outcome="aborted", usage_present=False,
                           input_basis="unknown", **dict.fromkeys(usage.TOKENS)), NOW)
        late = []
        assert spool.export(lambda batch: late.append(batch) or {}, NOW) == 1
        attributes = {item["key"]: item["value"] for item in logs(late[0])[0]["attributes"]}
        assert attributes["usage.model"] == {"stringValue": "model-b"}
        assert attributes["usage.producer_kind"] == {"stringValue": "chat"}
        assert stored(spool) == [("register", 0)]
        assert spool.db.execute("SELECT bytes FROM budget").fetchone()[0] == len(
            spool.db.execute("SELECT payload FROM events").fetchone()[0])
        assert spool.prune(NOW + timedelta(days=35, microseconds=1)) == 1


def pending(spool):
    return spool.db.execute("SELECT (SELECT count(*) FROM events WHERE sent IS NULL)"
                            "+(SELECT coalesce(sum(records),0) FROM packs)").fetchone()[0]


def test_spool_keeps_unacknowledged_batches_and_retries_identical_bytes(tmp_path):
    with usage.Spool(tmp_path / "spool.sqlite") as spool:
        register(spool)
        start(spool)
        complete(spool)
        attempts = []

        def lost(batch):
            attempts.append(json.dumps(batch))
            raise OSError("acknowledgement lost")

        later = NOW + timedelta(hours=2)
        for moment, send in ((NOW, lost), (later, lambda batch: attempts.append(json.dumps(batch))
                                           or {"partialSuccess": {"rejectedLogRecords": "1"}})):
            with pytest.raises((OSError, ValueError)):
                spool.export(send, moment)
            assert pending(spool) == 3
        spool.accept(event("checkpoint", sequence=1, at=later.isoformat()), later)
        assert spool.export(lambda batch: attempts.append(json.dumps(batch)) or {}, later) == 4
        assert attempts[0] == attempts[1] == attempts[2] != attempts[3]
        assert stored(spool) == [("register", 0)] and pending(spool) == 0


def test_backlog_packs_by_window_and_model_and_sends_the_ledger_records(tmp_path):
    earlier = NOW - timedelta(hours=3)
    sent = {}
    with usage.Ledger(tmp_path / "usage.sqlite") as ledger, \
            usage.Spool(tmp_path / "spool.sqlite") as spool:
        for store in (ledger, spool):
            register(store, now=earlier, at=earlier.isoformat())
            for number, model in enumerate(("model-b", "model-a", "model-b", "model-a", "model-b"), 1):
                moment = earlier + timedelta(minutes=20 * number)
                store.accept(event("start", number, sequence=number, provider="example",
                                   model=model, at=moment.isoformat()), moment)
                complete(store, number, now=moment, at=moment.isoformat())
            sent[store] = []
            store.export(lambda batch, store=store: sent[store].append(batch) or {}, NOW)
        assert sorted(json.dumps(log, sort_keys=True) for batch in sent[spool] for log in logs(batch)) \
            == sorted(json.dumps(log, sort_keys=True) for batch in sent[ledger] for log in logs(batch))
        models = [[next((item["value"]["stringValue"] for item in log["attributes"]
                         if item["key"] == "usage.model"), "") for log in logs(batch)]
                  for batch in sent[spool]]
        assert models == [["", "model-a", "model-a", "model-b", "model-b"],
                          ["model-a", "model-a", "model-b", "model-b", "model-b", "model-b"]]
        assert pending(spool) == 0


def test_a_35_day_outage_keeps_labels_expires_held_packs_and_admits_again(tmp_path, monkeypatch,
                                                                          capsys):
    with usage.Spool(tmp_path / "spool.sqlite") as spool:
        register(spool)
        start(spool)
        assert spool.export(lambda _: {}, NOW) == 2
        complete(spool)

        def other(moment):
            return {**event("register", producer_kind="helper"), "producer": str(UUID(int=2)),
                    "at": moment.isoformat()}

        monkeypatch.setattr(usage, "SPOOL_BYTES", spool.db.execute("SELECT bytes FROM budget").fetchone()[0])
        with pytest.raises(ValueError, match="full"):
            spool.accept(other(NOW), NOW)
        week = NOW + timedelta(days=8)
        with pytest.raises(ValueError, match="too old"):
            spool.accept(other(week), week)
        late = NOW + timedelta(days=35, seconds=1)
        spool.prune(late)
        assert stored(spool) == [("register", 0), ("start", 0), ("complete", 1)]
        assert spool.export(lambda _: pytest.fail("a held record must not be sent"), late) == 0
        assert spool.held(late) == 1
        body = spool.db.execute("SELECT body FROM packs").fetchone()[0]
        [kept] = [{item["key"]: item["value"] for item in log["attributes"]}
                  for log in json.loads(zlib.decompress(body))]
        assert kept["usage.model"] == {"stringValue": "model-a"}
        assert kept["usage.producer_kind"] == {"stringValue": "chat"}
        monkeypatch.setattr(usage, "SPOOL_BYTES", spool.db.execute("SELECT bytes FROM budget").fetchone()[0])
        spool.accept(other(late), late)
        capsys.readouterr()
        spool.prune(late)
        assert json.loads(capsys.readouterr().err) == {"expired_held_records": 1}
        assert spool.held(late) == 0 and stored(spool) == [("register", 1)]
        assert spool.export(lambda _: {}, late) == 1


def test_sender_compresses_and_spaces_requests(monkeypatch):
    bodies, pauses = [], []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            bodies.append((self.headers["Content-Encoding"],
                           self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_):
            pass

    monkeypatch.setattr(usage.time, "sleep", pauses.append)
    with ThreadingHTTPServer(("127.0.0.1", 0), Receiver) as server:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        send = usage.sender(f"http://127.0.0.1:{server.server_port}/v1/logs")
        payload = usage.batch([{"body": {"stringValue": "Model request metadata"}}])
        assert send(payload) == send(payload) == {}
        server.shutdown()
    assert [(encoding, json.loads(gzip.decompress(body))) for encoding, body in bodies] \
        == [("gzip", payload)] * 2
    assert len(pauses) == 1 and 0 <= pauses[0] <= usage.JITTER


def test_spool_refuses_records_beyond_its_age_and_payload_bounds(tmp_path, monkeypatch):
    with usage.Spool(tmp_path / "spool.sqlite") as spool:
        register(spool)
        week = NOW + timedelta(days=7)
        spool.accept(event("checkpoint", sequence=0, at=week.isoformat()), week)
        late = week + timedelta(microseconds=1)
        with pytest.raises(ValueError, match="too old"):
            spool.accept(event("checkpoint", 2, sequence=0, at=late.isoformat()), late)
        spool.export(lambda _: {}, late)
        spool.accept(event("checkpoint", 2, sequence=0, at=late.isoformat()), late)
        size = spool.db.execute("SELECT bytes FROM budget").fetchone()[0]
        monkeypatch.setattr(usage, "SPOOL_BYTES", size)
        spool.accept(event("checkpoint", 3, sequence=0, at=late.isoformat()), late)
        with pytest.raises(ValueError, match="full"):
            start(spool, now=late, at=late.isoformat())
        assert spool.db.execute("SELECT bytes FROM budget").fetchone()[0] == size
        assert stored(spool) == [("register", 0), ("checkpoint", 1)]


def test_a_spool_at_its_page_limit_still_acknowledges_open_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "SPOOL_PAGES", 120)
    monkeypatch.setattr(usage, "SPOOL_SPARE", 40)
    with usage.Spool(tmp_path / "spool.sqlite") as spool:
        spool.db.execute("PRAGMA max_page_count=120")
        register(spool)
        number = 0
        with pytest.raises(ValueError, match="full"):
            while True:
                number += 1
                start(spool, number)
        assert spool.export(lambda _: {}, NOW) == number
        assert stored(spool) == [("register", 0)] + [("start", 0)] * (number - 1)


def test_export_drains_a_high_water_snapshot_in_bounded_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "BATCH", 2)
    monkeypatch.setattr(usage, "BATCHES", 2)
    with usage.Spool(tmp_path / "spool.sqlite") as spool:
        register(spool)
        for number in (1, 2):
            start(spool, number)
            complete(spool, number)
        sizes = []

        def send(batch):
            sizes.append(len(logs(batch)))
            if len(sizes) == 1:
                start(spool, 3)
            return {}

        assert spool.export(send, NOW) == 4
        assert spool.export(send, NOW) == 2
        assert sizes == [2, 2, 2]
        assert spool.export(send, NOW) == 0


def test_spool_writers_wait_for_a_long_transaction_instead_of_failing_busy(tmp_path):
    path = tmp_path / "spool.sqlite"
    ready, go, outcome = threading.Event(), threading.Event(), []

    def collector():
        with usage.Spool(path) as waiter:
            waiter.db.execute("PRAGMA busy_timeout=50")
            ready.set()
            go.wait()
            outcome.append(waiter.accept(event("start", sequence=1, provider="example",
                                               model="model-a"), NOW))

    with usage.Spool(path) as holder:
        register(holder)
        thread = threading.Thread(target=collector)
        thread.start()
        ready.wait()
        with holder.locked():
            holder.db.execute("BEGIN IMMEDIATE")
            go.set()
            thread.join(0.3)
            assert thread.is_alive()
            holder.db.commit()
        thread.join()
    assert outcome == [{"accepted": True, "duplicate": False}]


def test_spool_cli_keeps_no_history_and_never_opens_the_ledger():
    mount = next((path for path in ROOT.parents if path.is_mount() and path != Path("/")), None)
    if mount is None:
        pytest.skip("needs a separate mounted worktree")
    with tempfile.TemporaryDirectory(prefix=".usage-spool-", dir=ROOT) as temporary:
        data = Path(temporary) / "usage"

        def cli(*command, stdin=""):
            return subprocess.run([sys.executable, str(ROOT / "scripts/usage.py"), "--data-dir",
                                   str(data), "--mount", str(mount), "--store", "spool", *command],
                                  input=stdin, capture_output=True, text=True)

        assert cli("report").returncode == 1 and not data.exists()
        record = {**event("register", producer_kind="chat"), "at": datetime.now(UTC).isoformat()}
        accepted = cli("collect", stdin=json.dumps(record) + "\n")
        assert json.loads(accepted.stdout) == {"accepted": True, "duplicate": False}
        assert sorted(path.name for path in data.iterdir()) == [
            "spool.lock", "spool.sqlite", "spool.sqlite-shm", "spool.sqlite-wal"]
        assert {oct(path.stat().st_mode & 0o777) for path in data.iterdir()} == {"0o600"}
