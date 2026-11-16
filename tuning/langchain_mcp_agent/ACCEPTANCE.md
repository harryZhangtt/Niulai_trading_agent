# Acceptance criteria — isolated MCP clients and trace-inspection agent

Status: FROZEN  
Revision/source: mcp-atomic-v1.1, 2026-11-16, independent designer; proposed client/agent implementation not inspected; baseline receipt and active-server preservation clarification below.  
Selected verification level: Balanced with independent deliberate-break controls.  
Why this level is enough: changed HTTP MCP, model/tool handoff, response/grader, bounded recovery and exact synthetic readback boundaries are included. No production tests, global/active host registration, private account reads, brokerage effects, billing scans, email, scheduler, load or autonomous inference.

## Assumptions and scope

- **R1**: user MCP/E2E addition delegated by the integration owner. **R2**: root/mentor policies, development-discipline, installed backend-testing-skill-set core/exception workflow. **R3**: frozen LC/SE and atomic v1.1 acceptance files. **R4**: captured actual MCP initialize/tools schema and owned exploratory results. **R5**: tuning/evaluation-design evidence rules. **R6**: owner-private source document revision 4473, SHA256 `654269626985fa210b39eb72e2238e7cc2a15a5cb2bc10d170babea2060bc4ba`; original remains in its private snapshot and is not copied here or into cases.
- This design/case file is inert/local. `shared/langchain_mcp` owns the bounded transport and tool/schema adapter; `tuning/langchain_mcp_agent` owns the synthetic inspection experiment and grader. No active-host/global MCP configuration, hook, browser, credential or server changes are authorized by these criteria.
- Endpoint allowlist is exact `http://127.0.0.1:2025/mcp` for the owned isolated Agent Server and `https://api.smith.langchain.com/mcp` for the existing authorized synthetic LangSmith workspace. Redirects, userinfo, URL overrides and credential forwarding to another endpoint are forbidden. Any endpoint change requires a new reviewed manifest. Active servers on both ports 2024 and 2025 remain untouched; this candidate is a client and four-read matched agent, not a server deployment.
- Only live-discovered allowlisted local `calculator`, `holdings`, `calculator_session` and remote `query_runs` tools may be used. Studio alias `trading_pilot` is not an MCP tool name. Captured remote initialize reports protocol `2025-06-18`; candidate supports an explicit frozen version set and must validate the negotiated version. `fetch_runs` is deprecated in the actual captured schema and is not an automatic fallback.
- Fixed synthetic task/trace selectors are the public ingress. The adapter, not model/user raw arguments, binds exact owned workspace/project/trace IDs from private receipts. No `ai_search`, arbitrary filters, reference-dataset expansion, broad billing/cost scans, unowned projects/traces, attachments or invocation parameters. Full/compact queries request only predeclared fields needed for this comparison.
- Before E2E, seal an owner-private live manifest containing two distinct immutable trace/root identities, exact project/workspace scope, independent reference outputs/hierarchy/status, source/config/schema/prompt/grader hashes and case roster, response fields, budgets and original accepted/failed UI histories. Trace immutability is a comparison precondition checked by exact before/after evidence, not assumed because a trace ID exists. Historical identities/content remain private.
- Frozen safety defaults: schema <= 262144 UTF-8 bytes; each decoded response <= 2097152 UTF-8 bytes and cumulative decoded data per logical read <= 4194304 UTF-8 bytes; JSON nesting <= 32; tool roster <= 100; per HTTP attempt timeout <= 10 seconds; each logical read's total active deadline <= 30 seconds; at most two HTTP attempts per declared replay-safe read and two pages per trace query; page_size <= 100. A documented smaller limit is allowed. Larger limits require a new contract revision. `Retry-After` beyond the deadline returns deferred/rate-limited without waiting or issuing another request. Measure cumulative decoded bytes across streamed chunks/pages as well as each response.
- Matched comparison: two immutable traces × full/compact = four logical `inspect_trace` calls across the round, maximum four. Every attempted logical tool invocation, including rejected/error calls, counts; transport attempts/pages are counted separately. Root's existing cooperative model budget remains bounded. The public default self-tests remain deterministic; host drives internal cooperative handoff and user is never asked to paste raw resume JSON.
- `response_utf8_bytes` measures the actual serialized tool response delivered to the model, `len(response.encode('utf-8'))`, including wrapper/JSON text. It is distinct from wire bytes, Python character count, tokens or money. Full and compact must preserve the same grade-relevant truth. A compactness-benefit claim is allowed only when exact measured bytes decrease on each paired trace; an unfavorable measurement is preserved, not relabeled or dropped.
- Existing 339 checks are a frozen baseline to preserve, with their original failures, skipped states, UI histories and source/config fingerprints. `cases.json` embeds the immutable baseline manifest reference/hash: the owned existing receipt reports 339 executed, zero skipped/failures/errors, PASS and scheduled business/email acceptance UNVERIFIED; SHA256 `b16888d309eb92802a408c77d3f608252cfb4640ab6baf5d83afc2d3b0cb41c9`. The previous failed 339 receipt and owned API/UI readback histories are hash-pinned separately. These records were read, not rerun by the designer. Old acceptance/config/source hashes were captured by reading bytes only. New candidate fingerprints must be sealed before live dispatch; missing or mutated evidence stays unverified/fails preservation respectively.
- Shared-workspace cases are independent development cases, not blind holdouts. Atomic controls may use synthetic protocol fixtures; changed-boundary E2E must execute the new candidate through real MCP. Earlier curl/exploratory successes, handshake/listing, mocks, UI labels and source imports cannot substitute. No quality/alpha/generalization or unattended-host claim is in scope.

