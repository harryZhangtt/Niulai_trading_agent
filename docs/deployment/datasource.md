# Local datasource observability

## Start and stop

From the workspace root, use an existing Node >=22.12 and pnpm10.18.3. Tested
here with Node22.23.1. Install only the pinned workspace dependencies:

```sh
pnpm install --frozen-lockfile --ignore-scripts
pnpm run dev
```

Open <http://localhost:7270/datasource>. The root command starts the read-only
API and Vite together on7270, bound to IPv4/IPv6 loopback. A matching healthy
second invocation reuses the server. A foreign or older process on7270 produces
an actionable error; it is never killed and the port does not silently change.
Stop the owning terminal with Ctrl+C, then restart after server-code changes.
`pnpm run dev:status` prints only the matching server's allowlisted status.
This is a foreground development server, not an installed availability daemon.

The workspace uses the Figma-derived dark research-operations visual system in
`ui/datasource/DESIGN.md`. Shared navigation, Poppins font assets and tokens live
in `WorkspaceChrome.tsx`, `workspace-theme.css` and `src/assets/fonts/`; the
Research request/state and evidence contracts remain in their existing owners.
The Figma source is a raster visual authority, so the documented palette and font
match are reconstructed rather than exported component metadata. Design review
and responsive evidence are recorded in `ui/datasource/design-qa.md` and ignored
artifacts below `ui/runtime/figma-reference/`.

The same app exposes <http://localhost:7270/scheduler> for actual registered job
schedules, next sends, prompt custody metadata, history and stored message
previews. Prompt bodies, paths, references and digests are excluded. Its separate [scheduler dashboard runbook](scheduler-ui.md) covers the
read-only API, existing calendar interpreter and output/privacy boundaries.

The Python projection uses `.research-sources/.venv/bin/python` and existing
research dependencies; see [source setup](../../shared/research_sources/README.md).
Do not install another Python environment. Node dependencies are confined to
workspace `node_modules/`; pnpm store/cache/state and Vite/Playwright artifacts
are below `ui/runtime/`. No global packages, production scheduler allocations,
credentials or active MCP configuration are changed.

## Boundaries and recovery

`ui/datasource/server.mjs` executes the allowlisted Python projection CLI with
an argument vector,8s timeout,2MB output ceiling, bounded pending reads, single
flight,2s cache and last-good fallback. The UI exposes original timestamps and
staleness warnings; a retained result is not a fresh acquisition. A paginated
snapshot mismatch returns409 and requires a fresh first page rather than mixing
versions. Health checks have a700ms absolute deadline and bounded response size.
Unknown WebSockets and private file requests are rejected; shutdown destroys
owned sockets. Host/Origin checks and GET/HEAD-only APIs reduce exposure to
foreign web pages. These controls do not make a development server an internet
service or defend against arbitrary code running as the same local user.

The API never returns prompts, credentials, private paths or raw execution
payloads. Scheduler packets are recursively checked before cache admission;
prompt-bearing or secret-key packets return a sanitized unavailable response and
cannot use a previous snapshot as stale fallback. The frontend's filesystem allowlist excludes private research/auth
roots. Read/projection/label failures are diagnostic: they cannot modify saved
research status or advance a pipeline. `best_effort_observe` runs after the
business receipt exists and returns a bounded warning on observer exceptions.

## Persisted sources, labels and runs

`investment.research.information_labels.annotate_source` validates raw/text/source
hashes and writes immutable document/claim sidecars. The key includes source
version, label and policy hashes; repeat writes reuse the same result. The default
index is under private `investment-research/information-labels/keys/`. Labels
are conservative provisional hints, not semantic admission or independent truth.
Claim targets/opinions are never promoted into whole-document factual status.

`investment.research.datasource` projects known captured reports plus a bounded
private registry at `investment-research/datasource/registry.json`. Registry
entries pin source refs, report refs and exact run-bound temporal diagnostics.
The UI shows source links, publisher/perspective/type/topic/knowledge labels,
published/available/fetched/recorded times, execution/config/script versions,
phase statuses and recognized catalog/extracted-observation outputs. Missing
costs or measurements remain Unknown. Original failed A/B graders, captured
repair cohorts and their expected/graded denominators remain separate. Colored
text differences show wording changes; they do not establish information gain.

