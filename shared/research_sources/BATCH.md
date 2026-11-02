# Configurable acquisition batches

`batch.py` composes the existing source catalog, Cache/Store, immutable artifact
contract and registered acquisition action. It adds no model, service, dependency,
semantic labels or investment admission. The configured query is descriptive;
source selection is the explicit bounded requirement/route list.

Run with the existing project-local Python environment from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m shared.research_sources.batch \
  --config shared/research_sources/examples/batch-now.json
```

`examples/batch-nvda.json` supplies an alternative public issuer case. These are
configurable examples, not live-access claims. Existing allowlist and payload
checks still apply; unsupported hosts, access failures and HTTP-200 error pages
remain failed. No credentials or new API key are required. Optional MCP and host
web-search workflows are not dispatched by this batch runner.

`run_batch(config, execution_id=None, state_directory=None, cache_directory=None,
fetcher=None, observer=None)` returns a UUID execution and hashed terminal
`report_ref`. The schema is declared in `batch.CONFIG`: at most 32 requirements,
three predeclared routes each, one or two attempts per route, four workers, 64
adapter dispatches, 120 seconds per dispatch and 600 seconds per batch. Discovery
returns metadata; reads return documents. Default adapters are
`official_document.read`, `arxiv.read`, `openalex.discover`, `arxiv.discover`.
Catalog-only routes remain explicitly unavailable and may use a predeclared
compatible access-level fallback; this does not prove semantic equivalence.

Current wiring before this addition was narrower: the action/CLI paths fetched
directly, Cache was exercised by cache-matrix/tests, and source_matrix was a fixed
serial NVDA/arXiv validation workload. This batch runner places Cache around the
real registered acquisition action and reuses the original discovery adapters in
a bounded subprocess. The ordered investment phase runner is unchanged.

## Execution, cache and retention

The default archive is `.niulai-state/reports/research-sources/runtime/batches/UUID/`.
A durable hashed intent precedes dispatch. An execution-scoped nonblocking lock
rejects concurrent duplicates. A completed UUID with identical config returns its
existing final receipt; changed config conflicts. Existing failed/unknown finals
are reconciled without dispatch and are not labeled successful replays. An intent
without a final is **unknown** and fenced: inspect its immutable attempt intents,
cache receipts and any child action receipts, then explicitly choose a new
execution only after reconciliation. The runner never resumes uncertain work.

Each terminal manifest binds config, capability catalog and script/release hashes,
requirement result refs, per-attempt refs, source refs, timings and counters.
Sources are acquired into the immutable execution archive. `final.json` is an
atomically published pointer. Cache TTL cannot delete or rejuvenate those bytes.
Snapshots are retained indefinitely until an explicit reviewed garbage-collection
policy; backups, disk quotas and automatic archival GC are not implemented.

The shared hot index defaults to
`.niulai-state/reports/research-sources/cache/acquisition/`, using the existing
Store SQLite database and per-key process locks/CAS. Cache keys bind provider,
capability, parameters, native version, public scope, capability-catalog and adapter
release/code policy, and batch normalization version.
Identical keys share a fetch across threads/processes. Cache freshness is separate
from historical eligibility: original acquisition/publication times are retained,
and consumers must screen exact pinned versions through the temporal broker.
Changing query text, batch ID or worker/call budget does not invalidate an identical
acquisition key. Per-execution config hashes still bind the immutable execution;
reusing the same UUID with a changed config remains a conflict. Historical cutoff
and semantic eligibility stay consumer decisions rather than universal cache flags.

Retries default to one attempt. A configured second attempt is allowed only for
registered network/502/503/504 failures. Unknown timeout/worker outcomes fence the
requirement before another retry or fallback. 401/403 remain cache dependency
holds. No automatic stale-data policy is enabled. Cache-publication failure may
return validated `fetch_uncached`; integrity errors never become warm hits.

`provider_calls` counts atomically reserved **adapter dispatches**, including
pre-network rejections; it does not count HTTP requests. One arXiv acquisition can
make multiple HTTP requests. `http_requests`, tokens and cost are not inferred.
No fetched source becomes a supported claim by being cached. `observation_refs`
remains empty until a separate, evaluated semantic mechanism produces them.

Observers run after authoritative terminal publication. Observer errors return a
stable warning and cannot change acquisition status. They are synchronous optional
callbacks; injected test fetchers, like Cache callbacks, own their hard I/O timeout.
The actual adapters use bounded child processes and process-group cleanup. This
is process containment, not an OS security sandbox.

## Verification and integration boundary

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest \
  shared.research_sources.tests.test_batch -v
```

Tests verify cold/warm reuse across executions, shared-key singleflight, concurrent
UUID fencing, atomic provider budget, fallback/retry distinctions, unknown-intent
recovery, observer isolation, the actual registered-action/cache boundary and a
real owned subprocess timeout. Fixture fetches are not live-provider evidence.

One narrow live E2E should use one reviewed public issuer URL: cold UUID A fetches,
warm UUID B performs zero adapter dispatches and retains A's source/time hashes;
replaying A does not dispatch; both immutable manifests remain readable after
cache-pointer invalidation. Publish only sanitized execution-level DTOs using
registry `batch_refs:[{batch_ref,subject}]`, with exact item/config/execution/source
bindings. Aggregates must retain cohort denominators, failed/partial/unknown runs
and the distinction between adapter attempts and HTTP requests. No investment
alpha or semantic-label accuracy follows from this acquisition test.

Live and future scheduled acceptance, independent postconditions and verified
owner email remain separate workspace gates. The initial batch unit tests alone
do not satisfy them. No schedule, email or active MCP configuration is changed by
this component. Deployment/setup inventory synchronization belongs in the same
integration change; no new package installation is needed.
