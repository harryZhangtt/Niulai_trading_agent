# Codex and Claude acquisition host adapters

Status: **PROPOSED — PROVIDER-FREE CANDIDATE, LIVE ACCEPTANCE PENDING**, 2026-11-05. The current candidate has shared local contracts and host-specific adapters, but this document does not claim either host has completed the sealed live-provider E2E, that MCP is active, or that information quality improved.

## Goal and non-goals

Use one acquisition state machine and evidence contract across Codex and Claude while keeping host tools, credentials, caches, runtime state, limits, and observed identities separate.

The abstraction must make these paths easy to operate and compare:

```text
sealed case + shared acquisition contract
├── codex_native_web → native_tools.web__run
└── claude_code_web → WebSearch / WebFetch
        └── later: claude_api_server_web, only after separate SDK/auth review
```

It does not:

- convert host-specific outputs into publisher-original bytes;
- make Codex and Claude independent evidence when they read the same disclosure;
- share credentials or mutable cache/state between hosts;
- silently switch hosts after an error;
- enable MCP, install a provider SDK, or alter global/user settings;
- establish acquisition-quality improvement, forecast value, or investment alpha.

## Shared boundary

The following remain provider-neutral and single-owned:

| Capability | Current owner | Invariant |
|---|---|---|
| IDs, exact arguments, failure taxonomy, alternate descriptors | `shared/research_sources/acquisition_contracts.py` | Same logical operation has stable IDs and canonical argument bytes. |
| Admission, budgets, deduplication, fallback selection | `investment/research/acquisition_orchestration.py` | One logical accounting policy; no host changes the experiment budget. |
| Dispatch journal, deadlines, raw bound, restart fence | `investment/research/acquisition_runner.py` | One active dispatch, append-only identity-bound receipts, unknown outcomes never replay. |
| Host preparation, capture, screening, cache | `shared/research_sources/host_web.py` | Cache/provider namespace includes configured backend; exposed representation and limitations stay explicit. |
| Assessment, unit, independent review, recovery | `investment/research/acquisition_driver.py` | Provider-free repair imports existing immutable refs and never calls a host. |
| Cross-ledger reconciliation and trace checking | `investment/research/acquisition_trace.py` | Reopen source artifacts; never trust the runner, host, model, or UI summary alone. |
| Cooperative session lifecycle | `investment/research/acquisition_live_session.py` | Same `init → next → capture → assess → review → finalize` protocol. |
| Read-only projection | `investment/research/acquisition_projection.py` | Only checker-approved, sanitized traces cross into the UI. |

Host adapters own only capability negotiation, tool-input mapping, exact host-result capture, host/tool identity, and representation limitations.

## Adapter profile contract

A sanitized source/config profile contains references and declared capabilities, never credentials:

```json
{
  "schema_version": "acquisition-host-profile-1",
  "adapter_id": "codex_native_web",
  "configured_backend": "native_tools.web__run",
  "allowed_tools": ["native_tools.web__run"],
  "capabilities": {
    "search": true,
    "open": true,
    "find": true,
    "publisher_byte_attestation": false,
    "rendered_extract": false,
    "max_items_per_dispatch": 1
  },
  "credential_ref": {
    "owner": "codex-runtime-owner",
    "source": "host_managed",
    "profile_id": "codex-acquisition-owner"
  },
  "mcp_profile_ref": null,
  "runtime_policy_ref": "runtime-policy-sha256-or-private-ref"
}
```

```json
{
  "schema_version": "acquisition-host-profile-1",
  "adapter_id": "claude_code_web",
  "configured_backend": "claude_code.web",
  "allowed_tools": ["claude_code.WebSearch", "claude_code.WebFetch"],
  "capabilities": {
    "search": true,
    "open": true,
    "find": false,
    "publisher_byte_attestation": false,
    "rendered_extract": true,
    "max_items_per_dispatch": 1
  },
  "credential_ref": {
    "owner": "claude-runtime-owner",
    "source": "host_managed",
    "profile_id": "claude-code-active-session"
  },
  "mcp_profile_ref": null,
  "runtime_policy_ref": "runtime-policy-sha256-or-private-ref"
}
```

A later Claude API profile is a separate adapter and credential owner:

