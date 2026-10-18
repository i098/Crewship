#!/usr/bin/env python3
"""Render the SigNoz v6 custom dashboard without contacting a service."""

import argparse
import json
from pathlib import Path

# SigNoz logs v2 stores numeric metadata in Float64 maps.
# Private identities exist only in the inner log deduplication query.
COVERAGE_BALANCE = "through - retired - completed_count"
DEDUP = """WITH records AS (
    SELECT attributes_string['usage.producer'] AS producer,
           attributes_string['usage.event'] AS event,
           attributes_string['usage.kind'] AS kind,
           any(toUInt64(attributes_number['usage.at_us'])) * 1000 AS completed_ns,
           any(attributes_string) AS strings,
           any(attributes_number) AS numbers,
           any(attributes_bool) AS flags
    FROM signoz_logs.distributed_logs_v2
    WHERE scope_name = 'crewship.usage'
      AND resource.service.name::String = 'crewship-usage'
      AND attributes_number['usage.schema'] = toFloat64(1)
      AND ts_bucket_start >= toUnixTimestamp(now()) - 35 * 86400 - 1800
      AND timestamp >= toUnixTimestamp64Nano(now64(9) - INTERVAL 35 DAY)
      AND timestamp < toUnixTimestamp64Nano(now64(9))
      {records_filter}
    GROUP BY producer, event, kind
), completions AS (
    SELECT *, if(mapContains(numbers, 'usage.total'),
                 toNullable(numbers['usage.total']), NULL) AS tokens
    FROM records WHERE kind = 'complete'
), producers AS (
    SELECT producer, any(strings['usage.producer_kind']) AS producer_kind,
           min(numbers['usage.registered']) AS registered,
           max(numbers['usage.sequence_through']) AS through,
           maxIf(numbers['usage.at'], kind IN ('checkpoint', 'shutdown')) AS checkpoint,
           uniqExactIf(numbers['usage.sequence'], kind = 'complete') AS completed_count,
           max(numbers['usage.retired_completions']) AS retired,
           countIf(kind = 'gap') AS gaps,
           countIf(kind = 'shutdown') AS shutdowns
    FROM records GROUP BY producer
), coverage AS (
    SELECT *, {coverage_balance} AS missing
    FROM producers
)
"""
SELECTED = "completed_ns >= $start_timestamp_nano AND completed_ns < $end_timestamp_nano"
CLOSED = (
    "completed_ns >= intDiv($start_timestamp_nano + 59999999999, 60000000000) * 60000000000 "
    "AND completed_ns < intDiv($end_timestamp_nano, 60000000000) * 60000000000"
)
END = "fromUnixTimestamp64Nano(toInt64($end_timestamp_nano))"
LOCAL_END = f"toTimeZone({END}, 'America/Los_Angeles')"
EVENT_WINDOW = (
    "AND attributes_string['usage.kind'] = 'complete' "
    "AND ts_bucket_start >= intDiv($start_timestamp_nano, 1000000000) - 1800 "
    "AND timestamp >= $start_timestamp_nano "
    "AND toUInt64(attributes_number['usage.at_us']) * 1000 >= $start_timestamp_nano "
    "AND toUInt64(attributes_number['usage.at_us']) * 1000 < $end_timestamp_nano"
)


def panel(name, query=None, visualization="TablePanel", description="", records_filter=""):
    queries = [] if query is None else [{
        "kind": "time_series" if visualization == "TimeSeriesPanel" else "scalar",
        "spec": {"name": "A", "plugin": {"kind": "signoz/ClickHouseSQL",
                  "spec": {"name": "A", "query": DEDUP.format(
                      records_filter=records_filter, coverage_balance=COVERAGE_BALANCE) + query,
                           "disabled": False}}},
    }]
    return {"kind": "Panel", "spec": {
        "display": {"name": name, "description": description},
        "plugin": {"kind": f"signoz/{visualization}", "spec": {}}, "queries": queries,
    }}


