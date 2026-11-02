# Evaluation contracts

For evaluation, benchmark or promotion claims, read mentor/AGENTS.md and the
local evaluation-design skill. Separate development conformance from blinded
reasoning tests and prospective investment validation.

Use `tuning/evals/evidence_runtime/contracts.py` for new comparable runtime
rounds: seal inputs, expected outcomes, complete case roster, grader source
closure, required metrics, critical failure rules, identical per-arm budgets and
candidate fingerprints before dispatch. Validate the sealed contract at begin
and finish. Register every attempt before work; never overwrite a failed/unknown
attempt, remove a hard case, change its criticality after results, or compare
arms using changed inputs/graders/budgets. A change starts a new contract version.

The actual host-side completion path must invoke the gate; a document or a model
claim is not enforcement. Use independent state/source checks. Worker submissions
contain evidence references, not authoritative pass labels. A critical case
failure cannot be averaged away. Unknown tokens/cost stay unknown. Direct unit
checks remain ordinary development evidence and cannot stand in for this gate.

The current earnings/source/cache round is development/unblinded. Packet-level
answer separation does not provide OS access isolation. Do not label it blind,
claim unseen-case generalization, or infer alpha from conformance. Protected
validation needs an actual inaccessible answer/grader boundary and new cases;
postpone that stronger claim until the integration supplies it.
