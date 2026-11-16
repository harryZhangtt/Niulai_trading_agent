# Acceptance criteria — atomic calculator, synthetic holdings and tracing

Status: FROZEN  
Revision/source: atomic-contract-v1.1, frozen 2026-11-15 by the independent acceptance designer before inspecting proposed implementation; factual scope amendment recorded below.  
Selected verification level: Balanced, with deliberate-break controls.  
Why this level is enough: atomic arithmetic/data semantics, changed public Agent Server and session boundaries, synthetic cloud contracts, concurrency/recovery and independent readback are included. Production, real brokerage data, orders, email, production scheduler, unattended inference, load/stress and provider-wide reliability are excluded.

## Assumptions and scope

- Requirement sources: **R1** = user task delegated by the integration owner on 2026-11-15; **R2** = root `AGENTS.md`, `mentor/AGENTS.md` and development-discipline; **R3** = existing `tuning/langchain_pilot/ACCEPTANCE.md` LC-01–08 and SE-01–08; **R4** = `docs/architecture/holdings-boundary-review.md`; **R5** = `tuning/AGENTS.md` and evaluation-design; **R6** = `docs/deployment/langchain-pilot.md`, including its observed pre-callback privacy gap and unknown-write reconciliation rules.
- Exploratory purpose: make two bounded atomic capabilities inspectable and testable. This contract does not establish investment quality or alpha. Preserve existing calculator cloud results and the original LC/SE oracle.
- Calculator uses the unchanged existing Decimal valuation calculator and LangChain tool execution through cooperative `SessionChatModel`. Host responses supply assistant messages only. No scripted fallback or copied API/subscription credentials. At most three model requests, as already documented; message/tool/output/time bounds must be recorded before dispatch.
- Holdings analytics reuses `niulai/holdings/analytics.build` behind an `investment/portfolio` contract. Pure analytics consumes only newly authored synthetic receipts. Never read private holdings fixtures or account archives to create cases.
- Maintained gateway position types are STK/OPT/FUT/FUND. Cash belongs to `assets.summary.amounts.cash`, not a position security type. Completion establishes the caller's requested scope; whole-portfolio/account verification is a separate authority and remains false/unknown unless separately established. A deterministic calculator-only self-test graph may supplement the required cooperative graph but must have no model-inference claim or fabricated model span.
- Only fixed public fixture selectors may enter the network execution route. Direct atomic adapter tests may construct synthetic malformed values; these are not permission for an arbitrary-payload cloud ingress. Record the exact allowed fixture roster and content hashes before cloud work.
- Impact classification: this document/case file is inert/local. Candidate server is isolated and owner-controlled; cloud writes are restricted to isolated synthetic test resources and owned receipts. Main `localhost:2024` PID 64553 is preserved during staging. The owner records the chosen port/config/source fingerprints and all process ownership before launch.
- UT = atomic contract test; IT = changed-boundary local integration; CLOUD = isolated synthetic cloud readback; MUT = deliberate break. All named cases are mandatory unless individually reported BLOCKED/NOT RUN with residual risk. MUT changes run only in disposable copies. A critical observed violation is FAIL and cannot be averaged away.
- Exact numeric oracle: `EV = sum(FCFF[t]/(1+r)^t) + terminal_EV/(1+r)^N`, `equity = EV - net_debt`, `per_share = equity/shares`. Use independent rational/Decimal mathematics, never the function under test. Holdings monetary sums preserve exact decimal values and declared currency; rate/percentage rounding must be declared, not inferred from binary float tolerance.
- Frozen runtime manifest must identify graph IDs, schemas, source/config/prompt/grader/case hashes, fixture roster, server bounds, thread/run/session/request IDs, owned paths, and cloud resource IDs. Cloud object creation times and exact feedback keys/scores are pinned before interpreting results.
- Shared-workspace cases are independent development cases, not inaccessible or blind holdouts. The implementer must not alter this file or case expectations. Amendments require an explicit behavioral reason and a new revision. Missing current hook output stays unverified; direct policy reads are the disclosed fallback.
- Residual risk: cooperative local execution and synthetic cloud evidence do not prove autonomous host dispatch, production durability, real account freshness or scheduled runtime acceptance. Major runtime activation remains subject to `docs/deployment/runtime-acceptance.md`; no business effect is executed for this contract.

## Criteria