## Temporal guard and actual model path

`shared.research_sources.temporal.prepare_corpus` checks pinned source/raw/text
hashes, cutoff, scope and version/observation availability before exposing search
results, titles, snippets, bodies or worker packets. Event/publication time does
not backdate a body first captured later. Future, unknown and qualified historical
reconstructions remain host-only in strict mode. Store lifecycle changes and
hashes are rechecked on exposure; an eligible old revision need not be erased by
a later ordinary version, while withdrawal revokes access. Cache reuse is bound
to the cutoff, scope and pinned versions.

`investment.research.datasource_query.run_query` is one maintained NOW recipe:
original capture guard -> explicit read-schema compatibility receipt -> registered
`evidence.read@1.1.1` -> one tool-free configured model turn -> bounded catalog
compilation and literal quoted observations -> immutable final snapshot -> optional
labels. It preserves the original capture/raw bytes/times and lineage; normalizing
the provider field for the existing read schema is not a new acquisition or a
second independent source. It invokes the host guard before read, model exposure
and finalization. Only source quotations from the issued passage are accepted as
observations. Five facets are required: business mechanism, technical mechanism,
unit economics, adoption and counterevidence. Catalog questions are proposals;
they do not prove those sources have been fetched, reviewed or admitted.

This path is not globally installed into every research tool. The broker is a
corpus-exposure boundary, not OS isolation or proof that model weights contain
no future knowledge. Strict historical evaluation still needs authentic version
availability and an isolated runtime for every allowed retrieval route. Historical
A/B results predating this broker are labeled reconstructed, not strict replay.

The professional primary-source rationale and interpretation are recorded in
[the architecture note](../plans/datasource-observability.md).

## Verification and one future acceptance

```sh
pnpm run build
pnpm run test:datasource
python3 ui/tools/run.py playwright --project ui/datasource test --config playwright.config.mjs
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest \
  investment.research.tests.test_label_sidecars investment.research.tests.test_datasource \
  investment.research.tests.test_datasource_query shared.research_sources.tests.test_temporal -q
```

The browser runner reuses the pinned workspace-local UI verification browser and
requires the dev server already running. It covers actual projection rendering,
keyboard/mobile behavior, slow subject switching, last-good refresh, private file
rejection and foreign-origin/mutation rejection. The responsive source regression
also verifies that a native `hidden` annotation badge computes to `display:none`
and deterministically checks the rendered text-accent token against both the panel
surface and selected blue-tint surface. Synthetic faults are marked.

For a reviewed version, start the local server, finish source edits, then run:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python \
  -m tuning.evals.datasource_acceptance setup --change REVIEWED_UNIQUE_CHANGE_ID
```

This reuses the existing Engine/default model/auth owner with one workspace-local
launchd label `com.local.trading-agent.datasource.*`, one future slot, one attempt,
45s lead time and420s completion limit. It fingerprints source/config/Python/Node,
issues one registered captured-source read and one real configured Codex turn,
and checks literal observations, five-facet catalog, labels, exact run/temporal
bindings and API output. Three clearly synthetic future/unknown/reconstruction
probes must be absent from the model prompt while remaining visible to reviewers.
It does not perform a new source-provider request or a broad historical A/B.

The next terminal tick unloads only its own temporary label. Failures retain
receipts and are not silently retried. The supervisor independently reopens
postconditions, confirms the label is unloaded, and performs the required exact
configured-owner email readback. The helper itself sends no email. See
[runtime acceptance](runtime-acceptance.md); a unit pass does not replace this gate.

## Information-yield v4 dashboard projection

The Overview page accepts an optional exact `evaluation` query identity and reads
only an immutable EIY v4 result referenced by an explicit registry artifact. The
server receives that registry reference through `INFORMATION_YIELD_REGISTRY_REF`;
it does not scan directories or select the latest result. Optional `case`, `arm`,
`run` and `source` selectors are hierarchical and exact. Unsupported run/source
identities return not found rather than linking to an unproved global record.

`investment.research.information_yield_projection` verifies registry and result
hashes, validates the closed v4 result schema, redacts private/raw fields and emits
a bounded read-only DTO. Unknown, unavailable and not-applicable measurements stay
distinct from numeric zero. Hard failures and the recorded verdict are preserved;
richness and depth remain separate co-primary outcomes and no scalar EIY, alpha,
valuation, return or PnL field is projected.

The loopback endpoint is `GET /api/information-yield?evaluation=<id>`. It keeps the
existing Host, Origin and read-only method guards, singleflight, timeout, bounded
cache and child-process cleanup. Stale-last-good data is retained only for the same
exact selector identity. The isolated Overview panel has its own render boundary,
hard-failure alert, evidence banner, paired small-multiple/table twin, policy
diagnostics and local case/arm drilldown. It cannot run an experiment or promote a
candidate.

Provider-free verification uses synthetic result artifacts only:

```bash
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  .research-sources/.venv/bin/python -B -m unittest \
  investment.research.tests.test_information_yield_projection -v
