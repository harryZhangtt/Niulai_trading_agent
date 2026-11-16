# RD-Agent + Qlib factor-mining integration

**Status:** IN PROGRESS — 2026-11-05, source pins, frozen blocked admission policy, synthetic PIT identities, development-only authority/runner/evaluator lineage, RunManifest v1/v2, read-only observability and live empty-route activation landed; durable trusted authority, real runtimes/data, a real sanitized performance manifest, baseline reproduction and factor experiment remain unaccepted.

## Goal

Take over the `量化因子库评估` research thread without inheriting its claims as facts. Reproduce RD-Agent and Qlib cleanly, rebuild the latest individual/combination baseline from frozen local evidence, diagnose why it fails, test one economically interpretable improvement at a time, and expose the process in a read-only `/factor-mining` tab on localhost:7270.

A passing factor is not an implementation deliverable. Valid outcomes are **Pass**, **Fail**, or **Inconclusive**. EV and Kelly remain withheld until a protected, post-cost incremental-return gate passes.

## Recovered state versus local evidence

The public share was decoded into 348 turns. It consistently names Microsoft RD-Agent and Microsoft Qlib, but its Qlib Recorders, datasets, account ledgers, factor formulas, reports and linked bundles are absent from this checkout. Therefore every number below is **share-reported and locally unverified**:

- Falling real rates reportedly improved forecast MSE about **7.9% SPY / 9.7% ONEQ**, but failed multiplicity and historical-mean comparisons.
- A repaired combination reportedly had forecast skill versus historical mean of **-1.27% SPY / +0.82% ONEQ** and annualized net-log-growth increments versus RV20 of **+0.234 / +0.169 percentage points**. Confidence intervals crossed zero; SPY became negative with a three-day lag; ONEQ's latest year was negative; all eight admission checks failed.
- A simplified 63-day model reportedly improved forecast skill **+6.54% SPY / +3.41% ONEQ**, while changing annualized net log growth by **-0.138 / +0.010 percentage points**. Better prediction did not establish trading value.
- Current buy EV and half-Kelly were withheld. No later run occurred after financial-explainability was added, and the prior continuation was paused.

The latest three-year slice has reportedly only 33 mature monthly origins, roughly nine non-overlapping three-month intervals per ETF, no NBER recession month in the cited 35-month slice, and repeated reuse during selection. It is development evidence, not a protected holdout.

## Why the factor still fails

Ranked by current evidence:

1. **No independent power.** Too few effectively independent recent outcomes and repeated selection make confidence intervals wide and multiplicity material.
2. **Weak incremental economics.** Forecast-error gains have not survived matched historical-mean, fixed-exposure and RV20 controls after costs.
3. **Point-in-time/timing fragility.** Revised macro/valuation histories, options availability, same-bar execution and lag sensitivity can create or erase value.
4. **Numerical instability.** A reported bull-steepening interaction extrapolated about 39 training standard deviations; CSV float round trips changed 48 selections.
5. **Implementation defects.** SPY/ONEQ row-index errors generated empty orders; warmup and start-range sensitivity changed EMA/running-peak values. These must be regressions, but their repair did not create alpha.
6. **Correlated search families.** Many variants retuned price/rate/credit information instead of adding independent point-in-time content.

## Architecture

| Component | Owns | Must not own |
| --- | --- | --- |
| RD-Agent runtime | `fin_factor` proposal, generated factor code, feedback | data truth, promotion gates, UI |
| Qlib RD-Agent profile | point-in-time features, fit/predict, native replay at `2fb9380…` | agent proposal or publication |
| Qlib standalone candidate | compatibility comparison at `v0.9.8` | silent replacement of the RD-Agent pin |
| Project adapters | stable request/receipt DTOs, process isolation, hashes, timeouts | upstream internal types as local APIs |
| Tuning guard | protocol sealing, global trial/holdout budgets, quarantine, remediation, promotion | factor execution or alpha claims |
| Run registry | immutable manifests, attempts, artifacts, failures, resource/cache facts | mutable “latest” truth |
| Projection/API | bounded, redacted, read-only ViewModels | importing RD-Agent/Qlib or dispatching work |
| `/factor-mining` UI | lineage, freshness, factors, ablations, gates, failures, resource use | run/retry/promote/edit controls |

