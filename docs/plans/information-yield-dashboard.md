# Information-yield evaluation dashboard

Status: **ACCEPTED/FROZEN — LONG-TERM METRIC CONTRACT; IMPLEMENTATION AND EVIDENCE PENDING LIVE STRUCTURAL E2E**, 2026-11-05. This document is the canonical version-1 metric, decision and projection contract for matched B0-versus-F information-yield evaluation. Freezing this design does not establish acquisition superiority, implementation completion, investment returns or alpha.

## 1. Decision scope and current evidence

Use **Excess Information Yield (EIY)** for matched improvement in source-supported information versus competent normal fetching (`B0`). EIY is a two-dimensional acquisition-quality estimand, never excess return, alpha or a weighted quality score.

Current evidence is mixed and development-only:

- structural acquisition traces prove wiring and integrity checks, not information-quality improvement;
- the repeatedly inspected NOW case is a recovery/UI diagnostic and is excluded from EIY aggregates;
- the registered v1 result is sensitivity-dependent: the 18-versus-15 richness ordering reverses to 14-versus-15 when explicitly anonymous reports are excluded;
- the documented round-v2 NOW result is a scoped regression: 15 supported new units versus 22–23, 5/8 usable reads versus 8/8, fewer original lineages and higher latency.

The tested v2 candidate is rejected for that NOW workload. Overall acquisition superiority remains unverified.

### 1.1 Long-term evaluation goal

Evaluate whether the acquisition pipeline produces **more decision-ready, source-supported understanding than B0** under matched conditions. The frozen hierarchy is:

1. **Integrity gates first:** no future exposure, fabricated/openless support, unknown replay, duplicate dispatch, source/version/quote mismatch, missing trace, silent case removal, secret leakage or unreconciled effect. A hard failure cannot be offset by any positive metric.
2. **Co-primary information outcomes:** matched richness (`EIY_R`) and depth (`EIY_D`) at the issuer-window unit. Both must pass independently; there is no scalar quality score.
3. **Operational diagnostics:** prospective authenticated freshness, usable-body yield, recovery/stability, lineage/redundancy, latency, provider work and observed cost. These diagnose mechanisms and constraints but do not compensate for either co-primary outcome.
4. **Incremental information value:** the supported baseline-relative knowledge delta that resolves frozen questions or required fields, including counterevidence and explicit uncertainty. Volume, prose length, source count and retrieval novelty alone earn no value.
5. **Downstream inference readiness:** whether admitted units can be consumed by a later financial-analysis layer with definitions, units, periods, entities, mechanisms, denominators, uncertainty and counterevidence intact. This is a diagnostic interface, not a forecast, valuation, recommendation or trading score.

Evaluation stops at the highest completed evidence level. Missing, mixed, invalid or underpowered evidence is inconclusive; a material observed regression or hard failure rejects the candidate version. Expansion requires a predeclared decision need, not a disappointing sign.

## 2. Experimental unit, arms and admissibility

The independent unit is one sealed **issuer-window**. Sources, HTML/PDF representations, passages, quotes, fields, model calls, review orders and repeated runs are repeated measures beneath that unit.

The first MVP compares only:

- **B0:** competent normal search/open/find with the common immutable ledger, safety, accounting and review; catalog/admission off and typed recovery off.
- **F:** full catalog/admission/accounting plus typed recovery.

Keep backend, model, effort, prompt shell, budgets, deadlines, safety ledger and reviewer contract matched. Use cold isolated cache namespaces and counterbalanced arm order. Do not mix Codex and Claude outputs inside an F-versus-B0 contrast; fix one accepted host/backend per cohort.

A unit is admissible for richness only when pooled review is complete and it is:

1. supported by an exact quote in an eligible opened source version;
2. answer-bearing for the frozen question/required field;
3. temporally eligible at the cutoff;
4. classified as `new_fact`, `refinement` or `counterevidence`;
5. not semantically present in the frozen baseline inventory;
6. assigned a complete canonical key and original lineage; and
7. bound to a complete acquisition trace.

Independent confirmations, syndication, mirrors, PDF/HTML forms of one disclosure, rewordings, sentence splits and repeated citations do not create new canonical units or lineages.

## 3. Co-primary outcomes

For issuer-window `c`, arm `a ∈ {F, B0}`, frozen baseline inventory `B_c`, and frozen applicable required fields `F_c`:

### 3.1 Richness

```text
U[a,c] = distinct canonical IDs of admissible new units from arm a in case c
R[a,c] = |U[a,c]|
ΔR[c]  = R[F,c] - R[B0,c]
```

Also report frozen-reference coverage separately:

```text
RefCoverage[a,c] = |U[a,c] ∩ G[c]| / |G[c]|
```

`G[c]` is sealed before target outputs. Union additions are logged separately and never expand the reference denominator after results are seen.

