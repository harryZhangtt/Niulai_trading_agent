---
name: ai-berkshire
description: Evaluate business quality, owner economics, fair value, expected returns, entry prices and leveraged-fund payoffs using AI Berkshire. Use for AI Berkshire or AI Berks requests, stock valuation, SaaS and AI applications, cyclicals, position sizing, conservative-model challenges, leveraged/inverse ETFs or ETNs including SOXL/TQQQ, and leveraged closed-end or structured funds.
---

# AI Berkshire

Enter through the parent adapter's [native research harness](../research-harness.md) for ticker research, including implicit requests that do not name a skill. Execute the full applicable company/fund pipeline, evidence-linked record and independent completion review; user examples do not narrow the required work. Use native Skills/plans/subagents and the standard run schema rather than a second agent executor. Recover unfinished research after compaction and distinguish structural validation from source/model truth.

Use policy **2026-10-15-growth-aware-1** by default. Read [Growth-aware policy](references/growth-aware-policy.md) before selecting a screen or building a valuation. State the policy version and chosen mode in the output. A request to use AI Berkshire alone selects this revised mode; select `strict-upstream` only when the user explicitly requests the original unmodified rules, and label its limitations separately.

For leveraged/inverse ETFs, ETNs, leveraged closed-end funds and structured funds, read and execute [Leveraged-fund policy](references/leveraged-funds-policy.md), version **2026-10-18-leveraged-funds-2**. This branch controls fund identity/payoff, reset compounding, financing, return-path probabilities, net EV and portfolio-risk analysis. Use it for SOXL/TQQQ, inverse and non-daily reset requests; do not apply a corporate ratio veto or a constant 3x formula to every fund. Use [linear-reset math](scripts/leveraged_funds.py) only for its stated scope; run its [tests](scripts/test_leveraged_funds.py) after edits. Preserve strong bull trends as well as chop, crashes and delayed recoveries. Do not confuse a log-growth/variance formula with arithmetic EV or illustrative weights with measured probabilities. Skip the corporate-only steps below for fund mechanics; retain source, arithmetic and reporting checks where applicable.

For company valuation builds or material revisions, also read and execute the parent adapter's [modeling contract](../modeling-adaptation.md), official [DCF workflow](../modeling-upstream/dcf-model/WORKFLOW.md), and official [3-statement workflow](../modeling-upstream/3-statement-model/WORKFLOW.md). Apply scope-appropriate capital/financing schedules and keep actual execution/completion claims precise. Bundling or reading these references is not proof of executing them.

## Execute the research

1. Run `date`; establish the security identity, quote timestamp, fiscal periods, source coverage, and company maturity classification. Preserve the user's market and portfolio scope.
2. Read the applicable canonical workflow under `references/upstream/skills/`: `quality-screen.md`, `investment-checklist.md`, or `industry-funnel.md`. Their original rules remain available for strict compatibility; apply the policy gate at their beginning in revised mode. Do not treat the original seven universal ratios as growth-company vetoes.
3. Collect primary filings and operating evidence. Distinguish reported facts, management guidance, dated accessible consensus, and analyst estimates. Independently derive the market's strongest supported case before comparing prices.
4. Build explicit scenarios and a growth fade. Reconcile SBC, existing equity claims, reinvestment, debt, leases, private investments, taxes, and cash retention. Follow one consistent FCFF/WACC or FCFE/cost-of-equity framework.
5. Calculate fair value, entry prices at the user's required return, scenario returns, loss probability, and model sensitivities as distinct outputs. If central value is below 50% or above 200% of price, complete the attribution and reverse-DCF review in the policy before publishing a buy/sell conclusion.
6. Validate financial arithmetic using the preserved `references/upstream/tools/financial_rigor.py`. Use `scripts/valuation_core.py` for the consistency checks and transparent DCF primitives when useful; it supplies no company forecasts or probabilities.
7. Run `references/upstream/tools/report_audit.py` before publishing financial reports. Check sign, units, dates and source identity in sampled cells; manually inspect parser warnings and actual mismatches. Never mark a warning-only mismatch as an audit pass. Audit observed facts externally and model arithmetic internally, not future estimates as if they were reported facts.
8. Explain the decision, the strongest opposing case, what evidence could change it, and any specific advantage over public expectations. Do not manufacture alpha or change a forecast just to reconcile it with the market price.

## Source and maintenance

Keep [upstream provenance](references/upstream-manifest.json) and the bundled MIT license. The financial-rigor and report-audit tools are preserved upstream copies. The three workflow sources carry a local precedence gate; their remaining original body is preserved for `strict-upstream` mode. Do not modify the Anthropic financial-services references in the sibling investment adapter.

After editing canonical workflow sources, regenerate compatibility references with `python3 scripts/sync_workflows.py` and verify with `--check`. This wrapper uses the preserved upstream generator, but stores results as `references/codex/*.md` rather than nested discoverable skills. Run `python3 scripts/test_valuation_core.py` and the skill-creator validator for the parent investment skill. Keep changes in the personal Skills repository and push its current branch to make later calls use the revision. Never push this local policy to the upstream AI Berkshire repository unless the user separately requests that action.
