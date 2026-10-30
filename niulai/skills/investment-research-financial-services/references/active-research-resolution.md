# Active research resolution and experiment selection

Policy **2026-10-24-active-resolution-1** adds a bounded problem-solving pass to the existing native research harness. A list of unknowns is a starting point, not the deliverable. The objective is to resolve facts we can obtain, calculate decision-changing bounds for genuinely uncertain inputs, and explain the remaining external dependency precisely. Do not promise positive alpha or solve unknowable future outcomes by inventing probabilities.

## Execute before returning a material unresolved question

1. **Restore and inspect the baseline.** Reuse exact prior source/model identities, sections, versions and cutoffs. Look in original report/model artifacts before treating an empty incremental table as absent research. Record what remains applicable and the specific changed input.
2. **Generate distinguishable explanations.** State the focal causal mechanism, strongest alternative and a failure case where appropriate. Each has a source, predicted observable and falsifier. Ask from customer, competitor, supplier and capital-provider perspectives only when their answers could change the decision. Multiple agents repeating the same public narrative are not independent evidence.
3. **Work backward from the action boundary.** Translate the question into revenue, price, utilization, margin, reinvestment, claims, per-share value and investment horizon as applicable. Recompute the exact call/stock/spread decision with equal capital and execution costs. Identify which observable would switch buy/wait/size, and how far the current evidence is from that boundary. A five-year DCF cannot substitute for a six-month catalyst distribution.
4. **Choose a discriminating test, not more commentary.** Prefer the best original filing, customer contract, competitor disclosure, official contract specification or reproducible numerical test. Document the expected result under each competing mechanism before collecting it. Search outside the ticker's promotional vocabulary: test substitution economics, supply arrival, unit-cost declines, customer bargaining and who retains the surplus.
5. **Execute bounded recovery.** For a recoverable evidence gap, attempt the primary source, then a genuinely different documented route or a sensitivity bound. Cache unchanged evidence. Save actual results/errors and their timestamps; a failed search is not evidence of no change. Set an explicit attempt/time budget and stop repeating identical failures. Hard access limits may be evidenced by a saved tool-availability/entitlement observation before a network call; never fabricate a failed call.
6. **Recompute and independently challenge.** Use the resulting evidence to update only affected dependencies. Keep contradictory and negative results. The reviewer checks source meaning, alternative explanation, horizon, matrix completeness, numerical direction and whether the decision is robust enough for its scope. Quantitative probability calibration and data authenticity stay separate from arithmetic correctness.
7. **Close with a decision or precise dependency.** Publish the strongest supportable answer now, the price/debit condition or measurable event that changes it, and a durable checkpoint. A valid wait/no-buy under conservative bounds can be complete in its declared decision scope. It is not proof that all uncertainty, executable quotes or historical trade validation are resolved.

Do not discard the full required research scope after one interesting question is answered. The frozen `expected_question_ids` roster and its independent review preserve all identified material questions, including negative results and unavailable outcomes. A small concurrency cap is not a scope cap. A budget interruption remains explicit incomplete progress.

## Small numerical aid, no second executor

Run:

```bash
python references/niulai-workflow/scripts/research_resolution.py \
  --input /absolute/research-resolution.json \
  --output /absolute/research-resolution-result.json
```

The authoritative packet interface is `example_packet()` in `test_research_resolution.py`; its numbers are synthetic functional tests, never company evidence. The zero-dependency calculator checks the full expected roster, identity/cutoff, actual file hashes/availability, rival hypotheses, linked attempts and review artifacts. Its result is `resolution_ledger_checked_not_research_completion`, not an investment completion receipt.

For each question supply a common-budget/horizon scenario utility matrix, where larger utility is better. Monetary P&L is appropriate only when the stated risk/loss constraints remain separately enforced. It computes statewise regret, minimax regret and actions that weakly dominate across all declared states. Scenario completeness, utilities and bounds require a substantive reviewer; this is not a universal robust-optimization certificate. For a future-parameter question, states may represent alternative defensible model/parameter regimes, with expected utility computed inside each regime when its probability basis is supported. They need not be individual realized stock outcomes: requiring a risky asset to outperform cash in every realized bull/bear outcome would impose an unjustified riskless-profit veto. A supported expected-utility decision under a justified probability model remains available through the full research process; this helper does not universally require statewise dominance for buying.

