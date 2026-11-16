---
name: development-discipline
description: "Guide this workspace's development decisions: component boundaries, reuse, engineering ROI, safe first E2E, failure handling, credential protection, and incremental integration. Use for implementation planning or review and integration readiness; not ordinary research summaries or grader-only changes."
---

# Development discipline

Apply this skill to the engineering decision at hand, alongside the workspace
instructions. It is a local mentor procedure, not a background monitor or an
automatic release lock. Keep executable experiments and graders in `tuning/`.

## Choose the smallest useful capability

State the observed problem (or label the idea exploratory), accepted deliverables,
expected benefit, cheapest adequate implementation, and acceptance evidence.
Compare implementation, maintenance, runtime and evaluation costs qualitatively
unless measurements support numbers. Preserve deliverables while reducing cost.
Stop after adequate verification; reopen only for a requirement, demonstrated
failure or material uncertainty.

Encapsulate each capability behind an explicit input/output/error contract. Name
its owner and keep state and dependencies behind that boundary. Reuse an existing
capability when its contract fits. Introduce a shared abstraction for demonstrated
duplication or a concrete second consumer; speculative future scale does not
justify a framework. For scaling needs, identify the actual workload or bottleneck
before choosing queues, services or concurrency.

Keep mentor supervision, tuning execution/evaluation, alpha discovery, entry
policy and shared adapters separate. Reuse shared adapters through their public
interfaces; do not make a domain module import another domain's private state.

## Build an atomic capability, then a narrow E2E

Deliver one independently testable capability and one narrow path from real
input through its public interface to an observable result. Define success before
running it. Inject dependencies where needed to make the contract testable; avoid
large scaffolding. Use reversible local/sandbox execution first. Label fixture,
stubbed, isolated-live and host-integrated evidence precisely. A handshake is not
a successful query; a mock-only E2E does not prove provider or host readiness.

After the first E2E, prioritize quality work by failure consequence and expected
benefit. Credential protection, containment of dangerous side effects, input
validation and visible failure are required on the first path. Broader coverage,
performance work and polish can follow. Do not use "E2E first" to defer a known
data-loss, duplicate-effect or credential-exposure defect.

Keep changes focused and reversible. For persistent updates, publish a complete
validated result atomically or leave the prior valid result intact. For external
effects, use idempotency or reconcile an unknown outcome before replaying. A small
patch or commit alone does not establish runtime atomicity.

## Compare architecture before another coupled patch

When the measurable architecture-escalation trigger in `progress-and-recovery`
fires, stop local patch iteration and nominate one integration owner. Seal the
candidate fingerprint, producer/consumer schemas and state authority map before
fan-out. Compare O0 retain/revert, O1 narrow canonical-owner repair and O2 shared
ownership consolidation. Add a new dependency, service, broker or workflow engine
only if O1/O2 cannot meet a concrete requirement. Compare trust authority,
contract fit, migration/failure radius, maintenance/runtime cost, fixture realism
and rollback explicitly; do not collapse these dimensions into an invented score.

Choose with one bounded provider-free vertical experiment, not by review vote. It
must state a falsifiable hypothesis and the result that would falsify it, then
cross the disputed public boundaries using a sanitized real-shaped input, one
nominal case and one failure injection, while proving identity/hash binding,
legal transition, unknown fencing or rollback, and zero external effects. Freeze
outward effects until it passes. Record rejected options, citations and limits;
stop research once the disputed semantics are resolved. Intended-runtime evidence
is still required after the architecture experiment.

## Protect the host and keep recovery available

Before changing hooks, settings, daemons, MCP, shared runtime, schedulers, or an
external-effect path, classify the impact surface:

1. **inert/local**: source, fixture, or disabled configuration that the active
   host cannot load and that cannot emit an external effect;
2. **staged host-impacting**: disabled candidate material requiring a separate
   activation; or
3. **active host/session-impacting**: material loaded by a current or future
   session, persistent/shared process, or external-effect path.

State the owner, activation boundary, affected sessions/processes/effects, and
failure radius before mutation. If classification is uncertain, use the more
host-impacting class until isolation proves otherwise. Diff size is not impact.

Keep an active-host candidate disabled while testing it through a disposable
lifecycle. Cover startup, normal use, timeout, malformed output or receipt,
source/configuration drift, cleanup, and recovery. For every injected failure,
verify user prompts and messaging, task notifications, read-only diagnosis, and
rollback/recovery remain available. Keep an owner-controlled backup, prove the
rollback from the staged candidate, then use a narrow canary and require an
explicit activation decision. Do not directly hot-add or broadly replace active
hooks, settings, daemons, MCP, shared runtime, or every-session dependencies.

Fail closed only around the exact unsafe mutation or effect: deny its activation,
write, command, delivery, or replay until evidence is adequate. Do not turn a
safety dependency into a conversation-wide stop. A mentor initializer timeout,
malformed receipt, source drift, or missing/untrusted output can produce a warning,
direct-file fallback, and a denial of the risky mutation, but must not block user
messaging, task notifications, read-only inspection, rollback, or recovery. These
availability properties are mandatory acceptance evidence for host-impacting
work. If they cannot be demonstrated, leave the candidate disabled and report the
specific unverified boundary.

## Contain failures and protect data

At actual I/O boundaries, bound timeouts and retries, distinguish transient,
permanent and unknown-outcome failures, clean up resources, and preserve a useful
sanitized diagnostic. Do not swallow exceptions, return empty "success", retry
permanent failures unchanged, or report a fallback as primary-path success.
Keep unrelated components usable when one dependency fails. Show recovery or
rollback for a material integration change; follow the existing MCP rollout rule.

Use synthetic secrets in tests. Keep credentials in the designated private store;
pass references rather than values through configuration and reports. Never put
secrets in source, fixtures, prompts, command arguments or logs. Redact at the
output boundary, including exceptions and nested provider responses. Verify
negative paths as well as success; ignored files alone do not prevent leakage.

## Integrate only for incremental value

Verify atomic contracts before composing capabilities. Change one material factor
at a time when attribution matters. For signal, prompt or model combinations,
compare each component and the combination to the same baseline under matched
cases, budgets and costs. Correlated sources/outputs do not provide independent
evidence. Collinearity is a risk to measure, not a universal prohibition: use
ablation and incremental out-of-sample value to decide whether to combine them.

Load `evidence-and-overfitting` for leakage, dependence or generalization claims;
load `experiment-design` when designing an intervention and `evaluation-design`
when defining cases, graders, metrics or promotion criteria. Log all tried
variants. Use temporal/group splits appropriate to the data, protect untouched
tests, and account for costs and repeated selection. Missing confirmation is
inconclusive, not a passing result or proof the idea is bad.

## Evidence before completion

Keep a brief decision record in the conversation or existing task record:
problem/benefit/cost; owner and contract; atomic and E2E evidence; material failure
and secret-handling checks; integration evidence if applicable; deferred work and
the allowed claim. Scale detail to consequence; do not create a dossier for a
small reversible edit. Cite actual artifacts or test results. Missing evidence
blocks the corresponding completion/promotion claim; an observed critical defect
requires repair. Instructions and self-reported checklists are not execution
evidence. Put repeatable checks in the affected component's test/CI path when one
exists, and state explicitly when enforcement remains procedural.

For changes to this skill or its routing, use the matched quality and context-cost
protocol in [the development evaluation](../../../tuning/evals/development-discipline/protocol.md).
