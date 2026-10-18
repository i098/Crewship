# Model usage metadata

This source provides a native metadata adapter, an upstream source patch, a durable ledger, an OTLP/HTTP exporter, and a SigNoz dashboard.
It does not install or activate a collector, a source adapter, or a SigNoz service.
Jaeger and its 48-hour raw trace policy remain separate and unchanged.

## Source compatibility

The collector accepts declared model-request completions from registered producers.
The protocol separates `chat`, `judgment`, and `helper` producers.
A producer registration declares its scope; it does not prove coverage of other processes or provider accounts.

OMP 18.7.0 does not expose a sufficient metadata-only completion callback.
Its `onChatUsage` callback skips absent usage and catches delivery errors.
Its provider messages initialize token fields with zeroes before provider usage arrives.
An adapter cannot determine usage presence from those zeroes.
The message events carry content and are not an authorized substitute.

`blueprint/patches/omp/usage.patch` adds the missing metadata contract to the OMP 18.7.0 source.
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

The Ansible `crewship_usage_install` variable defaults to false.
Setting it true copies the collector, adapter, dashboard, and source patch after a read-only data-mount check.
It does not apply the upstream patch, rebuild OMP, set agent configuration, start a service, or activate capture.
It preserves unknown settings and explicit user overrides.
The future process opt-in requires four explicit variables:

| Variable | Value |
| --- | --- |
| `CREWSHIP_USAGE_ADAPTER` | The absolute installed `omp-usage.ts` path. |
| `CREWSHIP_USAGE_COLLECTOR` | The absolute installed `usage.py` path. |
| `CREWSHIP_USAGE_DATA_DIR` | A dedicated directory below the verified large data mount. |
| `CREWSHIP_USAGE_MOUNT` | The actual configured mount path. |

The default asset directory is `~/.local/share/crewship/usage`.
The source does not activate unless a patched runtime receives the adapter opt-in.
No installed source, binary, process, or host configuration changes here.

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
It creates private ledger files with mode `0600` under a private directory.
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

Every collector, report, and export invocation prunes expired records.
A long-running collector also prunes hourly when it receives records.
Run the `prune` command from an independently authorized scheduler to remove expired data when collection is idle.
No scheduler or service is installed by this change.
Offline storage cannot delete records without a running retention process.

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
It sends at most 100 metadata log records per invocation.
Run again to drain more records.

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
