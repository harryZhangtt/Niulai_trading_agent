# Weekly winners/losers thesis review

Version: 2026-10-18-weekly-review-1. Apply the installed financial-services adapter, growth-aware policy and leveraged-funds policy. This is a review and proposed allocation workflow; it does not execute trades or alter alerts, holdings or thesis membership automatically. BAT means the proposed bet/position action in this workflow, pending clarification if Harry intended another metric.

## 1. Freeze the work identity and rank

- Read the latest saved research database and configuration, preserve their retained versions, and freeze a run manifest: `run_id`, universe IDs/revision, config revision, research input revision, actual skill commit/policy versions, price source, adjustment convention, price cutoff, evidence cutoff and prior completed review ID.
- Universe: the 37 currently catalogued US-listed research securities, including the nine context-only names; read actual membership rather than hard-code the count. Do not silently expand to the alert-only universe. Keep ETFs and leveraged funds identified in the same requested ranking, then use their correct review branch.
- Use the last **completed exchange trading week**, identified by the XNYS calendar, even when the job runs after a holiday. Weekly return is adjusted-close total return from the previous week's last session to this week's last session, with consistent split/distribution handling. A four-day week still compares its two proper week-end closes. Do not substitute intraday quotes, forward-fill stale closes, or treat missing returns as zero.
- Let `N` be names with both valid closes and valid adjustment metadata; choose `k = ceil(0.20 × N)` from each tail, capped to keep tails disjoint. At full 37-name coverage this is eight winners and eight losers. Sort by return, break exact ties by canonical security ID, and retain all ranks and unselected members for audit. Excluded names and reasons remain visible. A very incomplete universe makes selection provisional, not representative.
- Freeze prices at the final completed session close. Freeze the evidence cutoff separately at actual run start; label material after-close evidence explicitly because the ranked close has not incorporated it. Never present a backtest as if those later facts were available at the historical decision time.
- Price moves choose review priority. They are not evidence that a thesis improved or deteriorated. A material independently observed thesis-break event outside the tails can be a separately labeled exception, never a covert ranking change.

## 2. Load the actual prior thesis

For every selected security, locate its latest applicable dated section and exact artifact ID/version/pages. Resolve superseded cumulative-report sections; a filename is not a thesis date. Extract thesis pillars, falsification conditions, valuation cutoff, assumptions, scenario probabilities and their basis, entry/required-return rules, prior BAT and dated holdings basis. Preserve older conclusions as history.

Distinguish:

- `existing_thesis`: prior security-specific thesis is readable and attributable;
- `context_only`: mentioned/catalogued without a security-specific underwriting;
- `baseline_unavailable`: an artifact exists but cannot be read reliably;
- `model_available` / `reconstructable` / `model_unavailable`: machine-readable model completeness, independently of whether prose exists.

For context-only names, establish a first-pass research question and evidence map; do not invent a prior opinion or claim an EV change. For unavailable baselines, report the gap and preserve the source reference for recovery.

## 3. Search for both supporting and opposing evidence

- Search from each prior thesis's actual evidence cutoff through this run's evidence cutoff, not merely the last seven days. If the cutoff is unknown, say so and use a disclosed catch-up interval. Review missed periods after failed jobs.
- Prioritize filed financial statements/8-Ks, issuer earnings releases and product disclosures, customer or supplier disclosures, official regulatory/legal records, and primary technical research where relevant. Separate reported facts, management targets, dated accessible consensus and analyst inference. Secondary reports can flag a lead; material model changes require verified primary support or a clearly identified unresolved claim.
- Check both sides of each material pillar: adoption and monetization; pricing/mix and competition; margins/SBC/reinvestment; financing/equity claims; cycle/supply additions; execution and regulation. Do not assume workload growth equals vendor profit growth, or that a public narrative is unrealized alpha.
- Store source URL, title, publication time (null if unknown), retrieval time, reporting period, passage locator, summary, claim IDs and source type. Deduplicate by normalized source identity plus filing/event/period and claim. Multiple articles repeating one announcement are one event; republication is not new evidence. Preserve corrections as revisions rather than deleting the old claim.
- For each evidence item state `supports`, `opposes`, `mixed` or `not_material`, the thesis pillar, mechanism, expected financial magnitude/range, and whether it is new since the baseline. Absence of discovered evidence is not proof that nothing changed; report search coverage and gaps.
- Conclude `stronger`, `unchanged_within_checked_scope`, `weaker`, `broken`, `mixed` or `insufficient_evidence`. Name the observation that would next change the decision. Record an existing thesis as broken only against its actual conditions or a documented new fatal condition.

