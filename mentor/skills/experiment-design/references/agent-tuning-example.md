# Example: source-grounded retrieval prompt experiment

This is a design example, not a measured result. No investment holdout is used.

**Observation:** Development reviews found unsupported factual statements in
some generated earnings briefs. Record actual case IDs and source locations when
using this design; do not treat this illustrative observation as project evidence.

**Question:** Does requiring source evidence before drafting reduce unsupported
material claims on the intended earnings-research workload at comparable cost?

**Candidates and rivals:**

- H1: evidence-first drafting improves grounding, reducing unsupported claims
  while retaining required coverage.
- H2: apparent improvement is caused by producing fewer claims; coverage falls.
- H3: apparent improvement comes from extra retrieval/token budget rather than
  the prompt structure.
- H4: the judge rewards visible citations even when they do not support claims.

**Discriminating measurements:** Score support per material claim against the
actual source, required-aspect coverage, fabricated citations, tool/token cost
when measured, and source-access failures. A citation-presence count cannot
distinguish H1 from H4. A total unsupported-claim count alone cannot distinguish
H1 from H2. Match resource budgets to investigate H3.

**Design:** Freeze prompt versions, tool configuration, source snapshots/as-of
dates and case strata. Run baseline and candidate on matched development cases;
repeat stochastic cases only when variability affects the decision. Blind grader
labels and swap order for pairwise judgments. Treat company/time clusters as
dependent. Keep alpha selection and trading entry policy unchanged.

**Control:** Add a deliberately mismatched citation to a synthetic brief. If the
grader accepts it as support, repair/calibrate the grader before judging prompts.

**Decision rule:** Before inspecting results, define the workload's tolerated
critical failures, coverage requirement and resource limit with a rationale.
Promote only if the candidate meets them and the comparison supports improvement;
otherwise reject or report inconclusive. Do not fill missing criteria with a
generic 0.7 score or assume that 50 cases guarantee confidence.

**Record:** Use the upstream hypothesis, measurement and prediction-matrix assets
when structured validation helps. Log all variants and deviations; development
cases consulted during editing cannot later be called an untouched holdout.
The validators check declarations and cross-links, not the source support itself.
