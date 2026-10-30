# Growth-aware valuation policy

Version: **2026-10-15-growth-aware-1**. Default mode: `growth-aware`.

Before a DCF or material valuation revision, read and execute the [modeling contract](../../modeling-adaptation.md), official [DCF workflow](../../modeling-upstream/dcf-model/WORKFLOW.md) and official [3-statement workflow](../../modeling-upstream/3-statement-model/WORKFLOW.md). The contract corrects known source formula issues, requires gross-debt WACC weights and scope-labeled linked capital/financing checks, and forbids claiming complete three-statement integration without passing its actual statement linkages.

## Contents

1. Purpose and precedence
2. Classify the economics before screening
3. Model owner economics without double counting
4. Price duration and reinvestment explicitly
5. Separate value, required return, and stress
6. Resolve large gaps against the market
7. Evaluate edge and size the investment

## 1. Purpose and precedence

Keep financial rigor, skeptical underwriting and falsifiable theses. Replace universal mature-company vetoes and stacked conservatism with company-specific economics. Target accuracy and completeness, with no bullish or bearish direction target. Do not tune the method to produce a buy, raise a valuation, or reconcile it to market price. A high market price is evidence to understand, not proof of either market wisdom or stupidity. Attribute each material assumption revision and its valuation effect; distinguish a model correction from new evidence and a changed investment judgment. Separate reported facts, management targets, accessible dated consensus, and analyst estimates throughout.

In `growth-aware` mode this policy controls classification, screening, scenarios and valuation whenever an original workflow conflicts. Preserve the original quality/checklist results as labeled diagnostics when useful. In `strict-upstream` mode execute the original thresholds explicitly, report that mode, and do not present its screening outcome as a universal finding about business quality. User instructions control mode and scope.

## 2. Classify the economics before screening

Classify each company, or each material segment, as mature, growth, cyclical, or capital-intensive; hybrids require a segment bridge. Do not assume every technology company has an indefinite growth runway.

| Type | Primary economic test | Contextual diagnostics |
|---|---|---|
| Mature | Sustainable owner cash, ROIC versus capital cost, competitive durability and capital allocation | Historical ROE, coverage and long-run margins can be strong screens |
| Growth / intangible-heavy | Gross-profit retention, cohort contribution, net expansion, acquisition efficiency, recurring economic SBC, incremental margins, runway and credible scale economics | Historical GAAP ROE, EBIT/interest and reported net margin are diagnostics, not automatic vetoes |
| Cyclical | Through-cycle demand, supply additions, cost position, mid-cycle margins, maintenance investment and balance-sheet survival | Avoid peak EPS, trough P/E and straight-line cycle extrapolation |
| Capital-intensive | Segment ROIC, utilization, asset life, economic depreciation, maintenance plus growth capex, leases and financing | Backlog and EBITDA alone do not demonstrate shareholder value |

For net-cash growth software, assess unrestricted current cash, debt maturity schedule, coupons, covenants, convertibles and existing equity claims, working-capital sustainability, and downside cash runway. Negative GAAP EBIT divided by near-zero interest does not by itself establish credit distress. Do not waive genuine liquidity, refinancing, fraud, governance, or poor unit-economics problems.

Evaluate R&D and sales expense as possible investment only with cohort, retention, contribution-margin, payback or competitive evidence. Do not label every dollar discretionary. If capitalizing R&D for an economic ROIC diagnostic, include a consistent amortization schedule and research asset; do not add it back to owner cash for free. Show after-SBC incremental economics and where evidence is unavailable. With negative net income, mark CFO/NI as NM and examine the cash bridge; do not interpret a negative denominator as cash-quality failure.

## 3. Model owner economics without double counting

Choose one recurring SBC treatment: (a) retain economic compensation as an expense in owner earnings, or (b) add back the relevant noncash SBC and explicitly model dilution or the cash repurchase required to offset it. Reconcile the two as a sensitivity when material. Never subtract the same recurring SBC and also dilute for that same future award stream. Capitalized SBC belongs in the bridge. Existing RSUs, in-the-money options, convertibles, capped-call limits and acquisition consideration remain current claims even under treatment (a); distinguish them from future recurring compensation.

Choose one valuation basis:

- **FCFF / WACC**: unlevered NOPAT + economic D&A minus cash capex and working capital/reinvestment. Discount at WACC; then bridge current net debt and nonoperating assets to equity. Do not subtract interest inside FCFF.
- **FCFE / cost of equity**: owner cash after financing, interest and net borrowing/repayment. Discount at cost of equity; use a consistent terminal equity claim. Do not deduct the same financing principal again in the equity bridge.

Keep debt-funded cash, signed investments and finance leases consistent on both asset and liability sides. Include operating lease liabilities only with the corresponding operating-cost adjustment. Count private investments at a justified after-tax realizable value and date; discounted realization in a future year is not interchangeable with immediate cash. Do not count paper investment gains again as recurring operating income. Preserve negative cash years and explicitly fund deficits; a profitable terminal scenario does not remove an intervening liquidity problem.