If defensible probabilities are supplied, it also calculates:

`EVPI = sum_s p_s max_a U(a,s) − max_a sum_s p_s U(a,s)`.

This is the conditional value of **perfect information**, an ideal-information upper bound. It is not the expected value of a proposed experiment (EVSI), forecast calibration or alpha. Without a justified prior, do not fill one merely to get a score; leave probability-weighted outputs null and compare decision sensitivity. The lightweight priority `minimax regret / experiment minutes` is a heuristic in declared loss units, not EVSI. Never pool different currencies, investment budgets or horizons into one score. Expected information value below research/delay costs can justify stopping; a high upper bound alone does not prove a particular source is worth buying.

| Status | Minimum substantive meaning and structural check |
|---|---|
| `open` | Still actionable research work. Preserve next experiment, time budget, source and stopping condition. It is not a successful wait. |
| `resolved` | Actual obtained evidence plus saved resolution artifact and independent review. The reviewer must verify it answers the question. |
| `assumption_bound` | Transparent limits; the proposed action dominates across the declared states, with actual attempt and independent review. This is robustness within those limits, not future certainty. |
| `external_blocker` | Actual blocked/unavailable attempt or hash-bound hard-access observation, exact missing entitlement/input, recovery action and reopening condition. A buy dependent on that gap remains blocked. |
| `research_wait` | No further decision value inside reviewed bounds; robust action, wait reason and named reopening event. If the action still changes across plausible states, remain open or externally blocked. |

The output echoes `subject`, `as_of`, `proposed_action` and per-question `required_for_actions`; the parent finalizer must enforce its own applicable completion scope. Hashes and reviewer IDs prevent accidental mismatches but do not authenticate a source or make a self-reported review true. Native agents still retrieve, interpret and review. The calculator does not fetch sources, claim jobs, dispatch agents, trade or change reminders.

## Method sources and what is actually adopted

Source check: **2026-10-24**. The adaptations below are methods in this existing harness; no upstream executor or unreviewed agent loop is installed.

- [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent), MIT; [RD-Agent(Q) author paper](https://arxiv.org/abs/2505.15155) and [author finance scenario documentation](https://rdagent.readthedocs.io/en/stable/scens/data_agent_fin.html). Adopt the hypothesis → concrete experiment → execution → feedback memory loop. Use its recorded failed experiments as a design pattern; do not import its factor/model training/backtesting stack just to research one option. Paper-reported quant performance is not evidence this adaptation produces alpha. Repeated strategy search must remain frozen and scored on untouched data under our existing cycle/forecast contract.
- [Stanford STORM](https://github.com/stanford-oval/storm), MIT. Adopt perspective-guided, evidence-retrieving question generation to find overlooked customer/supplier/substitute observations. Its cited-report task is not an investment-quality or profit benchmark. Use native delegated questions rather than installing a parallel article-generation runtime.
- [MIT Risk and Decision Analysis: EVPI](https://ocw.mit.edu/courses/ids-333-risk-and-decision-analysis-fall-2021/resources/unit-9-value-of-info-video-4/). Use ideal-information value as an upper bound for research prioritization, with no claim the proposed research achieves it. The local finite-state helper implements the stated elementary arithmetic directly; no external code was copied.
- [LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research). Reviewed as a retrieval/planning reference, **not selected as a maintained install**: its owner archived it on **2026-08-21**, confirmed on the repository page. Stars and historical benchmarks are not maintenance or financial-validity checks.

Keep existing AI Berkshire growth-aware valuation, Anthropic financial-services workflows, first-principles adoption, cycle challenge, dual-source critical-input checks and independent finalization. This addition supplies initiative and stopping discipline around them; it is not a third valuation philosophy or a positive-alpha quota.

## CRWV application

A concrete investigation tree is: synchronize entitled option/stock quotes and exact contract terms; establish the medium-term business/event conditions independently of long-term fair value; calculate the maximum acceptable debit for those bounded outcomes; compare shares, call and defined-risk spread net of realistic execution; then inspect whether IV, timing or thesis risk actually switches the action. Public cost/debt/backlog disclosures can inform conditional bounds even without exact future prices. Missing future certainty is not an excuse to skip those calculations. Missing quote entitlement is an access dependency, and historical modeled marks must not be relabeled as current executable prices.
