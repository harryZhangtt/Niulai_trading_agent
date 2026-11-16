# Acceptance — canonical Trading Agent, first real holdings path

Status: FROZEN  
Revision: trading-agent-v1, 2026-11-16, independent designer; new integration source not inspected.  
Verification level: Balanced, independent offline failure/mutation controls plus one user-authorized real read-only snapshot and private analysis E2E.  
Scope decision: one canonical user-visible root graph, `trading_agent`. Existing capabilities migrate as independently verified internal subgraphs. The first delivered vertical path is Tiger credential lifecycle → positions/assets snapshot → admission → existing portfolio analysis → private local Studio result. This packet does not certify the remaining migration.

## User scenarios

| Input | Action | Visible result | Visible failure |
| --- | --- | --- | --- |
| Analyze holdings | Trading Agent obtains native access internally, reads positions/assets and analyzes them | Private portfolio summary with exact scope, source times, cash/NAV/exposures and unavailable fields | Access or read failure is shown; no misleading empty portfolio |
| Analyze holdings when native access is unavailable | Internal host helper checks access | Clear waiting/access-needed state; the conversation remains usable | No request to paste tokens, credentials or raw resume JSON |
| Analyze holdings after a complete requested-scope empty read | Analyze the confirmed empty result | Empty holdings within the requested scope; assets and coverage remain explicit | Requested scope is never presented as verified whole-account coverage |
| Analyze holdings with partial or failed snapshot | Preserve the read failure and gaps | Failure/partial status and a useful next action | No complete portfolio analysis from missing position types or failed assets |
| Analyze holdings with ambiguous account or currency | Validate snapshot identity and scope | Matching supported scope continues | Mismatch/ambiguity remains visible; no first-account choice or invented currency conversion |
| Analyze holdings when quote time is unknown | Preserve original source time/availability | Query time and quote time are distinguished; freshness can be unknown | A successful new query never makes an old/unknown quote fresh |
| Resume the same interrupted analysis | Recover the original workflow identity and receipts | Completed safe work remains; accepted data can proceed to analysis | Unknown acquisition/checkpoint/read is held for reconciliation and is not automatically replayed |
| Repeat the same completed request | Read its accepted result | The original private result is returned | No repeated credential acquisition or broker read for the same request |
| Open local Studio | Connect to the canonical Trading Agent on the new local instance | One root graph, its internal workflow and exact private outcome are inspectable | A printed link, health response or source import is not Studio acceptance |
| Ask what has migrated | Show the capability inventory and evidence status | Holdings path and remaining calculation/research/web/runtime capabilities have separate honest statuses | No claim that all Trading Agent capabilities or scheduled business effects have migrated |

Product labels stay simple. Gateway, lease and checkpoint mechanics below are internal verification controls, not extra visible agents or a raw-token/resume user flow.

## Scope, sources and authority

