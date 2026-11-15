# Skills and matched evaluation review

Review date: 2026-11-15. This is an exploratory, source-only review. The observed opportunity is a smaller configuration seam for matched comparisons; no measured failure currently establishes that LangChain or LangGraph improves research quality. The smallest useful change is one pilot-owned comparison adapter around the existing synthetic graph and sealed evaluation contract.

No actual `MENTOR_INIT_OK` or `UI_INIT_OK` SessionStart output was available in this review context. The policies and routers were read directly as a disclosed fallback. Development-discipline, evaluation-design, experiment-design and their required local investment context were applied selectively. No protected cases, private state, provider calls, graders, holdouts, hooks, MCP entries, jobs or email were changed or exercised.

1. **Keep skills as selected procedures, rather than turning every skill into an agent or tool.** Mentor guidance explicitly owns supervision while executable experiments and graders belong in tuning; it is instruction-based rather than a watchdog (`mentor/AGENTS.md:3-8`, `:52`, `:90-112`). Its router selects procedures by the unresolved decision and reuses already loaded bodies (`mentor/ROUTING.md:3-11`, `:15-38`, `:40-50`). UI uses the same principle; its resolver returns paths without loading bodies and does not claim a natural-language classifier or successful tool operation (`ui/ROUTING.md:12-20`). Preserve that mechanism. A selected skill body is prompt/context material, not evidence that its prescribed checks ran. A skill can bundle scripts, but these remain executable resources that require explicit invocation through their owning component; loading the prose does not execute them (`mentor/ROUTING.md:34-38`). The UI loader likewise attests resource readiness rather than a running quality monitor (`ui/AGENTS.md:23-38`). No UI specialist bodies are needed for this backend-only review (`ui/ROUTING.md:40`).

   The existing routing screen supports only provisional procedural routing: its reported instruction reduction is a tokenizer proxy, and its skill-effectiveness conclusion is inconclusive (`tuning/evals/mentor-routing/report.md:3-15`, `:60-72`). A LangChain wrapper must not upgrade that evidence to model, dollar-cost or whole-session effectiveness claims.

2. **The current graph already demonstrates the appropriate division of responsibility.** Its tool wraps the existing Decimal calculator and reads validated inputs from state, so the model cannot replace financial inputs (`tuning/langchain_pilot/graph.py:64-78`). Input validation, a bounded agent, and deterministic result verification are separate nodes (`:98-110`, `:113-151`, `:154-178`). The model-call middleware enforces a run limit; it does not enforce the investment evidence contract (`:166`). Keep owner-controlled evidence hashes, invocation identity and usage observations outside model-authored messages.

   The following mapping adds no new service:

   | Existing concern | Minimal LangChain/LangGraph placement | Authority remains with |
   | --- | --- | --- |
   | Stable scope, accepted deliverables and safety invariants | Small system instruction | Root/component policies |
   | Selected mentor or UI skill and required local references | Resolved, hash-pinned prompt/context fragment | Existing router and canonical files |
   | Arm ID, selected procedure IDs, cutoff and evidence references | Typed request context; durable artifact references in state only when needed | Coordinator; never model-created expected answers |
   | Pure calculator or typed source acquisition | Thin executable tool adapter | Existing calculator/shared source implementation |
   | Model-call cap, timeout/retry observation | Existing middleware/provider boundary | Harness; preserve unknown outcomes |
   | Validate input, invoke agent, verify actual result | A few explicit graph nodes | Existing public validators |
   | Research completion and promotion | Host callback after artifact capture | `investment.research` and tuning gates |

   For a later research path, retain the coordinator-held requirements pin before retrieval and retain `pipeline.finalize`/`complete`; those functions already revalidate source coverage and compose the preserved Niulai validators (`investment/AGENTS.md:3-12`, `:22-33`; `investment/research/README.md:17-37`, `:94-127`; `investment/research/pipeline.py:29-53`). Do not expose a generic shell, legacy finalizer bypass, arbitrary contract mutation, or model-selected production effect just to populate a tool catalog.

