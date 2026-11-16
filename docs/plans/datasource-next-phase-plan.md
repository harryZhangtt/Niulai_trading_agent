# Datasource quality, runtime, evaluation, and observability next phase

Status: **IN PROGRESS — PROVIDER-FREE RUNTIME/UI SLICE LANDED; LONG-TERM METRIC CONTRACT ACCEPTED/FROZEN; LIVE AND QUALITY EVIDENCE OPEN** on 2026-11-05. The independently reviewed runtime amendments are implemented in the working tree and current provider-free suites pass. The canonical version-1 information-yield design is frozen in `information-yield-dashboard.md`, but its evaluator/projection/UI and all live, matched, untouched, future-once and promotion evidence remain unverified. No commit or production promotion is claimed.

## 1. Objective and current evidence

Improve the investment datasource layer so it produces broader, deeper, fresher,
traceable candidate information for downstream reasoning, without claiming that
more information automatically improves forecasts or investment alpha.

Current verified boundary:

- The information catalog, cache/store, batch acquisition, HostWeb portal,
  provenance receipts, temporal screening and acquisition grader exist as
  separately tested components.
- The deterministic controller, Codex/Claude adapters, public cooperative runner,
  crash reconciliation, operational-host receipts, role-separated review,
  independent checker, bounded publication/projection and smoke/narrow session
  contracts are implemented and provider-free verified. Synthetic evidence cannot
  become live-acceptance evidence.
- The current parent verification passes 168/168 acquisition/readiness/fault/email-bridge tests,
  58/58 focused Gmail/business/completion tests, 15/15 datasource server tests,
  typecheck/build and 45/45 pinned browser tests. These results prove local contracts
  and UI behavior only; no real provider call, scheduled acceptance or delivery has passed.
- The latest documented NOW round-v2 comparison is a scoped regression: 15 supported
  new units versus 22/23 for B0, 5/8 usable reads versus 8/8, fewer original lineages
  and higher latency. The older v1 18-versus-15 ordering reverses to 14-versus-15
  under the explicit anonymous-source sensitivity.
- NOW is repeatedly inspected diagnostic evidence. It may exercise recovery and UI
  paths but is excluded from information-yield aggregates, untouched confirmation,
  freshness and generalization claims.
- The dashboard has routed run detail screens, run-scoped evidence, checker-backed
  structural traces and explicit incomplete/unavailable states. The separate
  B0-versus-F information-yield projection/dashboard remains proposed and must not
  infer quality from structural green status.

## 2. Workstream boundaries

### 2.1 UI observability

Owns read-only presentation, navigation, chart derivations, drill-downs, and visible
failure/leakage states. It does not mutate research state, grade semantic truth, or
invent missing source bodies/configuration.

### 2.2 Acquisition runtime

Owns the deterministic state machine around agent-proposed source discovery:
planning input, operation admission, budgets, dispatch handoffs, typed failures,
recovery, checkpoints, provenance, evidence-candidate persistence, and stopping.
It does not decide final economic support or investment importance.

### 2.3 Tuning and evaluation

Owns matched experiments, reference sets, pooled review, judge calibration,
leakage controls, metrics, uncertainty, ablations, and promotion decisions. It
keeps datasource quality distinct from prediction quality and alpha.

## 3. Implementation sequence

Provider-free items 2–4 below are landed in the working tree. Item 1 remains open for final setup/effective-config closure; items 5–7 remain evidence gates. “Landed” means locally implemented and tested, not live-provider, quality, runtime-acceptance or production evidence.

1. **Freeze and audit the effective candidate**
   - Re-read concurrent changes and preserve unrelated scheduler/factor-mining work.
   - Define one versioned experiment/config envelope with complete source/config
     pins, budgets, provider readiness evidence, retry taxonomy, trace ID,
     retention declaration, rollback target, and acceptance policy.
   - Refresh setup inventory/lock and require `shared/setup_audit.py --check` to
     pass before completion.

2. **Complete the UI interaction slice**
   - Make every visible run, evidence record, comparison, case, status segment, and
     relationship actionable.
   - Open the primary detail inline in the current context. Cross-view navigation
     remains a clearly labelled secondary action.
   - Add truthful status/activity/evidence/A-B monitoring visuals with accessible
     table twins and exact API reconciliation.
   - Add explicit unavailable states for source body, raw config, cost, tokens,
     freshness, and off-page relationships.

