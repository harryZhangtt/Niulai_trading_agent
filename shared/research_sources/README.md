# Research-source acquisition

`store.py` adds observation CRUD and durable requirement due checks. Local
integrity/revision checks remain separate from investment use policy. See
[the scoped runtime runbook](../../docs/deployment/investment-research.md).
The explicit issuer-document allowlist also includes `nvidianews.nvidia.com`
for the inspected original NVIDIA release.

Fetchers return source facts and immutable receipts. They never select investment
requirements, mark a thesis complete or modify a financial model. The separate
[investment adapter](../../investment/research/README.md) owns those decisions.

`catalog.json` describes useful capabilities by operation. Discovery output and
document output are different types. A catalog entry is not a live-health claim.

| Route | Added value beyond general search | Current scope |
| --- | --- | --- |
| OpenAlex REST | Structured publication/identifier candidates and citation metadata | Live discovery tested; publication merging/date precision require verification |
| arXiv Atom + versioned HTML | Exact manuscript revision, revision availability and source text | Live v2 document tested; HTML only, explicit failure when unavailable |
| Official document HTTPS | Dated original documentation artifacts | Live NVIDIA guide tested; small explicit host allowlist |
| arXiv MCP 0.8.2 | Structured paper outline and bounded section reads | Optional isolated one-paper live pilot; no active host registration |
| Normal web search | Broad terminology, issuer/customer/competitor and contrary-evidence discovery | Existing native/Work routing; URLs alone are not read evidence |

