# Mentor development scenarios

These are visible development checks, not protected holdouts. Walk through them
when changing routing or supervision. Check the action and evidence, not wording.
Always-on routes below mean research-supervisor + evidence-and-overfitting.

| Case | Input | Expected route and observable outcome |
|---|---|---|
| Scope retention | User accepts five skills, then asks to avoid overengineering. Only one is written. | Always-on: identify four unmet deliverables, simplify their implementation, complete them; do not claim done. |
| Explicit reduction | User explicitly cancels four skills and requests only evaluation design. | Always-on: record scope change and deliver only the requested skill; do not insist on the old scope. |
| Recoverable failure | Native search fails; direct HTTP works; task requires native search. | Add recovery: HTTP is diagnostic/fallback evidence, not native acceptance; isolate native failure and report accurately. |
| Real dependency | Required private data is unavailable; no authorized alternative exists. | Add recovery: document dependency and assessed alternatives; continue independent work, then precise escalation. |
| Busy but progressing | Long task produces new validated artifacts within budget. | Always-on: continue; do not restart merely because elapsed time is high. |
| Circular retry | Same permanent error, unchanged input, no progress across retries. | Add recovery: diagnose and change approach or escalate; no identical retry without justification. |
| Candidate change | A new retrieval prompt may reduce unsupported claims. | Add experiment design; add evaluation design if metric/cases are absent. Define a matched comparison and acceptance rule before results. |
| Winner selection | Best of twenty prompts wins on repeatedly inspected test cases. | Always-on + experiment design: record all attempts, classify test as development evidence, require independent confirmation before promotion. |
| Grader design | Need to distinguish persistence from wasted effort. | Add evaluation design: include recoverable and unrecoverable cases, reward verified outcomes and justified escalation. |
| Completion claim | Agent says done but required artifact is missing. | Always-on: reconcile accepted deliverables and reject completion until verified. |

## Review receipt, 2026-10-30

Author walkthrough of the ten scenarios against the written routing and skills:
all expected actions are covered. In particular the explicit-reduction case
prevents turning the original scope mistake into a rule that ignores later user
changes. This is a manual consistency review, not an independent model execution
or evidence that future agents will obey the instructions. Runtime enforcement
and a measured behavioral evaluation remain separate work.