3. **Repair controller/HostWeb contract mismatches before integration**
   - Unify question-ID grammar and URL policy before either side reserves budget.
   - Enforce capability and per-question source-role compatibility.
   - Reconcile controller versus HostWeb cache/provider accounting.
   - Normalize circuit/unknown outcomes.
   - Persist search candidates and exact quote assessments.
   - Add idempotent capture/replay and a driver-level handoff ledger.

4. **Build one application-owned acquisition driver**
   - compiled plan → frozen prefetch manifest;
   - one closed-schema agent proposal;
   - deterministic admission;
   - HostWeb cache/dispatch/capture;
   - typed failure/alternate recovery;
   - screened-body assessment;
   - immutable unit attachment;
   - terminal controller/HostWeb receipts.

5. **Run a narrow real E2E**
   - One current NOW question, cache disabled, one search, one deliberately brittle
     PDF open, one predeclared HTML alternate, one screened body, one exact quote,
     and complete trace validation.
   - This proves integration and recovery only, not acquisition superiority.

6. **Run staged information-yield evaluation**
   - keep deterministic faults and the NOW fixed-source replay as structural/diagnostic evidence only;
   - first run one or two predeclared non-NOW issuer-windows as matched **F versus B0** development pairs on one accepted host;
   - implement the full B0/R/C/F four-arm attribution experiment only if the bounded MVP creates a decision need;
   - use six new issuer-windows for untouched F-versus-B0 confirmation after one frozen decision contract passes;
   - use separate prospective authenticated disclosure cases for any freshness/detection-lag claim.

7. **Future-once runtime acceptance**
   - Pin the complete candidate and effective config.
   - Use one future-triggered scheduled session, independent postcondition checks,
     rollback/reconciliation evidence, and exact configured-owner email readback.
   - Do not promote directly to recurring production.

## 4. UI acceptance contract

### 4.1 Entry actionability

Every visible primary entry must be keyboard and pointer actionable:

| Entry | Primary action | Required detail |
| --- | --- | --- |
| Collection run | Open inline run detail | query, IDs, status/times, metrics, real configuration JSON, requirements, attempts, reason codes, selected evidence, captured source list, receipt hashes, limitations |
| Research run | Open inline run detail | query, IDs, phases/scripts, metrics, linked evidence, catalog questions, exact bounded observations, explicit raw-config-unavailable state |
| Comparison run | Open exact comparison/arm detail | collection/review status, budgets, cache outcomes, metrics, sources, bounded units, hashes and limitations |
| Evidence record | Open inline evidence inspector | public source link when valid, explicit body availability, sanitized preview when present, labels, timestamps, temporal decision, immutable IDs, limitations and linked entities |
| Comparison | Open exact comparison | takeaway/limits, arm definitions, primary measures, matched cases, order sensitivity, linked runs and immutable report identities |
| Comparison case | Expand exact case detail | A/B execution IDs, statuses/reasons, metrics, receipt hashes and captured summaries when projected |

Primary detail opens inline. “Open in Evidence,” “Open comparison,” and public URL
are separately labelled secondary actions. Invalid IDs render a not-found state and
never silently select the first record.

### 4.2 Visualization truth

- Status distributions use separate denominators for research, collection, and
  comparison runs. They must never be combined into one misleading whole.
- Activity is labelled **Recorded run starts (UTC)**. With the current two dates it
  is an event strip/columns, not a trend line or throughput claim.
- Evidence readiness uses full-snapshot counts only when the page is complete;
  otherwise it is labelled page-only.
- Evidence relationship categories may overlap and are never stacked as a whole.
- Cache route and usability are separate dimensions. Native misses/captures/hits/
  fallbacks are raw process counts, not a stacked partition.
- A/B plots show one metric/unit at a time, known-pair denominator, A−B, and the
  relevant sensitivity. Unknown cost/freshness stays unavailable.
- Every chart has a semantic table equivalent. Tooltips never gate values.
- Chart values must reconcile exactly to the API in browser tests.
- Palette validation must pass; status colors remain reserved for status.

### 4.3 Resilience and accessibility

