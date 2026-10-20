# Model usage metadata

Crewship provides a native metadata adapter, an upstream source patch, a durable ledger, a bounded retry spool, an OTLP/HTTP exporter, and a SigNoz dashboard.
The optional installation configures the export timer and copies the native assets.
It does not install SigNoz or rebuild the source runtime.
Jaeger and its 48-hour raw trace policy remain separate and unchanged.

## Source compatibility

The collector accepts declared model-request completions from registered producers.
The protocol separates `chat`, `judgment`, and `helper` producers.
A producer registration declares its scope; it does not prove coverage of other processes or provider accounts.

OMP 18.12.1 does not expose a sufficient metadata-only completion callback.
Its `onChatUsage` callback skips absent usage and catches delivery errors.
Its provider messages initialize token fields with zeroes before provider usage arrives.
An adapter cannot determine usage presence from those zeroes.
The message events carry content and are not an authorized substitute.

`blueprint/patches/omp/usage.patch` adds the missing metadata contract to the OMP 18.12.1 source.
It targets the upstream `packages/ai` directory.
It observes public `stream` and `streamSimple` calls before dispatch and after provider settlement.
It acknowledges metadata before it delivers a terminal result.
Nested calls count once.
Separate public calls keep separate event identities.
`complete` and `completeSimple` calls register as helpers.
The chat-backed judgment backend registers separately as `judgment`.
Ordinary streams register as `chat`, including main, subagent, and advisor calls through those entry points.
The adapter does not cover native judgments, embeddings, media calls, or callers that bypass both entry points.
Internal transport or authentication retries can remain inside one declared completion.
No count claims physical HTTP attempts or complete provider-account usage.
Enable capture on one process layer.
Do not enable both a client and its forwarding server for the same calls.

The patch preserves provider-reported presence for OpenAI Responses and Anthropic usage.
Anthropic output stays null until a terminal usage update supplies the final count, including compaction totals.
Interrupted streams retain known input and cache fields without inventing a complete token total.
The shared Responses normalizer also serves Codex and Azure paths; those transports are not exercised here.
Other normalizers keep usage presence unknown and export null token buckets.
The adapter never treats their initialized zeroes as observed usage.
It reads only selected terminal metadata and awaits durable acknowledgements.
Delivery failure escapes instead of disappearing inside `onChatUsage`.
After registration, every source record persists a pending gap first, including completion, checkpoint, and shutdown.
Graceful exit records a shutdown checkpoint.
An unreferenced one-minute timer records idle checkpoints without keeping a source process alive.
Start a new source process after an outage exceeds the retained producer horizon.
The collector cannot recover metadata that already expired.

The installed OMP CLI is a minified bundle.
A source-package patch alone does not prove capture from that bundle.
CLI activation requires an OMP artifact rebuilt from the patched source and a separate integration check.
The copied native-source fixture exercises real provider parsers and collector delivery without changing the installed runtime.

## Installation

Configure `crewship.usage` in the host configuration:

```yaml
crewship:
  usage:
    endpoint: https://ingest.example.invalid/v1/logs
    enabled: true
    auth_file: /srv/secrets/signoz.env
    mount: /srv/agent-data
    state_dir: /srv/agent-data/usage
```

Omit `usage` or leave its endpoint empty to install nothing.
Use the full OTLP/HTTP logs URL, including `/v1/logs`.
Remote endpoints require HTTPS; loopback HTTP supports isolated fixtures.
The configured mount must exist and differ from the root filesystem.
An empty `state_dir` uses `crewship.data_dir/usage`.
The installer checks the mount and target-account write and search access without creating state, including in check mode.
Prepare `state_dir` with mode `0700` and target-account ownership when the parent does not permit directory creation.
Apply the same preparation to `crewship.data_dir/usage` when `state_dir` is empty.
If the directory does not exist, its nearest existing parent must permit the target account to create it.

The optional `auth_file` is a systemd environment file containing `SIGNOZ_INGESTION_KEY=...`.
Create it separately with mode `0600`, readable by the target account.
The installer records only its path and never copies, reads, or deletes the authentication file.
Leave the path empty when the endpoint needs no ingestion key.
A missing configured file stops export instead of sending without its key.

