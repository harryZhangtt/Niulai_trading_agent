---
name: experiment-design
description: Turn agent-tuning proposals into bounded falsifiable experiments with a baseline, controlled changes, measurements, and stopping rules.
---

# Experiment design

Start with an observed failure or explicitly exploratory hypothesis. State the
mechanism the change should improve and a competing explanation for improvement.
Choose the smallest comparison that can distinguish them. Reuse existing runners.

Specify baseline, candidate, cases, controlled factors, metric, resource budget,
acceptance rule, and stopping rule before looking at results. When measurement
itself is uncertain, use the evaluation-design skill first. Do not create arbitrary
thresholds just to fill a template.

Change one interpretable factor initially. Test interactions deliberately when
the hypothesis requires them; do not claim every multi-factor experiment is invalid.
Use matched cases, comparable compute budgets, and repeated stochastic runs when
variance could alter the decision. Keep selection fixed for entry tests and entry
fixed for selection tests before testing their interaction.

Log all attempts and relevant model/prompt/tool/data versions, including failures.
If results suggest a new hypothesis, register a new experiment rather than
rewriting the original success rule. Use the evidence-and-overfitting skill to
assess support and holdout exposure.

Output a compact experiment specification and, after execution, effect, cost,
limitations, and adopt/reject/inconclusive decision. Stop once the declared
decision has sufficient evidence; avoid building infrastructure speculatively.