- Required viewports: 320, 360, 390, 768, 1024, 1440, and 2560 CSS px.
- Required text test: 200% browser text and 10× unbroken IDs/titles/URLs/reasons/
  JSON without page-level horizontal overflow.
- Long values wrap or use a labelled, keyboard-focusable internal scroller; full
  content remains reachable.
- All controls have visible focus; charts expose text/shape in addition to color.
- Loading, background refresh, retained-last-good error, no-data error, genuine
  empty, filtered empty, partial, unavailable, and not-on-loaded-page states remain
  distinguishable.
- Late responses cannot replace the current subject/entity. Refresh remains
  cancellable and bounded.
- No raw provider exception, credential, private path, or unsanitized HTML is
  rendered or persisted by browser verification.

### 4.4 UI pass gate

Pass only if build/typecheck, server tests, the full Playwright suite, focused
monitoring/drill-down/extreme-content specs, and a live read-only desktop/mobile
inspection all pass. A missing optional detector is disclosed, not treated as a
pass. No production acceptance is inferred from local UI tests.

## 5. Runtime data-accuracy acceptance contract

### 5.1 Deterministic trace chain

Every credited information unit must bind:

`experiment → requirement/question → proposal → exact operation arguments → attempt → source/version → exposure decision → literal quote → candidate unit → reviewer decision`.

The gate reports complete chains / credited units and requires 100% completeness.

### 5.2 Failure and recovery

- Distinguish transient, permanent, policy, typed representation, deadline,
  transport-circuit, and unknown-outcome failures.
- Never retry an identical failed operation unchanged.
- Never replay an unknown outcome; reconcile or start a new execution.
- Every alternate consumes the same frozen budget and must be predeclared,
  semantically compatible, and a different representation/request.
- Cache hits consume logical read budget but zero provider dispatches.
- Budgets are reserved before external dispatch and reconcile after cache/preflight.
- Crash injection at every controller↔HostWeb boundary must yield a deterministic
  resumable, blocked, or reconcile-required state—never duplicate dispatch.

### 5.3 Source/data accuracy

- Source URL, raw/text hash, source version, cutoff, availability, publication,
  modification and first-observed timestamps remain distinct.
- Search metadata/find locators cannot be credited as opened document evidence.
- Exact quote must be present in the screened body version.
- Unknown availability blocks historical worker exposure.
- Missing source body/config/cost/tokens remains unavailable, not zero or inferred.
- Source lineage, syndication and canonical information identity are reviewed
  separately from source count.

### 5.4 Runtime pass gate

Hard fail on future exposure, fabricated/openless support, budget violation,
unknown-outcome replay, duplicate external dispatch, source/version mismatch,
missing credited-unit trace, silent case removal, unclassified failure, or
unreconciled crash checkpoint.

## 6. Information-yield evaluation design contract

### 6.1 Case layers

1. **Fault cohort:** deterministic synthetic transport/state faults; no quality claim.
2. **NOW positive control:** fixed recovery/UI diagnostic only; excluded from EIY
   aggregates, development-case counts and untouched confirmation.
3. **Development MVP:** one or two predeclared non-NOW issuer-windows comparing F
   versus B0 on one accepted host/backend.
4. **Development attribution:** four distinct issuer-windows in B0/R/C/F only if
   the MVP creates a decision need that component attribution can answer.
5. **Untouched confirmation:** six new issuer-windows from six issuers, used once
   for frozen F versus B0 after all development decisions are sealed.
6. **Prospective freshness:** future disclosure windows with authenticated first
   availability and a predeclared source-role SLA.

Select cases from outcome-neutral issuer/window/sector/source-surface/PDF-burden
metadata before target outputs. If a hidden outcome class is needed, a separate
custodian applies a pre-existing rule and the resulting enrichment is disclosed.
Every roster includes explicit unresolved/missing possibilities, source-role and
surface diversity, frozen inclusion reasons and no-substitution rules.

### 6.2 Arms

First MVP and untouched confirmation:

- **B0:** competent normal search/open/find plus the common immutable ledger,
  safety, accounting and review; catalog/admission off and typed recovery off.
- **F:** full catalog/admission/accounting plus typed recovery.

Deferred development attribution only:

- **R:** B0 + typed recovery only.
- **C:** B0 + catalog/admission/accounting, typed recovery off.

Keep backend, model, effort, prompt shell, budgets, deadlines and safety identical.
Do not mix Codex and Claude outputs in one F-versus-B0 contrast; fix one accepted
host per cohort.

### 6.3 Matched budgets

The first fixed recovery protocol uses, per case/arm:

- 1 search item;
- 2 open items;
- 3 provider items;
- 60 seconds per provider call and 300 seconds inner run wall;
- concurrency 1, cache disabled and a fresh isolated namespace;
- zero unchanged retries and at most one sealed representation alternate;
- same backend, resolved model/effort and close launch window;
- every failure charged and retained;
- observed tokens/cost reported, otherwise unavailable.

A later broader discovery protocol may use a larger budget only when its need,
reserve policy and stopping rule are preregistered. The former blanket 6/8/14/600
budget is not the default for this three-dispatch recovery path.

### 6.4 Co-primary metrics and diagnostics

The independent unit is one issuer-window.

1. **Richness:** distinct admissible supported-new canonical units. A unit requires
   complete pooled review, exact quote in an eligible opened version, answer-bearing
   relevance, temporal eligibility, novelty versus the frozen baseline, canonical
   identity, original lineage and a complete trace. Mirrors, PDF/HTML forms,
   syndication, rewordings and repeated citations do not add units.
2. **Depth:** required-field state steps using `unknown=0`, `partial=1`,
   `resolved=2`. Report every transition; direct unknown→resolved is +2 and
   resolved→unknown is −2. The paired outcome is F net steps minus B0 net steps.
3. **EIY:** the ordered pair `(mean ΔRichness, mean ΔDepth)`. Never sum or weight
   the dimensions.
4. **Diagnostics:** frozen-reference coverage; judged/supported/unjudged units;
   omission sampling; independent lineages and redundancy; usable bodies/read
   attempts; preclassified recovery opportunities/successes; complete chains /
   credited units; logical/reserved/actual work; wall time; cache; observed tokens
   and cost; hard integrity failures.
5. **Freshness:** authenticated prospective detection lag, on-time rate and
   known/unknown counts, reported separately from EIY. Current capture/publication
   timestamps cannot authenticate historical availability.

Report planned/completed/valid/evaluable/unknown denominators per outcome. Unknown
is never zero. No weighted score, passage-level independence, provider-comparison
confounding or investment-alpha conclusion is permitted.

## 7. Leakage-prevention contract

### 7.1 Before execution

- Freeze case IDs, issuer windows, objective, cutoff, required fields, source roles,
  baseline research inventory, budgets, model/backend, grader, analysis and stopping
  rules before target outputs.
- Build hindsight references host-side only. Later documents may identify what was
  important but never enter worker queries, snippets, URLs, metadata, bodies, cache,
  prior context, prompts, or intermediate summaries.
- Protect untouched confirmation cases from prompt/controller/grader development.
- Use distinct arm workspaces/packets; neither arm sees the other arm's output.

### 7.2 At retrieval/exposure

- Screen every search result, document body and cache hit against cutoff and
  authenticated source-version availability before worker exposure.
- Unknown/future/qualified reconstruction remains reviewer-only and cannot earn
  acquisition credit.
- Cache keys bind cutoff, scope, source version and access view. Current cache must
  never backdate a historical body.
- Model-memory facts receive no credit unless grounded in an eligible opened source.

### 7.3 In review

- Pool candidates under neutral IDs and remove arm/process identity.
- Keep the frozen reference denominator unchanged; additions are adjudicated and
  reported separately.
- Opposite review order checks position sensitivity. Disagreement is unresolved
  and requires independent adjudication; it is not averaged into certainty.
- Log every tried variant and preserve failed/tied/unknown cases.

### 7.4 Dashboard leakage visibility

Every source/run detail must display, when projected:

- experiment and execution IDs;
- information cutoff;
- event/publication/modified/version-available/first-observed times separately;
- source-version/hash;
- worker exposed: yes/no/unknown;
- temporal decision: eligible/blocked/qualified/unknown;
- reason codes and screening time;
- cache route and whether a provider fetch occurred;
- whether evidence was credited, context-only, rejected, or unjudged.

