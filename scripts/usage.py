#!/usr/bin/env python3
"""Collect allowlisted model-request metadata in a 35-day ledger or a bounded retry spool."""

import argparse
import fcntl
import ipaddress
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

RETENTION = timedelta(days=35)
BATCH, BATCHES = 100, 50
SPOOL_BYTES, SPOOL_AGE = 64 * 1024 * 1024, timedelta(days=7)
SPOOL_PAGES, SPOOL_SPARE = 32768, 256
TRANSIENT = ("complete", "checkpoint", "gap")
PACIFIC = ZoneInfo("America/Los_Angeles")
TOKENS = ("input", "cache_read", "cache_write", "output", "reasoning")
COMMON = {"schema", "kind", "producer", "event", "at"}
FIELDS = {
    "register": {"producer_kind"},
    "start": {"sequence", "provider", "model"},
    "complete": {"sequence", "outcome", "usage_present", "input_basis", *TOKENS},
    "checkpoint": {"sequence"},
    "shutdown": {"sequence"},
    "gap": {"end", "reason"},
    "retention": set(),
}
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,127}\Z")
DURABLE = """
PRAGMA synchronous=FULL;
PRAGMA secure_delete=ON;
PRAGMA busy_timeout=10000;
"""
TABLES = """
CREATE TABLE IF NOT EXISTS events (
    producer TEXT NOT NULL, event TEXT NOT NULL, kind TEXT NOT NULL,
    sequence INTEGER, at REAL NOT NULL, ingested REAL NOT NULL,
    expires REAL NOT NULL, payload TEXT NOT NULL, total INTEGER, sent REAL,
    sequence_through INTEGER NOT NULL, retired_completions INTEGER NOT NULL,
    request_count INTEGER GENERATED ALWAYS AS
        (CASE WHEN kind='complete' THEN 1 ELSE 0 END) STORED,
    PRIMARY KEY(producer,event,kind)
);
CREATE UNIQUE INDEX IF NOT EXISTS request_sequence ON events(producer,sequence,kind)
    WHERE kind IN ('start','complete');
CREATE UNIQUE INDEX IF NOT EXISTS producer_registration ON events(producer)
    WHERE kind='register';
CREATE INDEX IF NOT EXISTS pending_export ON events(sent,ingested);
CREATE INDEX IF NOT EXISTS completion_calendar ON events(at) WHERE kind='complete';
CREATE INDEX IF NOT EXISTS expiry ON events(expires);
CREATE TABLE IF NOT EXISTS producer_state (
    producer TEXT PRIMARY KEY, sequence_through INTEGER NOT NULL,
    missing_sequences TEXT NOT NULL, retired_completions INTEGER NOT NULL,
    expires REAL NOT NULL
);
"""
SCHEMA = "PRAGMA journal_mode=WAL;" + DURABLE + TABLES
# A rollback journal holds one transaction, so no WAL grows beside the capped database.
SPOOL_SCHEMA = f"""
PRAGMA page_size=4096;
PRAGMA journal_mode=TRUNCATE;
PRAGMA temp_store=MEMORY;
PRAGMA max_page_count={SPOOL_PAGES};
{DURABLE}{TABLES}
CREATE TABLE IF NOT EXISTS budget (bytes INTEGER NOT NULL);
INSERT INTO budget SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM budget);
CREATE TRIGGER IF NOT EXISTS budget_insert AFTER INSERT ON events BEGIN
    UPDATE budget SET bytes=bytes+length(new.payload);
END;
CREATE TRIGGER IF NOT EXISTS budget_delete AFTER DELETE ON events BEGIN
    UPDATE budget SET bytes=bytes-length(old.payload);
END;
"""


def instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid UTC instant")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError("invalid UTC instant")
    return parsed.astimezone(UTC)


def integer(value, minimum=0):
    if type(value) is not int or not minimum <= value <= 2**53 - 1:
        raise ValueError("invalid metadata number")
    return value