## Criteria

### MCP-AC-001 — Endpoint and credential ownership are enforced before dispatch
- Requirement source: R1–R3. Risk: critical.
- Preconditions: frozen exact allowlist and fake sensitive canaries; no host registration.
- Action: use both intended endpoints, then wrong host/scheme/port/userinfo, override variable and redirect targets.
- Expected observable result: intended endpoint dispatch only; all other endpoints reject before network; credentials stay in their existing owner-private resolver and appear only on the authorized request.
- Forbidden result: copied credentials, cross-host forwarding, inherited redirect/base URL, global config mutation or secret-bearing diagnostics.
- Cases: MCP-01–03. Evidence: atomic dispatch/redirect canary controls; local/remote real E2E; mutation remove endpoint/redirect guard.

### MCP-AC-002 — Actual MCP version negotiation and message identity govern the session
- Requirement source: R1, R4. Risk: high.
- Preconditions: declared supported versions, bounded JSON/SSE transport and request IDs.
- Action: initialize, process initialized notification and list tools; inject unsupported version, mismatched response ID, malformed JSON/SSE, duplicate terminal response and error envelope.
- Expected observable result: only compatible version/session advances; required capability/session headers use the negotiated contract; one matching response accepted; invalid/error envelopes fail explicitly.
- Forbidden result: treating HTTP 200 as success, skipping negotiation, silently accepting incompatible version or reusing another request's result.
- Cases: MCP-04–06. Evidence: atomic protocol inverses; real initialize/list records; mutation bypass negotiation/ID/error gate.

### MCP-AC-003 — Live tool names and schemas bind calls
- Requirement source: R1, R4, R6. Risk: high.
- Preconditions: exact live tools/list schema hash and tool allowlist.
- Action: call actual local tools/remote query_runs; request Studio alias, deprecated fetch_runs, unknown tool and invalid required/extra arguments.
- Expected observable result: real MCP names/schema used; invalid/unallowlisted tools or arguments reject before call; query_runs uses current boolean/enum/select/pagination schema; runtime schema drift is visible.
- Forbidden result: alias inference, deprecated hidden fallback, arbitrary discovered tool exposure, stale tutorial API assumed current or passing malformed arguments.
- Cases: MCP-07–09. Evidence: atomic schema controls; real local calculator/holdings and remote query_runs E2E; mutation accept alias/extra fields/stale schema.

