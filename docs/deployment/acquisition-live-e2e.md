# Codex and Claude live acquisition E2E runbook

Status: **P0 IMPLEMENTED AND PROVIDER-FREE VERIFIED — LIVE ACTIONS NOT YET EXECUTED** (2026-11-05).

This runbook carries the hosted acquisition candidate from its current provider-free
state through one real call, the three-dispatch narrow E2E, independent publication,
and major-runtime acceptance. It does not authorize a provider call, scheduler
mutation, email, credential access, MCP activation, or production cutover. Commands
below are operator procedures with placeholders; every external-effect step is marked
**NOT YET EXECUTED**.

The implementation owner is `investment.research.acquisition_live_session`. The host
owns only the exact tool invocation returned by `next`; the coordinator owns durable
claims, capture, assessment, review, reconciliation, and checking. Codex and Claude
must use separate profiles, execution IDs, roots, caches, receipts, and acceptance
records. MCP is `not_used`.

## Acceptance target and claim boundary

The work is not complete merely because local tests, a tool listing, or a one-call
smoke passes. Continue until all applicable gates below have terminal evidence.
Operational fixture receipts are marked synthetic and cannot satisfy live acceptance.
A host's live structural claim requires:

1. one reconciled real-call smoke in a dedicated root;
2. one separate cold three-dispatch session (search, brittle PDF open, sealed HTML
   alternate) with no retries, duplicates, cache hits, or unknown outcomes;
3. one literal supported unit, an independent review, and an independently recomputed
   checker verdict of exactly `1 complete chain / 1 credited unit`;
4. checker-backed read-only dashboard publication without raw bytes, secrets, or
   private paths; and
5. for a major-runtime acceptance claim, the applicable future-triggered host lane,
   independent postcondition verification, acceptance email, and exact mailbox
   readback.

Codex major-runtime acceptance additionally requires the installed scheduler to claim
a future `once` slot and launch a new Codex session. A manual run cannot replace it.
The current workspace contract does not yet define Claude as an equivalent accepted
scheduler lane. Claude may complete a cooperative live structural E2E, but it remains
**runtime-acceptance unverified** until a reviewed Claude future-runtime contract and
email lane are defined and then actually pass.

A pass establishes only the tested hosted retrieval/recovery path at that time. It
does not establish general provider reliability, autonomous source selection,
publisher-original bytes for Claude WebFetch, acquisition-quality improvement,
independent corroboration, production readiness, forecast value, or investment
alpha.

This workspace uses the explicitly selected `operational_host_evidence` trust policy:
host-returned session/tool identifiers, exact input/result hashes, scheduler/process
evidence and the hash-chained local journal form practical runtime evidence. These
receipts are locally retained and do **not** resist malicious same-user file forgery;
no cryptographic remote-attestation claim is made. Synthetic fixtures remain
ineligible for live acceptance. Each receipt counts one adapter dispatch and one
host tool invocation separately from underlying HTTP requests or host-internal
retries; those lower-level counts remain explicitly unknown unless the host reports
them.

## Phase 0 — freeze owners, candidate, and isolated state

**NOT YET EXECUTED.** Do this before any provider or scheduler action.

Create a unique `<change-id>` and two host-specific `<execution-id>` values. Record
candidate source and configuration fingerprints, including uncommitted runtime files,
in private records under:

```text
<workspace>/.job-runtime/acceptance/<change-id>/
<workspace>/.research-sources/live-e2e/<case-id>/<candidate-id>/codex/<execution-id>/
<workspace>/.research-sources/live-e2e/<case-id>/<candidate-id>/claude/<execution-id>/
```

Each directory must be workspace-local, private, non-symlinked, and mode `0700`.
Never share mutable roots, raw-result files, journals, caches, or result packets across
hosts or between smoke and full runs. Preserve terminal and ambiguous journals; do
not delete or replay them to obtain a clean result.

