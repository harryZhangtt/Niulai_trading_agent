# Complex quality-gate draft construction

These eight synthetic cases were constructed from only the four assigned references: `hypothesis_quality_criteria.md`, `experimental_design_patterns.md`, `investment-context.md`, and `promotion-gate.md`. No prior cases, results, private data, or investment snapshots were consulted. All companies, contracts, versions, receipts, metrics, and timestamps in the cases are fictional.

The draft applies these upstream principles:

- Identify the exact object and scope before making a decision; evidence for a helper or research-quality gate does not establish selection alpha.
- Freeze criteria before the represented run. Give numerical criteria local operational meaning rather than treating them as universal quality scores or sample-size guarantees.
- Align each claim with direct evidence, source identifiers, versions, units, and as-of dates. Distinguish authenticated publication time from reporting period end and current retrieval.
- Preserve missing outputs and failed attempts. Missing evidence blocks acceptance without proving poor performance; a valid decisive critical violation can still justify rejection when missing evidence coexists.
- Treat deterministic grader correctness separately from prompt performance. An injected grader fixture is not an observed worker mistake, and invalid score artifacts cannot contribute favorable scores.
- Separate reproducible deterministic checks, repeated timing measurements, historical development evidence, and prospective outcomes; recognize dependence and model-weight contamination.
- Include distractors such as composite readiness scores and manager claims without making them valid evidence. Require calibrated claim boundaries and the smallest appropriate repair.

Each pair changes exactly one public leaf: requested scope, evaluated object, one source revenue value, or one publication timestamp. Contracts and other public artifacts are identical within pairs. Gold labels are two accept, three reject, and three inconclusive. Gold reasoning and prohibited claims are separate from each case’s `public` solver data. Local construction checks verified shape, label coverage, evidence references, 250–450-word public-data length, and one-leaf pair differences. No solver, grader, or model evaluation was run. The temporary construction script was removed. These are draft materials, not executed evaluation results.
