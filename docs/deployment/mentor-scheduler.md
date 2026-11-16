# Mentor scheduler work orders (candidate)

Status: atomic representation, bounded ephemeral live-model runner, isolated live
cycle and controlled failure campaign implemented and verified. A future installed
once allocation did run, but failed at the service-process dispatch boundary before
any model process or provider thread; it was reconciled as definitely not dispatched.
Runtime acceptance is failed, its result email is pending, and replay is not
authorized. This is not dispatch repair or a successful installed live cycle.
Provider-session resume is not implemented. The mentor skills remain procedures,
not a daemon.

## Ownership and reuse

The capability reuses `shared.job_runtime.Engine` for due slots, claims, retries,
resource serialization and unknown-outcome fences. Mentor-owned code lives in
`mentor/scheduler/`:

- `contracts.py`: strict JSON work orders bound to frozen plan and acceptance bytes.
- `state.py`: owner-private, append-only logical-session events and atomic head.
- `supervision.py`: meaningful-progress, loop, holdout and promotion decisions.
- `projection.py`: canonical read-only status derived from validated state.
- `cli.py`: bounded table/detail/JSON rendering of that projection.
- `runner.py`: serialized, journaled, read-only ephemeral model cycles with hard
  verifier timeout, no blind replay and crash reconciliation.
- `job_adapter.py`: opt-in installed-runtime bridge bound to the service-captured
  profile, STOP event, exact candidate manifest and Engine attempt identity.

A logical mentor session may contain multiple ephemeral provider thread IDs. This
is deliberate: the current scheduler model adapter invokes `codex exec --ephemeral`.
No code here claims that a provider conversation is resumed.

## Work-order contract

The dependency-free input format is strict JSON. Unknown and duplicate keys,
non-finite numbers, naive timestamps, escaping/symlink paths, oversized bound
files and hash drift fail closed. A work order declares:

- stable work-order and logical-session IDs;
- workspace-relative plan and acceptance paths plus SHA-256 digests;
- aware start/end timestamps, per-turn timeout and maximum turns;
- no-progress, repeated-action and intervention bounds;
- mandatory variant recording, variant/reused-evaluation limits and forbidden
  worker access to protected holdouts;
- required event evidence, no pending effects and frozen acceptance binding.

The acceptance file is itself strict JSON containing unique criterion IDs and
critical flags. Plan or acceptance edits require a new accepted revision. The
worker cannot alter frozen files in place to pass. Completion requires an existing,
bounded, non-symlink verification artifact that binds the work-order ID and
acceptance digest, reports `accepted`, and records `satisfied: true` exactly once
for every frozen criterion. Its actual SHA-256 is stored and revalidated; model activity or a caller-supplied
boolean/digest is insufficient. This atomic slice validates artifact binding and
completeness, not producer independence. The later runtime adapter must make the
verification location unwritable by the worker and record the trusted verifier's
receipt before this artifact can support live acceptance.

## Durable state and recovery

Session state belongs in an ignored workspace-local runtime directory. Every event
is exclusively created, fsynced and hash chained. `head.json` is atomically
published only after the event. On load, every mutable head projection is rebuilt
from the immutable ledger. Missing, orphaned, reordered or malformed events fail
closed for reconciliation.

Failed/unknown cycles and all variants remain append-only evidence. Worker events
must occur inside the declared window with monotonic timestamps. Durable counters
enforce no-progress, no-progress repetition, intervention, variant and reused-test
limits; repeated actions that add verified evidence remain allowed. A cycle with a
pending effect changes the session to `blocked_pending_effect`; no provider turn,
cycle or intervention can continue until an explicit confirmed/failed resolution
is appended. Exact intervention retries are idempotent; conflicting reuse fails.
Completion is final.

All state check/append transitions use an owner-private per-session file lock, so
concurrent exact intervention retries consume one event and return one revision.

A crash after an event fsync but before head publication leaves one valid orphan.
The owner-authorized recovery operation accepts exactly one fully written, correctly
chained next event and deterministically republishes the replayed head. Malformed,
conflicting or multiple orphan tails remain fenced for manual investigation.

## Meaningful progress and overfitting controls

Progress requires new verified evidence: a criterion, validated artifact, narrowed
root cause, resolved hypothesis, source-backed uncertainty reduction, reconciled
unknown effect or proven blocker. A progress-bearing cycle must reference a strict
artifact bound to the work order, plan, acceptance digest and cycle. Every evidence
ID in that artifact binds an existing bounded evidence file and its actual SHA-256;
replay revalidates all bytes. The reducer derives progress only from IDs never
consumed by an earlier cycle. There is no worker-supplied progress boolean or bare
ID API. Narration, planning, a tool call or an unchanged repeated action without
new verified evidence is not progress.

The deterministic supervision layer also enforces intervention/variant budgets,
evaluator-only holdout access, matched cases and budgets, required ablations and
three verdicts: accepted, rejected and inconclusive. Missing evidence is
inconclusive; an observed frozen-criterion violation is rejection for that gate.
Elapsed time or a retry count alone never proves an architectural failure.

