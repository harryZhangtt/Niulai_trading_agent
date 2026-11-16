# Scheduler observability and resilient-session v2

**Status:** FROZEN IMPLEMENTATION PLAN  
**Frozen on:** 2026-11-07  
**Activation:** disabled; read-only planning evidence only  
**Dependencies:** schema-9 prompt custody/source candidate, provider conformance, future runtime acceptance

## Goal

Extend the existing shared scheduler rather than replace it. The scheduler must classify failures from the Mac control plane through network, provider, model/tool, business and email layers; survive restart without duplicating effects; distinguish a new attempt from an authoritative provider-session resume; detect timing and repetition anomalies; and expose bounded, privacy-safe fleet/session/mentor evidence in one read-only dashboard.

A healthy launchd process, gateway, heartbeat or HTTP endpoint is **not** evidence that an inference, business action or email completed. Those outcomes remain separate.

## Frozen safety invariants

1. Success requires verified terminal evidence.
2. Automatic retry requires durable proof that submission/effect did not occur, or an explicit idempotent/reconcilable capability.
3. Any headers/event/token/tool fragment after possible submission makes a cut turn incomplete/unknown unless an official session cursor supports authoritative resume.
4. Partial assistant output never enters completed conversation history and partial tool JSON is never executed.
5. Gateway restart is a control-plane transition; it cannot complete, cancel or retry an inference.
6. Process/service crash recovery converts `running` to durable `unknown`; it never resets work to ready.
7. Business/email effects require their own operation key, receipt and reconciliation.
8. Prompt artifact/binding, operation, attempt, result and reconciliation remain transitively bound.
9. Dashboard is read-only and never exposes prompt/evidence bodies, paths, credentials, raw exceptions, mailbox identities or provider thread IDs.
10. Provider routes remain disabled until source/live conformance and future-triggered acceptance pass.

## Universal failure contract

Add `FailureEnvelopeV2` alongside the conservative V1 reader:

- `layer`: `dns | socket | tls | http | gateway | provider_stream | model_turn | tool | business | email | process | os | launchd | host_control_plane`;
- monotonic `stage` and exact attempt/operation/session/gateway generation;
- `request_accepted`: `no | yes | possible | unknown`;
- `output_observed`: `none | headers | event | partial_turn | terminal_turn`;
- `effect_state`: `none | prepared | exposed | committed | possible | reconciled_absent | reconciled_present`;
- `terminal_authority`: bounded typed authority, never prose;
- `retry_class`: `safe_automatic | resume_only | reconcile_then_retry | manual | permanent`;
- stable code, typed protocol/process fields, retry/deadline/observation times and evidence reference.

### Failure matrix

| Layer | Examples | Default disposition | Safe recovery |
| --- | --- | --- | --- |
| DNS | NXDOMAIN, resolver timeout | validated config/NXDOMAIN permanent; temporary pre-connect retry | bounded DNS budget; scope circuit by host/resolver/profile |
| Socket | refusal/connect timeout/reset | proven pre-write retry; after write unknown | preserve write/acceptance phase |
| TLS | certificate/hostname/protocol/handshake | certificate/config permanent; transient pre-request retry | bind trust generation |
| HTTP | 408/409/429/5xx | retry only with non-submission authority/idempotency; otherwise unknown | persist Retry-After; one total budget |
| Gateway | unavailable/restart/upstream 502 | control-plane failure only | fence attempt; journal generation; restart/probe; reconcile inference |
| Provider stream | malformed/missing first event, gap, disconnect, missing terminal | after acceptance/event: unknown or resume-only | official cursor/session lookup only |
| Model turn | refusal, max tokens, invalid stop, server error | structured terminal failure or incomplete turn | no tools after incomplete/refusal/max-token boundary |
| Tool | partial input, denied, started/no result, duplicate | pre-execution no effect; after start unknown | ledger by turn/tool/schema/operation key |
| Business | validation/postcondition/commit uncertainty | pre-commit terminal/policy; post-commit unknown | transaction/outbox and reconcile |
| Email | reject, accepted/no readback, timeout after send | pre-send retry; post-submit unknown | logical delivery key, message ID, exact readback |
| Process/OS | spawn, signal, OOM, ENOSPC, sleep/clock rollback | operational failure; post-launch often unknown | generation proof, bounded teardown, quarantine |
| launchd/host | bootstrap, restart storm, stale heartbeat, lock conflict | control plane unavailable | sole ownership, recover running unknown, repair host separately |

### Required real-world cases

- **No-output 502 / `server_error`:** `output_observed=none` does not itself prove `request_accepted=no`. Automatic retry only with gateway non-dispatch proof or declared safe idempotency/reconciliation.
- **Mid-response `server_error` cut:** durable `unknown`, partial bytes evidence-only, no history/tool execution. Resume only with official same-session cursor; otherwise reconcile before a new attempt.
- **Gateway V8 fatal/restart:** record gateway generation/restart independently. `/health` or reconnect is control-plane evidence, not inference completion.

## Durable state extensions

### Shared scheduler

