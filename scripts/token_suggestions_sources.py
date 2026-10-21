"""Read existing metadata without opening a writable usage client."""

import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from usage import normalize

MIB = 1024 * 1024
PACIFIC = ZoneInfo("America/Los_Angeles")
OMP_MAX_ENTRIES = 8192
OMP_MAX_FILES = 256
OMP_MAX_BYTES = 128 * MIB
OMP_MAX_FILE_BYTES = 16 * MIB
OMP_MAX_LINE_BYTES = 2 * MIB
OMP_MAX_RECORDS = 100_000
OMP_SECONDS = 15
DETECTORS = ("Repeated context", "Large tool outputs", "Retry loops", "Cache inefficiency")
ACTIONS = (
    "Review whether a short reference can replace the repeated context.",
    "Review narrower reads or quieter commands. Size alone does not prove waste.",
    "Review the first failure before another call. Normalized calls can have different arguments.",
    "Review cache eligibility for the same model. Cache reuse changes pricing, not input token count.",
)


def number(value):
    if type(value) is not int or not 0 <= value <= 2**53 - 1:
        raise ValueError("invalid metadata number")
    return value


def instant(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("missing time zone")
    return parsed.astimezone(UTC)


def windows(cutoff):
    end = cutoff.astimezone(PACIFIC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    return tuple(d.astimezone(UTC) for d in (start - timedelta(days=7), start, end))


def read_json(path, limit=MIB):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("source is not a regular file")
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("source exceeds limit")
    return json.loads(raw)


def normalized_input(present, basis, value, read, write):
    if present is not None and (type(present) is not int or present not in (0, 1)):
        raise ValueError("invalid usage presence")
    return normalize({"usage_present": None if present is None else bool(present),
                      "input_basis": basis, "input": value, "cache_read": read,
                      "cache_write": write, "output": None, "reasoning": None})["input_total"]


# Both result sets are aggregates. Private producer and event keys stay inside SQLite.
CACHE_SQL = """
WITH records AS (
    SELECT producer,event,kind,at,payload FROM events
    WHERE at >= :history AND at < :end
    GROUP BY producer,event,kind
), starts AS (
    SELECT producer,event,min(payload) AS payload FROM events WHERE kind='start'
    GROUP BY producer,event
), completions AS (
    SELECT c.at, c.payload,
           json_extract(s.payload,'$.provider') AS provider,
           json_extract(s.payload,'$.model') AS model,
           normalized_input(json_extract(c.payload,'$.usage_present'),
               json_extract(c.payload,'$.input_basis'),json_extract(c.payload,'$.input'),
               json_extract(c.payload,'$.cache_read'),
               json_extract(c.payload,'$.cache_write')) AS input_total,
           json_extract(c.payload,'$.cache_read') AS cache_read,
           json_extract(c.payload,'$.cache_write') AS cache_write
    FROM records c LEFT JOIN starts s
      ON c.producer=s.producer AND c.event=s.event
    WHERE c.kind='complete'
), comparable AS (
    SELECT *, input_total IS NOT NULL AND cache_read IS NOT NULL AND cache_write IS NOT NULL
              AND provider IS NOT NULL AND model IS NOT NULL AS known
    FROM completions
)
SELECT at >= :start AS current, provider,model,count(*) AS requests,
       sum(NOT known) AS excluded,
       sum(CASE WHEN known THEN input_total END) AS input_total,
       sum(CASE WHEN known THEN cache_read END) AS cache_read,
       sum(CASE WHEN known THEN cache_write END) AS cache_write
FROM comparable GROUP BY current,provider,model
"""
COVERAGE_SQL = """
WITH records AS (
    SELECT producer,event,kind,sequence,at,payload,retired_completions
    FROM events GROUP BY producer,event,kind
), periods AS (SELECT 0 AS current,:history AS lower,:start AS upper
               UNION ALL SELECT 1,:start,:end),
producers AS (
    SELECT periods.current, e.producer,
           min(CASE WHEN kind='register' THEN at END) AS registered,
           max(CASE WHEN kind IN ('checkpoint','shutdown') THEN at END) AS checkpoint,
           coalesce(max(CASE WHEN kind IN ('start','complete','checkpoint','shutdown')
                        THEN sequence END),0) AS through,
           max(retired_completions) AS retired,
           count(DISTINCT CASE WHEN kind='complete'
                                OR (kind='start' AND at>=upper)
                               THEN sequence END) AS accounted
    FROM records e CROSS JOIN periods GROUP BY periods.current,e.producer
    HAVING registered IS NULL OR registered<upper
)
SELECT p.current,
       (SELECT count(*) FROM producers WHERE current=p.current) AS producers,
       (SELECT count(*) FROM producers WHERE current=p.current AND
        (registered IS NULL OR registered>p.lower OR checkpoint IS NULL
         OR checkpoint<p.upper OR through-retired-accounted != 0)) AS incomplete,
       (SELECT count(*) FROM records WHERE kind='gap' AND at<p.upper
        AND julianday(json_extract(payload,'$.end'))>julianday(p.lower,'unixepoch')) AS gaps,
       (SELECT count(*) FROM records WHERE kind='shutdown' AND at>=p.lower AND at<p.upper) AS shutdowns,
       (SELECT count(*) FROM records WHERE json_extract(payload,'$.schema') IS NOT 1) AS unsupported,
       (SELECT count(*) FROM (SELECT 1 FROM events GROUP BY producer,event,kind
                              HAVING count(DISTINCT payload)>1)) AS conflicts
FROM periods p
"""


def bounded_rows(cursor, remaining):
    rows = []
    for row in cursor:
        row = dict(row)
        remaining -= len(json.dumps(row).encode())
        if remaining < 0:
            raise ValueError("aggregate response exceeds limit")
        rows.append(row)
    return rows, remaining


def read_ledger(path, bounds):
    params = dict(zip(("history", "start", "end"), (t.timestamp() for t in bounds)))
    deadline = time.monotonic() + 20
    with sqlite3.connect(Path(path).absolute().as_uri() + "?mode=ro", uri=True,
                         timeout=0.2) as db:
        db.execute("PRAGMA query_only=ON")
        db.row_factory = sqlite3.Row
        db.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
        if db.execute("SELECT name FROM sqlite_master WHERE name='packs'").fetchone():
            raise ValueError("retry spool is not history")
        db.create_function("normalized_input", 5, normalized_input, deterministic=True)
        db.execute("BEGIN")
        rows, remaining = bounded_rows(db.execute(CACHE_SQL, params), 2 * MIB)
        deadline = time.monotonic() + 20
        coverage, _ = bounded_rows(db.execute(COVERAGE_SQL, params), remaining)
    if any(row["unsupported"] or row["conflicts"] for row in coverage):
        raise ValueError("unsupported or conflicting metadata")
    for row in coverage:
        row["partial"] = bool(not row["producers"] or row["incomplete"] or row["gaps"]
                              or row["shutdowns"])
    return rows, coverage


def candidate(detector, key, window, source, tokens, basis, signal, partial=True):
    return {"detector": detector, "key": key, "window": window, "source": source,
            "tokens": tokens, "basis": basis, "signal": signal, "partial": partial}


def tool_shape_counts(shape, tokens):
    if not isinstance(shape, dict):
        raise ValueError("invalid tool shape")
    calls = number(shape["calls"])
    size = number(shape["tokens"])
    largest = number(shape["largest_call"])
    errors = shape.get("error_calls")
    if errors is not None:
        errors = number(errors)
    if (errors is not None and errors > calls) or largest > size or size > tokens:
        raise ValueError("invalid output counters")
    return {"calls": calls, "tokens": size, "largest_call": largest, "error_calls": errors}


def tool_counts(evidence):
    tokens = number(evidence["tool_output_tokens"])
    if evidence["signature_token_basis"] != "estimated_local":
        raise ValueError("unsupported output basis")
    shapes = evidence["top_signatures"]
    if not isinstance(shapes, list):
        raise ValueError("invalid output evidence")
    return tokens, [tool_shape_counts(shape, tokens) for shape in shapes]


def read_sink(sink, window, source, partial):
    if not isinstance(sink, dict):
        raise ValueError("invalid saved finding")
    key = sink["sink_id"]
    if not isinstance(key, str) or len(key) > 2048:
        raise ValueError("invalid finding key")
    evidence = sink.get("evidence", {})
    if not isinstance(evidence, dict):
        raise ValueError("invalid saved evidence")
    if key.startswith("recurring_context:repaste:"):
        sessions = number(evidence["recurrence_sessions"])
        calls = number(evidence["occurrences_total"])
        block = number(evidence["block_tokens"])
        tokens = number(evidence["occurrence_tokens_total"])
        if sessions < 3 or calls < sessions or block < 180 or tokens < block:
            raise ValueError("invalid repeated context evidence")
        return candidate(0, key, window, source, tokens, "repeated-context local estimate",
                         f"{sessions} sessions; {calls} occurrences; largest block {block} tokens.",
                         partial)
    if key == "tool_output_portfolio":
        tokens, shapes = tool_counts(evidence)
        row = candidate(1, key, window, source, tokens, "estimated_local",
                        f"{len(shapes)} measured tool shapes; raw signatures omitted.", partial)
        row["tool_shapes"] = shapes
        return row
    if key.startswith("learning_loop:error_loop:"):
        return retry_candidate(sink, evidence, window, source, partial)
    return None


def retry_candidate(sink, evidence, window, source, partial):
    calls = number(evidence["calls"])
    floor = number(evidence["observed_output_token_floor"])
    tokens = sink.get("tokens_observed")
    if tokens is not None:
        tokens = number(tokens)
    if (calls < 3 or (tokens is not None and tokens != floor)
            or evidence["tokens_observed_basis"] != "bytes4_estimate"):
        raise ValueError("invalid retry evidence")
    row = candidate(2, sink["sink_id"], window, source, tokens, "bytes4_estimate",
                    f"{calls} normalized calls; at least half failed. Exact failure count unknown.",
                    partial)
    row["observed_output_token_floor"] = floor
    return row


def confirmed_measurements(records):
    confirmed = []
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("attribution", {}), dict):
            raise ValueError("invalid saved attribution")
        attribution = row.get("attribution", {})
        # A per-turn artifact re-count is supported, but is never achieved stream savings.
        if (attribution.get("method") == "deterministic_remeasure"
                and attribution.get("provenance") == "intact"
                and row.get("unit") == "config_tokens_per_turn"
                and row.get("verdict") in ("improved", "unchanged", "regressed")
                and number(row["sessions_after"]) >= 3):
            before, after = row["before"], row["after"]
            if any(type(n) not in (int, float) or not 0 <= n <= 2**53 - 1
                   for n in (before, after)):
                raise ValueError("invalid confirmed counters")
            confirmed.append((before, after, number(row["sessions_after"]),
                              instant(row["applied_at"]).isoformat()))
    return confirmed


def snapshot_candidates(sinks, window, source, partial):
    rows, seen = [], {}
    for sink in sinks:
        row = read_sink(sink, window, source, partial)
        if row is None:
            continue
        key = row["detector"], row["key"]
        if key in seen:
            if seen[key] != row:
                raise ValueError("conflicting saved findings")
            continue
        seen[key] = row
        rows.append(row)
    return rows


def metadata_identity(records):
    accepted = [{key: value for key, value in record.items() if key != "source"}
                for record in records]
    return hashlib.sha256(json.dumps(accepted, sort_keys=True).encode()).digest()


def read_snapshot(path, bounds, index):
    data = read_json(path)
    if data["schema"] != "caveman.learn.v1" or data["basis"] != "inferred":
        raise ValueError("unsupported snapshot")
    start, end = (instant(data["window"][key]) for key in ("from", "to"))
    if not bounds[1] <= start < end <= bounds[2]:
        raise ValueError("stale or incompatible snapshot window")
    window = (start.isoformat(), end.isoformat())
    if not isinstance(data["caveats"], list) or not isinstance(data["sinks"], list):
        raise ValueError("invalid snapshot structure")
    partial = bool(data["caveats"] or start != bounds[1] or end != bounds[2])
    source = f"saved report {index} (configured local reference)"
    rows = snapshot_candidates(data["sinks"], window, source, partial)
    retro = []
    block = data.get("retro")
    if block:
        if block["basis"] != "inferred" or not isinstance(block["families"], list):
            raise ValueError("unsupported retrospective basis")
        for family in block["families"]:
            if family["id"] in ("repeated_blocks", "tool_outputs"):
                retro.append((family["id"], number(family["tokens"])))
    confirmed = confirmed_measurements(data.get("confirmed", []))
    summary = {"source": source, "window": window, "partial": partial,
               "caveats": len(data["caveats"]), "retro": retro, "confirmed": confirmed}
    summary["identity"] = metadata_identity([*rows, summary])
    return rows, summary


def omp_deadline(deadline):
    if time.monotonic() >= deadline:
        raise ValueError("omp source deadline")


@contextmanager
def omp_directory(root_fd, parts, deadline):
    fd = os.dup(root_fd)
    try:
        for part in parts:
            omp_deadline(deadline)
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def omp_paths(root_fd, lower, deadline, counts):
    paths, directories = [], [()]
    while directories and not counts["limited"]:
        parent = directories.pop()
        with omp_directory(root_fd, parent, deadline) as fd, os.scandir(fd) as entries:
            for entry in entries:
                omp_deadline(deadline)
                counts["entries"] += 1
                if counts["entries"] > OMP_MAX_ENTRIES:
                    counts["limited"] = 1
                    break
                if entry.is_dir(follow_symlinks=False):
                    directories.append((*parent, entry.name))
                elif entry.name.endswith(".jsonl") and entry.is_file(follow_symlinks=False):
                    modified = entry.stat(follow_symlinks=False).st_mtime
                    if modified >= lower.timestamp():
                        paths.append((modified, parent, entry.name))
    paths.sort(reverse=True)
    if len(paths) > OMP_MAX_FILES:
        counts["limited"] = 1
    return paths[:OMP_MAX_FILES]


def omp_records(root_fd, path, deadline, counts):
    _, parent, name = path
    with omp_directory(root_fd, parent, deadline) as fd:
        source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(source_fd, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError("omp source is not a regular file")
        size = 0
        while counts["records"] < OMP_MAX_RECORDS:
            omp_deadline(deadline)
            remaining = min(OMP_MAX_FILE_BYTES - size, OMP_MAX_BYTES - counts["bytes"])
            if remaining <= 0:
                counts["limited"] = 1
                break
            raw = source.readline(min(OMP_MAX_LINE_BYTES, remaining) + 1)
            if not raw:
                break
            counts["bytes"] += len(raw)
            size += len(raw)
            if len(raw) > min(OMP_MAX_LINE_BYTES, remaining) or not raw.endswith(b"\n"):
                counts["limited"] = 1
                break
            counts["records"] += 1
            try:
                record = json.loads(raw)
                if isinstance(record, dict) and record.get("type") not in ("session", "title"):
                    yield record
            except (ValueError, UnicodeError, RecursionError):
                counts["malformed"] += 1
        else:
            counts["limited"] = 1


def omp_text(content):
    if isinstance(content, str):
        yield content
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    yield text


def omp_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).digest()


def omp_cache(message, groups):
    provider, model = message.get("provider"), message.get("model")
    key = omp_digest([provider, model])
    row = groups.setdefault(key, {"current": 1, "provider": key, "model": key,
                                 "requests": 0, "excluded": 0, "input_total": 0,
                                 "cache_read": 0, "cache_write": 0})
    row["requests"] += 1
    usage = message.get("usage")
    try:
        if not isinstance(usage, dict) or not provider or not model:
            raise ValueError("unknown omp usage")
        read, write = number(usage["cacheRead"]), number(usage["cacheWrite"])
        total = normalized_input(1, "exclusive", number(usage["input"]), read, write)
    except (ValueError, KeyError, TypeError):
        row["excluded"] += 1
        return
    row["input_total"] += total
    row["cache_read"] += read
    row["cache_write"] += write


def omp_retry(run, retries):
    if run is not None and run["calls"] >= 3 and run["errors"] * 2 >= run["calls"]:
        retries[id(run)] = run


def omp_retry_groups(retries, deadline):
    covered = {}
    for run in sorted(retries.values(), key=lambda run: -run["calls"]):
        events, link = set(), run["events"]
        while link is not None:
            omp_deadline(deadline)
            event, link = link
            events.add(event)
        if any(events <= group for group in covered.get(run["events"][0], ())):
            continue
        for event in events:
            covered.setdefault(event, []).append(events)
        yield run


def omp_message(record):
    at = instant(record["timestamp"])
    if (not isinstance(record["id"], str)
            or record.get("parentId") is not None and not isinstance(record["parentId"], str)):
        raise ValueError("invalid omp entry identity")
    message = (record["message"] if record.get("type") == "message"
               else {"role": record.get("type")})
    identity = omp_digest(record)
    if not isinstance(message, dict):
        raise ValueError("invalid omp message")
    if message.get("role") == "assistant" and "completedAt" in message:
        at = datetime.fromtimestamp(number(message["completedAt"]) / 1000, UTC)
    texts = tuple(text.encode() for text in omp_text(message.get("content")))
    return at, message, identity, texts


def omp_tool_measure(message, shape, size, tools):
    key = shape or omp_digest(message.get("toolName"))
    tool = tools.setdefault(key, {"calls": 0, "tokens": 0, "largest_call": 0, "error_calls": 0})
    error = message.get("isError")
    tool["calls"] += 1
    tool["tokens"] += size
    tool["largest_call"] = max(tool["largest_call"], size)
    if type(error) is not bool:
        tool["error_calls"] = None
    elif tool["error_calls"] is not None:
        tool["error_calls"] += int(error)


def omp_pending_call(pending, key, deadline):
    while pending is not None:
        omp_deadline(deadline)
        calls, pending = pending
        if key in calls:
            return calls[key]
    return None, None


def omp_tool_result(message, call, run, size, retries, identity):
    shape, batch = call
    error = message.get("isError")
    if (run is None or shape != run["shape"] or shape is None or batch == run["batch"]
            or type(error) is not bool):
        omp_retry(run, retries)
        run = {"shape": shape, "batch": batch, "calls": 0, "errors": 0, "tokens": 0,
               "events": None}
    if shape is not None and type(error) is bool:
        return {"shape": shape, "batch": batch, "calls": run["calls"] + 1,
                "errors": run["errors"] + int(error), "tokens": run["tokens"] + size,
                "events": (identity, run["events"])}
    return run


def omp_context(texts, session, contexts):
    for text in texts:
        size = (len(text) + 3) // 4
        if size >= 180:
            context = contexts.setdefault(hashlib.sha256(text).digest(), {
                "sessions": set(), "calls": 0, "block": size})
            context["sessions"].add(session)
            context["calls"] += 1


def omp_calls(content, identity):
    if not isinstance(content, list):
        return {}
    return {omp_digest(block.get("id")): (
        omp_digest([block.get("name"), block.get("arguments")]), identity)
        for block in content if isinstance(block, dict) and block.get("type") == "toolCall"}


def omp_candidates(contexts, tools, retries, window, deadline):
    sinks = []
    for run in omp_retry_groups(retries, deadline):
        sinks.append({"sink_id": f"learning_loop:error_loop:omp-{len(sinks)}",
                      "tokens_observed": run["tokens"], "evidence": {
                          "calls": run["calls"], "observed_output_token_floor": run["tokens"],
                          "tokens_observed_basis": "bytes4_estimate"}})
    for context in contexts.values():
        if len(context["sessions"]) >= 3:
            sinks.append({"sink_id": f"recurring_context:repaste:omp-{len(sinks)}", "evidence": {
                "recurrence_sessions": len(context["sessions"]),
                "occurrences_total": context["calls"], "block_tokens": context["block"],
                "occurrence_tokens_total": context["calls"] * context["block"]}})
    if tools:
        sinks.append({"sink_id": "tool_output_portfolio", "evidence": {
            "tool_output_tokens": sum(tool["tokens"] for tool in tools.values()),
            "signature_token_basis": "estimated_local",
            "top_signatures": sorted(tools.values(), key=lambda tool: -tool["tokens"])[:32]}})
    return snapshot_candidates(sinks, window, "omp sessions", True)


def omp_messages(root_fd, path, deadline, counts, end):
    for record in omp_records(root_fd, path, deadline, counts):
        try:
            at, message, identity, texts = omp_message(record)
        except (ValueError, KeyError, TypeError, OverflowError):
            counts["malformed"] += 1
            continue
        if at < end:
            yield record, at, message, identity, texts


def omp_apply(entry, state, session, start, counts, observations):
    contexts, tools, cache, seen, retries, deadline = observations
    record, at, message, identity, texts = entry
    pending, run = state
    current = at >= start
    observed = current and record["type"] == "message" and identity not in seen
    if observed:
        seen.add(identity)
        counts["messages"] += 1
    role = message.get("role")
    if role in ("user", "developer", "reset_boundary", "compaction", "branch_summary"):
        omp_retry(run, retries)
        pending, run = None, None
        if observed:
            omp_context(texts, session, contexts)
    elif role == "assistant":
        pending = (omp_calls(message.get("content"), identity), pending)
        if observed:
            omp_cache(message, cache)
    elif role == "toolResult":
        key = omp_digest(message.get("toolCallId"))
        call = omp_pending_call(pending, key, deadline)
        pending = ({key: (None, None)}, pending)
        if current:
            size = sum((len(text) + 3) // 4 for text in texts)
            run = omp_tool_result(message, call, run, size, retries, identity)
            if observed:
                omp_tool_measure(message, run["shape"], size, tools)
    return pending, run


def read_omp(root, bounds):
    deadline = time.monotonic() + OMP_SECONDS
    counts = dict.fromkeys(("entries", "files", "bytes", "records", "messages",
                           "malformed", "limited"), 0)
    window = tuple(t.isoformat() for t in bounds[1:])
    contexts, tools, cache, seen, retries = {}, {}, {}, set(), {}
    observations = contexts, tools, cache, seen, retries, deadline

    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        paths = omp_paths(root_fd, bounds[1], deadline, counts)
        for session, path in enumerate(paths):
            if counts["bytes"] >= OMP_MAX_BYTES or counts["records"] >= OMP_MAX_RECORDS:
                counts["limited"] = 1
                break
            counts["files"] += 1
            states, leaves = {}, set()
            for entry in omp_messages(root_fd, path, deadline, counts, bounds[2]):
                record = entry[0]
                key, parent = record["id"], record.get("parentId")
                states[key] = omp_apply(
                    entry, states.get(parent, (None, None)), session, bounds[1], counts, observations)
                leaves.discard(parent)
                leaves.add(key)
            for leaf in leaves:
                omp_retry(states[leaf][1], retries)
    finally:
        os.close(root_fd)
    rows = omp_candidates(contexts, tools, retries, window, deadline)
    return rows, list(cache.values()), counts
