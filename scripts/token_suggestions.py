#!/usr/bin/env python3
"""Write private token-saving suggestions from explicitly configured metadata."""

# Start the deadline before loading the reader's dependencies.
# ruff: noqa: E402

import time

STARTED = time.monotonic()

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import sys
import tempfile
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

previous_bytecode_setting = sys.dont_write_bytecode
try:
    sys.dont_write_bytecode = True
    from token_suggestions_sources import (
        ACTIONS,
        DETECTORS,
        PACIFIC,
        candidate,
        instant,
        metadata_identity,
        read_json,
        read_ledger,
        read_snapshot,
        windows,
    )
finally:
    sys.dont_write_bytecode = previous_bytecode_setting
    del previous_bytecode_setting

SOURCE_ERRORS = (OSError, ValueError, KeyError, TypeError, RecursionError, sqlite3.Error)


def settings(path):
    config = read_json(path)
    if not isinstance(config, dict) or set(config) - {"fm_home", "ledger", "snapshots"}:
        raise ValueError("invalid report config")
    paths = config.get("snapshots", [])
    if not isinstance(paths, list) or len(paths) > 8:
        raise ValueError("invalid snapshot list")
    for value in [config["fm_home"], *paths, *([config["ledger"]] if config.get("ledger") else [])]:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("explicit absolute paths required")
    output = Path(config["fm_home"]) / "data/token-savings"
    if any(Path(source).resolve().is_relative_to(output.resolve())
           for source in [*paths, *([config["ledger"]] if config.get("ledger") else [])]):
        raise ValueError("source overlaps report directory")
    return config


def cache_candidates(rows, coverage, bounds):
    by_group = defaultdict(dict)
    for row in rows:
        by_group[row["provider"], row["model"]][row["current"]] = row
    periods = {row["current"]: row for row in coverage}
    result = []
    for index, group in enumerate(by_group.values(), 1):
        row = group.get(1)
        if row is None:
            continue
        total = row["input_total"]
        if not total:
            continue
        signal = (f"Model group {index}: {row['requests']} completions; "
                  f"{row['excluded']} excluded rows. ")
        signal += (f"Cache-read share {row['cache_read'] / total:.2%}; "
                   f"cache-write share {row['cache_write'] / total:.2%}; "
                   f"known input {total} tokens.")
        prior = group.get(0)
        complete = not any(p["partial"] for p in coverage)
        comparable = (complete and not row["excluded"] and prior is not None
                      and not prior["excluded"] and prior["input_total"])
        if comparable:
            signal += (f" Previous seven complete days: cache-read share "
                       f"{prior['cache_read'] / prior['input_total']:.2%}, "
                       f"cache-write share {prior['cache_write'] / prior['input_total']:.2%}.")
        else:
            signal += " Seven-day comparison unavailable: incomplete coverage or unknown usage."
        result.append(candidate(3, index, tuple(t.isoformat() for t in bounds[1:]),
                                "existing local ledger", None, "normalized cache shares", signal,
                                periods[1]["partial"] or bool(row["excluded"])))
    return result


def deduplicate_source_measurements(source, seen):
    for kind in ("retro", "confirmed"):
        unique = []
        for measurement in source[kind]:
            identity = metadata_identity([{"window": source["window"], kind: measurement}])
            if identity not in seen:
                seen.add(identity)
                unique.append(measurement)
        source[kind] = unique


