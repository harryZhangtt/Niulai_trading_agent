# Thin reasoning controller and publication integration

Policy **2026-10-24-reasoning-controller-1**. Keep the installed financial research skill and native orchestrator as the single execution backbone. Do not install another agent framework, queue, vector database or resident critic for this layer.

## Runtime boundary

1. Reuse the dated baseline and current evidence. Call `reasoning_controller.py --input case.json --output route.json` for material gaps. FAST reuses; FOCUSED repairs one dependency or runs one targeted investigation; DEEP compares distinct evidence paths with independent verification. External access and exhausted budgets remain explicit checkpoints. The 0/1500/5000 incremental-token and 0/2/5-call defaults are initial engineering settings, not measured optima or a claim about traffic proportions.
2. Native agents/tools perform the requested work; Python never manufactures research or dispatches nonexistent workers. Record actual usage in existing traces. The controller allocates a ceiling but cannot intercept native calls or guarantee model token usage. No MCP named `reasoning.resolve` is installed: the CLIs are callable functions until a real deployment adapter is authorized.
3. Feed actual attempts and bound calculations into `research_resolution.py`. Freeze expected questions before work; retain source/model versions, negative evidence and independent review. A more favorable prose tone, extra searches or agent agreement is not an insight metric.
4. Recalculate relevant valuation/payoff and equal-budget entry comparisons. Closure by robust bounds means the proposed action survives *declared alternative model regimes*. It does not demand a risky asset outperform cash in every possible realized market outcome. A supported expected-utility decision remains possible through the ordinary research/review route; do not turn this layer into a universal riskless-return veto.
5. Run finalization and completion with the actual publication evidence. New full company/fund/crypto records with cutoff or observed publication on/after **2026-10-24T10:28:00Z** require the resolution block below. Historical and narrow/price-only reports preserve their scope. Do not backdate publication to avoid the guard. Manual work does not enable disabled research schedules.

## Evidence contract

Add `policy_versions.active_resolution=2026-10-24-active-resolution-1` and:

```json
{"research_resolution_evidence":{
  "version":"2026-10-24-active-resolution-1",
  "status":"reviewed",
  "expected_question_ids":["question-id"],
  "ledger_artifact_id":"resolution-input",
  "output_artifact_id":"resolution-output",
  "review_artifact_id":"resolution-review",
  "communication":{"route":"direct","reason":"Written directly from checked claims; independent semantic review performed."}
}}
```

Use `pending` for unfinished progress. Register all evidence under `record.artifacts` with absolute paths and exact hashes, including the final report. Ledger subject/cutoff/author and proposed action must match the record. Ledger nested artifact paths must be absolute and match the main catalog. Expected question IDs must match the frozen roster and independent review. The recomputed output must equal the saved output. An open investigation cannot certify completed research; a scoped external blocker must have real access/not-available evidence and cannot support an action that requires resolving it.

Independent review JSON requires `status=approved_resolution_scope`, `reviewer_id` matching the separate research reviewer, subject/cutoff/proposed_action, `reviewed_question_ids`, `reviewed_at`, exact `artifact_hashes` for ledger/output/report and every referenced ledger artifact, and substantive `inventory_completeness_finding`, `attempt_sufficiency_finding`, `decision_bounds_finding`, `communication_finding`. This review must inspect omissions and semantic truth; file hashes alone do not do that.

For editorial rewrites use `communication.route=rewrite`, `input_artifact_id`, `output_artifact_id`. The existing gate recomputes `financial_report_checks.check`, requires parity success, pins both artifacts in review, and verifies the declared rewritten claims occur in the published report. Protect *all* action-changing claims; the software cannot discover undeclared omissions, prove financial semantics or certify CSS visibility. Independent final-report inspection is mandatory. Direct writing needs the same independent semantic review but no redundant before/after artifact pair. Translation is a separate reviewed artifact, not a numerical research revision or same-language parity claim.

## Small interfaces and migration

The reusable components are standard-library Python files alongside the existing calculators; no additional production numerical dependency is added. JSON packets and file hashes are the interface. The quote collector optionally reuses the existing pinned exchange calendar. Keep credentials in an approved secret manager injected into a narrowly scoped process, outside packets, git and report archives.

To transfer, copy the current installed skill with its existing relative dependency files, or use its Git revision. Do not copy only a wrapper while omitting `options_payoff_checks`, `research_resolution`, `rationale_guard` and their imported dependencies. CLI packets are portable when artifact paths are rematerialized and manifests regenerated; absolute runtime paths are intentionally not assumed portable. No claim is made that existing SQL queues, LangSmith credentials or native hooks transfer merely by copying a file.

Evaluate policy changes with [offline evolution](research-harness-evolution.md). Candidate edits happen in an isolated copy; baseline, dataset/rubric, trial budget, validation and sealed holdout remain frozen. Never let an optimizer edit its own guard, labels or holdout. A promotion recommendation does not change production, trades or alert levels. Real outcome calibration stays in existing forecast records, with original timestamps and failed/niche/abstained cases retained.
