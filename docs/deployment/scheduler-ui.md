# Local scheduler dashboard

Open <http://localhost:7270/scheduler>. It shares the existing datasource
frontend, React19.2/TypeScript/Vite toolchain, loopback server and navigation.
Start it with `pnpm run dev`; inspect it with `pnpm run dev:status`. See the
[datasource runbook](datasource.md) for dependency setup and frontend lifecycle.

The page now shares the Figma-derived research-operations rail, topbar, Poppins
assets and dark tokens documented in `ui/datasource/DESIGN.md`. Scheduler
presentation and request state remain under `src/scheduler/`; no visual component
owns or mutates business scheduling. On narrow screens the job list is the first
task, details open only after explicit selection, and Back restores the selected
row. Historical stale health is labelled as last recorded evidence rather than a
live-green health claim. Cross-page design QA is in `ui/datasource/design-qa.md`.
This is a foreground local UI, not a newly installed login service.

## Sources and responsibilities

- `shared/job_runtime/dashboard.py` owns the bounded read-only job projection.
  It reads the actual private runtime configuration, referenced allocation and
  heartbeat/watchdog observations and the scheduler's SQLite ledger. It does not
  open prompt bodies; standard-job details expose only bounded custody status and
  the count of attempts whose schema-9 proof is complete.
  It does not instantiate the Engine, dispatch, claim, retry, send or edit jobs.
- `niulai-runtime/niulai_runtime/scheduler_view.py` supplies the Niulai-specific
  NYSE eligibility and stored-message projection.
- `mentor/scheduler/scheduler_view.py` is the only mentor provider. The shared
  projection selects it only for the fixed
  `mentor.scheduler.job_adapter:prepare` adapter; it never imports a module named
  by an HTTP request or an arbitrary job string. Other job types retain their
  generic schedule, custody metadata and run history.
- `ui/datasource/src/scheduler/` owns presentation and request state. The page
  loads separately from the datasource page. For generic/Niulai jobs, only the
  selected job's prompt custody status and up to20 recent runs are retrieved, and a saved
  message is fetched on selection. Mentor jobs expose none of those payloads.

The job registry remains the existing allocation files. New registered jobs
appear without maintaining a second frontend list or new database. Definitions are not copied into a new editable UI store, and prompt content is
excluded from the projection and frontend entirely. Niulai's immutable
message payloads remain in `.niulai-state/databases/outbox.sqlite` and the existing
private mail/source snapshots. Only production work matching the selected policy's
recipient and automation prefix is included; tests and unrelated mail are separate.

## What the page shows

The default Current jobs view includes enabled daily/interval work, upcoming
once/sequence tasks and enabled mentor evidence. Needs attention filters the same
population for recorded failures, unknown effects, expired unaccepted mentor work
or unavailable evidence. Recurring jobs means daily/interval only; finite work is
never counted as recurring. All jobs includes disabled and historical tests.
An enabled finite job with no future run is labelled Finished rather than offered
another execution.

The main overview shows the next scheduled run and current/attention counts.
Standard details open on Overview with independent Last execution and Recorded
delivery facts. Run history, saved messages and prompt custody remain
deliberate views. Mentor details open on four separate runtime outcomes, dispatch,
window, pending effects, cycles and all six gates; Evidence and safeguards and
Recovery timeline expose the full existing contract.

Job links retain the exact requested identity, including disabled/historical
jobs. An unknown link reports Requested job not found rather than substituting
another job. Changing search clears the prior selection, mobile detail state and
selected `job` URL identity, so a detail filtered out of the list cannot remain
rendered. On narrow screens, selecting a job focuses its detail heading and
replaces the list; Back to jobs restores focus to the selected row. The shared
mobile header remains contained. List, detail and preview responses independently
label stale/partial evidence.

The line-tab rendering treatment adapts pinned Radix Themes MIT source into the
existing plain CSS. The complete source attribution is in
`ui/datasource/licenses/radix-tabs.md`; pinned originals and their receipt stay in
ignored `ui/runtime/scheduler-refactor/sources/`. No Radix, Tailwind or other
runtime dependency was added. See the scoped
[implementation/acceptance plan](../plans/scheduler-ui-refactor-20261105.md).

Each job shows its schedule/timezone, next run, next declared send, last recorded
outcome, prompt custody status and bound-attempt count, model/effort, recent runs
and saved production messages. Instruction bodies, paths, basenames, references
and digests are not dashboard state and never cross the scheduler API. The display timezone can be Shanghai, New York or UTC.
Niulai send eligibility uses the actual XNYS calendar and the configured IANA
timezone, including DST; its daily timer may still wake on a nontrading day and
record a no-send result. Recovery checks run every5minutes and have no fixed
outbound-message time: they send only when eligible pending recovery is ready.
Unknown generic delivery semantics stay unspecified rather than inheriting an
email promise from a timer.