def _validate_envelope(event):
    if not isinstance(event, dict) or event.get("kind") not in FIELDS:
        raise ValueError("invalid metadata schema")
    if set(event) != COMMON | FIELDS[event["kind"]] or type(event["schema"]) is not int:
        raise ValueError("invalid metadata schema")
    if event["schema"] != 1:
        raise ValueError("unsupported metadata schema")
    for key in ("producer", "event"):
        if not isinstance(event[key], str) or str(UUID(event[key])) != event[key]:
            raise ValueError("invalid private identity")
    instant(event["at"])


def validate(event):
    _validate_envelope(event)
    kind = event["kind"]
    if "sequence" in event:
        integer(event["sequence"], 1 if kind in {"start", "complete"} else 0)
    if kind == "register":
        if event["producer_kind"] not in {"chat", "judgment", "helper"}:
            raise ValueError("invalid producer kind")
    elif kind == "start":
        for key in ("provider", "model"):
            if not isinstance(event[key], str) or not LABEL.fullmatch(event[key]):
                raise ValueError("invalid bounded model metadata")
        if len(event["provider"]) > 64:
            raise ValueError("invalid bounded provider metadata")
    elif kind == "complete":
        if event["outcome"] not in {"success", "error", "aborted", "unknown"}:
            raise ValueError("invalid outcome")
        normalize(event)
    elif kind == "gap":
        if instant(event["end"]) < instant(event["at"]):
            raise ValueError("invalid gap interval")
        if event["reason"] not in {"delivery", "shutdown", "source"}:
            raise ValueError("invalid gap reason")
    return event


def _validate_usage(event):
    if event["usage_present"] is not None and type(event["usage_present"]) is not bool:
        raise ValueError("invalid usage presence")
    for key in TOKENS:
        if event[key] is not None:
            integer(event[key])
    if event["input_basis"] not in {"inclusive", "exclusive", "unknown"}:
        raise ValueError("invalid input basis")
    if event["usage_present"] is not True:
        if event["input_basis"] != "unknown" or any(event[key] is not None for key in TOKENS):
            raise ValueError("missing usage must stay unknown")
    if event["reasoning"] is not None and event["output"] is not None:
        if event["reasoning"] > event["output"]:
            raise ValueError("reasoning exceeds output")


def normalize(event):
    _validate_usage(event)
    uncached = total_input = None
    if event["input_basis"] == "inclusive":
        total_input = event["input"]
        known_cache = sum(event[key] for key in ("cache_read", "cache_write")
                          if event[key] is not None)
        if total_input is not None and known_cache > total_input:
            raise ValueError("cache exceeds inclusive input")
        if all(event[key] is not None for key in ("input", "cache_read", "cache_write")):
            uncached = total_input - event["cache_read"] - event["cache_write"]
    elif event["input_basis"] == "exclusive":
        uncached = event["input"]
        if all(event[key] is not None for key in ("input", "cache_read", "cache_write")):
            total_input = uncached + event["cache_read"] + event["cache_write"]
    if total_input is not None:
        integer(total_input)
    total = None if total_input is None or event["output"] is None else total_input + event["output"]
    if total is not None:
        integer(total)
    return {"uncached_input": uncached, "input_total": total_input, "total": total}


def calendar_bounds(period, snapshot):
    if snapshot.tzinfo is None:
        raise ValueError("calendar snapshot needs a timezone")
    local = snapshot.astimezone(PACIFIC)
    lower = local.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "week":
        lower -= timedelta(days=lower.weekday())
    elif period == "month":
        lower = lower.replace(day=1)
    elif period != "day":
        raise ValueError("invalid calendar period")
    return lower.astimezone(UTC), snapshot.astimezone(UTC)


def _acknowledge_sequence(ranges, sequence):
    for index, (lower, upper) in enumerate(ranges):
        if lower <= sequence <= upper:
            remaining = []
            if lower < sequence:
                remaining.append([lower, sequence - 1])
            if sequence < upper:
                remaining.append([sequence + 1, upper])
            ranges[index:index + 1] = remaining
            return