### MCP-AC-004 — Parsing, time and resources remain bounded under hostile responses
- Requirement source: R1, R2. Risk: high.
- Preconditions: frozen safety bounds, controlled streaming/clock and owned resources.
- Action: return oversized/deep/malformed/nonterminal/slow/chunked responses; cancel before/after response receipt.
- Expected observable result: limits enforce before unbounded allocation/export; decoded cumulative UTF-8 bytes are counted; deadline/cancellation closes owned sessions/bodies; explicit failure/defer remains inspectable.
- Forbidden result: unlimited stream/pages/schema growth, character-count byte bypass, orphan socket/client, swallowed error or late unintended tool commit.
- Cases: MCP-10–12. Evidence: atomic boundary and controlled cancellation tests; local failure integration; mutation remove cumulative bound/cleanup.

### MCP-AC-005 — Read rate limits use bounded pacing and one retry authority
- Requirement source: R1, R2. Risk: high.
- Preconditions: replay-safe read classification, monotonic deadline, attempt ledger.
- Action: return 429 with delta-seconds/date Retry-After, malformed header, repeated 429 and a delay beyond remaining deadline.
- Expected observable result: valid minimum delay honored; bounded deterministic pacing/read attempts recorded; malformed policy handled explicitly; out-of-budget delay defers without early request; permanent auth/schema errors stop.
- Forbidden result: ignoring Retry-After, overlapping retries, inner×outer multiplication, busy loop or retrying permanent failure unchanged.
- Cases: MCP-13–15. Evidence: atomic controlled-clock probes; local read-limit injection; mutation unconditional retry/remove pacing.

### MCP-AC-006 — Possible writes and unknown outcomes cannot be blindly replayed
- Requirement source: R1–R3. Risk: critical.
- Preconditions: per-tool effect/replay classification and owned intent/receipt identities; local tool may create run state despite economic read-only semantics.
- Action: lose acknowledgement/reset/cancel after tools/call may execute; restart/reissue command; invoke unclassified tool.
- Expected observable result: write/unknown/unclassified operation held; reconcile exact owned identities/end state before replay; classified remote query reads may retry only within read policy; prior failure/unknown receipt stays immutable.
- Forbidden result: classifying all POSTs as writes or all analytics/read-only names as replay-safe, duplicate local run/tool effect, clear-fence-and-rerun or replay to obtain cleaner evidence.
- Cases: MCP-16–18. Evidence: atomic before/during/after acknowledgement controls; local MCP reconciliation integration; mutation clear unknown fence/unconditional call retry.

### MCP-AC-007 — Trace queries cannot broaden owned synthetic scope
- Requirement source: R1, R3–R5. Risk: critical.
- Preconditions: exact private owned workspace/project/two-trace allowlist and fixed selectors.
- Action: inspect each trace; try foreign workspace/project/trace, absent scope, broad billing/AI query, arbitrary filter/cursor and extra/full sensitive fields.
- Expected observable result: query generated by adapter binds exact owned scope, explicit frozen time bounds/fields and page limits; foreign result records reject; pre-callback export is allowlisted/sanitized; cursor retains same scope.
- Forbidden result: name-only identity, all-project newest-run query, private account/input export, billing scan, arbitrary query execution or cursor scope loss.
- Cases: MCP-19–21. Evidence: atomic dispatch/result/canary controls; real exact query readback; mutation remove scope/result guard.

