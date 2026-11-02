# Hosted native web capture portal

`host_web.py` bridges a hosted agent's actual `tools.web__run` calls into the
existing immutable artifact and Store cache contracts. Python performs no search
or HTTP substitute. A cooperative host reserves an operation, invokes exactly
the returned tool arguments, captures the raw result, and exposes only the
returned screened packet. This is not an OS sandbox or a signed tool transcript.

The implementation is candidate infrastructure. Fixture and CLI checks do not
establish native transport availability, acquisition quality, or the required
future scheduled Codex acceptance and owner email receipt.

Version 1.1.0 adds native `find` as a locator for **both** experiment arms. Existing
capture histories and final manifests are read without rewriting them.

## Frozen configuration

Create a public baseline with `artifacts.save`, then initialize with this shape:

```json
{
  "config": {
    "schema_version": 1,
    "execution_id": "<canonical UUID>",
    "arm": "A",
    "question": "What new economic information changes the declared baseline?",
    "baseline_ref": {"path": "<private workspace artifact>", "sha256": "<64 hex>"},
    "cutoff": "<fixed aware ISO collection-window end>",
    "model_sha256": "<frozen model/backend configuration hash>",
    "backend": "native_tools.web__run",
    "cohort": "cold",
    "cache_enabled": true,
    "cache_max_age_seconds": 3600,
    "max_fallbacks": 2,
    "requirement_ids": ["pricing", "adoption", "economics"],
    "budget": {"search_items": 6, "open_items": 6, "provider_items": 12, "wall_seconds": 600}
  },
  "cache_directory": ".niulai-state/reports/research-sources/cache/host-web"
}
```

An optional `catalog_ref` freezes an existing artifact. It is provenance for host
instructions, not an automatically activated alternative provider. B sets
`cache_enabled:false` and otherwise uses the same logging boundary. Freeze both
arm configurations, baseline, question, cutoff, model/backend and budgets before
dispatch. Use a current collection window; current captures cannot authenticate
an earlier historical body from its publication date.

For new runs, call `freeze_config(config)` **before sealing** and pass its returned
configuration to `HostWeb`. The optional `code_pins` has shape
`{version,files:{workspace_relative_path:sha256}}`, with exactly the five public
direct files `shared/research_sources/{host_web,artifacts,cache,store}.py` and
`shared/job_runtime/service.py`. Arbitrary paths are rejected. This is an explicit
filesystem dependency check, not an executable bundle, full transitive closure,
loaded-bytecode attestation or OS write lock. Use a fresh project-local Python
process for the sealed runtime and keep candidate files unchanged.

Prepare checks pins before cache/dispatch; capture first archives the returned raw
result, then verifies pins before exposure. Drift returns failed
`HOST_WEB_SOURCE_CHANGED` with no worker packet or automatic redispatch. Cached
reads obey the same check. Intents, operation receipts and new final manifests
record `code_provenance:{version,implementation_sha256,dependency_sha256,pin_status}`;
pin status is `verified`, `changed`, or explicitly `unverified` for an unpinned
configuration. Legacy unpinned history does not gain a retroactive verification
claim. Historical `show`/`finish` readback remains available despite code drift.

All state, input files and result files must remain under an existing approved
workspace runtime root, such as `.niulai-state/reports/research-sources/`.
Configuration and exact operation/requirement arguments are immutable for an
execution ID. Reopening a completed operation never redispatches it. A pending
intent fences an unknown result across restarts: reconcile it before continuing.

## Python and CLI contract

```python
config = freeze_config(config)  # freeze before the experiment contract is sealed
portal = HostWeb(directory, config=config, cache_directory=cache_directory)
plan = portal.prepare("pricing-search", {
    "search_query": [{"q": "ServiceNow official pricing AI consumption"}],
    "response_length": "long",
}, requirement_ids=["pricing"])
# If plan['dispatch'] is true, the host invokes actual tools.web__run with
# plan['arguments']; Python cannot invoke that hosted tool.
result = portal.capture("pricing-search", {
    "actual_arguments": plan["arguments"],
    "raw_result": actual_native_result,
    "status": "returned",
})
final = portal.finish(unit_refs=[])
```

CLI entry point is project-local:

```text
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m shared.research_sources.host_web COMMAND --directory PRIVATE_RUN_DIRECTORY --input-file PRIVATE_INPUT_JSON
```

