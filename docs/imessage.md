# iMessage bridge

The iMessage bridge lets the owner talk to Firstmate from a phone. It is a small Bun service, `fm-imessage.service`, that uses one or both of two transports for the iMessage line: a [Photon Spectrum](https://photon.codes/docs/spectrum-ts) project (the default), and [self-hosted BlueBubbles relays](#use-self-hosted-bluebubbles-relays) on Macs that you control. It is off by default.

## What it does

For each message from the owner, the service does these steps:

1. It turns the message into text. A threaded reply, a message effect, or a group of messages is unwrapped, so nothing that he writes is lost. A threaded reply also names the text that it replies to. A message kind that the service does not know becomes a note that names the kind. Tapbacks, typing, read receipts, unsends, and chat changes are only signals, and the service ignores them.
2. For a supported desk, it starts reading `fm-inbox.sh status` before saving the message.
   It saves the full input and a stable request id in the private `routing.jsonl` journal before transport acknowledgement.
   It also appends the owner text to desk memory.
   It keeps authored text separate from quoted thread metadata for action and social checks.
3. It marks the text as read.
4. It combines text until 350 milliseconds of silence or 2 seconds from the first text, whichever comes first.
   This cap limits the batching wait, not status retrieval, model work, or delivery.
   Each new text cancels a running draft, resets the quiet timer, and starts a fresh status read.
   Text received during a draft starts a new batching wait; the next draft includes every pending message.
   The desk uses the latest status result after the wait without reading it again.
   Slow message persistence can make the status snapshot older than the batching wait.
   Attachments, unsupported content, group chats, and edits go to Firstmate without a model answer.
   A desk other than `omp` with `claude-haiku-5-5` or `inception` with `mercury-3` also sends every request to Firstmate.
5. The desk model classifies the whole pending burst.
   The default is Claude Haiku 5.5 with thinking off, through the existing one-shot `omp -p` runner.
   Both providers use the existing `omp -p` tool runtime for classification.
   `desk_provider: inception` selects `inception/<desk_model>` without changing the provider or configured reasoning level.
   Inception needs an explicit `desk_reasoning` of `instant`, `low`, `medium`, or `high`; `instant` is valid only with Inception.
   A native provider hook preserves Inception's `instant` wire value; other reasoning levels pass through unchanged.
   A failed Inception call never falls back to another provider; requests follow the [second-mate handoff rules](#second-mate-handoffs).
   The Inception voice pass still uses its tool-free chat-completions request and `instant` reasoning.
   The runtime has native `read`, `grep`, `glob`, `bash`, and `write` tools, plus the existing `zoom` extension.
   `desk-tools.yml` enables secret masking; a native extension checks every write against the current owner's authorized target.
   Before evidence validation and the voice call, the extension uses native filters to remove credentials from replies and tool results.
   The bridge rejects server-tool output without this filtered result.
   Each classification call with server tools uses a private temporary directory with a native secret file for parent-known credentials.
   This includes configured relay passwords and connection passwords without adding them to the tool environment.
   The service removes the directory when the call exits.
   Automatic writes require one explicit write, set, or replace request with one absolute file path and an existing parent directory.
   The target is resolved before the call and checked again before writing, including symbolic links.
   The native-normalized destination must resolve to that same authorized target; normalization cannot select a different file.
   Empty writes and unapproved targets are blocked; retrieved content cannot add a target.
   A shebang write requires approval if the native writer would add execute permissions, including when it creates a file.
   Version-controlled projects, registered mate homes, and known credential stores are not automatic write targets.
   Direct reads stay on the local filesystem and local process or artifact interfaces.
   The guard decodes native file URLs before checking each target from quote removal and delimiter expansion.
   Network reads require approval.
   Shell commands still require native approval, except the listed system reads.
   The automatic service check is exactly `systemctl --user is-active -- fm-imessage.service`; other service commands require approval.
   The child receives only its provider credentials and required runtime variables, not transport credentials.
   Native tools retain `XDG_RUNTIME_DIR` and `DBUS_SESSION_BUS_ADDRESS` so local user-service inspection can connect to the existing bus.
   Its input combines [desk memory](#desk-memory), durable `fm-inbox.sh status` output, and pending messages.
   Reading status does not request a supervisor answer.
   The desk refreshes typing every four seconds during the model call, delivery lookups, queue waits, and retries.
   It stops when the transport accepts the first response bubble or the reaction, or when the response is cancelled, handed off, or discarded.
   The service stops refreshes before saving delivery progress, even if that save fails.
   Shutdown stops typing and allows two seconds for pending cleanup.
   Supervisor typing starts after desk cleanup.
   Command typing has an eight-second expiry timer; another typing command renews it.
   The response-deadline callback stops typing only for its associated desk turn.
   A burst across different chats shows no typing because the model has not yet selected its response target.
   Informational noun phrases, including approval counts, reach this classifier after receipt or recovery.
6. When not [muted](#mute), a clear basic question can receive one direct answer without a Firstmate note or wake.
   The internal draft must equal complete evidence lines from status, prior supervisor or desk records, or successful current tool results.
   Model-identity evidence names the desk or supervisor and must match that subject's full configured model name.
   An unknown supervisor identity requires a handoff.
   The service checks every quote against its source and rejects conflicting draft text, missing evidence, and work claims.
   After those checks, the existing voice pass uses the original question and validated draft to write a short plain-text answer.
   It explains configuration values in context and preserves exact values, links, identifiers, and commands.
   The draft and question remain untrusted data; neither grants action authority.
   The native result envelope masks credentials in the original question before it reaches the voice pass.
   The prompt requires every fact, name, number, link, subject, negation, and claim to stay unchanged.
   The service rejects changed protected tokens or polarity, empty replies, failed calls, work claims, and unrequested Markdown fences.
   The reply check rejects Markdown, configuration rows, and bare source values unless the original question explicitly requests exact output.
   A retained configuration row still causes rejection when other lines contain prose.
   Unrequested inline code also causes rejection; the service does not strip its formatting.
   An explanation containing “exactly” does not authorize raw output.
   Explicit output noun phrases and quote or copy requests can authorize it; ambiguous requests cannot.
   The same rules apply when a request spans lines or combines several messages.
   Validated model-identity replies can retain the configured model name alone.
   All source-backed answers can use up to 2,000 characters so bare values can become useful sentences.
   Protected tokens include identifiers, paths, #numbers, versions, numbers with units, comparison operators, and links; their text and case must match.
   Source comparison ignores paired inline Markdown delimiters; it never removes characters from the delivered answer.
   Rewrites retain standalone scalar values, configuration field values, and inline code exactly.
   Only the approved prose pairs `Read-only`/`read-only` and `Restart-proof`/`restart-proof` can change case.
   All other hyphenated tokens retain their case, including sentence-leading identifiers.
   Rewrites can use contractions, reorder words, shorten wording, and lead with the answer.
   Polarity words must keep the same counts and immediately adjacent punctuation.
   These words are `no`, `not`, `never`, `none`, `nothing`, `n't` forms, `yes`, `failed`, `passed`, `broken`, `fixed`, `done`, `blocked`, `can't`, and `won't`.
   Configuration flags `on`, `off`, `true`, `false`, `enabled`, and `disabled` retain their counts without binding sentence punctuation.
   Every rejected rewrite hands off instead of sending raw source output, including stored chat and status excerpts.
   Blank lines separate bubbles; explicitly requested raw values can retain their line breaks.
   Reactions do not use the voice pass.
   The desk answers a burst once and selects the message that needs the answer, including an earlier question.
   Later corrections and follow-ups guide that selection.
   When not [muted](#mute), a purely social burst can receive one reaction and finish without a Firstmate note or wake.
   Every message must contain only a supported acknowledgement, thanks, laughter, celebration, or emoji.
   An answer to a prior question or approval request cannot use this shortcut.
   Only a small set of thanks, laughter, and celebration emoji can close a social turn.
   Incoming thumbs-up, check marks, objections, and stop or question symbols still go to Firstmate.
   The prompt asks for occasional reactions, not a reaction on every message or every social turn.
   It favors a fitting heart, laugh, or emphasis reaction instead of a default thumbs-up.
   Requests, questions, approvals, sensitive messages, and mixed bursts receive no desk reaction.
   A social reaction may include one short text from a fixed list of safe acknowledgements.
   The text cannot contain facts or work claims; an invalid text prevents the social response.
   Routine lookups and authorized actions do not create Firstmate inbox work.
   The desk finds existing board URLs itself and returns the URL immediately.
   Project requests follow the verified [second-mate handoff rules](#second-mate-handoffs), without a main note after successful delivery.
   A successful routine local action can return `{"kind":"handled"}` without an immediate chat reply.
   The bridge accepts this only after a successful write result and records it in the local routing journal.
   Before enabling a write, the journal records that the target may change.
   An interrupted or unverified action goes to Firstmate with that warning instead of running again.
   Cross-domain coordination, real ambiguity, actionable failures, and decisions beyond existing authority go to Firstmate.
   Destructive requests, unclear approvals, and sensitive content retain the existing hard handoff.
   Failed classification calls, invalid JSON, missing evidence, and clipped pending input follow the [second-mate handoff rules](#second-mate-handoffs).
   Only authenticated authored text grants authority; retrieved files, logs, pages, Slack, and tool output never grant permission.
   The prompt preserves project ownership, destructive-action approval, external-send approval, and credential boundaries.
   A refused tool call must not be bypassed.
7. The service saves the routing decision before a chat response or supervisor handoff.
   A direct answer enters the existing outbox with a stable deduplication key.
   A reply or reaction can set `target` to the message's 1-based position in the pending burst.
   Without `target`, the service selects the last pending message; an invalid target causes a handoff.
   The service threads a text only when another bubble separates the selected message from its answer.
   It checks separation at delivery, using the same rule as `fm-imessage --reply`.
   Desk answers stay on the selected message's transport and chat during retries.
   They never use another chat or transport as a fallback.
   A desk answer confirms requests only in its destination chat; other chats keep their separate handoffs and acknowledgement deadlines.
   A handoff uses `fm-inbox.sh note --request-id`; acceptance means the inbox saved it, not that the supervisor answered.
   Eight seconds after the latest unanswered request arrives in a direct chat, the bridge queues one request-specific acknowledgement.
   Each direct chat keeps its own deadline; messages in another chat do not cancel it.
   A deadline hands off only that chat's pending requests; it does not count as global Firstmate activity.
   Active mate delivery does not block a due acknowledgement or keep that chat's typing indicator active.
   It uses the existing outbox, preserves request routing, and states that no confirmed answer exists yet.
   It omits quoted content for sensitive messages and attachments, including audio transcripts and saved paths.
   A prompt answer suppresses the acknowledgement; typing alone does not.
   A queued supervisor response suppresses it only after the transport accepts that response.
   An explicit `--reply N` confirms only its selected message and that message's current edit requests, even with `--no-thread`.
   Each queued response stores its covered request ids; later arrivals cannot become covered through equal timestamps.
   The acknowledgement targets the latest unanswered request, even when a newer request already has a targeted answer.
   An accepted initial card counts as a response, like an accepted text.
   Restart replay confirms an initial card from its saved acceptance; a later card edit does not confirm newer requests.
   A checked desk answer already in the outbox keeps its place instead of receiving a duplicate acknowledgement.
   Purely social bursts and muted chats receive no timeout acknowledgement.
   Inbox failures retry from the durable journal; each inbox command has a five-second deadline.
   Named keep: synchronous inbox filing remains serial; two stalled commands can block the event loop for about ten seconds.
   This can delay acknowledgements and typing cleanup beyond eight seconds; their timers resume when filing returns.
   The five-second limit applies to each command, not the entire batch.
   The local regression test checks eventual acknowledgement and typing cleanup after two command timeouts.
   Firstmate activity cancels a draft and hands pending requests to Firstmate.
   A new owner text or Firstmate activity also stops the remaining bubbles of a queued desk answer.
   The service records already sent bubbles in memory and completes the cancelled answer without sending the remaining bubbles.
   Startup drops restored model answers that have unsent text bubbles and hands their requests to Firstmate, without waiting for inbound catch-up.
   Firstmate and service sends keep their durable recovery.
   Each transport checks cancellation after preparation and immediately before sending.
   Cancellation does not remove uncertain delivery records.
   For a live desk answer with an uncertain send, the service checks available transport history before cancellation.
   Acknowledgements also check available history before cancellation, including after a restart.
   It keeps unresolved evidence in the completion receipt.
   Unavailable history cannot block later supervisor sends after cancellation.
   A history check that disproves delivery clears the uncertainty before the service decides whether to hand off.

Neither transport reports typing events from the owner, so only a new text starts the wait again.

When the owner edits a text on the Photon line, the service files `[edited] <new text> (was: <old text>)`.
The note wakes Firstmate.
Edits of known messages keep the original chat reference, even when the raw event uses a different chat identifier.
The service keeps his last 100 texts in memory for the old text.
If it does not know the old text, the note says so.
This can happen when the text came before the last restart.
spectrum-ts does not pass edits on, so the service reads them from its own event stream on the line's client.
An edit that the owner makes while that stream is down is lost.
The BlueBubbles line does not report edits: an edit there files no note.

The classification runner has a 45-second process timeout, but the unanswered-response deadline can cancel it sooner.
The voice pass uses the same desk model, no tools, and a separate five-second timeout.
It disables omp reasoning and uses Inception's `instant` reasoning level.
New messages and Firstmate activity cancel this pass through the same path as classification.
The voice call receives the original question and checked draft, not chat history or unvalidated fleet status.
The durable status reader has a separate 5-second timeout; a timeout causes a handoff.
A completed desk turn records its outcome in the private `desk.log`, including `handled` and successful tool-call ids.
The log also records read completion, typing start and stop, model start and result, inbox acceptance, and transport acceptance.
These events contain timestamps and message ids, not model output or credentials.
Typing events retain the originating message id when a newer message arrives before the transport operation completes.
`transport-accepted` records successful transport completion before delivery-progress or response-confirmation writes.
`response-confirmed` records routing confirmation and can repeat during recovery without another send.
`history-reconciled` records a delivery found in transport history, not a new send.
`card-update-accepted` records an accepted card edit separately from initial card delivery.
Transport acceptance is not proof of user-visible delivery; verify the receiving device for live delivery checks.

For a standalone text, both desks accept classification answers only from one complete JSON object whose `kind` or `decision` is `reply`.
The `answer` must be a non-empty string with no directive.
iMessage checks the existing source evidence before passing that answer to the voice call.
An action can occupy the whole trimmed output, any JSON `kind` or `decision` field, or the final line after prose.
Recognized actions are `REACT:<emoji>`, `TAPBACK:<emoji>`, `SKIP`, `HANDOFF`, and the verified iMessage `HANDLED` result.
A JSON tapback uses `{"kind":"tapback","emoji":"👍"}`.
An action never sends the surrounding prose.
A JSON iMessage tapback may include `text`, for example `{"kind":"tapback","emoji":"❤️","text":"nice!"}`.
The allowed text is `thanks`, `thank you`, `you're welcome`, `anytime`, `haha`, `nice`, `congrats`, or `love it`.
Capitalization may vary, and one final period or exclamation mark is allowed.
Only a verified social burst can use this text, which shares the reaction's target and durable outbox item.
The Instagram desk ignores this optional text.
The parser validates the complete emoji; quotes, braces, and extra characters cannot become part of it.
Repeated matching decision fields produce one action, while conflicts produce no direct model response.
All other classification output, including plain prose, mixed prose and JSON, and malformed JSON, produces no direct model response.
Each rejected draft records one short outcome without raw model text.
Suppressed drafts and rejected non-social reactions retain the existing single request filing, without an extra operator request.
Social reactions retain all original messages and the completion decision in the routing journal, without filing a request.
Photon, BlueBubbles, and the Instagram desk share this parser.

The service replays unfinished routing after a restart.
Completed routing records suppress repeated transport delivery.
Keyed outbox receipts in `outbox-done/` prevent a decided answer from entering the outbox twice after a crash.
The journal stores response confirmations separately from routing completion.
The outbox saves accepted bubble and reaction progress before recording response confirmation.
If a routing-journal write or sync fails, retries confirm that saved progress without sending it again.
Transport acceptance stops the desk's typing indicator before those writes.
It persists a keyed acknowledgement per burst; completed outbox receipts prevent replay after a restart.
Cancelling an acknowledgement before any possible delivery releases its requests and persists a new identity for the next attempt.
Journal replay rejects the cancelled identity, so a crash cannot revive it or suppress the replacement.
Restart recovery schedules acknowledgements for unresolved requests with saved receipt timestamps, regardless of their age.
If no response bubble was delivered and the desk response is definitely undeliverable, the saved burst ids cause one stable-id Firstmate handoff.
Dead-letter receipts recover that handoff if the bridge stops before its failure callback completes.
A prior uncertain send or reaction blocks this failure handoff, except when startup drops restored desk text as described above.
The outbox saves possible reaction delivery after all lookups, health checks, and capability checks, immediately before the mutation.
It retains that state across retries and restarts.
Read-only preparation does not add delivery uncertainty.
It does not clear uncertainty from an earlier reaction attempt.
For a combined social response, the service saves text delivery before attempting the reaction.
Reaction retries and restarts do not repeat the text or hand it to Firstmate after delivery.
Text deliveries use a stable outbox identity in memory, so restart recovery records each delivered reply once.
This also recovers a reply when the bridge stops after saving delivery progress but before recording memory.
Keep the journal, receipts, memory, downloads, and pending outbox together during backups or migration.

The basic-answer system prompt is `deskPrompt` in `apps/imessage/desk.ts`.
The owner's name and the two model names come from the config.

The service ignores texts from all other senders. It saves attachments in `~/.local/state/fm-imessage/attachments/` for Firstmate to open. That directory is private to the account (mode `0700`). The service also keeps the owner's latest text on each transport, with the time of the message (its own timestamp, or the time received when it has none), in `~/.local/state/fm-imessage/latest` (and `latest-<transport>`). After a restart, typing and command tapbacks target the newest saved text. A file from before the time was kept counts as the oldest.
The service replaces latest-message files atomically, including the direct-chat destinations described in [Choose the transports](#choose-the-transports).

### Second-mate handoffs

The desk reads `$FM_HOME/data/secondmates.md` at runtime.
Second-mate routing stays off when this file is missing, unreadable, empty, or contains an invalid entry.
Single-home installs keep their existing behavior.
Each entry uses the existing registry format:

```text
- web-mate - Website owner (home: /srv/website-home; scope: Website pages and browser layout; projects: website; added 2026-10-23)
```

Each mate needs a unique id, an absolute home path, and a non-empty scope.
The desk can make a separate model call to select a handoff target from these ids or `firstmate`.
A failed or rejected basic-answer draft can still reach this call.
Failed status reads or clipped handoff input go directly to Firstmate.
The desk sends work to a mate only when the model reports high confidence and exactly one matching domain.
It checks the whole pending burst, including recent context, rather than splitting related texts across mates.
Invalid output, low confidence, ambiguous requests, and work across several domains go to Firstmate.
Decisions, approvals, merges, destructive actions, external sends, credentials, and sensitive messages also stay with Firstmate.
Attachments, group chats, edits, and unsupported desk models keep their existing Firstmate handoff.

The sender is `fm-send.sh`, beside the resolved `fm-inbox.sh` executable, including an `FM_INBOX_CMD` override.
The service sets `FM_HOME` to the main home that owns the second mates as tasks and holds the routing table.
It passes the mate id and `[from captain via desk] <verbatim text>` as separate arguments, without a shell.
The sender uses the mate's existing inbox and normal acknowledgement recovery.
The desk checks the registered id, home, and complete scope before each send.
A missing or changed entry sends the remaining texts to Firstmate.

A successful delivery records `routed to <mate-id>` in the local journal and completes without a main inbox note.
A failed sender, missing command, or five-second delivery timeout hands the request to Firstmate.
The journal saves delivery uncertainty before calling the sender.
The existing sender retains acknowledgement tracking; recovery never blindly repeats an uncertain send.
A failed or interrupted send retains a warning so Firstmate checks the mate's inbox before sending again.
The sender runs asynchronously, so inbound messages and Firstmate commands remain responsive during delivery.
New owner text, Firstmate activity, and shutdown cancel the active sender and stop the remaining sends in that burst.
Inbox retries and service restarts never repeat a recorded mate delivery.

Firstmate activity still cancels an unfinished routing decision and sends pending work to Firstmate.
Direct short answers and social reactions stay unchanged, including evidence-backed questions about approval counts when a registry exists.
Delayed handoffs follow the [acknowledgement rules](#what-it-does).

## Upstream outages

The Photon service can be unavailable for minutes. It then answers `UNAVAILABLE` (gRPC) or HTTP 502 or 503.
The queue code is `apps/imessage/outbox.ts`.
Desk cancellation and restart exceptions follow the [routing recovery contract](#what-it-does).

- **The outbox.** Each send and tapback enters the private `outbox/` directory as one file before delivery.
  This includes Firstmate answers and direct desk answers.
  The service syncs each temporary file before its atomic rename, then syncs the queue directory.
  The service acknowledges the enqueue only after both syncs succeed.
  A failed directory sync can leave a renamed packet on disk.
  A keyed retry syncs the directory without adding another packet.
  During a transient outage, an active desk answer stays queued without a supervisor handoff.
- **Delivery.** One loop sends the oldest file.
  It archives keyed direct answers in `outbox-done/` and deletes other completed items.
  A failed send retries after 1 second, then 2, 4, and so on, up to 60 seconds, with jitter.
  Unknown errors also retry, so the queue keeps its order.
  After each accepted bubble, the service saves its progress.
  Delivery is at least once: a lost answer or a stop before saving progress can cause a duplicate bubble.
  If the reply target is gone, the service sends without a thread.
- **Downloads.** If an attachment download fails, the note says that the attachment could not be saved yet. The service records the message id in `~/.local/state/fm-imessage/downloads/` and tries the download again with the same waits. When the download works, the service files a second note with the saved path. If the download moves to the dead-letter folder (see below), the service files a second note with the message id that says the attachment is lost, so Firstmate stops waiting for a path.
- **Restarts.** The outbox and downloads survive a service restart on disk.
  Delivery follows the [routing recovery contract](#what-it-does), including its desk-text exception.
- **Typing.** Typing bubbles are best effort. A typing error is logged and never fails or delays a send.
- **Logs.** Each failed try writes one log line with the operation and the code, for example `outbox item 3 failed (try 4), next try in 6.2 s: UNAVAILABLE: ...`. A transient error never writes a stack trace.

Permanent errors also move an item out of the queue.
These errors include missing or expired messages and attachments (HTTP 404 or 410, gRPC `NOT_FOUND`).
They include invalid items (HTTP 400 or 422, gRPC `INVALID_ARGUMENT`) and files that do not parse.
The service moves the file to `~/.local/state/fm-imessage/outbox-dead/` (for a download: `downloads-dead/`).
It writes one log line and continues with the next item.
Nothing is dropped without a trace.
Retry only unkeyed items by moving their files back to the queue directory under new sequence numbers.
Never requeue a direct desk answer by hand; follow the [routing recovery contract](#what-it-does).
Delete an unkeyed item's file to drop it by hand.
Keep keyed receipts with the journal as [routing recovery](#what-it-does) requires.
An error that can be systemic (for example HTTP 429 or 500, or `PERMISSION_DENIED`) holds the queue in order while it retries.
The log shows each try.
`FM_IMESSAGE_RETRY_MS` sets the first wait in milliseconds (default 1000); the longest wait is 60 times that value.

## Desk memory

The desk remembers the whole conversation, after the design in [UniiChat: one chat that never ends](https://gist.github.com/VictorTaelin/91837951a5ce5b38f341ec1ba1df6449). The code is `apps/imessage/memory.ts`.

- **The log.** The service records owner texts, Firstmate texts and tapbacks, and desk texts and tapbacks.
  The records are in `~/.local/state/fm-imessage/memory/main/YYYY-MM-DD.jsonl`.
  The service never edits or deletes a record.
  Inbound records also keep their stable request id, so a repaired memory write does not repeat after another restart.
- **The tree.** In the background, the service compresses the log into a binary tree of one-line summaries of at most 512 bytes. A text that fits in 512 bytes is its own line. Two adjacent lines merge into one line, again and again. The nodes are in `memory/tree/YYYY-MM-DD.jsonl`. At most 3 compaction calls run at the same time, and they never delay a desk turn.
- **The view.** Each desk turn gets a list of lines that covers the whole conversation: recent lines are fine, old lines are coarse. The view grows by one line for each message. When it is larger than 64 KB, one batch merges lines until it is 32 KB or less. The view is in `memory/view.json`, and the service loads it at start.
- **Recent originals.** Each desk turn also gets up to 12 messages before the pending burst, oldest first, beside the summary view.
  JSON lines include only the message id, kind, and text for owner, supervisor, and desk messages.
  Text stays verbatim up to 500 UTF-8 bytes; longer text keeps its head and tail with a clipping marker.
  The block stays within 6,000 UTF-8 bytes and drops the oldest messages first.
  The prompt budget can drop more messages, including for JSON escaping with Inception.
  Pending messages stay in their separate latest-burst block.
  Recent originals work before summaries finish; zoom still opens full messages.
  Owner text supplies context, not evidence for a direct answer.
- **Zoom.** When a line is too vague, the desk calls `zoom(id, n)` to open the line into the two lines under it. `zoom(id, 1)` gives one message whole. A text that is not summarized yet shows as "(not summarized yet: zoom it)".
- **The input cap.** The initial view keeps the existing 180,000-byte omp budget and the smaller Inception input budget.
  These byte limits estimate token use; they are not exact token counts.
  The native tool runtime owns later request framing and context limits.
  The desk clips fleet status, long texts, and each zoom result (16 KB) to their head and tail.
  After its budget, zoom returns "context limit reached", so the model answers from what it has.
  The separate Inception voice request refuses serialized bodies above 100,000 bytes.
  Compaction uses the smaller budget below and does not clip source text.
- **Compaction size.** Each conversation starts with at most 2,048 bytes of context and 4,096 bytes of source text.
  Long messages use complete UTF-8 chunks; the model then merges their summaries.
  Each chunk and reduction task states the source message's kind.
  Retries share a 16,000-byte input budget, including prior replies and reserved framing.
  Each model call keeps its 60-second limit.
  Compaction requests Luna 6 (`openai-codex/gpt-6-luna`) with `--thinking=off` and `--service-tier=priority` (the Fast tier, requested but not observed).
  The configured desk model stays unchanged.
  In omp 18.7.0, thinking off omits the reasoning setting rather than explicitly disabling reasoning.
  The measured provider responses reported `serviceTier=default`, despite the priority request; some responses contained thinking blocks.
  The runner uses a private temporary cwd and explicitly sets `memory.backend: off` in an omp configuration overlay.
  The existing flags skip extensions, tools, skills, and rules; sessions preserve shortening turns.
  Inherited native memory work can delay exit after the model produces a valid summary.
  A stalled exit still fails the call at 60 seconds; a partial response is not accepted.
  Each saved model summary logs `compacted summary`, its range, and its byte count.
- **Compaction failures.** A failed node leaves the source messages, existing summaries, and view intact.
  All model compactions share one cooldown: 5 minutes, then 10, 20, 40, and at most 60 minutes.
  Three initial workers can finish after the first failure; recovery uses one worker until a model compaction succeeds.
  A continuous outage permits at most six failed node attempts in any hour, regardless of the backlog.
  New messages do not trigger an early retry, and desk replies continue during the cooldown.
  Short source messages still build without a model call, so later desk turns see their text during an outage.
  `memory/retry.json` saves the failure count and next allowed time with an atomic rename.
  A restart restores this cooldown before rebuilding unfinished nodes from the unchanged message log.
  Missing retry state needs no migration; the service creates it after the first failure.

The memory and routing journal hold owner texts on the host in private state.
Deleting only `memory/` does not erase this history; routing recovery restores missing inbound records.
For complete erasure, first finish every pending routing request, download, and outbox delivery.
Then stop the bridge through the normal service procedure.
Remove `memory/`, `routing.jsonl`, and completed outbox receipts in `outbox-done/` and `outbox-dead/` together.
This also clears local routing deduplication, so retain transport seen records and do not replay old message history.
Never erase these files while requests or uncertain sends still need recovery.

A memory error does not stop an outgoing send, a tapback, or a supervisor handoff.
The service logs the error.
An inbound memory-write failure hands the durable routing record to Firstmate instead of attempting a basic answer.
At start, the service skips a memory log line that does not parse.

## Instagram front desk

The Instagram desk uses the same [decision parser](../apps/imessage/desk.ts), not the iMessage routing rules.
`instagram-desk.service` runs `apps/imessage/instagram-desk.ts` and reuses the memory, runner, input budget, and timing helpers.
Its channel-specific prompt does not use iMessage direct routing.
It has no Instagram client.
It follows two logs of the [instagram-dm](../blueprint/skills/public/instagram-dm/SKILL.md) listener:

- `state/instagram-dms.jsonl` (`INSTAGRAM_DM_LOG`): one row for each new DM from the operator. Each DM restarts the quiet period, 8 seconds (`crewship_instagram_desk_quiet_ms`), or 60 seconds (`crewship_instagram_desk_reel_quiet_ms`) once the burst holds a reel link.
- `state/.instagram-dms/sent.jsonl` (`INSTAGRAM_DM_SENT`): one row for each `fm-insta-reply` text, tapback, and typing indicator, with `by`, the value of `INSTAGRAM_DM_ACTOR` (`firstmate` by default). Any row that is not `by: desk` stops the desk for that burst of DMs, like a Firstmate send on iMessage.

When the quiet period ends without a Firstmate action, the desk handles the whole burst in one turn.
The service sends only the selected action or `answer` with `fm-insta-reply --thread ID` and `INSTAGRAM_DM_ACTOR=desk`.
A desk reply does not stop the next desk turn.
A new DM or Firstmate action cancels a draft before delivery.
If the call fails or exceeds 45 seconds, the desk sends nothing; Firstmate already has the note.
A burst with two or more different reel links gets no model call.
After the long quiet, the service sends `got N reels` and one eyes tapback in one `fm-insta-reply` call.
The log records `batch got N reels` for that batch.

The Instagram thread keeps its memory in `~/.local/state/instagram-desk/memory/`; see [Desk memory](#desk-memory).
The private `~/.local/state/instagram-desk/desk.log` stores the time, message ID, and a short outcome without raw model text.
Each model turn records `reply`, `skip`, `handoff`, `react <emoji>`, or `skip (desk failed)`.
The service saves its position in each log.
After a restart, only rows from the last 60 seconds can trigger a desk turn.
Older rows fill the memory but do not trigger replies.
With no saved position, the service starts at the end of both logs.
The desk does not show a typing indicator.

Set `crewship_instagram_dm_operator`, and the playbook installs the unit with the listener. The settings are the `crewship_instagram_desk_*` variables in `blueprint/ansible/group_vars/all/instagram_dm.yml`: `model` (default `claude-haiku-5-5`), `owner_name`, `supervisor_model`, `quiet_ms`, and `reel_quiet_ms`.

## Set up the Photon project

Skip this section when `transports` is `[bluebubbles]`.

1. Sign in to the [Photon dashboard](https://app.photon.codes) and create a project with the iMessage provider. The free plan gives a shared line.
2. In the project settings, copy the project ID and the project secret.
3. Add them to the host's secret store, `~/super.env`, as these two lines:

   ```bash
   PHOTON_PROJECT_ID=...
   PHOTON_PROJECT_SECRET=...
   ```

   Edit `super.env` on the primary VPS, push it, and fetch it on the host, as [Shared credentials](secrets.md) describes. On a host without the shared store, add the lines to `~/super.env` directly and keep the file at mode `600`. A later fetch replaces that file.

See [Enable it](#enable-it) for credential loading and shell requirements.

## Use self-hosted BlueBubbles relays

A relay is a Mac that runs [BlueBubbles server](https://bluebubbles.app) and is signed in to Messages. It costs nothing per month and does not depend on an outside messaging service. You can run the same Apple Account on several Macs: the bridge uses them as one line, in the order of the config.

### Set up a relay

1. Make an Apple Account for the line. An account with only an email address and no phone number works: the owner texts that email address, and `imessage.owner` stays his own phone number.
2. On each Mac, sign in to Messages with that account.
   Download BlueBubbles server and copy the app into Applications, but **do not open it or enable automatic start**.
   Copy this repository onto the Mac.
3. Disconnect the Mac from all networks, then run this command from the repository:

   ```bash
   bash apps/imessage/bluebubbles-relay prepare
   ```

   The command creates `bluebubbles.yml` in the account's home directory with a random password and `proxy_service: "lan-url"` (all tunnels off).
   It refuses to overwrite an existing file or continue while BlueBubbles or a tunnel runs.
   A fresh server otherwise starts its default public Cloudflare tunnel before you can set the password.
   BlueBubbles [reads this file before startup](https://github.com/BlueBubblesApp/bluebubbles-server/blob/v1.9.9/packages/server/src/main.ts#L28-L36).
   `persist-config: false` [applies the settings synchronously](https://github.com/BlueBubblesApp/bluebubbles-server/blob/v1.9.9/packages/server/src/server/databases/server/index.ts#L154-L173), before services start.
   Do not create `config.db` yourself: [an existing database disables initial schema creation](https://github.com/BlueBubblesApp/bluebubbles-server/blob/v1.9.9/packages/server/src/server/databases/server/index.ts#L37-L50).
   Keep the file for every launch; its settings override the UI settings.
   Protect the file and the server logs: BlueBubbles logs configuration values, including the password.
4. Open BlueBubbles while the Mac remains disconnected.
   Give it Full Disk Access and Accessibility permission.
   Keep **Proxy Setup** on **LAN URL** during its setup.
   Read the password from `bluebubbles.yml`, then run this one-command check and enter the password at its hidden prompt:

   ```bash
   bash apps/imessage/bluebubbles-relay check
   ```

   The check requires no `cloudflared`, `ngrok`, or `zrok` process.
   It requires HTTP 401 without a password and with a wrong password, then HTTP 200 with the password.
   A failed check exits with a clear error; quit BlueBubbles and keep the Mac disconnected until you fix the cause.
   Do not continue until the check passes.
5. Limit port 1234 to the agent host with the Mac's firewall or your private network before reconnecting the Mac.
   Do not configure port forwarding or select Cloudflare, ngrok, or zrok.
   Run the same check after reconnecting and after every server update.
6. Enable the BlueBubbles Private API if you want typing bubbles, tapbacks, threaded replies, and read receipts.
   Plain texts and attachments work without it.
   The Private API needs System Integrity Protection partly off; read the BlueBubbles docs first.
7. On each relay, register a webhook to `http://<webhook_listen>/bluebubbles` with the "New Messages" event.
   Use the server's API and Webhooks settings or `POST /api/v1/webhook`.
   Without a webhook on that relay, inbound messages wait for the bridge's per-minute catch-up.
8. Make sure that the Mac does not sleep.
   Enable automatic start only after the safety check passes.

Add each password to `~/super.env` as [Shared credentials](secrets.md) describes, for example `BLUEBUBBLES_PASSWORD=...`. The host config names the variable, never the password.

### Choose the transports

First [enable the bridge](#enable-it). Then add `transports` and the `bluebubbles` block to the `imessage` block in `.local/host.yml`, and run `./ship.sh launch`:

```yaml
    transports: [photon, bluebubbles]   # in order; [bluebubbles] uses the relays alone
    bluebubbles:
      relays:                      # in failover order
        - url: http://<relay-1>:1234
        - url: http://<relay-2>:1234
          password_env: RELAY_2_PASSWORD   # optional; the default is BLUEBUBBLES_PASSWORD
      webhook_listen: <agent host address>:8766   # where the relays post their webhooks
```

`webhook_listen` must be an address that the relays reach and nothing else does, such as the agent host's address on your private network. To use Photon alone again, remove `transports` and the `bluebubbles` block.

The bridge uses these routing rules with one or both transports:

- **Sends.** Each send and tapback goes through the [outbox](#upstream-outages) first.
  A proactive send without `--reply` stays in the owner's latest direct one-to-one chat, on that chat's transport.
  An owner message in a group does not replace this destination.
  The bridge saves this destination in `latest-direct` for Photon and `latest-bluebubbles-direct` for BlueBubbles, under `~/.local/state/fm-imessage/`.
  Without a known direct destination, the command returns HTTP 503 and queues nothing.
  The command selects that chat when it queues the text.
  An outage on that transport holds the send in the queue; it does not move the text to another line.
  An explicit threaded reply tries its target's transport first.
  Only a provably unsent reply can use another transport.
  See [What it does](#what-it-does) for desk-answer routing.
  A timeout or an unreadable answer saves the possible transport and chat in `maybe`, with the attempt time.
  The outbox retries the item or reports a final error through its existing dead-letter path.
- **A retry after an unsure send.** BlueBubbles searches the original chat for the text.
  If the text exists, the bubble counts as sent; otherwise the bridge retries in its permitted transport order.
  Photon cannot check an unsure send, so the bubble retries only on Photon.
  A Photon item waits if Photon does not start after a restart.
  The saved state stays in the outbox file.
  A saved transport that is no longer configured is ignored.
- **Where a fallback text arrives.** A fallback send goes into the owner's latest conversation on that transport. Before he texts the BlueBubbles line, it goes to a new chat with his number from the line's Apple Account. Photon can only answer in a conversation that he started.
- **Replies, typing, and tapbacks.** See [Commands](#commands) for reply behavior.
  A command's read-only failure can use a fallback because no send has happened yet.
  Typing bubbles and command tapbacks target the latest text across transports, including after a restart.
  See [What it does](#what-it-does) for direct desk answers.
  A typing error never fails a send.
  A tapback and typing are best effort and never block the outbox.
  A tapback that is not delivered in 2 minutes (`FM_IMESSAGE_REACT_MAX_MS`, in milliseconds) moves to the dead-letter folder with one log line.
  The sends behind it go on.
- **Inbound.** The bridge reads both transports and applies [the routing contract](#what-it-does) to each stable request id.
  It selects the latest text by message time, or receipt time when the transport gives none.
  A late text does not replace a newer latest text.
- **Start.** The bridge starts all configured transports together, but waits only for the first transport before opening the local listener.
  Fallback transports and saved-message reads run in the background, so they cannot delay the local listener.
  Photon startup HTTP requests have a 3 second timeout.
  After Photon startup succeeds or fails, later requests keep their own deadlines, including token renewals.
  A transport that is still starting rejects sends without waiting.
  BlueBubbles retries through its existing health checks and per-minute catch-up.
  If Photon cannot start while another transport is set, the bridge logs one line and runs on the others until its next restart.
  Saved destinations from every configured transport remain eligible even when that transport cannot start.
  Older `latest` files also qualify when they identify a direct chat.
  Proactive texts for an unavailable transport stay queued until it runs again.

### How the relay set behaves

- **Health.** The bridge reads `/api/v1/server/info` on each relay at start and during health checks.
  Each check uses the relay password, has a 3 second timeout, and keeps the result for 10 seconds.
  The bridge logs one line when a relay goes down or comes back.
- **Private API.** Each health check reads the relay's `private_api` flag.
  When it is off, the bridge sends no typing or tapback request to that relay and sends replies there as plain messages.
  Typing and tapbacks use the next healthy relay with the Private API on, or send no request if none supports them.
  An unsupported tapback reports failure; see [delivery recovery](#what-it-does).
  Unsupported typing remains silent.
  The bridge logs one line per relay when it first finds the Private API off or when the flag changes.
- **Sends.** Text sends and read receipts go to the first healthy relay, then to the next one if it fails.
  Typing and tapbacks follow the Private API rule above.
  When all relays are down, the outbox keeps the item and tries again.
- **Reply separation.** The bridge reads the target's chat and message time, then checks ordered history on each healthy relay.
  A bubble from either side counts only when its message time is later than the target's time.
  Older history on a relay does not count; tapbacks and other chats do not count.
  A later bubble on any relay permits threading, even when the first relay has old history.
  Thread support follows the Private API rule above.
  A failed history read follows the [transport fallback rules](#choose-the-transports) if no relay proves separation.
- **No double sends.** Each outbox item keeps a client GUID, and each bubble sends with its own one (BlueBubbles `tempGuid`). If a relay may have sent a text but did not answer (a timeout, a server error, or an answer that cannot be read), the bridge asks the relays whether the text is in the chat before it sends that bubble again, on any relay or transport (see above). It looks for the same text from the line in the last minute or so. The relay that may have sent is asked first, even when its health check says it is down. Known limits: when that relay cannot answer, another relay can still send the text a second time; a text that reaches the other Macs through iCloud late can be sent twice; a text identical to one sent in the same minute counts as sent; and a text that may be out on Photon cannot be checked, so Photon sends it again (at least once).
- **Inbound.** Every relay posts its webhook.
  A webhook carries only the message GUID that the bridge acts on.
  The bridge reads the message back from a relay with the password, so a forged webhook cannot inject text.
  The bridge keeps the last 1000 message GUIDs in `~/.local/state/fm-imessage/bluebubbles-seen`.
  It records a GUID only after it durably saves the request or ignores the message.
  It ignores other senders, outbound texts, tapbacks, and other signals.
  If handling fails or the bridge stops before completion, the next webhook or catch-up retries the message.
  See [What it does](#what-it-does) for durable routing and duplicate suppression.
  At start and each minute, the bridge asks every reachable relay for the last 15 minutes of messages.
  It handles each unseen message.
  This recovers a missed webhook or restart gap if a relay is reachable within 15 minutes.
  It does not recover older messages that missed their webhooks.
- **Attachments.** The bridge downloads a file from whichever relay has it. The first try runs while the bridge handles the message, so it has the short bound of 15 seconds, body included, and never holds up the next message. If it fails or is too slow, the note says that the attachment could not be saved yet, and the download queue tries again with a bound of 10 minutes, like a Photon download. A download that is cut off fails as a timeout, and the queue retries it. The item moves to the dead-letter folder only when every configured relay was asked and every one answered 404 (or another permanent error). If a relay is down, or its download was cut off, the queue retries, so a relay that comes back is asked again. The same rule holds for reading a message.
- **Tapbacks.** BlueBubbles has six: ❤️ 👍 👎 😂 ‼️ ❓. A tapback with another emoji moves to the dead-letter folder.
- **Location.** `fm-location` works only with Photon.

## Enable it

The iMessage bridge and optional card tunnel use `/bin/sh` to source `~/super.env` and export its assignments before starting.
Use POSIX shell assignments, including `export KEY=value`, and quote values that contain spaces.
Neither service passes this file to systemd's `EnvironmentFile` parser.
Only source trusted content: shell commands in this file run as the service user.
The credentials never go into the repository, the unit, or `.local/host.yml`.

Add this block to `.local/host.yml`, then run `./ship.sh launch`. The `firstmate` profile must be on.

```yaml
crewship:
  imessage:
    owner: "+<country code><number>"  # the owner's phone number, E.164 form
    owner_name: the owner           # optional; this is the default; how the desk prompt names him
    desk_provider: omp              # optional; this is the default; or inception
    desk_model: claude-haiku-5-5    # optional; this is the default; mercury-3 with inception
    desk_reasoning: "off"           # optional; this is the default; the omp thinking level or Inception reasoning effort
    supervisor_model: ""            # optional; the model that runs Firstmate
```

See [What it does](#what-it-does) for model-identity evidence and handoff rules.

Apply installs these items:

- the service in `~/.local/share/crewship/imessage/`, with the latest spectrum-ts
- the unit `~/.config/systemd/user/fm-imessage.service`, mode `0600` because it holds the owner's number
- the commands `fm-imessage` and `fm-location` in `~/.local/bin`

The service listens on `127.0.0.1:8765`. To use a different port, set `FM_IMESSAGE_PORT` in a unit drop-in (`systemctl --user edit fm-imessage`) and in the environment of the commands. `FM_INBOX_CMD` overrides the inbox command, which is `<workspace>/firstmate/bin/fm-inbox.sh` by default.

The service is for the host's own commands (`fm-imessage`, `fm-location`) only.
Except during shutdown, it checks the header `X-Firstmate: 1` and requires `Host` to be exactly `127.0.0.1:<port>` before looking at the path.
It answers `403` if either check fails.
A web page open in a browser on the host cannot set a custom header without a CORS preflight, which the service never answers.
The `Host` check stops DNS rebinding.
So a page cannot send messages as Firstmate or read the location.
If you call the service with your own `curl`, add `-H "X-Firstmate: 1"`.

On SIGTERM or SIGINT, the bridge refuses new work and sends SIGTERM to its running desk, compaction, and inbox-status children.
During shutdown, the command endpoint and BlueBubbles webhook answer `503` before other request checks.
The bridge waits up to two seconds, then sends SIGKILL to children that remain.
It waits up to another 500 ms for those children to exit, then exits with status 0.
The unit sets `KillMode=mixed` and `TimeoutStopSec=10` so systemd kills remaining service processes if shutdown stalls.
See [Desk memory](#desk-memory) for compaction recovery after a restart.

For this desk update, main must apply the reviewed source after merge and verify the installed bridge files.
Pre-merge fixture checks do not complete this step.
Run the following commands from the reviewed checkout as the bridge account, during an approved service window.
Keep the existing unit, credentials, model settings, dependencies, and private state unchanged.
Do not run a full host apply or restart another service.

```bash
runtime=$(systemctl --user show fm-imessage.service --property=WorkingDirectory --value)
test -n "$runtime" && test -f "$runtime/bridge.ts" &&
systemctl --user stop fm-imessage.service &&
install -m 0644 apps/imessage/{bridge,bluebubbles,desk,inception-desk,transcribe,zoom}.ts apps/imessage/desk-tools.yml "$runtime/" &&
install -m 0755 apps/imessage/fm-imessage "$HOME/.local/bin/fm-imessage" &&
systemctl --user start fm-imessage.service &&
systemctl --user is-active fm-imessage.service
```

If installation fails, keep the bridge stopped until every listed file is in place.
Compare each installed file with its checkout source before verification.
Use isolated transport fixtures and synthetic owner messages to verify the installed entrypoint without contacting a real recipient.
Confirm real file reads, searches, system reads, and an immediate board-link reply.
Confirm direct answers and successful mate deliveries create no main inbox note.
Confirm untrusted retrieved instructions cannot authorize deletion or an external send.
Confirm ambiguity, cross-domain work, delivery failures, and out-of-authority decisions still escalate.
Keep installation pending until these checks pass against the installed files.

To turn it off, remove the block, then run `systemctl --user disable --now fm-imessage` and delete the unit.

## Commands

| Command | What it does |
| --- | --- |
| `fm-imessage 'text'` | Queues a plain message using the [proactive routing rules](#choose-the-transports), even when his latest text is a thread reply. Without an argument, it reads the text from stdin. Paragraphs that a blank line separates become separate chat bubbles. The lines of one paragraph, for example a list or a schedule, stay in one bubble. Before each bubble after the first, the typing bubble shows for 400 ms plus 25 ms for each character, 2.5 seconds at most. |
| `fm-imessage --reply N 'text'` | Targets the owner's Nth most recent text (1 is the latest). The first bubble sends plain if the target is still the last bubble in its chat at delivery. It threads only when a later bubble exists from either side; tapbacks do not count. See [Reply separation](#how-the-relay-set-behaves) for checks across BlueBubbles relays. A transport that cannot thread sends plain. The command picks the target when it runs, and the queued message keeps that target's id through retries and restarts. The service keeps at most 10 texts received since it started that were the newest text at that time. A text that arrives late (see [Inbound](#choose-the-transports)) is not kept. If the Nth text is not kept, nothing is queued and the command exits non-zero. Any other value of N queues nothing and exits with code 2. |
| `fm-imessage --no-thread 'text'` | Forces a plain send, even with `--reply N`, regardless of option order. |
| `fm-imessage --image PATH ['caption']` | Queues a photo (png, jpg or webp), then the caption as text bubbles. See [Send a photo](#send-a-photo). `--reply N` and `--no-thread` act on the photo as they act on the first bubble of a text. |
| `fm-imessage --typing` | Shows the typing bubble on a best-effort basis. See [the typing lifecycle](#what-it-does) for expiry and cleanup. |
| `fm-imessage --react '👍'` | Queues a tapback in the outbox, in order with the sends. The tapback goes on the text that was his latest when the command ran. |
| `fm-imessage --card '<json>'` | Queues a card: a link to a page with options to tap, a chart, a timeline, or a table. The argument is the card JSON, `-` for stdin, or a file. See [Cards](#cards). |
| `fm-imessage --help` | Shows the usage. It queues nothing. |
| `fm-location` | Prints the location that the owner shares with the line in Find My, as JSON. |

Use `--` before text that starts with a dash: `fm-imessage -- '- first item'`.
Place send options before `--`: `fm-imessage --reply 1 --no-thread -- '- first item'`.
All arguments after `--` are text, not options.

If a spectrum-ts upgrade changes access to the Photon client, the service logs a warning.
Until the bridge is updated, `fm-location` returns HTTP 503 and the service does not see edits.
Plain Photon sends still use the public SDK.
Explicit threaded replies can use a configured fallback because the bridge cannot check the latest bubble.

`fm-imessage` exits 0 only when the message is on disk in the outbox, and prints that it is queued. It exits non-zero when it queues nothing. An unknown option queues nothing and exits with code 2.

## Mute

To block new outgoing items, create `~/.local/state/fm-imessage/muted`.
`STATE_DIRECTORY` overrides the default state directory.
While that file exists, the bridge queues no outgoing item.
Items already in the outbox can still send.
Firstmate sends, desk answers, cards, photos, voice memos, and tapbacks all stay out of the queue.
Inbound texts still arrive, and their notes still reach Firstmate.
The bridge refuses send, reaction, card, photo, and typing commands with HTTP 503 and `nothing queued: muted`.
`fm-imessage` exits non-zero for these refused commands.
The bridge also refuses a command if mute starts while it reads the request.
When mute blocks a desk answer or tapback, the bridge stops typing and hands every request to Firstmate.
The bridge keeps each request until the inbox accepts its note, including across a restart.
The desk can still show typing while it classifies inbound text.
Refused photo and card commands leave no new files behind.
Remove the file to resume sending.

```bash
touch ~/.local/state/fm-imessage/muted
rm ~/.local/state/fm-imessage/muted
```

## Send a photo

`fm-imessage --image PATH ['caption']` sends one photo. The command gives the file to the service, which sends it with the spectrum-ts attachment path (`attachment()` in `space.send`). The caption is optional. Blank lines in it make separate bubbles, as in a text. The photo goes first, and the caption bubbles follow it.

- **Checks.** The command checks that the file is readable, that its name ends in `.png`, `.jpg`, `.jpeg` or `.webp`, and that it is 25 MB or less. The service checks the content, not the name, so a renamed GIF or a text file is refused. A refused photo queues nothing, and the command exits non-zero with the reason.
- **Downscale.** A photo with a side over 2048 px (for example, a 4K screenshot) is downscaled to fit 2048 px, in the same format and with the same proportions. The EXIF orientation is applied. Smaller photos go out unchanged. The service uses Bun's built-in `Bun.Image`, so the bridge has no new dependency and the host needs no image tool. If the result is still over 10 MB, the photo is refused.
- **Queue.** The photo is an outbox item like a text. The service saves the downscaled file in `~/.local/state/fm-imessage/outgoing/` (mode `0700`) and queues the item after the file is on disk. The retries, the order, the restarts, and the dead-letter folder work as in [Upstream outages](#upstream-outages). The service deletes the file after the last bubble of the item is sent. A photo that moves to `outbox-dead/` keeps its file.
- **Memory.** The desk memory records the send as `[image: name]`, then the caption. The name has the extension of the real format.
- **Transport.** Photos go over the Photon line only. The BlueBubbles code of the bridge has no attachment send. When the owner's chat is on BlueBubbles, the photo uses the Photon line's latest chat. If the Photon line is not running, the command exits non-zero with HTTP 503.

## Voice memos and audio

A voice memo or an audio attachment (`.caf`, `.m4a`, `.amr`, `.mp3`, `.aac`, `.wav`, `.ogg`, `.opus`, `.flac`, `.aiff`, or any `audio/*` type) is saved in `~/.local/state/fm-imessage/attachments/`, then transcribed on the host. `apps/imessage/transcribe.ts` runs `ffmpeg` to make a 16 kHz mono wav, then `whisperx` on the CPU with `int8`. No API is called.

The note reads `[voice memo, 4s] <words>`, then `(audio saved for Firstmate at <path>)`. The desk memory records the same text, so the desk sees the transcript. If the audio holds no speech, the words are `(no speech heard)`. If `ffmpeg` or `whisperx` fails or times out, the service logs the error, and the note still has the path and says `transcription failed`. If the file cannot be saved, the download retries as for any attachment, and the retry transcribes it.

The inbound loop waits for the transcription, so the next inbound message waits too (about 15 s on a warm host, up to 45 s on a cold start). Sends are not held up.

| Variable | Default | Meaning |
| --- | --- | --- |
| `FM_IMESSAGE_WHISPERX` | `~/.cache/watch/whisperx-venv/bin/whisperx` | The `whisperx` executable. The `watch` skill's venv has it. |
| `FM_IMESSAGE_WHISPER_MODEL` | `small` | The Whisper model name. |
| `FM_IMESSAGE_TRANSCRIBE_MS` | `120000` | The time limit for each of the two commands. |

## Cards

`fm-imessage --card` sends a card: by default, a Spectrum app bubble. A tap opens the card's page as a full-width sheet inside Messages, in Photon's free "Spectrum" iMessage app; the bridge serves the page. He installs that app once, from the App Store prompt in Messages. The code is `apps/imessage/cards.ts`.

```bash
fm-imessage --card '{"kind":"choice","key":"layout","title":"Board layout?",
  "options":["Short list, one screen","Cards with a mock each","Table with all details"]}'
```

Every card has `kind`, `key` (1 to 40 letters, digits, `.`, `_` or `-`), and `title` (up to 120 characters). Optional fields: `subtitle` (up to 200 characters), `hours` until the card expires (1 to 168, default 24), `app` (default `true`; `false` sends a link in place of the app bubble; see below), and `live` (default `false`: a tap opens the full sheet; `true` asks for the app's live view, which draws the page inside the bubble at a narrow width that Messages sets and the page cannot change). The kinds:

| Kind | Fields | The page shows |
| --- | --- | --- |
| `choice` | `options`: 2 to 6 texts | One button per option, A to F. One tap picks. |
| `bars` | `bars`: 1 to 30 `{"label", "value"}`, optional `unit` | A bar chart. With `"unit": "%"` a bar fills its track at 100; with any other unit, at the largest value. |
| `timeline` | `items`: 1 to 50 `{"when", "text"}` | A vertical timeline. |
| `table` | `columns`: 1 to 8 texts; `rows`: 1 to 100 rows of that length | A table. |
| `text` | `lines`: 1 to 60 texts of up to 200 characters | The lines of `fm-text-card`: `# x` starts a section, `- x` is a bullet, `k: v` is a row, and other lines are plain rows. |

A bad card queues nothing, and the command names the first bad field.

- **Pick.** A tap on an option files the inbox note `[iMessage card pick] <key>: <letter>. <option>`.
  The note wakes Firstmate.
  The desk memory records the note.
  The page shows the pick with a check.
  An app bubble also changes in place to "Picked B: ...".
- **Delivery.** A card goes through the [outbox](#upstream-outages), in order with texts, to his latest direct chat, like a proactive text. The desk memory records `[card <key>: <title>]`, never the URL. An outage retries like a text.
- **App bubbles.** The card uses spectrum-ts `app(url, {layout, live})` on the Photon transport. Photon's docs say that the app delivers the URL to the Spectrum extension on tap and opens it in Messages, so the view is the card's page. The page has no fixed width: it fills the sheet, and text, bars and tables reflow to it. spectrum-ts `app()` has no size or presentation option; the sheet is the full view, and the live bubble is the narrow one. The bubble's layout is the title and one status line (no trailing caption: without the app, Messages runs the two together). The service keeps the card session that the send returns, and uses it with `edit` for the change in place, also after a restart. Measured on the free shared line: Photon delivers the bubble with no error. Without the Spectrum app, his phone shows only a plain balloon with the layout text. Photon's pricing lists iMessage mini apps for the Business plan only. Any error other than an outage moves the card to `outbox-dead/`, files the note `(card <key> was not sent: <reason>)`, and the texts behind it go on.
- **Link cards.** With `"app": false`, the card is its page's URL as a plain text, which iMessage shows as a link preview from the page's Open Graph tags (`og:title`, `og:description`). A link card goes on any transport, and a tap opens the browser.
- **Mac.** The Spectrum app is for iPhone only. In Messages on a Mac, an app card stays a plain balloon with the title and the status line, and a tap does not open the page. Open the card on the iPhone, or send it with `"app": false` when he reads on the Mac.
- **PNG cards stay the default.** `fm-text-card --send < text` and `eta_timeline.py --send` send their PNG with `fm-imessage --image`. With `--card`, they first send a `text` or a `timeline` card, and send the PNG only when `fm-imessage --card` queues nothing (cards off, or an older bridge). Choice cards are always cards.
- **Page.** The page looks like an iOS view: the system font and text sizes, the system colours in light and dark mode, inset grouped rows of 44 pt or more, safe-area padding, and a pressed state with no tap delay. It has no script.
- **Page listener.** A second listener serves the pages. It listens on `127.0.0.1:8767` (`FM_IMESSAGE_CARD_PORT`), apart from the private command port. It answers only `GET /c/<token>` and `POST /c/<token>/pick`; every other request gets `404`. The command port does not answer card paths. Cards are off until `FM_IMESSAGE_CARD_URL` is set: then `/card` queues cards, and the bubbles open `<FM_IMESSAGE_CARD_URL>/c/<token>`.
- **Instagram webhook.** With `INSTAGRAM_DM_BACKEND=graph`, `INSTAGRAM_GRAPH_APP_SECRET` and `INSTAGRAM_GRAPH_VERIFY_TOKEN` set, the page listener also answers `/instagram/webhook` (`apps/imessage/instagram-webhook.ts`), even when cards are off. `GET` is Meta's verification: the right verify token gets the challenge, any other gets `403`. `POST` must carry a valid `X-Hub-Signature-256`; an unsigned or badly signed request gets `403` and files nothing. Each new DM from `INSTAGRAM_DM_OPERATOR` goes to `INSTAGRAM_DM_NOTIFY` first and then to `INSTAGRAM_DM_LOG`. A DM from any other sender files nothing, and the service logs its sender id once per DM. A refused note gets `500`, so that Meta sends the DM again; the mid stops a second copy. With the webhook on, the body limit is 64 KiB, not 4 KiB.
- **Tokens.** Each card has its own token: 256 random bits, base64url. The token is the only key to the card: no login, no password. A wrong, unknown, or expired token gets the same `404` page. A choice card takes one pick: a second pick gets `409` and files no note. If the inbox refuses the note, the pick is undone and the page says to try again. The service never logs a token and never prints one; `fm-imessage` prints only the key. The pages send `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, and a Content Security Policy that allows no script and no outside content.
- **Records.** Each card is one file, `~/.local/state/fm-imessage/cards/<token>.json` (the directory is private to the account). The service deletes a card file one day after the card expires.

### Publish the card pages

The bubble opens on his phone, so the page listener needs a public HTTPS address. Use a named Cloudflare tunnel, because a quick tunnel gets a new address at each restart, and the old cards stop working.

1. In the Cloudflare account that holds the domain, make a remotely managed tunnel (for example, `crewship-cards`). Give it one public hostname, for example `cards.example.com`, to `http://127.0.0.1:8767`. The catch-all rule stays `http_status:404`.
2. Make sure that the DNS record of that hostname is a proxied `CNAME` to `<tunnel id>.cfargotunnel.com`.
3. Add the tunnel token to `~/super.env` as `CARDS_TUNNEL_TOKEN=...`, as [Shared credentials](secrets.md) describes.
4. Add the `cards` block to the `imessage` block in `.local/host.yml`, then run `./ship.sh launch`:

   ```yaml
       cards:
         url: https://cards.example.com   # the public hostname of the tunnel
         port: 8767                       # optional; this is the default
         tunnel_token_env: CARDS_TUNNEL_TOKEN   # optional; this is the default
   ```

Apply then installs `cloudflared` and the unit `fm-cards-tunnel.service`, which runs the tunnel with the token from `~/super.env`, and sets the card variables in the bridge unit. The tunnel reaches only the page listener. To turn cards off, remove the block, run `./ship.sh launch`, then run `systemctl --user disable --now fm-cards-tunnel` and delete its unit.

## Plain messages and the shared line

See [Commands](#commands) for plain sends and explicit replies.
On Photon's free shared line, plain sends into the owner's conversation work.
A conversation that the service opens itself is refused ("Target not allowed for this project").
See [Upstream outages](#upstream-outages) for retries and permanent refusals.
Before the owner sends the first text, the commands fail with HTTP 503.

## Location is personal data

`fm-location` works only while the owner shares his location with the line in Find My. The location is personal data. Use it only when the work needs it. Keep it on the host: do not put it in a commit, an issue, a PR, a log, or a chat.