## Read-only CLI

The CLI consumes the canonical projection; it does not dispatch, edit, enable,
retry, reconcile or send:

```sh
python3 -B -m mentor.scheduler.cli --state <projection.json>
python3 -B -m mentor.scheduler.cli --state <projection.json> \
  --work-order-id <id>
python3 -B -m mentor.scheduler.cli --state <projection.json> --json
```

It distinguishes scheduler state from task state and shows gates, cycles,
interventions, variants, time remaining, goal drift, holdout/promotion and email
status. Input is size/row/text bounded, non-symlinked and stale/future checked.
Prompt, credential, receipt and arbitrary path fields are not accepted. Narrative
fields containing AWS IDs/secrets, Basic/Bearer auth, cookies, private keys, JWTs,
provider tokens or high-entropy token material are fully redacted; unsafe structured
status fields fail closed without echoing their input.

## First-class read-only scheduler UI

The existing local scheduler route at <http://localhost:7270/scheduler> recognizes
only the fixed `mentor.scheduler.job_adapter:prepare` provider. It does not import
an adapter named by a request. `mentor/scheduler/scheduler_view.py` requires the
exact installed adapter-config keys, the fixed `synthetic_bindings_v1` verifier,
and matching work-order/logical-session/change/job identities. Work order, plan,
acceptance record, canonical head and scheduler ledger inputs must remain inside
the workspace, owner-private, regular and non-symlinked; SQLite access is
read-only and query-only.

The public mentor schema is intentionally smaller than the private evidence. The
completed UI presents nine bounded groups: work order/window; scheduler/dispatch;
session; progress usage and all limits; safeguards and the replay-safe versus
replay-authorization distinction; six named acceptance gates; evaluation and
overfitting controls; runtime acceptance/model-turn/email status; and the recovery
timeline. It exposes no prompt, plan body, criterion/evidence body, recipient,
attempt/slot/thread ID, hash, path, credential or saved output. Identity conflicts,
unsafe permissions, symlinks, malformed evidence or unexpected enum values replace
the complete inner projection with the exact unavailable sentinel. A valid outer
partial scheduler response remains distinguishable and does not imply success.
The page and API cannot dispatch, edit, enable, retry, reconcile, authorize replay
or send email. See [the scheduler UI runbook](scheduler-ui.md).

## Sequential verification ladder

Later stages may run only after the prior stage passes with evidence bound to the
same candidate fingerprints:

1. Contract units: strict schema, hashes, paths, timestamps and budgets.
2. State units: append-only events, atomic head, projection rebuild and effect fence.
3. Supervision units: progress, loops, budgets, softening, holdout and promotion.
4. Atomic integration: contract → supervision → ledger replay → digest-bound
   promotion → canonical projection → CLI; forged heads/decisions fail closed.
5. Engine integration: temporary real `Engine`, deterministic due `once` slot,
   one claim and one cycle, no duplicate dispatch, plus a crash after mentor-ledger
   publication that leaves Engine `unknown` and mentor `blocked_pending_effect`.
   A private reconciliation journal validates slot/attempt/effect identity, hashes
   one real evidence file, applies one shared outcome/receipt to both ledgers and
   resumes safely when Engine commits before mentor state. Mentor effect activation
   has no public store method; it requires the coordinator's module-private
   capability, preventing callers from resolving the two ledgers inconsistently.
6. Isolated live model: passed for `mentor-live-isolated-20261104-v2`; one configured
   read-only ephemeral turn, one provider thread, one durable cycle, two evidence
   bindings and no pending effect. Candidate hashes/bindings/journal were reopened
   independently. This does not prove installed scheduling or email.
7. Failure campaign: passed 7/7 in `mentor-failure-campaign-20261104-v1` for permanent
   loop, retryable transient provider failure, checkpoint crash, unknown-effect
   reconciliation, acceptance softening, repeated evaluation and window expiry.
8. Full future-triggered E2E: installed scheduler, intended runtime/model/tools,
   independent frozen-criteria verification, private acceptance record and exact
   readback of the configured-owner `[CODEX]` result email.

The final gate follows `runtime-acceptance.md`. Local tests, a manual model run,
scheduler registration, a successful wake or an email by itself cannot accept a
major runtime change. Execution must pass and email synchronization must be
verified. No live stage or email is authorized merely by this candidate source.

The first stage-8 attempt,
`mentor-scheduler-runtime-20261105-v1`, did not pass. Its future once slot started
3.416 seconds late and failed in 0.041889 seconds at the service-process dispatch
boundary. Reconciliation found no model process/thread, mentor attempt journal,
mentor/service run directory, transport receipt, turn, notification or pending
effect, and classified the attempt `definitely_not_dispatched`. The preserved
Engine error is `DISPATCH_EXCEPTION_OUTCOME_UNKNOWN`; the reconciled slot is
failed with `OPERATOR_RECONCILED`. Acceptance is failed, result-email status is
pending and no replay is authorized while the root cause remains unresolved.
Neither this reconciliation nor its UI projection is execution of the changed
capability.