### 3.2 Depth

Freeze every applicable required field and its baseline state before execution. Use:

```text
unknown = 0
partial = 1
resolved = 2
```

For every arm and field retain baseline state `s0[c,f]` and reviewed post-arm state `s[a,c,f]`:

```text
D[a,c] = Σ over f∈F_c (s[a,c,f] - s0[c,f])
ΔD[c]  = D[F,c] - D[B0,c]
         = Σ over f∈F_c (s[F,c,f] - s[B0,c,f])
```

This gives `unknown→partial = +1`, `partial→resolved = +1`, `unknown→resolved = +2`, `resolved→partial = −1`, `partial→unknown = −1` and `resolved→unknown = −2`. Report every transition direction and facet separately. Denominators are `|F_c|` applicable fields and `2|F_c|` possible positive state steps; the co-primary value remains the unnormalized state-step count per issuer-window.

### 3.3 EIY summary

```text
EIY_R = mean over evaluable issuer-windows of ΔR[c]
EIY_D = mean over evaluable issuer-windows of ΔD[c]
EIY   = (EIY_R, EIY_D)
```

Report paired totals, mean, median/range, strict win/tie/loss counts and leave-one-issuer-out means for both dimensions. Do not sum richness and depth, and do not fold freshness, latency, cost or precision into EIY.

## 4. Freshness is a separate prospective diagnostic

Historical replay cannot establish uncontaminated discovery timing. Freshness requires a separate prospective target roster `T_c` with authenticated availability time `A[c,t]`, frozen source/version identity and deadline. Detection is the first immutable eligible worker exposure `E[a,c,t]`.

```text
lag[a,c,t] = E[a,c,t] - A[c,t]
KnownAvailability[c] = authenticated A / |T_c|
OnTime[a,c] = count(lag≤H[c]) / count(authenticated A)
ΔOnTime[c] = OnTime[F,c] - OnTime[B0,c]
ΔLag[c] = median over targets detected by both arms of (lag[F,c,t] - lag[B0,c,t])
```

`H[c]` is a predeclared source-role SLA. Undetected targets remain in the on-time denominator; unknown availability is excluded from lag arithmetic but retained in the planned-target unknown count. Current captures and publication dates must not be relabeled authenticated availability. Freshness remains diagnostic until a prospective cohort and justified margin are frozen.

## 5. Denominators, unknowns and hard failures

Every artifact and dashboard shows:

- `planned_cases`;
- `completed_pairs`;
- `valid_pairs`;
- `evaluable_richness_pairs`;
- `evaluable_depth_pairs`;
- `evaluable_freshness_pairs` and common target count;
- `unknown_pairs`, exclusions and immutable reason codes.

Rules:

- missing arm, invalid trace, unjudged pooled candidate, unresolved canonical identity or unknown required-field state is null/unknown, never zero;
- any unjudged pooled candidate makes richness unknown for both arms in that pair;
- depth is null unless all applicable fields have frozen baseline and reviewed post states; known/applicable counts remain visible;
- confirmation cannot silently drop unknown pairs; any non-evaluable planned pair makes the quality verdict inconclusive unless an observed hard failure already requires rejection;
- hard-failed cases remain in the roster and raw table and cannot contribute favorable yield;
- unobserved tokens, cost and authenticated availability remain unavailable;
- zero recovery opportunities is `not_applicable`, not 0% success.

Hard failures override positive EIY: future/unknown exposure, fabricated/openless support, unknown-outcome replay, duplicate dispatch, budget/deadline violation, source/version/URL/quote mismatch, secret or holdout leakage, missing credited-unit trace, silent case removal, unclassified failure or unreconciled crash checkpoint.

## 6. Frozen decision contract

This frozen version-1 section supersedes earlier “not worse in 3/4,” arbitrary `+6`, aggregate-only 4/6-win, five-point-precision and 25%-latency formulations in older datasource plan sections. Its hash-bound metric, denominator, margin, safeguard, stopping and missing-data rules must be sealed before any target output.

Pilot defaults in natural units:

- both co-primary outcomes must pass;
- `EIY_R ≥ +1.0` canonical unit per issuer-window;
- `EIY_D ≥ +1.0` field-state step per issuer-window;
- at least 4/6 untouched confirmation cases strictly positive on each co-primary outcome; zero is a tie;
- no case below `−1` on either outcome;
- every leave-one-issuer-out mean remains `>0` for both outcomes.

Replace these defaults only before confirmation outputs and only with a documented operating-cost/error-tolerance rationale. A positive result below a margin is inconclusive.

Mandatory safeguards:

- zero hard integrity failures;
- complete chains / credited units = 100%;
- every planned arm/case retained and pooled review complete;
- zero critical unsupported units;
- supported precision difference `P_F − P_B0 ≥ −0.05`, with judged-candidate denominators;
- aggregate original lineages F ≥ B0 and no case more than one lineage lower;
- all arms within 600 seconds; aggregate `Σwall_F / Σwall_B0 ≤1.25` and no case ratio above 1.50;
- identical budgets/backend/model/effort, cold isolated caches and counterbalanced order;
- recovery opportunities classified before arm outcome;
- token/cost claims only when observed.

A clear observed regression or hard failure rejects the candidate version. Broken custody, post-outcome roster/metric changes, case substitution or invalid grading rejects that evaluation version and leaves performance inconclusive unless the candidate independently committed a decisive integrity failure. Missing, mixed, underpowered or uncalibrated evidence is inconclusive.

### 6.1 Freeze and change control

Any change to a metric definition, admissibility rule, denominator, margin, safeguard, grader/calibration version, case eligibility, arm semantics, missing-data rule, stopping rule or multiplicity policy creates a new version and new seal **before** target outputs. The current confirmation roster is spent on first unblinding for any candidate; it cannot be reused after a design change. Corrections after unblinding remain development evidence and require a new untouched roster.

## 7. Evidence levels and cadence

1. **Synthetic structural:** deterministic faults/counting fake/schema/trace checks. Software wiring only.
2. **Live structural:** one bounded real host path with complete accounting. Connectivity/integration only.
3. **Development quality MVP:** one or two predeclared non-NOW issuer-windows, F versus B0 on one accepted host. Descriptive direction only; normally inconclusive for promotion.
4. **Full development attribution:** four distinct issuer-windows in B0/R/C/F only if the MVP creates a decision need. R/C/F attribution remains exploratory.
5. **Scoped untouched confirmation:** six new issuer-windows from six issuers, all complete, sealed custody/read logs, blind pooled review and no substitution. Scoped confirmation, not population-level statistical superiority.
6. **Steady improvement:** at least two separately sealed untouched six-issuer cohorts (minimum 12 independent issuer-windows), directionally consistent with leave-one-issuer-out stability.
7. **Freshness improvement:** separate prospective authenticated cohort and SLA.
8. **Investment alpha:** separate downstream prospective forecast/selection evaluation against a benchmark/horizon, with entry policy fixed and costs included.

NOW, familiar examples and calibration cases remain development diagnostics and are excluded from EIY aggregates and untouched confirmation. A confirmation roster is spent after first unblinding for any candidate. Any later prompt, policy, model, budget, metric, rubric, grader or stopping-rule change requires a new untouched roster.

## 8. Immutable evaluation fields

Preserve at minimum:

- evaluation ID; schema/rubric/grader versions and hashes; evidence level/split; candidate/B0 config and code hashes; metric/margin/safeguard policy hash; case-roster hash; seal time; planned cases; custody/read-log receipts;
- case ID, issuer, sector, window/cutoff, source surface/role, target facet, outcome-blind inclusion reason, baseline/reference hashes, required-field IDs/baseline states and prospective targets/SLA when applicable;
- arm, experiment/execution/trace IDs, model/backend/effort, prompt/catalog/taxonomy versions, budgets/reserves, cache namespace/order, timing/deadline, operation/attempt/dispatch refs, logical/reserved/actual work, terminal status/failure and observed tokens/cost/wall time;
- canonical unit/key, novelty class, support/answer-bearing/review status, source/version/raw/text hashes, exact quote/offsets, lineage, publication/modified/version-available/authenticated-available/first-observed/retrieved/screened/exposed times, temporal decision/reasons and reviewer/adjudication refs;
- field/facet ID, applicability, baseline/post states, transition/step value, evidence-unit refs and review refs;
- raw arm values, paired deltas, planned/evaluable/unknown denominators, exclusions, hard failures, safeguards, leave-one-out values, verdict and summary hash.

### 8.1 Runtime computation sources

Every metric is recomputed from immutable references; projections and UI summaries are never metric authorities:

| Metric family | Authoritative runtime inputs |
| --- | --- |
| Integrity | runner/HostWeb/driver journals, reconciliation, trace-checker gates, exposure and review receipts |
| Richness | sealed baseline inventory, canonical-unit and lineage records, exact source/version/quote bindings, pooled review/adjudication |
| Depth | frozen required-field roster and baseline states, reviewed post-arm field states and evidence-unit references |
| Freshness | authenticated availability/version record, first eligible exposure, target roster, deadline and temporal decision |
| Stability | operation/attempt receipts, failure taxonomy, preclassified recovery opportunities, cache route and terminal outcome |
| Efficiency | logical/reserved/actual work accounting, wall time and observed token/cost receipts |
| Financial-inference readiness | admitted unit-to-question/field mappings and reviewed definition/unit/period/entity/mechanism/denominator/uncertainty/counterevidence records |