3. **Reuse the generic sealed contract as the experiment authority; treat any future LangSmith record as a derived view.** `seal` already binds the complete input/answer roster, criticality, explicit grader closure and arm fingerprints (`tuning/evals/evidence_runtime/contracts.py:130-162`). `worker_packet` excludes answers from that packet, while explicitly disclaiming filesystem blindness (`:198-203`). `begin` checks equal budgets and fingerprints before execution (`:211-223`); `finish` checks the full roster, immutable evidence references, pinned host callback, required metrics and budget usage, and preserves an intent fence against unknown callback replay (`:231-287`).

   A pilot adapter needs only to map the selected arm to graph context, capture immutable public run/state evidence, and invoke those entrypoints. The existing earnings/cache `grade.callback` is workload-specific, so reuse the contract API rather than pretending that grader accepts calculator outputs (`tuning/evals/evidence_runtime/grade.py:12-27`, `:92-123`). A small pilot callback may reopen captured messages/state and reuse the graph's independent rational-arithmetic verification; it must not accept the graph's `result.status` as authoritative. Pin its complete source closure when implemented.

   If LangSmith is adopted later, export only an explicitly permitted sanitized view carrying the contract SHA, arm fingerprint, attempt/case IDs, outcome dimensions and trace link. Keep its dashboards or feedback subordinate to the locally reopened evidence and host verdict. No hosted dataset, upload, tracing activation or second experiment registry is required now. The current launcher deliberately disables LangSmith tracing (`docs/deployment/langchain-pilot.md:65-75`).

4. **The specialized acquisition matched checker is deliberately narrower than arbitrary prompt/graph A/B.** Its derived execution record includes backend, model, effort, prompt, tools, safety, catalog, taxonomy, budgets and deadlines (`investment/research/acquisition_eiy_checker.py:284-287`). The pair check requires those values to match; only experiment/execution/trace identities, cache namespace and order may differ (`:367-376`). Therefore a changed prompt, model, tool set or declared backend cannot simply be inserted as an EIY arm. Do not hide a changed treatment behind an unchanged hash or weaken this checker to accommodate the pilot.

   Keep the frozen research/source contracts and the fresh v5 evaluator intact. The maintained v5 path rereads canonical policy, underlying requests and custody, then issues fresh checked objects (`investment/research/acquisition_eiy_checker_v5.py:164-178`, `:182-232`). Its evaluator distinguishes decisive rejection from unknown/inconclusive evidence and explicitly limits its claims to structural evidence, excluding live-provider quality and financial alpha (`tuning/evals/information_fetch/information_yield/evaluator_v5.py:144-168`). Use the generic sealed contract for the first prompt/graph comparison. A future acquisition experiment needs a separately reviewed treatment-compatible design, while preserving the existing evidence-chain authority and policy; it is outside this report's implementation scope.

5. **The current request seam is enough for a first matched wrapper check, but it is not yet an A/B evaluation.** `PilotContext.variant` already selects `baseline` or `concise`, changing only one request sentence (`tuning/langchain_pilot/graph.py:51-52`, `:98-105`). The smoke client always dispatches `baseline`, captures elapsed time and run/state evidence, and does not produce a paired roster or authoritative token/cost observation (`tuning/langchain_pilot/smoke.py:37-80`). Both variants are already constrained to the same exact JSON answer by the system prompt, so no useful quality or output-length gain should be presumed (`tuning/langchain_pilot/graph.py:160-164`). Use this as a plumbing/negative-control experiment, then choose one substantive intervention only after identifying a concrete failure.

   Six source-defined boundary tests use a scripted fake model; they cover the public graph, invalid input, fabricated answer, missing tool use, visible failure and orphan receipt (`tuning/langchain_pilot/test_graph.py:13-67`). Reported passing boundary checks and a local graph/schema API are scoped evidence only. Actual provider E2E remains **unverified** in the review handoff; no private receipt was inspected here. Neither source inspection nor agreement among reviewers fills that gap.

## Minimal arm specification to implement next

This is a proposed configuration, not an executable config file or a registered/sealed experiment. It deliberately uses the graph's existing seam and fresh synthetic development inputs. The two repetitions exercise pairing/order and do not provide statistical power or independent investment observations.

