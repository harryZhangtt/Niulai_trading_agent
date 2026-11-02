# Recurring combined email

The 2026-10-31 user instruction explicitly authorizes Codex parallel production
sending while the ChatGPT task remains active. This is not sender cutover.
Local durable delivery identity remains the original portfolio-email key;
independent cloud/local ledgers cannot deduplicate each other's deliveries.

`jobs/daily-business.json` allocates NY13:00/19:00 with60-minute grace and a
five-minute recovery scan. The domain adapter additionally requires a real XNYS
session, actual current slot, strict private policy, enabled saved workflow role,
and an explicit owner-bound private parallel-authorization receipt. Source JSON,
SQLite inputs and revisions are frozen per work item. No clock is backdated.
The checked-in allocation stays disabled for safe redeployment; the configured
private active allocation and host receipts establish actual activation.

`daily_work.py` adds one indexed domain table to the existing outbox database,
not another broker/service. The shared scheduler owns execution and auth-cache
serialization. Domain work owns branch checkpoints and120/600/1800-second data
rechecks, at most4 acquisitions and within the original60-minute deadline.
No-due scans return before invoking a model. Permission/auth403 blocks wait for
an actual dependency change; unknown Gmail outcomes require reconciliation.
Expired intraday work is recorded expired and never satisfied by19:00.

`daily_prices.py` stages the preserved parser/classifier privately. First
production evaluation is live; recovery uses the original cutoff in replay mode,
retains raw provenance and reuses valid symbol checkpoints. Production history
persists across slots in`.niulai-state/databases/daily-prices.sqlite`. Collection
has a180-second budget,8-second individual reads,3workers and90-second PDF budget.
Missing names remain rows. The parser retains session, currency, split and rule
validation. Invalid or missing quotes are never converted to zero/false.

The native host obtains fresh authenticated Sites context for the existing Tiger
bridge. No service bearer is portable or persisted. Broker credentials remain
with the existing owner-private durable store, exclusive lease/checkpoint and
crash fence. Credential uncertainty is reported, not automatically repeated.
Ready holdings are reused for price recovery.

`daily_report.py` snapshots finalized branches per initial/correction revision,
uses the preserved combined composer and includes every price group, every
holding P&L row and2actual PDFs. Unavailable holdings produce unknown values and
an offline-readable failure PDF.13:00 current holdings/assets and prior completed-
session P&L are labeled separately.19:00 targets the current completed session.
Every new subject starts`[CODEX]`; partial is explicit.

The host verifies Gmail's actual current profile against the private requested
recipient. Prepare persists immutable MIME; claim permits one send. Save actual
message ID before exact raw readback of subject, HTML and both PDF bytes.
Sending/unknown and accepted-but-unverified records require reconciliation.
Completed data recovery can produce one distinct`补发` naming the original email,
without changing the original payload or refetching successful holdings.

After the v3 direct-send handoff returned INVALID_ARGUMENT, the same canonical
payload was accepted by native Gmail draft creation and exact raw parity.
The repaired path prepares the outbox, creates only this run's authorized email
draft, verifies its complete raw MIME, binds its immutable draft ID/digest, then
claims and sends by draft ID. Draft failures occur before the send claim. Both
draft and sent readbacks use bounded noncanonical TTY capture: ordinary getpass
line buffering truncates large records on macOS. Old unknown sends remain held;
this change never resets their outbox entries or reuses their test identities.

Use the project business interpreter, both workspace source roots in PYTHONPATH,
PYTHONDONTWRITEBYTECODE=1 and private TMPDIR. CLI operations and native connector
sequence are in`jobs/daily-business-prompt.md`. Sites responses stay only in RAM
and hidden TTY input. Do not place credentials in commands, config or logs.

Private deployment files:

- `.niulai-state/config/daily.json`: strict production policy and original
  automation/recipient identity.
- `.niulai-state/config/parallel-authorization.json`: exact explicit user
  instruction, owner/automation binding and timestamp;0600, not a cutover receipt.
- `.niulai-state/daily-inputs/versions/`: immutable dated imports;`current/`
  selects deployed inputs. Preserve prior versions.
- `.niulai-state/daily/`: work reports, raw observations, immutable per-mail
  snapshots and exact Gmail readback. Keep account data out of source.

The supplied migration inputs predate the latest cloud email. Refresh from the
named authoritative Library files is tracked separately; never label imported
v30 as a fresh authority export. A later sole-sender cutover still requires
latest cloud/outbox reconciliation, refreshed workflow/rules/databases/portfolio,
verified old-sender disablement and single-sender rollback.

Acceptance uses a future once allocation with this same recurring prepare/verify
adapter, prompt, branches, report and outbox, in a test-only dedup namespace.
Record candidate fingerprints and native Gmail readback. Also check branch-
failure/correction, duplicate and restart behavior. Unit tests alone do not prove
scheduled activation or perpetual stability. Actual evidence belongs in the
private runtime-acceptance record.

Test-only fault injection affects the first price acquisition of a separate
acceptance work item. A second future invocation of that same item fetches real
missing sources, reuses successful holdings and emits one correction. Production
cannot enable this injection. Final summaries require source_dates as ISO-date
arrays; independent source/outbox/readback checks remain authoritative.

For an uncertain send, an operator can read the exact matching Gmail Sent item
and run`reconcile --message-id ID --readback PRIVATE_RAW_FILE`; canonical MIME
parity is required before accepting it. This never resets an outbox send fence.
Receipt recording/readback remain available after production is disabled.

Rollback disables the two private business allocations and reloads the existing
service, preserving outbox, reports and credential fences. The existing ChatGPT
sender remains active during this parallel-run rollback.
