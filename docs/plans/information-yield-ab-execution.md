# Information-yield B0-versus-F A/B execution preregistration

Status: **PROVIDER-INDEPENDENT EXECUTION PACK — READY TO SEAL ONLY AFTER BOTH-HOST LIVE STRUCTURAL ACCEPTANCE**. Prepared 2026-11-05 from the accepted/frozen version-1 metric contract at `docs/plans/information-yield-dashboard.md` (SHA-256 `72f93cfac1c8e47084fd3c86b6d5cdb4ba7e4e8b11df90f20895fa1166b1ce9f`). This document does not start the A/B, select issuers, expose a holdout, establish data-quality improvement, or authorize provider/email/runtime effects.

## 1. Decision and allowed claim

Decision: compare the admissible, source-supported information in the full acquisition arm **F** with competent normal fetching **B0** under matched conditions, subject to integrity, support-quality, lineage, time and resource safeguards.

The estimand is the ordered pair `EIY = (EIY_R, EIY_D)`, not a weighted score. The allowed conclusion is adopt, reject, or inconclusive for this acquisition candidate and this sealed cohort. Forecast accuracy, valuation, recommendations, price/return, positions, entry policy, PnL and alpha are out of scope.

Execution is blocked until all of the following are recorded:

1. successful live structural Codex smoke and narrow traces;
2. successful live structural Claude smoke and narrow traces;
3. checker-backed publication/readback for both narrow lanes;
4. final setup synchronization;
5. frozen candidate/B0 configurations, grader/rubric, case roster, metric policy and common budget;
6. an owner-independent custody/read log proving no target-output access before sealing.

## 2. Experimental and analysis units

- Independent experimental and analysis unit: one sealed **issuer-window**.
- Required scoped-confirmation cohort: six issuer-windows from six distinct issuers.
- Sources, disclosures, representations, passages, canonical units, required fields, model/tool calls, review order and repeated runs are repeated measures beneath the issuer-window and are never counted as independent cases.
- NOW, familiar examples, calibration cases and any case inspected while designing or debugging the candidate are excluded from EIY aggregates and untouched confirmation.
- Development precedes confirmation: one or two separately marked non-NOW issuer-windows may be used to validate the evaluator and estimate direction. They cannot be promoted into the six untouched cases.

## 3. Outcome-blind roster selection and strata

The six untouched slots are populated before target outputs using only metadata available to the roster custodian. Selection aims to expose transport and extraction heterogeneity without selecting on expected arm performance:

- six distinct issuers;
- at least three predeclared sector families where the eligible pool permits;
- at least two primary-source surface classes;
- both table-heavy and narrative-heavy disclosures;
- both straightforward and multi-document/definition-sensitive required-field sets;
- amendment/revision exposure represented where prospectively identifiable;
- no more than two issuers from one sector family unless the eligible pool makes this impossible.

These are balance targets, not outcome filters. Any infeasible target, exclusion or replacement is decided and recorded before unblinding with an immutable reason. No case may be substituted after either arm starts. Selection metadata must not include candidate-specific retrieval results, support judgments, richness, depth, freshness or expected winner.

## 4. Arms and treatment contrast

### B0 — competent normal fetching

- common immutable safety/accounting/review ledger enabled;
- competent search/open/find behavior enabled;
- information catalog/admission policy disabled;
- typed representation recovery disabled;
- no candidate-only source roster, quote, canonical unit or field hint.

### F — full acquisition pipeline

- the same common ledger, safety, accounting and review boundary as B0;
- catalog/admission/accounting enabled;
- typed, predeclared representation recovery enabled;
- no capability, budget, model, backend or reviewer advantage over B0.

The contrast is exactly F minus B0. R/C attribution arms are not part of the version-1 confirmatory test and remain exploratory if later authorized and separately sealed.

## 5. Matched execution controls

Freeze and hash before execution:

- one accepted host/backend per cohort; never mix Codex and Claude outputs within one F-versus-B0 contrast;
- model, model profile, effort, prompt shell and tool contract;
- search/open/provider budgets, concurrency, deadlines, raw-output limits and stopping rules;
- safety and effect journal versions;
- information catalog/taxonomy and candidate code;
- B0 code/configuration;
- evaluator, canonicalizer, reviewer rubric and calibration examples;
- required-field roster and baseline state;
- baseline inventory and frozen reference set;
- case order, arm order and cache namespaces.

Use cold, isolated caches per case and arm. Counterbalance arm order as three F-first and three B0-first slots using a roster-custodian-generated allocation sealed before execution. Both arms retain every logical, reserved and actual provider operation; hidden retries and unchanged retries are prohibited.