## 4. Recalculate EV only through an auditable model

Model availability is a hard numeric gate. A PDF price target alone is not a model. Reconstruct only if cash-flow/terminal assumptions, horizon and timing, capital/equity bridge, scenario definitions, probabilities and distribution policy can be recovered and reconciled to the published result within stated rounding tolerance. Otherwise publish `not_recalculated_missing_inputs`, identify missing inputs, give qualitative direction and request a model-recovery task. Never label unrecomputed EV “unchanged.”

With a usable model, preserve a frozen baseline and calculate this fixed-order bridge, holding other input families constant at each step:

1. **Price and time only:** apply the new investable price, distribution/corporate-action history and shorter horizon to the old operating paths and old weights. Report changes in expected return/entry gap separately from the thesis. A price decline can improve entry economics without improving fair value.
2. **New fundamentals:** update evidenced revenue, margins, reinvestment, financing and equity claims. Show each material input family and avoid counting the same event twice.
3. **Model correction:** repair identified arithmetic, accounting, timing or structural mistakes and quantify the effect. This is a correction to our prior work, not alpha generated by new industry evidence.
4. **Investment judgment:** change duration, fade, terminal economics, risk parameters or scenario weights only with a documented rationale. Report its effect separately. Fixed-order bridge terms sum to the full change; disclose order dependence/interactions and use sensitivities for material correlated changes.

Report fair value separately from current-price expected investor wealth/return and hurdle-based entry price. Keep the original horizon/end date explicit; a rolling-horizon model requires a labeled roll-forward bridge. State whether “EV” is probability-weighted terminal wealth, expected net profit, IRR of expected cash flows or another named metric. Do not equate `CAGR(E[wealth])`, `E[CAGR]` and expected log growth. For stocks, apply consistent FCFF/WACC or FCFE/equity returns, one SBC treatment and one cash distribution policy. For cyclical businesses, use through-cycle evidence rather than extrapolating peak/trough EPS.

Every scenario weight carries `historical_frequency`, `calibrated_model` or `analyst_judgment`, its calibration/source cutoff and uncertainty. Weights sum to one; infeasible reverse solutions stay infeasible. Price changes do not automatically change physical probabilities. Missing calibration implies sensitivity ranges, not falsely precise odds. Apply the adapter's large-gap diagnostic if central fair value is below half or above twice market price. State public baseline, variant perception, profit mechanism and falsifier before claiming an unrealized edge.

### Leveraged-fund branch, including SOXL

Use the current issuer-verified benchmark/reset/fee structure, never “three times SOXX” by assumption. Historical fund NAV/adjusted returns already include realized costs. Forward linear-reset paths use `product(1 + L_t × r_t − c_t)` with dated funding assumptions, costs once, zero-barrier and actual reset conventions. A one-week realized path can be measured; it cannot identify the future distribution.

Retain smooth bull, volatile bull, chop, persistent decline, crash/V recovery and delayed recovery scenarios, with jointly calibrated trend/variation/cost uncertainty where possible. Freeze ex-ante matching conditions; disclose overlapping samples and independent episodes. If no defensible present-state probabilities exist, present conditional outcomes and break-even conditions rather than precise current EV. Report skew, median/log wealth, drawdown/loss tails and unlevered comparison as well as arithmetic EV; do not let an optimistic rare tail alone determine BAT.

## 5. Translate to BAT without inventing an account

