# Live-provider datasource E2E execution plan

Status: **P0 PROVIDER-FREE LIVE-CALL CONTRACT COMPLETE — BLOCKED ON FINAL SETUP/PACKET/HOST EXECUTION**, 2026-11-05. Readiness/session v2, a real one-call smoke mode, public cooperative runner APIs, exact sealed-pair gating and synthetic/live provenance separation are implemented. The checked-in packet remains intentionally not-ready and no provider call has executed.

## 1. Decision and current status

**Verdict: NOT READY FOR LIVE PROVIDER DISPATCH.**

The immediate next action is to complete the final coordinated setup fingerprint, materialize fresh host-bound credential/profile receipts and seal separate smoke/full readiness-v2 packets. The first external call remains blocked until those exact bytes pass preflight.

Current evidence is structural only:

- The complete provider-free acquisition/P0 suite passes **156/156**.
- Datasource server tests pass **15/15**, the current typecheck/build passes, and the parent full pinned browser run passes **45/45**.
- Readiness/session v2 derives live operations from the sealed packet; smoke is exactly one call and cannot publish as a full E2E.
- The runner owns cooperative begin/capture/unknown fencing; late or unknown smoke outcomes cannot emit another operation.
- The narrow path stops inconclusive when search does not contain the exact sealed PDF/HTML pair.
- No live-provider execution evidence exists. NOW remains repeatedly inspected diagnostic evidence only.


The intended narrow path is:

`AcquisitionDriver → AcquisitionController → HostWeb → hosted-native provider → capture/screen → assessment → candidate unit → independent reviewer → independent checker → dashboard`

Because the PDF and HTML URLs are frozen before search, this is a **scripted retrieval/recovery integration test**, not autonomous search-to-source selection.

---

## 2. What the narrow E2E must prove

On one sealed, current NOW development case, prove that the application can:

1. Submit exactly one hosted-native search.
2. Verify the sealed disclosure pair appears under a frozen URL-normalization policy.
3. Open one sealed brittle PDF exactly once.
4. Classify a naturally observed representation failure truthfully.
5. Recover only to one predeclared, semantically equivalent HTML representation.
6. Screen one eligible HTML body before worker exposure.
7. Bind one literal quote to that exact screened text version.
8. Persist one provisional assessment and candidate unit.
9. Obtain one separate reviewer disposition.
10. Reconcile driver, controller, HostWeb, cache and actual dispatch accounting.
11. Independently validate exactly `1 complete chain / 1 credited unit`.
12. Project only checker-approved, sanitized trace data in the dashboard.

### Explicit non-claims

A pass does **not** establish:

- General provider reliability.
- Autonomous source selection.
- Acquisition-quality improvement.
- Better freshness or historical detection lag.
- Independent corroboration; PDF and HTML are two representations of one disclosure.
- Forecast quality, portfolio value, entry-policy value or investment alpha.
- Recurring production readiness.
- Major-runtime acceptance.

---

## 3. Resolved implementation and remaining gates

| Capability | Current state | Remaining evidence |
|---|---|---|
| Hosted runner and dispatch fence | Resolved: public cooperative begin/capture/unknown APIs, bounded raw capture and restart fencing | Real host smoke |
| Readiness/session authority | Resolved: v2 derives exact question/query/PDF/alternate/budgets from the sealed packet; v1 fixtures remain readable | Materialized ready packet |
| One-call smoke | Resolved: explicit smoke state, one dispatch, 0/0 semantic credit, never publishable as full E2E | Real call per host |
| Narrow search gate | Resolved: exact sealed pair required before PDF open; miss is terminal inconclusive | Real search result |
| Recovery/review/checker/projection | Resolved provider-free with operational host/reviewer receipts and checker-backed publication | Real receipts and checker result |
| Setup closure | Open | One coordinated setup refresh/check after all owners freeze |
| Host readiness | Open | Fresh exact-session profile/credential receipts and empty isolated roots |
| Runtime acceptance | Open | Real Codex/Claude structural runs; future scheduled Codex run and verified result email for major-runtime acceptance |

---

## 4. Immediate next action: no-provider-call readiness packet

Create and review a sealed packet before implementation fan-out. This packet makes no external call.

### 4.1 Packet contents