Fan-out only after the input contracts are frozen:

| Lane | Owner | Output | Join gate |
|---|---|---|---|
| Packet and custody | case owner | sealed public NOW case, query, PDF/HTML equivalence, cutoff, hashes | no quote preselection |
| Codex host | Codex runtime owner | sanitized profile and opaque readiness receipt | exact native tool identity |
| Claude host | Claude Code runtime owner | separate sanitized profile and opaque readiness receipt | exact WebSearch/WebFetch identities |
| Runtime and reconciliation | acquisition implementation owner | green deterministic/fault suites and unknown fence | no replay path |
| Checker and dashboard | independent verifier/UI owner | recomputed verdict and bounded projection | UI never decides pass |
| Acceptance and delivery | scheduler/delivery owner | future-slot record and exact email readback | stable notification key |

No lane may inspect another host's raw output before its own terminal result. The
integration owner joins immutable references only; agent agreement is not evidence.

## Phase 1 — preflight and readiness packet

**NOT YET EXECUTED.** No provider call is allowed in this phase.

Seal one positive-control packet containing the exact official-domain search query,
one public PDF URL, one publisher-controlled equivalent HTML URL, frozen URL and
redirect rules, source role, cutoff, temporal policy, representation relationship,
failure taxonomy, stop rules, and retention/rollback owners. Freeze these limits:

```text
smoke: search items=1; open items=0; provider items=1; fallbacks=0
narrow: search items=1; open items=2; provider items=3; fallbacks=1
both: concurrency=1; cache=false; unchanged retries=0
raw result limit=65536 bytes
run wall seconds=<1..600>; provider call seconds=<1..run wall seconds>
```

Forbidden substitutions are `find`, a second query, a second alternate, curl, another
provider, a result-selected URL, and an unchanged retry. PDF success makes the
recovery test inconclusive; it is not permission to manufacture a failure or rerun
until favorable.

Prepare, without credential values:

- `<readiness-envelope.json>` accepted by
  `tuning.evals.information_fetch.live_e2e.readiness.load_and_validate`;
- one `<host-profile.json>` per host using `host-adapter-contracts-1`;
- one separate `<credential-readiness.json>` per host using
  `host-credential-readiness-1`, `status=ready`, an opaque receipt ID, and
  `credential_values_present=false`;
- one readiness-v2 `<init-spec.json>` per execution containing no free-form question or proposals; the live session derives exact operations from the sealed packet and binds the relevant profile/reference hashes.

The Codex profile must bind configured backend and search/open tool
`native_tools.web__run`. The Claude profile must bind backend `claude_code.web`,
search tool `claude_code.WebSearch`, and open tool `claude_code.WebFetch`. Profile
files contain owner/profile references and fingerprints only. Never place a token,
key, cookie, credential response, private service URL, or raw auth material in source,
arguments, logs, screenshots, packets, or receipts.

Run the provider-free gate from the workspace root:

```sh
cd "<workspace>"
.research-sources/.venv/bin/python -B -m unittest \
  shared.research_sources.tests.test_host_adapter_contracts \
  shared.research_sources.tests.test_host_web \
  investment.research.tests.test_acquisition_live_session \
  investment.research.tests.test_acquisition_claude_code \
  investment.research.tests.test_acquisition_fault_matrix
```

Also rerun the deterministic production-runner rehearsal:

```sh
cd "<workspace>"
.research-sources/.venv/bin/python -B -m unittest \
  investment.research.tests.test_acquisition_synthetic_e2e
```

The final provider-free materialized acceptance rehearsal is maintained at
`tuning/evals/information_fetch/live_e2e/test_materialized_acceptance_rehearsal.py`.
It reopens the exact materialized Codex/Claude profile, credential-readiness and
binding references, runs synthetic smoke and three-dispatch narrow sessions, then
publishes, replays and independently verifies the bounded acceptance envelope. It
uses no provider, email, scheduler, MCP or credential value. From the workspace root:

