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
payloads. The frontend's filesystem allowlist excludes private research/auth
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
rejection and foreign-origin/mutation rejection. Synthetic faults are marked.

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

## Execution-level acquisition addition

The default dashboard is now **Executions**. `shared.research_sources.batch.run_batch`
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
