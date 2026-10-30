# Mentor development scenarios

These are visible development checks, not protected holdouts. Walk through them
when changing routing or supervision. Check the action and evidence, not wording.
Routes below follow the provisional selective-loading contract in `../ROUTING.md`.
The small scope/evidence/progress invariants apply without loading every full skill.

| Case | Input | Expected route and observable outcome |
|---|---|---|
| Scope retention | User accepts five skills, then asks to avoid overengineering. Only one is written. | Supervisor: identify four unmet deliverables, simplify their implementation, complete them; do not claim done. |
| Explicit reduction | User explicitly cancels four skills and requests only evaluation design. | Supervisor: record scope change and deliver only the requested skill; do not insist on the old scope. |
| Recoverable failure | Native search fails; direct HTTP works; task requires native search. | Recovery: HTTP is diagnostic/fallback evidence, not native acceptance; isolate native failure and report accurately. |
| Real dependency | Required private data is unavailable; no authorized alternative exists. | Recovery: document dependency and assessed alternatives; continue independent work, then precise escalation. |
| Busy but progressing | Long task produces new validated artifacts within budget. | Supervisor when sustained state needs reconciliation; otherwise core invariants: continue; do not restart merely because elapsed time is high. |
| Circular retry | Same permanent error, unchanged input, no progress across retries. | Recovery: diagnose and change approach or escalate; no identical retry without justification. |
| Candidate change | A new retrieval prompt may reduce unsupported claims. | Experiment design; add evaluation design if metric/cases are absent. Define a matched comparison and acceptance rule before results. |
| Winner selection | Best of twenty prompts wins on repeatedly inspected test cases. | Evidence audit; experiment design if planning confirmation: record all attempts, classify test as development evidence, require independent confirmation before promotion. |
| Grader design | Need to distinguish persistence from wasted effort. | Evaluation design: include recoverable and unrecoverable cases, reward verified outcomes and justified escalation. |
| Completion claim | Agent says done but required artifact is missing. | Supervisor: reconcile accepted deliverables and reject completion until verified. |
| Atomic development | One consumer needs a provider adapter; a generic plugin framework is proposed before any query. | Development discipline: keep the public contract, complete the smallest capability and narrow E2E, defer unsupported scale work. |
| Unsafe first path | Happy-path E2E passes but partial publication loses prior state and errors expose a synthetic secret. | Development discipline plus recovery: block readiness, repair atomicity and redaction, inject negative paths; E2E-first does not excuse these defects. |
| Useful reuse | Two consumers pass frozen interface/E2E/failure criteria; no current bottleneck. | Development discipline: accept the scoped capability, defer speculative frameworks, do not claim live readiness. |
| Correlated integration | Rephrased same-source signals win after many reused tests. | Development discipline plus evidence/experiment: require component ablation and untouched/as-of confirmation; no independent-alpha claim. |

The four additions have a separate matched behavioral screen in
`../../tuning/evals/development-discipline/`. Its executable gate checks complete
artifacts and routing/token/quality criteria; it is not a production release hook.

## Review receipt, 2026-10-30

Author walkthrough of the ten scenarios against the written routing and skills:
all expected actions are covered. In particular the explicit-reduction case
prevents turning the original scope mistake into a rule that ignores later user
changes. This is a manual consistency review, not an independent model execution
or evidence that future agents will obey the instructions. Runtime enforcement
and a measured behavioral evaluation remain separate work.

## Routing update after lightweight screening, 2026-10-30

The historical author review above covered the former always-on policy. The
selective route now has a separate seven-request model screen, including overlap
and a non-mentor control. Results and limitations are in
`../../tuning/evals/mentor-routing/report.md`. Existing scenarios remain visible
development checks and are not reused as claimed blind validation.
