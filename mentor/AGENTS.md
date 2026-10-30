# Mentor scope

Guide agent improvement through evidence and small experiments. Mentor guidance
lives here; executable experiments and graders belong in `../tuning/` when needed.
Niulai implementation and private state remain separate. Reading or changing
private artifacts requires relevance to the task; do not inspect protected
holdouts during development. Do not change investment behavior as a side effect
of configuring the mentor.

# Minimum effective change

- Before engineering, state the observed problem, expected benefit, and smallest
  change that could address it. If no failure is observed, label the proposal as
  exploratory rather than inventing evidence.
- Preserve agreed deliverables while simplifying implementation. An efficiency
  preference is not a cancellation. Track each accepted deliverable and reconcile
  it with artifacts before claiming completion. Explain proposed omissions before
  changing scope; only an explicit user change removes an agreed requirement.
- Prioritize expected useful outcome relative to implementation, maintenance,
  runtime, and evaluation cost. Use qualitative estimates unless measurements
  support numbers. A cheap change still needs to satisfy the task's requirements.
- Reuse existing tools and plain files first. Add a dependency, abstraction,
  router, agent, or service only to meet a concrete current requirement; explain
  briefly why the simpler option is insufficient.
- Choose a bounded experiment and acceptance rule before examining its results.
  Scale rigor to consequence. Do not build an evaluation platform to answer a
  question that a small comparison can answer.
- After adequate verification, finish. Expand work only for a new requirement,
  observed failure, or unresolved material uncertainty. Remove failed experiments
  from the default path; preserve their result in the experiment record.
- Do not turn individual examples into universal rules. Prefer fixes that address
  a demonstrated failure mechanism and verify on different development cases.

# Progress and recovery

For sustained work, keep a short record of objective, acceptance evidence,
last verified progress, current obstacle, next action, and remaining budget.
Use conversation updates for short tasks; use ignored `runtime/` files only when
resumption needs durable state. Plans and repeated narration are not progress.

When an action repeats without new evidence, diagnose before retrying. Change a
relevant condition, try a materially different authorized approach, or isolate
the dependency. Bound retries and investigation effort proportionally to the task;
do not force a fixed retry count for permanent failures.

A blocker report must identify the actual dependency, observed evidence,
alternatives assessed, useful independent work remaining, and the smallest
external action needed. Neither difficulty nor elapsed time alone establishes a
blocker. Legitimate permission and missing-data boundaries must remain respected.
Do not claim completion without checking the requested outcome.

These are behavioral instructions, not an independently running watchdog.

# Skill routing

Use the provisional selective-loading contract in `ROUTING.md`. Keep the small
scope/evidence/progress invariants there and above active. Select full skills for
the decision at hand; the supervisor and evidence bodies are no longer loaded
unconditionally. Reuse skills already loaded in the session and add references
only when needed. Multiple specialists may apply to one decision.

The lightweight screen and its limitations are recorded in
`../tuning/evals/mentor-routing/report.md`. This is procedural skill routing,
not a change to the underlying model. A loaded body remains in the session's
context until the host compacts it; routing avoids unnecessary future loads.

Five entrypoints contain pinned upstream implementations and local resources;
`development-discipline` is the sixth, authored for this workspace. Apply it to
development decisions across components, retaining implementation and test
ownership in the affected component. Read imported skills' linked investment
context when applying them. Provenance, retained
licenses and the evidence-based pruning record live in `upstream/`; see
`upstream/ADAPTATIONS.md`. Do not substitute a globally installed skill or assume
that omitted upstream hooks, graders or background services are active.
For sustained tasks use `state/task.template.json` as a compact record, saved in
ignored `runtime/`. This template and routing are instruction-based, not a daemon.
Use `tests/scenarios.md` to review changes to routing or supervision behavior.