### AC-001 — Public execution accepts only frozen synthetic selectors
- Requirement source: R1, R2, R6. Risk: critical.
- Preconditions: clean request observer and disabled generic/private tracing; frozen fixture roster.
- Action: submit valid selector, unknown selector, unknown field, nested raw payload, malformed type and oversized request at the actual network entry.
- Expected observable result: valid selector resolves the exact frozen fixture; invalid requests fail explicitly before model/tool dispatch and before any exporting callback receives raw input.
- Forbidden result: arbitrary data, file/URL/account identifiers, extra metadata or private payload reaching cloud callbacks; silently ignored fields; selector drift.
- Cases: IN-01–08. Required evidence: UT-001, IT-001, CLOUD privacy sink inspection, MUT-001 remove/relocate validation after callbacks.

### AC-002 — The authorized effect boundary is demonstrably contained
- Requirement source: R1–R4. Risk: critical.
- Preconditions: synthetic-only environment with observed adapters/call sinks.
- Action: run both nominal and failed graphs with inherited provider/tracing variables and fake sensitive canaries.
- Expected observable result: only owned local state and authorized isolated synthetic cloud resources change; holdings provider, broker, email, scheduler, global settings and main server have zero calls/mutations.
- Forbidden result: private fixture/account reads, credential copying, global dependency/cache/state writes, production graph replacement or hidden provider fallback.
- Cases: ISO-01–04. Required evidence: UT-002, IT-002 before/after ownership evidence, MUT-002 enable a forbidden adapter call.

### AC-003 — Calculator independently matches exact arithmetic
- Requirement source: R1, R3. Risk: high.
- Preconditions: valid frozen synthetic valuation case and independent formula oracle.
- Action: invoke the calculation capability for one/multiple periods, positive/zero/negative cash flows, terminal value, debt and shares.
- Expected observable result: EV, equity and per-share match independent exact values; original one-period case remains EV 100, equity 100, per-share 10.
- Forbidden result: float-dependent drift, wrong discount period, debt sign reversal or post-hoc tolerance.
- Cases: CAL-01–10. Required evidence: UT-003; IT-003 nominal through real graph; MUT-003 exponent, terminal-period and debt-sign breaks.

### AC-004 — Arithmetic boundaries and transformations discriminate wrong calculators
- Requirement source: R1, R3, R5. Risk: high.
- Preconditions: finite valid cases including rate zero and rate just greater than -1 within the declared domain.
- Action: scale cash flows/terminal/debt together; scale shares; split same-period components; change one period's cash flow.
- Expected observable result: linear monetary scaling, inverse share scaling and independently computed discounted delta hold; exact decimals/negative equity remain explicit.
- Forbidden result: clamping losses to zero, ignoring terminal value, rounding intermediates or accepting unsupported numeric size outside bounds.
- Cases: CAL-11–17. Required evidence: UT-004 metamorphic controls; MUT-004 clamp/early-round/ignore-terminal breaks.

### AC-005 — Invalid calculation data fails before model or tools
- Requirement source: R1, R3 LC-03. Risk: high.
- Preconditions: observers reset; synthetic invalid fixtures.
- Action: submit zero/negative/missing/bool/nonfinite shares, rate <= -1, nonfinite/bool/malformed numeric values, empty/malformed cash-flow sequence and payload over declared limits.
- Expected observable result: explicit invalid classification; zero model requests and tool calls; diagnostic remains readable without credentials.
- Forbidden result: bool treated as a number, coercion of ambiguous malformed values, division by zero, NaN success or provider dispatch.
- Cases: CAL-18–30. Required evidence: UT-005, IT-005 selector-driven invalid fixture; MUT-005 bypass validation.

### AC-006 — Calculator success requires a real model-selected matching tool receipt
- Requirement source: R1, R3 LC-02/SE-02. Risk: critical.
- Preconditions: cooperative pending request and available allowlisted calculator tool.
- Action: host returns only an assistant-selected tool call; LangChain executes it; host supplies final answer.
- Expected observable result: actual tool receipt binds the same request/run/case hash, exact arguments and result; final exact answer independently matches that receipt and formula.
- Forbidden result: host-authored tool receipt, different case/arguments, correct asserted number without tool evidence, forged receipt or substituted tool.
- Cases: MOD-01–06. Required evidence: UT-006 negative receipt gate, IT-006 cooperative public API completion, CLOUD exact model/tool/final readback; MUT-006 remove receipt binding.

