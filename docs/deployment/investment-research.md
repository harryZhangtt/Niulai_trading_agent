# Scoped evidence-resolution runtime

## Candidate runtime information catalog and labels

`information_catalog.py` separates a question manifest from the existing evidence
inventory and provider catalog. `prepare_context(request, roster_ref, directory)`
reads a frozen catalog roster and the current capability declarations, explicitly
loads the project-local `skills/information-catalog/SKILL.md`, then writes separate
worker-context and host-diagnostic refs. Historical context excludes unknown-date
records and unauthenticated document versions before titles/content are serialized.
This catalog planner does not authenticate historical document versions. The separate
`shared.research_sources.temporal` broker now supplies before-exposure filtering for
the maintained NOW recipe; it is not installed globally across every retrieval route.

`compile_plan(proposal, context_ref, directory, parent_ref=...)` checks the closed
question shape, exact context hash, required facets/priority, known capabilities,
dependency order and host limits. Expansion is additive and bounded. It saves an
immutable retrieval plan, not successful coverage. There is no active tool/action,
automatic skill-discovery registration, model call, plan-head write, new service,
credential store or source-host enablement. Later executor registration, per-call
budget reservations and concurrent head publication remain integration work.

`information-labels.schema.json` defines version-bound document/claim annotations:
publisher relationship, perspective, document form, topic tags, knowledge status
and annotation provenance. `information-taxonomy.json` keeps canonical topic IDs
separate from record shape; unfamiliar topics remain provisional and discoverable.
Original source/observation refs retain time, version,
lineage, access and numeric scope. Labels do not prove truth or admit evidence;
immutable provisional sidecar persistence is now implemented without modifying original records.
See [the datasource runbook](datasource.md) for the bounded projection, localhost UI,
maintained query recipe and its separately verified acceptance scope.

Use the existing research environment; no new runtime dependencies are needed:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest \
  investment.research.tests.test_information_catalog \
  investment.research.tests.test_information_labels -v
```

On 2026-11-01, seven focused checks and the complete 94-test investment suite pass.
All 81 entity labels in the current 74-security catalog passed the temporal
preflight: 713 unknown-date associations were withheld from historical workers.
One independent development skill probe produced a valid ten-question NOW plan
and correctly exposed absent original-document routes. This is not a fetching
A/B or strict historical-runtime acceptance. The project skill's frontmatter was
checked using the existing project-local mentor validation environment; that
development check introduces no PyYAML dependency into the research runtime.

See [the catalog, labeling and evaluation design](../plans/runtime-information-catalog.md)
and `tuning/evals/information_fetch/protocol.json`. Historical corpus/oracles,
time-gated tool dispatch, actual matched retrieval, full-population semantic
coverage and production registration remain pending. No new scheduled runtime
acceptance or email claim is made for this unregistered candidate.

## Isolated NOW contribution handoff

`investment.research.contribution` supplies a closed contribution contract and
application-side provenance/scope/quotation/arithmetic checks.
`contribution_run.run_case` sends the actual configured model the dated old
hypotheses and source packet through the existing ordered runner. A mechanical
phase completion is not semantic approval. The separate source-grounded reviewer
and `checkpoint_review` bind actual independent model sessions, exact artifacts
and current snapshot dependencies; they do not automatically change a forecast,
thesis or trade. This component is not registered in active research jobs or the
action catalog. No new runtime dependency or authentication owner was added.

Use the existing research environment and local TMPDIR for
`python -m unittest investment.research.tests.test_contribution -v`.
See [the NOW evaluation contract](../../tuning/evals/now_contribution/README.md)
for source/old-context isolation, frozen A/B controls, full failed-round retention,
the captured-output repair replay and limitations of company forecast claims.

After component checks and setup audit, the optional isolated future probe is:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m tuning.evals.now_contribution_acceptance \
  setup --change REVIEWED_CHANGE_ID
```

It creates only its own workspace-resident temporary user launchd label
`com.local.trading-agent.now-handoff.*`, separate Engine/acceptance state and one
future slot. One attempt, per-call timeouts, a fixed completion window and
unknown-effect fences prevent automatic research reruns. The test requires a
fresh author and reviewer, strict source-support results, host receipt/hash and
snapshot readback, one rejected reference fault and exact conditional arithmetic.
It uses captured historical source packets, not a fresh provider fetch. No login
link or production allocation is changed. Unload its own label after inspection;
the next terminal tick also unloads it. The helper sends no email: the supervising
agent must independently verify and synchronize the configured-owner summary.
Acceptance remains pending until the fresh future execution and exact email
readback are recorded; unit or foreground A/B results do not substitute for it.

