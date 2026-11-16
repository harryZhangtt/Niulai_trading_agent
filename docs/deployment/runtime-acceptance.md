# Required acceptance for major runtime changes

Decision: 2026-10-30. Every agent in this workspace must apply this contract to
major runtime changes and carry it into delegated work. The durable entrypoint
is root `AGENTS.md`. Agent agreement cannot substitute for execution evidence.

## Scope and acceptance status

A major runtime change can affect scheduled execution: wake/startup/lifecycle,
scheduler dispatch, model/profile selection, tools or permissions, authentication,
provider adapters, runtime dependencies/paths, retries, job allocation, report
construction, delivery or the business postcondition. If a change could break
one of these paths, treat it as major. A documentation-only edit or unrelated
UI styling change does not by itself require another business email.

Use `pending`, `passed`, `partial`, `failed`, or `unverified` for execution and
`pending`, `verified`, `failed`, or `unknown` for email synchronization. Acceptance
requires execution `passed` and email `verified`. Partial results must identify
the missing coverage; they permit only the explicitly tested partial claim, not
an unqualified acceptance. Missing evidence is unverified, rather than proof
that the implementation failed. An observed criterion violation is failed.

Keep each private change record under `.job-runtime/acceptance/<change-id>/`.
Use the [record template](runtime-acceptance.template.json); it is a checklist,
not an automatically validating schema. Store no credentials in it. Keep owner
addresses, mailbox IDs, account data, raw reports and machine paths in private
state. A public handoff may name the sanitized status and link this contract.

## Before triggering the test

1. Name the changed capability, owner, impacted job and candidate source/config
   fingerprints. Include uncommitted runtime files; a Git commit alone is not
   enough. Do not retain secret configuration values in the record.
2. Define the observable expected business result, allowed coverage, source
   freshness/as-of rules, maximum start lateness and completion timeout before
   scheduling. State which real provider/tool path is required. A wake-only
   probe cannot accept a changed report, adapter or delivery path.
3. Finish the component checks and required setup documentation sync first.
   Stage a bounded future `once` allocation using the intended runtime,
   interpreter, model profile, auth ownership, tool access and approval mode.
   Keep acceptance request IDs/ledgers separate from production ownership.
4. Keep the existing credential, permission, archive and external-effect
   boundaries. This contract authorizes the configured owner's acceptance
   notifications and the already authorized test scope; it does not authorize
   trading, new consents, permission bypasses or production sender cutover.

## Evidence required from the actual scheduled session

- The installed scheduler claims a future due slot and launches a new Codex
  session. Record job/slot/attempt/thread IDs, due/start/end times, lateness,
  requested model profile and actual transport completion/exit status. Do not
  infer a backend model identity that the transport does not report.
- The Codex session itself exercises the changed capability with its available
  tools, dependencies and permissions. A successful supervising-shell call,
  mock response, tool listing or server handshake does not establish this.
- Verify business postconditions independently of the model's final assertion.
  For Niulai's full path this includes source freshness/provenance and coverage,
  confirmed Tiger checkpoint, complete canonical HTML and two real PDFs, one
  accepted delivery record, and exact Gmail raw readback. Report historical
  replay separately from current live data. Preserve partial and unknown values.
- Preserve every failed attempt, retry and reconciliation. Verify absence of
  duplicate effects; exercise restart/retry recovery when that behavior changed.
  Unknown send outcomes remain held until exact-message reconciliation.
- Bind the evidence to the candidate actually run. A later material source,
  configuration, model, tool or runtime change requires fresh scheduled evidence.
  Old proof is a baseline only. A repaired formatting failure may be reconciled
  against real delivery evidence, but a claim that the repair now works requires
  a subsequent scheduled run of the repair.

One passing run proves that tested path and time. It does not establish perpetual
punctuality, unrestricted production readiness or coverage of unrelated jobs.

## Additional gate for provider/retry v2 and schema 8

The provider-neutral retry v2/schema-8 implementation is currently a disabled,
source-live candidate only. Provider-free source checks do not activate it or
establish provider, scheduler, host, delivery or production readiness. The Codex
normalized translator remains source-live but conformance-unverified and is blocked
by the service code gate. The Claude custody normalizer is not a host invocation
bridge; that bridge is unavailable and its runtime is unverified.

Before a future acceptance attempt:

1. Keep every candidate profile and allocation disabled. Quiesce the writer, create
   an owner-private database backup, and prove schema/source/config rollback on a
   copy without deleting or rewriting the original database. A schema-8 database
   is not compatible with an old writer unless a separately reviewed restore or
   rollback has demonstrated that exact pairing.
2. Capture fresh fingerprints for all candidate source, schema/migration logic,
   sanitized configuration, selected provider profile, translator or host bridge,
   prompt and reconciliation adapter. Include uncommitted inputs. Any material
   change after capture invalidates the corresponding evidence.