### MCP-AC-008 — New candidate executes the real MCP path end to end
- Requirement source: R1, R3, R4. Risk: high.
- Preconditions: sealed candidate fingerprint, owned server/remote identities and bounded real execution.
- Action: new client performs initialize → tools/list → tools/call for calculator, holdings and exact remote trace; cooperative agent invokes inspect_trace using that same client.
- Expected observable result: actual local calculator nominal per-share 10 and holdings net 700/gross 1100 independently match expected synthetic results; remote records match exact immutable trace; candidate transport/tool receipts prove the path.
- Forbidden result: old exploratory/curl success, fixture-only SDK result or handshake called new-client E2E; Studio alias substituted; direct SDK bypass hidden inside inspect_trace.
- Cases: MCP-22–23. Evidence: fresh candidate real local/remote MCP and actual model-selected inspect_trace receipt; mutation replace MCP with fixture/direct SDK.

### MCP-AC-009 — Host supplies only model work through internal handoff
- Requirement source: R1–R3, R6. Risk: critical.
- Preconditions: current host SessionChatModel, persisted binding/request/thread and allowlisted inspect_trace tool.
- Action: create inspection task, host responds to internal interrupt; submit stale/duplicate/foreign response and forbidden raw resume input.
- Expected observable result: host selects tool via assistant message; framework executes real tool; final state follows exact bound receipt; handoff state persists; public user flow requires no raw resume JSON or credential/token copy.
- Forbidden result: host-forged tool receipt, scripted inference, arbitrary user resume payload, lost state/replayed admission or unattended wake-up/backend attestation claim.
- Cases: MCP-24–25. Evidence: atomic session admission controls; actual cooperative inspection E2E; mutation allow forged/foreign reply.

### MCP-AC-010 — Logical tool and transport budgets are separately observable
- Requirement source: R1, R2, R5. Risk: high.
- Preconditions: four-call matched round and explicit per-read attempts/pages/model bounds.
- Action: run two traces in both arms, attempt a fifth tool invocation, nonterminal model loop and pagination/retry pressure.
- Expected observable result: four-call maximum enforced before fifth dispatch; failed/rejected logical invocation counts; HTTP attempts/pages/bytes remain separately bounded and reported; exhaustion stays explicit.
- Forbidden result: budget counted only on successful calls, unlimited calls hidden by retry/page wrapper, fabricated observed zero cost or changing budget after results.
- Cases: MCP-26–27. Evidence: atomic budget inverses; exact fresh comparison receipts; mutation increment after success/remove fifth-call gate.

### MCP-AC-011 — Independent grading verifies actual root, output, hierarchy and scope
- Requirement source: R1, R3–R5. Risk: critical.
- Preconditions: two privately sealed reference traces and independent grader closure, not model assertions or output previews.
- Action: grade actual full/compact responses; alter root, numeric output, parent, node roster/error status or project/trace scope.
- Expected observable result: exact actual root/output and expected hierarchy/node set/status/scope agree with independent reference; missing/truncated/foreign/duplicate node fails; root is observed, not inferred from trace ID equality.
- Forbidden result: model self-grade, correct-looking final value masking wrong hierarchy/scope, preview substring accepted as full output or one critical failure averaged away.
- Cases: MCP-28–30. Evidence: atomic wrong-root/output/parent/roster controls; exact independent real readback for both traces/arms; mutation weaken full-output/hierarchy checks.

### MCP-AC-012 — Paired bytes reflect the exact model-visible response
- Requirement source: R1, R5. Risk: high.
- Preconditions: same two immutable trace identities, identical scope/oracle/budgets and frozen full/compact fields.
- Action: inspect all four pairs, serialize actual tool responses and independently count UTF-8 bytes; inject multibyte text or lossy compact projection.
- Expected observable result: exact byte counts and paired semantic grades recorded; compact retains root/output/hierarchy/scope/errors; full/compact source traces remain unchanged before/after; unfavorable byte results preserved. Byte-reduction claim needs strict reduction on each trace.
- Forbidden result: comparing different traces/fields/time windows, counting characters as bytes, stripping output/errors to win, equating bytes with tokens/cost or generalizing from two traces.
- Cases: MCP-31–32. Evidence: atomic multibyte/projection inverses; exact four-response serialization/readback table; mutation len(text)/drop-parent-output.