Verification on 2026-10-31: guard version 1.0.2 passes 87 investment tests plus
one copied-artifact grader regression. The full captured-output repair roster and
16-fault matrix pass the sealed mechanical replay; source/semantic assessments
remain unchanged in the repaired captured-only regrade. Original failed rounds
are retained. [The measured NOW report](../plans/now-contribution-e2e.md) records
one consistent A preference, five consistent ties, two order-dependent preferences
and no observed forecast-accuracy gain. Source-support and integrity claims are
reported separately.

Fresh future change `now-handoff-20261031-v102` passed its one margin-case attempt
with new author/reviewer sessions: 0.92s start lateness, 84.51s execution, four
independently reopened source spans, current snapshot dependencies, rejected
reference fault and exact scenario arithmetic. The owned temporary label is
unloaded. The manual supervising summary has verified exact configured-owner
recipient, subject and HTML mailbox readback in its private record. This is scoped captured-source
runtime acceptance, not active production registration or fresh-fetch coverage.

## Isolated raw-catalog indexing candidate

`investment.research.catalog` reads the legacy research SQLite database read-only
and imports its catalog/section metadata and active evidence/assessment notes
into the existing observation Store. It never follows historical report paths,
executes jobs, authenticates old reviews or promotes notes to original evidence.
Use an explicit shadow output under the private research roots:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m investment.research.catalog \
  --database "$PWD/niulai-private/state/research.sqlite" \
  --out "$PWD/.niulai-state/reports/research-sources/runtime/my-catalog-import"
```

The output is bound to one frozen record roster. Identical imports reuse it;
changed/deleted rows require a new output directory. Original availability stays
unknown when not established. Entity associations do not imply independent
sources. `RecordIndex.select` performs bounded candidate lookup;
`RecordIndex.checkpoint` uses the existing snapshot CAS dependency check. Both
remain discovery/storage operations, with no semantic admission or thesis commit.

Run the focused checks with:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest \
  shared.research_sources.tests.test_indexing investment.research.tests.test_catalog -v
```

This path requires no new runtime dependency. The separately supplied historical
prototype was rebuilt with one-time task-local `xlrd==2.0.2`, `openpyxl==3.1.5`
and `et-xmlfile==2.0.0`, using the existing private NumPy/Pandas environment.
These optional spreadsheet readers are not required by catalog indexing and
were not installed into the runtime environment. Preserve the input archive and
run the prototype only in a private disposable copy because its checks overwrite
its own result files.

See [the integration and verification review](../plans/raw-source-index-integration.md).
This component is not activated in scheduled jobs or the action catalog. No
production/runtime acceptance is claimed; later activation requires the existing
future-triggered Codex and exact owner-email gate.

## Existing evidence resolution path

The component combines shared evidence CRUD, strict registered actions, ordered
phases and scoped use checks. Its first path reconciles reported revenue from
one original issuer release. Full-company coverage and preserved Niulai
validators remain separate.

Use existing `.research-sources/.venv`, `jsonschema==4.25.1` and
`rfc3339-validator==0.1.4`. No new dependency or active MCP entry is required.
The model callback uses the existing workspace-owned default model profile and
authentication lock; credentials are not copied into evidence or prompts.

Run from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m investment.research.run_pilot \
  --out "$PWD/.niulai-state/reports/investment-research/my-pilot"