3. Pass focused provider-contract, retry-policy, config, engine, service, provider
   adapter, dashboard and provider-free campaign checks, plus adjacent Python and
   scheduler UI typecheck/build/Node/Playwright checks. Record semantic coverage;
   these remain pre-activation evidence, not runtime acceptance.
4. Define bounded future `once` allocations for separate Codex and Claude lanes.
   Each lane must use its intended service code, interpreter, provider/profile,
   credential resource, translator or host bridge, tools and approval boundary.
   Codex evidence cannot accept Claude, and a normalized synthetic fixture cannot
   accept either lane.

Each future scheduled lane must then demonstrate, in persistent state:

- a fresh scheduler claim and attempt/operation identity bound to the captured
  source and profile fingerprints;
- provider result and retry-decision persistence across service restart, including
  the exact selected retry timestamp rather than redrawn jitter;
- a valid typed `Retry-After` minimum, exhaustion/deadline handling and permanent
  auth/config/model/policy stop behavior;
- circuit scope by provider, profile, resource and generation; open-circuit deferral
  with no attempt, one durable half-open probe lease, close/reopen behavior and no
  cross-scope leakage;
- post-submit timeout/reset/partial/missing-terminal as an unknown fence, with no
  automatic or blind replay;
- if replay is needed, one owner-issued immutable reconciliation proof for the
  exact attempt, operation, slot scope and evidence/result digests, consumed once;
- crash/restart recovery that preserves immutable attempts, provider results,
  retry decisions, reconciliation records and consumptions; and
- independent proof of no duplicate business or delivery effect.

Where email is an intended effect, exercise the actual `emailsender` path. Preserve
execution outcome separately from email synchronization: a passed execution with
missing mail readback is not fully accepted, and a verified acceptance-summary
email cannot turn failed execution into a pass. Claim one durable notification key
before one Gmail call, then read back the exact Gmail message by message ID and
verify sender/recipient, subject and content. An ambiguous call remains `unknown`;
reconcile the exact message before any resend. Never replay an unknown provider or
email outcome merely to obtain a cleaner acceptance record.

Rollback after a failed or partial attempt must disable the v2 allocations/provider
route and restore the reviewed source and configuration pairing while preserving
the schema-8 database, backup, attempts, ledgers, unknown fences, credentials and
mail receipts. Never delete the database to roll back. Record execution and email
verdicts independently, including rollback outcome and any remaining incompatible
schema/source boundary.

## Email synchronization is part of completion

Email the result to the user's recipient from the validated owner-private
delivery policy, for success, partial, failure and blocked/unverified outcomes.
Use a stable change/run identifier and subject such as
`[CODEX] Runtime acceptance | <status> | <change-id>`.

Include the change/scope, execution verdict, scheduled/actual timing, job and
session IDs, verified outputs, coverage/as-of limits, failure codes, recovery or
rollback, evidence references and remaining production boundaries. Never include
tokens, keys, private service URLs or raw credential responses. Emailing an
acceptance report does not convert a failed execution into a pass.

The scheduled session should send its own business result where delivery is part
of the job. A supervising agent may send the acceptance summary after independent
verification, including when the job failed before email. Label that sender
clearly; a supervisor-sent summary is not proof that the scheduled job sent mail.
Verify the exact sent message's recipient, subject and content through mailbox
readback and retain its ID and verification time in the private record. Link the
original business message when a separate summary is needed.

Before sending, use one durable notification key and check its existing receipt.
Record a send claim before calling Gmail once. On an ambiguous response, retain
`unknown`, search/read the exact message, and reconcile before another call.
When email cannot be verified, keep synchronization incomplete and disclose it
in chat; do not silently claim it was sent. Retry only classified transient
failures with bounded waits and preserve approval denials unchanged.

## Handoff and enforcement boundary

Implementers provide the record; reviewers inspect actual evidence and withhold
acceptance if it is absent. Delegations and handoffs must include the change ID,
status, evidence location and email status. Active peers must be told about a
new shared rule; new sessions obtain it from root `AGENTS.md`.

The scheduler/outbox already enforce durable claims, bounded retries, approved
tool boundaries and delivery postconditions for configured jobs. This additional
workspace-wide acceptance contract is enforced through agent instructions and
review. No universal CI, merge/deploy hook or automatic acceptance-email service
is installed by this document. `shared/setup_audit.py --check` enforces setup
documentation consistency; it does not certify a scheduled run or send email.

The earlier full Niulai scheduled test is retained as a baseline with explicit
partial coverage and operator reconciliation. Daily production email cutover is
still separate. Do not relabel that baseline as acceptance of newer runtime code.