Missing or invalid inputs produce null/unknown or a hard failure according to Sections 5–6; they never produce inferred zeroes, reconstructed timestamps or model-estimated costs.

### 8.2 Downstream financial-inference readiness diagnostic

This diagnostic asks whether supported information can be safely consumed by a later financial-analysis layer. For every admissible unit, preserve a mapping to a frozen financial question or model field and review these separate readiness elements:

- exact entity and field/question identity;
- metric/term definition, unit, basis, period and comparison denominator;
- evidence-to-mechanism link and stated boundary conditions;
- uncertainty, missing denominator and unresolved contradiction status;
- counterevidence/adverse-boundary coverage; and
- source/version/time compatibility with the downstream analysis cutoff.

Report `mapped supported units / admissible supported units`, `fully ready mappings / mapped units`, readiness by element/facet, unresolved contradiction count, and unknown/unavailable denominators. “Fully ready” requires every frozen applicable element; partial mappings remain partial rather than receiving prose-based credit. These diagnostics do not enter EIY or compensate for richness/depth failures.

Revenue or earnings forecast accuracy, valuation error, price/return, position sizing, recommendation changes, entry-policy performance, PnL and alpha are explicitly outside this layer. They require separate prospective downstream evaluations with fixed financial models/policies, benchmarks, horizons and costs.

## 9. Bounded API, ViewModel and dashboard MVP

Use a separate bounded evaluation endpoint/projection rather than optional fields on paginated `DatasourceResponse`. Wire DTOs live in `ui/datasource/src/types/informationYieldApi.ts`; only transport and the feature adapter import them. Components consume a total ViewModel with explicit `known | unavailable | not_applicable` states and never use `?? 0` for missing evidence.

Overview order:

1. evidence banner: evidence level, candidate/B0 hashes, rubric, issuer-window unit, last seal, completed/planned/evaluable/unknown counts and verdict;
2. two outcome cards: raw F/B0 totals and paired richness/depth deltas, each linked to the exact case table;
3. independent lineages F versus B0 as a separate safeguard;
4. one zero-centered paired richness/depth plot only when at least two cases are evaluable, with a complete visible table twin;
5. compact diagnostic tables for richness, depth transitions, freshness known/unknown, integrity, stability and observed cost;
6. exact case → arm/run → source/trace drilldown.

Hard failures render first and force `Reject`. Transport/permission/schema failure is distinct from not evaluated, incomplete and genuine empty. Invalid IDs show not found and never select the latest/first record. The nested case view remains useful when a global run/source is off-page; emit global links only when exact lookup is supported.

MVP files:

- new versioned `tuning/evals/information_fetch/information_yield.py` and tests; preserve acquisition evaluator v1;
- new bounded `investment/research/information_yield_projection.py`;
- dedicated server endpoint/bridge;
- `InformationYield/` adapter, ViewModels and abort/request-identity hook;
- render-only banner, outcome, paired-table, freshness and hard-failure components;
- one focused browser contract.

Stop after this bounded MVP. Multi-cohort trends, leave-one-out UI, facet heatmaps, prospective distributions, cost/yield frontiers and untouched-confirmation UI are later work. Do not build a generic analytics or streaming platform.

## 10. Acceptance tests

- Canonical duplicate representations do not increase richness.
- All field transition directions reconcile to depth and summaries reconcile to pair rows.
- Positive EIY plus one hard failure renders `Reject`.
- Unjudged/unknown required evidence cannot render eligible.
- Null cost/tokens/freshness remain unavailable; zero recovery opportunity is not applicable.
- Every plot mark has one table row with identical case, raw values, delta and direction; one metric/unit per plot.
- Evaluation → case → F/B0 arm/run → source/trace links retain exact identities; invalid IDs never fall back.
- 403, timeout/503, schema mismatch, no evaluation, incomplete evaluation and retained-last-good are visibly distinct.
- Runtime narrowing rejects non-finite/negative values, malformed hashes, duplicate IDs, oversized fields, secrets/private paths/raw payloads and untrusted HTML.
- Required widths 320–2560, 200% text, keyboard-only operation, long IDs, reduced motion and no page overflow pass.
- Status colors remain reserved and direction uses text/shape as well as hue.
- A one-case live-development result is labeled single-cohort/inconclusive; the DOM contains no alpha, excess-return or steady-return claim.
- Components/hooks do not import wire DTOs; malformed information-yield data does not take down existing Overview/Runs/Evidence.

## Expected ownership

- Tuning owns versioned EIY artifacts, matched-case computation and verdicts.
- Investment research owns bounded read-only projection.
- Datasource transport/adapter owns DTO validation and request lifecycle.
- UI components render the ViewModel and never grade evidence.

Current structural traces remain wiring evidence and cannot be used as EIY or investment-alpha evidence.