node --test ui/datasource/tests/information-yield-server.test.mjs
python3 -B ui/tools/run.py playwright --project ui/datasource test \
  tests/information-yield.spec.mjs --config playwright.config.mjs
```

These checks establish projection, transport and rendering contracts. They do not
run the B0-versus-F experiment or establish production information value.

## Execution-level acquisition addition

The default dashboard is now **Overview**, followed by distinct **Runs**,
**Evidence**, and **Comparisons** views. Overview owns aggregate health and cohort
metrics; Runs separates collection, research, and comparison runs; Evidence owns
source records and hides hashes/temporal diagnostics under technical provenance;
Comparisons owns controlled A/B outcomes and its linked run receipts. Each view is
addressable through `?view=...` and survives reload/Back. The legacy `/datasouce`
typo redirects permanently to `/datasource` while preserving its query.

`shared.research_sources.batch.run_batch`
assigns each configured fetching batch a UUID and immutable intent/config/attempt/
result/final manifest. It wraps actual registered acquisition in the existing
Cache(Store), with bounded per-item deadlines, atomic dispatch budgets and
per-key singleflight. Same-key acquisitions can be reused across queries and
worker budgets. Same execution/config replays its terminal receipt; an interrupted
intent remains unknown and cannot automatically dispatch again. Cache metadata
is disposable; source and cache-attempt receipts needed for history live in the
execution archive. No automatic GC, backup or disk quota is installed.

Register immutable manifests as `batch_refs:[{batch_ref,subject}]` in the private
registry. The API validates execution/config/requirement/source links before
projection. Per-execution cache/adapter counts and retained references have explicit
counting scope, including failed/partial/unknown results. The configured route list
is executed; the question catalog is not yet automatically converted to new Web
search tasks. See [the batch runbook](../../shared/research_sources/BATCH.md).

The A/B view now distinguishes original review passes from actual pipeline
completion, marks limited comparisons, retains order-disagreement flags, and
identifies selected metric/unit/known-pair counts. All-equal rubric scores explicitly
state that they do not distinguish the arms. Those historical runs fixed the same
evidence packet and made zero retrieval calls. They cannot measure acquisition
richness or freshness. [The diagnosis and replacement gate](../plans/acquisition-ab-diagnosis.md)
retain that limitation rather than rewrite old results.

## Unified visual-system verification

The final Figma-style pass on 2026-11-05 passed the 65-case combined browser
suite, all 15 shared Node server/read-only cases, TypeScript and the 104-module
production build. Focused Research checks covered 1296/1440 desktop, 390x844,
320x800, 200% text, exact URL/Back identity, source/detail focus return, loading,
empty, retained failure and successful stale states. Final captures are ignored
under `ui/runtime/final-ui-acceptance-20261105/`; the review record is
`ui/datasource/design-qa.md`. The follow-up normal-text contrast gate covers
global links, RunEvidence, disclosure/action/button/comparison labels and
Overview class links on panel and selected-tint surfaces; all rendered pairs meet or
exceed `4.5:1`, with no open P0/P1/P2 contrast findings.

The responsive chrome uses short visible mobile labels with unchanged full
accessible names. Under text expansion it scrolls internally rather than widening
the document. This is visual/read-only acceptance only; it does not establish new
acquisition freshness, investment quality, dispatch or email delivery.

The shared-worktree setup refresh also observed concurrent changes in the
separately owned acquisition live-session/acceptance sources. Their hashes are
included by the workspace consistency snapshot, but this UI verification did not
exercise or accept those provider, scheduler, Gmail or external-effect paths.

Jev labeling is paused at the user's request. Its local adapter/evaluator source is
available but live classification timed out and label accuracy remains unmeasured.
Use [the handoff](../handoffs/jev-labeling-20261101.md); do not enable another call
or treat source labels as semantically validated through this dashboard.


## Registered controlled native acquisition comparisons

The same A/B selector accepts `acquisition_comparison_refs:[{report_ref,subject}]`
in the private datasource registry. Only `controlled_acquisition_comparison`
version-1 reports are recognized, at most four registered comparisons. The
allowlisted projection binds immutable report/result/contract/submission refs,
derived runs to their original collection receipts, both pooled review rosters,
and each preview quotation to its captured source text. It never reruns a grader,
reads an arbitrary file parameter, or alters original failed grading receipts.
Each arm exposes at most8 unit previews; omitted counts are explicit. Existing
shared read/byte and2MB response bounds still apply.

Native execution IDs, public source links, configuration hashes, logical search/
open counts and native callbacks are shown separately from configurable batches.
The current pair's16 captures mean4 search-metadata snapshots plus12 document
capture instances representing11 unique document bodies, not16 independent
sources. Thirty-two unique extracted observations create36 arm-bound references
because shared observations bind to both captures. The adjudicated answer-bearing
pool contains29 economic identities. Two recorded review orders agree on core
metrics; freshness labels differ for4 unique observations/8 arm-bound references.
Authenticated first availability remains unknown for32 unique observations/36
bindings, so monitoring detection lag remains unknown.

The primary new-unit count18A/15B is presented alongside an explicitly exploratory
anonymous-source exclusion14A/15B. This reverses count ordering and does not
establish broad quality dominance. Per-task counts overlap; touching all three
broad topics does not resolve all twelve underlying gaps. Financial Q3-vs-Q2
company context measures reporting-period selection, not AI-specific recognized
revenue or original-publication detection latency. Provisional labels and LLM
absolute accuracy remain unestablished. Old failed and captured-repair cohorts
remain selectable and separate.

Focused verification adds
`investment.research.tests.test_acquisition_projection` and
`ui/datasource/tests/acquisition-comparison.spec.mjs` to the commands above.
These tests validate local projection/rendering boundaries; the workspace's
future-scheduled runtime and verified owner-email gate remains separate.

## Provider-free acquisition-driver trace rehearsal

The private registry may also contain a bounded `acquisition_driver_projection`
envelope. The server and client accept it only when the independent checker is
recomputed as an exact `1/1` pass over immutable driver, proposal, actual-dispatch,
review and optional reconciliation references. The projection exposes allowlisted
identities, state transitions, sanitized exact arguments and hashes, accounting,
source/version lineage, literal quote/review fields, checker gates and explicit
limitations. Raw provider bytes, private paths, arbitrary HTML, credentials and
unchecked runner/UI verdicts never cross the API boundary.

`HostedAcquisitionRunner` is provider-agnostic and receives only an injected
callable. Its runtime root must be workspace-local, private and non-symlinked. It
keeps hash-chained dispatch journals, content-addressed actual-dispatch receipts
and bounded raw captures below that configured root. A persisted claim cannot be
replayed after restart without authoritative definitely-not-dispatched evidence;
a possibly-dispatched outcome requires provider-free reconciliation before any
further action. HostWeb receives only the privately reopened bounded capture.

Run the deterministic rehearsal with the pinned environment; it makes no network,
email, scheduler or trading call:

```bash
cd "<workspace-root>"
.research-sources/.venv/bin/python -B -m unittest \
  investment.research.tests.test_acquisition_synthetic_e2e
