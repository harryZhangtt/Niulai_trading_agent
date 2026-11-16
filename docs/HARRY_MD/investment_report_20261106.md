# Market Drawdown, AI and Semiconductor Portfolio-Manager Report

**Cutoff:** 2026-11-05 market close  
**Status:** completed diagnostic research with explicit gaps. No buy, staged entry, size, alert, or trade is supported for SOXL or TQQQ.

## Decision first

- **Rates are material but insufficient as a standalone explanation.** Three-month evidence supports renewed hikes and higher-for-longer. The latest one-month yield path retraced while the post-close AI basket still fell.
- **Near-term AI infrastructure demand is strong, but owner-value capture is uneven.** Public filings support high spending and supplier revenue. They do not establish independent customer utilization, AI-specific return on invested capital, or durable scarcity rents.
- **Semiconductors are multiple subcycles.** Accelerators, HBM, leading-edge foundry, advanced packaging and networking have stronger issuer-reported demand than several mature-node, legacy and consumer categories, but evidence quality differs by row.
- **Current SOXL and TQQQ analysis is diagnostic only.** Daily-reset path dependence is demonstrated, but exact benchmark histories, fund NAV, complete cost ledgers, calibrated probabilities and equal-budget entry comparisons are missing.

## Rate-path downside sensitivities

| Assumption | +50 bp | +100 bp | +150 bp |
|---|---:|---:|---:|
| S&P 500, rate only, 18.7x | -8.6% | -15.8% | -21.9% |
| S&P 500, plus 10% earnings decline | -17.7% | -24.2% | -29.7% |
| Nasdaq sensitivity, rate only, 30x assumed | -13.0% | -23.1% | -31.0% |
| Nasdaq sensitivity, plus 10% earnings decline | -21.7% | -30.8% | -37.9% |

These are mechanical required-return sensitivities, not forecasts. Nasdaq uses an assumed multiple because no authoritative current Nasdaq Composite forward P/E was available.

## Historical anchors, not calibrated probabilities

- **Dot-com Nasdaq:** -77.9% over 2000-03-10/2002-10-09 from direct FRED levels.
- **Tightening 2018:** Nasdaq -23.5% and S&P 500 -19.8%; real-yield change 37 bp.
- **Tightening 2022:** Nasdaq -35.5% and S&P 500 -25.4%; real-yield change 278 bp.
- **San Francisco Fed sample:** net S&P losses in 5 of 15 tightening cycles; start-to-end, not peak-to-trough.

A roughly 20% drawdown is a useful 2018-style stress anchor. The 2022 observations provide a 25% to 35% combined duration-and-earnings stress anchor. These are conditional analogs, not estimated likelihoods.

## Current valuation snapshot

| Universe | Names | TTM median | Forward median | Portfolio-weight aggregate forward P/E using holding weights or market-cap proxy weights | Name coverage | Weight coverage | Composition |
|---|---:|---:|---:|---:|---:|---:|---|
| S&P 500 proxy via SPY | 505 | 23.2x | 19.6x | 19.2x | 97.2% | 97.1% | SPY holdings 2026-11-04 |
| Nasdaq-listed proxy | 3341 | 18.9x | 15.1x | 7.0x | 38.7% | 90.9% | Nasdaq-listed proxy as of 2026-11-05, not COMP |
| SOXX | 30 | 38.7x | 25.9x | 17.6x | 73.3% | 89.2% | SOXX holdings 2026-11-03 |

Means, medians, density modes, covered-company market-cap aggregates and portfolio-weight aggregates using holding weights or market-cap proxy weights are separate measures. The Nasdaq proxy has low name coverage and is not an exact IXIC valuation.

## Post-close AI basket attribution

The attribution was rerun on 33 modeled post-close series whose latest observation is 2026-11-05. Thirty-four series were downloaded; XLK was unused in the specified 26-asset and 7-factor model. The OLS intercept is separate from factor-common and residual terms. Equal-weight mean log points are additive; arithmetic-return medians are shown separately.

| Window | Median arithmetic return | Mean total log points | Mean factor-common | Mean intercept | Mean residual | Days |
|---|---:|---:|---:|---:|---:|---:|
| Asset-specific peak since six-month anchor | -30.7% | -49.5 | -29.9 | 7.6 | -27.2 | 1–127 |
| One Month | -21.8% | -32.2 | -32.2 | 1.4 | -1.3 | 23 |
| Three Month | -19.1% | -22.9 | -19.8 | 3.9 | -6.9 | 65 |
| Six Month | -5.3% | -10.4 | -10.3 | 7.7 | -7.8 | 128 |

- The one-month mean decomposition is dominated by factor-common pressure; the residual is comparatively small.
- Asset-specific peak windows span different lengths and are not comparable with fixed horizons.
- The decomposition is descriptive and model-dependent. It is not causal company-fundamental attribution.

## AI demand and value capture evidence classes