```sh
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  .research-sources/.venv/bin/python -B -m unittest -v \
  tuning.evals.information_fetch.live_e2e.test_materialized_acceptance_rehearsal.MaterializedAcceptanceRehearsalTests.test_materialized_dual_host_smoke_narrow_publish_verify
```

The frozen 2026-11-05 candidate passed this narrow rehearsal 1/1 and its adjacent
provider-free suite 74/74. This proves deterministic materialization-to-readback
composition only; it does not establish provider readiness, live host execution,
email delivery or major-runtime acceptance. Test artifacts remain in private
workspace-local roots and normal cleanup removes per-test temporary state.

Before live execution, the applicable setup documentation and inventory owners must
finish their coordinated update and pass:

```sh
cd "<workspace>"
python3 -B shared/setup_audit.py --refresh
python3 -B shared/setup_audit.py --check
```

Do not run `--refresh` while another setup owner is active, and inspect every changed
fingerprint. A passing audit proves documentation consistency, not provider readiness.

Preflight passes only when the readiness verdict is true, the host-session-bound
credential receipt is at most 15 minutes old and matches the exact profile fingerprint
and configured capability, profile and credential references hash-match, smoke/full
runtime and cache roots are new or verified empty and distinct, roots and permissions
pass, all deterministic suites pass, setup audit passes, no critical review finding
remains, and rollback/reconciliation owners are named.

## Phase 2 — explicit authorization checkpoint

**BLOCKED / NOT YET EXECUTED.** Obtain the user's explicit authorization for the
first bounded external call after Phase 1 passes. Bind the authorization receipt to:

- exact host and backend;
- packet hash or exact benign smoke query;
- `N_SMOKE_MAX=1`, then separately `N_NARROW_MAX=3`;
- wall/per-call timeouts and private artifact root;
- bounded raw-response retention/deletion policy; and
- confirmation that no trading, protected holdout, `niulai-private`, MCP, recurring
  job, production mutation, provider switching, or credential copying is included.

Authorization for Codex does not authorize Claude, and vice versa. A prior general
instruction to finish acceptance does not replace consent for an exact new external
call when the sealed packet, retention, or host is not yet identified.

## Phase 3 — one-call smoke per host

**NOT YET EXECUTED.** Use a dedicated smoke execution and root, not the target E2E
root. Initialize with a one-call benign public search packet approved in Phase 2.
The coordinator itself never calls the provider.

```sh
cd "<workspace>"
PY=".research-sources/.venv/bin/python"
SESSION="<private-smoke-session-root>"

"$PY" -B -m investment.research.acquisition_live_session init \
  --directory "$SESSION" --input-file "<smoke-init-spec.json>"
"$PY" -B -m investment.research.acquisition_live_session next \
  --directory "$SESSION"
```

The host operator must copy neither prose nor a reconstructed request. It invokes
exactly the returned `tool_identity` with exactly the returned `tool_input`, once,
and writes the exact JSON result to a private bounded `<raw-result.json>`. Then create
a credential-free `<capture-envelope.json>` with exact host/tool identity and an
`operational_host_evidence` receipt binding host session, host event/tool-call ID
(or explicit unavailable reason), dispatch, input/result hashes, timestamps and
terminal status. Claude captures also require the exact `actual_tool_input` and
`captured_at` fields. Operational receipts are not cryptographic remote attestation.

```sh
"$PY" -B -m investment.research.acquisition_live_session capture \
  --directory "$SESSION" \
  --input-file "<capture-envelope.json>" \
  --raw-result-file "<private-raw-result.json>"
"$PY" -B -m investment.research.acquisition_live_session finalize \
  --directory "$SESSION"
"$PY" -B -m investment.research.acquisition_live_session status \
  --directory "$SESSION"
```