def collect(config, bounds):
    candidates, sources, notes = [], [], []
    available = False
    statuses = ["unavailable: no matching saved measurement" for _ in DETECTORS]
    if config.get("ledger"):
        try:
            rows, coverage = read_ledger(config["ledger"], bounds)
            candidates.extend(cache_candidates(rows, coverage, bounds))
            available = True
            statuses[3] = "available" if candidates else "unavailable: no known nonzero input denominator"
            notes.append("Current ledger completions: "
                         f"{sum(r['requests'] for r in rows if r['current'])}; excluded rows: "
                         f"{sum(r['excluded'] for r in rows if r['current'])}.")
            notes.append("Ledger coverage: " + "; ".join(
                f"{'day' if c['current'] else 'prior seven days'}: "
                f"{c['producers']} registered sources, {c['incomplete']} incomplete, "
                f"{c['gaps']} retained gaps, {c['shutdowns']} shutdowns; "
                f"{'partial' if c['partial'] else 'complete for registered sources'}"
                for c in coverage) + ".")
        except TimeoutError:
            raise
        except SOURCE_ERRORS:
            notes.append("Local ledger source_unavailable: missing, unsupported, malformed, or timed out.")
    else:
        notes.append("Local ledger source_unavailable: not configured.")
    notes.append("SigNoz source_unavailable: no authorized read-only query path is integrated.")
    seen_snapshots, seen_findings, seen_measurements = set(), set(), set()
    for index, path in enumerate(config.get("snapshots", []), 1):
        try:
            rows, source = read_snapshot(path, bounds, index)
            identity = source.pop("identity")
            if identity in seen_snapshots:
                continue
            seen_snapshots.add(identity)
            available = True
            deduplicate_source_measurements(source, seen_measurements)
            sources.append(source)
            for row in rows:
                identity = metadata_identity([row])
                if identity in seen_findings:
                    continue
                seen_findings.add(identity)
                candidates.append(row)
                statuses[row["detector"]] = "available: saved measurement"
        except TimeoutError:
            raise
        except SOURCE_ERRORS:
            notes.append(f"Saved report {index} source_unavailable: missing, stale, unsupported, or malformed.")
    return candidates, sources, notes, statuses, available


def candidate_lines(row, count):
    unranked = row["tokens"] is None
    tokens = "unknown" if unranked else str(row["tokens"])
    marker = "-" if unranked else f"{count}."
    lines = [f"{marker} **{DETECTORS[row['detector']]}**", "",
             f"   Source: {row['source']}. Observed tokens: {tokens}. "
             f"Basis: {row['basis']}. Coverage: {'partial' if row['partial'] else 'complete for this source'}.",
             f"   Signal: {row['signal']}",
             "   Uncertainty: observed volume is not avoidable work or achieved savings.",
             f"   Action: {ACTIONS[row['detector']]}", ""]
    for index, shape in enumerate(row.get("tool_shapes", []), 1):
        errors = "unknown" if shape["error_calls"] is None else str(shape["error_calls"])
        lines.append(f"   Tool shape {index}: calls {shape['calls']}; tokens {shape['tokens']}; "
                     f"largest_call {shape['largest_call']}; error_calls {errors}.")
    return lines


def markdown(bounds, collected, stale):
    candidates, sources, notes, statuses, _ = collected
    lines = ["# Token-saving suggestions", "",
             f"Window: {bounds[1].isoformat()} to {bounds[2].isoformat()} (previous complete Pacific day).",
             "", "Achieved savings: unknown. No total savings or money estimate is calculated.",
             "No-commit sessions and agent counts are not findings.", ""]
    if stale:
        lines.extend(["A previous cycle failed. This report uses the current window; it does not fill the gap.", ""])
    lines.extend(["## Detector status", "", "| Detector | Status |", "| --- | --- |"])
    lines.extend(f"| {name} | {state} |" for name, state in zip(DETECTORS, statuses))
    lines.extend(["", "## Source coverage", "", *notes, ""])
    for source in sources:
        lines.append(f"{source['source']}: {source['window'][0]} to {source['window'][1]}; "
                     f"{'partial' if source['partial'] else 'complete saved window'}; "
                     f"{source['caveats']} source caveats (private text omitted).")
        for family, tokens in source["retro"]:
            lines.append(f"Estimated retrospective reduction ({family}): {tokens} tokens. "
                         "This saved estimate is not achieved savings and is not added to other estimates.")
        for before, after, samples, applied in source["confirmed"]:
            lines.append(f"Saved artifact measurement: {before:g} before, {after:g} after tokens per turn; "
                         f"method deterministic_remeasure; attribution intact; {samples} after-sessions; "
                         f"applied at {applied}. Window: {source['window'][0]} to {source['window'][1]}.")
            lines.append("Confounders: the artifact count does not measure how often it was sent, "
                         "or whether the same edit would happen without the suggestion. "
                         "Achieved stream savings remain unknown.")
    lines.extend(["", "## Review candidates", "",
                  "Token ranks apply only within the same window and measurement basis. "
                  "Cache shares and count-only observations have separate groups. "
                  "Overlapping measurements are never added.", ""])
    groups = defaultdict(list)
    for row in candidates:
        group = (row["tokens"] is None, row["detector"] == 3, row["window"], row["basis"])
        groups[group].append(row)
    count = 0
    for (unranked, cache, window, basis), rows in sorted(groups.items()):
        if count == 5:
            break
        heading = "Cache shares" if cache else "Count-only retry observations" if unranked else basis
        lines.extend([f"### {heading}: {window[0]} to {window[1]}", ""])
        ordered = rows if unranked else sorted(rows, key=lambda c: -c["tokens"])
        for row in ordered[:5 - count]:
            count += 1
            lines.extend(candidate_lines(row, count))
    if not count:
        lines.extend(["No measured candidates in the permitted sources for this window.", ""])
    return "\n".join(lines)