```

This makes an explicit public source call and actual model calls. Optional
`--source-ref` names a JSON file containing a cached source artifact reference;
its bytes and availability are still checked. It does not rejuvenate old data.

`examples/nvda-revenue-pilot.json` is the reviewed field/period/precision
contract. The deliberately allowlisted original route is nvidianews.nvidia.com.
Headline 26,000 and table 26,044 USD millions reconcile within declared
50-million headline precision. Both have one issuer upstream. This verifies
extraction/rounding, not independent corroboration or valuation.

Acquisition uses `shared.actions.invoke`. The application freezes source-bound
observations, guards the numeric action, asks the tool-free Codex adapter for
structured proposals, executes permitted actions and returns call-linked
outcomes. Finalization requires an actual hash-bound source read and rechecks
current observation/lifecycle stamps at snapshot commit.

The pipeline caps four actions, three model turns and 300 seconds; workers and
model calls also enforce remaining deadlines. Failed or incompatible critical
inputs block publication. Due-check state persists in the evidence index; no
refresh service is installed. Artifacts stay in existing private research roots
and model transport state in `.job-runtime/runs/`. JSON and escaped private HTML
distinguish execution, evidence findings and runtime acceptance.

The initial implementation limitations below are superseded by the incremental
candidate section for immutable releases and safe accepted-phase resume.
Source-native latest ordering is not inferred from retrieval time. Broader metrics/providers/PDFs need reviewed adapters. Production
scheduler integration and full research promotion are follow-up decisions.

Run component checks with workspace-local TMPDIR:

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest discover -s shared/research_sources/tests -q
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest discover -s shared/actions/tests -q
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.niulai-state/reports/research-sources/tmp" \
  .research-sources/.venv/bin/python -m unittest discover -s investment/research/tests -q
```

After checks and setup audit, a single future component acceptance can use:

```sh
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python \
  -m investment.research.pilot_acceptance setup --change reviewed-pilot-change-id
```

This creates a workspace-resident temporary user launchd label, separate Engine
state, one future slot, no automatic retry and a fixed window. It does not edit
the primary scheduler allocations or install a login link. The verifier rereads
fresh source, actual model/thread receipts, typed action handoffs and snapshot
dependencies against a complete source fingerprint including shared/actions.
Preserve failed attempts. Unload the label after inspection; it also unloads on
its next terminal tick. The driver sends no mail: the supervising agent verifies
the configured-owner acceptance notification under runtime-acceptance.md.

The earlier temporary development dispatcher was stopped at the user's request.
This session owns foreground integration with multiple agents; the old isolated
probe and its receipts remain historical. Changes are visible in this checkout.

## Verification scope recorded on 2026-10-31

The scoped suites passed 94 checks (23 source/storage, 11 action, 60 investment).
One fresh future-triggered pilot passed with independent source, transport,
selected-read and snapshot readback; configured-owner notification was verified.
The first manual range/call-ID false block is retained alongside its correction.
These results do not certify the separately changing `shared/calculation/`
candidate. This pilot invokes the preserved numeric crosscheck through its own
pinned action wrapper; global setup fingerprint synchronization is not a
functional acceptance result for unrelated calculator-validation changes.

## Current incremental candidate: immutable execution and cache validation

The current action catalog publishes immutable captured source/schema releases
under `.niulai-state/reports/research-sources/action-releases/`. Active scripts
are version 1.1.0. An existing action/version cannot be republished with different
bytes in that catalog. The worker records release, request/data and interpreter
hashes. This remains a controlled subprocess, not a security sandbox or a fully
immutable third-party dependency environment.

The ordered earnings recipe is now
`investment/research/examples/earnings-query.pipeline.json`. `run_pilot` accepts
`--pipeline-config` for a workspace-local recipe. The existing reviewed historical
NVIDIA case remains fixed; editing phases does not approve arbitrary tickers,
periods or investment conclusions. The domain finalizer still requires exact
source-bound inputs and an actual source read.

Use `--pause-after comparison` to save a safe accepted-phase checkpoint. Save the
returned `checkpoint_ref` as JSON, then use `--resume /path/to/reference.json` with
the same output directory. Resume preserves execution ID, pinned config/releases,
accepted outputs, counters and original absolute deadline. Mid-action/model or
publication uncertainty is held for reconciliation; older checkpoints cannot
bypass a newer intent. Long-delayed resume can legitimately exhaust its original
budget.

Optional audit/HTML projection is handed over separately in
`docs/plans/observability-handover.md`. Audit or rendering exceptions return
sanitized warnings without changing investment execution status. Authoritative
receipts, checkpoints, dependency checks and unknown-effect fences remain
required. The stylesheet `report.css` is a renderer dependency, inlined into the
standalone saved HTML. `python -m investment.research.audit list` and `show
--execution-id UUID` read the optional per-execution index.