- **[Reported financial]** Microsoft, Alphabet, Amazon, Meta and Oracle reported very high infrastructure spending. Several also reported weak or negative free cash flow during the expansion.
- **[Management guidance]** Microsoft guided calendar-2026 capex near $170 billion; Meta and other issuers maintained aggressive investment plans.
- **[Reported financial]** NVIDIA reported $89.0 billion of quarterly data-center revenue. Broadcom, TSMC and Micron reported strong AI-linked supplier results.
- **[Management claim]** Token growth, delivered capacity, order pipelines and take-or-pay commentary support demand but do not independently prove customer ROI or durable supplier rents.
- **[Analyst synthesis]** Custom silicon, efficiency gains, capacity additions and customer bargaining can preserve AI adoption while weakening selected merchant suppliers or subcategories.

## Semiconductor subcycle evidence matrix

| Subcategory | Diagnostic | Evidence class | Confidence | Missing evidence |
|---|---|---|---|---|
| GPUs / AI accelerators | issuer-reported demand strong; value-capture duration uncertain | reported financial plus management guidance | medium-high near-term demand; medium durable returns | independent utilization, customer ROI and normalized scarcity rent |
| CPUs | insufficient current subcycle evidence | insufficient evidence | low | current units, inventory, pricing and AI host-CPU attach data |
| Custom ASICs | issuer-reported structural demand; merchant-GPU substitution risk | reported financial plus management claim | medium | matched workload economics and independent deployment volumes |
| HBM | issuer-reported tight demand; qualification, yield and supply response remain decisive | issuer financial and management claim | medium-high near term | cross-vendor qualified capacity, yield and contract-price dataset |
| Commodity DRAM | cyclical recovery may diverge from HBM | issuer-reported | medium | independent contract pricing and customer inventory |
| NAND | insufficient evidence; more cyclical and less directly AI-bound | limited issuer evidence | low | current NAND-specific utilization, inventory and realized pricing |
| Leading-edge foundry | issuer-reported AI and custom-silicon demand strong; concentration risk | issuer-reported | medium-high | independent utilization, customer mix and node-level realized pricing |
| Trailing-edge foundry | insufficient current evidence; legacy end-market weakness possible | insufficient disaggregated evidence | low | mature-node utilization, lead times and cancellations |
| Advanced packaging | limited issuer aggregate evidence; capacity and yield remain unverified | limited issuer aggregate evidence | low | qualified delivered capacity, yield and customer allocation |
| Networking / switching / optics | issuer-reported AI scale-out demand strong; architecture and mix risk | reported financial plus management claim | medium-high near term | independent deployment, utilization and normalized optical pricing |
| EDA / semiconductor IP | insufficient current evidence | insufficient evidence | low | current bookings, design starts, concentration and export effects |
| Wafer-fab equipment | insufficient content-verified evidence; long-lag and export risk require monitoring | issuer-reported | medium | cross-vendor bookings, cancellations and delivered capacity |
| Analog / power | insufficient content-verified semiconductor evidence; AI power opportunity remains a hypothesis | limited issuer evidence | low-medium | data-center mix, distributor inventory and power-semiconductor pricing |
| Automotive / industrial | insufficient content-verified evidence; legacy-cycle weakness remains a hypothesis | issuer-reported | medium | independent channel inventory and end-demand normalization |
| PC / handset chips | insufficient evidence; AI-device monetization unverified at scale | insufficient evidence | low | paid AI-device demand, content growth and channel inventory |
| Storage controllers / HDD / SSD | AI data growth supportive but pricing and capacity remain cyclical | limited issuer evidence | low-medium | controller and HDD vendor evidence plus normalized capacity economics |

Monitoring should remain separate across the adoption clock, operating supply-demand clock and market-expectations clock. Weekly observations cover pricing, breadth, revisions, real yields and credit. Monthly observations cover inventory, lead times, utilization and bookings. Quarterly observations cover units, ASP, margins, capex, cash conversion and guidance.

## SOXL and TQQQ diagnostic path analysis


### SOXL: exact benchmark NYSE Semiconductor Index; adjusted market-price proxy SOXX

Issuer page expense ratios: net not verified; gross not verified.

| Horizon | Fund adjusted-price return | Proxy adjusted-price return | Synthetic daily-3x proxy path | Difference, not identified drag | Fund max drawdown |
|---|---:|---:|---:|---:|---:|
| 21d, 2026-10-07 to 2026-11-05 | -71.5% | -30.7% | -70.6% | -0.9 pp | -71.5% |
| 63d, 2026-08-07 to 2026-11-05 | -67.7% | -25.5% | -65.7% | -2.0 pp | -72.4% |
| 126d, 2026-05-07 to 2026-11-05 | -70.2% | -17.7% | -66.9% | -3.2 pp | -84.9% |
| 252d, 2025-11-04 to 2026-11-05 | 6.0% | 37.7% | 24.8% | -18.8 pp | -84.9% |
| 756d, 2023-10-31 to 2026-11-05 | 209.7% | 188.4% | 411.8% | -202.2 pp | -87.9% |