Extend provider contracts, schema and Engine with:

- transport observations and normalized V2 failure envelopes;
- gateway generation/events and one restart lease;
- provider session checkpoints bound to transcript/model/tool-schema/gateway generation and event cursor;
- incomplete tool-input and tool-effect ledger;
- availability observations that may affect health/circuits but never grant replay authority;
- anomaly observations and per-layer timestamps;
- parent deadline plus child budgets for queue, DNS, connect, TLS, headers, first event, stream gap, turn, tool, business, email, teardown and gateway lifecycle.

Keep three independent state machines:

1. slot: allocated → claimed → running → retry-wait/succeeded/failed/unknown;
2. inference: prepared → request-started → accepted? → streaming → terminal-verified/incomplete-unknown;
3. gateway: starting → ready → degraded → draining → restarting/quarantined.

`restart_gateway()` and `retry_inference()` are separate APIs and transactions.

### Mentor scheduler

Freeze a mentor schema v2 before UI implementation:

- separate immutable goal contract and public revision;
- complete work-order-byte fingerprint, not only ID/plan/acceptance hashes;
- explicit active candidate/cycle/attempt authority;
- durable `attempt_started`, `attempt_phase`, `attempt_finished`;
- typed `progress_assessment` and `supervision_assessment` events;
- privacy-safe failure class/signature;
- `blocker_opened`, `blocker_confirmed`, `blocker_resolved` lifecycle;
- heartbeat/lease for hung-attempt evidence;
- separate source, setup, runtime and delivery acceptance events;
- per-source freshness provenance.

Make `mentor/scheduler/projection.py` the canonical private derivation and `scheduler_view.py` the strict public redaction adapter. Remove the current unsupported `goal_drift: none` claim and align all valid terminal states (`rejected`, `inconclusive_budget_exhausted`, `expired`, etc.).

## Timing and anomaly model

Project server-grounded timing only:

- scheduled lateness, queue age, claim-to-start;
- DNS/connect/TLS/TTFB/first-event/inter-event/turn duration;
- retry delay/deadline/exhaustion;
- circuit state/probe age/oscillation;
- unknown fence age/reconciliation latency;
- process TERM/KILL/descendant cleanup;
- gateway readiness/restart rate/quarantine;
- heartbeat age, tick age, event-loop lag and worker saturation;
- tool/business/email commit/readback latency.

Timing states: `on_time | late_within_grace | late_outside_grace | missed | clock_skew | not_computable`.

Warnings initially affect dashboard attention only, never promotion or terminal state:

- unknown/pending external effect: immediate critical/blocking;
- binding/ledger contradiction: fail closed unavailable;
- no progress: information after 1, warning at half configured limit (minimum 2), critical at limit;
- repeated action: warning 2, change-approach/critical 3 unless verified evidence changed;
- repeated stable failure signature: warning 2, critical 3 when unchanged/permanent;
- failure-rate warning ≥50% after ≥3 cycles; critical ≥75% after ≥4;
- budget warning ≥80%, critical only exhausted;
- “hung” requires heartbeat/lease evidence, never age of an immutable historical record alone.

## Read-only dashboard v2

Keep the current dark-violet DESIGN.md authority and established components/tokens. Do not import an upstream visual system.

### Desktop layout

```text
┌ Workspace rail ┬ Scheduler                              Read-only  Refresh evidence ┐
│                │ MAC CONTROL PLANE                                                   │
│                │ service • heartbeat • watchdog • launchd • gateway generation      │
│                │ “Host health does not prove provider/business/email completion.”    │
│                ├──────────┬───────────┬─────────┬──────────┬────────────────────────┤
│                │ Current  │ Attention │ Unknown │ Retry wait│ Timing anomalies       │
│                ├─────────────────────────────────────────────────────────────────────┤
│                │ Search | scope | failure layer | evidence | timezone               │
│                ├────────────────────────┬────────────────────────────────────────────┤
│                │ FLEET / JOBS           │ SELECTED JOB / SESSION                     │
│                │ status, next, drift    │ Overview | Timeline | Failures | Evidence  │
│                │ six layer summary      │ Mentor plan* | Privacy                     │
│                │ bounded/paged rows     │ six lanes, chronology, recovery authority  │
└────────────────┴────────────────────────┴────────────────────────────────────────────┘
```

Mobile uses one document flow, two-column wrapping counters, no nested scroll, explicit Back/focus restoration and text-labelled states at 320px. RTL uses logical properties; machine timestamps may remain LTR.

### User journeys

1. **Fleet triage:** Mac/control-plane first, then current/attention/unknown/retry/anomaly counters and layer filters with one contextual live announcement.
2. **Session timeline:** select immutable session; show scheduled→claimed→provider→business→email chronology. Distinguish not-recorded, not-applicable, withheld and unavailable.
3. **Layered failure map:** host, scheduler, dispatch, provider, business, email rows with state, safe reason, freshness and recovery authority.
4. **Retry/reconciliation:** descriptive states only—scheduled/due/circuit wait/unknown fence/reconciled absent/present/replay forbidden/exhausted. No Run/Retry/Resume/Reconcile/Send buttons.
5. **Mentor preview:** frozen plan/goal revisions, criterion counts, active attempt, meaningful progress, bounded blocker/loop/anomaly state and separate source/setup/runtime/delivery acceptance. Any private-integrity failure yields whole-object unavailable.
6. **Privacy:** explain received/withheld categories, freshness and sandbox limits; never expose prompt/plan/evidence bodies, paths, raw hashes/signatures, provider IDs, recipients or exceptions.