Smoke finalization must return `status=callable`, `run_kind=smoke`, exactly one actual dispatch, and `complete_chains=0`, `credited_units=0`. It is never eligible for full acceptance publication. Stop after one dispatch. Capture must arrive before both the 60-second call deadline
and 300-second inner run wall; late or indeterminate outcomes are fenced and earn no
credit. Do not use the target PDF/HTML case, retry, adapt, switch providers, assess,
or claim full readiness. The smoke may establish only backend
callability, exact argument transfer, one durable dispatch receipt, bounded raw versus
screened separation, and cleanup ownership. An ambiguous result becomes
`possibly_dispatched`; preserve it and go to reconciliation. Do not begin the full
run until the smoke is terminal and independently reconciled.

## Phase 4 — full three-dispatch cooperative E2E

**NOT YET EXECUTED.** Create a new execution ID and cold root. Run Codex and Claude
as separate sessions; never fail over from one to the other.

Initialize and request the first operation:

```sh
cd "<workspace>"
PY=".research-sources/.venv/bin/python"
SESSION="<private-full-session-root>"

"$PY" -B -m investment.research.acquisition_live_session init \
  --directory "$SESSION" --input-file "<full-init-spec.json>"
"$PY" -B -m investment.research.acquisition_live_session next \
  --directory "$SESSION"
```

For every returned dispatch, the host performs exactly one matching tool call and the
operator immediately captures it using the Phase 3 `capture` command. Request another
operation only when capture returns an authorized dispatch phase:

1. Search once. The sealed pair must match the frozen URL policy. Search metadata
   receives zero evidence credit; a miss is inconclusive and terminal.
2. Open the sealed PDF once. Preserve bounded diagnostics. Only a predeclared
   representation failure may release the alternate.
3. Open the exact sealed HTML alternate once. Require URL/representation match,
   temporal eligibility, and a screened body.

After the eligible HTML body is screened, create `<assessment.json>` with one literal
quote and deterministic substring/offset support, then obtain `<review.json>` from a
reviewer distinct from both the live operator and assessment author. The review must
include a separate operational reviewer-session receipt binding the reviewer principal,
session, exact review-payload hash and timestamp; unequal caller labels alone do not
establish independence:

```sh
"$PY" -B -m investment.research.acquisition_live_session assess \
  --directory "$SESSION" --input-file "<assessment.json>"
"$PY" -B -m investment.research.acquisition_live_session review \
  --directory "$SESSION" --input-file "<review.json>"
"$PY" -B -m investment.research.acquisition_live_session finalize \
  --directory "$SESSION"
"$PY" -B -m investment.research.acquisition_live_session finalize \
  --directory "$SESSION"
"$PY" -B -m investment.research.acquisition_live_session status \
  --directory "$SESSION"
```

The second finalization must return the same immutable final reference. Pass requires
exactly three actual dispatches, zero cache hits, one fallback, zero duplicates, zero
unknowns, one reviewed unit, and checker `1/1`. Preserve a truthful partial HostWeb
status caused by the failed PDF. Any unknown, secret leak, identity mismatch, budget
breach, source/quote mismatch, duplicate, or replay rejects the candidate version.
Unknown-class codes must carry terminal status `unknown`; fallback is permitted only
after a known `failed` representation outcome.

## Phase 5 — independent checker and dashboard publication

**NOT YET EXECUTED.** The verifier must reopen the packet, config, driver, proposal,
dispatch, raw/source/text/version, assessment, unit, review, and reconciliation
references. It must recompute hashes, identities, exact arguments, legal transitions,
dispatch cardinality, cache/fallback accounting, PDF/HTML lineage, quote support,
permissions, and finalization identity. Never accept the runner, model, host, or UI's
self-reported pass.

Register only the checker-approved sanitized projection through the private datasource
registry's bounded `acquisition_driver_projection` envelope. Start the existing local
read-only dashboard using its runbook and verify Overview/Runs/Evidence projection.
Publication must expose identities, accounting, hashes, temporal fields, quote/review,
checker reasons, and limitations, but never raw provider bytes, prompts, credentials,
private paths, arbitrary HTML, or unchecked verdicts.