- Keep business/thesis quality, valuation/entry quality and portfolio fit separate. Recommend `add_candidate`, `hold`, `wait`, `reduce_candidate`, `exit_candidate` or `research_only`, with a price/benchmark or fundamental condition and invalidation.
- Read the latest authorized holdings snapshot and its as-of time. Do not interpret an earlier proposed allocation as an executed holding. If holdings, NAV, cash or correlated exposure are stale/missing, give a conditional target range and risk-budget illustration rather than an exact personal order or a claimed current weight.
- Show current/proposed weight when verified, incremental portfolio downside under a common stress, concentration/correlation and the reason for a size change. Respect Harry's stated preference for up to 4% SOXL when EV is not materially different, but do not force a 4% answer when model uncertainty or risk evidence changes; quantify the disagreement. Savings capacity affects loss capacity, not the asset's expected return.
- An EV bridge may justify no action despite a large weekly price move. No automatic trade, alert rewrite or holdings mutation is authorized by this review.

## 6. Required result and persistence

Publish a short Chinese weekly digest: ranking dates/coverage, selected winners and losers, material thesis changes, model-ready EV bridges, BAT changes and next evidence checks. Separate a failed quote/model/evidence task from a quiet result. Include favorable and unfavorable findings even when the final decision is unchanged.

Each selected name has one summary row, with detailed source/model records linked rather than crammed into the table:

| Field | Required meaning |
|---|---|
| security_id, ticker, instrument_type | Stable identity; fund leverage/reset label where relevant |
| tail, rank, weekly_return, price_as_of | Actual selection and matched return convention |
| prior_thesis_ref, prior_cutoff, baseline_status | Exact artifact/section/version and known coverage |
| thesis_status, favorable_evidence_ids, unfavorable_evidence_ids | Pillar changes, including mixed/insufficient cases |
| model_status, model_hash, metric_definition, horizon | Numeric gate and reproducible EV definition |
| old_EV, price_only_EV, fundamental_EV, corrected_EV, revised_EV | Nullable exact-stage bridge; missing values have reasons |
| prior_entry_range, revised_entry_range, BAT, BAT_conditions | Required return and conditional action |
| holdings_as_of, prior_verified_weight, proposed_weight_range | Nullable account basis; never proposed-as-executed |
| confidence_basis, evidence_gaps, next_check | Uncertainty, falsification and follow-up |

Use SQL evidence/model-revision tables and an immutable final job-run record where supported. Retain input and output hashes, model/code policy versions, calculation checks, coverage failures and exact saved artifact references. A stable idempotency key contains task kind + week-end session + frozen universe/config/input/skill revisions. Reuse unfinished matching work; never overwrite a completed run or its old report. Explicit revised runs point to the superseded result. Persist checkpoints after ranking, evidence collection and model computation so interruption does not erase completed work.

Before publication reread expected research/config/artifact versions. On concurrent changes reject stale writes, reconcile the new baseline and rerun affected calculations; do not publish an old-input result as current. Confirm saved file/database versions before marking `published`. Track evaluation, persistence and notification delivery separately; a completed analysis is not proof of device receipt. Save reports and JSON/database updates through retained-version guards, leaving private account data out of the Skills repository.

## Decision tree

1. Are both return endpoints valid? **No:** exclude from rank with a coverage failure. **Yes:** rank the frozen universe and select the tails.
2. Is a prior security-specific thesis readable? **No:** `context_only` or `baseline_unavailable`; establish/recover the baseline without inventing past opinions. **Yes:** compare pillars against new evidence.
3. Is a validated reproducible valuation model available? **No:** qualitative thesis/BAT review with missing-input status; no numeric EV claim. **Yes:** run the four-stage bridge and diagnostics.
4. Are probabilities defensible and account inputs current? **No:** conditional scenarios/target ranges, explicit missing-data limits. **Yes:** quantify EV, stress loss and proposed position change.
5. Do revision guards and persistence succeed? **No:** retain draft/partial status and checkpoint. **Yes:** publish the reviewed digest and record the native notification outcome separately.


## All-selected completion requirement

Apply [TaskQ production completion and continuation gate](task-queue.md#production-completion-and-continuation-gate) on every run. Bounded batches limit simultaneous workers, not selected coverage. The parent must continue every selected ticker and repair fixable partials; a completed worker attempt, three pilot tickers, or a saved checkpoint does not finish the research run. Reuse the full research harness and independently reviewed evidence/model artifacts. Return complete only after all expected names pass their applicable decision and persistence/readback gates; supported no-buy/hold decisions are valid. Irreducible external blockers stay explicitly blocked with actual recovery-attempt evidence, never fabricated certainty. Preserve unfinished work across interruptions and resume it.