### Wire/API shape

Introduce an isolated `schema_version: 2`, `scope: local_scheduler_observability` packet rather than widening v1. It contains:

- `control_plane` with service/watchdog/launchd/power/gateway evidence and freshness;
- `fleet` counts plus exact six-layer aggregate;
- paged `jobs` summaries with attention/timing/layers/latest session;
- session detail with bounded timeline, timing, retry/reconciliation, metrics, independent provider/business/email evidence, optional all-or-unavailable mentor preview and privacy metadata;
- strict warning codes and cursor bounds.

Exact adapters enforce six unique layers, UTC chronology, collection caps, server/client metric cross-checks, safe-code allowlists and all-or-unavailable mentor projection. V1 remains a separate compatibility adapter.

### Components/performance

Split fleet and session resources (`useFleet`, `useSession`) with exact query identities, AbortSignal, same-key retained data, one refresh per key, visibility-aware polling and no optimistic business state.

Use server pagination first (50–100 jobs). Do not virtualize ≤100 rows; add isolated virtualization only after measurement. Lazy-load Timeline/Failure/Mentor views. Use `useDeferredValue` for search, `startTransition` for nonurgent filtering, stable Maps/keys and measured memoization.

## Implementation phases

1. **Contracts first:** V2 failure matrix, gateway/session/tool state and scheduler packet schemas; privacy canaries and V1 conservative migration.
2. **Durable evidence:** Engine schema/tables/events, gateway restart lease, checkpoints, tool ledger, mentor goal/work-order/progress/blocker/failure/freshness events.
3. **Provider/host adapters:** exact DNS/socket/TLS/HTTP/stream/tool normalization; nested retry budget; gateway manager separated from dispatcher/launchd.
4. **Backend projection:** control-plane, fleet summary, session timeline, timing assessment, six layer projectors and canonical mentor projection.
5. **Fleet UI shell:** control plane, counters, filters, paginated semantic list and URL state.
6. **Session views:** outcome lanes, timeline/timing, failure map/recovery, mentor preview and privacy.
7. **Scale/accessibility:** measured virtualization, lazy chunks, mobile/RTL/keyboard/zoom/forced-colors/reduced-motion.
8. **Acceptance:** model-free fault gateway/restart campaign, full Python/Node/Playwright fixtures, inspected renders, then separately authorized provider/gateway/future-scheduled/email acceptance.

## Open-source reuse policy

Reuse concepts through local adapters only; do not add workflow runtime dependencies. Code-level candidates to pin before use:

- APScheduler: misfire grace/coalescing/max-running, not effect reconciliation;
- Temporal: durable history/heartbeat/timeout taxonomy and at-least-once lesson, not its runtime;
- Celery/Kombu/Dramatiq/RQ: ack/redelivery/retry/shutdown duplicate hazards;
- urllib3: connect/read/status counters, allowed methods and Retry-After;
- systemd/launchd: watchdog/start limits/process supervision, not inference state;
- pybreaker: vocabulary only; current durable generation/lease circuit is stronger;
- Temporal Web/Airflow/Prefect/Dagster/Bull Board: grouped timeline/layer/queue presentation only, never mutation controls;
- Netdata/Glances: control-plane freshness separation, no invented realtime data.

Before copying/adapting code, record immutable repository commit, tag relation, exact source/test files and license file/hash in a source ledger. No unverified README claim counts as implementation evidence.

## Verification gates

- Table-driven failure matrix including authoritative/no-authority 502 and partial stream/tool cases.
- Local deterministic fault gateway for DNS/socket/TLS/502/headers-close/SSE-close/partial tool/out-of-order terminal/gateway restart.
- Crash/restart campaign at every claim/request/event/tool/business/email boundary with two contenders and no unknown auto-replay.
- Effect sentinels proving zero duplicate tools/business/email; exact reconciliation and message-ID readback.
- Backend exact-schema/chronology/freshness/privacy tests.
- UI race/stale/filter/count/timeline/failure/recovery/mentor/privacy/mobile/RTL/keyboard/zoom/forced-colors tests.
- No private canary in API, adapter error, cache, DOM, trace or screenshot.
- 1,000-job behavior bounded and accessible.
- Future scheduled runtime/email acceptance remains separately required.

## Completion boundary

This plan is frozen, but implementation is staged after the schema-9 prompt-custody candidate stabilizes. It does not activate providers, gateways, launchd changes, scheduler mutations or email. A successful source/model-free implementation is not production acceptance; future intended-runtime evidence and exact email readback remain mandatory.
