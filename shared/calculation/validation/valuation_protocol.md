# Valuation validation protocol — frozen before target execution

Version: 2026-10-31-valuation-validation-1. Target: the copied candidate only.
No source calculator, production workflow, credential store or private account
sample may be changed/read for this campaign. No target execution has occurred
when this protocol is first written. A subsequent protocol change is a new trial
and must preserve prior evidence.

Decision: identify supported arithmetic failures and numerical/context risks;
do not certify forecasts, calibrated probabilities, investment alpha or fair value.
The public live-retrieved sample is Microsoft FY2026 issuer/SEC financial data;
the two publications reflect the same reporting origin, not independent estimates.
CFO less cash additions to PP&E is a cash-flow proxy, explicitly not FCFF.
Any discount rate/terminal growth/ROIC/forecast is a declared test assumption.

## Frozen checks

- Use independent `fractions.Fraction` rational oracles and an 80-digit local
  Decimal conversion. Compare Decimal arithmetic by `abs(actual-reference) <=
  max(1e-18, abs(reference)*1e-24)` under the declared default 28-digit context.
  No float conversion is allowed in the oracle/comparison for Decimal outputs.
- Cover PV with positive, negative and zero cashflows and rates -0.75..1.00;
  terms 1..1000; cashflow magnitudes 1e-8..1e15. Annuity references use the
  closed form rather than the target loop. Cover WACC weights/tax and zero debt,
  terminal FCFF/reinvestment and near g=WACC, enterprise/equity/nonoperating
  asset discounting, per-share scaling and weighted expected wealth.
- Deterministic generated cases use seed 20261031 and retain counterexamples.
  Require every ordinary declared-domain case to match, finite output or a
  documented unsupported rejection; silently incorrect/nonfinite values fail.
- Test metamorhic properties: PV linearity and rate monotonicity for positive
  cashflows, WACC financing scale invariance, equity/share scaling, weighted EV
  permutation invariance, holdings net/gross and NAV residual reconciliation.
- Separate finite stress from ordinary domain: cancellation with mixed signs
  and widely separated magnitudes; 1000-term accumulation; large/small values;
  rounding ties; rate close to -1; terminal rate/growth close separation.
  Failures beyond a documented target domain are unsupported rather than wrong.
  Where a target only declares finite inputs and no magnitude limit, record
  finite-stress failures explicitly without inventing a retroactive limit.
- Ambient context probes use precision 6/28/50 and ROUND_HALF_EVEN/ROUND_DOWN.
  Run under a restored local context. If results change beyond the tolerance,
  report context dependence separately from default-context arithmetic accuracy.
- Reject invalid/nonfinite inputs and illegal denominators. Expected rejected
  cases must raise a controlled numeric/value/type error or return the legacy
  documented unknown/blocked result; no nonfinite output may masquerade as valid.
  Assert-based validation is separately probed under Python `-O`; if rejection
  disappears, record an optimization safety defect, not a fixed implementation.
- One bounded synthetic workload each: <=10000 positions and <=1000 DCF terms.
  Record elapsed time; 5 seconds per case is an exploratory resource budget,
  not a platform SLA or a numerical pass criterion.

## Evidence and acceptance

Acquisition is separate: public HTTPS allowlisted issuer sources only, bounded
response size/time, no account data, no credentials or arbitrary model-supplied
URLs. Save source URL, retrieval/as-of, response hash and exact transformations.
The evaluation `run(output_dir, sample_path=None)` is network-free and consumes
a hash-bound public sample; generated artifacts remain below the workspace's
`.job-runtime/calculation/validation/`.

Retain every actual failed case and observed value, with a minimal fix suggestion.
Do not edit the preserved legacy implementations or relax thresholds to pass.
Each return is structured with counts, findings, modules exercised and evidence.
The root coordinator independently reviews the report and owns the future timed
Codex run plus exact result-email verification. Shell execution alone is not
scheduled acceptance. Missing or failed evidence remains visible.
