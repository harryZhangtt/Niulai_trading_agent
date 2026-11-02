# Jev labeling: paused handoff

User asked to stop this stream and hand it to another agent on2026-11-01.
Do not interpret this handoff as provider readiness or automatic promotion.
The root continues acquisition/A-B investigation and the local dashboard separately.

## Current state

- Official matching service: TypeSafe Jev, pinned `jev-1.14.0`.
  [Models](https://docs.typesafe.ai/models),
  [API](https://api.typesafe.ai/redoc),
  [probability semantics](https://docs.typesafe.ai/confidence).
- `shared/typed_judge/` supplies engine-scoped typed Boolean/Noul and Enum/Choice
  requests, closed output validation, exact resolved-model check, finite probability
  bounds, enum sum/argmax checks, explicit abstention, bounded subprocess transport,
  no redirects and an immutable normalized-output cache. Live defaults off.
- Credential is already stored at `.job-runtime/credentials/jev.api-key`, owned
  mode0600 under an ignored private directory. Never copy its value into prompts,
  source, fixtures, command arguments, logs, this document or another task message.
  The authorized worker loads that reference; no global environment/config changed.
- `investment/research/source_labeler.py::label_source` guards source availability
  and exact immutable chunks before model exposure, asks one document-type Choice
  plus11 independent topic Noul questions in one call, and emits a source/chunk/
  taxonomy-bound evaluation output. Publisher/perspective are conservative rule
  hints; epistemic status remains unknown. Model labels remain provisional.
- `information_labels.annotate_source(...,policy=...)` supports explicit immutable
  model-policy sidecars without relabeling old artifacts. Optional sidecar failures
  do not rewrite authoritative result status. No active global action registration,
  automatic classification daemon or default model override was installed.
- `tuning/evals/label_accuracy/` supplies sealed input/gold/code/arm/budget contracts
  and retained attempts. Measures document accuracy/confusion/macro-F1, independent
  topic PR/F1/exact-set, abstention coverage/selective error, valid-gold Brier/log
  losses and known/unknown latency/cost. Transport errors/disabled calls cannot pass
  as abstentions. Missing cases, future versions, changed gold/code/budget/source
  bindings fail. No gold set or live label accuracy measurement has been completed.

Local evidence: typed-judge14 tests; domain/labels/typed-judge combined33 tests;
label evaluator9 tests passed. These are synthetic/conformance evidence, not
Jev task accuracy, calibration or live integration acceptance.

## Actual live observations — preserve all outcomes

1. First real POST to the official pinned `/v1/systemone` used a small excerpt
   from the already captured public NOW Q12025 earnings source and two questions.
   The worker hit its12s hard wall deadline. Result:
   `error / JUDGE_TIMEOUT_UNKNOWN_OUTCOME`, zero returned classifications,
   model/usage unknown. It was **not automatically retried**. The request may
   have reached the provider; billing/completion is unknown.
2. Public official OpenAPI HEAD returned200 from this host. A separately bounded
   read-only authenticated `/v1/models` diagnostic returned200 and a `models`
   object, taking about31s across network phases. This is not a successful
   classification; the diagnostic did not establish whether that endpoint requires
   authentication or independently authenticate the account/key's permissions.
3. No eight-case label A/B was run. No label accuracy, probability calibration,
   latency SLA, cost saving or forecast gain is established.

The first POST receipt is private:
`.niulai-state/reports/research-sources/runtime/datasource-observability-20261101/jev-smoke/a3f2cf54627dcb657463d1d19a0d0207d9cafd0b997ffb1f7a61307d1f37e434.json`.
Do not overwrite or relabel it as a pass. The existing datasource scheduled v1
failed on a different Codex response-schema compatibility issue, not on Jev; its
record is `.job-runtime/acceptance/datasource-observability-20261101-v1/record.json`.
Do not reuse that failure or old scheduled proof to accept a new Jev integration.

## Next agent: smallest useful sequence

1. Read root/mentor/evaluation instructions and `shared/typed_judge/README.md`.
   Review the observed slow host transport before another billable POST. Keep a
   single retry owner, hard total deadline, no same-call automatic replay after
   unknown outcome and no global network/proxy changes. A changed diagnostic or
   separately registered attempt must retain the first unknown result.
2. Verify one public captured source through `label_source` with explicit opt-in.
   Use an explicitly provisional development threshold policy (default no policy
   deliberately abstains). Check real receipt, distributions/model, chunk/source
   binding and repeat-cache reuse. Do not send private reports before reviewing
   provider retention terms; ZDR is not established by default.
3. Prepare/freeze eight source-bound development cases before calls. Independently
   annotate allowed document types/topic sets; separate ambiguous cases explicitly.
   Withhold gold from both rule and Jev worker packets. Use identical chunks,
   taxonomy, cutoff and budgets, register both arms before dispatch and retain all
   failures/unknowns. Group correlated chunks by original source/version.
4. Report per-dimension accuracy and coverage plus latency/usage, with unknown
   costs preserved. This development screen detects failures; it cannot establish
   generalization, significance or calibrated confidence. Later add genuinely held
   out source families and independently reviewed labels before default promotion.
5. Update setup runbooks/inventory and run setup audit. A newly wired major runtime
   needs its own real future-triggered configured Codex path and independently
   checked postconditions plus exact configured-owner email readback. Preserve
   production jobs, model/auth ownership, archives and global settings.

## Important interpretation

Choice confidence is a statistic of the predicted distribution, not independent
P(correct). Noul questions are independent probabilities, not a single categorical
softmax. Unknown/abstained/error are distinct. Keep dates, hash checks, arithmetic,
cutoff admission and durable state transitions deterministic. This judge annotates
candidate information; it does not certify factual truth, economic support,
independence, historical eligibility or investment usefulness.