### AC-007 — Final-answer failures remain failures even with a correct tool
- Requirement source: R1, R3. Risk: high.
- Preconditions: a valid actual tool receipt.
- Action: return wrong/missing/malformed/approximate final answer or extra unsupported monetary claim.
- Expected observable result: independent gate rejects mismatch/schema violation; persisted output explains the bounded failure and retains actual tool evidence.
- Forbidden result: substring matching, accepting rounded wrong value, accepting a final answer from another run, or overwriting failure with PASS.
- Cases: MOD-07–11. Required evidence: UT-007, IT-007 one inverse control; MUT-007 weaken exact answer/schema gate.

### AC-008 — Session inference is cooperative and bounded
- Requirement source: R1, R3 SE-01/07/08, R6. Risk: high.
- Preconditions: default session engine with no Platform credentials and frozen size/time bounds.
- Action: create run, inspect interrupt, leave it unserviced, and supply repeated tool-only or nonterminal replies.
- Expected observable result: persisted bounded pending requests; at most three model requests; deadline/limit produces explicit terminal or resumable classification; no hidden model HTTP requests or busy waiting.
- Forbidden result: scripted fallback, unattended-inference claim, automatic host wake-up claim, unlimited model/tool loop or made-up backend attestation.
- Cases: SES-01–05. Required evidence: UT-008, IT-008 pending and exhaustion; MUT-008 remove call cap or enable fallback.

### AC-009 — Stale, duplicate, malformed and concurrent replies cannot corrupt session state
- Requirement source: R1, R3 SE-03/06, R6. Risk: critical.
- Preconditions: known pending request, current binding/revision and attempt receipts.
- Action: submit duplicate reply, stale revision/request, wrong thread/run, non-assistant message, malformed tool arguments, oversized reply and two simultaneous replies.
- Expected observable result: invalid replies reject visibly; at most one legal admission advances state; original financial inputs and completed tools stay unchanged; no extra calculation.
- Forbidden result: cross-thread reuse, duplicate advance, response replay after unknown dispatch or global recovery block.
- Cases: SES-06–13. Required evidence: UT-009; IT-009 controlled-barrier concurrency and actual malformed public reply; MUT-009 remove identity/dedup gate.

### AC-010 — Rebinding and recovery retain authoritative graph state
- Requirement source: R1, R3 SE-04/05/08, R6. Risk: high.
- Preconditions: same thread with pending model request or completed tool; owned server lifecycle.
- Action: rebind host, gracefully stop/restart, discover original thread and resume with current ownership.
- Expected observable result: original messages, completed tool receipt and case hashes remain inspectable; new ownership governs subsequent admission; already admitted response obeys the documented graph-side snapshot; calculator is not executed again.
- Forbidden result: reconstructing state from chat, replacement thread hiding loss, deleting uncertain attempt receipts or calling dev persistence production crash durability.
- Cases: SES-14–18. Required evidence: UT-010, IT-010 restart/rebind before and after tool; MUT-010 reset state or replay tool.

### AC-011 — Trace identities and parent relations represent the actual execution
- Requirement source: R1, R5, R6. Risk: high.
- Preconditions: isolated trace project and frozen identity manifest; one actual cooperative calculator and holdings run.
- Action: retrieve exact root/child runs after completion.
- Expected observable result: roots bind graph/thread/run/case/config/source identities; actual model and tool children belong to the correct root/parent; timestamps and outputs agree with local evidence; holdings is analytics and has no invented model span.
- Forbidden result: fabricated/reused model span, orphan/wrong-root child, unknown declared model treated as attested or root-only trace called model/tool tracing.
- Cases: TRC-01–05. Required evidence: UT-011 trace-contract controls, IT-011 callback capture, CLOUD exact-ID readback; MUT-011 alter parent/identity.

### AC-012 — Pending, errors and cancellation have honest trace outcomes
- Requirement source: R1, R3 LC-05, R6. Risk: high.
- Preconditions: pending, controlled tool-error and session-timeout synthetic cases.
- Action: inspect their exact local/cloud spans and terminal status.
- Expected observable result: interrupt is distinguished from completed inference; errors/cancellation remain typed and bounded; no success output after failed tool; open spans reach honest bounded status or remain explicitly pending/unverified.
- Forbidden result: failed child laundered by PASS root, swallowed exception, false completed model call or deliberate failures counted as real-agent reliability.
- Cases: TRC-06–09. Required evidence: UT-012, IT-012, CLOUD error readback; MUT-012 suppress/replace error.