Run the focused local verification commands applicable to the candidate:

```sh
cd "<workspace>"
pnpm run build
pnpm run test:datasource
python3 ui/tools/run.py playwright --project ui/datasource test \
  --config playwright.config.mjs
```

Record warnings and unrelated known failures separately; do not convert partial UI
coverage into a checker pass. Dashboard publication is observability evidence only.

## Phase 6 — Codex future `once` runtime acceptance

**NOT YET EXECUTED.** This phase is mandatory before claiming the changed Codex path
accepted. It must use the installed scheduler, intended Codex runtime/model profile,
auth owner, exact candidate fingerprints, and one future `once` allocation. Do not
invent an acquisition scheduler helper: if no reviewed helper owns staging, implement
and review that local helper first under the existing `shared.job_runtime` contracts.

Before staging, create the private acceptance record from
`docs/deployment/runtime-acceptance.template.json` and predeclare source freshness,
coverage, maximum start lateness, completion timeout, exact provider/tool path,
business postconditions, rollback, and delivery key. Then the authorized scheduler
owner stages and registers one future allocation. Record the actual command and its
sanitized output in the private record; this runbook intentionally supplies
placeholders rather than an unverified command:

```sh
# NOT YET EXECUTED — provider-free preparation only.
cd "<workspace>"
.research-sources/.venv/bin/python -B -m \
  tuning.evals.information_fetch.live_e2e.once_acceptance setup \
  --change-id "<change-id>" --due "<future-aware-iso>" \
  --codex-envelope "<sealed-codex-envelope.json>" \
  --codex-root ".job-runtime/acceptance/<change-id>/codex-session"
# Review/materialize the returned manifest, then use the existing Engine owner to stage/register once.
```

The resulting evidence must include job, due slot, attempt, Codex session/thread,
execution, and trace IDs; due/start/end times and lateness; requested profile; actual
transport completion; three-dispatch business evidence; checker `1/1`; dashboard
publication; cleanup; and independent duplicate/unknown reconciliation. A manual live
run, old scheduled proof, handshake, or successful supervising shell does not satisfy
this gate.

If the future run fails or is partial, retain it, publish the true status, repair the
candidate, and schedule a new future run for the repaired fingerprints. Do not loop
unchanged or relabel old evidence.

## Phase 7 — Claude cooperative and future-runtime acceptance

The manual/cooperative Claude smoke and full E2E follow Phases 3–5 with
`claude_code.WebSearch` and `claude_code.WebFetch`. WebFetch is a
`rendered_extracted_representation`, not publisher-original bytes, and support is
limited to wording in that exact captured extract.

**POLICY BLOCKED / NOT YET EXECUTED:** before claiming major-runtime acceptance for
Claude, define and review an equivalent future-triggered lane in the runtime acceptance
contract. It must name the actual Claude launcher/session identity, future trigger,
profile/auth owner, WebSearch/WebFetch observations, independent postconditions,
unknown fencing, rollback, acceptance-email sender, and exact readback. Only then may
an authorized operator stage and execute it. Codex evidence cannot be reused as Claude
evidence, and a Claude cooperative session cannot be described as a Codex scheduled
session.

## Phase 8 — email synchronization and exact readback

**NOT YET EXECUTED.** Send a result for pass, partial, failure, blocked, or unverified
status using the validated owner-private delivery policy. Newly composed Codex-led
subjects begin:

```text
[CODEX] Runtime acceptance | <status> | <change-id>
```

Use a distinct stable run/change ID for each host. The body must identify manual versus
scheduled execution, slot/request ID when available, scope, timings, job/session/
execution/trace IDs, verified outputs, coverage/as-of limits, failure codes, recovery,
rollback, evidence references, and remaining production boundaries. Do not include
credentials, raw provider output, private service URLs, owner addresses, or private
paths.

