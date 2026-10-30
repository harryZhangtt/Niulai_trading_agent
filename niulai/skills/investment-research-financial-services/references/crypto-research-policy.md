# Crypto research and value-capture policy

Version **2026-10-23-crypto-1**. Route native cryptoassets and protocol tokens to `crypto_full`; preserve company and fund branches for listed operating businesses and ETP wrappers. Read the research harness and entry-policy contract too. This branch replaces corporate accounting requirements only where genuinely inapplicable; it does not waive evidence, calculations, independent review or persistence. No schedule, trading or alert changes follow implicitly.

## 1. Identify what is owned and paid for

Verify chain, canonical asset/contract, units, supply definition, custody and instrument. Distinguish native ETH, wrapped ETH, liquid staking claims, restaked claims, ETFs, stablecoins and listed equity. Token ownership is not a legal equity interest in every ecosystem application. Identify the user's job: permissionless settlement, dollar access, trading, collateral, programmable finance, remittance or speculative exposure. Ask why the user pays for this service instead of the best available alternative. Preserve the dated prior thesis and classify every material claim as strengthened, maintained, weakened, invalidated, reclaimed or unverified; attach evidence and a reopening/falsification condition.

## 2. Separate ecosystem growth from investor capture

Reconcile **application user fees → sequencer/application revenue → L1 execution/data-availability payments → base/blob fee burn → tips/MEV to validators → validator operating/provider costs**. Treat issuance as new token supply and a transfer/dilution mechanism, not external customer revenue. Show supply opening + issuance − burn = closing, or document actual reconciling adjustments. Burning is not a cash dividend; do not add a buyback-like benefit and lower future token supply for the same burn without an explicit non-overlapping valuation bridge. Validator income and passive-holder accrual differ. Separate nominal staking yield, issuance dilution, provider fees, slashing, lock-up/exit queues, smart-contract and restaking risks. Compare staked, unstaked and wrapper exposures net of their actual costs.

Never aggregate L1 and L2 gross fees as ETH-holder revenue. Stablecoin supply, tokenized asset face value, TVL and settlement volume are stocks/flows, not network revenue or tokenholder assets. Remove bridged duplicate supply, recursive lending/rehypothecation, wash/self-transfer/bot activity where measurable; retain provider definitions and uncertainty where not. Unique addresses are not unique people. Compare developers only with matching definitions, ecosystems, periods and deduplication.

For stablecoins or L2s, require **Circle/CRCL and Coinbase/COIN** as economic-capture comparators. Follow reserve interest, customer/distribution revenue-sharing, sequencer margin and L1 payments without counting the same distribution revenue twice across the ecosystem. Distinguish competition for user functionality from alternative investment exposure. Full stock entry recommendations still require their company pipelines; token relative attractiveness alone does not value their shares. Include bank deposits, instant payments, card/acquirer networks, permissioned tokenization and conventional securities where they solve the same job.

## 3. Compare technology at equal service quality

Measure delivered cost, inclusion latency, economic finality, reliability, composability/liquidity, censorship resistance, decentralization/client concentration, data availability, bridge/upgrade-key/security assumptions and user recovery. TPS is not a universal quality score: distinguish simple transfers, complex transactions, voting/system traffic and batching. Compare L1 with L1 and L2 with the appropriate settlement/security stack. Separate announced, devnet, testnet, mainnet-activated and demonstrably adopted features. A roadmap date is not delivered capacity. Falling cost improves adoption but can reduce token rents; calculate demand elasticity required to offset lower fees.

Test the claim that a substitute does “80% of the job” with a **use-case matrix** and predeclared user weights. Do not present an invented universal percentage. Show where alternatives win, where they depend on Ethereum and which remaining function users materially pay to retain. Compare liquidity/security and switching costs, not brand rank alone.

## 4. Regional demand and regulation

Cover US and Europe separately from Asia, Africa and Latin America or explain bounded scope. Test dollar savings, remittance, cross-border commerce and financial-access demand, including FX/on/off-ramp costs, account access, custody and local cash-out. Gross on-chain transfer volume is not measured merchant payments. Compare to instant domestic payment rails; an excellent domestic system may still leave cross-border gaps. Separate legitimate utility, exchange/speculation, illicit activity and unknown classification without assuming any region is homogeneous. Record enacted law, effective implementation, pending rules and proposals distinctly; never infer legal status from political odds or an announcement. Reverify current primary regulatory sources.