### AC-013 — Privacy filtering precedes all exporting callbacks
- Requirement source: R1, R2, R4, R6 observed privacy gap. Risk: critical.
- Preconditions: fake secret/account/private-path canaries and callback/export/exception capture at the actual boundary.
- Action: submit nested invalid input and trigger model/tool/validation/trace-export failures.
- Expected observable result: no canary or arbitrary private payload appears in exported inputs/outputs/metadata/tags/errors; only exact allowlisted synthetic content and sanitized diagnostics are exportable.
- Forbidden result: checking only returned output, post-callback redaction, leaking through exception repr, environment capture, headers or attachment/path metadata.
- Cases: PRIV-01–06. Required evidence: UT-013 pre-callback sink proof, IT-013 real ingress, CLOUD exact payload scan; MUT-013 move check after callback or leak nested exception.

### AC-014 — Trace export failure cannot trigger capability rerun
- Requirement source: R1, R2, R6. Risk: high.
- Preconditions: owned trace attempt and completed local result; synthetic exporter timeout/reset/429.
- Action: lose acknowledgement or observe delayed cloud visibility, then reconcile exact run IDs.
- Expected observable result: result and unknown/pending trace state remain distinct; read-only bounded reconciliation honors service limits; capability executes once and no new trace root is invented to obtain a pass.
- Forbidden result: blind model/tool rerun, unbounded SDK/outer retry multiplication, deletion of unknown attempt or reporting acknowledgement as exact readback.
- Cases: TRC-10–14. Required evidence: UT-014, IT-014 injected exporter, CLOUD reconciliation evidence; MUT-014 automatic rerun.

### AC-015 — Holdings complete requested-scope empty is distinguishable from failed or partial retrieval
- Requirement source: R1, R4. Risk: critical.
- Preconditions: synthetic confirmed complete-requested-scope empty, failed-empty, partial-empty and unresolved receipts, with separate whole-portfolio verification state.
- Action: invoke pure holdings adapter and registered subgraph.
- Expected observable result: only confirmed complete requested-scope empty is successful empty within that scope; failure/partial/unknown remain explicit with gaps; wholePortfolioVerified stays false/unknown without separate proof.
- Forbidden result: collapsing exception/partial/unknown to empty success or promoting requested-scope completion to whole-account coverage.
- Cases: HOLD-01–05. Required evidence: UT-015, IT-015 nominal/inverse public selectors; MUT-015 replace errors with empty.

### AC-016 — Holdings account and type coverage is explicit and count-consistent
- Requirement source: R1, R4. Risk: high.
- Preconditions: synthetic requested/observed type scope and row/type counts.
- Action: use explicitly requested STK/OPT/FUT/FUND scope, STK-only requested scope, a required type omitted from receipt and inconsistent count metadata; observe cash separately in assets.
- Expected observable result: declared requested/observed/missing scope and exact counts remain visible; requested-scope completion requires all requested types and counts; STK-only completion remains limited to STK; cash stays a monetary asset field; wholePortfolioVerified is independent.
- Forbidden result: treating nonzero rows or STK-only completion as whole-portfolio coverage, manufacturing missing option rows, counting cash as a security type or accepting contradictory count claims.
- Cases: HOLD-06–10. Required evidence: UT-016, IT-016 partial selector; MUT-016 ignore missing type/count mismatch.

### AC-017 — Account identity mismatch, ambiguity and unknown never become accepted scope
- Requirement source: R1, R4. Risk: critical.
- Preconditions: synthetic accountResults/holdings/assets with declared identities.
- Action: mismatch holdings/assets account, supply multiple ambiguous accounts, omit identity, or explicitly match one synthetic account.
- Expected observable result: mismatch/ambiguity reject; unknown remains unknown/unresolved and cannot yield full-scope success; exact declared match succeeds without claims of real authentication.
- Forbidden result: first-account-wins, merging two accounts, account-ID spoofing treated as permission or omitted identity inferred from row content.
- Cases: HOLD-11–15. Required evidence: UT-017; MUT-017 skip account check.