- **R1**: user-authorized Tiger vertical path and subsequent correction to one canonical Trading Agent, delegated by integration owner. **R2**: root/mentor instructions, development-discipline, backend-testing-skill-set core/exception/live guidance. **R3**: maintained `shared/tiger/README.md`. **R4**: holdings boundary review and frozen LC/SE/atomic/MCP contracts. **R5**: tuning/evaluation-design rules. Existing source was used only as an established public contract; no credentials, private account artifacts or new integration source were read by the designer.
- Source/case files are inert/local. An isolated server candidate on `127.0.0.1:2027` with new private persistence may expose the single canonical graph. Preserve active 2024/2025, frozen baseline339/MCP receipts and original snapshots. No active host/global MCP registration, hook, scheduler, email, brokerage order, transaction-history, OAuth consent/forced rotation or production sender change.
- Root graph owns durable thread/request/action/config identity and legal transitions. Internal host helper owns fresh native Sites `get_site` handoff through private pipes. Existing `shared/tiger` exclusively owns configured project/origin/sole owner, lease, restore, token saves/checkpoints, unresolved fence and remote reconciliation. Existing portfolio adapter/analytics owns admitted financial calculations. These authorities must not be duplicated.
- Public graph input is only closed action `analyze_holdings`; unknown fields/actions, account IDs, endpoints, credentials, raw financial inputs, tool/resume commands or caller-supplied private paths reject before native context, credential or provider I/O. Requested security types are fixed before dispatch in the private run manifest: unique nonempty subset of STK/OPT/FUT/FUND; existing default is STK/OPT/FUT. FUND requires explicit fixed four-type scope. Currency/account policy is owner configuration, not public input.
- Persist opaque thread/request/attempt/action/config identity and effect claim before native access or gateway dispatch. Host services native authorization internally; native context/service bearer/broker tokens never enter graph input, state/checkpoint, resume arguments, environment, command arguments, saved JSON, source, public output or logs. Secret-bearing material is pipe/memory only, aside from the gateway's existing protected credential custody.
- Reuse exactly one gateway snapshot portal/worker attempt. Preserve existing store-only idempotent acquire/checkpoint retry policy: maximum three attempts, identical IDs/bytes, 15-second timeout and 1/2-second backoff. No outer broker/OAuth retry. Existing budgets remain worker100s, supervisor105s, portal request110s/total115s and launcher125s, escalation1.5s. New orchestration must not multiply or silently enlarge them.
- Same remote private store and local nonblocking lock remain the credential owner. Every observed SDK token save checkpoints under the same lease; final committed checkpoint requests release. A committed release request is not a separate verified lease-release receipt. Do not fabricate actual rotation, release, fresh quote, account completeness or uninterrupted availability.
- Private gateway artifacts use owned 0700 directories/0600 regular files; no symlink/path escape. New graph persistence and analysis outputs are workspace-local, private and excluded from version control, separately rooted from old servers. Raw account values and permitted private output stay local. Cloud tracing/export is forcibly off before framework callbacks, even with inherited LangSmith keys/tracing settings; no live payload enters LangSmith datasets, traces, telemetry attachments or public reports.
- Offline tests use newly authored synthetic data/canaries and injected dependencies; no private historical fixture reads, actual credential access or live failure injection. The single real read is explicitly user-authorized, exact configured owner/project/unique STANDARD-account scope, concurrency1 and one snapshot attempt. Independent verifier checks actual private artifacts and results locally; public evidence reports sanitized IDs/counts/hashes/status only.
- Before live dispatch, seal private candidate source/config/schema/pins/run/budget/type-policy fingerprints and immutable old baseline references. Freeze arithmetic/formula and semantic grading rules here; after actual fetch, the independent verifier derives expectations locally from admitted source values without relying on the analysis implementation's assertions. No live numerical oracle is invented before acquisition.
- All missing evidence stays BLOCKED/NOT RUN/unverified; observed critical violation is FAIL and cannot be averaged away. Same request replay is held; a new explicitly scoped request is distinct from retrying an unknown operation. Scheduled business/email acceptance remains UNVERIFIED under `docs/deployment/runtime-acceptance.md`.

## Internal acceptance controls

### TGA-AC-001 — One canonical root and a closed action boundary
- Source: R1, R2, R4. Risk: critical.
- Precondition/action: inspect registered root/schema; submit analyze_holdings and unknown/extra/account/token/endpoint/resume inputs.
- Observable: one visible `trading_agent` root; only valid closed action admitted, with internal capability subgraphs; invalid input rejects before native/credential/provider dispatch.
- Forbidden: visible standalone Tiger trial, arbitrary tool/account selection, raw resume/token input or validation after credential I/O.
- Cases/evidence: TGA-01–03; atomic ingress inverses and actual public schema; mutation bypass strict schema.