### Mentor status contract

A mentor job is not a generic custody/history/message view. Its provider suppresses
standard-job custody metadata, generic Engine history and saved outputs, and rejects every
`output` lookup. A successful projection emits `job_type: "mentor"` plus one exact,
bounded `mentor` object. The UI renders that object as nine evidence groups:

1. work-order identity, declared window and acceptance/event requirements;
2. scheduler status/code/attempt count and dispatch classification;
3. logical-session status and revision;
4. progress usage and limits for cycles, provider threads, variants,
   interventions and reused evaluations, plus pending effects;
5. safeguards, including the explicit distinction between configured replay safety
   and replay authorization;
6. all six acceptance gates: future wake, profile binding, stop propagation, model
   turn, journal/cycle postcondition and no duplicate dispatch;
7. evaluation and overfitting controls;
8. execution, acceptance, model-turn and result-email status; and
9. the bounded recovery timeline.

If any private-file, schema, identity or state invariant fails, the whole inner
object is replaced by `{ "status": "unavailable" }`; partial private evidence is
not returned. The outer scheduler response can still be a valid partial snapshot,
so the UI renders the unavailable sentinel honestly instead of inferring success,
dispatch, acceptance or delivery.

The provider reads only owner-private, regular, non-symlink files beneath the
workspace and the scheduler database in query-only mode. Adapter keys are exact;
the work-order, logical-session, acceptance-record and scheduler-job identities
must agree. The acceptance record must contain one recognized reconciliation.
Prompts, evidence payloads, arbitrary narrative, filesystem paths, digests,
receipts, recipient/mailbox data and provider-thread identifiers are never part of
the response. This is a fixed schema/privacy boundary, not a generic private-state
browser.

The historical verified candidate snapshot is deliberately negative: the mentor session
is `active`, revision `0`, expired, with zero turns, variants and pending effects;
the scheduler result is `failed / OPERATOR_RECONCILED`; reconciliation classified
it `definitely_not_dispatched`; runtime acceptance is `failed`; result email is
`pending`; replay is `not_authorized`. The scheduler claimed the future slot, but
the adapter failed before any model process or provider thread existed. The root
cause was unresolved in that snapshot, so this page is not evidence of dispatch repair, model
execution, replay, notification or runtime acceptance. Current live projections
may be unavailable or independently retained/stale. Their explicit state and
timestamps take precedence over historical documentation; never substitute the
historical snapshot for missing current evidence.

Scheduled send times are starts, not guaranteed arrival timestamps. No-send
results, successful execution and accepted/readback-verified email are distinct.
The current UI snapshot is not evidence that a future delivery already occurred.
Cloud Price Alert Studio tasks are outside this local registry and are labelled
as separately managed; the UI does not infer their health from a local heartbeat.

## Safety and failure behavior

`GET /api/scheduler` returns the job list. `job=<registered-id>` selects details;
`output=<opaque-sha256>` selects one policy-bound saved message. Arbitrary file
paths and unknown query fields are rejected. Non-GET methods are rejected by the
existing loopback Host/Origin guard. No create/edit/enable/run-now/send controls
are supplied in this version; the existing reviewed configuration remains the
execution authority.

The API invokes `.niulai-state/.venv/bin/python` in place, using its already
pinned exchange-calendar dependency, repository source roots in PYTHONPATH and
workspace-local TMPDIR. There is no package installation, copied authentication,
active MCP registration or scheduler-configuration change. Each subprocess is
bounded to8seconds and2MB, with at most8 distinct pending requests, singleflight,
a5second cache and16 cached identities. Refresh failures label retained snapshots
stale. Database connections use read-only URI mode, query-only SQL and a query
deadline; they never initialize or migrate the live ledgers.

Prompt output is prohibited. Schema8 ledgers report legacy/unavailable custody;
schema9 ledgers are queried dynamically for slot/attempt proof completeness and
return only `status` plus `attempts_bound`. The projection never selects prompt
plaintext, paths, basenames, references, identities or digests. Private
configuration and auth blobs are not returned. Message HTML is rendered in an empty-sandbox iframe
with restrictive CSP; scripts, remote resources, forms, popups and parent access
are blocked. PDF attachment names are displayed without exposing embedded bytes
or arbitrary private download paths. This is localhost ownership/transport
containment, not an OS sandbox or internet-facing authenticated application.

The UI refreshes visible-page data every30seconds, cancels obsolete reads and
checks job/output identity before rendering. A failed same-job refresh preserves
its last good content; another job's response cannot replace the current one.
Malformed data produces a recoverable error, with a render boundary as a final
fallback. Refresh and job selection do not mutate schedules or delivery state.

