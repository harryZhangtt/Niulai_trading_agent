# Investment research execution harness

Revision: **2026-10-18-research-harness-2**. Preserve the growth-aware, modeling and leveraged-fund policies. Use this contract for execution and recovery; use their economic methods for judgment.

## Native execution first

Use the existing ChatGPT Work/Codex capabilities rather than a custom orchestration framework:

| Capability | Use in this workflow |
|---|---|
| Native Skills and implicit invocation | The installed skill is the persistent default route for ticker research; relevant references load progressively |
| Native plan tracking | Track full stages and preserve the original objective when the user supplies additional context |
| Native subagents | Delegate evidence/industry/model work and obtain an independent source/numerical/reasoning review |
| Connected source tools and citations | Retrieve original filings/docs; preserve returned source references and precise passages |
| Shell/code and existing financial helpers | Compute rather than invent numbers; reuse the installed valuation, leveraged-return and audit helpers |
| Persistent files and versioned research catalog | Save explicit run state, evidence, models and actual file/version receipts; recover after compaction or a new runtime |
| Standard JSON Schema | Validate the research record's required shape and completion evidence with a maintained validator; do not write a second workflow engine |

Native API Structured Outputs can enforce a supported output shape when an actual API integration is configured; adapt this domain contract to the API's supported schema subset and still validate its completion conditions. Do not claim an ordinary chat JSON file was produced under server-enforced Structured Outputs. Native hooks can inject context after compaction and validate at Stop **where that runtime supports and trusts them**. As checked on 2026-10-18, official docs restrict personal Work Cloud from using local/plugin command hooks. Do not create a hooks file there and call it active; no hook trust/configuration tool is exposed in this session. Keep configuration, availability and observed execution distinct.