### TGA-AC-002 — Durable identity precedes effects and prevents replay
- Source: R1–R4. Risk: critical.
- Precondition/action: begin request, interrupt before/during/after gateway dispatch, repeat same request or race two admissions.
- Observable: durable same thread/request/attempt/action/config claim exists before first effect; at most one admission; completed result reused; submitted/unknown operation held for exact reconciliation.
- Forbidden: new attempt/thread hides lost state, claim after effect, duplicate snapshot or same request reissued after timeout.
- Cases/evidence: TGA-04–06; atomic controlled barriers/private journal and public resume integration; mutation remove pre-effect claim/dedup.

### TGA-AC-003 — Native authorization is fresh, exact and private-pipe only
- Source: R1–R3. Risk: critical.
- Precondition/action: host obtains actual fresh native Sites result; inject stale/wrong project/origin/owner/audience, missing context, denied access and nested secret canaries offline.
- Observable: existing policy validates exact configured sole owner/project/origin before lease; safe internal auth-needed state; host sends context privately with no user raw credential/resume burden; definitive pre-acquire401/403 has no fabricated acquired-lease fence.
- Forbidden: copied saved Sites/token input, broad audience, raw context in graph/checkpoints/resumes/logs/cloud or hidden browser/OAuth fallback/retry.
- Cases/evidence: TGA-07–09; offline pre-lease and secret-sink controls plus actual native handoff proof in private evidence; mutation post-state validation/context leak.

### TGA-AC-004 — Existing lease/restore/checkpoint authority is retained
- Source: R1–R3. Risk: critical.
- Precondition/action: gateway performs snapshot with simulated token saves/checkpoint failure or lock contention; real read observes actual lifecycle receipts.
- Observable: single configured store/lease owner and local lock; restore and each save/final checkpoint bind same lease; only identical store acquire/checkpoint retry is bounded; rotation/release facts are reported only when actually observed.
- Forbidden: second credential cache/owner, copied old token restoration, independent refresh/consent, broker/OAuth retry, final release request labeled verified lease release.
- Cases/evidence: TGA-10–12; offline lease/rotation/commit/concurrency probes and private real receipts; mutation cross-lease checkpoint/retry multiplication.

### TGA-AC-005 — Unresolved outcomes fence later acquisition and resume
- Source: R1–R3. Risk: critical.
- Precondition/action: uncertain lease acquisition/read/token persistence/checkpoint/interruption; invoke later call or resume; compare definitive pre-acquire denial.
- Observable: existing unresolved fence/working profile preserved; graph unknown/submitted receipt retained; later call stops before another lease; owner-mediated exact reconciliation only; no cached snapshot substitute.
- Forbidden: deleting fence/profile, guessing consent expired, copying older token, another route/replay to obtain pass or failed/unknown result converted to empty success.
- Cases/evidence: TGA-13–15; offline before/after-ack barriers and counting provider/store spies; mutation clear fence/reacquire/fallback.

### TGA-AC-006 — Private artifact custody binds admission to the exact query
- Source: R1–R4. Risk: critical.
- Precondition/action: consume exact gateway receipt/artifacts; substitute stale/different request/hash/path, symlink, insecure permissions or incomplete output.
- Observable: owner-private regular files/directories under allowed roots, exact request/config/query/status/hash/checkpoint bindings; no successful envelope after partial read; graph trusts verified custody, not caller path or a hash label alone.
- Forbidden: arbitrary file read, path escape, copied private account state into fixture/cloud/docs, mutable wrong-query payload admitted or credentials copied into new graph runtime.
- Cases/evidence: TGA-16–18; offline path/hash/permission/receipt controls and private real custody readback; mutation skip custody/binding.

### TGA-AC-007 — Snapshot admission verifies requested types, account and currency
- Source: R1, R3, R4. Risk: critical.
- Precondition/action: completed requested-scope empty/nonempty snapshot versus partial/failed/missing assets, inconsistent counts, ambiguous/mismatched STANDARD account and unknown/mixed currency.
- Observable: exactly one observed STANDARD account; same holdings/assets identity and compatible explicit currency; every fixed requested type completed/count-consistent; complete empty only within requested scope; unknown/mismatch does not yield complete analytics.
- Forbidden: first-account-wins, CASH counted as security type, missing requested type accepted, partial-to-empty success, inferred USD/FX or wholePortfolioVerified promoted from requested-scope completion.
- Cases/evidence: TGA-19–21; offline semantic inverses and exact private gateway/adapter readback; mutation ignore scope/count/account/currency.

