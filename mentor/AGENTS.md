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

For mentor tasks, always apply `skills/research-supervisor/SKILL.md` and
`skills/evidence-and-overfitting/SKILL.md`. Load additional skills by the decision:

| Trigger | Skill |
|---|---|
| Stalled progress, repeated failures, premature stop, or blocker review | `skills/progress-and-recovery/SKILL.md` |
| Propose or assess a tuning change, isolate its effect | `skills/experiment-design/SKILL.md` |
| Design/review cases, graders, metrics, splits, or acceptance criteria | `skills/evaluation-design/SKILL.md` |

Multiple routes may apply. Reuse already-loaded guidance; do not reload all five
on every step. Ordinary tasks outside mentoring do not activate these skills.
For sustained tasks use `state/task.template.json` as a compact record, saved in
ignored `runtime/`. This template and routing are instruction-based, not a daemon.
Use `tests/scenarios.md` to review changes to routing or supervision behavior.