- Immutable case ID.
- Disclosure/canonical-document ID.
- NOW issuer identifier.
- One narrow current question.
- One exact official-domain search query.
- One exact public PDF URL.
- One exact publisher-controlled HTML URL.
- Frozen URL normalization and redirect policy.
- Evidence that PDF and HTML represent the same disclosure:
  - publisher control;
  - title;
  - disclosure date;
  - document/release identity;
  - representation relationship.
- Positive-control disclosure:
  - the PDF was selected because brittleness was previously suspected or observed;
  - the case is development evidence, not representative failure-frequency evidence.
- Required source role, access level and capabilities.
- Evidence facet sought.
- Eligible body rules.
- Cutoff and temporal eligibility policy.
- Eligible PDF failure classes.
- Stop and inconclusive rules.
- Cache-disabled setting.
- Runtime and artifact roots.
- Experiment, execution, trace, operation, attempt and dispatch ID rules.
- Retention owner and rollback target.
- Packet SHA-256.
- Effective-config envelope SHA-256.
- Explicit statement that the quote is **not** preselected.

### 4.2 Frozen narrow budget

| Variable | Value |
|---|---:|
| `B_SEARCH` | 1 |
| `B_OPEN` | 2 |
| `B_PROVIDER` | 3 |
| `B_FALLBACK` | 1 |
| `B_CONCURRENCY` | 1 |
| `CACHE_ENABLED` | false |
| `T_RUN_WALL` | predeclared |
| `T_PROVIDER_CALL` | predeclared |
| `RAW_RESULT_LIMIT` | 64 KiB unless the pinned implementation differs |

Permitted dispatch sequence:

1. Search.
2. PDF open.
3. Sealed HTML open, only after an eligible PDF representation failure.

Forbidden:

- `find`;
- second query;
- unchanged retry;
- second alternate;
- provider switching;
- curl substitution;
- result-selected URL replacement.

### 4.3 Readiness packet pass checklist

- [ ] Case packet is complete and hash-sealed.
- [ ] Effective config is complete and hash-sealed.
- [ ] PDF/HTML equivalence review is recorded before quote selection.
- [ ] Candidate selection bias is disclosed.
- [ ] URL/redirect policy is frozen.
- [ ] Budget, deadlines and stop rules are frozen.
- [ ] Private artifact root is workspace-local, non-symlinked and mode `0700`.
- [ ] Raw-output retention and deletion policy are declared.
- [ ] Rollback and reconciliation owners are named.
- [ ] No provider, email, scheduler, trading or protected-data action occurred.

---

## 5. Required implementation contracts

### 5.1 Hosted runner

The runner must:

- Accept only the sealed case and effective-config envelopes.
- Call only the configured hosted backend.
- Invoke the exact argument bytes returned by the driver.
- Use absolute per-call and whole-run deadlines.
- Stream/spool provider output privately with a hard byte bound.
- Never print raw output or include it in exceptions.
- Record invocation start before calling the provider.
- Capture configured and provider-reported backend identities separately.
- Leave observed identity unavailable if the provider does not report it.
- Clean up child processes, tasks, locks and temporary files on all exits.

### 5.2 Dispatch journal and fencing

Use stable dispatch IDs and append-only states:

`prepared → claimed → definitely_not_dispatched | invocation_started → captured | possibly_dispatched`

Rules:

- `claimed` alone is not permission to redispatch after restart.
- Redispatch requires durable, authoritative `definitely_not_dispatched` evidence.
- Any lost callback after invocation starts becomes `possibly_dispatched`.
- `possibly_dispatched` is terminally fenced until reconciled.
- Unknown outcomes never trigger fallback or retry.
- Actual dispatch cardinality comes from durable receipts, not in-memory counters.

### 5.3 Repair APIs

Add no-provider-call reconciliation for:

- controller reservation committed before driver write;
- HostWeb intent committed before driver write;
- HostWeb capture committed before driver update;
- controller capture committed before driver update;
- assessment saved before driver update;
- unit attached before driver update;
- reviewer decision saved before driver update;
- partial finalization.

Every repair must be idempotent and import the exact existing immutable reference.

### 5.4 Closed failure taxonomy

The versioned taxonomy must classify:

- transient;
- permanent;
- policy/validation;
- representation failure;
- deadline before dispatch;
- deadline after possible dispatch;
- circuit open;
- unknown outcome.

For the target E2E, fallback is allowed only for sealed codes such as:

- `HOST_WEB_BODY_TOO_LARGE`;
- `HOST_WEB_SOURCE_INACCESSIBLE`;
- `HOST_WEB_BODY_UNPARSEABLE`, only if explicitly predeclared.

No fallback after:

- 401/403/404 policy failures;
- 429/503 transient failures;
- transport failure;
- circuit open;
- source or code drift;
- deadline after possible dispatch;
- unknown outcome.

Failure classification must prefer structured provider diagnostics. Arbitrary body text containing failure-like phrases must not determine status.

### 5.5 Frozen alternate descriptor

Replace each bare URL with:

- representation kind;
- exact arguments;
- source role;
- required capability/access level;
- canonical disclosure ID;
- relationship to primary;
- semantic-equivalence rationale;
- permitted triggering failure codes;
- budget cost.

### 5.6 Reviewer and trace contracts

The reviewer:

- cannot be the live operator or assessment author;
- receives immutable screened references, not the operator’s summary;
- records a hash-bound disposition;
- reviews question relevance, literal support and canonical lineage;
- does not infer investment importance.

Required trace:

`experiment → question → proposal → exact arguments → operation/attempt/dispatch → raw/source/text/version → exposure → assessment/quote proof → candidate unit → reviewer decision`

The independent checker must reopen artifacts and require `1/1`, rather than trusting runner or UI summaries.

### 5.7 Effective-config envelope

Pin:

- runner;
- driver;
- controller;
- HostWeb;
- cache/store;
- taxonomy;
- alternate policy;
- assessment/unit/review schemas;
- checker;
- projection;
- backend and model configuration;
- runtime interpreter;
- case packet;
- budgets and deadlines;
- retention/GC policy;
- rollback target;
- acceptance policy.

---

## 6. Parallel implementation wave

Freeze interfaces and packet schemas first. Then the following work may run in parallel without provider access.

| Agent | Ownership | Deliverables | Cannot do |
|---|---|---|---|
| A — Runtime/ledger | Runner, dispatch journal, deadlines, bounded raw capture, cleanup | Runner contract tests and durable dispatch receipts | Provider calls |
| B — Reconciliation/faults | Crash repair APIs, unknown fencing, disk/process/lock tests | Table-driven fault suite and duplicate-dispatch proof | Redesign taxonomy unilaterally |
| C — Policy/controller | Failure taxonomy and alternate descriptors | Closed mapping, fallback gate and migration tests | Select live outcomes |
| D — Evidence/checker | Assessment proof, reviewer artifact, ledger reconciliation, checker | Machine-readable verdict with per-gate reasons | Trust runner summary |
| E — Case/custody | Public NOW packet and equivalence review | Sealed positive-control packet and hashes | Preselect quote or inspect protected holdouts |
| F — Projection/UI | Read-only checker-backed projection and browser tests | API DTO, dashboard details, accessibility/security tests | Grade semantic truth |
| G — Security/operations | Path/permission policy, canaries, retention, rollback | Containment report and cleanup checks | Expand global permissions/settings |

### Sequential integration owner

After parallel work:

1. Merge one contract owner at a time.
2. Resolve interface disagreements.
3. Rerun all deterministic suites after each merge.
4. Review setup fingerprint changes.
5. Seal one candidate revision/configuration.
6. Block dispatch on every unresolved critical finding.

Multi-agent review does not create independent experimental samples, and defects cannot be voted away.

---

## 7. Deterministic testing stages

## Stage 0A — Component and contract tests

Run with provider/network dispatch disabled.

Confirm the repository’s pinned interpreter before execution, then run the focused suites:

```bash
cd "<workspace-root>"

python3 -m unittest \
  investment.research.tests.test_acquisition_driver \
  investment.research.tests.test_acquisition_orchestration \
  shared.research_sources.tests.test_host_web \
  investment.research.tests.test_acquisition_projection
```

Add and run suites for:

- hosted runner;
- dispatch journal;
- reconciliation;
- failure taxonomy;
- alternate descriptors;
- reviewer decisions;
- cross-ledger accounting;
- trace checker;
- new-driver projection;
- raw-output containment;
- timeout/process cleanup.

If setup-sensitive implementation changes, update:

- `docs/deployment/datasource.md`
- `docs/local-setup.md`
- `docs/deployment/setup-inventory.json`
- `docs/deployment/setup-lock.json`

Then run:

```bash
cd "<workspace-root>"
python3 -B shared/setup_audit.py --refresh
python3 -B shared/setup_audit.py --check
```