The acquisition cache uses the existing Store SQLite database, exact canonical
provider/capability/parameters/access-scope/native-version keys, per-key bounded
OS locks, CAS and raw/text hash validation. Warm eligibility is requirement
specific; cached publication/retrieval times are retained. 401/403 dependencies
remain held until a changed access scope or explicit force refresh; other
registered transient/coverage failures default to a bounded 60-second cooldown
(maximum 3600). This adds no polling service or automatic retry. Optional attempt
logging failure is a warning; failed cache publication may return validated
`fetch_uncached` data. Source coverage and claim support are checked separately.

`shared.research_sources.source_matrix` runs one bounded live capability matrix;
`cache_matrix` runs a small cold/warm and captured-source cache workload, with
controlled concurrency/crash/corruption contrasts. `runtime_validation` composes
them as one public CLI for an actual scheduled agent's shell tool. No active MCP
configuration changes occur: the optional candidate is queried by an isolated
protocol client. SEC and external-host web availability remain explicit gaps;
metadata discovery does not establish document reading. Calls/timing and cache
hits are not estimates of investment alpha or provider-wide reliability.

For a fresh combined candidate test, add `--with-sources` to the existing
`pilot_acceptance setup` command. It schedules one temporary once allocation,
then runs a fresh shell-enabled Codex source/cache session followed by the
application-controlled earnings pause/resume and real model read. Source/cache
session timeout is 600 seconds, the earnings absolute budget remains 300 seconds,
and the combined completion ceiling is 1000 seconds. Existing auth locks and
model selection are reused; the primary scheduler allocations are unchanged.
The verifier independently reopens captured payloads, counters, calculation,
accepted-phase checkpoint and snapshot. Report partial source coverage honestly,
preserve failures, unload the temporary label, and verify the configured-owner
summary email. This candidate's fresh combined conformance and explicit partial coverage are
recorded in the verification section below.

### Sealed evaluation gate

The combined `--with-sources` acceptance now seals
`tuning/evals/evidence_runtime/cases.json` and the explicit grader/runtime source
closure before scheduling. The same Store artifact roots hold separate input and
expected packets plus a small per-contract attempt ledger. Before actual work,
the host verifies pins and claims the attempt once. Completion requires every
case, declared metrics, observed usage within the frozen budget, unchanged source
bytes and a pinned host callback. Failed/unknown attempts cannot be overwritten;
changed contracts require a new version. Required critical failures cannot be
averaged away. Direct unit runs are development checks, not promotion evidence.

The first consumer is development/unblinded. Expected packet separation is not
OS isolation or a blind reasoning result. The host callback independently
reopens source/cache/phase artifacts and binds them to the actual schedule,
source report and execution. Coverage is still reported per provider/capability;
a passing accounting/guardrail test does not make an unavailable route available.
The future baseline/candidate API uses one case/answer/grader/budget contract for
both arms; this first run is candidate-only and establishes no superiority.
See `tuning/evals/evidence_runtime/README.md` for the contract and limitations.


### Incremental verification result, 2026-10-31

175 component checks passed: 77 investment, 59 source/store/cache, 18 actions,
11 controller and 10 sealed-contract checks. A fresh future-triggered combined run
(`source-cache-resume-20261031-v2`) passed all 10 sealed host-graded conformance
cases with three actual Codex sessions. The reported fact/snapshot/resume path
passed independent readback; broader source availability remains partial.
Observed source/cache counts are 10/11 usable attempts, 8 distinct usable cases,
10/10 warm integrity hits and 9/10 decision-eligible reads. Cold issuer acquisition
2.753s; warm 18.12ms with zero extra provider requests. Controlled five-process
singleflight and 100 warm reuse postconditions passed. These are bounded workload
observations, not statistical reliability or independent source counts.

The previous v1 receipt retains its incomplete helper fingerprint/cache binding
findings. The v2 closure pins the executed cache test and MCP helper dependencies
and binds cache captures to the same source report and scheduled cutoff. A fresh
repaired-controller future probe passed and was stopped before implementation
activation. Its 11 negative/progress guard checks passed; actual 12-hour endurance
is unverified. All temporary test/development labels are unloaded.

One supervising-agent summary covered v1 limitations, v2 results and controller
scope, with exact configured-owner recipient/subject/HTML mailbox readback.
The private acceptance records preserve threads/attempts/timing/pins/receipts.
SEC and unattended web remain unresolved, technical equivalent fallbacks are
absent, and MCP upstream HTTP freshness remains unknown. Optional UI/control
expansion is owned separately. Do not infer full-company promotion, alpha,
blind reasoning quality or general production readiness from this conformance.