Runtime roots remain ignored and separate. Upstream code is never copied into scheduler/datasource modules. Generated code is untrusted and never runs in the host process.

## Deterministic anti-overfitting mechanism

The tracked implementation is `tuning/factor_mining/`. Before outcomes are read, it freezes and hashes:

- hypothesis and financial mechanism;
- snapshot and chronological development/validation/protected split fingerprints;
- exact factors, transformations and degrees of freedom;
- model, costs, cash treatment and execution lag;
- target, horizon, purge/embargo and matched baseline;
- multiplicity family/method, global variant budget and stopping rule;
- promotion criteria and numerical overfitting triggers.

Attempts are atomically published and hash-chained. Identical configurations cannot be renamed into hidden retries. A protocol version cannot reset its multiplicity-family budget, and a protected-split fingerprint can be consumed only once across the ledger. Completion requires a successful protected attempt whose evidence hash matches completion.

If declared instability appears—even after promotion—the evidence becomes quarantined and future combination/EV/Kelly use fails. Research continues only through a new parent-linked remediation protocol with a protected split unused by any ancestor. That protocol must reduce freedom or correct a declared defect, then earn fresh validation; it cannot relabel the original holdout.

## Implementation waves

### Wave 0 — identities and contracts (current)

- [x] Recover public-share turns as untrusted historical context.
- [x] Pin source-only RD-Agent and two isolated Qlib profiles with revisions, trees and license hashes.
- [x] Implement deterministic overfitting guard and adversarial negative tests.
- [x] Freeze adapter request/receipt schemas and RunManifest v1; add backward-compatible RunManifest v2 structured performance records without changing v1 identities, and verify synthetic success/failure manifests remain fixture-only.
- [x] Freeze the initial pre-outcome admission policy (`joint-easing-overlay-v1`, `d010b965…c0b9f`) with one candidate/variant/look, exact Pass/Fail/Inconclusive, controls, triggers and 13 explicit non-sealable authority/data blockers.

Gate: source verification passes; no install or experiment claim is made.

### Wave 1 — synthetic boundary complete; real two-engine E2E blocked

- [x] Run a fixed trusted synthetic subprocess through bounded request/receipt, process-group cleanup, host-owned evidence, immutable success/failure manifests and explicit missing-output failure.
- [x] Prove source/fixture packages import no RD-Agent, Qlib, pandas, MLflow or sklearn into the host process.
- [x] Define and statically verify a scalable two-container Linux runner: internal-network controller, no-network executor, digest-only images, non-root/read-only/cap/resource policy, no Docker socket, deterministic argv and fail-closed health-only workers.
- [x] Derive stable anti-relabel identities from a synthetic PIT dataset and bind them through a blocked local authority, atomic nonce claim, fixed outcome-free runner receipt and outcome-free evaluator receipt. This proves structural lineage only.
- [x] Define and adversarially verify provider-neutral disabled contracts for durable checkpoints/signers/recovery, a blocked 25-field real-source inventory, monotonic outcome-exposure ledger and calendar-replayed fresh-split readiness. These remain non-authoritative/nonsealable.
- [x] Select and freeze the lightweight GCP Cloud Run/Storage/KMS/Workflows candidate as `gcp-cloud-run-factor-mining-20261105-v1`; 60 architecture/provider files are pinned by manifest `593b5d60…7188d`. AWS remains superseded disabled comparison evidence.
- [x] Implement and separately freeze the disabled GCP authority, Cloud Run and provider/PIT contracts plus the apply-disabled activation scaffold (`gcp-factor-activation-20261105-v1`, manifest `1c31c6ca…c29a`); no cloud resource or credential was created.
- [ ] Provision the frozen GCP projects, durable checkpoint/signing/recovery, trusted real runner/evaluator/independent-check and purpose-specific publication policies after account-owned login/billing/location inputs and account-side conformance.
- [ ] Resolve digest-pinned Cloud Run images/SBOM/provenance and provider-proxy deployment. The frozen runtime and activation profiles remain `runnable:false`/`apply_allowed:false` until every blocker clears.
- [ ] Run one actual RD-Agent proposal/coding step into one Qlib materialization/replay only inside the accepted GCP runtime. Native macOS remains non-upstream-faithful.
- [ ] Run one actual RD-Agent proposal/coding step into one Qlib materialization/replay only inside that approved runtime.
- [ ] Lock real-engine regressions for future `Ref`, warmup/crop invariance, row alignment, zero orders, float round trips, availability and next-close execution.