Overview shows counts of eligible, blocked, qualified reconstruction, unknown
availability, after-cutoff, and unjudged records. A blocked/future item must remain
inspectable by reviewers but visually impossible to confuse with worker evidence.

## 8. Canonical decision and promotion contract

This section and `information-yield-dashboard.md` supersede the earlier “not worse
in 3/4,” arbitrary `+6`, aggregate-only 4/6-win, five-point-precision and 25%-
latency formulations. Freeze one hash-bound contract before any untouched output;
never choose among old/new rules after seeing results.

### 8.1 Development MVP

One or two predeclared non-NOW F-versus-B0 issuer-windows validate the metric,
review and artifact path and provide descriptive direction only. They are normally
**inconclusive** for promotion. Stop when the frozen roster is terminal; do not add
cases because the sign is disappointing. Spending the untouched roster requires a
separate explicit decision after reviewing all retained development evidence and
freezing margins, grader, roster, missing-data and stopping rules.

### 8.2 Untouched confirmation

All six planned issuer-window pairs must be complete/evaluable for both co-primary
outcomes; otherwise the verdict is inconclusive unless a hard failure already
requires rejection. Pass requires all of:

- mean paired richness gain `EIY_R ≥ +1.0` canonical unit per issuer-window;
- mean paired depth gain `EIY_D ≥ +1.0` field-state step per issuer-window;
- at least 4/6 cases strictly positive on **each** co-primary outcome; zero is a tie;
- no case below −1 on either outcome;
- every leave-one-issuer-out mean remains positive for both outcomes;
- trace completeness is 100% and pooled review/calibration is complete;
- zero critical unsupported unit or hard leakage/integrity failure;
- supported precision `P_F − P_B0 ≥ −0.05`, with judged denominators;
- aggregate original lineages F ≥ B0 and no case more than one lineage lower;
- all arms meet the 600-second ceiling, aggregate wall ratio ≤1.25 and no case
  ratio above 1.50;
- matched budgets/backend/model/effort, cold caches, counterbalanced order and
  preclassified recovery opportunities hold;
- tokens/cost are claimed only when observed.

These are pilot operating margins, not statistical-significance thresholds. Change
them only before target outputs with a documented cost/error-tolerance rationale.

### 8.3 Verdict semantics

A valid observed hard failure or frozen material-regression breach rejects the
candidate version. Broken custody, post-outcome roster/metric changes, case
substitution or invalid grading rejects that evaluation version while candidate
performance remains inconclusive unless an independent integrity failure exists.
Missing, mixed, underpowered, unjudged or uncalibrated evidence is inconclusive.

A pass makes F only **eligible for future-once runtime acceptance/canary** on the
tested acquisition strata. Recurring production, freshness and investment alpha
require separate prospective evidence and acceptance.

## 9. Independent fan-out review packet

After this file is frozen, independent reviewers receive this same plan and answer:

1. UI reviewer: can every acceptance item be exercised through the rendered UI?
2. Runtime reviewer: are all controller/HostWeb/config failure states deterministic
   and observable?
3. Evaluation reviewer: do the case roster, leakage controls, metrics and gates
   support the claimed decision without repeated-testing leakage?

Reviewers report confirmed defects and proposed plan edits separately. One owner
reconciles the plan before implementation expands.

## 10. Normative amendments from independent review

These amendments clarify and strengthen Sections 3–8. They do not turn any failed
criterion into a pass.

### 10.1 UI identity, chart, and leakage requirements

- Invalid nested `collection`, arm, case, and relationship IDs follow the same
  not-found rule as run/source/comparison IDs. No nested identity may fall back to
  Arm A, the first row, or another entity.
- Comparison-run primary action opens inline detail in Runs. Cross-view comparison
  navigation is a separately labelled secondary action.
- Every comparison case has one exact detail surface containing both execution
  identities, status/reason, selected metric values, pipeline/case receipt hashes,
  and projected captured summaries.
- The activity title is exactly **Recorded run starts (UTC)**.
- A chart table twin contains every mark/category, including every document-class
  bar—not merely headline values from the same panel.