Review every `--refresh` fingerprint change. A passing refresh does not authorize a provider call.

## Stage 0B — Fault matrix

Every row must produce exactly one outcome: `resumable`, `terminal_blocked` or `reconcile_required`.

| Injection boundary | Required behavior |
|---|---|
| Before controller reservation | No operation or usage |
| Controller committed before driver write | Import same reservation; no extra charge |
| Host intent committed before driver write | Bind existing intent; no dispatch |
| Claim persisted before invocation | Dispatch only with authoritative not-dispatched proof |
| Invocation started, callback lost | Fence as possibly dispatched; never replay |
| Provider returned before raw journal persistence | Unknown unless authoritative host evidence exists |
| HostWeb capture committed before driver update | Import receipt without provider call |
| Controller capture committed before driver update | Import transition and queue fallback at most once |
| Assessment save interrupted | No credited unit |
| Unit attachment interrupted | No duplicate unit |
| Reviewer save interrupted | No credit until disposition is complete |
| Finalization interrupted | Repeat returns byte-identical references |
| Disk full / permission / rename / fsync failure | Preserve prior valid state; deterministic repair class |
| Deadline before invocation | Zero provider dispatches |
| Deadline after invocation may have begun | Unknown fence; no alternate |
| 401/403/404 policy result | Terminal; no fallback |
| 429/503 | Frozen transient handling; no unchanged retry |
| Explicit oversized PDF | Representation failure |
| Malformed/truncated/invalid-UTF provider result | Typed failure, never empty success |
| Provider schema drift | Typed rejection |
| Raw result above bound | No exposure; bounded private handling |
| Redirect/canonical mismatch | No source or unit credit |
| URL/body mismatch | No credit |
| Future or unknown eligibility timestamp | No exposure |
| Source/code pin drift | No exposure |
| Quote absent from screened text | No assessment/unit credit |
| Same arguments under different operation ID | Reject duplicate fingerprint |
| Concurrent runner / stale lock | Bounded busy result |
| Cancellation / timeout | No surviving process, task or lock |
| Observer/cache publication failure | Authoritative receipt survives with bounded warning |
| Prompt-injection/HTML/script canary | Treated as inert data; no tool/UI execution |
| Secret/private-path canary | Absent from logs, API, DOM, storage, screenshots and traces |
| Finalized replay | Rejected without provider action |

## Stage 1 — Synthetic full-path rehearsal

Use the production runner with a counting fake:

1. Search returns the sealed URLs.
2. PDF returns a structured oversized diagnostic.
3. Controller queues the exact sealed HTML descriptor.
4. HTML returns one eligible body.
5. One literal quote is selected.
6. Assessment, unit and reviewer decision are stored.
7. Controller, HostWeb and driver finalize.
8. Accounting reconciles.
9. Checker reports `1/1`.
10. Dashboard projection consumes checker output.

Assertions:

- [ ] Exact argument bytes.
- [ ] Exactly three fake invocations.
- [ ] Zero duplicate dispatches.
- [ ] Zero cache hits.
- [ ] Exactly one fallback.
- [ ] Search metadata receives no document or unit credit.
- [ ] Raw output is captured once and never logged.
- [ ] Reconciliation invokes the fake zero times.
- [ ] Repeated finalization is byte-identical.
- [ ] Post-finalization reserve/capture/dispatch fails closed.
- [ ] No process, task, lock or temporary artifact remains.
- [ ] API and UI show no raw payload or private path.

---

## 8. Stage 0/1 pass gate

All must pass before requesting authorization:

- [ ] Existing focused tests pass.
- [ ] New deterministic suites pass.
- [ ] Every crash edge has a tested classification.
- [ ] Reconciliation is idempotent and provider-free.
- [ ] Dispatch cardinality is independently provable.
- [ ] Cache is disabled in the target packet.
- [ ] Candidate and effective-config hashes are sealed.
- [ ] Exact backend readiness is recorded without claiming a call.
- [ ] Private path, ownership and mode checks pass.
- [ ] Raw-output and secret canaries remain contained.
- [ ] Setup audit passes.
- [ ] No unresolved critical review finding remains.
- [ ] Synthetic rehearsal checker result is `1/1`.
- [ ] Dashboard projection is checker-backed and bounded.

Failure of any item blocks external calls.

---

## 9. Explicit human authorization checkpoint

Passing deterministic gates does not authorize network/provider activity.

