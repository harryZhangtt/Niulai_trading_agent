---
name: evaluation-design
description: Design or review agent evaluations, grading rubrics, baselines, data splits, and promotion criteria for investment-agent tuning and mentor supervision.
---

# Evaluation design

Produce the smallest evaluation that can inform the requested decision. Keep
design guidance here and executable cases/graders in workspace-local `tuning/evals/`
when needed. Do not create a framework, new agent, or dependency by default.

## Define the decision

Identify the behavior being measured, intended users/cases, baseline, candidate
change, and what evidence would justify adoption. Separate:

- Alpha discovery: evidence correctness, falsifiable forecasts, calibration, and
  incremental selection value against a declared benchmark and horizon.
- Entry policy: incremental decision value with the candidate stream fixed,
  accounting for costs, unfilled orders, waiting, and missed opportunities.
- Mentor behavior: verified progress, useful recovery, justified escalation,
  correct completion, and resource consumption.

Hold entry behavior fixed when testing selection; hold selection fixed when
testing entry. Evaluate their interaction later. Research quality is not proof of
investment alpha. Evaluate realized outcomes prospectively when necessary.

## Choose cases and grading

Use cases drawn from the intended workload and observed failures, including
ambiguous and negative cases. Start small, then expand only when uncertainty or
coverage affects the decision. Include at least a contrasting case for a proposed
behavioral rule: recovery should work when an authorized alternative exists;
escalation should work when a necessary dependency is genuinely unavailable.

Use deterministic checks for verifiable properties. Use anchored rubrics for
judgment; calibrate model graders against independently reviewed examples before
relying on their scores. Blind candidate identity/order where practical. Do not
grade eloquence, verbosity, self-reported confidence, or agent consensus as truth.
Check source support, not merely the presence of citations.

Evaluate both outcome and relevant trace evidence. Penalize fabricated evidence,
false completion, and pointless repetition; do not reward persistence by itself.
Keep correctness and evidence failures visible rather than averaging them away
with speed or style. Report cost separately alongside quality.

## Protect inference

- Define metrics, failure gates, budget, and acceptance rule before results.
  Distinguish exploratory work from confirmatory tests; do not invent numerical
  cutoffs or sample-size confidence unsupported by the data.
- Keep development, validation, and protected tests distinct. The evaluated worker
  must not edit its grader or acceptance rules or inspect protected answers.
  Instructions alone do not enforce isolation: state whether the runner actually
  restricts access. Material already visible in context is not a blind holdout.
- Record every tried variant, including prompts, model/tool changes, failed runs,
  and evaluation changes. Repeatedly consulted tests become development evidence.
- For historical finance cases, use information available at the decision time,
  including publication lags, revisions, historical membership, and delistings.
  Date-filtered retrieval does not erase future knowledge in model weights.
  Label that contamination risk; use prospective evaluation for stronger evidence.
- Compare candidates on matched cases and comparable resource budgets. Repeat
  stochastic runs when variability could change the conclusion. Account for
  temporal or company-level dependence rather than treating all rows as independent.
- Report effect size and uncertainty appropriate to available data and number of
  comparisons. A small smoke test verifies basic behavior, not general superiority.
  Permit an inconclusive result. Promote only on evidence meeting the stated rule.

## Deliverable

Provide a concise evaluation specification containing:

1. Decision, baseline, candidate, and hypothesis.
2. Cases, provenance, as-of dates where relevant, and split/access boundaries.
3. Metrics, grader/rubric, critical failure gates, and grader limitations.
4. Resource budget, comparison method, acceptance and stopping rules.
5. Results when run: artifacts, failures, uncertainty, and adopt/reject/inconclusive.

Adapt detail to the task; a short document or table is sufficient. Do not claim
tests ran or isolation exists merely because the specification describes them.