- Palette acceptance is reproducible: run the repository-pinned dataviz validator
  against the exact series hexes and `#ffffff` surface with all relevant pairs;
  retain the pass output with UI test evidence. No dark-mode claim is allowed until
  a separate dark palette is selected and validated.
- Browser evidence enumerates all seven widths, actual 200% text, every listed 10×
  content class, keyboard-only primary/secondary flows, nested invalid IDs, and
  leakage/security canaries. Missing execution evidence is a fail.
- Leakage fields are required nullable API/ViewModel fields, not silently optional:
  experiment/execution IDs; event, publication, modified, version-available and
  first-observed times; screening time; source/version hashes; run-bound exposure;
  canonical temporal state/reasons; cache/provider route; and credit disposition.
  Unavailable is rendered explicitly.
- Normalize transport/source states into the UI vocabulary
  `eligible | blocked | qualified | unknown`; `not_evaluated` renders as `unknown`
  with its original reason retained in technical details.
- Leakage overview uses a unique source-version denominator and reports eligible,
  blocked, qualified, unknown availability, after-cutoff and unjudged separately.
  Overlapping categories are not stacked or summed as one whole. Reviewer-only
  source diagnostics never appear as worker evidence.

### 10.2 Canonical runtime contracts

- One shared pre-reservation validator owns question/operation ID grammar, public
  HTTPS URL policy, role compatibility for **every** bound question,
  capability→operation/access compatibility, and host policy. Controller and
  HostWeb cannot reserve before it passes.
- Accounting distinguishes logical search/read items, reserved provider items, and
  actual provider dispatches. A terminal reconciliation receipt binds both ledgers;
  a cache hit consumes logical read budget and reconciles provider dispatch to zero.
- One versioned closed failure taxonomy maps concrete codes to transient,
  permanent, policy, representation, deadline-before-dispatch,
  deadline-after-possible-dispatch, circuit-open, and unknown. Identical failed
  operations are never retried unchanged on any path, including batch acquisition.
- An alternate is a frozen descriptor—not a URL string—with representation kind,
  exact arguments, source role, capability/access level, semantic-compatibility
  rationale, primary relation, and budget cost.
- The driver handoff ledger uses durable states:
  `reserved → host_intent → dispatch_claimed → captured | unknown → controller_committed → assessment_saved → unit_attached → finalized`.
  Reconciliation behavior is specified and crash-tested at every edge.
- An assessment artifact contains assessment ID, experiment/execution/trace IDs,
  question/proposal/operation/attempt IDs, source/raw/text/version hashes, exact
  quote or offsets, disposition, assessor/version, cutoff, screening and timestamps.
  Candidate units must reference it.
- Search/find metadata can produce only `candidate_found`; it never completes a
  question. Completion requires an eligible opened body plus assessment, or an
  explicit blocked/unresolved terminal state.
- Immutable `experiment_id`, `execution_id`, and `trace_id` propagate through plan,
  proposal, controller, HostWeb, cache, exposure, assessment, unit, review,
  projection, scheduled acceptance and email. A deterministic chain validator
  computes the trace-completeness denominator.
- One effective-config envelope pins source/code/config/model/backend/catalog/
  taxonomy versions, readiness receipts, retry mapping, budgets including
  concurrency and token/cost observability, retention/GC owner, rollback and
  acceptance policy.
- Native cache identity binds cutoff, scope, access view, and source version or
  frozen version-selection rule; a current capture cannot satisfy a historical
  cutoff merely from an old publication date.
- Narrow E2E and future-once acceptance pin the driver, controller, HostWeb,
  cache/store, assessment/unit attachment, grader/projection, effective config and
  acceptance helper. Setup inventory/lock and `shared/setup_audit.py --check` are
  hard prerequisites.

### 10.3 Case roster, isolation, and hindsight references

- Freeze a case-roster table before reference/outcome access. Every issuer-window
  row records issuer, sector, window/cutoff, source surface/role, target facet,
  PDF/HTML burden, difficulty and an outcome-blind inclusion reason. Selection uses
  outcome-neutral event/source strata. If outcome enrichment is necessary, a
  separate custodian applies a pre-existing hidden rule and the artificial
  prevalence/generalization limit is disclosed. Quotas are fixed before results.
  Repeated NOW cases are tagged diagnostic and excluded from aggregate case counts.
