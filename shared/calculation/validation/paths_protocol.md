# Frozen paths/replay validation protocol

Protocol ID: paths-v1, 2026-10-31. Scope is copied `leveraged_funds`,
`entry_policy_ev`, `options_decision_bounds`, `options_path_checks`,
`cycle_checks` and `cycle_vintage_checks`. No production imports or original
source are modified. This protocol is fixed before target calculation runs.

The claim tested is arithmetic and contract consistency in these stated cases,
not calibrated probabilities, executable fills, predictive skill or alpha.
Offline calculation receives only bounded public/synthetic inputs. Public data
acquisition is separate, unauthenticated, read-only and performed before testing;
no private account data, credentials or source files are transmitted. Raw public
samples and receipts stay under `.job-runtime/calculation/validation/paths/`.

## Cases and acceptance rules

- Compounding/reset/mix: compare fixed-seed finite decimal input cases against
  100-digit Decimal/Fraction arithmetic; use absolute error <= 1e-12 plus
  relative error <= 2e-11 for accumulated wealth/drawdown. Equivalent statement
  is `abs(actual-reference) <= 1e-12 + 2e-11*abs(reference)`. Input permutations
  apply only to terminal compounding, not path-dependent drawdown. Zero and
  absorbing loss are tested separately. Workload stress is <=100,000 resets.
- Extreme positive exact wealth: finite input paths with no -100% return must
  not silently become mathematical ruin because of binary underflow. A clear
  numerical-domain rejection is acceptable; silently labeling loss as exact
  ruin is a failure. Overflow may reject rather than return nonfinite success.
- Weighted quantile: declared left inverse of the weighted empirical CDF must
  agree with exact rational cumulative weights on ordinary and near-boundary
  probabilities, including zero weights. This is a discrete identity and uses
  exact selected value equality, not an approximate numeric-value tolerance.
- Tail mean: compare exact rational partial mass integration including tail
  masses 0.05, 1, and 1e-15 and zero-weight observations. Error tolerance is
  1e-12 + 2e-11*abs(reference); zero weights cannot change the result.
- Probability-simplex bounds: independent enumeration of vertices for 2..5
  states, not the target's greedy allocation, must match Decimal bounds to
  absolute 1e-24. Weights must remain within declared intervals and sum to one.
  Test infeasible, nonfinite and mismatched vectors as rejection cases. A
  5,000-state bounded stress checks finite feasibility and ordering only.
- Supplied-case entry replay: a separately specified 3-path no-fee/no-carry
  cash/share ledger has exact hand-calculated outcomes. Future observations may
  change terminal wealth but never earlier decisions. Costs/carry receive
  explicit hand checks; unknown probabilities cannot yield fabricated EV.
- Vintage replay: future releases cannot change the selected-view hash;
  timestamp-equivalent orderings must match; missing and pending inputs must
  stay explicit; mismatched units and conflicting identities must reject.
- Cycle arithmetic: a minimal supplied supply/demand case has exact rational
  growth/balance values. Unit/scope and future-availability errors must reject.
  This is not an independent economic truth verification of assumptions.
- GBM: sigma=0 paths must equal analytic `S0*exp(mu*T)` to rel 2e-11/abs1e-10;
  identical seed repeats must be identical. For fixed seeds 314159/271828,
  5,000 paths with fixed moderate mu/sigma must have terminal mean within six
  analytic Monte Carlo standard errors and sample log variance within 12% of
  sigma^2*T. Max payload <=5 million path-steps; over-budget and lookahead must
  reject before allocation/simulation. These stochastic tests do not validate
  market calibration; fixed-seed tests are development evidence, not holdouts.
- Stationary bootstrap: fixed seed must repeat exactly, constant historical log
  returns must yield their analytic deterministic terminal price; future or
  missing-history dates must reject. Optional dependencies missing => skipped,
  never passed. Public sample arithmetic uses price-index level ratios, no
  invented dividends or current-tick claim; sample/bootstrap extent is reported.

## Public facts and outcome reporting

Prefer a fresh, bounded official FRED daily-close SP500 retrieval plus official
series metadata. It is a price index without dividends, and its last available
date is not necessarily the latest trading day. Cross-check stated dates/levels
between CSV and visible source when available. A current retrieval of historical
daily observations is labeled `fresh_retrieval_historical_daily_close`.
If CSV acquisition fails, preserve the failure; a short primary-page sample may
still test telescoping, while historical bootstrap remains synthetic and labeled.

Every case reports passed/failed/skipped and reference/actual/error where useful.
Do not alter criteria after results or turn a failure into an expected pass.
Failures remain evidence and require a separately reviewed correction. Do not
claim full16-module coverage. Root owns scheduled Codex acceptance and the
verified owner result email; shell execution alone does not satisfy that gate.
