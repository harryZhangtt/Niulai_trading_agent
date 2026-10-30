# Daily reached-price research

Version: 2026-10-20-triggered-research-1. Role: `daily_triggered_research`.

This role reviews **every enabled security whose configured zone was reached in the target session**, including names already in-zone before today. A reached price selects work; it is neither a new-crossing claim nor a buy recommendation. Keep the existing price summaries and weekly winners/losers task independent. Reuse the installed research harness, AI Berkshire growth-aware policy, financial-services workflows and leveraged-fund branch; this is not another agent executor.

## 1. Configuration, due gate and frozen inputs

1. Recover the latest workflow, alerts JSON, alerts SQLite and research database through their exact saved identities and `runtime_filename`s. Retain actual versions. Validate configuration before price/research source calls. Resolve this role's saved automation ID against the executing task and its notification policy. A missing/disabled role or disabled policy stops quietly; missing/invalid configuration is a scoped failure, never permission to use the retired Studio.
2. Use `America/New_York`, including DST, and the actual XNYS calendar. Run only on an XNYS session at the configured 19:00 slot, with the configured grace capped at 60 minutes. Do not use weekday inference. A holiday/weekend/out-of-slot execution is quiet; calendar failure is a coverage failure. The slot is the **start of research**, not a promise that deep research finishes at 19:00.
3. Freeze session, configuration revision, complete rules hash, research database version, price/source cutoff, evidence cutoff at actual start, actual skill commit and policy versions. Resolve each security's identity and instrument type. The planner's input fingerprint and per-ticker jobs must refer to these frozen inputs.
4. Use one valid completed-session snapshot matching current enabled rules/revision and the target session. The summary may start at the same clock time: never assume it has finished. If its current snapshot is not available, copy the restored alerts database to an isolated temporary file using SQLite backup and run the existing `price_watch.py` in **replay** mode at the actual current cutoff on that copy. This is a read-only, retrospective price snapshot for research, not a new alert notification. Retain raw inputs and provenance with the research artifacts; never upload the temporary alerts database over the authority or relabel its events as live.
5. A snapshot's regular-session close is not a current executable after-hours quote. Label its time; late news may change the thesis without changing that close. Any proposed executable limit remains conditional on a fresh verified quote and corporate-action check.

## 2. Deterministic planning and coverage

Use `scripts/triggered_research.py` for deterministic planning and structured-result checks; consult its CLI help for the installed arguments. It does not fetch evidence, execute agents, prove source truth or place trades. Python/SQL handles identity, selection, batching, arithmetic, gates and records. Native tools/skills handle research and independent review.

The planner takes `plan --config workflow.json --rules alerts.json --snapshot SNAPSHOT.json --session YYYY-MM-DD --research-db research.sqlite --output PLAN.json`. Add `--allow-replay` only for the explicitly labeled read-only snapshot described above or an offline replay test; this does not convert replay evidence into live crossing proof. Its recovered `baseline` contains database metadata, not the source documents themselves: complete the document-reading gate in section 3. `validate --plan PLAN.json --results RESULTS.json --output CHECKS.json` checks the structured results after research. Batch configuration is `research.daily_triggered_review.batch_size`; all batches remain in scope.

- Select current **enabled** rules and group all reached rules into one job per ticker. Keep actual threshold attainment, approach-buffer-only, currently in-zone and reached-then-rebounded distinct. Do not silently limit the universe to the highest-priority five shown on a phone.
- Include rule-only securities absent from the research catalog; establish their baseline rather than invent past research. Above-direction alerts do not automatically mean buy. A previously entered zone still merits an incremental review today; do not require a newly inserted alert event.
- Honor the monitor's configured leverage-scaled buffer and explicit per-rule override. A larger buffer expands the approach classification, not intrinsic value or the recommended allocation.
- Keep every missing, stale, expired, split-invalidated or otherwise unevaluated rule in the coverage report. Partial price coverage permits research on valid names, never a claim of complete coverage or zero hits.
- Freeze stable sorted jobs and bounded batches from configuration. `batch_size`/`max_concurrency` describes research work; `tranche_weight` describes portfolio sizing. They are different fields. Do not process only the first batch or omit failed names.
- Resume matching unfinished ticker work from checkpoints. A completed session publication key suppresses duplicate output even if configuration changes afterward; an intentional correction must link to the superseded publication and identify the changed inputs. Input-specific attempt IDs preserve recalculation provenance without bypassing publication deduplication.

