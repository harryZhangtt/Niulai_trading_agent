# Atomic mentor quality-gate screen v1

Frozen before responses on 2026-10-30. Six fresh synthetic cases in three matched pairs. This tests the adapted evaluation skill's gate decisions, separately from routing and the earlier four-case mentor screen.

Only one fact changes per pair: required-case coverage; presence of a defined critical error while the mean stays fixed; or repeats of an already complete deterministic state set. Required verdicts are accept / inconclusive, accept / reject, accept / accept respectively. These expectations follow declared gates, not an LLM score. All other requirements are explicitly satisfied to avoid hidden scope expansion.

Load the same adapted evaluation-design skill and required investment context for every worker. Hold model, output cap and instructions constant; independent fresh contexts, no earlier case outputs or expected verdicts supplied. Read/write restrictions are instructions, not an OS sandbox. All situations are synthetic; no protected investment data.

Output: JSON with verdict (accept/reject/inconclusive), decisive_evidence, allowed_claim and next_action; at most 100 words. Score the verdict deterministically, then review whether the decisive evidence matches the changed fact and the allowed claim stays within scope. A correct label with a conflicting rationale fails. Never accept a required-case gap or declared critical failure. Rejecting the valid small scoped regression is a false rejection.

Acceptance: all six verdicts correct, every rationale tied to its single tested rule, and the three paired relations correct. No skills or gate instructions are edited after outputs. Stop after six responses, with one retry only for missing/malformed JSON. Failure stays in the result; these cases become development evidence. No baseline/ablated condition is run, so this establishes observed gate behavior only, not that a particular adaptation caused it or that all future gates are reliable.
