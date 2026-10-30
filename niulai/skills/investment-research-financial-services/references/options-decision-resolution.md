# Resolve an options decision before declaring a gap

Policy **2026-10-24-options-resolution-1** adds remedies to the current payoff, American-engine, surface and path workflow. It does not replace their evidence gates. Never turn a methodological success into trade approval.

## Make the unresolved question answerable

| Report gap | Active next operation | What resolves it / safe fallback |
|---|---|---|
| Per-contract quote clocks, sizes, synchronized stock | Capture an entitled consolidated snapshot for exact symbols; compare second source within time/skew limits; retain raw payload | Matched timestamps/feed/sides/units/sizes, or a precise authentication/session blocker; retrieval time is never quote time |
| Quote origin $54.07 ask vs $54.24 close | Keep both provenance records; rebuild all candidate calculations on one synchronized observation for a new live decision | Diagnostic may retain labeled anchors; do not relabel ask as official close |
| Standard or adjusted deliverable | Query exact series through OCC/broker contract detail and inspect adjustment memos | Verified exact multiplier, shares/cash basket and adjustment status; a generic standard100 rule is not exact-contract proof |
| Dividend assumption | Read latest issuer filing and recent corporate actions, then rate/discrete-dividend sensitivity | Source-backed base assumption with explicit future uncertainty, rather than repeatedly saying company facts are unavailable |
| Carry/rate/borrow | Match Treasury/OIS horizon and compounding convention; query broker borrow only if relevant to shortstock/assignment | Modeling rate differs from investor cash yield, company debt cost and stock borrow; stress all material terms |
| Catalyst and date | Recover baseline, latest filing/IR calendar; verify date and determine the actual signpost changing capacity, margins, financing or dilution before expiry | Date verified or a dated range; no-news search is not unchanged fundamentals; five-year value is not six-month target |
| Physical path probabilities | Freeze hypotheses, condition on event regimes, compare simple benchmarks prospectively; retain failures and uncertain intervals | An assumption-bound decision may be usable; small retrospective samples cannot produce certified six-month probabilities |
| Highest acceptable debit | Recalculate cost limit across declared scenario/probability intervals; include fees, closing friction, hurdle and model reserve | Exact input-bound limits and the assumption where decision flips, not an unsupported single target |
| IV too expensive? | Compare price of event exposure with thesis-specific path range, IV term/skew and bid/ask IV intervals; stress IVcrush and delays | Quantify whether edge survives plausible return/volatility assumptions; high absolute IV alone is insufficient |
| Surface midpoint convexity failure | First synchronize/filter quotes and check bid/ask interval feasibility; account for American exercise/dividends before European constraints | If no feasible surface, reject valuation use. Do not “fix” by smoothing until fit looks good |
| Incomplete forward-IV history | Start a licensed timestamped archive, retain ATM/constantmaturity definitions and changes; historical licensed data only where authorized | No fabricated IVrank; use strike IV ranges and conditional stress now |
| Exit liquidity/fees | Exact legs, package bid/ask, quantity/depth and fee schedule; test adverse close costs and delayed exit | Limit-order plan is not fill assurance; no legging assumption unless separately funded and reviewed |
| Exercise/early assignment/pin risk | Compute gross long-strike cash and short delivered shares; inspect broker exercise deadlines, margin and close policy | Open-cost affordability is separate; pre-expiry package close avoids expiration exposure only if actually filled |
| Numerical/Greek validation | Reuse QuantLib convergence and independent limiting cases; repricing after finite shocks rather than linear Greeks | Price grid stability does not certify Greeks or all numerical regimes; test relevant Greeks separately |
| Unstated model assumptions | Independent adversary maps every action-changing input to evidence or sensitivity; failure taxonomy and prospective outcomes | No software can certify absence of undeclared assumptions; enforce inventory plus substantive reviewer inspection |

## What was actually solved in this increment

On 24 October 2026 the CRWV June30 10-Q was opened at the SEC. Its dividends note states that no common dividends had been declared as of June30 and preferred dividend rights ceased after the IPO; its risk discussion states a current intention not to pay dividends in the foreseeable future. This supports a zero scheduled common-dividend **base assumption**, subject to checking subsequent declarations and future changes. It does not guarantee a zero dividend through April2027. Distinguish a known policy from a guarantee of a future board decision.

Bounded searches of official IR releases/calendar and SEC plus a second search engine did not verify the reported November11 earnings date. A snippet suggesting a preliminary Q3 release on October19 was traced to another issuer (FreightCar America), not CRWV, and rejected. Do not convert related-page snippets into company evidence.

`options_decision_bounds.py` is the new lightweight numerical remedy. It accepts the exact existing `options_payoff_checks` packet, a fixed whole-contract quantity, explicit `valuation_horizon` equal to contract expiry, terminal-stock scenarios and per-scenario probability lower/upper bounds. It validates supported OCC identity and topology via the existing calculator. It computes payoff extrema over that probability-simplex set using greedy allocation, without a new numerical dependency.

Let `P` be total option premium, `F0` opening fees, `F1` assumed closing cost at expiry, `R` a terminal model-error reserve, and `h` a declared **total holding-period** return hurdle on invested opening cash. If `Emin` is the lowest expected intrinsic payout allowed by the declared probabilities:

`Pmax = (Emin − F1 − R) / (1 + h) − F0`.

The cash budget separately caps premium at `budget − F0`. `h` is not an annual rate. Closing cost and model reserve are sensitivities, not observed future expenses. The routine reports a finite-precision decimal quotient, not tick-rounded executable prices. Users/brokers must round any hypothetical limit downward to valid ticks. Probability intervals and scenario support require evidence/independent review; this helper does not bless them.