## 5. Value the token with multiple non-overlapping lenses

Use a protocol economic model (`crypto_hybrid`, `network_cashflow` or `monetary_demand`), not corporate EBITDA. Model externally funded fees and beneficiary allocation, security costs, supply/issuance/burn and net staking outcomes. Separately bound collateral/monetary convenience demand, adoption/velocity and speculative liquidity premium. State which components overlap and remove double counting. A monetary premium is a scenario assumption requiring evidence, not a residual silently chosen to reproduce market price. Do not capitalize all TVL or reserves as ETH assets.

Build bear/base/bull, strong price-supporting case and reverse required fees/adoption/premium. Distinguish a model's fair-value discount rate from the user's annual-return hurdle. Label probabilities as judgment, historical or calibrated; preserve zero-edge and wait conclusions. Test fee compression, demand elasticity, L2/alternative-DA leakage, issuance, concentration/censorship, exploits/depeg, leverage unwind and favorable adoption. Use a severe discontinuity case rather than treating high volatility as a normal distribution. Price precision must reflect model uncertainty.

## 6. Rates, liquidity, market structure and technical evidence

Separate rate channels: discount rate; cash opportunity cost; leverage/funding/liquidations; USD/real-rate liquidity; stablecoin reserve yield; and token staking yield. Falling rates may support token demand while reducing stablecoin issuer revenue. Compute at least ±100/200 bp or justified alternatives, with volume/balance responses separate. Historical beta is regime-dependent, not a causal constant: use point-in-time data, rolling windows, BTC/equity/USD controls, nonlinear stresses and out-of-sample checks before claiming predictive calibration.

Use timestamped 24/7 price series, venue/UTC cutoff, gaps and corporate/token events. Compute technical levels deterministically (trend, volatility, drawdowns, volume and relative ETH/BTC where relevant); disclose that support can fail. Do not recycle an old chart's numeric levels. Funding, basis, open interest, liquidations, options implied volatility/skew and ETF flows require actual current data. Missing data is explicitly unavailable, never neutral/zero. Compare buy-now/staged/wait at the same end date with cash carry, nonfill, fees, staking/custody treatment and deterioration; follow the existing entry evidence gate using `basis: crypto_bound`.

## 7. Evidence and completion

Use `schemas/crypto-evidence.template.json` for the crypto block's hashed assessment artifact. Each required topic records `evidenced`, `limited` or `not_applicable`, a finding, source IDs and artifact IDs; limitations need a reason and decision impact. An unavailable market metric may leave the topic limited without fabricating precision, but a source-free complete recommendation is forbidden. Keep exact periods, scope, units, source versions and monetary conversions. A user PDF is dated hypothesis/context, not independently verified fact.

Set `scope: crypto_full`, `subject.security_type: cryptoasset`, `policy_versions.crypto: 2026-10-23-crypto-1` and `crypto_evidence` in the main run record. Attach assessment plus actual independent review with pinned hashes. Run `references/niulai-workflow/scripts/crypto_evidence.py --record RECORD`; finalization and completion invoke it. Run the existing schema, valuation and entry checks too. The check enforces evidence bindings and numerical supply reconciliation, not source truth, good forecasts or background execution. Parent-only guarded database registration and independent save/readback remain required.

## Professional methodology anchors (read critically; not price authorities)

- [Fidelity, Ethereum Investment Thesis, 2023](https://www.fidelitydigitalassets.com/research-and-insights/ethereum-investment-thesis): distinguish monetary demand and yield; scaling changes capture and supply is conditional. Its historical figures are not current inputs.
- [CoinShares, Ethereum five-year framework, 28 May 2026](https://coinshares.com/insights/research-data/ethereum-5-year-valuation-framework/): separates cash-flow and monetary-premium lenses and revisits assumptions after scaling. Audit component overlap and alternative assumptions rather than adopting its targets.
- [VanEck, ETH 2030 framework, June 2024](https://www.vaneck.com/us/en/blogs/digital-assets/matthew-sigel-eth-2030-price-target.pdf): useful TAM → adoption → market share → take rate → token allocation bridge. Its forecast, terminal multiple and portfolio backtest are dated assumptions, not consensus or proven future allocations.

Use current protocol specifications, on-chain provider methodologies, regulator publications and issuer filings to update the anchors. Asset managers may own or sell related products; seek contrary evidence. Enforce the analytical process, not a permanently bullish view of ETH or an allegedly optimal crypto strategy.