Official references: [Skills](https://learn.chatgpt.com/docs/skills-and-plugins), [AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md), [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents), [Hooks](https://learn.chatgpt.com/docs/hooks), [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Reverify changing product limits before activation. Record & Replay is for demonstrated computer workflows; it does not establish research truth. Do not choose legacy Agent Builder without checking its current lifecycle.

## Default route

For “research NOW”, “check this ticker”, “is X a good business/buy?”, an entry/EV request or comparable unbounded instruction, start a **full** run without requiring the user to name a skill. Verify the issuer, instrument, share class/corporate actions and completed-market-session cutoff. Use one complete primary run per ticker receiving an investment recommendation; comparison mentions alone do not certify completed coverage.

Route native cryptoassets/protocol tokens to `crypto_full` under [crypto policy](crypto-research-policy.md), with `cryptoasset` identity and token-economics schedules. Route operating companies to `company_full`, leveraged/inverse/structured products to the applicable `fund_full` mechanics branch. Classify mature/growth/cyclical/capital-intensive economics within the company branch. A general fund review must cover its underlying industry/holdings rather than apply an operating-company DCF to the wrapper. Unknown instrument identity blocks an instrument-specific investment conclusion.

Use `narrow` only when the user's instruction expressly limits scope, such as a definition, a single reported metric or a scheduled evidence delta. Record that scope in the request. Reading one news item is not a full ticker evaluation. A narrow or incomplete run may report supported facts and explicit gaps; it must not claim a completed buy/entry/position recommendation. Upgrade the run when the scope expands.

## Required full research

Execute these subjects using the existing workflows. Prioritize relevant evidence and avoid padding: mark a genuinely inapplicable item with a reason and inspectable support instead of inventing data. Missing public information is a gap, not evidence of a favorable result.

| Subject | Required output |
|---|---|
| Scope and prior thesis | Verified security, dates/units, fiscal periods, prior saved thesis/model and changes; preserve the user's horizon and market scope |
| Business and economics | Who pays for what, revenue/profit drivers, unit economics, pricing power, customer/vendor concentration, management and capital allocation |
| Industry and technology | First-principles demand/supply, adoption and monetization, competition/moats/substitution, cyclicality and phase, relevant macro/policy/regulation |
| Operating and cash quality | Latest quarter plus TTM/multi-year trend; organic/acquired/FX distinctions; revenue/backlog definitions; GAAP/adjusted/owner cash bridge, recurring SBC once, reinvestment and balance-sheet/financing risks |
| Profit scalability and value capture | Trace usage to paid units/net price and variable/fixed costs; measure or sensitize incremental gross/operating/owner profit after lost legacy revenue, SBC and reinvestment; identify who captures economic surplus and why |
| Expectations and valuation | Accessible consensus or explicitly model-implied expectations; history and relevant peer multiples; forward DCF/economic model, capital/cash/claims schedules and honest integration scope; reverse expectations and strongest market-price-supporting case |
| Scenarios and decision | Supportable bull/base/bear and growth fade, recalculated sensitivities and named stresses, labelled probability basis, return horizon and EV; distinguish fair value from hurdle entry; portfolio correlation/loss budget, conditional position logic and cost of waiting when relevant |
| Edge and falsification | Public baseline, exact variant perception and causal mechanism, information versus reasoning advantage (or no demonstrated edge), counter-evidence, catalysts/timing and measurable confirmation/invalidation |
| Review and publication | Reproducible calculations, independent numerical/source/semantic review, resolved findings, final claims traceable to evidence, saved reports/models and versioned research registrations |

For leveraged products, replace corporate wrapper economics with verified payoff/reset/benchmark, holdings and look-through overlap, derivative terms/collateral/fees/funding, exact applicable path returns, positive trend compounding, adverse variation, tails, daily NAV/market-price distinctions and joint portfolio exposure. Retain underlying industry/cycle, market expectations, EV, falsification and source/review stages. Apply the existing leveraged policy; do not impose normal/IID returns, a universal cost number or a corporate ratio screen.

### Profit multiplier: required economic test

Define the meaningful economic unit first: completed/assigned workflow, customer, workload, transaction, bit, rack or another justified measure. Raw tokens, registrations and deployments are not automatically paid units. Model `revenue = paid units × effective net price + fixed/committed fees`, then variable model/cloud/power/material/support/rework costs and fixed operating expenses. Bridge operating profit through cash taxes, recurring SBC and maintenance/growth investment to owner cash per share.

Where observable, compute incremental gross and operating margins (`change in profit / change in revenue`), unit contribution, cohort/customer wallet and cash conversion over consistent periods. Separate acquisition/FX/mix/prepayment effects and identify minimum commitments, credits, discounts, price declines, efficiency and unused entitlements. Do not mechanically extrapolate an acquisition quarter or adjusted FCF addback as AI profit leverage.

Explain the replication economics and bargaining mechanism: what the customer would spend to build, migrate, operate and accept responsibility for an alternative; which scarce asset is hard to substitute; whether multiple model/supplier options are genuinely equivalent; who controls distribution and authorization; and whether customer competition returns cost savings through lower prices. A needed function does not establish that one vendor is indispensable. Technical superiority, workload growth and usage billing alone do not prove monopoly rents.

Recalculate at least a price/cost/mix sensitivity, including both favorable scale and adverse margin compression. Classify the supported outcome as positive, linear, negative, mixed or not established. If negotiated prices, paid utilization, model costs or outcome-level profits are undisclosed, mark the unit economics unidentifiable and use transparent consolidated/segment sensitivities with limits. Never invent a dollar/token figure or force a positive result. Temporary margin investment can still create value when the resulting returns are evidenced; margin compression is not an automatic permanent veto.

## Start, execute and checkpoint

Use `schemas/research-run.schema.json` for the run record and a maintained JSON Schema validator. Store private run data in the working research directory, never in Skills git. The schema is a domain contract, not another agent runtime.

Install the pinned `schemas/requirements.txt` in the available runtime if needed. Validate with `jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(record)`; keep date-format support installed. Run `tests/test_research_run_schema.py` when changing the contract. This validator is not OpenAI server-side Structured Outputs. Retain its actual result alongside the independent evidence/reasoning review.

1. Create the run record with its actual request, ticker, security type and cutoff. Resume an unfinished matching run rather than duplicate it. Record the active skill git revision and policy/source versions. Required coverage comes from the fixed schema/profile, not a model-chosen shortened checklist. Use native plan tracking for progress.
2. Record sources with publication/reporting/retrieval dates, source type, precise passage locator and a saved source snapshot/extract. Record claims as observed fact, company guidance, interpretation or analyst assumption. Connect each material claim to supporting/opposing sources. Do not source a reverse-model assumption as consensus.
3. Build topic coverage through actual claim IDs, report anchors and model/review artifacts. Record file hashes and dependencies; after any source/input revision, mark affected downstream work stale and rerun it. Inspect links and current file hashes using existing file/code tools. Include executed calculation commands and their output/check artifacts, not only a statement that a workflow was read.
4. Record the owner-cash/SBC bridge, scenario inputs/outputs, economic definitions, sensitivities, reverse/market case and model limitations. Preserve strong bull cases and the strongest countercase. Do not choose assumptions to obtain a buy, sell, PASS or alignment with price.
5. Have another agent/reviewer independently inspect numerical claims and reasoning using the actual source/model artifacts. Keep factual verification separate from assumption/arithmetic checks. Record unresolved findings and what changed; rerun affected calculations and dependency checks after corrections.
6. Validate the prepublication record against the schema and have an independent reviewer inspect the actual evidence/model/report and missing topics. Incomplete evidence, stale dependencies, unresolved material findings or empty numerical/factual reviews block a completed decision. The preserved upstream report-audit tool can return a PASS with no eligible checked values or warning-only mismatches; its headline verdict alone is insufficient. Inspect samples, dates/units and warnings explicitly; never modify the pinned upstream tool to hide them.
7. Save final reports/models/run artifacts through actual available persistence capabilities. Register exact file/version receipts, source/quote cutoff, model/policy revision and supersession in the research catalog/database. Validate the published record with those receipts and inspect every save result. An uploaded file alone does not prove a source claim, forecast, scheduled execution or notification delivery.

## Recovery after compaction or a new runtime

Keep a small checkpoint in the active work directory: original objective, current hypotheses, profile/stages, source/model paths and hashes, latest valid inputs, contradictions, next actions and persistent file references. Include it in the saved run bundle at material handoffs or before a long continuation. Record unfinished run references in the saved research catalog so a new runtime can locate them. Do not rely on a conversation summary, local path or a claim that a repo exists.

On recovery, load this skill, resolve the latest saved run/catalog, restore the native plan and inspect stale dependencies before continuing. A new user detail steers the active objective; it does not silently replace it or remove a stage. New delegates read this contract and receive scope, input revisions, required outputs and unresolved gaps. Reading is not recorded completion of their task.

## What the checks establish

For new full reports also execute [visual rationale and cycle challenge](rationale-cycle-policy.md), version `2026-10-23-rationale-cycle-1`, and start with schema version3. Generate the committed dependency lock, sourced/model-bound rationale card and prominently embedded graph; require a genuine independent cycle/valuation challenge and preserve its hash bindings. `rationale_guard.py` is called by finalization/completion, including new publication timestamps even if an older schema is incorrectly supplied. Genuinely earlier published records retain their historical status. Missing, stale or incorrectly cited dependencies reject new full completion, while narrow/price-only output stays scoped. Freeze resolvable forecasts for later scoring; structural acceptance is not evidence of calibrated forecasts or alpha.

Apply the [economic cycle module](cycle-capital-allocation.md) to that challenge rather than infer cheapness from a trend classification. Recompute applicable cycle arithmetic with the installed `cycle_checks.py`, bind the exact input/output artifacts and independent review, and preserve the assumptions. Optional regime/change-point packages have separate admission and out-of-time tests in [cycle method integration](cycle-method-integration.md); their absence cannot silently become a claimed execution or a hidden universal stop.

Standard schema validation verifies required structure and recorded completion fields. It does not itself resolve references, authenticate a provider, verify file hashes, prove a passage supports a claim, calibrate judgmental probabilities or intercept arbitrary tool calls. Use existing file tools to verify references/hashes and an independent source/reasoning review for semantic checks. Preserve a clear boundary between complete recorded execution and a sound investment thesis; neither guarantees returns.

Keep the reusable contract and CLI in the active personal Skills repository, validate and push changes. Keep individual research, private holdings, checkpoint data and credentials outside git. Do not auto-pull upstream or change alerts/trades/schedules as part of a research decision.

## Mandatory earnings/probability/entry evidence extension

For each new or resumed full pipeline, execute [valuation evidence policy](valuation-evidence-policy.md). Record `valuation_evidence` before finalization. Preserve old published records; do not claim they passed this newer policy. Reuse existing research and applicable fund mechanics; never force optimistic weights or technical confluence.

## Cost-aware entry override

For scheduled/batch candidate research, apply [research triage](research-triage.md) before full-work claims. Harry's 2026-10-20 cost instruction supersedes full research on every reached-price candidate. Honor current `research.triage.held_run_ids` and preserve unfinished history. Route reuse, repricing, bounded probes and targeted deltas separately; only selected decision-relevant cases enter full research. Explicit deep-dive requests and completed recommendations retain full applicable gates. Do not claim 80% savings until measured.

## Mandatory trend-to-value bridge

Apply [Trend-to-value execution contract](trend-to-value-policy.md) to full company research and material model revisions. Identify the three material trends, trace each into owner cash per share, test their joint dependencies and quantify what the market already prices. Link the actual bridge and counterfactual calculations into valuation evidence; do not substitute three narratives or unsupported precise probabilities.

## Entry policy comparison before publication

For every new or materially revised entry decision, apply [Entry policy and opportunity cost](opportunity-cost-policy.md) and pin `policy_versions.entry_policy=2026-10-23-entry-policy-2`. Reuse actual company/fund baseline models and source evidence, then calculate now/staged/wait on equal budgets and a common calendar horizon. A synthetic calculator demonstration, missing probability analysis, or an unchanged old alert is not a completed reassessment. Transparent judgmental probability/path assumptions are permissible with sensitivity and limits; do not require unknowable certainty or force prices to change.

`entry_policy_evidence.py` checks the company-bound input/output hashes, baseline/source bindings, finite policy metrics, explicit changed/unchanged decision and independent reviewer bindings. `finalize_research.py` and `research_completion.py` invoke it for opted-in full records; the JSON schema also rejects a missing/completion-incompatible block. It does not authenticate a source, prove statistical calibration, or intercept arbitrary tool calls. New records must opt in; older records and price-only summaries are preserved. `limited`/`pending` evidence is progress only and cannot certify a completed new entry decision. Have an independent reviewer inspect cash/distributions, nonfills, invalidation, information timing, probability assumptions, numerical direction and unchanged-price rationale before publication. Promote a reusable winning strategy only after pre-registered, leakage-controlled out-of-sample validation.