### TGA-AC-008 — Times, amounts and missing performance remain honest
- Source: R1, R3, R4. Risk: high.
- Precondition/action: synthetic decimal/short/leverage data, missing amount/NAV, stale/unknown quote time and current-only unrealized PnL; later actual admitted source.
- Observable: exact decimal monetary totals and signs; net=sum(values), gross=sum(abs(values)), NAV/cash ratios only with valid compatible denominator; query/source/quote times distinct; unavailable quote/dailyPnl remain unavailable; source fields preserved.
- Forbidden: float drift, missing-to-zero, absolute net/clamped leverage, query time rejuvenating quote, dailyPnl invented from unrealized PnL or fake PIT/whole coverage.
- Cases/evidence: TGA-22–24; independent Decimal/metamorphic/time controls and private source-to-result verification; mutation round/clamp/relabel/rejuvenate.

### TGA-AC-009 — Existing portfolio analysis is a pure independently checked subgraph
- Source: R1, R2, R4. Risk: high.
- Precondition/action: admit gateway single-account envelope, explicitly map to existing portfolio/analytics contract, invoke pure analysis; inject error.
- Observable: existing `investment/portfolio` adapter and maintained analytics reused; identity/provenance preserved; independent arithmetic agrees; exception stays visible and original source hash unchanged.
- Forbidden: duplicated diverging analytics, acquisition/order/email inside analysis, source mutation, exception turned success or analysis result treated as evidence of acquisition by itself.
- Cases/evidence: TGA-25–26; direct-vs-subgraph/independent oracle controls and real private final readback; mutation bypass existing adapter/suppress error.

### TGA-AC-010 — Private account data never exports to cloud
- Source: R1–R4. Risk: critical.
- Precondition/action: force inherited LangSmith/tracing/provider settings and secret/account/path canaries offline; exercise success and nested error/pending/cancel paths.
- Observable: export disabled before callbacks; no credentials in any graph/state/checkpoint/resume/log/public projection; financial payload stays in permitted private local outputs; zero live LangSmith trace/dataset/export calls; diagnostics sanitized.
- Forbidden: output-only redaction, generic Agent Server callback leaks, cloud export under inherited flags, credentials in URLs/args/env/saved JSON or public screenshots/account fixtures.
- Cases/evidence: TGA-27–28; pre-callback exporting-sink controls and local network/export observer; mutation enable exporter/leak exception.

### TGA-AC-011 — Local Studio shows one understandable private workflow
- Source: R1–R4. Risk: high.
- Precondition/action: owned new127.0.0.1:2027 instance/new private persistence; connect actual Studio, submit closed action and inspect status/outcome.
- Observable: `trading_agent` root and internal first path visible; user sees accurate auth-needed/read/admission/analysis/failure state and exact private result or inspectable owned private result reference; host helper handles authorization internally; test URL matches owned listener.
- Forbidden: standalone Tiger product, raw user token/resume fields, opaque PASS report as product result, silent port fallback, source/health-only claimed UI success or shared old persistence.
- Cases/evidence: TGA-29–30; actual UI/public API/owned listener and private result readback; mutation wrong root/port or raw credential UI.

### TGA-AC-012 — One fresh real read proves this specific vertical path
- Source: R1–R5. Risk: high.
- Precondition/action: sealed candidate/preflight, exact authorized owner/project/fixed type scope; one native-assisted gateway snapshot with concurrency1; admit and analyze actual returned artifacts.
- Observable: actual native context/lease/restore/checkpoint, requested positions/assets, exact private custody, independent scope/math and final local root result bound to one request/config/source; all partial/unknown/failure statuses kept; actual account values private only.
- Forbidden: earlier snapshot/historical fixture/mock/handshake as fresh E2E, additional broker/OAuth retry, broad account scan, real chaos/fault injection or unverified token rotation/release/scheduled business claim.
- Cases/evidence: TGA-31–32; one fresh real readonly E2E and independent private end-state review; negative controls run offline only.

