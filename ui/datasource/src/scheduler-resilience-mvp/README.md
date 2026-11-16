# Scheduler Resilience MVP

This reusable read-only panel began as a standalone MVP and is now integrated into
the existing scheduler source/API/UI path as a disabled candidate. The directory
still owns only the strict adapter, ViewModel, presentation, fixtures and focused
tests; backend projection is in `mentor/scheduler/resilience_preflight.py` and
`mentor/scheduler/scheduler_view.py`, server composition is in the existing
datasource server, and `MentorJobDetail.tsx` renders the panel. Integration does
not activate a job or install a live service. The candidate remains inactive and
causes no provider, network, email, database, replay or business effect.

See the [scheduler UI runbook](../../../../docs/deployment/scheduler-ui.md) and
[mentor scheduler runbook](../../../../docs/deployment/mentor-scheduler.md) for the
exact projection, privacy, disabled-candidate and runtime-acceptance boundaries.

## Contract

`adaptResilience` is a pure, total boundary from an untrusted reduced wire value to
the strict `ResilienceEvidence` ViewModel. Wire names stay snake_case; component
props receive only the camelCase ViewModel. Missing properties render **Not
recorded**, invalid or explicitly absent containers render **Unavailable**, and
literal unknown states remain **Unknown**. The adapter does not infer business
completion, delivery, safe replay, provider readiness or fresh evidence.

The integrated panel is one compact Resilience section with four plain groups:
Snapshot, Active work, Recovery and Host timing. Related values are merged into 16
labelled rows without dropping evidence. The unknown-outcome fence and provider
replay authorization lead Recovery; provider execution, business acceptance and
email delivery remain separate outcomes. Host Last tick and Catch-up continue to
render **Not recorded** because the public contract intentionally omits them.

The selected detail request supplies display timezone, stale, refreshing and partial
context. Outer retained-stale state overrides an inner `current` marker. Partial is
an independent completeness axis, and a same-identity failed refresh remains stale
while retrying until a successful response replaces it. Identity changes still clear
retained data/errors, and the existing abort, timeout and late-response guards remain.
Recorded timestamps use semantic `time` elements, the shared `displayDate` formatter
and bidirectional isolation.

The integrated `mentor.resilience` wire preserves these existing evidence groups:

- `generated_at`, packet `status`, and `projection_state`;
- scheduler `status` and `attempts`;
- `provider_safety.latest_attempt`, `delayed_until`, `delay_source`,
  `unknown_fence`, and `replay_authorization`;
- mentor cycle, no-progress, repeated-evidence, and reset counters; and
- health heartbeat age and watchdog result.

Public scheduler packets intentionally omit private identities, paths, digests,
receipts, prompts, recipient data, host last-tick and business-owned catch-up
details. Optional panel fields therefore render **Not recorded** unless a separately
reviewed projection supplies them. Fixtures are synthetic and never a product or
live-data fallback. Provider execution, business acceptance and email
synchronization remain separate evidence domains.

## Integration example

```tsx
import { adaptResilience, ResiliencePanel, type ResilienceEvidenceWire }
  from './scheduler-resilience-mvp';

export function SchedulerResilienceSlot({ wire }: { wire: ResilienceEvidenceWire | null }) {
  return <ResiliencePanel
    evidence={adaptResilience(wire)}
    zone="UTC"
    stale={false}
    refreshing={false}
    partial={false}
  />;
}
```

Import the existing workspace theme before rendering so the `DESIGN.md` variables
referenced by the CSS module are defined. The panel uses only established
dark-violet tokens and adds no package.

## Focused checks

From `ui/datasource`:

```sh
node --test src/scheduler-resilience-mvp/resilience.test.mjs
node --test tests/scheduler-server.test.mjs
pnpm typecheck
pnpm build
python3 -B ../tools/run.py playwright --project . test --config scheduler.playwright.config.mjs --grep 'resilience|mentor'
```

The focused Node suite currently contains **9 tests** and transpiles only the pure adapter in memory and statically
checks the component/CSS contract. Broader server and browser checks are owned by
the linked runbooks. None of these checks dispatches, activates, sends email or
proves intended-runtime acceptance.

## Preserved limits

- the frozen allocation remains `enabled:false`;
- no materializer or runtime `spec_sha256` enforcement exists;
- host freshness, provider/model execution and email readback remain unverified;
- unknown effects stay fenced for reconciliation and are never inferred safe;
- no mutation controls, recovery actions, replay authorization or live polling are
  added by this panel;
- localization, interactive drill-downs, history, charts, notifications and
  telemetry remain outside this MVP; and
- browser verification is synthetic and loopback-only; it does not establish live
  scheduler, provider, business, email or future-slot runtime acceptance.