Before one send, check the durable notification key and record a send claim. On an
ambiguous response, retain `unknown`, search for and read the exact message, and
reconcile before any second call. Verify exact recipient, subject, body, message ID,
and verification time through mailbox readback. A supervisor summary is not proof
that the scheduled business session sent its own message. Execution can pass while
email remains unknown, but overall runtime acceptance then remains incomplete.

## Unknown reconciliation and stop rules

At any `invocation_started` outcome without an authoritative capture, stop that
execution. Preserve all journals and raw references, mark it `possibly_dispatched`,
and perform provider-free reconciliation. Never issue the next operation, fallback,
retry, host switch, email resend, or scheduler replay while the relevant effect is
unknown. Reconciliation may import an existing immutable receipt; it may not invoke a
provider. If authoritative definitely-not-dispatched evidence is unavailable, the run
stays fenced and cannot pass.

Permission denial, user cancellation, credential failure, policy failure, source/code
pin drift, 401/403/404, circuit-open, or deadline-after-possible-dispatch are terminal
for that execution. Record transient 429/503/transport outcomes without unchanged
retry in this narrow run.

## Rollback

Rollback is additive and host-specific:

1. stop staging new allocations for the affected host;
2. unload only the owned temporary scheduler label after terminal reconciliation;
3. preserve pending, failed, unknown, and final journals and exact fingerprints;
4. remove only terminal, reconciled private test allocations according to the sealed
   retention policy;
5. leave the other host, its credentials, and unrelated jobs untouched;
6. restore an active host configuration only from an owned pre-change receipt after
   reconciling later edits; and
7. keep candidate provider/MCP configuration disabled by default. MCP remains
   `not_used`.

Rollback does not erase evidence, rewrite status, resend mail, or authorize a replay.
Recurring activation or production cutover is a separate user decision.

## Evidence index and final claim

Keep credential-free public references and private evidence separate. Expected private
locations are:

```text
.job-runtime/acceptance/<change-id>/                 runtime acceptance record
.research-sources/live-e2e/<case>/<candidate>/codex/ host-isolated sessions
.research-sources/live-e2e/<case>/<candidate>/claude/host-isolated sessions
<session>/artifacts/                                 immutable coordinator/checker refs
<session>/runner/                                    dispatch journals and bounded raw refs
```

The terminal handoff must state, per host: smoke verdict; full E2E verdict; dispatch,
cache, fallback, duplicate, and unknown counts; checker result; dashboard status;
future-runtime status; email status/readback; evidence locations; rollback state; and
exact allowed claim.

Allowed claims by evidence level:

| Highest completed evidence | Allowed claim |
|---|---|
| deterministic suites only | provider-free structural contracts pass |
| reconciled one-call smoke | that host/backend was callable once |
| full E2E plus checker/dashboard | that host completed the tested live structural path |
| Codex future `once` plus verified email | tested Codex candidate satisfies the scoped major-runtime contract |
| Claude future lane plus verified email | tested Claude candidate satisfies its separately reviewed scoped contract |

## Decisions required from the user

The implementation can continue independently through provider-free preparation. It
must ask the user before crossing these unresolved boundaries:

1. authorize the exact Codex smoke call and raw-result retention after packet review;
2. authorize the exact Claude smoke call and raw-result retention separately;
3. approve the sealed target query/PDF/HTML packet if the packet owner cannot derive
   it from an already approved public case;
4. choose whether Claude needs only cooperative live structural evidence now or a new
   future-triggered runtime-acceptance lane equivalent to Codex; and
5. approve any later recurring activation or production cutover (neither is part of
   this runbook).

Missing authorization or missing Claude-lane policy is a precise blocker, not a failed
provider result. All useful provider-free preparation, review, and isolation checks
should continue while those decisions are pending.