### Atomic action safety and open-question candidate

Active action versions are now 1.1.1; original 1.1.0 frozen bundles remain historical
and readable. This patch closes selected-output-schema/error/release binding,
misrepresented descriptor and owned-process cleanup defects, and rejects explicit
HTTP 200 service/authentication error pages without keyword-blocking technical
documentation about errors. Arguments are validated before the runner records an
effect intent, so an invalid proposal can be corrected within its existing budget.

The next bounded validation uses
`tuning.evals.atomic_actions.acceptance setup --change CHANGE_ID`, with the
existing research Python environment and workspace-local TMPDIR. It freezes four
neutral questions and separate host oracle criteria, current script/grader source
closure and budgets before one future once allocation. Each case uses the
existing ordered runner and real tool-free Codex proposals to read original
source passages and, where relevant, execute host-bound numeric comparisons.
This adds no production engine, UI, credentials, provider or scheduler allocation.

The private output root is
`.niulai-state/reports/research-sources/runtime/atomic-open-questions/` and the
contract ledger root is `runtime/atomic-evaluation-contracts/` under the same
source state. Temporary user launchd labels start `com.local.trading-agent.atomic.`.
Four cases share a 720-second ceiling, at most6 actions and7 model turns per case,
and a declared 12-request HTTP upper bound. Unknown costs remain unknown. Source
periods, model/session receipts and output citations are independently checked.

After the scheduled run, perform the predeclared source-grounded review for each
actual answer. Bind each review to the case, exact answer/source refs, oracle hash
and complete critical-criteria roster. `acceptance finalize --record RECORD
--reviews REFERENCES_JSON` invokes the sealed host grader. Pending/manual review
is partial, not semantic acceptance. Preserve failures/new versions, verify the
configured-owner summary email, and unload only the temporary label. Four
correlated development questions do not establish blind generalization or alpha.

The atomic patch also requires execution receipts for failed worker responses;
unreceipted `not_started/retryable` claims cannot authorize a retry. Unpinned
current requests still bind to the preselected release. On Darwin, cleanup
retains the unreaped leader until group shutdown and bounded status collection;
an expired request remains a deadline failure even if shutdown encounters the
zombie-group EPERM race. The new adapter retains every blocked question and
finishes its complete failed roster. Case metrics remain unknown where missing;
only budget maxima use conservative enforced bounds. Acceptance module loading
and this blocked-suite finalization have direct regression checks.

The first four-question run completed all actual actions and source-grounded
answers, but its sealed1.0.0 mechanical EPS grader falsely rejected grouped
labelled values and verbose valid fiscal-period notation. The failed evaluation
and original grader bytes are preserved. Contract1.0.1 accepts equivalent labelled
representations while contrast checks still reject swapped GAAP/non-GAAP values
and wrong periods. Expectations, questions and worker prompt remain unchanged;
a new future round validates the correction. New acceptance records capture the
grader/question/oracle source snapshots as well as their pre-run hashes.

The second open-question round exposed a real citation-quality failure: a correct
outlook value cited5000:6500although its text was at4761inside an actual0:6500read.
It was rejected by source-grounded review. Evaluation contract 1.0.2 uses the exact
`passage.locator` returned by `evidence.read`, bound to the source reference;
claims no longer submit model-computed offsets. The host resolves observed
locators and rejects foreign/unissued references. This reuses the existing read
action output, adds no engine service and preserves1.1.1script releases. A source
review is still necessary: an issued passage reference alone does not prove a
claim's meaning. Questions/factual expectations remain fixed; earlier failed
rounds and grader bytes remain immutable. The new scheduled round tests all four
cases because the citation representation is shared by their outputs.


Atomic verification is complete for contract 1.0.2:
`atomic-open-questions-20261031-v3` passed all four scheduled source-grounded cases,
with 14 actual action calls and 14 Codex turns in 308.73 seconds. 213 component checks
pass. Input+output usage 402,262 tokens; charge unknown. Preserve the two failed
rounds and captured grader sources. The manually composed supervising summary
used the required `[CODEX]` subject prefix and exact configured-owner To/subject/
HTML readback; all three private acceptance records are synchronized. All three
temporary labels are unloaded. Use captured public-data regressions to contain
routine validation cost; further broad live/model repeats need a concrete changed
capability or unresolved material risk. This adds no runtime-engine or UI platform.