Before the first external call, obtain explicit authorization binding:

- exact provider/backend;
- sealed packet hash or exact query/URLs;
- `N_SMOKE_MAX = 1`;
- later target maximum `N_NARROW_MAX = 3`;
- maximum wall time and per-call timeout;
- workspace-local private artifact root;
- raw-provider-response retention;
- confirmation that no email, scheduler mutation, trading, protected holdout, `niulai-private`, recurring job or production mutation will occur.

Save a credential-free authorization receipt.

---

## 10. First external execution: one-call smoke

This is a distinct execution ID and must stop after one call.

- Use one benign, public, non-target search.
- Use the same runner, journal, timeout, raw capture, screening and cleanup path.
- Do not retry, adapt or switch provider.

It may establish only:

- configured backend callability;
- exact argument transfer;
- one durable dispatch receipt;
- raw/screened separation;
- timeout and cleanup ownership.

It does not prove target retrieval, PDF recovery, quality or runtime acceptance.

Any ambiguous outcome is fenced; do not proceed to the target until reconciled.

---

## 11. Target live E2E

Use a new execution ID and cold private root.

### Operation 1 — Search

- Dispatch the sealed query once.
- Require the sealed canonical disclosure or exact sealed PDF/HTML pair under the frozen URL policy.
- Keep search data discovery-only.
- Credit zero evidence units from search output.
- If the pair is absent, stop as discovery failure/inconclusive.
- Do not issue a second query or substitute another URL.

### Operation 2 — PDF

- Open the exact sealed PDF once.
- Preserve bounded raw diagnostics privately.
- Classify through the frozen taxonomy.
- Recover only on an eligible representation failure.

If the PDF succeeds:

- preserve the successful result;
- classify the recovery test as inconclusive;
- do not manufacture a failure;
- do not rerun unchanged until a failure appears.

### Operation 3 — HTML alternate

Only after an eligible PDF failure:

- verify the exact alternate descriptor and canonical relationship;
- verify arguments differ from the PDF operation;
- dispatch once;
- require exact returned URL/representation match;
- screen temporal bounds and body eligibility;
- expose only the screened body.

### Assessment and completion

1. Select one literal quote after body screening.
2. Save offsets or deterministic substring proof.
3. Save one assessment.
4. Attach at most one candidate unit.
5. Obtain a separate reviewer disposition.
6. Finalize controller, HostWeb and driver.
7. Reconcile all ledgers.
8. Run the independent checker.
9. Run finalization again and verify identical references.
10. Project the sanitized checker result.

Expected accounting:

| Measure | Expected |
|---|---:|
| Search items | 1 |
| Open items | 2 |
| Actual provider dispatches | 3 |
| Cache hits | 0 |
| Fallbacks | 1 |
| Duplicate dispatches | 0 |
| Unknown outcomes | 0 |
| Credited units | 1 |
| Complete chains | 1/1 |

HostWeb may truthfully finish `partial` because the PDF failed. Do not rewrite that component status as fully successful.

---

## 12. Narrow-run verdict rules

### Pass

All must hold:

- sealed packet unchanged;
- exactly one search, one failed PDF and one successful sealed HTML open;
- PDF failure is a predeclared representation failure;
- no cache, duplicate, retry or unknown replay;
- one eligible body;
- one literal quote bound to its exact text version;
- one assessment, unit and reviewer approval;
- exact accounting reconciliation;
- checker reports `1/1`;
- clean process/lock/artifact state.

### Inconclusive

- PDF succeeds.
- Search misses the sealed pair.
- Backend readiness prevents execution without a policy violation.
- Required evidence is absent but no integrity rule was violated.
- Recovery-opportunity denominator is zero.

Do not rerun unchanged merely to obtain a favorable result.

### Reject candidate version

- duplicate dispatch;
- unknown replay;
- future/unknown source exposure;
- fabricated or openless support;
- URL/source/version/quote mismatch;
- budget or deadline violation;
- unclassified failure;
- secret/private-path leakage;
- missing credited-unit trace;
- case, URL, metric, grader or denominator manipulation;
- protected-holdout leakage.

---

## 13. Independent checker

The checker runs outside the runner and React application.

### Inputs

- sealed case packet and hash;
- effective-config envelope and hash;
- expected identities;
- final driver reference;
- approved private root.

### Required checks