```

The rehearsal requires exactly three counting-fake invocations for search, the
structured oversized-PDF response and the frozen HTML alternate, then requires one
reviewed unit and an independently recomputed checker-backed projection. Its pass
is structural evidence only, not provider readiness or acquisition-quality
improvement. Delete only the isolated test temporary root after the test process
has exited; never replay a claimed or possibly-dispatched journal to recover space.

## Codex and Claude Code hosted live-session entrypoints

`investment.research.acquisition_live_session` is the provider-free coordinator for
both cooperative hosts. It never invokes a provider itself. A sealed session binds
one sanitized host-adapter profile, an opaque credential-readiness receipt, exact
runtime/config fingerprints, a private non-symlinked execution root and one of:

- `codex_native_web`: configured and observed tool `native_tools.web__run`;
- `claude_code_web`: configured backend `claude_code.web`, with operation-specific
  observed tools `claude_code.WebSearch` and `claude_code.WebFetch`.

Credential values never enter the packet, session, logs or checker. The host
profile records only owner/profile references and hashes; its credential readiness
receipt is opaque and hash-bound. MCP is `not_used`; no active MCP configuration is
added. A missing, mismatched, unknown or secret-bearing profile/receipt blocks
initialization.

Both adapters reuse the same `HostedAcquisitionRunner` journal, deadlines, raw
bounds, restart/unknown fences, driver reconciliation and independent trace checker.
The coordinator commands are `init`, `next`, `capture`, `assess`, `review`,
`finalize` and `status`. `next` returns one exact host tool input only after durable
claim and invocation fencing. `capture` accepts the exact JSON tool result once from
a private bounded file and rejects host/tool/input substitution. An unknown outcome
is fenced and cannot emit another dispatch.

Claude Code WebSearch is current metadata only. WebFetch output is retained as a
`rendered_extracted_representation`, explicitly not publisher-original bytes;
literal support is limited to wording in that exact captured extract. Codex native
URL/body checks are unchanged. Cache identities, source providers and receipts stay
separate by configured backend. One run remains concurrency `1`; later matched
cases may use separate isolated roots rather than weakening per-run serialization.

Provider-free verification:

```bash
cd "<workspace-root>"
.research-sources/.venv/bin/python -B -m unittest \
  shared.research_sources.tests.test_host_adapter_contracts \
  shared.research_sources.tests.test_host_web \
  investment.research.tests.test_acquisition_live_session \
  investment.research.tests.test_acquisition_claude_code \
  investment.research.tests.test_acquisition_fault_matrix