class Ledger:
    schema = SCHEMA

    def __init__(self, path):
        self.db = sqlite3.connect(path, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(self.schema)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    def locked(self):
        return nullcontext()

    def _admitted(self, event, now):
        pass

    def accept(self, payload, now=None):
        now = now or datetime.now(UTC)
        event = validate(payload)
        if event["kind"] == "retention":
            raise ValueError("retirement metadata belongs to the ledger")
        at = instant(event["at"])
        if not now - RETENTION <= at <= now + timedelta(minutes=5):
            raise ValueError("event outside retention or clock bounds")
        encoded = json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False)
        identity = event["producer"], event["event"], event["kind"]
        self.db.execute("BEGIN IMMEDIATE")
        try:
            previous = self.db.execute(
                "SELECT payload FROM events WHERE producer=? AND event=? AND kind=?", identity
            ).fetchone()
            if previous:
                if previous[0] != encoded:
                    raise ValueError("identity conflict")
                self.db.commit()
                return {"accepted": True, "duplicate": True}
            self._check_transition(event)
            expiry = (max(at, now) + RETENTION).timestamp()
            through, retired = self._track_sequences(event, expiry)
            self.db.execute("INSERT INTO events(producer,event,kind,sequence,at,ingested,expires,"
                            "payload,total,sequence_through,retired_completions) "
                            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                            (*identity, event.get("sequence"), at.timestamp(), now.timestamp(),
                             expiry, encoded,
                             normalize(event)["total"] if event["kind"] == "complete" else None,
                             through, retired))
            self.db.execute("UPDATE events SET expires=max(expires,?) "
                            "WHERE producer=? AND (kind='register' OR "
                            "(kind='start' AND event=?))",
                            (expiry, event["producer"], event["event"]))
            self._admitted(event, now)
            self.db.commit()
        except sqlite3.IntegrityError as error:
            self.db.rollback()
            raise ValueError("identity conflict") from error
        except BaseException:
            self.db.rollback()
            raise
        return {"accepted": True, "duplicate": False}

    def _track_sequences(self, event, expiry):
        producer, kind = event["producer"], event["kind"]
        if kind == "register":
            self.db.execute("INSERT INTO producer_state VALUES(?,0,'[]',0,?)", (producer, expiry))
            return 0, 0
        state = self.db.execute("SELECT * FROM producer_state WHERE producer=?",
                                (producer,)).fetchone()
        through = state["sequence_through"]
        sequence = event.get("sequence", through)
        ranges = json.loads(state["missing_sequences"])
        if kind == "start" and sequence <= through:
            if not any(lower <= sequence <= upper for lower, upper in ranges):
                raise ValueError("identity conflict")
        if sequence > through:
            if ranges and ranges[-1][1] == through:
                ranges[-1][1] = sequence
            else:
                ranges.append([through + 1, sequence])
            through = sequence
        if kind == "complete":
            _acknowledge_sequence(ranges, sequence)
        self.db.execute("UPDATE producer_state SET sequence_through=?,missing_sequences=?,"
                        "expires=max(expires,?) WHERE producer=?",
                        (through, json.dumps(ranges), expiry, producer))
        return through, state["retired_completions"]

    def _check_transition(self, event):
        producer, kind = event["producer"], event["kind"]
        registration = self.db.execute(
            "SELECT at FROM events WHERE producer=? AND kind='register'", (producer,)
        ).fetchone()
        if kind == "register":
            if registration:
                raise ValueError("identity conflict")
            return
        if not registration:
            raise ValueError("producer is not registered")
        if instant(event["at"]).timestamp() < registration["at"]:
            raise ValueError("event precedes registration")
        shutdown = self.db.execute(
            "SELECT at FROM events WHERE producer=? AND kind='shutdown'", (producer,)
        ).fetchone()
        if shutdown and kind != "complete":
            raise ValueError("producer has shut down")
        if kind == "complete":
            start = self.db.execute(
                "SELECT event,at FROM events WHERE producer=? AND sequence=? AND kind='start'",
                (producer, event["sequence"])
            ).fetchone()
            if not start or start["event"] != event["event"]:
                raise ValueError("completion has no matching start")
            if instant(event["at"]).timestamp() < start["at"]:
                raise ValueError("completion precedes start")
        if kind in {"checkpoint", "shutdown"}:
            highest = self.db.execute(
                "SELECT sequence_through FROM producer_state WHERE producer=?",
                (producer,)
            ).fetchone()[0]
            if event["sequence"] < highest:
                raise ValueError("checkpoint regresses sequence")
            latest = self.db.execute(
                "SELECT max(at) FROM events WHERE producer=? AND kind!='retention'",
                (producer,)
            ).fetchone()[0]
            if latest is not None and instant(event["at"]).timestamp() < latest:
                raise ValueError("checkpoint regresses time")

    def coverage(self, now):
        result = []
        registrations = self.db.execute("SELECT payload FROM events WHERE kind='register'")
        for stored in registrations:
            registration = validate(json.loads(stored[0]))
            producer = registration["producer"]
            state = self.db.execute(
                "SELECT "
                "max(CASE WHEN kind IN ('checkpoint','shutdown') THEN at END) AS checkpoint,"
                "sum(kind='shutdown') AS shutdown FROM events WHERE producer=?", (producer,)
            ).fetchone()
            durable = self.db.execute("SELECT * FROM producer_state WHERE producer=?",
                                      (producer,)).fetchone()
            gaps = [validate(json.loads(row[0])) for row in self.db.execute(
                "SELECT payload FROM events WHERE producer=? AND kind='gap'", (producer,))]
            acknowledged = self.db.execute(
                "SELECT event,sequence FROM events WHERE producer=? AND kind='complete' "
                "ORDER BY ingested DESC,rowid DESC LIMIT 1", (producer,)
            ).fetchone()
            checkpoint = (datetime.fromtimestamp(state["checkpoint"], UTC).isoformat()
                          if state["checkpoint"] is not None else registration["at"])
            result.append({"producer": producer, "producer_kind": registration["producer_kind"],
                           "registered": registration["at"],
                           "checkpoint": checkpoint, "through": durable["sequence_through"],
                           "missing_sequences": json.loads(durable["missing_sequences"]),
                           "retired_completions": durable["retired_completions"],
                           "last_acknowledged_event": acknowledged["event"] if acknowledged else None,
                           "last_acknowledged_sequence": acknowledged["sequence"] if acknowledged else None,
                           "gap_intervals": len(gaps), "gaps": gaps,
                           "shutdown": bool(state["shutdown"]),
                           "retained_from": (now - RETENTION).isoformat()})
        return result

    def summary(self, lower, upper, now=None):
        now = now or datetime.now(UTC)
        with self.db:
            self.db.execute("BEGIN")
            totals = self.db.execute(
                "SELECT count(*) AS requests,sum(total) AS tokens,count(*)-count(total) AS unknown "
                "FROM events WHERE kind='complete' AND at>=? AND at<?",
                (lower.timestamp(), upper.timestamp())
            ).fetchone()
            coverage = self.coverage(now)
            partial = lower < now - RETENTION or not coverage or any(
                instant(row["registered"]) > lower
                or instant(row["checkpoint"]) < upper or row["missing_sequences"]
                or any(instant(gap["at"]) < upper and instant(gap["end"]) > lower
                       for gap in row["gaps"])
                for row in coverage
            )
            return {"requests": totals["requests"], "counted_tokens": totals["tokens"],
                    "unknown_tokens": totals["unknown"], "partial": bool(partial),
                    "basis": "declared model-request completions; not human submissions",
                    "estimated_cost_usd": None, "verified_billing_usd": None,
                    "lower": lower.isoformat(), "upper": upper.isoformat(), "coverage": coverage}

    def prune(self, now=None):
        now = now or datetime.now(UTC)
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            retired = self.db.execute(
                "SELECT producer,count(*) FROM events WHERE expires<? AND kind='complete' "
                "GROUP BY producer", (now.timestamp(),)).fetchall()
            for producer, count in retired:
                self.db.execute("UPDATE producer_state SET retired_completions="
                                "retired_completions+? WHERE producer=?", (count, producer))
                state = self.db.execute("SELECT * FROM producer_state WHERE producer=?",
                                        (producer,)).fetchone()
                if state and state["expires"] >= now.timestamp():
                    self._retirement_snapshot(producer, state, now)
            result = self.db.execute("DELETE FROM events WHERE expires < ?", (now.timestamp(),))
            self.db.execute("DELETE FROM producer_state WHERE expires<?", (now.timestamp(),))
        if result.rowcount:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return result.rowcount

    def _retirement_snapshot(self, producer, state, now):
        event_id = str(uuid4())
        payload = {"schema": 1, "kind": "retention", "producer": producer,
                   "event": event_id, "at": now.isoformat()}
        encoded = json.dumps(validate(payload), sort_keys=True, separators=(",", ":"))
        expiry = (now + RETENTION).timestamp()
        self.db.execute("INSERT INTO events(producer,event,kind,at,ingested,expires,payload,"
                        "sequence_through,retired_completions) VALUES(?,?,'retention',?,?,?,?,?,?)",
                        (producer, event_id, now.timestamp(), now.timestamp(), expiry, encoded,
                         state["sequence_through"], state["retired_completions"]))
        self.db.execute("UPDATE producer_state SET expires=max(expires,?) WHERE producer=?",
                        (expiry, producer))
        self.db.execute("UPDATE events SET expires=max(expires,?) "
                        "WHERE producer=? AND kind='register'", (expiry, producer))

    def export(self, send, now=None):
        now = now or datetime.now(UTC)
        exported = 0
        with self.locked():
            high = self.db.execute("SELECT coalesce(max(rowid),0) FROM events").fetchone()[0]
        for _ in range(BATCHES):
            with self.locked():
                pending = self.db.execute("SELECT rowid,* FROM events WHERE sent IS NULL AND expires>=? "
                                          "AND rowid<=? ORDER BY ingested,rowid LIMIT ?",
                                          (now.timestamp(), high, BATCH)).fetchall()
                logs = [self._log_record(row) for row in pending]
            if not pending:
                break
            acknowledged(send({"resourceLogs": [{"resource": {"attributes": [
                {"key": "service.name", "value": {"stringValue": "crewship-usage"}}]},
                "scopeLogs": [{"scope": {"name": "crewship.usage", "version": "1"},
                               "logRecords": logs}]}]}))
            with self.locked():
                self._acknowledged(pending, now)
            exported += len(pending)
        return exported

    def _acknowledged(self, rows, now):
        with self.db:
            self.db.executemany("UPDATE events SET sent=? WHERE producer=? AND event=? AND kind=?",
                                [(now.timestamp(), row["producer"], row["event"], row["kind"])
                                 for row in rows])

    def _log_record(self, stored):
        event = validate(json.loads(stored["payload"]))
        metadata = {**event, "ingested": stored["ingested"],
                    "sequence_through": integer(stored["sequence_through"]),
                    "retired_completions": integer(stored["retired_completions"])}
        registration = self.db.execute(
            "SELECT payload FROM events WHERE producer=? AND kind='register'",
            (event["producer"],)
        ).fetchone()
        if registration:
            source = validate(json.loads(registration[0]))
            metadata.update(producer_kind=source["producer_kind"],
                            registered=instant(source["at"]).timestamp())
        if event["kind"] == "complete":
            start = self.db.execute(
                "SELECT payload FROM events WHERE producer=? AND event=? AND kind='start'",
                (event["producer"], event["event"])
            ).fetchone()
            if start:
                started = validate(json.loads(start[0]))
                metadata.update(provider=started["provider"], model=started["model"],
                                started=instant(started["at"]).timestamp())
            metadata.update(normalize(event), request_count=1)
        metadata["at"] = instant(event["at"]).timestamp()
        delta = instant(event["at"]) - datetime(1970, 1, 1, tzinfo=UTC)
        metadata["at_us"] = ((delta.days * 86400 + delta.seconds) * 1_000_000
                             + delta.microseconds)
        if "end" in metadata:
            metadata["end"] = instant(metadata["end"]).timestamp()
        attributes = []
        for key, value in metadata.items():
            if value is None:
                continue
            if type(value) is bool:
                field = {"boolValue": value}
            elif type(value) is int:
                field = {"intValue": str(value)}
            elif type(value) is float:
                field = {"doubleValue": value}
            else:
                field = {"stringValue": value}
            attributes.append({"key": f"usage.{key}", "value": field})
        retention_time = max(metadata["at"], stored["ingested"])
        return {"timeUnixNano": str(round(retention_time * 1_000_000) * 1000),
                "observedTimeUnixNano": str(round(stored["ingested"] * 1_000_000) * 1000),
                "body": {"stringValue": "Model request metadata"}, "attributes": attributes}