### AC-018 — Currency scope and missing currency constrain totals
- Requirement source: R1, R4. Risk: critical.
- Preconditions: USD match, USD/HKD mismatch, absent currency and mixed-currency synthetic values.
- Action: compute summary without an authorized FX contract.
- Expected observable result: matched monetary totals retain USD; mismatched values reject or remain separately partial/unaggregated; missing currency remains unknown and blocks a complete same-currency total.
- Forbidden result: adding incompatible currencies, assuming USD, inventing FX or producing a complete NAV from unresolved scope.
- Cases: HOLD-16–20. Required evidence: UT-018; MUT-018 coerce all currency to USD.

### AC-019 — Duplicate contract identity cannot double count or erase distinct instruments
- Requirement source: R1, R4. Risk: high.
- Preconditions: duplicated canonical contract, conflicting duplicate values and same ticker with distinct option expiry/strike/right.
- Action: calculate totals and exposures.
- Expected observable result: duplicate canonical identity is rejected or explicitly quarantined before full totals; distinct valid contracts remain distinct; ticker alone is insufficient identity.
- Forbidden result: silent double count, silent last-row-wins, or collapsing stock and option/different contracts.
- Cases: HOLD-21–25. Required evidence: UT-019; MUT-019 remove duplicate guard or dedup on ticker.

### AC-020 — Missing or invalid financial amounts stay missing or invalid
- Requirement source: R1, R4. Risk: high.
- Preconditions: amount/value/quantity/price/NAV/cash fields with zero, absent, null, malformed, bool and nonfinite values.
- Action: invoke adapter on these synthetic receipts.
- Expected observable result: explicit zero is valid where permitted; missing/invalid required amounts reject or yield labeled unavailable/partial result with no complete total; typed finite Decimal semantics are preserved.
- Forbidden result: defaulting missing to zero, bool as 1, trusting NaN/Infinity or computing ratios with unavailable/zero denominator.
- Cases: HOLD-26–33. Required evidence: UT-020; MUT-020 default missing values or suppress invalid denominator.

### AC-021 — Quote time, query time and unknown freshness remain distinct
- Requirement source: R1, R2, R4. Risk: high.
- Preconditions: fresh query with stale/unknown quote, known quote at cutoff, and impossible future/inconsistent timestamps.
- Action: produce synthetic analytics as-of/freshness summary.
- Expected observable result: query completion never rejuvenates quote time; absent quote time remains unknown; cutoff comparisons use actual quote timestamps and declared zone/as-of; impossible times fail or remain visibly unresolved.
- Forbidden result: fresh query == fresh quote, invented price timestamp, backdating or calling unknown historical/PIT coverage current.
- Cases: HOLD-34–39. Required evidence: UT-021; MUT-021 substitute query time for quote time.

### AC-022 — Exact monetary totals preserve shorts and leverage
- Requirement source: R1, R4. Risk: high.
- Preconditions: exact decimal long/short positions and explicit NAV/cash in a single currency.
- Action: compute net and gross exposure, concentration and cash/NAV ratios using independent arithmetic.
- Expected observable result: signs are preserved; net and gross differ as declared; leveraged gross may exceed NAV and negative cash stays negative; monetary totals have no float drift.
- Forbidden result: abs applied to net exposure, clamping leverage/negative cash, dividing by market value instead of declared NAV or early rounding money.
- Cases: HOLD-40–46. Required evidence: UT-022, IT-022 mixed long/short selector; MUT-022 abs/clamp/wrong denominator.

### AC-023 — Current holdings do not invent daily performance
- Requirement source: R1, R4. Risk: high.
- Preconditions: synthetic market value, NAV, cash and optional unrealized PnL; no accepted historical/execution daily-performance contract.
- Action: build summary.
- Expected observable result: dailyPnl/daily return is absent or explicitly unavailable; allowed unrealized/current fields retain correct labels; no recommendation/order is implied.
- Forbidden result: unrealized PnL relabeled daily PnL, inferring daily performance from current snapshot or emitting invented daily change.
- Cases: HOLD-47–50. Required evidence: UT-023; MUT-023 add dailyPnl from unrealizedPnl.

### AC-024 — Holdings receipt/checkpoint uncertainty prevents replay
- Requirement source: R1, R2, R4. Risk: critical.
- Preconditions: synthetic committed, unknown, stale and mismatched receipt/checkpoint states; provider spy.
- Action: invoke/resume holdings subgraph, including failure and restart.
- Expected observable result: known committed synthetic receipt may be consumed; unknown/unresolved/mismatched checkpoint rejects before analytics success; provider call count stays zero; no state recovery silently reacquires.
- Forbidden result: read-only presumed replay-safe, resolving unknown by provider call, regenerating receipt after failure or private checkpoint lookup.
- Cases: HOLD-51–56. Required evidence: UT-024, IT-024 resume inverse control; MUT-024 replay/accept-unknown breaks.