Commands are `init`, `prepare`, `capture`, `show`, `finish`. Without `--input-file`
the command reads a bounded JSON object from stdin. `init` accepts the envelope
above. `prepare` accepts `{operation_id,arguments,requirement_ids,fallback_of?}`.
`capture` accepts `{operation_id,capture:{actual_arguments,status,code?,documents?}}`
plus raw tool JSON via `--result-file PRIVATE_RAW_JSON` or `--result-json RAW_JSON`;
it also accepts `capture.raw_result` in stdin/file input. `show` and `finish`
accept `{}`; `finish` optionally accepts `unit_refs`. Output is one JSON object.
Failure prints a stable code and exits nonzero; raw exceptions are not echoed.

The actual tool result is often a **string**, not a structured search-results
object. Serialize that exact value once with `JSON.stringify(raw)`; do not call
`.get('results')`, reconstruct it from prose, or replace it with HTTP output.
The raw result's JSON representation must fit 64 KiB. A result file must contain
JSON, including quotes when the native result is a string.

A hosted `functions.exec` cell can use this sequence after writing public
prepare/capture metadata files. The capture metadata's `actual_arguments` must
equal `plan.arguments` exactly. Use proper shell quoting for public-only JSON:

```javascript
const q = s => "'" + String(s).replaceAll("'", "'\\''") + "'";
const cli = "PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m shared.research_sources.host_web";
const plan = JSON.parse((await tools.exec_command({
  cmd: cli + " prepare --directory " + q(runDirectory) + " --input-file " + q(prepareFile)
})).output);
if (plan.dispatch) {
  const raw = await tools.web__run(plan.arguments);
  // Hold raw inside this host cell. Do not text()/notify() it before capture.
  const captured = await tools.exec_command({
    cmd: cli + " capture --directory " + q(runDirectory)
      + " --input-file " + q(captureMetadataFile)
      + " --result-json " + q(JSON.stringify(raw))
  });
  if (captured.exit_code !== 0) throw new Error("HOST_WEB_CAPTURE_FAILED");
  text(JSON.parse(captured.output)); // Contains only screened packet and refs.
} else {
  text(plan); // cache_hit packet, pending/already_captured, or not_retry.
}
```

Never use `JSON.stringify` itself as shell escaping. Use a result file for large
public outputs, and keep credentials/private queries out of this portal. Inspect
and classify an actual tool transport failure as `status:'failed',
code:'NATIVE_TRANSPORT_FAILED'`; keep its actual raw result in the private capture.
Supported explicit failure codes also include `SOURCE_HTTP_401/403/404/429/503`.
Unknown outcomes use `status:'unknown',code:'HOST_WEB_RESULT_UNKNOWN'`. Invalid or
unparseable bodies from a returned tool call become a known normalization failure
(`failed`, `HOST_WEB_BODY_UNPARSEABLE`), retaining raw bytes and allowing a different
bounded fallback. They do not open the unknown-outcome fence or become empty success.

## Exposure and body handling

Search packets preserve actual native titles/snippets in `search_text`, bounded
to 48,000 characters, plus separately validated portable HTTPS `urls`. They expose
`search_text_truncated` and `search_text_total_chars` explicitly. No parsed title or
snippet fields are invented. The source's text hash binds the exact issued text;
its raw hash binds the full actual tool result. Its access level and packet scope
are current search metadata only, with no historical backdating or semantic
admission. Search metadata earns no positive economic-unit credit until the source
is opened. Native turn IDs may appear in that original text; the packet warns
callers that they are session-only and must not replace portable full URLs for open.
Search is always native; there is no cross-session cached search result.
Open with a full HTTPS URL, default port or 443. Credentials, secret query keys,
loopback/private IPs and local/internal hosts are rejected.

Use `arguments={"find":[{"ref_id":"https://public.example/document",
"pattern":"heading or distinctive phrase"}],"response_length":"long"}` to locate
a section in the actual native body. Each pattern is nonempty and at most 400
characters. The receipt has `native_verb:'find'` and normalized `operation:'open'`:
each locator consumes the **same** logical `open_items` and `provider_items` limits
as an open, with no cache lookup/publication. It preserves bounded actual native
`find_text`, explicit truncation/total characters, portable `urls` and at most 64
native `line_hints`. This is `current_locator_metadata_only`, provider
`native_web_find`, access level `metadata`, with original raw/text bindings and the
same per-operation exposure guard, circuit and unknown-outcome fences. It does
not create document evidence or a parsed title. Follow it with an actual targeted
`open:[{ref_id:full_url,lineno:chosen_line}]` within the remaining read budget.
The acquisition grader rejects native search/find metadata as scored-unit sources;
a returned locator cannot substitute for the opened document passage.