def acknowledged(reply):
    if not isinstance(reply, dict) or set(reply) - {"partialSuccess"}:
        raise ValueError("invalid export acknowledgement")
    partial = reply.get("partialSuccess", {})
    if (not isinstance(partial, dict)
            or set(partial) - {"rejectedLogRecords", "errorMessage"}):
        raise ValueError("invalid export acknowledgement")
    rejected = partial.get("rejectedLogRecords", 0)
    if type(rejected) is bool or rejected not in (0, "0"):
        raise ValueError("export rejected metadata records")
    if partial.get("errorMessage"):
        raise ValueError("export returned a partial acknowledgement")


class Spool(Ledger):
    """Keep unexported metadata plus the registrations and starts that later records need."""

    schema = SPOOL_SCHEMA

    def __init__(self, path):
        self.lock = os.open(Path(path).with_suffix(".lock"),
                            os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        with self.locked():
            super().__init__(path)

    def __exit__(self, *_):
        super().__exit__()
        os.close(self.lock)

    @contextmanager
    def locked(self):
        # SQLite's busy handler polls and can starve a waiter; a blocking flock queues it.
        fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(self.lock, fcntl.LOCK_UN)

    def accept(self, payload, now=None):
        with self.locked():
            return super().accept(payload, now)

    def _admitted(self, event, now):
        if event["kind"] == "checkpoint":
            self.db.execute("DELETE FROM events WHERE producer=? AND kind='checkpoint' "
                            "AND sent IS NULL AND event!=?", (event["producer"], event["event"]))
        oldest, size, used = self.db.execute(
            "SELECT (SELECT min(ingested) FROM events WHERE sent IS NULL),(SELECT bytes FROM budget),"
            "(SELECT page_count FROM pragma_page_count())"
            "-(SELECT freelist_count FROM pragma_freelist_count())").fetchone()
        if oldest < (now - SPOOL_AGE).timestamp():
            raise ValueError("retry spool is too old")
        # Collectors stop short of max_page_count: an acknowledgement also needs free pages.
        if size > SPOOL_BYTES or used > SPOOL_PAGES - SPOOL_SPARE:
            raise ValueError("retry spool is full")

    def _acknowledged(self, rows, now):
        done = [(row["producer"], row["event"], row["kind"]) for row in rows
                if row["kind"] in TRANSIENT]
        with self.db:
            self.db.executemany("DELETE FROM events WHERE producer=? AND event=? AND kind=?", done)
            self.db.executemany("UPDATE events SET sent=? WHERE producer=? AND event=? AND kind=?",
                                [(now.timestamp(), row["producer"], row["event"], row["kind"])
                                 for row in rows if row["kind"] not in TRANSIENT])
            self.db.executemany("DELETE FROM events WHERE producer=? AND event=? AND kind='start' "
                                "AND sent IS NOT NULL",
                                [identity[:2] for identity in done if identity[2] == "complete"])

    def prune(self, now=None):
        now = (now or datetime.now(UTC)).timestamp()
        with self.locked(), self.db:
            self.db.execute("BEGIN IMMEDIATE")
            removed = self.db.execute("DELETE FROM events WHERE sent IS NOT NULL AND expires<?",
                                      (now,)).rowcount
            self.db.execute("DELETE FROM producer_state WHERE expires<?", (now,))
        return removed


def configured_data_dir(data_dir, mount):
    mount, data_dir = Path(mount), Path(data_dir)
    if not mount.is_absolute() or not data_dir.is_absolute() or ".." in data_dir.parts:
        raise ValueError("use absolute configured data_dir and mount paths")
    mount = mount.resolve(strict=True)
    if (mount == Path("/") or not os.path.ismount(mount)
            or mount.stat().st_dev == Path("/").stat().st_dev):
        raise ValueError("configured data mount is missing or root-backed")
    resolved = data_dir.resolve()
    if not resolved.is_relative_to(mount) or resolved == mount:
        raise ValueError("data_dir must stay below the configured data mount")
    existing = resolved
    while not existing.exists():
        existing = existing.parent
    if existing.stat().st_dev != mount.stat().st_dev:
        raise ValueError("data_dir is not on the configured data mount")
    return resolved


def data_path(data_dir, mount, name):
    directory = configured_data_dir(data_dir, mount)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / name
    if path.is_symlink():
        raise ValueError("metadata storage must not be a symlink")
    return path


def sender(endpoint):
    url = urlsplit(endpoint)
    if url.username or url.password or url.query or url.fragment or not url.hostname:
        raise ValueError("invalid OTLP endpoint")
    if url.scheme != "https":
        try:
            loopback = ipaddress.ip_address(url.hostname).is_loopback
        except ValueError:
            loopback = False
        if url.scheme != "http" or not loopback:
            raise ValueError("use HTTPS for a remote OTLP endpoint")
    headers = {"Content-Type": "application/json"}
    if key := os.environ.get("SIGNOZ_INGESTION_KEY"):
        headers["signoz-ingestion-key"] = key

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_):
            return None

    opener = urllib.request.build_opener(NoRedirect)

    def send(payload):
        request = urllib.request.Request(endpoint, json.dumps(payload).encode(), headers)
        with opener.open(request, timeout=15) as response:
            if response.status != 200:
                raise ValueError("export has no success acknowledgement")
            return json.loads(response.read(65537))

    return send