def calendar_query():
    periods = {"Today": f"toStartOfDay({LOCAL_END})",
               "This week": f"toStartOfWeek({LOCAL_END}, 1)",
               "This month": f"toStartOfMonth({LOCAL_END})"}
    queries = []
    for name, boundary in periods.items():
        lower = f"toUnixTimestamp64Nano(toDateTime64({boundary}, 9, 'America/Los_Angeles'))"
        condition = f"completed_ns >= {lower} AND completed_ns < $end_timestamp_nano"
        queries.append(f"""SELECT '{name}' AS period,
    toString({boundary}) AS pacific_start,
    if(count() = 0, NULL, toNullable(toFloat64(count()))) AS model_requests,
    sumOrNull(tokens) AS counted_tokens,
    countIf(isNull(tokens)) AS unknown_token_requests,
    if({lower} < toUnixTimestamp64Nano(now64(9) - INTERVAL 35 DAY)
       OR (SELECT count() FROM coverage) = 0, 1,
       (SELECT countIf(missing != 0
                      OR registered * 1e9 > {lower}
                      OR checkpoint * 1e9 < $end_timestamp_nano) FROM coverage) > 0
       OR (SELECT countIf(kind = 'gap' AND completed_ns < $end_timestamp_nano
                          AND numbers['usage.end'] * 1e9 > {lower}) FROM records) > 0) AS partial
FROM completions WHERE {condition}""")
    return "\nUNION ALL\n".join(queries)