### TGA-AC-013 — Failure cleanup and rollback preserve owners, fences and old servers
- Source: R1–R3. Risk: critical.
- Precondition/action: offline denial/timeout/malformed output/cancel/claim interruption and owned new-server startup/stop/restart/rollback; gracefully stop live path only after safe completion.
- Observable: gateway budget/process-group cleanup respected, private pending/unknown evidence retained; new server/children/sockets bounded and owned; read-only diagnosis, prompts and recovery available; original credential owner/fences and active2024/2025/baseline snapshots unchanged.
- Forbidden: live destructive fault injection, deleting state/fence for rollback, killing old server, global activation, orphan process, indefinite polling or blocking user recovery.
- Cases/evidence: TGA-33–34; controlled offline lifecycle/rollback, before/after hashes/listeners and independent cleanup review; mutation skip cleanup/delete fence.

### TGA-AC-014 — Capability inventory and completion claims match evidence
- Source: R1, R2, R4, R5. Risk: high.
- Precondition/action: present user scenarios, migration inventory and independent verification report after first path.
- Observable: implemented/candidate/unverified/blocked statuses have evidence and scope; calculation/research/web/runtime inventory includes owner/input/output/errors/effects and smallest next subgraph/test; existing baseline339/MCP preserved; counts/attempts/mutations/skips explicit; first path acceptance distinct from whole migration/scheduled business/email acceptance.
- Forbidden: creating more visible trial agents, silently omitting remaining capability inventory, claiming all migration done, model consensus as evidence, skipped/zero executed as PASS or sending/trading/scheduler side effects.
- Cases/evidence: TGA-35–36; independent inventory/criterion-test-evidence report and frozen hash review; mutation drop missing capability/failure and overclaim migration.

## Remaining capability inventory to complete

| Capability | Existing owner/contract to inventory | Current migration claim allowed by this packet | Next evidence needed |
| --- | --- | --- | --- |
| Tiger snapshot and portfolio analysis | shared/tiger; investment/portfolio; maintained holdings analytics | First path candidate until TGA criteria run | Fresh private readonly E2E and local Studio acceptance |
| Calculation/valuation | Existing shared calculator; frozen independent arithmetic and model/tool receipt contracts | Existing capability; canonical-root integration not certified here | Inventory exact interface/effects and verified internal subgraph |
| Investment research | investment.research frozen evidence/finalization contract | Inventory required; not migrated by holdings success | Explicit source/evidence/finalization interface and narrow research path |
| Web/source acquisition | Maintained shared source/native web adapters and web-routing policy | Inventory required; no provider path assumed active | Source scope/provenance/error and native transport evidence |
| Runtime/model/host handoff | Existing session and runtime owner/contracts | Internal native helper only for this path; unattended/scheduled capability unverified | Inventory lifecycle/retry/unknown semantics; separate intended-runtime acceptance |

The integration owner fills exact source mappings and evidence statuses; this table is a deliverable checklist, not a claim that source discovery or integration is finished.

## Independence and amendments

`cases.json` holds 36 compact synthetic controls, 14 deliberate-break specifications and old frozen reference hashes. Shared-workspace cases are development cases, not blind holdouts. Implementer may map semantic fixtures to schemas but cannot weaken expectations. No live account/token values belong in this packet. Missing Studio or live prerequisites block that corresponding claim while useful offline work continues.

| Revision | Change | Behavioral reason | Owner |
| --- | --- | --- | --- |
| Before first freeze, v1 | Replaced planned standalone Tiger visible graph/path with tuning/trading_agent and one canonical trading_agent root; added readable scenarios and remaining capability inventory | Explicit user correction before implementation/freeze | Independent designer, integration-owner instruction |
