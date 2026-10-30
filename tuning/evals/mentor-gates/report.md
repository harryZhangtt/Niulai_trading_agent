# Atomic quality-gate checks — 2026-10-30

Atomic cases revealed one useful ambiguity: a missing required case correctly
blocked acceptance, but the response labeled the candidate `reject` while its
rationale described incomplete evidence. The original screen scored **5/6**
verdicts. No invalid input was accepted.

| Single rule being tested | Positive case | Changed fact | Expected changed verdict | Observed |
| --- | --- | --- | --- | --- |
| Required coverage | All 12 required cases present → accept | C12 grading output missing | Inconclusive | Reject; rationale correctly said incomplete |
| Critical failure dominates mean | All 10 cases, score 0.96, zero critical errors → accept | One verified currency/scale error; score remains 0.96 | Reject | Reject |
| Scoped deterministic check | All six declared states checked once → accept | Repeat the same states ten times | Accept, with unchanged scope | Accept |

The valid small test passed without an invented 50-case minimum. Repeated inputs
were not counted as new coverage or evidence of investment performance.

## Narrow correction and fresh checks

Added `mentor/skills/evaluation-design/references/promotion-gate.md`, linked from
the skill at adoption decisions. It distinguishes:

- acceptance: complete valid evidence meets the declared gate;
- rejection: observed evidence establishes a decisive quality violation;
- inconclusive: missing/invalid/insufficient evidence blocks the decision without
  establishing candidate inferiority.

The evaluated object matters: a broken grader can be rejected while the prompt's
performance remains inconclusive. This prevents a pipeline failure from being
silently converted into either a favorable score or a performance rejection.

The original six outputs and their answer key were preserved. Two fresh situations
were frozen after the correction and before their responses:

| Fresh situation | Expected | Observed |
| --- | --- | --- |
| Eight outputs exist, support 0.94, source checksums unavailable, no observed material error | Inconclusive; obtain provenance | Inconclusive; preserve candidate and recover checksums |
| Eight outputs and provenance verified, support 0.94, independently confirmed material source contradiction | Reject under zero-error rule | Reject for the source contradiction, with a bounded claim |

**2/2 fresh verdicts and reasons matched.** These cases test the identified
distinction; they are not evidence that all gates are reliable or that the new
reference alone caused the difference. The original wording ambiguity remains a
recorded failure, not a passing case after reinterpretation.

## Method and scope

Each case used a fresh GPT-6.1 Sol worker with identical supplied evaluation-skill
context and a 100-word cap. Only the single changed rule varied within each original
pair. Workers received no expected verdicts, prior responses or paired counterpart.
The v2 workers additionally received the explicit promotion-gate reference.
Expected verdicts were frozen before responses, checked deterministically, and
the root reviewed the evidence, rationale and allowed-claim scope in all eight answers.
Read/write restrictions were instructions, not an enforced sandbox.

No real tuning run, investment holdout or trading decision was performed. The
screen tests atomic guidance behavior rather than actual source retrieval, grader
execution or portfolio outcomes. There was no no-skill/upstream ablation in this
atomic screen, so it does not establish a causal effect of a specific skill edit.

Cases, expected outcomes and protocols: `cases.json`, `protocol.md`,
`refinement-cases.json`, `refinement-protocol.md`. All observed answers are retained
in `results.json`; frozen packets and manifests remain in ignored
`tuning/runtime/mentor-gates-v1/`. Run `python3 tuning/evals/mentor-gates/summarize.py`
from the workspace root to recheck the recorded artifacts.