- no symlink/path escape;
- hashes recompute;
- code/config fingerprints match;
- identities agree across all artifacts;
- arguments equal the sealed packet;
- state transitions are legal;
- exactly three actual dispatch receipts exist;
- no duplicates or unknowns;
- controller reservations reconcile with HostWeb receipts;
- cache hits equal zero;
- PDF and HTML map to one disclosure/lineage;
- search metadata receives no evidence credit;
- HTML URL equals the sealed alternate;
- raw/text/version hashes agree;
- temporal bounds satisfy cutoff;
- quote is an exact substring of the bound text;
- assessment, unit and reviewer decision are linked;
- complete-chain result is `1/1`;
- repeated finalization references are identical;
- permissions and retention policy are correct;
- canaries did not escape.

Output a sanitized machine-readable verdict with per-gate reasons.

---

## 14. Dashboard acceptance

Add a bounded, read-only `acquisition_driver_run` detail sourced from checker output.

Required fields include:

- experiment/execution/trace IDs;
- case and question;
- proposal hash and sanitized exact arguments;
- operation/attempt/dispatch identities and transitions;
- logical, reserved and actual dispatch accounting;
- cache and fallback state;
- PDF failure and representation relationship;
- canonical disclosure and source URL;
- raw/text/version hashes, never raw bytes;
- publication, modification, availability, first-observed, retrieval, screening and exposure times as distinct nullable values;
- quote, assessment, unit and reviewer disposition;
- checker verdict and missing links;
- explicit limitations and unavailable values.

Security requirements:

- allowlisted refs only;
- byte/cardinality bounds;
- fail closed on identity/hash mismatch;
- no credentials, prompts, private paths, raw exceptions or arbitrary HTML;
- no pass inferred from absent data.

Browser matrix:

- 320, 360, 390, 768, 1024, 1440 and 2560 CSS pixels;
- actual 200% text;
- keyboard-only flows and visible focus;
- long IDs, URLs, quotes and reason codes;
- Back, Close, deep links and invalid nested IDs;
- loading, partial, unavailable, retained-last-good error, empty and filtered-empty;
- stale/late response and refresh races;
- zero page-level horizontal overflow;
- canary scans across API, DOM, browser storage, console, screenshots and traces.

The dashboard remains observability evidence, not the validator.

---

## 15. How to test whether quality actually improved

Only start after the narrow structural E2E passes.

### Hypothesis

Typed representation recovery and deterministic admission increase supported canonical information without unacceptable precision, lineage, latency or integrity regression.

### Rivals

- Recovery merely adds redundant representations.
- Catalog/admission, not recovery, causes any gain.
- Extra calls alone explain gains.
- Positive-control case selection exaggerates usefulness.
- Grader/reference behavior creates apparent gains.
- The candidate improves one source surface while materially harming another.

### Development 2×2 ablation

| Arm | Catalog/admission | Typed recovery |
|---|---|---|
| B0 | Off | Off |
| R | Off | On |
| C | On | Off |
| F | On | On |

Use four predeclared issuer-windows from distinct issuers and source surfaces. NOW remains development-only.

Matched controls:

- same backend, model/effort, prompt shell, ledger and safety policy;
- cold isolated cache namespace per arm;
- randomized/counterbalanced order;
- fixed budgets and deadlines;
- every arm and failure retained;
- issuer-window is the unit, not passage, quote or field.

Suggested maxima:

- 6 search items;
- 8 read items;
- 14 provider items;
- 600 seconds;
- 4 cases × 4 arms = at most 224 provider items.

### Co-primary outcomes

1. Unique supported new canonical units.
2. Net required-field transitions:
   - unknown → partial;
   - partial → resolved;
   - minus resolved → partial/unknown regressions.

Report separately:

- usable bodies/read attempts;
- recovery successes/preclassified opportunities by reason;
- trace completeness;
- supported precision;
- independent lineage;
- latency, calls, bytes, tokens and observed cost;
- all unknowns and failures;
- paired issuer-window deltas;
- median/range;
- leave-one-issuer-out sensitivity.

Recovery opportunity must be classified before arm outcome.

### Development gate

Before outputs, freeze:

- tie definition;
- practical aggregate margins for both co-primary outcomes;
- maximum material per-case regression;
- precision and latency safeguards;
- opportunity denominator;
- stopping and missing-data rules.

At minimum:

- all cases and arms retained;
- zero integrity failures;
- both aggregate co-primary directions satisfy the frozen gate;
- no material fourth-case regression is hidden by three ties/wins;
- lineage is not lower;
- precision no more than five percentage points lower;
- latency within the frozen ceiling;
- recovery exercised when eligible opportunities exist;
- no budget/deadline violation.

This gate permits untouched confirmation only; it is not a quality claim.

---

## 16. Untouched confirmation

Compare only frozen `F` versus `B0` on six new issuer-windows from six issuers.

Custody requirements:

- separate case/reference custodian;
- sealed roster and manifest hashes;
- enforced worker/grader access boundaries;
- read/access logs;
- outcome-blind selection;
- no substitution or silent removal;
- cold isolated namespaces;
- counterbalanced order;
- blind pooled review;
- opposite reviewer order;
- independent adjudication.

Any premature access converts that case to development evidence.

Before accessing outcomes, justify and freeze:

- practical aggregate gain on both co-primary outcomes;
- minimum case-win rule;
- maximum per-case regression;
- leave-one-issuer-out requirement;
- precision, lineage and latency safeguards.

The previously suggested `+6`, 4/6 wins, five-point precision tolerance and 25% latency ceiling are **not accepted merely by appearing in a plan**; they need operating-cost, error-tolerance and development-variance justification. Otherwise six cases remain a scoped coverage/cost pilot and the result is inconclusive.

No six-case design supports a statistical-superiority claim.

---

## 17. Future-once runtime acceptance

Only after structural, development and untouched gates pass, follow:

`docs/deployment/runtime-acceptance.md`

Because adding a provider runner changes scheduled provider execution, it is a major runtime change.

Required later gate:

1. Pin candidate revision plus uncommitted fingerprints.
2. Create one separately authorized future `once` allocation.
3. Use the intended scheduler, runtime, backend, auth owner and config.
4. Exercise the changed business path.
5. Record slot, attempt, session, execution and trace IDs plus timing.
6. Verify business postconditions independently.
7. Reconcile duplicate/unknown effects.
8. Preserve rollback evidence.
9. Send the acceptance result with subject:

```text
[CODEX] Runtime acceptance | <status> | <change-id>
```

10. Verify recipient, subject, body, message ID and verification time by exact mailbox readback.

A manual live run cannot substitute for this gate. Recurring activation remains a separate decision.

---

## 18. Call and cost envelope

Define without inventing provider prices:

- `N_SMOKE_MAX = 1`
- `N_NARROW_MAX = 3`
- `N_DEV_MAX = 4 × 4 × 14 = 224`
- `N_CONFIRM_MAX = 6 × 2 × 14 = 168`
- `N_CANARY_MAX = separately frozen`

Track independently:

- logical operations;
- reserved provider items;
- actual dispatches;
- failed/partial calls;
- bytes;
- latency;
- tokens when observed;
- monetary cost when observed.

Unknown token or monetary cost remains unavailable, not zero.

---

## 19. Evidence and handoff inventory

### Before run

- case packet and hash;
- effective config and hash;
- authorization receipt;
- code/runtime fingerprints;
- equivalence review;
- setup-audit evidence;
- provider-readiness receipt;
- rollback, retention and cleanup declarations.

### Per operation

- proposal and hash;
- controller decision;
- HostWeb intent;
- exact arguments;
- dispatch claim/journal;
- raw private reference;
- operation receipt;
- typed failure;
- fallback relation;
- budget before/after;
- timestamps.

### Per credited unit

- canonical disclosure/lineage;
- source URL and hashes;
- temporal fields;
- exposure decision;
- quote proof;
- assessment;
- candidate unit;
- reviewer decision.

### Terminal

- controller summary;
- HostWeb receipt;
- driver artifact;
- cross-ledger report;
- checker verdict;
- cleanup and file-mode report;
- finalization identity proof;
- sanitized API snapshot;
- browser traces and canary scans.

Relevant source and policy files:

- `docs/plans/datasource-next-phase-plan.md`
- `docs/deployment/runtime-acceptance.md`
- `investment/research/acquisition_driver.py`
- `investment/research/acquisition_orchestration.py`
- `shared/research_sources/host_web.py`
- `docs/deployment/datasource.md`
- `docs/local-setup.md`

**Immediate execution order:** readiness packet → parallel no-provider implementation → deterministic fault matrix → synthetic full-path rehearsal → integration review → explicit human authorization → one-call smoke → single target run.