## Reproduction and verified scope

The task-oriented refactor verification on2026-11-05 passed21/21 scheduler browser
cases,10/10 scheduler/server cases, TypeScript checking and the99-module production
build. The guarded live desktop/mobile journey passed with8 scheduler GET requests,
zero unsafe requests/page errors and unchanged static hook/guard files. Final
desktop, mobile-list, mobile-detail and mentor screenshots were inspected under
ignored `ui/runtime/scheduler-refactor/`.

The first integrated suite passed16/20. Four assertions were adapted to the
deliberate detail views/status-context paragraphs. The next run exposed a real
mobile Back-to-jobs focus race; restoring focus at render commit fixed it without
weakening the assertion. Independent review found inconsistent mentor row/header
priority rules; both now share one helper, with a21st regression for unknown
effects and failed logical sessions. All strict schema, identity, sanitized error,
stale-response, RTL/long-content and sandboxed-preview checks remain.

These checks meet the declared UI acceptance. They do not prove faster task
completion in a user study, a working future scheduler dispatch or a new verified
Gmail delivery. The current read-only page may still show retained/incomplete
business evidence.

The final Figma-style mobile pass kept the same 21/21 scheduler regressions and
added rendered checks at 1440, 390x844 and 320px across live, mentor, loading,
error, stale and partial states. It removed unselected mobile detail duplication
and nested list scrolling, raised operational labels, preserved detail/Back focus,
and labels cached health as `Last recorded health` with warning styling. The
focused audit observed 28 GET requests, zero page errors and zero horizontal
overflow. Evidence is under `ui/runtime/scheduler-mobile-audit-20261105/`.

The workspace setup gate snapshots other components too. During this UI handoff,
the independent mentor implementation was still editing
`mentor/scheduler/controller.py` and `mentor/scheduler/state.py`; the first
post-refresh check detected that source drift. Those changes are outside this UI
verification and remain subject to their owner's runtime/runbook acceptance. A
passing snapshot check records consistency at that instant, not completion of the
concurrent mentor work.

From the workspace root with the existing documented local environments:

```sh
PYTHONPATH="$PWD:$PWD/niulai-runtime" PYTHONDONTWRITEBYTECODE=1 \
TMPDIR="$PWD/ui/runtime/tmp" .niulai-state/.venv/bin/python -B -m unittest \
  mentor.tests.test_scheduler_view shared.job_runtime.tests.test_dashboard \
  shared.job_runtime.tests.test_dashboard_provider_retry -v
node --test ui/datasource/tests/scheduler-server.test.mjs ui/datasource/tests/server.test.mjs
pnpm --dir ui/datasource typecheck
pnpm run build
python3 -B ui/tools/run.py playwright --project ui/datasource test \
  --config scheduler.playwright.config.mjs
python3 -B shared/setup_audit.py --check
```

Final grouped-mentor UI verification on2026-11-05 passed28/28 Python
backend/Niulai cases,10/10 Node scheduler/server cases, datasource typecheck, the
production build of98 modules and the full scheduler Playwright suite12/12. The
browser suite covers all nine groups above, all progress limits, the replay-safety/
authorization distinction, all six gates, failed and staged/passed distinctions,
long identifiers, mobile/RTL/keyboard behavior, exact unavailable-sentinel handling
and malformed discriminated mentor rejection. The focused preserved-evidence read
also produced `REAL_MENTOR_PROJECTION_OK` with the failed/reconciled/not-dispatched/
email-pending/no-replay state above.

The final guarded live pass issued31 allowed read-only requests and observed zero
blocked requests, writes, non-loopback requests, unknown API/output requests or page
errors; every grouped mentor marker was present. Nine static private evidence files
were byte-equal before and after the pass. A credential-category scan of24 recent UI
artifacts found zero matches. These checks establish the bounded grouped rendering
and read-only/privacy behavior; they did not dispatch, reconcile, replay, send email
or turn the failed candidate into runtime acceptance.

The live browser case needs the provisioned local scheduler/policy and running
frontend; the other browser cases intercept synthetic responses, including the
unavailable inner sentinel and valid outer partial response. For an isolated preview
port, set `SCHEDULER_TEST_BASE_URL=http://localhost:7271`. The tests do not dispatch
jobs or send mail. Browser and screenshot artifacts remain ignored below
`ui/runtime/scheduler-tests/` and `ui/runtime/scheduler-20261103/`.

