# Offline research-harness evolution

Policy **2026-10-24-offline-promotion-1**. Improve the reasoning process through small, measured changes, while preserving the existing execution runtime and financial completion rules. An optimizer proposes changes; a frozen evaluator and independent reviewer decide whether the change is useful. No process can guarantee real alpha from prompt optimization or benchmark scores.

## Minimal portable architecture

Keep four ordinary files/interfaces: a versioned prompt/skill candidate, a source-bound case manifest, append-only JSONL observations, and a deterministic evaluation result. Existing native agents supply proposals and run the task. Python verifies recorded outcomes; it does not simulate agents or start an endless self-modification service.

Use this loop:

1. Diagnose a recurring failure from actual trajectories: e.g. stopping after one missing quote, conflating five-year value with six-month payoff, not quantifying an action boundary, or hiding an incomplete model behind confident prose.
2. Freeze a narrow editable surface and test protocol. Change one question strategy, retrieval rule, critic instruction or report contract at a time. Keep source permissions, mathematical ground truth, tests and evaluation adapters outside the editable surface.
3. Run baseline and candidate on the same complete case roster and source vintages. A result must contain actual artifacts, including errors and missing outcomes. Use chronological train/development/sealed-test partitions with nonoverlapping target windows when evaluating predictive work. Human/source-verified judgments supplement deterministic checks; candidate LLM scores alone cannot be the truth label.
4. Inspect detailed verifier feedback and failures, not a single reward. Revise only using training/development feedback. Record every tried variant, token/latency cost when observed, test exposure and the reason for stopping. No unobserved cost is silently zero in a real model run.
5. Freeze the selected candidate before opening the sealed holdout. One final evaluation compares candidate and baseline; do not revise against its failures and keep calling it untouched. Failed holdouts become future development cases, with a genuinely new sealed set required for a new promotion claim.
6. Accept only a scoped improvement with no critical failure, no paired regression and complete required coverage. At equal quality prefer the simpler/lower-cost implementation. An independent reviewer inspects factual labels, task leakage and the complete experiment history before any explicit production change. Keep the old git revision available for rollback.

The observation ledger is append-only by operating procedure; hashes detect later mismatches against the frozen manifest. Local hashes and caller-supplied timestamps do **not** prove that an adversarial proposer never saw the holdout or that a file was cryptographically immutable. Preserve an independently saved manifest/version receipt and reviewer-controlled test access for empirical claims. JSONL portability is a deliberate alternative to adding a database, distributed scheduler or another agent framework.

## The small local evaluator

`references/niulai-workflow/scripts/research_eval_promotion.py` reads a JSON manifest and JSONL observation file:

```bash
python references/niulai-workflow/scripts/research_eval_promotion.py \
  --manifest /absolute/eval-manifest.json \
  --expected-manifest-sha256 FROZEN_HASH_FROM_INDEPENDENT_RECEIPT \
  --observations /absolute/observations.jsonl \
  --output /absolute/evaluation.json
```

The adjacent test's `fixture()` supplies the exact version1 shape and synthetic examples. Declare the domain as `functional`, `research_quality` or `forecast_outcomes`. Each case binds a source artifact and a named verifier. Observations bind the exact baseline/candidate hashes, source vintage and saved verifier output. The module requires the externally retained frozen-manifest SHA256 and checks actual artifact bytes, full paired scope, chronology, source availability, bounded logged trials and single declared holdout evaluation. Costs and timings must match the hash-bound verifier measurements; editing only a JSONL row cannot create a cost improvement. It derives pass/completeness/critical-error counts from verifier artifacts instead of trusting a candidate's reported aggregate. Any critical candidate error or paired passing-case regression vetoes promotion, including when total accuracy improves elsewhere.

Its output is **`eligible_for_independent_offline_review` or `reject`**, never automatic production promotion. No fixed “85% accuracy” or universal minimum sample size is claimed. A small fixed family of tests verifies mechanics; it does not establish statistical significance, calibrated probabilities or superior financial decisions. The current module compares one selected candidate with one baseline. A larger optimizer's complete search history, rejected variants and authentic frozen receipts remain independently reviewable inputs; hiding extra searches cannot be detected from a truncated local file alone.

Prefer exact unit/currency/contract/availability checks, source-span entailment reviewed against original text, recomputed utility/valuation checks, attempted-resolution coverage and a professional readability rubric. Separate:

| Evaluation | Useful metric | What it cannot establish |
|---|---|---|
| Functional execution | Complete required stages, correct instrument, reproducible math, exact source/artifact bindings, bounded recovery | Correct forecasts or alpha |
| Research reasoning | Blind source-grounded reviewer agreement; causal bridge, strongest alternative, decisive tests, justified action boundaries | Realized return superiority |
| Forecasting | Frozen probability/price/horizon forecasts, mature outcomes, calibration/proper scores, full failed/withdrawn denominator | Executable net P&L without fills/costs |
| Investment policy | Equal-capital/time comparison, realistic fills/nonfills, fees, funding and dependence-aware out-of-time outcomes | Future guarantees |

