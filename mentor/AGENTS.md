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

# Host-impact safety red line

Before proposing or making a change to hooks, settings, daemons, MCP, shared
runtime, schedulers, or any path that can create an external effect, classify its
impact surface as one of:

- **inert/local**: source, fixture, or disabled configuration that the active host
  cannot load and that cannot emit an external effect;
- **staged host-impacting**: a disabled candidate that can affect a host or shared
  runtime only after a separate activation; or
- **active host/session-impacting**: anything loaded by a current or future
  session, a persistent process, shared runtime, or an external-effect path.

Record the owner, activation boundary, affected sessions/processes/effects, and
failure radius before mutation. Treat uncertainty as the more host-impacting
class until isolated; a small text diff does not make an active hook low impact.

An active host/session-impacting candidate must first be kept disabled and pass a
disposable lifecycle and failure-injection path. Exercise startup, normal use,
timeout, malformed output/receipt, source or configuration drift, cleanup, and
recovery. Demonstrate that user prompts and messaging, task notifications,
read-only diagnosis, and recovery/rollback remain available when the candidate
fails. Require an owned backup and tested rollback, then a narrow canary with an
explicit activation decision. Reject direct broad or hot replacement of active
hooks/settings/daemons/MCP/shared runtime, including changes that make every
prompt or session depend on an unproven component.

Failure containment is scoped to the exact risky mutation or external effect.
Fail closed on that activation, write, command, delivery, or replay when its
safety evidence is missing; do not fail closed on the whole conversation or
recovery surface. Mentor initialization timeout, malformed receipt, source drift,
or missing/untrusted output may warn, fall back to direct policy reads, and deny
only the unsafe mutation. It must never block user messaging, task notification,
read-only inspection, rollback, or recovery. Availability of those paths is a
first-class acceptance condition, not a best-effort fallback.

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