## Information-yield v5 provider-free source-closure handoff

The frozen final setup-owner handoff is
`mentor/runtime/live-provider-e2e-20261104/information-yield-v5-final-handoff.json`.
The generated `docs/deployment/setup-lock.json` `sources` entry is authoritative
for its current SHA-256; this runbook deliberately does not embed that digest and
thereby avoids a handoff↔documentation fixed-point cycle. The handoff records 80
deduplicated setup-sensitive paths at aggregate SHA-256
`bbb4a4d7e397eebea93e2bc7280d0270b69dbbfb283bd62177496c37096cd1e7`,
including Lane A (24 paths, `58ea34386579e10b084e320baac891ca5129e8afbee61cb875e95edb90b9b3b5`),
Lane B (16 paths, `ae849b96467e73198ed200950e1bb6dd32e9eb56da40306ff9807d25bf2b1bc2`)
and scheduler authority/parity (23 paths,
`954add57d08731e59f94dd4142c4f730701b075b8b218101684e2e5a6a8a2dc9`).
All 80 files were present and exact at handoff.

The fixed publication root is `tuning/runtime/information-yield-v5`. The custody-only
projector `investment/research/information_yield_projection_v5.py` is
`e44ad1d788663f30efdc8f7ba8928160a7901b8440274f89410370473e468979`;
`ui/datasource/server.mjs` is
`0f8d49027d722040700091047520df8795eb7bb74b70a66394d4b0070c73d43c`;
the v5 wire type is
`8c241ed8953ba2f3f47bfbb39f632f700c76b1157886a6f38197b4b6efb2ce1f`;
the API client is
`c45555b64e3bd3c73bdb8dea6339cd2b8afcd3e4d90daf14077c57f77d7151cf`;
the wire adapter is
`cd7dbfc4891870d9b142d6f075fd61acb8fed0ee177cf5ad03e2c6fbf77071bc`;
and the shared UI panel is
`7877c1c43650e2e2b2d74d5e50ccff1ad1d38aec5e53b90f3ff68b038ac1ba19`.
The sealed architecture remains
`4727e1fca4b2d7c4147b365d3aa2874ccfa1ff0d41fab07b987566c71a52f1bc`.

This closure changes no provider, model, retry, deadline, cache, host-adapter, MCP
or email policy in Phases 0–8 above. It creates no runtime root and executes no
provider/network/scheduler/email/business effect. Referenced immutable v5 objects
and indexes are retained; cleanup must be reference-aware and is deferred to the
named `information-yield-v5-integration-owner`. Unknown publication or delivery
outcomes remain fenced and reconciled before retry.

Activation, if ever separately authorized, remains ordered and fail-closed:

1. preserve O0 as active/default and keep rejected v3/v4 disabled with no upgrade;
2. verify frozen source hashes, no-writer state, independent reviews, the provider-free
   nominal vertical and corruption matrix;
3. review and explicitly approve both the v5 locator/publication root and
   `INFORMATION_YIELD_V5_ENABLED=1`—neither one alone is approval;
4. materialize only the fixed non-symlink root at `0700`, publish immutable files
   at `0600`, and reconcile every ambiguous publication before retry; and
5. separately plan and execute future intended-runtime provider/scheduler acceptance
   and exact branded email readback under the unchanged runtime contract.

Rollback disables the flag and locator, preserves immutable artifacts and returns
to O0 without v3/v4 fallback. The handoff status is
`closed_exact_record_only_handoff`; writer state is
`all_source_ui_test_architecture_and_runtime_writers_frozen_clean_no_writer`;
readiness is `not_ready_no_authorization`; and the allowed claim is provider-free
structural evidence only. Remaining blockers include two confirmed B/schema9 P1
items, deferred prompt-custody activation repairs, absent host/service freshness,
no future provider/scheduled/email readback and the flag remaining off.
Completing setup consistency is not activation or authorization.