Specify a single distribution policy: distribute annual owner cash, retain it and model the resulting balance/investment return, or reinvest it in an explicitly funded operating path. Do not both pay out cash and retain it in terminal equity. Do not charge for reinvestment without connecting it to growth, or assume high growth with no required investment merely because the business is asset-light.

## 4. Price duration and reinvestment explicitly

Research scenario assumptions independently of the valuation hurdle. Anchor near years in dated evidence; derive later growth from workloads, customers, net monetization, competition, saturation and market capacity. Use 10–15 explicit years when a long-duration growth business requires them, with growth and margins fading toward a sustainable state. A shorter forecast is acceptable only if its terminal value already captures the remaining duration coherently.

Tie sustainable terminal growth to reinvestment and return on incremental capital. For a steady FCFF model, terminal reinvestment = NOPAT × g / ROIC and terminal FCFF = NOPAT × (1 − g / ROIC); value it at WACC > g. Explain why terminal ROIC is defensible and finite. An exit multiple may be used instead, but reconcile its implied growth, margin, reinvestment and risk with a perpetuity cross-check.

Do not assume that a 25× terminal profit multiple removes all future growth: it already embeds growth and risk assumptions. Do not add a 15-year growth runway and retain the same generous early high-growth multiple without justification. Show terminal value share and sensitivity to duration, fade, margins, capital intensity, discount rate and exit assumptions.

Check the final explicit-year to first terminal-year continuity of NOPAT, reinvestment, ROIC, margins, cash conversion and FCFF. Flag a terminal cash-flow decline greater than 10% despite nonnegative NOPAT growth. Fade ROIC/reinvestment toward their steady state gradually, or explain and quantify a real boundary event; do not silently create a pessimistic or optimistic cash-flow cliff solely by switching formulas.

## 5. Separate value, required return, and stress

Estimate fair value using a risk-appropriate capital cost; show a 9–11% sensitivity for relevant US growth equities as a starting range, not a universal rule. Choose WACC versus cost of equity consistently with the cash flows. The user's 15%, 18% or 22% entry hurdle is a portfolio opportunity-cost decision, not a claim that the market should discount every business at those rates.

Publish separately: central and probability-weighted fair value; current-price expected wealth or cash-flow IRR under the stated distribution policy; hurdle-rate entry price; downside loss probability and magnitude; and named stress outcomes. Label scenario probabilities as judgment unless empirically calibrated. Distinguish IRR of expected cash flows, probability-weighted scenario IRR, arithmetic expected wealth and expected log wealth; do not substitute one for another. State the horizon and reinvestment assumptions.

Constrain reverse probability calculations to the feasible simplex. For example, fixing the base weight at 50% permits only 0–50% bull weight if the remaining bear weight must be nonnegative. A solved bull weight of 59.9% in that setup is infeasible, not an estimate of what investors believe. Label an infeasible solution and state which fixed assumptions would have to change.

Do not impose a blanket extra 25% cash-flow haircut on expected value when the bear cases already include the same risks. Keep such a haircut, multiple compression, lower growth, dilution and terminal stress as separate sensitivities. If combining them, name the joint stress and explain correlation and what would need to occur together. A deeply discounted entry threshold may express the investor's return requirement without showing that current market fair value is one tenth as large.

## 6. Resolve large gaps against the market

If central fair value is below **50%** or above **200%** of current price, pause the investment conclusion and complete all of the following:

1. Attribute the gap to revenue path, duration/fade, gross and operating margins, SBC/equity claims, reinvestment, capital bridge, discount rate, terminal assumptions and distribution policy. Change one input family at a time before presenting combined changes.
2. Build the strongest evidence-supported market case. Compare historical analogues and dated accessible near-term expectations; avoid a straw-man terminal multiple or an implausible margin ceiling. Disclose source gaps rather than invent a licensed consensus.
3. Reverse-solve the required operating conditions at both fair-value capital cost and the investor's return hurdle. Call this **conditional required growth/margin/duration**, not “market consensus.” It is not measured consensus without a dated external source.
4. Reconcile the reverse case with workload economics, addressable gross profit, competitive structure and investment requirements. A growing technical workload does not automatically grow vendor bills: efficiency, caching, sampling, open standards, pricing and customer insourcing can change net monetization.
5. Publish the remaining disagreement and which observable evidence distinguishes the competing cases. A large model gap requires stronger diagnosis; it is neither permission to force the model toward price nor to declare the market wrong without explanation.

## 7. Evaluate edge and size the investment

For each proposed alpha identify the public baseline, a specific variant perception, supporting primary evidence, a measurable monetization/owner-profit mechanism, a time horizon, catalysts and falsification. State whether the claimed advantage is information access, better interpretation, time horizon, or none yet. Public product launches, TAM and consumption-growth narratives alone are not unrealized alpha.

Size against downside, liquidity needs, business uncertainty and correlated exposure, not price targets alone. Distinguish compounder/core candidates from earlier-stage satellite positions without applying a permanent zero-weight veto solely because a mature-company ratio fails. Keep “good business,” “fairly priced,” and “meets this portfolio's required return” as separate decisions. Respect the user's existing sector and portfolio budget; no analysis authorizes trading or watchlist/alert writes.