### AC-025 — Holdings adapter remains a separately testable pure boundary
- Requirement source: R1, R2, R4. Risk: high.
- Preconditions: frozen synthetic canonical input and existing analytics capability.
- Action: invoke `investment/portfolio` adapter directly and via registered holdings graph; inject analytics exception.
- Expected observable result: same contract result and provenance; existing analytics is reused; error stays visible and no source input/private state mutation occurs.
- Forbidden result: copied analytics diverging silently, provider/acquisition inside analytics, mutation of frozen receipt or exception converted to success.
- Cases: HOLD-57–60. Required evidence: UT-025, IT-025 source integration and output equality; MUT-025 input mutation/error suppression.

### AC-026 — Actual public graph discovery and schema expose the tested capabilities
- Requirement source: R1, R3 LC-04. Risk: high.
- Preconditions: explicitly registered graph IDs and isolated owned server manifest.
- Action: query actual public assistant discovery/schema and submit valid/invalid public requests for both graphs.
- Expected observable result: both declared IDs are discoverable; schemas reflect fixed selectors; actual input reaches intended graph; independently read run state/result after completion.
- Forbidden result: source import/health check-only E2E, missing holdings graph, arbitrary raw ingress, wrong-server results or graph ID inferred from display name.
- Cases: API-01–05. Required evidence: IT-026 discovery/schema/run/state artifacts; MUT-026 unregister/wrong mapping.

### AC-027 — Self-test URL points at the owned tested instance
- Requirement source: R1, R2, R3. Risk: high.
- Preconditions: recorded PID/process identity, chosen port and config/source fingerprints; main port 2024 preserved.
- Action: launch on selected free port, occupy it in a negative control, and open/query supplied test URL.
- Expected observable result: URL and API base match owned listener and graph IDs; occupied port fails clearly with no silent fallback; main PID/listener/config remains unchanged.
- Forbidden result: killing/replacing main server, silently choosing another port, returning an untested URL or claiming Studio browser success from a printed link.
- Cases: API-06–09. Required evidence: IT-027 listener/provenance and actual URL/API readback; MUT-027 silent port fallback.

### AC-028 — Candidate lifecycle failures stay bounded and reversible
- Requirement source: R1, R2, R3 LC-05/06. Risk: high.
- Preconditions: owner-controlled local candidate with backup/rollback and interruption points.
- Action: fail startup/config, cancel in flight, stop with pending/tool-completed run, restart, rollback and stop.
- Expected observable result: bounded exits/drain, useful diagnostics, owned children/sockets cleaned up, retained state recoverable under its declared dev contract, rollback restores prior pairing; user diagnosis/recovery remains available.
- Forbidden result: orphan process, deleting original state to make rollback pass, blocking prompts/recovery or declaring production crash durability.
- Cases: LIFE-01–07. Required evidence: IT-028 before/during/after lifecycle, MUT-028 skip cleanup/state preservation.

### AC-029 — Cloud resource identity is isolated, exact and immutable for the trial
- Requirement source: R1, R2, R5, R6. Risk: critical.
- Preconditions: authorized synthetic test workspace/project and owned manifest; production resources excluded.
- Action: create/reuse intended synthetic project/dataset/experiment/prompt; independently read exact IDs and resource metadata.
- Expected observable result: exact resource identities, versions/time/hash and test provenance match manifest; no similarly named resource substitution; all existing calculator results remain intact.
- Forbidden result: production writes/tests, name-only identity, overwrite/delete of historical calculator experiments or changing ownership to pass.
- Cases: CLD-01–05. Required evidence: UT-029 identity negative controls, CLOUD exact readback and before/after preservation; MUT-029 name-only/wrong-ID acceptance.

### AC-030 — Prompt and dataset are pinned to a frozen synthetic roster
- Requirement source: R1, R5, R6. Risk: high.
- Preconditions: finalized fixture roster, independent expected outputs and source/grader hashes before evaluation.
- Action: load prompt by exact commit; read dataset at pinned version/as-of; introduce missing/extra/drifted/duplicate case.
- Expected observable result: exact prompt content/commit and case IDs/content/expected hash equal manifest; roster is complete and duplicates rejected; prompt/case drift opens a new trial version.
- Forbidden result: latest prompt alias, removing failed case, unsealed expectations, public private-data upload or treating shared development answers as blind holdouts.
- Cases: CLD-06–11. Required evidence: UT-030 sealed-roster controls, CLOUD prompt/dataset readback; MUT-030 drift/drop-case acceptance.