```json
{
  "schema_version": "acquisition-host-profile-1",
  "adapter_id": "claude_api_server_web",
  "configured_backend": "anthropic.messages.server_web_20260209",
  "allowed_tools": ["web_search_20260209", "web_fetch_20260209"],
  "credential_ref": {
    "owner": "anthropic-api-runtime-owner",
    "source": "anthropic_profile_or_environment_reference",
    "profile_id": "private-profile-reference"
  },
  "mcp_profile_ref": null,
  "status": "later_candidate"
}
```

The later profile must use the official Anthropic SDK. It is not implemented by treating Ferry's OpenAI-compatible gateway or a Claude Code session token as an Anthropic API credential.

## Credential isolation

Credentials are host-owned runtime dependencies, not shared acquisition inputs.

Rules:

1. Store only an opaque credential reference and owner in private runtime state. Source, fixtures, prompts, logs, CLI arguments, API responses, screenshots and trace receipts contain no value.
2. Codex never reads Claude/Ferry/Anthropic auth, and Claude never reads Codex auth. No synchronization or copy operation exists.
3. A readiness check may establish only `present`, `missing`, `expired`, `blocked`, or `unknown`; it never prints a token or claims upstream identity from file presence.
4. Each execution binds its adapter/profile reference hash. A different credential owner or profile requires a new execution ID and sealed config.
5. Authentication failure is a policy/authorization outcome. It does not trigger cross-host fallback or unchanged retry.
6. Ferry remains optional personal Claude configuration. Its model catalog HTTP success is not evidence of Claude acquisition tool execution or Anthropic API identity.
7. Rollback never deletes or rewrites host credentials. It stops using the adapter/allocation and preserves unknown-outcome evidence.

## Capability negotiation and tool mapping

Before reservation, the live session intersects the sealed operation with the chosen adapter capabilities. Unsupported operations fail without spending logical or provider budget.

| Acquisition operation | Codex mapping | Claude Code mapping | Claude limitation |
|---|---|---|---|
| one search query | `native_tools.web__run(search_query)` | `WebSearch({query})` | Domains/recency/multi-query are rejected until exact semantics are specified and tested. |
| one full-URL open | `native_tools.web__run(open)` | `WebFetch({url, frozen prompt})` | Output is `rendered_extracted_representation`, not publisher-original bytes. |
| find/line locator | native `find` | unsupported | Fail before reservation; do not emulate with another prompt. |
| batch operations | rejected in narrow E2E | rejected | One item keeps accounting and identity exact. |

For Claude Code, literal support is limited to text present in the exact captured rendered extract. The source URL comes from the sealed, identity-checked tool input, not from an arbitrary string in the output. Codex keeps its existing stricter native URL/body checks.

## Identity and receipts

Every dispatch records both adapter-level and operation-level identities:

```json
{
  "experiment_id": "...",
  "execution_id": "...",
  "trace_id": "...",
  "operation_id": "...",
  "attempt_id": "...",
  "dispatch_id": "...",
  "adapter_id": "claude_code_web",
  "host_identity": "host-reported-or-configured-session-id",
  "configured_backend": "claude_code.web",
  "tool_identity": "claude_code.WebFetch",
  "acquisition_arguments_sha256": "...",
  "tool_input_sha256": "...",
  "raw_result_sha256": "...",
  "representation_scope": "rendered_extracted_representation"
}
```

The runner receipt binds the configured backend. The host capture binds the exact allowed observed tool. Under the selected `operational_host_evidence` policy, each dispatch also carries a host-returned operational receipt binding the host session, optional host event/tool-call ID (or an explicit unavailable reason), dispatch, exact input hashes, result hash, timestamps and terminal status. Credential readiness and independent review likewise carry separate operational session receipts. These records are practical runtime evidence but are locally retained and do not resist malicious same-user file forgery; no cryptographic remote-attestation claim is made. Synthetic receipts are never live-acceptance eligible.

The checker requires operation-compatible identities and rejects:

- a Claude receipt in a Codex run or vice versa;
- WebSearch for an open or WebFetch for a search;
- changed tool input, arguments, host identity, dispatch ID or raw hash;
- missing/unreported tool identity represented as a known value;
- adapter output that claims stronger representation fidelity than its capability profile.

