# Holdings email attribution and partial recovery

Status update2026-10-31: the subsequent [recurring implementation](../../niulai-runtime/docs/recurring.md)
is active under explicit parallel-sender authorization. Scheduled partial, restart,
recovery/correction, exact readback and duplicate checks passed. The investigation
and proposal below are historical; the active domain work table reuses the
existing outbox DB and scheduler. No sole-sender transfer is claimed.

## Verified incident

The October 30 New York 13:00 delayed-check email was sent by the existing
ChatGPT Work daily price/holdings task. Its live conversation contains the same
partial result and send confirmation. The exact Gmail message was read; the
local Codex outbox contains no matching receipt. The local schedule ledger's
19:00 readiness run started at 23:00:01 UTC, after the email's 22:49:39 UTC send.
That allocation is readiness-only, not the recurring production mail sender.
Private message/task identifiers are retained only in
`.niulai-state/recovery-audit/holdings-origin-20261031.json`.

Observed price collection: nine of 66 symbol responses saved, six with raw data,
three failed and 57 not collected. The 87 enabled rules had no final evaluation;
missing results must not be counted as no alerts. The reported blockers were
canceled network approval and proxy `403` failures. This establishes the failed
execution boundary, not the underlying reason for that cancellation/proxy policy.
The holdings read succeeded; valuation remained partial on its own terms.

Another same-day task wake reported `outside_slot` at 12:44 New York time and
did no work. The later wake performed the delayed price check. The timing gap
is observed; its scheduler cause has not been established from current schedule
configuration. Do not label it a proven timezone bug.

## Existing components to reuse

| Responsibility | Existing owner | What remains missing |
| --- | --- | --- |
| Durable due tickets, generation checks and source-failure cooldowns | `shared/research_sources/store.py`, `cache.py` | A price-report-specific requirement/checkpoint binding |
| Wakes, serialized resource ownership and bounded attempt retries | `shared/job_runtime/engine.py`, `service.py` | A deliberately admitted recovery allocation/adapter |
| Exact immutable message, one claim and uncertain-send reconciliation | `niulai-runtime/niulai_runtime/delivery.py` | A correction identity linking the original partial message to the completed price component |
| Report/source semantics and missing-symbol frontier | Niulai business adapter | Restore and verify current cloud-owned state without creating competing owners |

The due tickets are a persistent backlog, not an autonomous consumer or a complete
leased MQ. The shared scheduler currently retries replay-safe work only within
its configured attempt limit and slot window. Neither automatically reopens a
partial report after that window. No Redis, Kafka, new polling daemon or second
general workflow database is needed for the proposed thin adapter.

## Proposed recovery contract

Persist the original report/slot identity, rule/config revision, source contract,
price cutoff, successful source/checkpoint references, missing-symbol frontier,
next-check time and stable generation. Preserve successful holdings. Attempts
receive new attempt IDs but retain the logical request identity; changed rules
or cutoffs require an explicit new revision/rebase.

| Observed condition | Next action |
| --- | --- |
| Timeout, connection reset, HTTP 429 or transient 5xx | Bounded retries per wake; persist a later due check with increasing delay/jitter, respecting Retry-After |
| Valid response lacks required data or publication is pending | Wait for data; resume missing work and revalidate timestamps/coverage |
| Approval cancellation, denied access, credentials or proxy-policy 403 | Persist `waiting_access` without repeated dispatch; resume after verified access/policy change or an already-authorized equivalent provider path |
| Source unsupported, delisted or permanently unavailable | Retain a visible terminal gap; do not wait indefinitely for nonexistent data |
| Delivery outcome unknown | Reconcile the exact Gmail message before another send; preserve the outbox fence |

A scheduler tick should perform a cheap local due scan before starting a model.
No due work means no model call. Admit one bounded attempt under existing
resource ownership, reuse verified receipts/cache and persist the next due time
when incomplete. Suggested delayed checks are minutes apart, capped at roughly
an hour; exact limits belong in reviewed runtime policy. This is persistent
waiting with bounded executions, not an unbounded busy retry loop.

Expired intraday work cannot become a new live alert because a later quote
exists. Preserve the failure and use explicitly dated historical evaluation
where the accepted policy permits it. Never backdate a current quote, rejuvenate
stale data with a fetch timestamp or invent a directional crossing.

## 补发 and sender ownership

Send an initial partial report once if that is the established notification
policy. When missing required price data and rule evaluation become complete,
prepare one correction referencing the original message/period and actual data
times. Derive its delivery key from the original identity and correction
revision/content digest. Repeated wakes must find that same prepared/accepted
correction. Do not repeat successful holdings reads solely for a price failure.

Newly composed Codex mail must start with `[CODEX]`; corrections also say `补发`
and name the original period. Root `AGENTS.md` records this procedural rule;
producer-level enforcement still needs adoption and verification. Historical
outbox and exact-parity test subjects remain unchanged.

The ChatGPT task still owns production sending. A staged Codex adapter must not
activate another production sender. Activation requires verified state/ledger
handoff and a sender-ownership decision. The user was asked whether to retain
that sender or move recovery/delivery to Codex; no answer was inferred.
This investigation does not claim successful price recovery or 补发.

## Acceptance before activation

Exercise partial retrieval/checkpoint, restart, delayed availability, access-
blocked waiting, unchanged-input resume, changed-input rebase, full evaluation,
one correction, repeated-wake deduplication and unknown-send reconciliation.
Use synthetic failure cases and a real future-triggered scheduled Codex session
for the admitted live scope. Verify message/readback under the workspace runtime
acceptance contract before claiming production recovery works. A saved due
record or passing shell test is not an active recovery service.