### AC-031 — Code grading and feedback exact readback determine the scoped score
- Requirement source: R1, R5, R6. Risk: high.
- Preconditions: frozen deterministic grader closure, complete case roster and independently calculated per-case expectations.
- Action: evaluate nominal and controlled-wrong outputs; fetch exact run/example links, outputs and persisted feedback.
- Expected observable result: every case has the correct result, reference example and exact predeclared feedback key/score; critical fail remains fail; arithmetic, scope, privacy and trace status are separate checks.
- Forbidden result: model self-grade, aggregate masking critical fail, favorable score without exact stored feedback or grading another run/example.
- Cases: CLD-12–17. Required evidence: UT-031 inverse grader controls, CLOUD full-roster readback; MUT-031 always-pass/wrong-example/drop-fail.

### AC-032 — Unknown cloud writes are fenced and only reconciled by reads
- Requirement source: R1, R2, R6. Risk: critical.
- Preconditions: owned planned operation/attempt identity and injected acknowledgement loss after possible write.
- Action: bootstrap/evaluate/trace encounters timeout, interruption or delayed visibility; retry command is issued.
- Expected observable result: attempt preserves unknown state; command refuses blind repeat; reconciliation rereads exact IDs/content and can confirm, fail or remain unknown without new execution/write; bounded reads respect 429.
- Forbidden result: recreating missing targets, duplicate example/run/feedback, clearing fence, SDK auto-retry of unknown effect or replay solely for clean receipt.
- Cases: CLD-18–23. Required evidence: UT-032, IT-032 failure injection, CLOUD exact reconciliation; MUT-032 unconditional rerun/clear-fence.

### AC-033 — Independent evidence reports all attempts and practical limits
- Requirement source: R1–R6. Risk: high.
- Preconditions: frozen criteria/cases and candidate source/config/runtime manifest.
- Action: independent verifier maps all executed tests and deliberate breaks to criteria and reads actual end state/cloud artifacts.
- Expected observable result: PASS/FAIL/BLOCKED/NOT RUN, executed/skipped counts, mutation kills/survivors, every attempt and residual risk are explicit; zero executed is failure; unavailable identity/usage/cost remains unknown; setup runbook/inventory gate is checked if setup changed.
- Forbidden result: implementer narrative as evidence, synthetic reliability/alpha/production acceptance claim, undocumented skipped cases, survivor called success or unverified scheduled/email gate called passed.
- Cases: EVID-01–06. Required evidence: independent verification report and criterion/test matrix; MUT-033 zero/drop/falsified evidence controls.

## Independent development cases

`tests/atomic_contract_cases.json` contains concrete requirement-derived development inputs/oracles and adversarial variants. It is written by the designer without inspecting `graph.py`, `holdings.py`, `snapshot.py`, session implementation or proposed tests. API fixture identifiers may be mapped to equivalent frozen public selectors in the manifest; expected semantics must not change. Direct malformed adapter inputs must not be exposed as unrestricted network ingress.

One atomic test has one behavioral reason to fail. Controlled barriers, not sleeps, should force concurrent reply/timeout orderings. Deliberate breaks are independent specifications, not implementation prescriptions; mutate the actual enforcing layer, record classification for any survivor, and do not weaken this contract to obtain green.

## Amendments after freeze

| Time | Criterion | Change | Behavioral reason | Requested/approved by | Affected tests |
| --- | --- | --- | --- | --- | --- |
| 2026-11-15 | Scope assumptions, AC-015, AC-016 | v1.1: use gateway STK/OPT/FUT/FUND taxonomy, cash asset field; separate requested-scope completion from wholePortfolioVerified | Integration owner supplied maintained gateway factual contract; preserves unknown/partial and no fabricated coverage requirements | Independent designer, requested by integration owner | HOLD-01–10, HOLD-60; cloud scope grading |
| 2026-11-15 | Scope assumptions | Deterministic calculator-only public self-test may supplement cooperative graph | Integration owner added a URL-usable tool-only test surface; required actual cooperative inference and trace criteria unchanged | Independent designer, requested by integration owner | API-01–05, TRC-01–05 |