## 6. Masking, custody and roles

Separate roles where feasible:

- **roster custodian:** selects/seals cases and order without target outcomes;
- **live operator:** executes exact sealed arm packets and cannot grade support;
- **assessment author:** prepares canonical-unit/field candidates without promotion authority;
- **reviewer:** judges pooled, arm-hidden candidates in randomized order;
- **adjudicator:** resolves preregistered disagreement classes;
- **evaluator:** reopens immutable artifacts and computes metrics;
- **decision owner:** applies the frozen rule without changing data or thresholds.

The reviewer sees pooled candidates without arm labels. Candidate IDs are randomized and stable across review/adjudication. Every custody read is logged. First target-output access spends that case/cohort for that candidate.

## 7. Admissibility and canonicalization

A richness unit is counted only when it is new relative to the frozen baseline inventory, question relevant, answer bearing, literally supported, bound to exact source/version/quote/offsets, canonicalized, independently reviewed, and attached to a complete acquisition trace.

Mirrors, syndication, representations of one disclosure, rewordings, sentence splits, repeated citations and independent confirmations do not create additional canonical units or original lineages. Pooled review must be complete before richness is evaluable.

## 8. Frozen outcomes and denominators

For arm `a` and case `c`:

`R[a,c] = |U[a,c]|`, where `U` is the set of admissible supported-new canonical IDs.

`DeltaR[c] = R[F,c] - R[B0,c]`.

Frozen-reference coverage is required separately for every arm and case:

`RefCoverage[a,c] = |U[a,c] ∩ G[c]| / |G[c]|`.

Retain the explicit numerator `|U[a,c] ∩ G[c]|` and denominator `|G[c]|` in every arm/case artifact. `G[c]` and its content hash are sealed before target outputs. Pooled-union additions are retained in a separate immutable log and never expand, replace or retrospectively correct the frozen denominator.

Required-field states are `unknown=0`, `partial=1`, `resolved=2`.

`D[a,c] = sum_f(s[a,c,f] - s0[c,f])` and `DeltaD[c] = D[F,c] - D[B0,c]`.

Co-primary cohort outcomes:

- `EIY_R = mean(DeltaR[c])` over evaluable issuer-windows;
- `EIY_D = mean(DeltaD[c])` over evaluable issuer-windows.

For depth, every arm/case artifact reports both frozen denominators: `|F_c|` applicable required fields and `2|F_c|` possible positive state steps. The co-primary depth outcome remains the unnormalized field-state step count; neither denominator rescales `DeltaD[c]`.

Report separately for richness and depth:

- arm totals and per-case values;
- per-arm/per-case RefCoverage numerator, frozen denominator and ratio;
- per-arm/per-case applicable-field and possible-positive-step depth denominators;
- paired delta mean, median and range;
- strict win/tie/loss counts;
- leave-one-issuer-out means;
- richness shared/F-only/B0-only sets as a development diagnostic;
- full depth transition matrix and applicable-field denominator.

Every report shows planned, completed, valid, evaluable-richness, evaluable-depth, evaluable-freshness and unknown-pair counts, exclusions and immutable reason codes.

## 9. Integrity, safeguards and diagnostics

Hard failures override all favorable outcomes: future/unknown exposure, fabricated/openless support, unknown-outcome replay, duplicate dispatch, budget/deadline breach, source/version/URL/quote mismatch, secret/holdout leakage, missing credited-unit trace, silent case removal, unclassified failure or unreconciled crash checkpoint.

Mandatory safeguards:

- zero hard integrity failures;
- complete chains / credited units = 100%;
- every planned arm/case retained and pooled review complete;
- zero critical unsupported units;
- supported precision difference `P_F - P_B0 >= -0.05`, with judged denominators;
- aggregate original lineages F >= B0 and no case more than one lineage lower;
- each arm <=600 seconds, aggregate wall-time ratio <=1.25 and every case ratio <=1.50;
- identical budgets/backend/model/effort, cold isolated caches, counterbalanced order;
- recovery opportunities classified before arm outcomes;
- cost/token claims only from observed receipts.

Freshness, stability, recovery, lineage, latency, work and cost are separate diagnostics and never compensate for a co-primary failure.

## 10. Decision rule and multiplicity

Adopt only when all conditions hold:

1. `EIY_R >= +1.0` canonical unit per issuer-window;
2. `EIY_D >= +1.0` field-state step per issuer-window;
3. at least 4/6 untouched cases are strictly positive for richness;
4. at least 4/6 untouched cases are strictly positive for depth;
5. no case is below -1 on either outcome;
6. every leave-one-issuer-out mean is >0 for both outcomes;
7. every mandatory integrity and safeguard rule passes.