def atomic_write(path, content):
    fd, temporary = tempfile.mkstemp(prefix=".report-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as target:
            target.write(content)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def publish(config, cutoff, *, started=None):
    if started is None:
        started = time.monotonic()
    interrupted = False

    def timeout(_signum, _frame):
        nonlocal interrupted
        interrupted = True
        raise TimeoutError("report deadline")

    directory = Path(config["fm_home"]) / "data/token-savings"
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid != os.getuid():
        raise ValueError("unsafe output directory")
    directory.chmod(0o700)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    handlers = {}
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for signum in (signal.SIGALRM, signal.SIGTERM):
            handlers[signum] = signal.signal(signum, timeout)
        status_path = directory / "status.json"
        try:
            remaining = 50 - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError("report deadline")
            signal.setitimer(signal.ITIMER_REAL, remaining)
            previous = read_json(status_path) if status_path.exists() else {}
            bounds = windows(cutoff)
            collected = collect(config, bounds)
            if not collected[-1]:
                raise ValueError("no permitted source available")
            text = markdown(bounds, collected, previous.get("state") == "failed")
            if interrupted or time.monotonic() - started >= 50:
                raise TimeoutError("report deadline")
            day = bounds[1].astimezone(PACIFIC).date().isoformat()
            atomic_write(directory / f"{day}.md", text)
            for old in sorted(directory.glob("????-??-??.md"))[:-8]:
                old.unlink()
            atomic_write(status_path, json.dumps({"state": "complete", "cutoff": cutoff.isoformat(),
                                                  "window": [t.isoformat() for t in bounds[1:]]}) + "\n")
            atomic_write(directory / "latest.md", text)
        except (TimeoutError, *SOURCE_ERRORS):
            signal.setitimer(signal.ITIMER_REAL, 0)
            atomic_write(status_path, json.dumps({"state": "failed", "cutoff": cutoff.isoformat(),
                                                  "reason": "source_unavailable or report failure",
                                                  "detectors": dict.fromkeys(DETECTORS, "unavailable")}) + "\n")
            raise
    finally:
        if handlers:
            signal.setitimer(signal.ITIMER_REAL, 0)
            for signum, handler in handlers.items():
                signal.signal(signum, handler)
        os.close(fd)


def main(argv=None, *, started=None):
    if started is None:
        started = time.monotonic()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--cutoff", type=instant, help="fixed aware time for a manual fixture cycle")
    args = parser.parse_args(argv)
    try:
        publish(settings(args.config), args.cutoff or datetime.now(UTC), started=started)
    except (TimeoutError, *SOURCE_ERRORS):
        print("Token suggestions failed; previous successful report retained.", file=sys.stderr)
        return 1
    print("Token suggestions published.")
    return 0


if __name__ == "__main__":
    sys.exit(main(started=STARTED))