## 3. Evidence delta before expensive reconstruction

### Native per-ticker orchestration

When `research.daily_triggered_review.orchestration_policy_version` is
`2026-10-20-native-ticker-1`, use the configured native subagent topology:

```json
{
  "engine": "native_subagents",
  "orchestrator": "single_parent",
  "unit": "ticker",
  "max_active_ticker_pipelines": 3,
  "independent_review": true,
  "shared_db_writer": "orchestrator_only",
  "per_ticker_checkpoints": true
}
```

The single parent freezes and validates the plan, then assigns **one ticker to
each native child research pipeline**, retaining the exact checkpoint key,
baseline document/model references, input revisions, evidence cutoff and required
research profile. Do not substitute one broad industry child for the per-ticker
pipelines. Limit active ticker pipelines to the minimum of available native
capacity and `max_active_ticker_pipelines`; that limit may not exceed either
`batch_size` or `max_concurrency`. Queue every remaining ticker and retain explicit
status for failures. Shared industry evidence may be reused with provenance, but
each ticker still needs its own value-capture, valuation and portfolio reasoning.

Children use task-specific result/checkpoint files and return research plus
actual computation/check outputs. They **must not write the shared research or
alert database**, change configuration, send notifications or edit alert rules.
The parent performs independent review using a reviewer that did not author the
result, returns material findings for correction, and validates the final merged
result against the full frozen plan. A missing child result is an explicit
partial entry, not an omission. Passing the structural validator is not a
substitute for independent source/model review.

Only the parent writes reviewed evidence/assessment revisions through
`research_store.py` atomic commits, with expected revisions and immutable request
IDs, reads back those results and performs guarded persistent upload. Persist
per-ticker checkpoints before publication, so a stopped batch resumes without
discarding completed work. Price summaries remain independent. A native-agent
capability failure is reported as a partial orchestration failure; never claim
parallel execution from JSON configuration alone. Older configurations without
the version field retain their previous execution contract; the versioned policy
requires the full orchestration object and validates it before source calls.

For **each** selected ticker, locate the exact latest security-specific report/section, evidence cutoff, assumptions, model artifact and prior recommendation. Recover actual saved model checkpoints. A mention, old price target, filename or proposed position is not a complete baseline or executed holding.

The saved research database/catalog is an index into the inherited research, not a substitute for it. **Open and read the exact prior source document(s) and model**, including the relevant section and its references; catalog summaries or search snippets alone do not satisfy baseline recovery. Record artifact IDs, retained versions, section/page locators, actual evidence/valuation cutoff, original thesis, original EV definition/assumptions and prior entry/tranche proposals. Resolve section-level supersession in cumulative reports rather than blindly selecting the newest filename. Distinguish `baseline_unavailable` (we could not recover/read it), `not_previously_researched`, and `company_not_disclosed` (the checked company sources do not disclose it); inability to find a document is not evidence the company withheld the metric. Preserve original records and mark an explicit successor revision when new research changes them.

Run an incremental primary-source search from its prior evidence cutoff through this run's frozen evidence cutoff, including contrary evidence and scheduled catalysts. Unknown cutoff requires a disclosed catch-up window. Record sources actually checked, publication/retrieval times, reporting periods, claim locators and gaps. Deduplicate repeat coverage of the same filing, announcement or study; a republished old story is not a new fundamental change.

Every job records:

1. **What changed:** new reported facts, management claims, technical evidence, estimate revisions or no material change found within checked scope.
2. **Financial transmission:** technical/adoption change → affected billable volume/mix or competitive position → realized pricing → variable and fixed costs, lost legacy revenue, SBC and reinvestment → owner profit/cash flow per share. Identify which link is observed, inferred or unsupported; include magnitude/range and horizon where defensible.
3. **Market baseline and variant:** dated accessible expectations, or a clearly labeled reverse-valuation implication if consensus is unavailable; how our view differs; why public information is not already reflected. Public growth news by itself is not alpha. Sources/analytical depth may support an edge but do not prove mispricing.
4. **Unrealized potential:** catalyst, realization window, measurable signpost, competing explanation, and falsifier. Test who captures the surplus and whether usage improves or compresses profit. Strong monopoly assertions require evidence of economic replication barriers and pricing power, not market-share adjectives.
5. **Decision impact:** which model inputs change and why; what would reverse the conclusion; credibility based on independent evidence quality and coverage, not number of repeated articles or complexity of prose.

Allowed edge outcomes include `supported_variant`, `plausible_unproven`, `already_priced`, `no_new_edge_found`, `negative_edge` and `insufficient_evidence`. **Do not require positive alpha for every ticker.** No new evidence is not proof of no change. Logical links must be testable; elaborate chains do not compensate for weak support.

Reuse a valid model when assumptions remain applicable; refresh price/time and run the needed checks. Perform deeper company/fund work when a material driver, thesis, instrument mechanic or model validity changes, or no adequate baseline exists. A previously unsupported model does not become valid because today's search found no new news. Do not repeat a complete report merely to fill a daily template.

## 4. EV and allocation gates

Use the existing full research harness and model execution contract for completed recommendations. For ordinary companies, maintain the appropriate cyclical/growth/capital-intensive model and owner-cash/share treatment. For leveraged funds, verify issuer benchmark, leverage/reset, costs and wrapper risks, then model path-dependent net returns; use the leveraged-fund policy's trend/chop/crash/recovery regimes, probability uncertainty, mean/median/log outcomes and tails. Do not multiply an underlying stock price target by the leverage ratio.

- Run the fixed-order EV bridge from the weekly contract: **price/time → new fundamentals → model corrections → judgment**. Attribute differences; do not call a math repair new alpha. Show the metric definition and horizon, calibrated versus judgmental weights, downside, expected outcome and sensitivity to disputed assumptions. Distinguish fair value, hurdle-based entry and terminal wealth.
- Python must recompute scenario aggregates and check finite values, probability totals, units, timing and consistency. The structured validator supplements, not replaces, the research harness's model, source and independent-review gates. Passing field checks does not prove a real model was executed.
- Missing prior model: recover or reconstruct and independently reconcile; if impossible, build a properly scoped fresh baseline through the full pipeline. Until validated, numeric EV/precise sizing remains null with the missing inputs. Never fill a required numeric field with invented estimates or label uncomputed EV unchanged.
- State business quality, valuation and portfolio fit separately. Possible actions: add candidate, hold, wait, reduce candidate, exit candidate, research only. More favorable evidence can still imply wait at an expensive price.
- Use only verified dated holdings, NAV/cash and correlated exposures for personalized incremental weights. If unavailable, report **conditional target ranges and tranche illustrations**, not exact current holdings or executable quantities. Common semiconductor, memory and leveraged exposure must not be treated as independent bets.
- Propose multiple entry/alert tiers only if justified by model/risk sensitivity. Each proposed tier includes direction, price or bounded range, required evidence, confidence basis, incremental portfolio-weight tranche, cumulative target/maximum exposure, invalidation and review expiry. Explicitly distinguish alert levels from validated buy ranges. Do not force a fixed number of tiers or equal tranche sizes.
- Alert edits, trades, holdings changes and automatic thesis-membership changes are **not authorized**. Save proposals with old/new values and rationale. Never turn a proposal into an enabled JSON rule automatically.

## 5. Checkpoints, publication and phone output

