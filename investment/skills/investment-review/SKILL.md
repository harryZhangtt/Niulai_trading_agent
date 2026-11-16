---
name: investment-review
description: Review an investment using this repository's existing research, source acquisition, data-quality checks, AI Berkshire methodology, models and completion gates. Use for a company or fund review, thesis reassessment, valuation update or an explicitly bounded evidence review.
---

# Investment review

Carry the user's request through the existing research workflow in the current
agent session. Reuse valid work and continue through the authorized stages without
asking for permission at each stage. This entrypoint supplies instructions; the
existing tools perform acquisition, calculations and validation.

## Resolve the workspace and scope

Resolve this file's canonical location before following relative links, including
when loaded through `.agents/skills/`. Its repository root is three directories
above this directory. Read [workspace instructions](../../../AGENTS.md),
[investment instructions](../../AGENTS.md), the
[source-coverage contract](../../research/README.md), and the existing
[investment research adapter](../../../niulai/skills/investment-research-financial-services/SKILL.md).
Follow their applicable requirements; historical upstream installation, global
path, schedule or publication instructions do not expand workspace authorization.

Resolve the security, instrument, decision question, horizon and actual cutoff
from the request and existing context. Ask only for a materially blocking unknown.
An unqualified investment review uses the full applicable company/fund profile;
an expressly bounded factual or evidence-delta request retains its narrow scope
and cannot claim a completed full recommendation.

Locate the matching saved thesis, model, source receipts and unfinished run using
the existing catalog and state interfaces. Check their identity, dates and hashes
before reuse. Resume matching work; invalidate affected downstream results when
inputs change. Missing saved work is a disclosed gap, not permission to invent it.

## Execute the existing pipeline

1. Record the request, profile, cutoff, run identity and remaining work in the
   existing versioned research-run contract. Keep private records and checkpoints
   under a new approved private directory in
   `.niulai-state/reports/investment-research/`, using the existing artifact writer.
   Preserve historical records, unknown-outcome fences and unrelated runs.
2. Before new retrieval for full company research, use `investment.research freeze`
   to freeze the material claim/source requirements. Retain its expected hash in
   the coordinator contract separately from author/retrieval output. Use `routes`
   to select useful supported capabilities. Apply the reviewed issuer/profile
   rules in `investment/AGENTS.md`; unavailable coverage remains a gap and must
   not silently weaken the frozen requirements.
3. Reuse eligible dated sources first. Acquire missing original documents through
   [shared source tools](../../../shared/research_sources/README.md) and the
   [existing web routing](../../../docs/web-search-routing.md) as needed, including
   contrary evidence. Check availability/cutoff before exposing cached or fetched
   content to analysis through the applicable temporal guard. Preserve raw/text
   hashes, actual passages, versions, times, source lineage and applicability
   limits. Search snippets, catalog plans and provisional labels do not establish
   document reading, factual support or independent corroboration.
4. Execute the applicable research subjects and policies in the investment
   adapter. Explicitly read and apply the bundled
   [AI Berkshire workflow](../../../niulai/skills/investment-research-financial-services/references/ai-berkshire/WORKFLOW.md)
   and its
   [growth-aware policy](../../../niulai/skills/investment-research-financial-services/references/ai-berkshire/references/growth-aware-policy.md).
   Use the repository's policy version by default, with `strict-upstream` only on
   explicit request. Load additional financial-services workflows only as needed.
   Record exact dependency versions/hashes and their actual evidence/model
   applications using the existing rationale/provenance contract.
5. Apply the adapter's data cross-checks and preserved financial-rigor/calculation
   helpers to decision-critical numbers. Reconcile units, currency, periods,
   definitions and source dependence. Bind each material evidence item to the
   actual model parameter and explain a changed, unchanged or bounded effect.
   Recompute affected scenarios, sensitivities and valuation/entry comparisons.
   Keep fair value, return-hurdle entry price and model-implied expectations
   distinct. Inactive shared-calculation or acquisition candidates require their
   own evidence; do not present their installation as active integration.
6. Use a separate native agent or available independent reviewer to inspect the
   actual sources, numerical outputs, model assumptions and reasoning. Preserve
   the real review, exact input hashes, findings and corrections. An unavailable
   reviewer or unresolved material finding leaves the result partial. Never
   fabricate approval or treat the author's self-review as independent review.
7. For a full company run, execute `investment.research assess`, then use the
   maintained `pipeline.finalize` and `pipeline.complete` entrypoints (or their
   CLI operations) with the pinned contract and actual packet. They compose source
   coverage with the preserved Niulai validators. Never invoke legacy finalization
   directly to bypass coverage. For a fund or narrow scope, use its applicable
   adapter gates; unsupported source-profile coverage stays explicitly unverified.
   Required persistence needs actual authorized save receipts and exact readback;
   without them deliver an unsaved draft/partial result.

Run existing Python operations from the repository root with
`.research-sources/.venv/bin/python -B -m investment.research`; use the operation's
documented JSON request and output arguments. Reuse existing local dependencies
and cache paths. Do not add another executor or install global packages.

## Finish or leave a recoverable partial result

Deliver the supported decision, changes from the prior thesis, valuation basis,
strongest contrary case, decision conditions and remaining gaps. Link the actual
report, model and evidence artifacts. Report `complete`, `partial` or `failed`
according to observed gate results, with source/quote cutoff and method versions.
Before ending unfinished work, save the last verified stage, current inputs and
hashes, attempted actions, unresolved dependency and next action in the run record.
Resume from that checkpoint on the next invocation after checking for drift.

Invocation authorizes the requested research and scoped local artifacts. External
publication, email, trades, holdings changes, schedule activation and host settings
retain their existing owner/authorization boundaries. This skill creates no
background continuation. New major runtime claims still require the workspace's
future-triggered acceptance and verified email evidence.
