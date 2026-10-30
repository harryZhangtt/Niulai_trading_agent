# Constructing discriminating mentor-gate cases

The useful unit is a decision that could go wrong for a specific reason. A long
story alone does not make a good hard case. This screen uses complicated evidence
around a small, checkable decision and keeps the decisive contrast identifiable.

## Existing skills applied

| Existing resource | Method used here | Concrete artifact |
| --- | --- | --- |
| `mentor/skills/experiment-design/references/hypothesis_quality_criteria.md` | State a falsifiable mechanism and rival explanations; do not equate an elaborate mechanism with evidence. | Protocol separates gate benefit, already-sufficient background guidance and blanket refusal. |
| `mentor/skills/experiment-design/references/experimental_design_patterns.md` | Matched comparisons, controlled intervention, measurement validity, positive controls and applicability limits. | One changed decisive fact per pair; identical model/context except the explicit gate reference; valid accept cases. |
| `mentor/skills/experiment-design/references/preregistration_and_open_science.md` | Freeze hypotheses, interpretation rules and expected outcomes before the observed results. | Hashed reviewed cases, protocol, exact guidance and immutable packets. Any later alteration is a new development revision. |
| `mentor/skills/evaluation-design/SKILL.md` and local investment context | Assess outcomes and evidence separately; keep critical failures visible; use realistic negative and ambiguous situations. | Exact verdict checks, wrong-object and false-acceptance accounting, plus separate evidence/scope/action scores. |
| `mentor/skills/evaluation-design/references/promotion-gate.md` | Distinguish evaluated object and scope, observed failure and missing evidence. | Case families contrast scoped adoption, grader correctness, prompt performance and evaluation-pipeline validity. |
| Evidence/overfitting local guidance | Preserve temporal provenance and exposure history; do not claim a repeatedly consulted case is untouched. | Artifact timestamps and versions, fresh synthetic cases, all attempts retained, no investment holdouts. |

The test reuses these procedures rather than adding a new evaluation framework.
The bundled prediction/rival CSV template also structures `prediction-rival-matrix.csv`.
Its validator was tried but requires a nonempty negative-control ID. This screen
has no separately designed negative-control intervention, so the validation
attempt is recorded as inapplicable. We do not invent an ID for a passing report.
The matched no-gate comparator and positive accept cases serve their stated roles.

## Case recipe

1. **Name the exact decision.** "Should this grader version be accepted?" and
   "Has this prompt improved?" can require different answers from the same logs.
2. **Write the acceptance contract.** Identify required evidence and the meaning
   of a critical failure. Keep it plausible for the task; do not add a generic
   sample-size or quality-score threshold after seeing results.
3. **Provide evidence, not the conclusion.** Use case IDs, source excerpts,
   commit identities, timestamps and artifact inventories. A dashboard saying
   "passed" is a claim to audit, not the answer key.
4. **Add competing signals.** Favorable averages, a confident manager note or
   completed auxiliary tests make the decision realistic. They must not silently
   alter the acceptance contract.
5. **Make a matched counterpart.** Change the tested scope, object, decisive source
   excerpt or publication timestamp. Keep the remaining artifacts identical.
   Complex background can remain; only the reason the decision should change varies.
6. **Derive the key from the artifacts.** Store decisive evidence IDs, required
   reasoning, allowed claims and prohibited extrapolations outside solver packets.
7. **Audit ambiguity before freezing.** An independent reviewer checks whether a
   second defensible verdict exists, whether numbers/IDs agree and whether the
   pair changed more than intended. Repair design defects before any solver sees it.
8. **Test behavior without revealing the key.** Fresh solver context for each
   case/condition, fixed output budget, blinded grading and no skill changes mid-run.
9. **Inspect both answer and reason.** A correct label with fabricated evidence
   or a wrong-object conclusion fails the grounding/scope check.
10. **Preserve misses and limit the claim.** New failures identify the next
    hypothesis; rewriting the same key to fit an answer does not validate a gate.

## What makes the results interpretable

The accept/reject/inconclusive balance prevents a blanket refusal strategy from
passing. Paired changes reveal whether the response follows the decisive fact.
The matched gate-reference ablation separates marginal gate guidance from the
background skill. Artifact-based answers are more informative than citation count
or prose confidence, while the blinded reviewer helps catch surface grading.

These controls still do not create population-level reliability estimates.
The cases are authored synthetic situations, each sampled once per arm. A clean
screen supports these specific behaviors; live tuning execution and long-session
effects require separate evidence.