### MCP-AC-013 — Baseline, failures, document revision and source/config remain reviewable
- Requirement source: R1–R3, R5, R6. Risk: high.
- Preconditions: old frozen artifacts and original 339 execution/UI evidence; new source/config/prompt/grader fingerprints sealed before live work.
- Action: finalize comparison report and rerun applicable baseline checks; introduce material drift, missing baseline record or replaced failure history.
- Expected observable result: previous acceptance/case/source/config hashes match frozen capture; baseline executed/skipped/failed counts and failed UI histories are retained; document revision/hash and practical takeaways distinguish old examples from tested current APIs; new candidate evidence binds exact source/config used.
- Forbidden result: editing old expectations/results, historical proof relabeled new acceptance, copying private document/content/IDs to public cases or a 339 count treated as execution proof.
- Cases: MCP-33–34. Evidence: independent hash/diff/baseline/evidence review; mutation drift source/delete failed history.

### MCP-AC-014 — Isolation, default self-tests and failure recovery are honest
- Requirement source: R1–R3. Risk: high.
- Preconditions: owned local client/agent resources, deterministic public default self-tests and reviewed rollback.
- Action: exercise default URL/schema/test operation, interrupted initialize/read/cooperative handoff, cleanup and source/config rollback; review all outcomes.
- Expected observable result: default self-tests use deterministic graphs with correct visible labels; cooperative graph requires host service only through internal handoff; no existing server/global host mutation; owned resources close and diagnosis/recovery remains available; PASS/FAIL/BLOCKED/NOT RUN, all attempts and mutations reported separately.
- Forbidden result: UI health/listing as completed model inference, blocked recovery/prompts, private data migration, orphan process, claiming runtime/production/email acceptance or hiding zero/skipped/unknown evidence.
- Cases: MCP-35–36. Evidence: actual default public MCP self-test and local lifecycle/rollback; independent verification report; mutation skip cleanup/report skipped as pass.

## Practical takeaways to freeze and verify

1. Treat MCP as a transport/tool contract: discover and negotiate the actual deployed schema before binding tools. Keep the transport reusable and business/experiment policy separate.
2. Keep the first path small: deterministic calculator/holdings tests prove MCP dispatch; the cooperative inspection run separately proves actual model-selected tool use. A persistent interrupt is workflow state and still requires an available host to service it.
3. Use the installed/current agent API for this workspace. Legacy tutorial agent construction and generic raw resume demonstrations do not establish compatibility with LangChain 1.5 or a suitable user flow.
4. Query exact owned immutable traces and grade observable end state independently. Compact projections are acceptable only when they preserve required truth; measure response bytes directly rather than assuming fewer fields imply less context or cost.
5. Preserve query/write classification, pacing and unknown fences inside the transport boundary. Adding an active host MCP registration is a separate, excluded rollout.

These are candidate design lessons to test, not claims that the new implementation or two-trace experiment already passed.

## Independent development cases

`cases.json` contains 36 compact requirement-derived cases, mutation controls and captured old artifact/source hashes. Private real trace IDs, credentials, raw document content and oracle payloads are excluded. Actual live reference bindings belong only to the owner-private sealed manifest. Designer did not inspect proposed client/agent source. A surviving deliberate break is a finding to classify and repair, not a success.

## Amendments after freeze

| Time | Criterion | Change | Behavioral reason | Requested/approved by | Affected tests |
| --- | --- | --- | --- | --- | --- |
| 2026-11-16 | Scope, MCP-AC-013/014 | v1.1 pins located immutable baseline339 receipt, previous failed339 and API/UI history hashes; explicitly preserves active2024/2025 | Integration owner requested final minimal client/four-read packet and active-server preservation; designer located actual existing baseline evidence without rerun | Independent designer, integration-owner clarification | MCP-33–36 |