## State, cache and unknown fences

Each arm/host gets distinct execution, trace and dispatch IDs plus a private non-symlinked root:

```text
.research-sources/live-e2e/<case>/<candidate>/<host>/<execution-id>/
```

Never share mutable state, runner journals, HostWeb heads, cache directories, raw files or temporary paths across hosts or arms. A canonical public information identity may later relate reviewed units, but that is not a cache key or a dispatch deduplication key.

Both adapters reuse the same durable states:

```text
prepared → claimed → definitely_not_dispatched | invocation_started
invocation_started → captured | possibly_dispatched
possibly_dispatched → captured only through authoritative provider-free reconciliation
```

No host fallback occurs after `invocation_started`, timeout-after-possible-dispatch, circuit-open or unknown outcome. Terminal status and failure code are one closed contract: unknown-class codes require `unknown`, while a sealed alternate follows only a known `failed` representation outcome. A failed Codex run is retained as the Codex result; Claude does not silently rescue it. Cross-host comparison launches a separately sealed execution.

## Retry, throughput and fallback

The narrow live E2E uses concurrency one and no unchanged retries. It exposes provider instability instead of retrying until green. Operational receipts count the adapter dispatch and host tool invocation; underlying HTTP requests and host-internal retries remain explicitly unknown unless reported by that host.

- validation, auth, policy, source/code drift: terminal;
- unknown or post-dispatch deadline: fence and reconcile;
- 401/403/404: terminal;
- 429/503/transport failure: record transient/circuit result; no retry in the narrow comparison;
- sealed representation failure: one predeclared semantically equivalent alternate within the same host and budget;
- identical failed arguments under another operation ID: reject.

Later throughput may parallelize independent issuer-window executions under a small configured cap. Each retains its own root, cache and single active dispatch. Do not introduce Kafka, Redis, Temporal, an always-on queue, or distributed locking without measured workload pressure.

## MCP boundary

MCP is not required for the web adapters. The prior host crash followed active TradingView/Schwab MCP additions; root cause remains unknown. Therefore:

1. Keep active `.codex/config.toml`, Claude settings and workspace runtime free of new acquisition MCP registrations.
2. Store MCP proposals in a separate disabled candidate file. Host profiles refer only to a candidate ID/hash, never an active endpoint or credential value.
3. Validate candidates through isolated protocol clients with network-free startup, bounded handshake/tool-list/query deadlines, strict read-only tool allowlists, queue limits, cancellation, process cleanup, malformed output, connection loss, auth-blocked and unknown-outcome cases.
4. Require one real isolated provider query on the final transport; a handshake or tool listing is insufficient.
5. Validate one provider in a separate host launch, record crash diagnostics, and retain whole-table rollback. Do not hot-add during an active development session.
6. Activation is a separate explicit decision and requires fresh setup sync plus future host/runtime acceptance. Codex activation does not activate Claude, and credentials remain separate.

## Cooperative operator flow

Both hosts use the same application commands and private files:

```text
acquisition_live_session init
acquisition_live_session next
<host invokes exact returned tool once>
acquisition_live_session capture --raw-result-file <private bounded JSON>
... repeat only when session returns another authorized operation ...
acquisition_live_session assess
acquisition_live_session review
acquisition_live_session finalize
acquisition_live_session status
```

The host-specific wrapper must:

1. read only the public `next` response;
2. verify its own adapter/tool identity;
3. call exactly the returned tool input once;
4. persist exact JSON output privately before emitting prose;
5. call `capture` with exact observed identity and input;
6. print only the bounded screened response;
7. preserve ambiguous journals and stop on user control, permission denial or unknown outcome.

A model assertion, tool list, handshake or supervising-shell exit code is never the business postcondition.

## Matched Codex/Claude live evaluation

Use one sealed case and policy but derive separate host configs, executions, roots and caches. Counterbalance host order across development issuer-windows. Do not let either host see the other's output.

Report separately:

- actual host dispatches and unknown outcomes;
- usable screened bodies/read attempts;
- unique supported canonical units;
- net required-field transitions;
- independent lineages and redundancy;
- authenticated freshness/detection lag and unknown rate;
- complete chains / credited units;
- wall time, tool calls, and observed token/cost where available;
- provider-specific representation limitations.