OpenAlex's [provider MCP](https://github.com/ourresearch/openalex-mcp-server) is a
possible future transport; its authenticated MCP operation was not tested here.
The tested REST discovery route required no new credentials. Provider budgets and
terms still apply; a successful anonymous call does not guarantee continuing access.
The [arXiv MCP](https://github.com/blazickjp/arxiv-mcp-server) is third-party,
Apache-2.0, pinned to 0.8.2. Repository activity is not analytical validation.

## Local setup

Python 3.12 is the exercised interpreter. Node >=22 and the locked dependencies in
`shared/market_data_mcp/` are needed only for the optional MCP probe. Reuse their
documented local npm setup. No host MCP configuration or global packages change.

```sh
umask 077
mkdir -p .niulai-state/reports/research-sources/tmp .research-sources/cache/pip .niulai-state/reports/research-sources/runtime
chmod 700 .research-sources
PYTHONDONTWRITEBYTECODE=1 .niulai-state/.venv/bin/python -m venv .research-sources/.venv
TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" .research-sources/.venv/bin/python -m pip install \
  --cache-dir "$PWD/.research-sources/cache/pip" -r shared/research_sources/requirements.txt
```

Core fetchers use the standard library. `jsonschema==4.25.1` and
`rfc3339-validator==0.1.4` support the preserved Niulai validators. The bootstrap
interpreter is an explicit dependency from the [Niulai setup](../../docs/deployment/niulai.md);
another workspace-local Python 3.12 can create this environment on a new device.

Optional isolated MCP candidate:

```sh
TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" .research-sources/.venv/bin/python -m pip install \
  --cache-dir "$PWD/.research-sources/cache/pip" -r shared/research_sources/optional-mcp-requirements.txt
NODE_COMPILE_CACHE="$PWD/.niulai-state/reports/research-sources/cache/node" \
  node shared/research_sources/mcp_probe.mjs inspect
NODE_COMPILE_CACHE="$PWD/.niulai-state/reports/research-sources/cache/node" \
  node shared/research_sources/mcp_probe.mjs live
```

The evaluated wheel SHA256 is
`11cb0f60064242028c823ffc78825774340cec644bfb26eaa2917d8d45eb32f7`.
No PDF/ML extras were installed. Direct requirements are pinned, but this is not a
complete transitive hash lock; the actual resolved listing is private runtime
evidence. Do not auto-upgrade or treat this pilot as a production dependency lock.

The MCP storage path, working directory, temporary files, package and Node caches
are explicitly inside the declared component state roots. Its download tool is a local write:
the reviewed adapter exposes one explicit versioned cache-materialization operation
with overwrite disabled. Subsequent section queries use the existing `QueryPortal`,
which still excludes tools annotated `readOnlyHint=false`. Both clients are isolated,
bounded and closed; the probe checks query-process exit. Never remove that read-only
filter to make a candidate tool appear available. Preserve the recorded failed probe
history in the mentor task record; the first section query used the wrong schema key
and was corrected before the successful live run.

## Fetch and read

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m shared.research_sources openalex-discover \
  --value 'FlashAttention' --out "$PWD/.niulai-state/reports/research-sources/runtime/example"
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m shared.research_sources arxiv-read \
  --value '2407.08608v2' --out "$PWD/.niulai-state/reports/research-sources/runtime/example"
```

`document-read --value HTTPS_URL` handles the configured first-party hosts.
`arxiv-discover` returns metadata/abstract candidates, not document-read evidence.
`passage --value RECEIPT_REF_JSON --start N --max-chars 6000` returns a bounded
normalized-text passage with offsets. Receipts preserve raw bytes, extracted text,
source URL/ID/version, revision availability, retrieval time and hashes. They do not
claim that retrieving the full document means reading or understanding all of it.
`ingest_mcp_section` normalizes a successful version-matched MCP section into the
same receipt type, keeping the primary arXiv identity/date reference.

HTTPS GET uses explicit hosts, no redirects, an 18-second timeout and 4 MiB bound;
there is no hidden retry loop. Auth/rate-limit/server failures remain errors rather
than empty success. arXiv HTTP calls share a local lock and at least 3.1-second start
spacing; this does not coordinate unrelated machines or external callers. One local
HTTP source lookup may need two calls (Atom plus HTML). The optional MCP has its own
bounded retry settings; do not fan out both routes as independent observations.

Treat source content as untrusted data. OpenAlex can map an arXiv request to a
different proceedings DOI; preserve candidates and verify identity/version on the
primary source. Publication dates may be approximate. arXiv hosting alone does not
establish peer review, and a vendor-submitted benchmark is not automatically an
independent replication. Keep those judgments in the investment evidence review.

Artifacts are private, hashed, immutable files under
`.niulai-state/reports/research-sources/` and
`.niulai-state/reports/investment-research/`. Older interactive roots remain readable. Model bindings may additionally read `.niulai-state/reports/`.
No credential directories, archive writes, source snapshots or external paths are
allowed. Runtime state is ignored by Git. Current host allowlists and HTML extraction
are deliberately small; report unsupported formats/hosts instead of claiming coverage.

Run offline acquisition checks with:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest discover -s shared/research_sources/tests -v
```

The scheduled executor permits its existing `.niulai-state/` write root. Runtime
source artifacts/caches therefore use `.niulai-state/reports/research-sources/`,
and investment snapshots/packets use `.niulai-state/reports/investment-research/`.
The dependency environment remains `.research-sources/.venv/` and is read-only
at execution. Older interactive artifact roots remain readable for compatibility.
Run scheduled commands with an explicit workspace directory; a relative interpreter
path from the scheduler's private working directory is not a valid invocation.
This layout fits existing runtime permissions without broadening them.

For scheduled execution, configure the real Node binary once from an interactive
shell where Node >=22 is installed:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -c \
  'from shared.research_sources.toolchain import configure_node; configure_node()'
```

The owner-private `toolchain.json` references immutable metadata containing the
resolved executable, version and binary hash. The scheduled adapter verifies this
reference and uses the absolute binary, so an interactive `fnm` shim is not a hidden
runtime dependency. Configuration refuses to overwrite an existing pointer; review
and explicitly migrate that pointer when replacing Node. Do not change global PATH,
shell profiles or the runtime's permission boundaries to make a test pass.

The incremental runtime cache and live capability matrix are documented in
[the scoped runtime runbook](../../docs/deployment/investment-research.md#current-incremental-candidate-immutable-execution-and-cache-validation).
`cache.py` reuses Store SQLite; `source_matrix.py`, `cache_matrix.py` and
`runtime_validation.py` expose bounded validation commands. Captured replay,
actual acquisition, cache integrity, requirement eligibility and semantic support
are reported separately. A source hit with inadequate coverage cannot become a
completed critical input. No new global dependency, active MCP entry or daemon
is installed by these modules.