The proxy-return block bootstrap median was 51.7% with a 5th percentile of -67.2% and loss frequency of 30.4%. It is historical resampling, not a calibrated forecast.
- **Issuer warning:** Daily objective only; cumulative return beyond one day should not be expected to equal three times benchmark cumulative return.
- **Issuer warning:** A total loss may occur in one day.
- **Issuer warning:** Derivatives, counterparty, liquidity, closure and financing terms require the current prospectus and supplements.

### TQQQ: exact benchmark Nasdaq-100 Index; adjusted market-price proxy QQQ

Issuer page expense ratios: net 0.78%; gross 0.94%.

| Horizon | Fund adjusted-price return | Proxy adjusted-price return | Synthetic daily-3x proxy path | Difference, not identified drag | Fund max drawdown |
|---|---:|---:|---:|---:|---:|
| 21d, 2026-10-07 to 2026-11-05 | -37.5% | -13.5% | -36.9% | -0.6 pp | -37.5% |
| 63d, 2026-08-07 to 2026-11-05 | -29.7% | -9.3% | -27.8% | -1.8 pp | -38.0% |
| 126d, 2026-05-07 to 2026-11-05 | -26.4% | -5.5% | -22.5% | -3.9 pp | -39.8% |
| 252d, 2025-11-04 to 2026-11-05 | -5.2% | 6.3% | 5.2% | -10.4 pp | -39.8% |
| 756d, 2023-10-31 to 2026-11-05 | 229.5% | 89.9% | 365.0% | -135.5 pp | -58.0% |

The proxy-return block bootstrap median was 48.5% with a 5th percentile of -46.0% and loss frequency of 24.6%. It is historical resampling, not a calibrated forecast.
- **Issuer warning:** Daily objective only; multiday returns depend on the path and may differ significantly from three times cumulative benchmark return.
- **Issuer warning:** Derivatives, counterparty, liquidity, closure and financing terms require the current prospectus and supplements.

**Action status:** diagnostic only. No buy, staged entry, size, price alert or medium/long-horizon 3x forecast is supported. Earnings revisions, breadth, pricing, utilization and volatility are monitoring triggers only.

## Completion ledger

- `wf_068b80ca-e8a`: **partial**. Completed: models-history, valuation-universe, ai-first-principles. Failed/incomplete: rates-path, historical-portfolio, drawdown-attribution, earnings-capex.
- `wf_24810f9e-183`: **partial**. Completed: earnings-capex, recovery-critic. Failed/incomplete: rates-current, historical-portfolio, semiconductor-subcycles, soxl-mechanics, tqqq-mechanics.
- `wf_12052c70-f09`: **stopped_after_quota_and_gateway_instability**. Completed: none. Failed/incomplete: semiconductor-subcycles-retry, leveraged-funds-retry.

**Remaining gaps:**
- Exact Nasdaq Composite constituent membership, weights and authoritative current forward valuation
- Licensed point-in-time consensus and historical constituent valuation
- Exact reset-aligned NYSE Semiconductor Index and Nasdaq-100 total-return histories plus fund NAV series
- Complete current SOXL financing, derivatives, collateral, counterparty and fee-waiver ledger
- Independent customer utilization, AI-specific ROI and supplier normalized scarcity-rent evidence
- Calibrated physical probabilities and equal-budget now/stage/wait comparison

**Prohibited conclusions:**
- Causal company-fundamental attribution
- Exact IXIC valuation
- SOXL or TQQQ buy, staged entry, size, alert or medium-long-horizon 3x forecast
- Calibrated probability forecast from historical bootstrap
- Uniform semiconductor-cycle conclusion

## Freshness and sources

- Native search was used until the shared quota was exhausted. Authorized EgoLite browser discovery and direct official-page opening continued freshness checks.
- Browser pages with zero extracted text receive no evidence credit. The workbook source register separates content-verified, metadata-only, zero-text, gated and failed access.
- Primary anchors include Federal Reserve and Treasury data, FRED, State Street SPY holdings, iShares SOXX holdings, Direxion, ProShares and opened issuer materials.
- Full URLs, access status, dates and extract hashes are in the workbook Source Register sheet.

### Key direct sources

- Federal Reserve statement: https://www.federalreserve.gov/newsevents/pressreleases/monetary20261028a.htm
- Federal Reserve projections: https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm
- Atlanta Fed Market Probability Tracker: https://www.atlantafed.org/research-and-data/data/market-probability-tracker
- FRED macro and index data: https://fred.stlouisfed.org/
- State Street SPY holdings: https://www.ssga.com/us/en/intermediary/etfs/spdr-sp-500-etf-trust-spy
- iShares SOXX holdings: https://www.ishares.com/us/products/239705/ishares-semiconductor-etf
- Direxion SOXL: https://www.direxion.com/product/daily-semiconductor-bull-bear-3x-etfs
- ProShares TQQQ: https://www.proshares.com/our-etfs/leveraged-and-inverse/tqqq

## Workbook

`Market_Drawdown_AI_Semiconductor_Valuation_2026-11-05.xlsx` contains the full current tables, model details, completion ledger, audit rows and source register.