## Current verification

The exact focused UI/provider check run on2026-11-05 was:

```sh
PYTHONPATH="$PWD:$PWD/niulai-runtime" PYTHONDONTWRITEBYTECODE=1 \
TMPDIR="$PWD/ui/runtime/tmp" .niulai-state/.venv/bin/python -B -m unittest \
  mentor.tests.test_scheduler_view shared.job_runtime.tests.test_dashboard -v
```

The final command set passed28/28 Python backend/Niulai cases and10/10 Node
scheduler/server cases. Datasource typecheck passed, the production build completed
with98 modules, and the full scheduler Playwright suite passed12/12. These checks
cover the fixed provider's bounded schema and privacy failures plus completed
frontend rendering of all nine grouped evidence areas, the exact unavailable
sentinel/valid outer partial distinction, malformed mentor rejection and bounded
mobile/RTL/keyboard behavior. A separate read of the preserved candidate produced
`REAL_MENTOR_PROJECTION_OK` with the exact failed/reconciled/not-dispatched/
email-pending/no-replay state above.

The guarded live pass allowed31 read-only requests and observed zero blocked or
write requests, non-loopback requests, unknown API/output requests or page errors;
all grouped markers were present. Nine static private evidence files remained
byte-equal, and24 recent UI artifacts had zero credential-category scan matches.
This is grouped projection/UI and containment evidence only. It sends no email,
does not repair or replay the failed future attempt and does not establish runtime
acceptance.

The broader foundational atomic-suite command is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest \
  mentor.tests.test_scheduler_contract \
  mentor.tests.test_scheduler_supervision \
  mentor.tests.test_scheduler_cli \
  mentor.tests.test_scheduler_integration \
  mentor.tests.test_scheduler_runner \
  mentor.tests.test_scheduler_job_adapter \
  mentor.tests.test_scheduler_view \
  shared.job_runtime.tests.test_runtime_adapter -v
```

The repeatable suites are model-free and send no email. One separately recorded
isolated live cycle has passed. The installed future allocation described above
failed before model dispatch; it did not execute a mentor turn. Independent final
acceptance and exact-readback result email are absent, and the failed slot must not
be replayed without authorized reconciliation and a repaired, newly verified
candidate.

## Pure two-slot scheduler-resilience candidate (disabled)

`mentor/scheduler/resilience_candidate.py` is a pure builder/validator and
`mentor/scheduler/resilience_preflight.py` is a pure read-only assessor. Neither
discovers the host, reads or writes files, materializes configuration, registers a
job, invokes a provider or mutates runtime. The frozen candidate record is under
`mentor/runtime/scheduler-resilience-mvp-20261109/`; its allocation contains exactly
two sequence slots (`2026-11-14T02:00:00Z` and `2026-11-14T03:00:00Z`), two maximum
turns and ephemeral provider threads, 10,800 seconds grace and `enabled:false`.
These past timestamps are frozen candidate data, not a schedule to replay.

The builder requires exact canonical work-order/allocation/manifest shapes, UTC
times strictly inside one bounded window, one immutable source hash per canonical
workspace-relative path, exact plan/acceptance/profile/prompt bindings, disjoint
IDs, limits of 2/2 repeated and no-progress cycles, zero reused evaluations, no
worker holdout access and no pending effects at completion. Private state is
restricted to `.job-runtime/acceptance/<candidate>/` and public source references
may not be absolute, dotted, aliased or symlinked. Preserved candidate records stay
under `mentor/runtime/scheduler-resilience-mvp-20261109/`; no portable private state
is supplied.

Retry is allowed only for a proven pre-dispatch transient failure. A submitted,
streaming, unknown or possibly-dispatched result is fenced; reconciliation has
precedence over retry and no replay is authorized from this candidate. Host
preflight requires two fresh independent observations before stable readiness;
stale, unavailable, clock-reversed and insufficient observations remain explicit.
No optimistic status can override an unknown-effect fence.

The canonical bundle includes `spec_sha256`
`0eb1f86541d7b8570ff8518cad58a76d02ef1f72ac5a7c878d1614a9344b5790`,
but the current runtime adapter does **not** verify that broader identity. This is a
runtime blocker: a future integration would need an independently reviewed
materializer/staging receipt that seals and enforces `spec_sha256`, exact profile
and source bindings before any activation. None exists here. Host freshness was
blocked by stale service generation; exact profile/auth/home configuration loading
was not run; provider invocation, service reload, active config writes and external
effects were all zero.

The candidate-manifest's 15 source hashes and its eight SHA256SUMS-listed records
were rehashed exact. Separately, the final v5 handoff's 23-path scheduler
authority/parity family is aggregate SHA-256
`954add57d08731e59f94dd4142c4f730701b075b8b218101684e2e5a6a8a2dc9`.
This is provider-free structural evidence only. There is no materializer,
activation, scheduler registration, runtime acceptance, email, business effect or
permission to replay the earlier failed mentor slot.