def collect(ledger):
    ledger.prune()
    next_prune = time.monotonic() + 3600
    while line := sys.stdin.buffer.readline(16385):
        if time.monotonic() >= next_prune:
            ledger.prune()
            next_prune = time.monotonic() + 3600
        if len(line) > 16384:
            raise ValueError("metadata record exceeds the size limit")
        payload = json.loads(line)
        print(json.dumps(ledger.accept(payload)), flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--mount", required=True)
    parser.add_argument("--store", choices=("ledger", "spool"), default="ledger",
                        help="spool keeps only unexported metadata in a bounded retry buffer")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("collect")
    commands.add_parser("prune")
    commands.add_parser("check")
    report = commands.add_parser("report")
    report.add_argument("--period", choices=("day", "week", "month"), default="day")
    report.add_argument("--at", type=instant)
    export = commands.add_parser("export")
    export.add_argument("--endpoint", required=True, help="full authorized OTLP /v1/logs URL")
    args = parser.parse_args(argv)
    if args.command == "check":
        configured_data_dir(args.data_dir, args.mount)
        print(json.dumps({"mounted": True}))
        return
    spool = args.store == "spool"
    if spool and args.command == "report":
        raise ValueError("the retry spool keeps no local history")
    os.umask(0o077)
    path = data_path(args.data_dir, args.mount, "spool.sqlite" if spool else "usage.sqlite")
    with (Spool if spool else Ledger)(path) as ledger:
        if args.command not in {"prune", "collect"}:
            ledger.prune()
        if args.command == "collect":
            collect(ledger)
        elif args.command == "prune":
            print(json.dumps({"removed": ledger.prune()}))
        elif args.command == "report":
            bounds = calendar_bounds(args.period, args.at or datetime.now(UTC))
            print(json.dumps(ledger.summary(*bounds)))
        else:
            print(json.dumps({"exported": ledger.export(sender(args.endpoint))}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, KeyError, TypeError):
        print("usage: metadata operation failed; check the schema, identity, mount, and endpoint",
              file=sys.stderr)
        sys.exit(1)