```

A pass proves the shared lifecycle and host-identity contracts with synthetic
results only. Codex and Claude each require a separately sealed execution ID,
artifact/cache roots and actual one-call smoke before any live-readiness claim.
Unknown outcomes remain held for reconciliation and are never repaired by replay.


### Ordered-query acceptance v2

The helper version `datasource-ordered-query-acceptance-2.0.0` fingerprints the
actual official-document acquisition, action release, batch/cache/store, ordered
query/model, label and API/UI closure. It excludes the independent skill-TUI,
HostWeb/native acquisition and acquisition-grader paths; changing a relevant
pinned dependency still fails. Existing broad v1 failure records are preserved.
No production allocations or shared model/engine/service code is changed.

Before scheduling, the helper checks the actual catalog transport schema rejects
unsupported `uniqueItems` guidance while complete local schemas retain that
validation rule. The future one-attempt run performs a fresh official-document
cold batch, a warm cache hit and same-ID replay, then freezes its cutoff after
acquisition. Replay output and before/after archive hashes are retained. One
actual configured tool-free Codex catalog turn must yield literal observations,
all five catalog facets, exact guarded API output and reviewer-only synthetic
future/unknown/reconstruction probes. Actual model schema/event/response hashes
and newly scheduled timing are independently checked. Parent supervision still
owns exact configured-owner email synchronization; the helper never sends mail.


### Comparison presentation followup

A later view-text repair makes source-class ordering conditional on actual arm
counts, identifies native rounds by their existing comparison IDs, and brings
already-recorded forward/reverse counts from quality limitations into the visible
review notice. It changes no grader, metric, API contract or execution behavior.
The earlier ordered-query scheduled proof remains scoped historical evidence;
its whole UI candidate hash is not claimed unchanged after this text repair.
A registered report that exceeds the bounded projection read budget remains
unavailable with a partial-data warning; tests must not inject it as live data or
relax the gate to hide that limit.


### Current two-report overview capacity repair

The unit preview bound is eight per arm. Full report metrics, derived/original
run identities, both complete review rosters and their full unit-reference sets
remain validated; only source quotation previews are bounded. `units_total` and
`units_truncated` expose each omission. A regression rejects a missing review
outside the visible eight previews. Company financial-period context continues
to use the complete loaded review roster, rather than disappearing when its
quotation preview is omitted.

For the actual registered v1/v2 pair, the former bound hit512 reads and returned
a partial overview without v2. The eight-preview candidate finishes at451 reads
and about9.96MB, with both rounds present and no warnings. The global512-read,
64MB-read and2MB-response limits are unchanged. This does not promise capacity
for four independent reports. The next scaling step is metadata-only comparison
overviews plus selected-report bounded details, rather than raising those caps.
A new future ordered-query acceptance v3 is required for this API capacity change;
the prior v2 pass is retained as historical evidence for its earlier candidate.

## Information-yield v5 frozen-disabled projection

The additive v5 path is implemented in source but frozen disabled. Lane B reads
only `investment/research/information_yield_projection_v5.py`; the existing
loopback server owns `InformationYieldV5Bridge` in `ui/datasource/server.mjs`;
`src/services/apis/informationYieldV5/` is the client;
`src/types/informationYieldApiV5.ts` is the wire type; and
`src/InformationYield/adaptInformationYieldV5/`,
`useInformationYieldV5/` and `InformationYieldPanel/` adapt and render it. Focused
server/browser coverage is in `tests/information-yield-v5-server.test.mjs` and
`tests/information-yield-v5.spec.mjs`. No new dependency is introduced: projection
uses the existing Python 3.12.16 `.research-sources/.venv` with
`jsonschema==4.25.1`; UI uses the existing React 19.2, TypeScript 5.9.3 and Vite
7.1.12 graph.

The read-only endpoint is `/api/information-yield/v5`. Its exact query is
`evaluation=<id>` with optional `case=<id>`, optional `arm=B0|F` only when a case
is present, and optional `refresh=1`; all other keys, invalid identifiers and
non-GET methods are rejected. The wire is `information-yield-wire-5` with
publication `information-yield-v5`. `INFORMATION_YIELD_V5_ENABLED=1` is an
activation boundary, not approval, and is insufficient without separately reviewed
locator/publication approval and intended-runtime authorization. It is currently
off; setup does not create the publication root or restart the parent-owned
localhost listener.

Projection opens only the fixed canonical root
`tuning/runtime/information-yield-v5` and follows this authority chain:

```text
index/<evaluation>.json -> custody.json -> canonical policy -> context.json -> result.json
```

Every hop is a canonical repository-relative custody reference. Absolute paths,
symlinks, aliases, selector substitution, identity/hash drift, policy/authority
mismatch, reordered/duplicate gates and result/context drift fail closed. The
server requires the exact evaluation/case/arm identity, 18 ordered gates, six
confirmation cases, C/D/E/N population semantics and canonical policy/authority
hashes. A prior same-identity response may be labelled `stale` only after a
transient unavailable result. Missing, disabled, custody/identity conflict,
privacy failure and output-limit errors never reuse stale evidence.

The child projection receives only sanitized `PATH`, `PYTHONPATH`,
`PYTHONDONTWRITEBYTECODE`, `TMPDIR` and `LANG`; it inherits no provider or
credential environment. Index reads are capped at 64 KiB, artifacts at 8 MiB,
wire output at 512 KiB, pending requests at eight and cache entries at sixteen.
The server rejects non-finite values, depth over eight, arrays over 256, objects
over 128 keys, strings over 512 bytes and nested raw/payload/prompt/credential/
auth/token/secret/private/path/quote/exception/password/key fields. Sanitized
fixed error codes distinguish invalid query, disabled/not found, authority
conflict, permission denial and transient unavailability.

Rollback turns off the flag and any separately approved locator, preserves all
immutable v5 publications and returns to O0. It never deletes artifacts, rewrites
identity, auto-upgrades, or falls back to rejected v3/v4. The verified claim is
provider-free structural closure only: no live provider quality, acquisition or
population superiority, alpha, scheduler/runtime acceptance, email delivery or
host activation is established.