If probability bounds allow all mass on a zero-payoff scenario, no positive premium meets a positive hurdle under that worst case. This is an honest consequence of complete ambiguity—not proof every option is bad. The work must then focus on which evidence can narrow an action-changing probability bound. More simulated draws do not solve the missing economic distribution.

### Actual saved CRWV diagnostic

All36 previously saved strategy/model distributions were reused, not refitted. An illustrative 10% **total expiry-period** hurdle, $0.65 opening fee per contract/leg, zero closing friction and zero model reserve give these conditional maximum premium prices **per quoted share**:

| April16 2027 structure | Raw historical bootstrap | Zero-drift GBM | 20% annual-drift GBM | Saved opening premium |
|---|---:|---:|---:|---:|
| $65 call,1 contract | $5.63 | $9.14 | $11.77 | $10.80 |
| $70 call,1 contract | $4.86 | $8.00 | $10.40 | $9.15 |
| $55/$65 spread,2 packages | $1.94 | $2.85 | $3.33 | $4.10 |
| $55/$70 spread,2 packages | $2.70 | $3.98 | $4.70 | $5.25 |

These are **not new alert/order prices or recommended limits**. The models failed/small-sample calibration checks remain visible, and no model weights were invented. In particular, the $65call passes one bullish drift assumption and fails others: identifying a justified medium-term return distribution is decision-relevant. The spread fails this illustrative hurdle even in the20%drift case; lower premium alone does not establish better expected value. $11.77 is the economic cap before the separate $1,100cash budget; budget permits at most $10.9935/share before tick rounding with this opening fee. Any positive exit/model reserve lowers all caps.

A further numerical check compares finite Monte Carlo means with the analytic **physical GBM** expectation (not discounted risk-neutral valuation). For the same $54.07 anchor,95.70%volatility and119/252year clock, the exact expected $65call intrinsic payout is $1,045.16 at zero drift and $1,338.88 at20%drift; the saved10,000path means are $1,005.94 and $1,295.35. Narrow profit-probability sampling intervals do not certify equally small error in a tail-driven mean. Keep an analytic limiting-case check or mean standard errors/tail convergence where possible, and do not present a sampled cap to cents as economically precise.

The corresponding analytic switching arithmetic drifts, under the same illustrative10%total-period hurdle and fees, are10.27%annual for the$65call,7.03%for$70call,50.89%for$55/$65spread and35.37%for$55/$70spread. Those imply expected stock gains of4.97%,3.38%,27.17%and18.18%over119sessions. They do not imply those gains will occur or that the stated mean-return condition makes a trade desirable: call means are tail-sensitive and full-premium-loss probabilities remain substantial. A required-return cap is not a risk-adjusted utility optimum or evidence the assumed tail is realistic. These thresholds guide which evidence could change the decision; no drift was fitted to justify buying.

Physical funding arithmetic: one $65call can require $6,500 to purchase100shares, one $70call $7,000. Two spreads with $55long legs can require $11,000 gross purchase cash. Their200short-call shares, strike proceeds and long legs must not be assumed to net automatically. Margin is left null because broker/account/borrow rules and asynchronous exercise/assignment matter. Funding excess does not prohibit selling a long call before expiry; it requires a realistic, funded exit plan with fill risk retained.

## Reuse maintained tools, add complexity only at a decision gate

- [QuantLib](https://github.com/lballabio/QuantLib): already installed1.44 through the pinned optional adapter. Reuse American exercise, cash dividends, convergence and stress rather than introducing another pricer.
- [arch](https://github.com/bashtage/arch): already installed8.0.0. Reuse stationary bootstrap and chronological scoring. GARCH/filtered historical simulation are experiments requiring frozen tests, not automatic forecasting upgrades.
- [Gatheral–Jacquier SVI](https://arxiv.org/abs/1204.0646) and [author implementation](https://github.com/JackJacquier/SSVI): references for appropriate European surface constraints. Do not feed asynchronous American quotes straight into a European fit.
- [CVXPY](https://github.com/cvxpy/cvxpy): reviewed maintained candidate for bid/ask interval feasibility/convex constrained projection if a sufficiently rich, synchronized, exercise-adjusted surface makes that calculation useful. Not installed for the small probability-bound problem; greedy allocation already solves that restricted LP.
- [NY Fed Malz risk-neutral distribution method](https://www.newyorkfed.org/research/staff_reports/sr677.html): a pricing-distribution reference, not physical profit probabilities.

## Operational integration

Call the new helper only for expiry decisions and keep the input/output/method hashes with the current research artifact. A before-expiry exit uses the existing time/IV/American repricing route and corresponding exit date; do not substitute terminal intrinsic payoff. Core validation continues to gate executable quotes, exact contracts, thesis, independent review and persistence. This module currently provides an optional numerical check; its presence is not a global interception mechanism.

Source verification on24October2026:

- CRWV [June30 2026 10-Q](https://www.sec.gov/Archives/edgar/data/1769628/000176962826000366/crwv-20260630.htm), Dividends note and common-stock risk discussion; [Q2 earnings release](https://investors.coreweave.com/news/news-details/2026/CoreWeave-Reports-Strong-Second-Quarter-2026-Results/default.aspx), dated11August2026.
- OCC/OIC [assignment FAQ](https://www.optionseducation.org/referencelibrary/faq/options-assignment) and [bull call spread](https://www.optionseducation.org/strategies/all-strategies/bull-call-spread-debit-call-spread): broker policies matter; assignment and paired-long action can be asynchronous; closing before expiry requires actual completion.
- OCC [series search](https://www.theocc.com/market-data/market-data-reports/series-and-trading-data/series-search) and [adjustment memos](https://infomemo.theocc.com/infomemo/search): discovery points, not a claim that exact AprilCRWV terms were successfully authenticated this run.