Maintain the existing active-resolution ledger for a ticker's questions. This offline evaluator improves the reusable harness; it does not duplicate the resolution ledger, price sender, task queue or financial model.

## Selected upstream patterns and installation boundary

Primary-source review: **2026-10-24**. No upstream runtime below was installed by this extension. Only locally authored, dependency-free evaluation code was added. Repository benchmarks are author claims in their own domains, not validated investment performance for this harness.

| Primary source | Verified role/license | Minimal useful borrowing / decision |
|---|---|---|
| [GEPA](https://github.com/gepa-ai/gepa) / [optimize_anything API](https://gepa-ai.github.io/gepa/api/optimize_anything/optimize_anything/) | MIT; reflective search over text artifacts with an external evaluator and feedback. The current API distinguishes training, validation and an optional test set. | Best optional later proposer for a measurable prompt/skill adaptation. Supply execution traces and failure categories as actionable feedback. Keep critical-error vetoes outside a scalar reward. Do not install until a real task set, reproducible evaluator, budget and authorized model access exist. Pin and smoke-test the selected package/API then; a README install command is not execution. |
| [karpathy/autoresearch](https://github.com/karpathy/autoresearch) | MIT; the actual task is automated single-GPU language-model training. | Adopt a small editable surface, fixed evaluation budget, explicit experiment log and rollback. Do not treat GPU-training improvements as research intelligence, install its training stack for a finance report, or reuse its continuing loop without a stop budget. |
| [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent) | MIT; data/factor/model research-development-feedback architecture. | Already used as a method reference by the active-resolution extension. Preserve failed hypotheses and run concrete tests. Its quant training/backtesting stack is a separate, heavier project, not a prerequisite for a good fundamental/options answer. |
| [Sakana AI-Scientist-v2](https://github.com/SakanaAI/AI-Scientist-v2) | **The AI Scientist Source Code License**, derived from Responsible AI licensing; not MIT. Official documentation requires AI disclosure for resulting scientific manuscripts and describes Linux/NVIDIA/CUDA/PyTorch needs. | Borrow the general idea of an experiment manager preserving promising and failed branches. Do not vendor its code or deploy unrestricted self-executing experiments here. The README itself notes broader exploration can have lower success than a strong template. |
| [Thirdlayer AutoAgent](https://github.com/thirdlayerinc/autoagent), formerly `kevinrgu/autoagent`; [official article](https://www.dexterity.so/blog/autoagent) | MIT; the official link resolves the user's “Dexterity AutoAgent” name to this repository. Its setup uses Docker/Harbor and model credentials. | Borrow fixed-adapter boundaries, trajectory-based failure diagnosis and simplicity at tied quality. Do not install a second full harness just to reproduce these patterns. Its spreadsheet/terminal results are not investment evidence. |
| [A-Evolve](https://github.com/A-EVO-Lab/a-evolve) | MIT; framework with agent workspaces, benchmark adapters, evaluation/history/version-control interfaces. | Keep the filesystem contract and rollback pattern. Its own interface gives algorithms optional shared primitives; having the framework does not prove every evolution engine uses a quality gate. Do not conflate it with Google AlphaEvolve or assert universal benchmark claims. |
| [LangChain Open Deep Research](https://github.com/langchain-ai/open_deep_research) | MIT repository **archived 2026-08-21** on the owner page. | Historical retrieval/planning reference only; not recommended as a maintained installation. |
| [TradingAgents](https://github.com/TauricResearch/TradingAgents) | Already reviewed as an opposing-research pattern in the cycle method contract. | Reuse native independent challenge; a vote between agents is not independent data or calibrated probability. Reverify any selected code revision/license before later copying or installing it. |

No special July combination-paper claim is needed for this design; unverified date/performance claims should be omitted. The portable improvement is the interface and evidence discipline, not the number of installed frameworks. If GEPA is later enabled, count the final baseline/candidate test evaluations in the overall spending cap: its current API documents test-set scoring outside the optimization budget. Reserve that cost explicitly; a max-evaluation setting alone is not a complete billing cap.

## What was actually exercised

The local functional regression suite checks admission/rejection, paired scope, timestamp/source mismatch, heldout leakage declarations, critical-error vetoes and cost ties. A separate executed numeric-parser replay uses the existing strict `research_resolution.number` function against an intentionally weak `float()` control. It preserves source hashes and actual observed outcomes. These are synthetic functional probes, **not** a real historical production baseline, not GEPA optimization, not a genuinely unseen financial holdout, and not measured alpha. A useful workflow improvement must later be measured on independently authored source-grounded research cases.