A single open automatically extracts native `L0: ...` passages. For another
native format or a batch, supply `documents:[{url,text,title?,published_at?,modified_at?}]`.
Each URL must equal its corresponding requested URL and appear in the raw tool
result; each bounded passage must be a substring of the raw or normalized native
line text. Unsupported returned formats fail normalization. The adapter does not assert that
a passage is the original publisher's complete bytes.

Document receipts use provider `native_open_primary_capture`, hash-bind raw/text,
and preserve acquisition time as `retrieved_at` and `available_at`. Known future
publication/modification/version availability blocks exposure. No date alone
establishes strict historical eligibility or semantic truth. Every exposed source
has capture <= host screening <= host exposure <= the fixed cutoff. The aggregate
receipt is `acquisition_worker_exposure`, mode `per_operation_host_screened`, with
deduplicated source refs and immutable `acquisition_operation_exposure` event refs.
Events bind execution ID, operation ID, requirement IDs, cutoff and exact source
refs. Operation receipts bind actual request/response refs and source hashes.

## Budget, cache and failure semantics

All search/open items are reserved under the per-execution lock **before** tool
dispatch or cache exposure, including cache hits. `provider_items` counts only
reserved actual native dispatch items. A batched tool call consumes one item per
query/URL, not one item per callback. At most 32 operations, four search queries or
12 open URLs per call are accepted. Four-query calls explicitly require
`response_length:medium` or `long`, matching the native tool schema. Config limits
are at most 64 items of each kind. Cache hits cannot
extend the logical open budget. Pending operations prevent another dispatch.

A reuses validated Store rows keyed by public URL, provider, request view and
normalization/backend version; changing the question or execution ID does not
invalidate the same acquisition. Original source timestamps are retained. Freshness
TTL is separate from immutable execution retention. This split callback portal
uses Store CAS rather than holding `Cache.get_or_fetch`'s lock across hosted tool
calls; it does not provide cross-execution dispatch singleflight. A mixed hit/miss
open batch fetches the whole batch, recording unused lookup hits explicitly as
`CACHE_PARTIAL_BATCH_NOT_USED`; single-URL opens avoid that extra acquisition.

Identical failed native requests are never retried. A native transport failure
closes the route for the run. Unknown outcomes also fence subsequent dispatches.
An eligible cached body can still be exposed without provider dispatch. A
predeclared different request may use `fallback_of` after a failed operation,
within max_fallbacks and the same budgets; only actual execution is recorded as
used. No adapter fallback is claimed unless independently wired and executed.

Mandatory acquisition receipts fail closed if they cannot be persisted. Optional
`capture(..., observer=callback)` runs after the atomic authoritative state update;
its exception returns `HOST_WEB_OBSERVER_UNAVAILABLE` without changing capture
status. Cache publication errors similarly preserve a usable fresh capture with
an explicit `fetch_uncached` cache receipt. Finished immutable run artifacts are
retained indefinitely unless an explicit separate retention policy is introduced;
only a small mutable state pointer and cache index are replaced atomically.

Verify the component without calling native/provider routes:

```text
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -m unittest shared.research_sources.tests.test_host_web -v
```

The suite includes locator/read-budget accounting and metadata-unit rejection,
code-file drift during a pending result, legacy unverified readback, exact tool arguments/schema, preservation of a rare discovery
clue absent from URLs, explicit text truncation, immutable replay/pending fences,
cache fairness, circuit/failure fallback, future/deadline exclusion, observer isolation,
actual CLI string capture and a real portal receipt through `acquisition.validate_run`.
Run the intended hosted-native workload separately, then complete the workspace's
[runtime acceptance contract](../../docs/deployment/runtime-acceptance.md).

Observed manual native controls on November 2, 2026 retained two locator misses
and one successful article read using a predeclared known line anchor. Native
`find` can return a navigation window without its requested phrase. Generic
`line_hints` are observed line numbers, **not verified matching locations**;
inspect the actual L-line text before selecting a target. A phrase repeated in
the echoed tool request is not a body match. Transport/capture success must stay
separate from a useful locator or completed information need.

Native opens can also return `Internal Error` payloads stating a size limit or
an inaccessible URL. Version 1.1.0 retains these raw failures under
`HOST_WEB_BODY_UNPARSEABLE`; that generic code does not establish a parser root
cause or a transport outage. Keep the payload diagnosis and original receipt,
avoid identical requests, and choose a justified alternate source/representation
within the existing budget. Do not infer that all PDFs are unsupported.
