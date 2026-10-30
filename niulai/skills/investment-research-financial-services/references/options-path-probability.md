# Options paths, probabilities and case replay

Policy **2026-10-24-options-path-1** supplements the options model-selection policy. A profitable company thesis is not a probability distribution for its stock before expiry. Use the smallest useful path model, disclose its assumptions and retain rejected forecasts.

## Two implemented physical-assumption routes

`options_path_checks.py` reuses the exact normalized payoff packet, costs, OCC terms and budget. It supports:

1. **GBM sensitivity:** explicit arithmetic SDE drift and volatility, seeded NumPy paths. The drift mu in dS/S = mu dt + sigma dW implies expected gross growth exp(mu T), not a simple annual return equal to mu. Log increments include the −sigma²/2 term. State the trading-time clock; do not confuse 252 trading steps with 365 calendar days.
2. **Stationary block bootstrap:** optional pinned `arch==8.0.0`, reusing [Kevin Sheppard's maintained implementation](https://github.com/bashtage/arch) rather than copying an unreviewed investment notebook. Historical log-return blocks retain some local dependence. Freeze block length before evaluation; compare a small stated set rather than selecting the best historical result. Raw empirical drift and recentered marginal drift are distinct routes. Recentered one-step expected returns do not imply the same multi-step mean under dependent blocks.

Neither route is automatically calibrated. Historical blocks assume a sufficiently stable distribution and cannot invent shocks absent from the sample. GBM has restrictive constant-volatility/lognormal assumptions. No risk-neutral pricing probability may be relabeled as a physical probability of investment profit. More simulated paths reduce Monte Carlo error, not regime, parameter or model error.

## Required probability output

Report probability of positive net expiration P&L, loss of at least half the opening debit, loss of the entire debit, P&L percentiles/mean and same-budget shares/cash. State exact integer contract counts and idle cash; one contract and maximum affordable contracts are different comparisons. Probability of touching the expiration break-even before expiry is not probability of finishing profitable, and daily-close samples miss intraday touches. Cash-equivalent expiration payoff does not remove exercise funding or spread assignment risks.

Show Monte Carlo sampling intervals separately from the range across model/drift/volatility/block assumptions. Do not average models or attach probabilities to narrative scenarios without an evidence-backed weighting rule. Report tail sensitivity and failure cases, not only the highest simulated expected value. A probability with narrow simulation error but poor historical calibration remains weak decision evidence.

## Lightweight historical evaluation

Use chronological rolling origins and only pre-origin observations for fitting. Freeze the full eligible cohort, event definition, horizon and baseline. Primary results use nonoverlapping target windows where feasible; overlapping diagnostics are labeled dependent. Compare Brier score for direction/profit events, log score when supported and interval coverage/width against simple baselines. Preserve failures, abstentions and unavailable outcomes. One retrieved revised history is a retrospective pseudo-out-of-sample experiment, not a genuine archived-vintage trading backtest.

The CRWV October24 diagnostic has only nine nonoverlapping 20-session test windows. It tests underlying stock forecasts, not option returns: historical option chains/fills are missing. Its bootstrap direction forecasts underperformed a 50/50 baseline, and nominal90% bands covered7/9 outcomes. These results do not validate six-month option-profit probabilities. Do not tune the method until this small sample looks successful; preserve the failure and require more genuinely frozen evidence before promoting predictive claims.

## Required visual replay

Include a stock-path fan chart with its probability basis and cutoff, a strategy outcome/probability comparison, and a paired case replay using identical stock paths for shares/call/spread. Label path selection in advance (for example, fixed seed IDs), quantities, cash and costs. A pointwise percentile fan is not one realizable trajectory or a simultaneous confidence band. Keep historical observed paths separate from simulated futures. If option quote history is absent, show endpoint payoff or explicitly modeled intermediate values, never an alleged realized option backtest. First-touch markers must not imply an executable exit.

The `model_selection.path_review` gate records either conditional scenarios with no numerical-probability claim, or linked reproducible simulated paths and replay evidence. Declared simulation results bind exact inputs, method hashes, costs, cutoff and independent review. Simulation cannot clear failed quote, contract or medium-term thesis gates. An unsupported advanced method fails its own route; useful historical diagnostics remain available.

## Primary foundations and dependency boundary

- [StationaryBootstrap API](https://bashtage.github.io/arch/bootstrap/generated/arch.bootstrap.StationaryBootstrap.html): Politis–Romano stationary bootstrap; seeded reproducibility and random block lengths. The installed package retains its upstream license; no source code is vendored into this skill.
- [Block-length methodology](https://bashtage.github.io/arch/bootstrap/generated/arch.bootstrap.optimal_block_length.html): Politis–White2004 and Patton–Politis–White2009 correction. Training-only selection is necessary; automated block choice is not proof of investment predictability.
- [Gneiting and Raftery2007](https://sites.stat.washington.edu/raftery/Research/PDF/Gneiting2007jasa.pdf): proper scoring rules evaluate probabilistic forecasts and encourage honest distributions. Use these scores for comparison, not to infer reliable calibration from a handful of outcomes.

No heavy stochastic-volatility calibration, new market-data service or trading endpoint is introduced. Existing optional QuantLib handles exercise-sensitive valuation; physical stock simulation and risk-neutral valuation remain separate layers.
