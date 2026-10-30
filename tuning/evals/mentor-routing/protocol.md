# Mentor guidance and routing screening v1

Frozen before model responses on 2026-10-30. Exploratory development evaluation.

Decision: do the five imported skills improve concrete mentor guidance, and can
selective skill loading reduce instruction context without a visible quality loss?

Four synthetic cases cover experimental attribution, completion/recovery, grader
design and legitimate external dependency handling. They use no holdings,
investment holdouts or existing `mentor/tests/scenarios.md` case text. The case
author knows the rubric, so these are not an independently held-out benchmark.

## Conditions

- General baseline: common mentor scope/minimum-change/recovery policy, no full
  skill body. This is a strong existing-policy baseline, not a model with no guidance.
- Current: same policy plus the current always-on supervisor and evidence skills,
  and the specialist named by each case. Include required local context references.
- Candidate: same policy plus a compact routing contract and only case-relevant
  full skills/local contexts. No upstream skill is deleted or shortened.

All conditions use the same model, reasoning setting, case, 220-word maximum and
tool restrictions. Each response starts in a fresh worker with no conversation
history. Only its packet and output file may be read/written. This is an
instruction-level isolation boundary; workers retain tool capabilities. Audit
visible worker activity and disclose any violation. No web access is needed.

The case-to-skill mapping is chosen by the author before outcomes. Therefore this
tests the quality/cost of those subsets, not the accuracy of an autonomous router.
The proposed natural-language router will receive a separate blind selection test
before any adoption. Skill references beyond entrypoint and required local context
are not loaded in this bounded text-only screen; no tool execution benefit is tested.

## Grading

Keep arm identities hidden from the grader and randomize response order per case.
Use the four case-specific criteria in `cases.json`, each scored:

- 0: absent, wrong or contradicted;
- 1: partially addresses it but leaves a material decision/action gap;
- 2: concrete, correct and useful for the next tuning decision.

Maximum: 8 per case, 32 per arm. Record exact output evidence for every score and
each critical failure. Critical failures block adoption regardless of mean score.
The grader must correctly grade two obvious calibration anchors before scoring
real responses. Review arithmetic and critical failures independently at the root.
Same-family judging remains a limitation, not human calibration.

## Cost and acceptance

Measure serialized instruction-context size with `o200k_base`; label it a tokenizer
proxy, not billed/model telemetry. Report output length separately. Shared provider
instructions, reasoning tokens, caching and tool overhead are not measured by this
proxy. Do not claim wall-time improvement from parallel dispatch timing.

Candidate routing may become the provisional default only if:

1. No critical failure and no case score below the current condition.
2. At least 30% lower aggregate loaded instruction-token proxy across these cases.
   This is a practical context-reduction target, not a statistical threshold.
3. The blind route-selection screen includes all explicitly necessary specialists,
   avoids unnecessary full skills on a routine non-mentor case and handles overlap.

If current/candidate do not clearly beat the general baseline, report that skill
effectiveness is unproven. Do not tune to these cases and relabel a rerun as fresh
validation. If a material regression occurs, retain current routing and document it.

Budget: twelve short solver responses (four cases × three conditions), one blind
grading pass and one independent routing pass; no retry unless a response is absent
or malformed. A surprising borderline result remains inconclusive rather than
triggering a large sweep. This screen measures next-step guidance, not long-session
drift, actual experiment execution or investment profitability.