The 2026-11-03 verification covered the retired prompt-rendering design and is not
acceptance evidence for the metadata-only boundary. Its still-relevant cases covered
per-job next-time and timezone display, existing datasource navigation, A→B late response, failed
refresh/retry, wrong identity/malformed data, keyboard focus, empty search,
360px/desktop layout and extreme text, and saved-message active-content isolation.
Initial browser failures and screenshots are retained in ignored evidence; two
selectors were corrected to match the existing alert component and an actual
long-title mobile overflow was repaired. Saved-output scope/read-only behavior
uses synthetic ledger fixtures; the first production report slot was still
pending during this UI verification. This observation surface does not change
business execution, and no scheduled business/send acceptance is claimed for it.

Rollback stops only the owned frontend and restores the previous frontend source.
It does not disable the scheduler, clear unknown sends, alter outbox history or
replay a report. Restart the frontend after server-code changes; preserve foreign
port occupants and all private scheduler/delivery evidence.

## Integrated scheduler resilience projection (disabled candidate)

The previously standalone panel is now integrated into the existing read-only
scheduler source/API/UI path. Backend authority is
`mentor/scheduler/resilience_preflight.py` plus
`mentor/scheduler/scheduler_view.py`; the server boundary remains
`shared/job_runtime/dashboard.py` and `ui/datasource/server.mjs`; the exact wire
type is `ui/datasource/src/types/schedulerApi.ts`; adaptation is
`ui/datasource/src/services/apis/scheduler/adaptScheduler.ts`; scheduler ViewModels
are in `ui/datasource/src/scheduler/types.ts`; and rendering is owned by
`src/scheduler/components/MentorJobDetail.tsx` and
`src/scheduler-resilience-mvp/`. The directory README now describes this integration
and links to this runbook and the [mentor scheduler runbook](mentor-scheduler.md).
No package, server, listener, route, database or runtime service was added.

Within an exact mentor packet, `mentor.resilience` has only these top-level keys:
`generated_at`, `status`, `projection_state`, `scheduler`, `provider_safety`,
`mentor` and `health`. Its nested contract is:

- `scheduler`: exact `status` and non-negative `attempts`;
- `provider_safety`: `latest_attempt` (null or exact `phase`/`status`),
  `delayed_until`, `delay_source`, boolean `unknown_fence` and bounded
  `replay_authorization`;
- `mentor`: non-negative `cycles`, exact `no_progress` and `repeated`
  `{used,limit}` budgets, and boolean `evidence_reset`;
- `health`: nullable non-negative `heartbeat_age_seconds` and nullable boolean
  `watchdog_healthy`.

Track C presents that projection as one **Resilience** panel with four semantic
sections and 16 rows. Snapshot records the timezone-formatted source time,
completeness and effective freshness. Active work merges scheduler state/attempts
and the latest provider phase/status. Recovery leads with the unknown-outcome fence
and provider replay authorization, followed by retry context and merged budgets.
Host timing keeps heartbeat/watchdog observations separate and leaves Last tick and
Catch-up as **Not recorded** under the public contract. Provider execution does not
stand in for business acceptance or email delivery.

The panel receives selected-detail request state rather than list health. An outer
retained-stale response overrides an inner `current` marker; partial completeness
remains separate. Same-job refresh failures keep the stale marker through retry and
clear it only after success, while identity changes retain the existing abort and
late-response protections. The panel has no controls, requests, polling or mutations.
It uses h3/h4 hierarchy, semantic `time` plus `displayDate`, bidirectional isolation,
one atomic polite read-state announcement, one-column defaults and panel-width
container queries at approximately 40rem and 26rem. The focused Track C Node suite contains **9 tests**. Synthetic browser coverage
includes 320px RTL, Back-arrow direction, 200% zoom, forced colors, reduced motion,
timezones, stale/current contradiction, refresh failure/recovery and read-only
request boundaries. No authenticated live browser was used for this Track C check.

The adapter rejects extra/missing keys, mismatched `generated_at`, impossible delay
or unknown-fence combinations and over-limit counters. Unknown outcomes require
reconciliation or remain not authorized. The public packet intentionally omits
prompts, paths, digests, profile/provider identity, raw receipts, email recipient
and business-owned host last-tick/catch-up details. Optional fields in the reusable
panel remain **Not recorded**; synthetic fixtures are never a live fallback.

The frozen 2026-11-09 handoff records current provider-free checks as scheduler
broad Python 294 passed, focused core Python 68 passed, focused Node 8 passed,
scheduler browser 32 passed, and exact server cross-contract Node 7 passed. The
combined datasource typecheck and 125-module production build also passed. These
checks supersede only the local source/UI evidence counts above; the historical
failed future attempt remains failed and reconciled definitely-not-dispatched.
The resilience allocation is still `enabled:false`; there is no provider, email,
replay, materialization, service reload or runtime-acceptance claim.
