# Options numerical validation protocol v1

Frozen before target evaluation on 2026-10-31. This is development evidence for
the inactive copied calculators, not production or model-calibration approval.
No target source or original Niulai source may be edited by this validator.

## Independent references and numeric criteria

- European BSM: an independent mpmath 80-decimal implementation of the analytic
  formula and analytic Greeks. Prices use absolute error <= max(1e-9,
  3e-14*max(spot,strike)); central Greek checks use absolute <=1e-9 plus relative
  <=2e-8. Re-evaluate selected references at 120 digits to verify convergence;
  mpmath is a high-precision reference, not a formal interval proof.
- Standard grid: spot/strike scales .01, 1, 100, 10000; moneyness .5,.9,1,1.1,2;
  time 1/365, .25, 1, 10; volatility .03,.2,1,3; rates -.05,0,.05 and yields
  0,.02,.2 sampled deterministically. Both puts and calls. Boundary grid also
  exercises short maturity, very low/high volatility, zero expiry and extreme
  supported price scales. Boundary underflow below price tolerance is acceptable.
- IV: independent high-precision bisection, premium repricing error <=max(1e-8,
  1e-10*premium). Volatility roundtrip error <=2e-6 only for declared
  identifiable cases: positive T, vega per unit sigma >1e-5 and time value
  >1e-7. Near-flat inversions must be reported as ill-conditioned; numerical IV
  agreement is not evidence of measured zero volatility or forecast calibration.
- Metamorphic checks: put-call parity and linear homogeneity use the price
  tolerance above, positive option bounds and vega/gamma where applicable,
  reject nonfinite/Boolean inputs, and preserve exact expiry payoff behavior.
- American/date-level adapter: use independent Python Cox-Ross-Rubinstein trees
  at 800 and 1600 steps; compare adapter fine-grid price to the averaged adjacent
  1599/1600-step CRR reference within .02 USD/share. Require CRR adjacent-grid
  sensitivity <=.02. This bounds approximation disagreement; it is not a proof
  for discrete dividends. For nondividend calls with nonnegative rates, compare
  against independent analytic European price within .005 USD/share. Preserve
  QuantLib date state; reject malformed terms and double-counted dividends.
- Surfaces: build nodes from the independent analytic reference, verify IV/node
  recovery, bracket-only interpolation and absence of extrapolation. Detect
  intentionally increasing call prices, invalid vertical spreads, negative
  butterflies and decreasing total variance. No sampled result may claim global
  arbitrage freedom, executable fair value or physical probability.

## Public sample and source separation

Acquisition happens separately from run(). An exploratory GET to Cboe's public
delayed AAPL chain selects up to 12 nonexpired, positive, uncrossed near-ATM
contracts across two expiry dates. Retain source URL, retrieval UTC, exact raw
provider timestamp (timezone remains unknown if not declared), raw response hash,
bounded selected fields and deterministic transform lineage. No account state,
credentials or private portfolio files are inputs; no source content is code.
Market spot/strikes/terms form real-data input scales and quote sanity checks.
American market premiums are NOT a European BSM mathematical oracle; provider
Greeks and IV with unspecified conventions are recorded rather than certified.

run(output_dir, sample_path=None) is offline. It consumes the saved public capture
and synthetic cases, writes sanitized structured evidence under its own output
directory, and never fetches or reads credentials. Missing public capture or
optional dependencies is unverified coverage, not a pass. Freshly retrieved
delayed market data is labeled by its provider as-of, not realtime.

## Bounds and acceptance

Use deterministic bounded grids and at most 12 market cases; no exhaustive
combinatorial surfaces or production sends. Record elapsed time, case counts,
dependency versions, maximum errors, every failure and skipped path. Do not relax
tolerances or silently exclude failures after inspecting results. Root owns any
fix decision, new candidate version, subsequent scheduled Codex verification and
verified owner result email. Shell checks alone do not establish that acceptance.

Primary sources read: Cboe AAPL delayed dashboard
(https://www.cboe.com/delayed_quotes/aapl/quote_table/), OIC option-pricing and
parity discussion (https://www.optionseducation.org/videolibrary/put-call-parity),
and QuantLib's build/test documentation
(https://www.quantlib.org/install/cmake.shtml). Native search and source opening
worked. Public-source conventions and model assumptions remain explicit.