Reject on a hard failure or clear observed regression. A positive result below either margin, mixed evidence, any planned non-evaluable pair, incomplete review, invalid custody or insufficient calibration is inconclusive unless an independently decisive hard failure requires rejection.

Richness and depth are co-primary and both must pass. They are not summed, weighted or substituted. No alpha adjustment or financial metric is tested. Diagnostics are descriptive; any later diagnostic promotion rule requires a new version and seal before outputs.

## 11. Missingness, stopping and deviations

- Missing arm, invalid trace, unjudged candidate, unresolved canonical identity or unknown required-field state is null/unknown, never zero.
- Any unjudged pooled candidate makes pair richness unknown for both arms.
- Depth is null unless all applicable fields have frozen baseline and reviewed post states.
- Unknown authenticated availability remains in planned-target unknown counts and outside lag arithmetic.
- A hard-failed case remains in the roster/raw table and cannot contribute favorable yield.
- Stop the affected lane on identity/argument drift, credential/policy failure, budget/deadline breach, cancellation, unknown outcome or source-pin drift. Do not replay an unknown effect.
- Stop the evaluation and reject its version on custody break, target-output access before seal, post-unblinding metric/roster/rubric change or case substitution.
- Deviations are append-only records with time, decision owner, affected objects, rationale, expected impact and exploratory/confirmatory status. Planned analyses remain reported.

No outcome-dependent stopping is permitted. The six-case cohort is analyzed only when all planned pairs are resolved as valid, hard failed or explicitly unknown under the frozen rules.

## 12. Repeated-run development diagnostic

Before untouched confirmation, repeat a small predeclared development subset two or three times under identical budgets and cold caches to estimate acquisition stochasticity. Repeats are nested under issuer-window and remain excluded from the independent-case denominator.

Report per arm and case:

- richness/depth variance and range;
- canonical-unit Jaccard agreement;
- required-field state agreement;
- verdict flip rate;
- operation/failure-route agreement.

This diagnostic may show that confirmation is premature; it cannot promote the candidate or change v1 after target outputs.

## 13. Freshness and source revisions

Freshness uses a separately sealed prospective target roster with authenticated availability time, version identity and source-role SLA. Preserve availability, first observed, opened, admitted and ready timestamps separately when available. Undetected targets remain in the on-time denominator; unknown availability is retained but excluded from lag arithmetic.

Preserve explicit document/version relationships for amendments, corrections, supersession, mirrors and parser transformations. Historical publication dates and current captures are not reconstructed as authenticated discovery time. Freshness remains diagnostic until a separate prospective margin is sealed.

## 14. Holdout use and later confirmation

- Development cases, NOW, familiar examples and calibration items are permanently excluded from untouched confirmation.
- The six-case roster is spent for a candidate at first unblinding, even if execution later fails.
- Any candidate, prompt, model, budget, metric, admissibility, grader, missingness, stopping or review change requires a new untouched roster.
- A later steady-improvement claim requires at least two separately sealed six-issuer cohorts (minimum 12 independent issuer-windows) with directionally consistent co-primary outcomes and leave-one-out stability.

## 15. Downstream financial-inference readiness

After v1 structural and quality execution, a separate diagnostic may test whether admitted evidence packets carry exact entity, definition, unit, basis, period, denominator, mechanism, uncertainty, contradiction/counterevidence and cutoff-compatible source/version fields. Score packet conformance, arithmetic, evidence entailment and abstention separately. Do not include this diagnostic in EIY or use it to compensate for richness/depth failure.

## 16. Required outputs

- sealed roster/config/metric/rubric/custody manifests and hashes;
- exact F/B0 run, source, trace, review and adjudication references;
- per-case arm values, paired deltas, unknowns and failures;
- cohort co-primary statistics and leave-one-out values;
- safeguards and diagnostics with denominators;
- immutable verdict artifact and summary hash;
- append-only deviations;
- dashboard projection retaining evaluation -> case -> arm/run -> source/trace links.

## 17. Execution sequence

1. complete both-host live structural acceptance;
2. validate evaluator and review workflow on synthetic artifacts;
3. seal one or two non-NOW development cases;
4. execute paired B0/F development MVP and repeatability diagnostic;
5. freeze the candidate and six-case untouched roster;
6. execute all six matched pairs with blind pooled review;
7. compute version-1 outcomes and apply the decision rule once;
8. archive the spent roster and deviations;
9. only then consider a new untouched cohort or separately versioned diagnostics.