- Issuer-window is the independent unit. Fields, passages, units and review orders
  are repeated measures. Four development and six confirmation cases are a
  coverage/cost pilot, not statistical superiority evidence. Expand untouched
  confirmation when uncertainty could change the decision.
- Define the ablation as a 2×2: catalog/admission OFF/ON × typed recovery OFF/ON.
  Backend, model/effort, prompt shell, ordinary retrieval capability, safety,
  ledger and failure accounting stay identical. Recovery OFF disables only the
  candidate alternate policy. Use distinct cold cache namespaces, block cross-arm
  reuse, randomize/counterbalance order, retain resolved model/time, and report
  `R−B0`, `C−B0`, and `F−R−C+B0`. One run/arm is descriptive unless repeats are
  preregistered.
- Untouched confirmation requires an enforcement mechanism, not prose: sealed
  manifest hashes, distinct case/reference custody, worker/grader access boundaries,
  read logs, and no developer access until the decision artifact is sealed. The
  roster is spent after first unblinding for any candidate. Any premature read,
  prompt/policy/model/budget/metric/rubric/grader/stopping-rule change, case
  substitution or later candidate reuse converts affected cases to development
  evidence and requires a new untouched roster. If enforcement is procedural only,
  label it procedural—not protected isolation.
- Every frozen reference unit records ID, required field, canonical key, locator
  provenance, exact eligible pre-cutoff source/version/quote, authenticated
  availability basis, lineage and limitations. Later documents may nominate but
  never support a unit. Reference builders cannot see target-arm output. The core
  denominator is frozen under a documented source-role search/stopping rule;
  union additions remain separate.
- Historical evaluation retains every query, URL, snippet, redirect, cache lookup
  and intermediate summary. Model-memory-originated targets are flagged. Historical
  replay may support grounded acquisition quality, not uncontaminated historical
  discovery timing. Only prospective authenticated cases support detection-lag or
  freshness claims.

### 10.4 Grader and metric operationalization

- Freeze a calibration packet independent of confirmation, human-reviewed across
  support, answer-bearing status, novelty, canonical identity, lineage, field
  transition and temporal eligibility. Report per-label confusion/agreement,
  reviewer agreement, order consistency and systematic errors by stratum.
  Same-family judge agreement is not calibration. Until fit-for-use minima are
  justified and passed, semantic promotion is blocked.
- Field states are frozen as `unknown=0`, `partial=1`, `resolved=2`. Preserve every
  transition direction and step value per field/case: unknown→partial +1,
  partial→resolved +1, unknown→resolved +2, resolved→partial −1,
  partial→unknown −1 and resolved→unknown −2. Net depth is the sum of reviewed
  post-state rank minus frozen baseline-state rank; unknown fields make depth null,
  not zero.
- Omission sampling freezes its frame, seed/rule, sample size, blind reviewer and
  missed-supported-unit metric before target outputs.
- Recoverable opportunity is classified before arm outcome using the frozen
  taxonomy. Report success/opportunity with reason; do not use an arm-dependent
  denominator.
- Report paired issuer-window deltas, median/range, evaluable/unknown denominators,
  and leave-one-issuer-out sensitivity. Never attach passage-level confidence as if
  passages were independent.

### 10.5 Decision contract alignment

- Section 8 and `information-yield-dashboard.md` are the canonical decision
  contract and supersede older conflicting thresholds. Freeze their metric,
  denominator, missing-data, margin, safeguard and stopping-rule hashes before
  untouched results. If the six-case pilot cannot resolve the frozen decision,
  the result is inconclusive and additional untouched evidence requires a new
  roster—not a post-result threshold change.
- Both richness and depth must meet their natural-unit margins; ties are not wins,
  no case may breach the −1 harm bound, and both directions must survive
  leave-one-issuer-out sensitivity. Precision, lineage, latency/budget and zero-hard-
  failure safeguards are mandatory and cannot be averaged away.
- The first one/two-case B0-versus-F MVP is descriptive. Full B0/R/C/F attribution
  is deferred until that MVP creates a decision need and cannot spend the untouched
  roster.
- A passing confirmation outcome is only **eligible for future-once runtime
  acceptance/canary**. Recurring production requires separate prospective evidence
  and the workspace runtime-acceptance contract.