Run `./ship.sh chart` to preview and `./ship.sh launch` to install.
The installation copies the client, adapter, dashboard, source patch, and `capture.env` into `~/.local/share/crewship/usage`.
It installs `crewship-usage.service` and `crewship-usage.timer` as user units.
The timer schedules export five minutes after boot and after each export finishes, plus up to five minutes of random delay.
An expired timer deadline can start export immediately on activation or resume.
The sender also applies the [per-request random delay](#reports-and-export) before the first request.
One service instance exports at a time, with a twenty-minute timeout.
Each run uses the [bounded spool](#retry-spool) and the [export limits](#reports-and-export).
It does not open or drain an old `usage.sqlite` ledger.

With `start_services: false`, installation writes units and the static timer link without starting, stopping, or reloading systemd.
A later managed apply reloads stale exporter and timer units, including changes made while service management was off.
With service management enabled, set `usage.enabled: false` and apply to stop the timer and any current export.
This removes the boot link and installed files.
Clearing `usage.endpoint` and applying has the same effect.
Both operations preserve state, old ledgers, and authentication files.
When service management is off, apply again with service management enabled to stop an already running timer.
Stop or restart opted-in source processes without `capture.env` before disabling or removing collection.
Already running sources keep their environment.

### Native process opt-in

The installation does not apply the upstream patch, rebuild OMP, or activate capture in existing processes.
For a separately verified patched runtime, source the installed `capture.env` before starting that process.
Do not source it globally.
The file selects the spool and supplies these variables:

| Variable | Value |
| --- | --- |
| `CREWSHIP_USAGE_ADAPTER` | The absolute installed `omp-usage.ts` path. |
| `CREWSHIP_USAGE_COLLECTOR` | The absolute installed `usage.py` path. |
| `CREWSHIP_USAGE_DATA_DIR` | A dedicated directory below the verified large data mount. |
| `CREWSHIP_USAGE_MOUNT` | The actual configured mount path. |
| `CREWSHIP_USAGE_STORE` | Optional: `spool` (the default) or `ledger`, passed to the collector as `--store`. Another value fails every record. |

The source does not activate unless a patched runtime receives the adapter opt-in.
Installation preserves unrelated host and agent settings.

## Durable protocol

`python3 scripts/usage.py --mount MOUNT --data-dir DATA_DIR collect` reads bounded JSON records from a producer's standard input.
It acknowledges each committed record on standard output.
The native source must supply these records; operators must not fabricate production events.
Synthetic fixtures use the same collector path.
A rejected record stops collection with a fixed error message and a nonzero exit status.
The collector never logs rejected input.

Each record contains exactly `schema`, `kind`, `producer`, `event`, `at`, and the fields for its kind.
`schema` is `1`.
Private producer and event identities use canonical UUID strings.
`at` is an explicit UTC instant.
Additional fields are rejected at capture and checked again before export.

| Kind | Additional fields | Meaning |
| --- | --- | --- |
| `register` | `producer_kind` | Register a native `chat`, `judgment`, or `helper` producer. |
| `start` | `sequence`, `provider`, `model` | Persist a positive sequence, bounded model labels, and a request start before dispatch. |
| `complete` | `sequence`, `outcome`, `usage_present`, `input_basis`, `input`, `cache_read`, `cache_write`, `output`, `reasoning` | Complete the matching start with the same private event identity. |
| `checkpoint` | `sequence` | Declare the highest sequence produced through this UTC instant, including missing delivery. |
| `shutdown` | `sequence` | End this producer's coverage through this instant. |
| `gap` | `end`, `reason` | Record a half-open UTC interval with `delivery`, `shutdown`, or `source` as its reason. |

A process restart needs a new producer identity unless it restores the previous sequence and pending metadata durably.
Sequence values do not count requests by themselves.
A checkpoint must not move backwards in time or sequence.
Missing sequence ranges and starts without completions remain visible in coverage.
The ledger keeps these intervals separately from completion rows so ordinary expiry does not create false gaps.
An old checkpoint does not prove current coverage.
A shutdown ends coverage; a new process registers separately.

One completion row represents one declared model request.
Its stored `request_count` is always one.
Replaying the same identity and payload adds no row and does not extend its retention.
A different payload or sequence under an existing identity fails.
Separate recorded attempts need separate event identities and sequences.
This is not a count of unobserved provider HTTP retries.

Outcomes are `success`, `error`, `aborted`, or `unknown`.
Unknown token fields use JSON null, never substituted zeroes.
Absent usage requires `usage_present: false`, `input_basis: unknown`, and null token buckets.
Known zero usage remains different from absent usage.
Partial reported usage can retain null buckets.
Unknown native presence uses `usage_present: null` with an unknown basis and null token buckets.
The exporter preserves that unknown state by omitting its Boolean attribute.

Inclusive input already contains cache read and cache write.
Exclusive input adds those two buckets once.
Reasoning is a subset of output and never adds tokens to the total.
An unknown cache bucket prevents an exclusive total, but it does not prevent a known inclusive total.
The ledger rejects negative buckets, inconsistent cache totals, and reasoning above output.
Known cache counts cannot exceed inclusive input, even when another cache bucket is unknown.
Numbers must be nonnegative safe integers.

## Data mount and retention

Use the host's existing `crewship.data_dir` layout on a separately configured data mount.
Pass a dedicated child directory and the actual mount path explicitly.
For example, use `--mount /srv/agent-data --data-dir /srv/agent-data/usage` only after that mount exists.
The collector refuses a missing mount, the root filesystem mount, path traversal, and paths outside the configured mount.
It does not create a fallback root-backed directory.
It creates private ledger and spool files with mode `0600` under a private directory.
The `check` command verifies these paths without creating a directory or database.
It preserves existing host and agent configuration because it writes neither.

The SQLite ledger uses full synchronous commits and transactional identity constraints.
Metadata, deduplication state, and coverage records survive session and raw trace expiry independently.
Records expire 35 days after the later of their event time and ingestion time.
Active producer registration and matching starts stay at least as long as their dependent metadata.
No replay extends that window.
The ledger emits a `retention` control record when it retires completed records.
Retirement counting, watermark updates, and deletion share one write transaction so concurrent collectors cannot retire a completion twice.
The collector rejects producer-supplied retirement records.
Exported `sequence_through` and `retired_completions` values are immutable snapshots, not account totals or metric labels.
The dashboard uses the retirement watermark without hiding missing records from a partial export.

Every ledger collector, report, and export invocation prunes expired records.
A long-running collector also prunes hourly when it receives records.
The installed spool export timer prunes spool data, including while capture is idle.
Run the ledger `prune` command from a separately authorized scheduler if an old ledger still needs retention cleanup.
Offline storage cannot delete records without a running retention process.

## Retry spool

Add `--store spool` before the command to keep metadata only until the OTLP endpoint acknowledges it.
The operator CLI default `--store ledger` keeps the 35-day ledger described above.
The spool uses `spool.sqlite` in the same data directory and never opens `usage.sqlite`.
An existing ledger stays unchanged; its unsent rows still export with `--store ledger export`.
The native adapter uses the spool unless `CREWSHIP_USAGE_STORE=ledger` is set.
A running process keeps the store that it started with, so restart producers to change the store.

The spool applies the same allowlist, identity, and transition rules as the ledger.
`collect` only validates and stores each record; it never compresses or sends.
Each `export` run first moves the backlog of closed UTC hours into packs.
A pack holds the rendered OTLP log records of up to 500 records from one closed hour, grouped by model and compressed with zlib.
The current hour stays unpacked until the export sends it.
The export sends the oldest packs first; then it packs and sends the current hour in batches of up to 100 records.
A pack never changes after it is made, so a retry sends the same records in the same request.
The exporter deletes a pack only after the OTLP acknowledgement.

Moving records into a pack deletes their completions, checkpoints, and gaps from the record table.
Registrations, shutdowns, and starts without a packed completion stay, because later records need their producer and model labels.
These kept rows expire 35 days after their last use, as in the ledger; `prune` and `export` remove them.
A kept row stays while a pending record of its producer or request still needs its labels, so a late pack keeps its producer and model labels.
A new unpacked checkpoint replaces the older unpacked checkpoint of the same producer.
The dashboard reads only the latest checkpoint of each producer, so this replacement removes no reported value.
For the same records, the spool exports the same OTLP log records as the ledger.
The spool keeps no totals, calendar periods, coverage, or reports, so `report` fails.
It cannot recognize a replay of a record that it already packed.

SigNoz drops a log record when its timestamp is older than the log retention.
The exporter therefore holds a pack when its oldest record is less than one hour from the end of 35 days.
A held pack stays in the spool, compressed and unchanged, and it is never sent.
`export` reports held records as `held`.
Held records do not count toward the byte, page, or age limits, so an outage longer than 35 days cannot keep collection refused.
When every record in a held pack is past its 35-day local retention, `prune`, `collect`, and `export` delete the pack.
SigNoz would drop these records at 35 days anyway, so this deletion is retention expiry, not a loss of exportable data.
Each prune that deletes held packs writes one line, such as `{"expired_held_records": 3}`, to standard error.

| Limit | Value |
| --- | --- |
| Stored bytes: unpacked records and compressed packs that are not held | 64 MiB |
| Age of the oldest pending record that is not held | 7 days |
| Database file | 128 MiB: 32,768 pages of 4,096 bytes |
| Pages in use when `collect` refuses, less the pages of held packs | More than 32,512 |

`collect` refuses a record that would go past the byte, age, or page limit.
Without held packs, 256 pages stay free; held packs can use these pages until prune deletes them, about one to two hours later.
In that window, SQLite's `SQLITE_FULL` limit at 32,768 pages stops any write that needs more pages.
The 256 free pages let an export acknowledge and remove records from a full spool.
With adapter records, the page limit stops collection at about 42 MiB of record bytes, about 83,000 pending requests, before the byte limit.
SQLite refuses any page above the database limit with `SQLITE_FULL`.
A refusal has the fixed error message and exit status 1, and it stores nothing.
The adapter then records a delivery gap and fails the metered model call, as for any other collector failure.
An export that packs or removes records lets collection continue.
Records that are still below the limits wait through an endpoint outage and then export.

The spool uses a write-ahead log with full synchronization; a one-record collector process makes two disk syncs, where a rollback journal makes five.
A commit checkpoints the log into the database after 128 pages, and the log shrinks back to 1 MiB after a checkpoint, so it stays below 4 MiB.
A closing process does not checkpoint, so a collector process that carries one record does not pay for a full checkpoint.
The directory holds only `spool.sqlite`, `spool.sqlite-wal`, `spool.sqlite-shm`, and the empty `spool.lock`; a short-lived `spool.sqlite-journal` exists only while the first process creates the database.
Each collector and export transaction takes an exclusive lock on `spool.lock`.
The exporter does not keep the lock during the HTTP request.
Each packing transaction handles at most 500 records.
After each transaction, the process pauses for one millisecond, because `flock` wakes waiting processes in no fixed order.
A collector waits for another transaction instead of failing with a busy database.

The spool keeps no exported completions, so it cannot count completions that expire later in SigNoz.
Its exported `retired_completions` value stays 0.
A producer that runs longer than 35 days therefore shows its expired completions as missing sequences, and the dashboard marks its periods partial.
A restarted producer registers a new identity without this effect.

## Reports and export

Run `report --period day`, `report --period week`, or `report --period month` after the common mount arguments.
Use `--at` with a UTC instant for a bounded snapshot.
The report uses UTC completion times and half-open America/Los_Angeles calendar bounds.
Each report starts at the Pacific calendar boundary and excludes completions at or after the selected snapshot.
Weeks start on Monday.
Timezone-aware bounds include daylight-saving changes.

`requests` counts retained declared completions.
`counted_tokens` sums known totals; `unknown_tokens` reports completions without a known total.
A token total is incomplete when any selected completion lacks a known total.
`partial` describes history coverage, not token completeness.
Both conditions matter.
An empty token period returns null, not an invented zero.
Human-only submissions remain unmeasured.
Repeated history and user-role records never supply a human count.
Estimated cost and verified billing remain separate null values.
No model prices or invoices are supplied or inferred.

Run `export --endpoint https://AUTHORIZED-ENDPOINT/v1/logs` only after separate endpoint and egress authorization.
`SIGNOZ_INGESTION_KEY`, when supplied by the operator, sets the ingestion header and never enters the ledger or exported metadata.
The exporter refuses endpoint credentials, redirects, and remote plain HTTP.
Loopback HTTP is supported for isolated protocol fixtures.
Each run takes a snapshot of the pending records and makes at most 50 requests.
Records that arrive during the run wait for the next run.
The sender compresses each request body with gzip.
Before every request, including the first, it waits a random interval of up to one second.
These waits spread the requests of many hosts that reconnect at the same time.
The run stops at the first failed, throttled, or rejected request; the requests before it stay acknowledged.
The next scheduled run continues, so a slow or busy endpoint receives fewer requests.

The exporter acknowledges a batch only after a successful OTLP response with no rejected records.
A transport error, rejected batch, or invalid acknowledgement keeps the complete batch pending.
Retry sends the same private identities and numeric values.
A response lost after ingestion can cause duplicate log records in SigNoz.
Every dashboard query removes those duplicates before it counts requests or adds tokens.
The OTLP log timestamp uses the later of event time and ingestion time for the independent retention policy.
The separate `usage.at_us` attribute stores the exact UTC event instant as safe integer microseconds.
Dashboard queries use that completion instant for calendar counts, not ingestion time.
Private identities are log attributes, not resource attributes or metric labels.
Only fixed schema fields, bounded model metadata, selected numeric fields, and private identity fields leave the ledger.
Content, content hashes, arbitrary attributes, headers, tool arguments, tool results, credentials, and error text never leave through this path.

## SigNoz custom dashboard

`blueprint/usage/dashboard.json` is an importable current SigNoz v6 definition for the v2 dashboard API.
It uses the documented logs v2 table and ClickHouse query panels.
Panels share rows on the 12-column SigNoz v6 grid.
It is not a screenshot or a running dashboard.

Regenerate it with:

```sh
uv run python scripts/usage_dashboard.py --output blueprint/usage/dashboard.json
```

The Usage section has three rows:

| Row | Panels (width of 12) |
| --- | --- |
| 1 | Completed model requests per minute (6) and completed-call counted tokens per second (6) |
| 2 | **Prompts sent** (3), change in completed-call token rate (3), and requested model ranking (6) |
| 3 | Pacific calendar totals (12) |

The Details section puts producer coverage (6) beside outcomes (6), with the method notes (12) below.

Model ranking orders by the declared request count and shows known tokens and unknown totals separately.
It shows about one model at a time and scrolls inside its panel.
Closed one-minute bins measure completed-call accounting, not live decoding speed.
The rate queries omit clipped first and last minutes.
The first rate change and changes across missing bins stay null.
No empty bin is filled with zero.
The definition requests a closed Details section with methodology, coverage, outcomes, cost limits, and history limits.
The native renderer can start this section open.
SigNoz supports a collapsed section, not an HTML disclosure.
On a narrow phone screen, SigNoz shrinks each row instead of stacking its panels, so it cuts panel titles short and tables need sideways scrolling.
This definition does not introduce another frontend.
Task and session state need a separate trusted source and are not inferred here.

The dashboard reads only the last 35 days of metadata logs.
It counts each private producer/event/kind identity once before aggregation.
Calendar queries use the selected end instant, not an assumed fixed UTC offset.
A retained gap makes a calendar period partial only when its half-open interval overlaps that period.
The count panels return no value when no completions are observed.
Such a period is unknown, not a proved zero-request interval.
Coverage cannot prove requests from a producer that never registers.
Periods before the current retention cutoff remain partial, even when current checkpoints appear healthy.
The exporter does not import transcripts, mutable history indexes, or raw traces.

### Read-only query regression checks

Set `CREWSHIP_TEST_CLICKHOUSE_URL` to an explicitly supplied synthetic ClickHouse HTTP endpoint.
Set `CREWSHIP_TEST_USAGE_RECEIPT` to a JSON receipt from the independent synthetic ledger.
The receipt contains `start_ns`, `end_ns`, and expected `prompts` and `calendar` result arrays.
Each calendar row contains `period`, `pacific_start`, `model_requests`, `counted_tokens`, `unknown_token_requests`, and `partial`.
Sort the calendar rows by `period`.
Use a snapshot inside the retained history.
Run `uv run pytest tests/test_usage.py -k generated_queries_match_clickhouse_ledger_receipt`.
These checks execute generated queries with `readonly=1`; they do not create tables or ingest records.
The default test run skips these checks when either variable is absent.
Use stored logs v2 metadata with Float64 numeric maps; constant-row queries do not test the storage predicate.

### Activation prerequisites

Obtain separate authorization for all activation steps.
Supply and verify an OMP CLI artifact rebuilt with the included native metadata patch, then opt in each declared producer.
Verify the configured large data mount and authorize an independent retention schedule.
Supply a separately authorized SigNoz OTLP/HTTP logs endpoint and its access policy.
Configure and verify at least 35 days of metadata log retention before ingestion.
Import the dashboard into a SigNoz version that supports the current v6 definition and logs v2 schema.
Use the v2 dashboard API or its native JSON import.
The older native AI overview is trace-only and is not this dashboard.

No source, endpoint, account, package, service, deployment, or host configuration is activated here.
No full ClickHouse or SigNoz integration run is claimed.
The isolated HTTP receiver proves the exporter protocol, not a SigNoz deployment.

### Primary contracts

- [SigNoz dashboard API schema](https://signoz.io/api/api-reference-openapi/latest/)
- [Current v6 dashboard source contract](https://github.com/SigNoz/signoz/blob/main/pkg/types/dashboardtypes/perses_dashboard.go)
- [Native dashboard sections and JSON import](https://signoz.io/docs/userguide/manage-dashboards/)
- [SigNoz logs v2 schema and ClickHouse panels](https://signoz.io/docs/userguide/logs_clickhouse_queries/)
- [Signal retention policy](https://signoz.io/docs/userguide/retention-period/)
- [OTLP/HTTP export responses](https://opentelemetry.io/docs/specs/otlp/#otlphttp-response)