```yaml
experiment: langchain-calculator-matched-v1
split: development
blindness: unblinded
arms:
  baseline: {context: {variant: baseline}}
  candidate: {context: {variant: concise}}
controlled:
  graph_and_tool: same_frozen_source_closure
  model_and_gateway: same_requested_profile_and_loopback_endpoint
  output_token_limit_per_model_call: 1024
  model_call_limit_per_run: 3
  provider_timeout_seconds: 180
  sdk_retries: 0
  server_recursion_limit: 16
  outer_timeout_seconds_per_run: 420
  tracing: false
  fresh_thread_per_case_repetition: true
roster:
  - id: one_period
    input: {case_id: one-period, fcff: ['110'], terminal_ev: '0', rate: '0.1', net_debt: '0', shares: '10'}
    expected: {per_share: '10', successful_bound_tool_receipt: true}
    critical: true
  - id: debt_contrast
    input: {case_id: debt-contrast, fcff: ['220'], terminal_ev: '0', rate: '0.1', net_debt: '50', shares: '10'}
    expected: {per_share: '15', successful_bound_tool_receipt: true}
    critical: true
  - id: invalid_shares
    input: {case_id: invalid-shares, fcff: ['110'], terminal_ev: '0', rate: '0.1', net_debt: '0', shares: '0'}
    expected: {input_rejected: true, model_dispatches: 0}
    critical: true
repetitions: 2
order: [baseline_then_candidate, candidate_then_baseline]
sealed_attempt_budget_per_arm: {server_runs: 6, wall_seconds: 2520}
```

When sealing, expand each case/repetition into a unique roster ID. Create one non-replayable attempt per arm before any work, using the same roster/expected answers/grader/budget and different fingerprints. Each fingerprint must include resolved prompt bytes, `variant`, graph/tool/validator source hashes, lockfile hash, requested model/effort/settings and sanitized endpoint identity. Do not infer actual upstream identity from the requested model ID. The pinned operational bounds above come from the current graph and smoke path (`tuning/langchain_pilot/graph.py:81-95`, `:166`; `tuning/langchain_pilot/smoke.py:59-62`, `:85-86`). They are bounded development limits, not empirically chosen optimal budgets.

Required per-case metrics: `input_boundary_ok`, `bound_tool_receipt_ok`, `arithmetic_ok`, `exact_answer_ok`, `model_dispatches_observed`, `tool_calls_observed`, `latency_seconds`, `input_tokens_observed`, `output_tokens_observed`, `cost_usd_observed`. Negative-case inapplicable tool/arithmetic checks should be explicitly defined by the pilot rubric before sealing. Capture dispatch counts at the actual invocation boundary, including failed calls; count a valid pre-provider rejection as zero only with independent observation. Report paired differences by case/repetition and retain every failed/unknown attempt.

Use `null` for unavailable token/cost metrics, as allowed by `finish`; never report them as zero or infer dollars from a proxy (`tuning/evals/evidence_runtime/contracts.py:268-275`; `tuning/AGENTS.md:15-25`). The contract's numeric `usage` must exactly match the budget keys and contain observed finite values (`tuning/evals/evidence_runtime/contracts.py:251-253`), so the initial budget contains only host-measurable run count and wall time. The existing provider/middleware bounds still apply equally to both arms. If a later token/cost ceiling is required, add a trustworthy measurement/enforcement path and a new contract version before execution.

Critical failures: invalid input reaches the provider; missing/orphan tool receipt; calculator/answer mismatch; altered sealed inputs or unpinned grader; dropped roster item; budget breach; external effect; or automatic replay after an unknown outcome. Any observed critical violation rejects that candidate/version for this scoped gate. Missing transport/usage/required evidence keeps the corresponding comparison inconclusive; a missing cost observation blocks a cost-saving claim. No faster run can offset a correctness or evidence failure (`tuning/AGENTS.md:7-25`; `mentor/skills/evaluation-design/references/investment-context.md:31-62`). Stop after the declared roster with no quality retries. Permit only the claim that paired dispatch, capture and grading work at this scope; tied exact answers do not establish framework or skill effectiveness.

No skill-to-agent compiler, new planner, vector store, persistent memory service, generalized graph-per-skill layer, evaluator framework, scheduler rewrite or production migration is justified by this experiment. Reuse the existing owners and one comparison adapter; add a new abstraction only for a demonstrated second consumer or unmet requirement (`mentor/skills/development-discipline/SKILL.md:21-39`, `:122-148`). Any future major production integration still requires an actual future-triggered Codex business execution and independently verified acceptance-email readback; this documentation-only review sends no email (`docs/deployment/runtime-acceptance.md:9-21`, `:47-71`, `:138-164`).