def dashboard():
    count = f"""SELECT if(count() = 0, NULL, toNullable(toFloat64(count()))) AS value
FROM completions WHERE {SELECTED}"""
    history = f"""SELECT toStartOfMinute(fromUnixTimestamp64Nano(toInt64(completed_ns))) AS ts,
       toFloat64(count()) AS value
FROM completions WHERE {SELECTED} GROUP BY ts ORDER BY ts"""
    ranking = f"""SELECT strings['usage.model'] AS model,
       strings['usage.provider'] AS provider, toFloat64(count()) AS model_requests,
       sumOrNull(tokens) AS counted_tokens, countIf(isNull(tokens)) AS unknown_token_requests
FROM completions WHERE {SELECTED}
GROUP BY model, provider ORDER BY model_requests DESC, model ASC, provider ASC LIMIT 20"""
    token_series = f"""SELECT toStartOfMinute(fromUnixTimestamp64Nano(toInt64(completed_ns))) AS ts,
       sumOrNull(tokens) / 60 AS value
FROM completions WHERE {CLOSED} GROUP BY ts ORDER BY ts"""
    rate_change = f""", bins AS (
    SELECT toStartOfMinute(fromUnixTimestamp64Nano(toInt64(completed_ns))) AS ts,
           sumOrNull(tokens) / 60 AS rate
    FROM completions WHERE {CLOSED} GROUP BY ts
), changes AS (
    SELECT ts, rate,
           lagInFrame(toNullable(ts), 1, NULL) OVER full_window AS previous_ts,
           lagInFrame(rate, 1, NULL) OVER full_window AS previous_rate
    FROM bins WINDOW full_window AS
        (ORDER BY ts ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
SELECT ts, if(previous_ts IS NULL OR dateDiff('second', previous_ts, ts) != 60,
              NULL, (rate - previous_rate) / 60) AS value FROM changes ORDER BY ts"""
    health = """SELECT producer_kind, toFloat64(count()) AS registered_producers,
    sumIf(missing, missing > 0) AS missing_sequences,
    countIf(missing < 0) AS inconsistent_producers, sum(gaps) AS retained_gap_intervals,
    sum(shutdowns) AS shutdown_intervals,
    min(checkpoint) AS earliest_checkpoint_utc_seconds,
    min(registered) AS earliest_registration_utc_seconds
FROM coverage GROUP BY producer_kind ORDER BY producer_kind"""
    outcomes = f"""SELECT strings['usage.outcome'] AS outcome,
    toFloat64(count()) AS model_requests,
    countIf(NOT flags['usage.usage_present']) AS missing_or_unknown_usage,
    countIf(isNull(tokens)) AS unknown_token_totals
FROM completions WHERE {SELECTED} GROUP BY outcome ORDER BY outcome"""
    panels = {
        "prompts": panel("Prompts sent", count, "NumberPanel",
                         "Declared model-request completions. See Details for the counting basis.",
                         records_filter=EVENT_WINDOW),
        "requests": panel("Completed model requests per minute", history, "TimeSeriesPanel",
                          records_filter=EVENT_WINDOW),
        "models": panel("Requested model ranking by model-request count", ranking,
                        records_filter=EVENT_WINDOW),
        "calendar": panel("Pacific calendar totals - partial until coverage is proved", calendar_query()),
        "tokens": panel("Completed-call counted tokens per second", token_series, "TimeSeriesPanel",
                        "Closed one-minute accounting bins. Not live decoding speed. Clipped and unknown bins stay empty.",
                        records_filter=EVENT_WINDOW),
        "change": panel("Change in completed-call token rate", rate_change, "TimeSeriesPanel",
                        "The first change and changes across missing bins are unknown.",
                        records_filter=EVENT_WINDOW),
        "coverage": panel("Coverage of registered producers", health),
        "outcomes": panel("Outcomes and unknown usage", outcomes, records_filter=EVENT_WINDOW),
        "method": panel("Method and limits", visualization="TextPanel"),
    }
    panels["method"]["spec"]["plugin"]["spec"] = {
        "mode": "markdown", "text": (
            "**Prompts sent** counts declared model-request completions, not human submissions or physical HTTP retries.\n\n"
            "Each private producer/event identity counts once after replay. Identities are not metric labels. "
            "Tools, parent spans, repeated history, and user-role records do not add requests.\n\n"
            "The source covers public stream and streamSimple calls. One-shot helpers and chat-backed judgments register separately. "
            "Calls that bypass those entry points, native judgments, embeddings, and media requests are outside this source. "
            "Declared completions include failures and cancellations. Ranking uses requested model labels.\n\n"
            "OpenAI Responses and Anthropic normalizers preserve reported usage presence. Other normalizers keep presence and tokens unknown. "
            "Codex and Azure share the Responses normalizer but their transports are not exercised here. "
            "The CLI needs a verified build with the native source patch; copying adapter assets does not activate collection.\n\n"
            "**Counted tokens** sum known input plus output. Cache-inclusive input already contains cache buckets. "
            "Cache-exclusive input adds cache read and cache write once. Reasoning stays inside output. "
            "Absent usage and unknown buckets stay null. Known totals can remain partial when some requests lack usage.\n\n"
            "**Estimated cost: unknown. Verified billing: unknown.** No price or invoice source is configured.\n\n"
            "Calendar bounds use [Pacific calendar start, selected end). Weeks start on Monday. "
            "Counts use UTC completion instants. A collection start, missing sequence, explicit gap, shutdown, "
            "retention loss, or an old checkpoint can make a period partial. "
            "No observed producer proves coverage of unrelated processes or provider accounts. "
            "An empty period is unknown, not zero. The coverage table reports only registered producers.\n\n"
            "The ledger and SigNoz metadata log policy require 35 days, separate from sessions and raw traces. "
            "No history before collection can be recovered here. Native usage-presence support is required. "
            "Completed-call bins are not stream timing. The first rate change and changes across missing bins are unknown.\n\n"
            "Rate graphs omit clipped first and last minutes instead of comparing partial bins with full bins.\n\n"
            "Details uses a native collapsed section, not an HTML disclosure. "
            "Task/session state requires a separate trusted source and is not inferred from request completion. "
            "Jaeger and its 48-hour raw trace policy stay separate and unchanged."
        ),
    }

    def section(title, items, opened=True):
        return {"kind": "Grid", "spec": {
            "display": {"title": title, "collapse": {"open": opened}},
            "items": [{"x": x, "y": y, "width": width, "height": height,
                       "content": {"$ref": f"#/spec/panels/{key}"}}
                      for key, x, y, width, height in items],
        }}

    return {"schemaVersion": "v6", "name": "crewship-model-usage", "tags": [], "spec": {
        "display": {"name": "Model usage", "description":
                    "Metadata-only request accounting. Inspect Details and coverage before using partial totals."},
        "variables": [], "duration": "1h", "refreshInterval": "1m", "panels": panels,
        "layouts": [section("Usage", [("requests", 0, 0, 6, 5), ("tokens", 6, 0, 6, 5),
                                      ("prompts", 0, 5, 3, 4), ("change", 3, 5, 3, 4),
                                      ("models", 6, 5, 6, 4), ("calendar", 0, 9, 12, 5)]),
                    section("Details", [("coverage", 0, 0, 6, 5), ("outcomes", 6, 0, 6, 5),
                                        ("method", 0, 5, 12, 6)], False)],
    }}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    content = json.dumps(dashboard(), indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content)
    else:
        print(content, end="")


if __name__ == "__main__":
    main()