Gate: synthetic success and forced failure are independently checkable and establish host-boundary behavior only. Real two-engine acceptance remains blocked; neither synthetic outcome proves factor quality.

### Wave 2 — current baseline reproduction

- Recover or rebuild point-in-time data, formulas, calendars, universe-by-date, labels, costs, cash interest and lags.
- Reproduce every individual factor, combination, ablation and matched control.
- Reconcile all share-reported counts/metrics or record named discrepancies.

Gate: two cache-cold runs from different directories reproduce normalized hashes and account decisions. Until then, historical metrics remain unverified.

### Wave 3 — one frozen improvement

Preferred only if point-in-time inputs are available: a prespecified real-rate-decline plus credit-spread-contraction hypothesis with no weight tuning. Otherwise, test one new event-time information source only after coverage is complete.

Report predictive and economic verdicts separately. Use block/dependence-aware inference, multiplicity correction, lag/cost/regime sensitivity, ablation and negative controls. No formula changes after target outcomes are read.

Gate: Pass, Fail or Inconclusive is recorded; no repeated tuning loop follows a failure.

### Wave 4 — read-only observability and live empty route accepted; real run pending

- [x] Add a bounded/redacted immutable-manifest projection, sibling `/api/factor-mining` bridge and lazy `/factor-mining` route without changing scheduler semantics.
- [x] Verify empty/error/stale/malformed/late-response/mobile/keyboard behavior and existing datasource/scheduler browser regressions.
- [x] Add RunManifest v2 standalone/combination/leave-one-out performance observations, provenance-aware legacy suppression and an accessible point-and-interval view with an exact table equivalent. Browser fixtures prove rendering and evidence boundaries only.
- [x] Verify the current localhost:7270 workspace owner/fingerprint and read back the actual fresh empty registry route without terminating an unrelated process.
- [ ] Render one real sanitized run manifest; fixture-only manifests remain visibly non-predictive.

The implemented page shows:

- run/protocol/snapshot/revision identities and reported-vs-reproduced labels;
- stage state, attempts, elapsed time, resource use and cache status;
- legacy scalar factor metrics with provenance-aware fixture suppression;
- structured standalone, combination and leave-one-out point estimates only when metric/unit/period/baseline and hash-bound evidence are explicit;
- implementation/predictive/economic/publication gates independently;
- failure codes, limitations and bounded immutable artifact identities without paths.

The current contract does not yet represent correlation matrices, financial-mechanism prose, selection reasons or complete point-in-time freshness/missingness. Those remain unavailable rather than placeholders. Charts require accessible table equivalents; loading, empty, error, stale, late-response, legacy, fixture-withheld and unavailable states are explicit. RD-Agent and Qlib are not embedded by iframe: Qlib has no native operational UI and RD-Agent's browser surfaces are either trace-path viewers or privileged mutable execution consoles. Future operator tools require separate authenticated top-level deployment and accepted runtime isolation.

Gate: one real sanitized manifest and one failed fixture render end-to-end; malformed/oversized/secret/path-traversal cases fail visibly; `/datasource` and `/scheduler` remain green.

### Wave 5 — throughput after correctness

Add content-addressed stage caching, duplicate-manifest singleflight, unique worker directories, separate bounded LLM/fit/metric queues, resumable immutable stages and measured CPU/RAM/time limits.

Gate: failure injection proves no collisions, no stale cache reuse, bounded growth and clean cancellation.

## Completion boundary

This plan is not complete until source-only checkouts become reproducible environments, the baseline is locally reconciled, one frozen experiment has a verdict, the read-only UI is rendered and tested, setup docs pass, and every unsupported claim is explicitly withheld. Major runtime acceptance remains subject to the workspace's future-scheduled execution and configured-owner email contract.