Use the durable [TaskQ contract](task-queue.md) and `scripts/task_queue.py` for long per-ticker work. This is a SQLite task ledger, not another model executor or always-running service. The native parent alone dispatches child agents and writes the shared database. A queue attempt may finish with a partial research result; queue completion never certifies a buy recommendation.

Across separately restored remote copies, SQLite alone is not a global lock. Before dispatching claimed work, the parent must successfully persist the claim with the retained remote version guard. A conflict requires reload and re-claim, not dispatch from the losing copy. Persist renewals/checkpoints, reread the current lease token before committing results, and reconcile unrelated database changes. Do not claim exactly-once external delivery from queue leases or a successful database save.

Checkpoint at frozen plan, evidence delta, model computation and reviewed result. Use the saved research database/run ledger with immutable attempt IDs and input hashes; retain per-ticker statuses, checks/errors, source/model references and prior-run links. Preserve unrelated research and historical records. Use `niulai_state.py record-run` for the actual final run record, not a fabricated completion. Save detailed artifacts and databases to their existing persistent identities where applicable with fresh version guards; new reports require actual saved receipts. Never put private data in Skills git.

Use `scripts/research_store.py` for additive evidence/assessment CRUD on the **restored research database only**: `commit --db research.sqlite --file REQUEST.json`, `read --db research.sqlite --id ID [--revision N]`, and `export --db research.sqlite [--ticker SYMBOL]`. A commit request has `request_id`, `run_id` and atomic `operations`; each operation has `id`, `ticker`, `kind` (`evidence` or `assessment`), `expected_revision` (0 for create), `action` (`put` or `retract`) and its structured payload. Supply a reason for a retraction; it is a tombstone, not erasure of research history. Referenced evidence uses exact ID/revision pairs. Assessment `baseline_refs` must retain the exact old documents/model references and `input_revisions` must record frozen inputs. An explicit `no_new_evidence_reason` explains checked scope and search gaps; it is not permission to skip source research. Read back committed revisions before guarded persistent upload. This local transaction API does not itself save the remote database, satisfy a model gate or prove delivery. On a remote version conflict, recover the latest database, reconcile revision conflicts and replay only still-valid operations; never overwrite concurrent changes.

Before publishing, reread source/config/research revisions. Reconcile concurrent updates rather than overwrite; recalculate affected jobs or label the frozen historical cutoff explicitly. Track evaluation, persistence, publication and device delivery separately. Native final output is the notification channel; it does not prove phone receipt. Do not create a second sender or call Studio.

The Chinese phone summary leads with **actionable changes**, then wait/reduce findings and coverage. Each researched ticker has a compact row in the full saved output: snapshot price/time and hit classification; prior versus current thesis; new favorable/unfavorable evidence; alpha status; model/EV and downside; action and conditional tranche/total weight; proposed tiers; confidence, invalidation and next check. The phone may show the most important few with a link to the complete roster, but every planned name must have completed, unchanged-within-checked-scope, partial or failed status and reason. Do not call a job complete merely because it was queued.

If no qualifying names exist and coverage is complete, follow the role's quiet policy. If many names are reached but no new edge is found, summarize that honestly rather than generate long repeated stories. If some jobs cannot finish, publish an explicit partial result and persist the remainder for recovery; never claim all-name completion. The independent price summary must not be blocked by this slower research.


## All-selected completion requirement

Apply [TaskQ production completion and continuation gate](task-queue.md#production-completion-and-continuation-gate) on every run. Bounded batches limit simultaneous workers, not selected coverage. The parent must continue every selected ticker and repair fixable partials; a completed worker attempt, three pilot tickers, or a saved checkpoint does not finish the research run. Reuse the full research harness and independently reviewed evidence/model artifacts. Return complete only after all expected names pass their applicable decision and persistence/readback gates; supported no-buy/hold decisions are valid. Irreducible external blockers stay explicitly blocked with actual recovery-attempt evidence, never fabricated certainty. Preserve unfinished work across interruptions and resume it.
