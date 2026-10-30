# Options model selection and stress review

Additive policy **2026-10-24-options-model-selection-1**. Reuse the equity-options policy, underlying thesis, normalized source packet and existing review. Do not install a collection of competing stacks or imply that model complexity supplies missing information.

## Select the smallest adequate calculation

| Decision question | Implemented route | Required boundary |
|---|---|---|
| Cost, break-even, maximum loss and expiration payoff | `options_payoff_checks.py`, Decimal | OCC symbol/date/right/strike binding; verified deliverable for actionable output; fees and cash separate |
| Local theta/vega and conditional spot/time/IV moves | `options_scenario_checks.py`, stdlib BSM | European continuous-carry assumptions; full repricing for large moves, no probability inferred from delta |
| Early exercise or discrete cash dividends | `options_american_checks.py`, optional QuantLib **1.44** | Pinned dependency, date-level ACT/365F, doubling-grid convergence, European/intrinsic checks; no intraday-expiry support |
| Strike/expiry inconsistency and interpolation uncertainty | `options_surface_checks.py` | Bid/mid/ask IV intervals; forward log-moneyness and total variance; common support only; preserve rejected nodes and failed sampled checks |
| Whether volatility premium is unusually expensive | Adjusted-return RV and a dated IV history, if available | Align horizons/definitions; separate event jumps, window sensitivity and physical versus risk-neutral expectations; no IV rank without IV history |
| Event jump, IV crush, delayed catalyst or adverse liquidity | Explicit conditional scenario grid | State event date/source, shocked stock/IV/date, purchase side and exit-cost assumption; do not invent probability weights |

Install the optional American engine only with `python -m pip install -r references/niulai-workflow/requirements-options-american.txt` from the skill root, then run its adjacent test suite. Import is lazy; an absent or mismatched version blocks that route with a specific error rather than silently switching to European pricing. The adapter supports American/European calls and puts, flat continuous rates/yields or an explicit discrete cash-dividend schedule with zero continuous yield. It restores QuantLib's evaluation date; use serial calls or separate processes, not shared QuantLib objects across threads.

The American adapter returns model values per share. To show a trade P&L, compare the scenario liquidation value with the actual saved purchase debit, multiply by the verified deliverable/quantity, and subtract applicable fees and exit slippage. Its `model_value_change_per_share` is a model-to-model change, not a realized trade return. A scenario label such as “event jump” is a conditional shocked state; it is not a calibrated jump-diffusion process. Large moves must be repriced rather than multiplying local Greeks by the shock.

## Review complicated situations explicitly

Use a small, decision-relevant grid: favorable/adverse stock move, rapid/slow/no catalyst realization, IV rise/crush, skew change by leg, and wider exit bid/ask. Include a joint adverse case. For a debit spread, reprice each leg separately and compute the signed package; a short leg reduces some exposures but caps upside and introduces assignment/funding risks. Conservative package closing uses long bid minus short ask, not two midpoints. Do not describe a theoretical surface value as an executable exit.

For event-sensitive trades, avoid double-counting an event jump in both an inflated continuous volatility and a separate jump distribution. If timing/probability is unknown, report conditional outcomes and break-even conditions rather than an invented expected value. Include loss of the full debit and an explicit pre-expiry exit/funding plan. The current numerical topology supports standard long calls and bull-call debit spreads, not an arbitrary strategy generator. Unsupported structures require their own reviewed payoff/exercise logic.

## Surface discipline

The implemented surface is a piecewise-linear **total-variance diagnostic**, not SVI calibration, local volatility or an American volatility surface. It reports observed-node and interpolated strike convexity checks, sampled calendar checks and interior-strike holdouts. It never certifies global absence of arbitrage. A low interpolation error is not out-of-time prediction skill. Unknown quote timestamps, American exercise, assumed carry/spot or failed checks keep valuation approval false. Preserve the raw inputs, excluded nodes and failure output; do not smooth them away to make a chart attractive.

Use Gatheral–Jacquier's [arbitrage-free SVI paper](https://arxiv.org/abs/1204.0646) and [author's SSVI notebook](https://github.com/JackJacquier/SSVI) as methodological references. They are not installed calibration dependencies. Require adequate synchronized data, suitable exercise treatment, holdouts, parameter stability and explicit calibration errors before adding constrained SSVI. Heston/local-vol/Bates/Monte Carlo are candidates only when a decision depends on their additional dynamics and identifiable parameters exist. They require seed/error or grid convergence, simpler-model benchmarks and out-of-sample checks; no automatic escalation when basic data fail.

## Enforcement and error attribution

The options completion validator binds contract terms, recomputed payoff/scenario artifacts, code hashes, source crosschecks, visible payoff chart and independent findings. Its model-selection extension records the analytical-equivalence or American-FD route and any surface use; declared advanced calculations must be reproduced and bound to the selected contracts/inputs. An unsupported model choice or omitted applicable evidence cannot pass by writing “reviewed”. A sourced no-dividend call equivalence can avoid a heavier engine when its assumptions hold; a generic claim that American exercise is unimportant cannot.

Keep historical illustration and actionable completion separate. Record errors by contract identity, source normalization, clock, units, computation, underlying path, timing, IV/skew, fill/slippage and model selection. Reuse frozen inputs and failed candidates in the existing forecast ledger. Tests establish behavior on tested cases, not accurate future probabilities, authentic quotes, fills or profitability.

## Professional dependencies reviewed

- [QuantLib](https://github.com/lballabio/QuantLib), BSD-3-Clause: **1.44 installed and adapter-tested on 2026-10-24**; [official American test suite](https://github.com/lballabio/QuantLib/blob/v1.44/test-suite/americanoption.cpp), [release](https://github.com/lballabio/QuantLib/releases/tag/v1.44). Numerical engine, not a market-data source.
- [vollib](https://vollib.org/), MIT: reviewed European Black/BSM IV/Greeks alternative; **not installed or used here**. Existing stdlib BSM plus the independently implemented QuantLib comparison avoids another runtime dependency.
- [Alpaca official MCP](https://github.com/alpacahq/alpaca-mcp-server) and [Tradier official MCP](https://tradier.com/develop/mcp-server): data-access candidates, **not authenticated connections in this run**. Require secure credentials, entitlements and read-only tool allowlists. Free indicative data are not executable OPRA quotes; an MCP wrapper is not a pricing model.

No new service, database, sender or trading capability is required by this extension.

## Pathway extension

For simulated stock pathways, probability of profit/loss and visual case replay, use [Options paths, probabilities and case replay](options-path-probability.md). This adds seeded physical-assumption GBM and optional stationary-bootstrap diagnostics with the existing payoff packet. It does not supply calibrated trade probabilities or convert the European surface into a physical forecasting model. Preserve failed historical calibration checks and use the path-review completion binding.
