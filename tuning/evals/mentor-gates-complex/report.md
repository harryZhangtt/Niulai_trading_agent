# Complex quality-gate effectiveness screen — 2026-10-30

The explicit promotion-gate reference handled all eight fresh complex cases and
all four matched contrasts. The matched background-skill control missed one
disposition label and one part of the recovery action. This is narrow observed
benefit on these cases, not evidence of general or long-session superiority.

| Outcome | Existing evaluation skill without explicit gate | Same skill with explicit gate |
| --- | ---: | ---: |
| Correct accept/reject/inconclusive verdict | 7/8 | 8/8 |
| Correct decisions for both members of a pair | 3/4 | 4/4 |
| Evidence, scope and next-action score | 47/48 | 48/48 |
| False acceptance | 0 | 0 |
| Valid accept case wrongly rejected | 0 | 0 |
| Fabricated evidence IDs | 0 | 0 |
| Critical unsupported scope/object claims | 0 | 0 |

## What the difficult cases tested

| Pair | Evidence held constant | One changed fact | Expected decisions | Control | Gate |
| --- | --- | --- | --- | --- | --- |
| Scope transport | Eight correct helper fixtures, valid timing receipt, empty prospective panel, misleading 98/100 readiness | Requested helper adoption versus selection-alpha adoption | Accept / inconclusive | Both correct | Both correct |
| Evaluated object | Reproduced grader field-name bug, impossible 13/12 score, twelve unjudged prompt outputs, favorable dashboard | Grader correctness versus prompt performance | Reject / inconclusive | Both correct | Both correct |
| Missing evidence plus material defect | Missing R10, 32 known rubric points, R07 claims 118/18%, authenticated revenue table and manager pressure | Cited table's FY2025 revenue is 108 versus 118 | Reject / inconclusive | Reject / reject | Both correct |
| Publication cutoff | Correct copied figures, authenticated revision, historical membership and unrelated 94% dashboard | Source first public 13:45 versus 14:15, around a 14:00 cutoff | Accept / reject | Both correct | Both correct |

All issuers, versions, dates and records are synthetic. Public case data contains
artifact excerpts, not the answer key. Separate author and reviewer passes checked
arithmetic, IDs, ambiguity and one-public-field contrasts before freezing the suite.
The verdict balance was two accept, three reject and three inconclusive, so always
blocking acceptance cannot pass.

## The observed difference

For `complex-06`, R07's revenue and growth match its source, but R10 has no output
or source join. The control correctly recognized the missing evidence and blocked
adoption, yet called the incomplete recorded panel `reject`. It explicitly avoided
claiming the generator was factually defective. The gate instead said
`inconclusive`: missing evidence blocks acceptance without establishing a quality
violation. Thus this was a disposition/terminology difference, not unsafe acceptance
by the control or proof that the gate prevented a real candidate from being discarded.

The blind reviewer also identified a small action gap. The control said to obtain
“only” R10's missing output, source join and rubric assessment. R07's rubric grading
was also unfinished. The gate requested completion of missing grading before
reassessment. Root review agreed with this bounded 1-versus-2 action score; the
remaining evidence and scope reasoning was correct in both responses.

The material-error counterpart demonstrates precedence: 118 claimed against an
authenticated 108 is a EUR 10 million discrepancy under a EUR 1 million tolerance.
That observed failure justifies rejection despite missing R10. When the source
instead says 118, the observed failure disappears and incompleteness remains.

## How the existing skills improved construction

- **Experiment design:** declared competing explanations, a matched gate-reference
  ablation and one decisive change per case pair. The favorable summary remains
  constant, so it cannot explain the correct verdict flip.
- **Evaluation design:** separate verdict correctness, evidence grounding, scope
  and next action; include valid positive cases; freeze keys before model answers;
  blind and shuffle answers for the grader; keep alternative valid reasoning creditable.
- **Evidence/overfitting guidance:** distinguish publication time from reporting
  period and retrieval time, valid artifact proof from outcome evidence, and
  unavailable observations from demonstrated failure.

The detailed reusable recipe and exact existing references are in `construction.md`.
The independent author's construction receipt and pre-run review are preserved in
`author-construction.md` and `case-review.json`.

## Execution, cost and limits

Sixteen fresh-context solver responses: eight cases × two conditions, same inherited
GPT-6.1 Sol model/settings and 180-word cap. Conditions differed only in the
promotion-gate addition/reference. Routing was held fixed, and skill text was not
edited during the screen. All sixteen outputs parsed, cited existing evidence IDs
and respected the cap; no solver answer was rerun or dropped.

A separate same-family grader passed good/bad calibration anchors before grading
anonymized shuffled answers. Root reviewed all sixteen responses, the one verdict
discrepancy, arithmetic and the secondary-score gap. Grading was based on the
declared rubric and pre-freeze cautions, not on preferred wording. Read/write
restrictions were instructions, not a secure evaluator sandbox.

The gate added 476 serialized instruction tokens per case using the existing
`o200k_base` proxy: 37,128 versus 33,320 across the eight cases, an 11.43% increase.
This is not billed-token or latency telemetry. The small reference should remain
conditional on an adoption decision rather than loaded for unrelated mentor work.

One sample per condition/case, four related case families, synthetic artifacts and
same-family model grading do not support a statistical or population reliability
claim. The result supports keeping the explicit object/scope and evidence-state
distinction; it does not justify expanding the rule set or declaring the full
mentor package proven effective. No skill or routing change was needed in this run.
Future live tuning tasks should record whether the gate changes an actual next
action and whether completed artifacts support that decision.

## Artifacts

- `protocol.md`: frozen hypotheses, comparison, grading and budget.
- `cases.json`: public situations and separate gold keys; now development evidence.
- `results.json`: all responses, case-level scores, evidence excerpts and aggregate results.
- `prediction-rival-matrix.csv`: upstream-template design matrix. The bundled
  validator requires an explicit negative-control ID and was inapplicable here;
  its unsuccessful attempt is retained, not presented as a scientific validation pass.
- `prepare.py` and `summarize.py`: packet freezing and offline artifact checks;
  workers were dispatched separately, not by a new agent service.
- Local raw packets, manifests, calibration and grades:
  `tuning/runtime/mentor-gates-complex-v1/` from the workspace root.

To recheck the retained artifacts, run `summarize.py` in the existing workspace-local
validation environment with the tokenizer cache under `tuning/runtime/`. The
checks verify hashes, coverage, shapes, IDs and arithmetic; they do not independently
prove the semantic answer key.
