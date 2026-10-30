# Financial modeling execution contract

Revision: **2026-10-15-modeling-1**. Apply alongside AI Berkshire growth-aware policy. Preserve the unmodified Anthropic sources and use this local contract for environment adaptation and identified formula corrections. Target accuracy and completeness, with no bullish/bearish direction target.

## Load and execute the source workflows

- Read [DCF model](modeling-upstream/dcf-model/WORKFLOW.md) for intrinsic valuation, cash projections, risk-appropriate discounting, terminal value, equity bridge and sensitivities.
- Read [3-statement model](modeling-upstream/3-statement-model/WORKFLOW.md) and [formula reference](modeling-upstream/3-statement-model/references/formulas.md) for cash, capital, financing and cross-statement linkages. Read [SEC extraction](modeling-upstream/3-statement-model/references/sec-filings.md) when collecting public filings. Read its formatting reference only for spreadsheet work.
- Treat these as inspectable methodology, not execution of an external Claude application. Never claim to have used a workflow merely because it was installed or mentioned. Record what was read, which checks were applied, outputs checked and unresolved omissions.

## Adapt the environment and task scope

The user's authorized format controls the deliverable. For a PDF/text research request, a reproducible code/formula model and transparent tables can execute the modeling methodology; a separate Excel file, Office session, 75-cell presentation template or repeated user checkpoint approvals are not prerequisites. Perform incremental internal checks and communicate material findings without interrupting already authorized work.

If delivering an actual workbook, follow the environment's spreadsheet skill, preserve live formulas, source every input, recalculate it and inspect errors. Do not claim workbook recalculation or Excel checks for a Python-only model. The bundled DCF validator is an optional workbook diagnostic, not proof of complete model correctness; its sheet assumptions can differ from the source workflow.

## Correct source issues explicitly

1. **WACC weights:** Use market equity E and nonnegative gross financial debt D, preferably market debt value or a disclosed justified proxy. Equity weight = E/(E+D), debt weight = D/(E+D), WACC = Ke×E/(E+D) + Kd×(1−tax)×D/(E+D). Cash is a separate nonoperating/enterprise-to-equity adjustment, not negative debt in the weights. Never use negative net debt or operating EV as the WACC capital denominator. With no debt, WACC = Ke. Reconcile lease treatment with both debt and the operating cash-flow definition.
2. **Missing/NM:** Do not follow troubleshooting examples that replace economically undefined ratios with zero. Return null/NM with the reason, preserving sign and period. Near-zero interest, negative earnings, missing market data or unavailable assumptions require a definition/coverage explanation, not fabricated certainty.
3. **Retained earnings and SBC:** Roll retained earnings as beginning RE + GAAP net income − dividends ± genuine documented adjustments. SBC is not added directly to retained earnings; its equity credit generally belongs in APIC while the expense is already inside GAAP net income. The common/APIC roll-forward must reconcile cash equity issuance, SBC, option exercises, withholding, repurchases and other documented transactions. Therefore ΔCommon Stock/APIC is not automatically equal to cash equity proceeds.
4. **NOL and tax:** Existing issuers begin with sourced opening NOL balances, tax attributes and valuation allowances. Do not default them to zero because a model begins in a new year. Taxable income and GAAP EBT are different: a NOL deduction reduces taxable income, not GAAP pretax profit. GAAP net income = EBT − income-tax expense; model cash taxes and deferred-tax movements consistently. Apply utilization limits only after verifying jurisdiction, vintage and restrictions.
5. **Timing:** State the actual valuation date, stub year and end-year versus midyear convention. A terminal perpetuity valued at forecast year-end is discounted from that year-end; do not blindly reuse the last explicit midyear period. If using a midyear terminal convention, derive it consistently and disclose it. Discount future nonoperating asset realization from its actual assumed date.
6. **Checks versus economic rules:** Terminal-value share, historical margin ordering, credit hierarchy, sample tax/capex/growth ranges, and a 5-year forecast are diagnostics or examples, not universal bounds. Do not force assumptions to satisfy them. Derive growth duration, driver economics and taxes from evidence. Show gross profit, EBITDA, EBIT and SBC definitions without counting embedded D&A/SBC twice.

## Required DCF execution evidence

Document the input cutoff, units and fiscal years. Distinguish actual facts, management guidance/targets, dated accessible consensus and analyst estimates. Do not use reverse-DCF conditions as a consensus source.

Record the following checks, with per-case/per-period outputs or reasoned N/A:

- Historical revenue, margins, D&A, capex, working capital and economic owner-cash bridge; explain acquisition/restructuring normalization and retain recurring SBC exactly once.
- Revenue and cost drivers: customers/workloads/net price; gross profit; R&D, S&M and G&A; after-SBC incremental economics; growth and margins fading toward a supportable steady state.
- FCFF at WACC or FCFE at cost of equity, taxes/loss years, reinvestment, negative-cash funding, timing, terminal ROIC/reinvestment continuity and terminal-value concentration.
- Market equity, gross debt, cash, financing maturities, leases, private/nonoperating assets and existing equity claims. Avoid an interest/principal/private-asset double count in the equity bridge.
- Fully recalculate sensitivities for discount rate/terminal economics and growth/operating margins; the base sensitivity intersection must reproduce the base result. Add beta/risk-free sensitivity if a sourced CAPM build is used; do not invent beta or ERP to fill a template. State any unsourced capital-cost assumption as such.
- Separate fair value, required-return entry price, expected wealth/IRR, loss probability and named stresses. Complete the large-gap attribution/strongest market case/reverse DCF required by the growth-aware policy.

## Minimum capital and financing schedules for material valuations

Build or explicitly reconcile opening balance + additions − reductions = ending balance for material cash, debt, PP&E/D&A, capitalized software, leases, working capital/deferred revenue, tax attributes and equity claims. Link timing and totals to the operating cash build and valuation bridge. Record unavailable debt-coupon, maturity, NOL or claim details; do not fill missing values with convenient zeroes.

For a DCF that does not project a complete balance sheet, label the output **DCF with operating, capital and financing schedules** (list actual schedules and omissions). A current capital bridge alone is not an annually linked financing schedule. If only selected schedules are complete, say **DCF with selected linked schedules** and name the gaps. Do not imply full three-statement integration or external audit assurance.

## Completion claims and checks

Claim **complete integrated three-statement model** only when all forecast periods and scenarios contain linked IS, BS and CF, and all of these checks actually pass within a stated materiality tolerance:

| Required check | Evidence |
|---|---|
| Balance sheet | Assets − liabilities − equity = 0 |
| Cash continuity | Prior ending cash = next beginning cash; CFO + CFI + CFF + FX/other = cash movement; CF ending cash = BS cash |
| Earnings link | IS net income = CF starting net income |
| Earnings and contributed equity | RE and APIC/treasury stock roll forward using the corrected treatment above |
| Capital assets | PP&E/software beginning + additions − depreciation/amortization − disposals/other = ending |
| Debt and leases | Opening + borrowings/additions − repayments/reductions/other = ending; interest links correctly |
| Working capital and tax | Balances/movements and cash-tax/deferred-tax/NOL schedules tie to the statements |
| Scenario integrity | Every scenario recalculates the actual linked model; undefined metrics stay NM |

Label each check passed, failed, not performed or not applicable with a reason. Reading a 3-statement workflow, running only its arithmetic helpers or checking a DCF's cash bridge does not establish these linkages. Use **internally checked/reconciled** where appropriate; reserve **audited** for a genuine external audit and identify its scope.