The issuer-window is the independent unit. Same-disclosure outputs from Codex and Claude are correlated repeated measures, not independent discoveries. Missing or mixed evidence is inconclusive.

No cross-host winner is promoted from one NOW positive control. Use the development micro-A/B and untouched confirmation contract in `docs/plans/information-yield-dashboard.md`.

## Acceptance and email

A local/provider-free pass permits only structural claims. Each host requires its own actual future execution evidence bound to its final adapter/config fingerprint. Current workspace major-runtime acceptance names a scheduled Codex session specifically; it does not automatically accept Claude. A Claude acceptance lane must record the actual Claude session/tool identities and equivalent independent postconditions, then update the acceptance contract/runbook before being treated as a workspace acceptance route.

Email synchronization, when required, uses the validated owner-private sender and exact readback. Codex and Claude result messages use distinct stable run IDs. Unknown sends remain fenced; one host never resends the other's message. Missing Gmail authorization keeps email status incomplete without changing execution evidence.

## Setup and runbook ownership

Changes must update in the same change:

- `docs/deployment/datasource.md`: adapter/tool identities, commands, failures, roots and tested scope;
- `docs/local-setup.md`: component row, runtime prerequisites and private-state ownership;
- `docs/deployment/setup-inventory.json`: sanitized declared sources, tests and prerequisites;
- `docs/deployment/setup-lock.json`: refreshed only after all owners report stable hashes;
- `docs/mcp-stability.md`: only when an MCP candidate or host-isolation result changes;
- `docs/deployment/runtime-acceptance.md`: only after a reviewed Claude acceptance lane is actually defined.

Then run `python3 shared/setup_audit.py --refresh` once and `--check`. Setup sync proves documentation consistency, not live host readiness.

## Rollback

Rollback is additive and host-specific:

1. Stop staging new allocations for the affected adapter.
2. Preserve pending, possibly-dispatched, unknown and final journals plus exact config hashes.
3. Do not delete or replay ambiguous state to obtain a clean dashboard.
4. Remove only the new private test allocation after it is terminal and reconciled.
5. Leave the other host adapter and credentials untouched.
6. Restore active host config only from an owned pre-change receipt after reconciling later edits.
7. Keep source/candidate configuration disabled by default until a later reviewed activation.

## Staged migration

### MVP

1. Freeze provider-neutral host profile schema and tool allowlists.
2. Run both provider-free cooperative lifecycles through the same live session, runner, HostWeb, driver and checker.
3. Seal separate Codex and Claude Code runtime profiles and private roots.
4. Pass component, full fault-matrix, identity-substitution, setup and browser projection gates.
5. Run one bounded smoke per host, then one exact positive-control E2E per host.
6. Project host identity and representation limits visibly.
7. Run a matched development micro-A/B only after both E2Es reconcile.

### Later

- Official Anthropic SDK/Claude API server-web adapter after dependency/auth/retention review.
- Bounded multi-case concurrency after measured serial cost/latency establishes need.
- Disabled MCP candidates after isolated protocol/live-provider/cleanup evidence.
- Separate future Claude runtime acceptance and email lane.
- Untouched multi-issuer confirmation and information-yield dashboard.

Do not build a generic provider framework, secret broker, distributed scheduler, streaming analytics platform or automatic MCP activator.

## Expected file impact

Current candidate and tests:

- `shared/research_sources/acquisition_contracts.py`
- `shared/research_sources/host_web.py`
- `investment/research/acquisition_runner.py`
- `investment/research/acquisition_driver.py`
- `investment/research/acquisition_trace.py`
- `investment/research/acquisition_live_session.py`
- `investment/research/acquisition_claude_code.py`
- corresponding `investment/research/tests/test_acquisition_*.py`
- `tuning/evals/information_fetch/live_e2e/`

Potential small follow-up:

- one provider-neutral `host_adapter_contracts.py` only if duplicated validation is demonstrated by the integrated tests;
- private host profile envelopes below each execution root;
- no active MCP or credential source file.

UI projection remains read-only under `ui/datasource/src/AcquisitionTrace/` and must display configured host, observed tool, representation scope and limitations without exposing raw output, private paths or credential references.
