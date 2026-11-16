# Independent atomic verification

2026-11-15 initial checkpoint. Balanced verification with deliberate breaks. The independent local
suite is green on the recorded candidate: **302 executed tests, 0 skipped,
0 failures, 0 errors**, including **44 independent tests**. This is local
development conformance. Agent Server, cloud readback, owned URL/browser and
lifecycle acceptance are still pending at this revision of the report.

The verifier read the frozen atomic-contract-v1.1 and implementation directly.
There was no actual current `MENTOR_INIT_OK` output for this fork. Root and mentor
instructions, local development-discipline/evaluation-design, and the installed
backend-testing-skill-set/core-workflow/exception-safety were read directly as the
disclosed fallback. Live-testing and PPE data-safety references were also read.
No source, frozen expectation, root test, server, provider, cloud resource,
credential, email, scheduler or global setting was changed by the verifier.
Only the independent test source, this report and workspace-owned temporary
test/evidence files were written.

The final independently executed local evidence is
`.langchain-pilot/runtime/atomic-independent/1794813688174377000/local-suite.json`.
It records every executed test ID, failures/skips, six mutation outcomes, candidate
source fingerprints and the test log. The command was:

```sh
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false \
TMPDIR="$PWD/.langchain-pilot/tmp" XDG_CACHE_HOME="$PWD/.langchain-pilot/cache" \
.langchain-pilot/.venv/bin/python -B -m unittest discover \
  -s tuning/langchain_pilot -p 'test_*.py' -t .
```

The frozen acceptance SHA256 is
`e374cc970c7e4d24ad8ae11fe8689672a492acec4d5db9beece8e8fdf041e453`.
The case JSON SHA256 is
`bffd7b0217b07b6c0c5c7a2384d5afcb1cd7ca455f0cca27951f929f7c5e1d78`.
The independent test SHA256 is
`f46870760c3415d24d9c9c8479c8b2cb4b9a3a076c7d4677a9077f9206437d7a`.
The recorded `atomic_cloud.py` SHA256 is
`20343433c9c2d8c61d118c4e7248f2d2cfaf06d8bc16e4a01069d752ba54f8e3`.
Material later source/config changes require fresh applicable evidence.

The frozen JSON contains **196 designed cases**, not 196 automatically executed
tests. Thirty CAL cases and sixty HOLD cases each have individual executable
test IDs. Other scenarios have grouped controls and the evidence gaps below.
The 302 test total includes existing pilot tests and mutation harness tests;
reused runs and mutation target subtests are not additional independent samples.

The verifier observed and reported the following failures before their repairs.
All listed regression controls pass in the final local evidence:

| Observed wrong behavior | Discriminating independent control | Final local result |
| --- | --- | --- |
| Cooperative receipt `10.000000000001` accepted for exact oracle `10`; other receipt amounts not checked | ArithmeticReceiptTests: near-correct, wrong enterprise/equity, extra monetary claim, exact positive control | PASS after exact Fraction/schema checks |
| Same names/copied metadata substituted different project/dataset IDs during unknown bootstrap reconciliation | CloudIntegrityTests: wrong saved resource IDs and no-repeat-write controls | PASS after exact saved-ID reads |
| Changed remote expected result and matching favorable run/feedback certified as success | CloudIntegrityTests: remote expected-output drift | PASS after full frozen-roster comparison |
| Foreign favorable run IDs replaced the owned evaluation attempt | CloudIntegrityTests: owned run-ID mismatch | PASS |
| Returned foreign-project or child run accepted as owned root | CloudIntegrityTests: foreign session/root-parent controls | PASS after returned identity checks |
| Duplicate remote example rows disappeared in a dictionary | CloudIntegrityTests: duplicate remote rows | PASS after raw-list admission |
| Untrusted remote private payload reached `aevaluate` before validation | CloudIntegrityTests: before-evaluation callback admission | PASS; invalid rows rejected before target/experiment/dispatch |
| Native tracer clones lost delivery errors and native IDs; injected post timeout still looked recorded | NativeTraceTests: actual RunTree post/patch capture and unknown-repeat fence | PASS after shared clone collector |
| Deterministic calculator tool propagated raw private-canary exception | PublicBoundaryTests: deterministic closed diagnostic | PASS |
| Cooperative tool-only replies produced six requests and a seventh pending request despite run-limit 3 | PublicBoundaryTests: persisted three-request cap | PASS after thread-limit enforcement |

The first standalone adversarial arithmetic probe actually returned `passed` for
the wrong exact amount. Early independent runs found three cloud failures; the
44-test pre-final run found the remaining cap failure. These are retained findings
and development iterations, not reliable-agent samples. The earlier whole-local
evidence at `atomic-independent/1794813191764196000/local-suite.json` passed 292
tests before the later targeted additions; it does not supersede the final run.

The native trace controls use the real PublicTracer, LangChain RunnableLambda,
prompt and StructuredTool callbacks. Only RunTree network post/patch is replaced.
They assert one deterministic root, one actual tool, no model span, exact native
span-ID set in the owned receipt and valid parent membership. An injected unknown
post preserves the completed result separately from unknown trace delivery,
blocks the same-thread repeat before another calculation and leaves the original
receipt intact. These controls exposed the actual native clone boundary that a
direct `_persist_run_single` mock had missed.

The cooperative unit integration uses the real SessionChatModel and LangGraph
interrupt/checkpoint path, with manually supplied assistant envelopes and no
provider request. It exercises interrupt → actual tool → interrupt → exact final
answer. It proves this local handoff contract, not model backend attestation or
autonomous host inference. The concurrency test uses controlled Events: the first
response pauses at dispatch while holding its owned journal lock; the second
fails lock admission; one legal reply advances and one tool receipt persists in
the subgraph. No sleeps are the ordering oracle.

Six independent in-memory mutations were executed and killed. The original
function identities were checked after patch restoration. MUT-001 allowed an
unknown outer request key; MUT-003 replaced exact arithmetic with a tolerance;
MUT-006 skipped the receipt artifact check; MUT-007 allowed an extra receipt
monetary claim; MUT-013 preserved private tags; MUT-031 always passed the grader.
There are no unexpected survivors among these six. The remaining frozen mutation
specifications are **NOT RUN by this verifier** unless covered in the separate
holdings evidence. Their absence prevents a claim that all 33 deliberate-break
specifications were executed.

The holdings owner receipt at
`.langchain-pilot/runtime/portfolio/579ab2ff-812c-41b3-b38c-8a5e124bd6da/holdings-tests.json`
was read and its relevant source hashes agree with the independent suite snapshot.
The independent suite reran all 168 holdings tests, including all sixty frozen
HOLD cases. The owner's fourteen mutation executions are separate evidence:
thirteen kills and one classified second-layer-enforcement survivor. Removing
both duplicate-identity enforcing layers killed the public-outcome control. The
verifier did not rerun those fourteen mutations or treat the owner's narrative
as independent execution.

The full criterion map follows. `PASS local` applies only to the specified
executed layer. Missing mandatory boundary evidence remains `NOT RUN`; it cannot
be inferred from a green unit suite.

| Criterion / designed cases | Independently executed local evidence | Remaining mandatory evidence / current status |
| --- | --- | --- |
| AC-001 / IN-01–08 | PublicBoundaryTests raw extra/nested/type/unknown/oversize envelopes; root PublicIngressTests for all three kinds; closed schemas; MUT-001 | Actual HTTP raw ingress and cloud sink scan NOT RUN |
| AC-002 / ISO-01–04 | Synthetic-only tests; forbidden socket at pure HOLD boundary; fake cloud clients; local path confinement | Current main/candidate process/config before-after and forbidden-effect live spies NOT RUN |
| AC-003 / CAL-01–10 | CalculatorContractTests individual exact cases; independent Fraction oracle; ArithmeticReceiptTests | Actual nominal public API execution/readback NOT RUN |
| AC-004 / CAL-11–17 | Individual metamorphic/domain cases; exact receipt inverse; MUT-003 | PASS local; live narrow nominal path still NOT RUN |
| AC-005 / CAL-18–30 | Individual invalid inputs with zero model dispatch; public invalid selector with zero model/tool | Actual HTTP invalid selector NOT RUN |
| AC-006 / MOD-01–06 | Real cooperative unit handoff; matching artifact/hash/thread/tool checks; forged receipt and no-tool inverses; MUT-006 | Actual native host/API cooperative result and exact cloud model/tool/final trace NOT RUN |
| AC-007 / MOD-07–11 | Wrong/extra final answer and extra monetary receipt controls; root hallucinated/no-tool tests; MUT-007 | Actual inverse public response and stored failure readback NOT RUN |
| AC-008 / SES-01–05 | Default no-provider model, ordinary persisted interrupt, logical three-request exhaustion control | Actual unserviced API pending/deadline behavior and native host bounds NOT RUN |
| AC-009 / SES-06–13 | Session response identity/schema/stale/unknown checks; controlled-barrier owning-lock concurrency; CLI unknown fences | Actual simultaneous HTTP replies and malformed public reply NOT RUN |
| AC-010 / SES-14–18 | Binding revision/rebind tests and authoritative in-memory checkpoint retention | Owned graceful stop/restart/rebind before/after tool NOT RUN |
| AC-011 / TRC-01–05 | Real native callback root/tool/ID/parent controls; cooperative model callbacks; holdings native tool-parent tests | Exact isolated cloud root/model/tool parentage and local/server identity correspondence NOT RUN |
| AC-012 / TRC-06–09 | Cooperative/deterministic tool-failure tests; holdings tool-error trace; SDK/session errors remain typed | Actual pending/error/cancel spans and terminal status readback NOT RUN |
| AC-013 / PRIV-01–06 | Public selector and assistant privacy guards; native metadata/tag/error cleanup; pre-eval remote raw-list admission; closed diagnostics; MUT-013 | Actual HTTP pre-export ingress plus exact full cloud payload/attachment scan NOT RUN |
| AC-014 / TRC-10–14 | Actual native cloned-callback post failure; result/trace separation; receipt preservation; same-thread repeat blocked | Exact cloud read-only reconciliation and 429/read-window control NOT RUN |
| AC-015 / HOLD-01–05 | All individual frozen cases; complete-scope empty versus failed/partial/unknown | Nominal/inverse public selectors through actual API NOT RUN |
| AC-016 / HOLD-06–10 | All individual frozen type/count/cash/requested-scope cases and boundary controls | Actual partial-scope public API readback NOT RUN |
| AC-017 / HOLD-11–15 | All individual matched/mismatch/unknown/ambiguity cases | PASS pure local scope; no real authentication claim |
| AC-018 / HOLD-16–20 | All individual currency match/mismatch/missing/mixed cases | PASS pure local scope; no FX/provider claim |
| AC-019 / HOLD-21–25 | All individual canonical duplicate/distinct instrument cases | PASS pure local scope; owner mutation evidence separately classified |
| AC-020 / HOLD-26–33 | All individual missing/null/bool/nonfinite/zero/denominator cases plus extreme-size controls | PASS pure local scope |
| AC-021 / HOLD-34–39 | All individual quote/query/cutoff/future/timezone cases and age boundaries | PASS caller-supplied synthetic scope; real freshness remains unverified |
| AC-022 / HOLD-40–46 | All individual exact long/short/leverage/NAV cases plus scaling/permutation/split/large Decimal controls | Actual mixed-long-short public API path NOT RUN |
| AC-023 / HOLD-47–50 | All individual daily-PnL absence/label cases | PASS synthetic current-holdings scope |
| AC-024 / HOLD-51–56 | All individual committed/unknown/stale/mismatched checkpoint cases; zero-provider repeated rejection | Actual API resume/restart inverse NOT RUN |
| AC-025 / HOLD-57–60 | All individual direct/graph parity, reuse, exception and unchanged-input cases | Actual registered holdings API result parity NOT RUN |
| AC-026 / API-01–05 | Exact config graph mapping, local schemas and every deterministic selector | Actual discovery/schema/run/state artifacts on owned listener NOT RUN |
| AC-027 / API-06–09 | In-memory occupied/invalid port and generic-tracing rejection controls; no exec/fallback | Actual owned PID/listener/config/main preservation plus supplied URL/API/browser readback NOT RUN |
| AC-028 / LIFE-01–07 | Source review only; in-memory launch rejection is not lifecycle proof | Startup/config failure, cancellation, drain/cleanup, retained-state restart and rollback NOT RUN |
| AC-029 / CLD-01–05 | Bootstrap positive/foreign-ID/unknown/no-recreation controls; complete source closure review | Exact owned resource identity/creation metadata and historical-resource preservation cloud readback NOT RUN |
| AC-030 / CLD-06–11 | Frozen artifact checks, exact local rosters, remote drift/duplicate/extra raw admission controls | Exact prompt commit/content, dataset version/as-of and frozen case-content cloud readback NOT RUN |
| AC-031 / CLD-12–17 | Correct/wrong grader, wrong expected output, owned-run/reference/project/root and wrong feedback inverses; MUT-031 | Full exact run/example/output/persisted-feedback cloud roster readback NOT RUN |
| AC-032 / CLD-18–23 | Bootstrap unknown-write fence, exact saved-ID read, missing-target no recreation; native trace unknown-repeat fence | Native bootstrap/eval/trace interruption reconciliation and bounded 429 read behavior NOT RUN |
| AC-033 / EVID-01–06 | Every test ID/count/status and mutation outcome retained; 196 designed distinguished from 302 executed; all 33 criteria mapped | Final live evidence and applicable setup gate pending; scheduled business execution/email UNVERIFIED |

There are no unresolved observed local defects at the recorded final revision.
The verifier authorizes no external activation. Root may proceed with the already
authorized bounded owned synthetic API/cloud verification. The verifier will
only perform read-only live verification after root supplies the candidate URL,
exact ownership manifests and runtime receipts. Main localhost:2024 PID 64553
was not started, stopped or queried by this verifier.

No future scheduled Codex business path or verified acceptance email ran here.
Major-runtime acceptance remains **unverified** under
`docs/deployment/runtime-acceptance.md`. Local synthetic success establishes no
investment alpha, real-account freshness, autonomous model dispatch, production
durability or production/scheduler acceptance.

The resumed verification reviewed the current 303-test owner receipt at
`atomic-independent/68e22cef-e070-447a-ae1f-d3809deeeddb/local-suite.json` and the
staging artifacts under `atomic-live/fef7fd42-a0f9-4ea4-8043-f1359cd241ea/`.
The staging manifest's complete source fingerprints match its recorded candidate.
It contains six selector result streams and three actual raw-extra-field error
streams, with closed schemas for all three public graphs. The cooperative
after-tool request retains one exact calculator receipt; after graceful restart,
the same thread's final result retains `tool_calls=1`, the prior checkpoint and
the matching pending request ID. The reported earlier harness assertion expected
a two-field projection from the full session result. Its failure is retained;
read-only reconciliation, not another response dispatch, confirmed the result.
These are independently inspected owner artifacts, not new live calls by the
verifier. Exact final API run/state and process/listener ownership still need
read-only verification on the final owned instance.

Actual staging cloud evidence exposed another defect: an implicit traceable
middleware wrapper was emitted outside the PublicTracer ledger and sanitizer.
The old `runtime/atomic/4df53344371ae67b` candidate's affected trace remains failed
or unverified; repairing source cannot certify that historical trace. The
independent `NativeSessionTransportTests` reproduced one unledgered emitted ID
using a genuine SessionChatModel interrupt, with every RunTree post/patch replaced
by local capture. The repaired candidate disables ambient implicit traceable
export while admitting the explicit native callback tracer. Both emitted-ID
equality and sanitized error/input/serialization controls now pass. No model
response is auto-serviced in this test.

Seven new TraceReadbackTests cover root parent, required native model/tool spans,
exact candidate metadata, and a valid final model segment whose calculator tool
belongs to an earlier recursively verified waiting segment. A completed segment
does not need to repeat its completed tool; the current successful model and
the actual tool across the exact same-thread/fixture/profile segment chain are
required. Root-only fabricated successful traces remain invalid. An initial
waiting model segment and a pre-tool rejection legitimately lack a completed
tool and are not falsely rejected for that reason.

The corresponding full independent rerun at
`atomic-independent/1794815304336005000/local-suite.json` passed **312 tests,
53 independent, zero skips/failures/errors**, with the six original independent
mutation controls killed and restored. Its candidate cloud-source SHA256 is
`d11b8436f73284c8055890e2b881e129b6d578d15215797c5624db21c04089ea`.
The nine added tests are the seven trace readback cases and two genuine pending
session transport-capture cases. This supersedes the earlier 302-test local
snapshot for those repaired boundaries.

A further narrow parent-identity control subsequently found that the checker
accepted a tool whose `parent_run_id` was its own ID. Merely requiring parent
membership in the returned ID set does not prove the actual nesting relation.
`TraceReadbackTests.test_completed_tool_parent_must_match_enclosing_root` records
that defect and must pass after the enclosing-parent check before the next final
candidate is accepted. The 312-test snapshot does not contain that later test.

No browser action was taken by the verifier. Root reports the user took browser
control; Studio connection/browser acceptance remains unverified and must not
be claimed from a printed or opened link. No cloud evaluation, production,
brokerage, email or scheduler effect was initiated by the verifier during this
resumed pass. The scheduled business/email acceptance gate remains unverified.

The bounded whole-checker review is now complete. After the enclosing-parent
repair, its remaining observed gaps were bundled before another activation:
wrong actual tool output could support a correct root, an unfinished model
child could count as successful inference, and private tags/extra metadata were
not independently rejected. Root completed the canonical checker repairs;
the verifier changed only test fixtures and regressions. The final sixteen
TraceReadbackTests validate exact root inputs/reference/type/name; parent nesting;
frozen result equality; required actual span types; terminal model evidence;
native tool output; closed errors; sanitized tags/metadata; and the legitimate
final-model/prior-waiting-model-selected-tool chain.

The tool fakes use the inspected native `{'output': ...}` envelope. Cooperative
tools have the exact ToolMessage data, arithmetic fields, case hash, tool-call ID
and thread artifact; their inputs are `{}`. The prior waiting positive includes
a successful native model message selecting that same tool ID, followed by the
actual tool span. Deterministic tools use the actual frozen case inputs. These
fixture changes preserve the behavioral expectations. Earlier incomplete fakes
caused missing-input/serialization errors; those harness errors were corrected
before the final green run.

Privacy controls now use different markers for the configured synthetic key and
the fake private metadata/path. An earlier same-marker version could fail at the
credential scan and did not independently prove tag/metadata enforcement. The
corrected controls exercise the intended sanitized envelope gate.

Final local evidence:
`atomic-independent/1794815752641403000/local-suite.json` — **321 tests executed,
62 independent, 0 skipped, 0 failures, 0 errors**. Source fingerprints were
captured before and after execution and were identical. All six frozen
independent mutation controls were killed with the original function identities
restored. The real pending SessionChatModel transport tests observe every native
RunTree post/patch without network calls or auto-servicing a model response;
the emitted ID set equals the owned ledger and error/input/serialization capture
contains no private model-path canary or raw interrupt stack.

This latest result supersedes the 312-test snapshot for the repaired checker
and resolves the later self-parent finding. There are no unresolved observed
material local defects within the bounded review. The tests are now frozen.
Final owned API/cloud/listener evidence still needs read-only verification on
the new source-version candidate. Historical failed or unverified traces remain
separate and are not accepted through the source repair.

Read-only final-instance verification began for candidate `d50c52458918dfe0`.
The verifier observed PID **13922** listening on `127.0.0.1:2025`, running the
pinned `strict_cli` with `atomic-langgraph.json`; PID **64553** remained listening
on `127.0.0.1:2024` with the original `langgraph.json`, and port 2026 had no
listener. Only process/listener reads were made for the main server. The final
ownership manifest and all three owned profiles agree with the frozen source
fingerprints and candidate hash.

Actual loopback API readback passed: the calculator, holdings and trading_pilot
graphs are discoverable; each actual input schema is closed at both envelope
levels and its selector enum equals the frozen public roster. Six exact
run/thread records and persisted states match the frozen nominal, debt,
invalid-shares, holdings nominal, long/short and partial-empty results. All three
extra-field negative runs remain errors, without result or trace values. State
metadata binds each read result to its exact run; no run was created or replayed
by the verifier. Graph/xray, schema, run and state responses are retained in
`atomic-independent/1794815922461503000/api-readback.json`.

The final cooperative run
`01a1e35d-6d78-7290-b393-563352f660b4` was independently read from the actual API.
It succeeded on the original final-model thread, its current state has no
interrupt or pending next node, and its complete result is the exact synthetic
per-share value 10 with one tool receipt and the declared answer schema.
The state binds cloud trace root
`9004207b-0ed1-4858-8817-2d92ce33e223` to the same final candidate. This independent
postcondition readback is retained in
`atomic-independent/1794816068671003000/model-api-readback.json`.

Root observed a LangSmith `/runs/query` 429 while reading children. The verifier
had made **zero LangSmith cloud calls** at that point and paused cloud reads.
Cloud trace verification remains pending the owner's bounded exact-ID direct-GET
manifest and coordinated read budget. No query retries, cloud writes or
evaluations were initiated by the verifier. Browser control remains with the
user; Studio/browser connection is unverified. Major scheduled business/email
acceptance remains unverified.

The later `d50c52458918dfe0` actual cloud diagnostics are not a passing
cooperative trace result. Root read six calculator/holdings traces successfully,
but the cooperative model spans were separate roots with no parent and their own
trace IDs. This was an observed failure, even though the API result was correct.
The source owner added native-parent context binding around the middleware
handler. The new independent native transport control checks that every actual
model span has the owned root's trace ID and a parent chain reaching that root.
Removing only this context binding reproduces the orphan failure and is killed
as MUT-011; the original function/context identity is restored afterward.

The service's automatic `dataset_split=['base']` metadata had also stopped
evaluation admission before an evaluation claim or write. Independent cases
now accept exactly absent or `['base']` split metadata, while other, private,
multiple, null, string and empty split forms reject before project creation,
evaluation dispatch or claim creation. No failed case or financial expectation
was changed to admit the service metadata.

The user's new 429 steering is covered by fourteen independent local
RatePolicyTests. They use a synthetic SDK transport, controlled clock and
workspace-private state. Cases cover validated parameters; numeric/date/past/
malformed Retry-After; uncapped server-priority delay versus bounded fallback;
one retry authority and maximum attempts; allowlisted read-only POSTs versus
one-attempt writes; explicit pacing-budget stops; durable category windows;
warmup once/failure; private records; and actual dispatch ordering. A controlled
two-client test exposed that an early reservation could be delayed and send at
the same time as a later reservation. The owner now retains the owned pacing
lease through transport completion and records the next interval in `finally`.
The dispatch-gap and exception-release tests pass. These are local policy
checks, not a guarantee against service quotas or unrelated account traffic.

The first full run after the new policy executed 339 tests and found three
adjacent regressions: bootstrap warmed up before checking its unknown-attempt
fence, and optional native-parent lookup outside a graph masked two SDK 401
sanitizer outcomes. These failures are retained at
`atomic-independent/1794816796782233000/local-suite.json`. Source-only repairs
restored the existing assertions without changing test expectations.

Latest final local evidence:
`atomic-independent/1794816920347892000/local-suite.json` — **339 executed tests,
80 independent, zero skipped, zero failures, zero errors**. Candidate source
fingerprints were stable before and after execution. Seven independent
mutations, including the actual native model-parent control, were killed and
restored. The fourteen rate-policy cases, dataset metadata admission and model
parentage checks are all included. The earlier API/cloud records remain tied
to their older source revisions. The next final intended-runtime API, native
trace and evaluation/feedback readback still must run against the new candidate;
the verifier has made zero LangSmith cloud calls during these passes.

For the next frozen candidate `7459ededd5d206d3`, the verifier independently
observed PID **20798** serving `127.0.0.1:2025` through the pinned strict CLI.
Main PID **64553** remained on port 2024 and port 2026 had no listener. Its
ownership manifest and source hashes agree with the latest 339-test snapshot,
including the rate-policy source/configuration. Actual API discovery, closed
schemas and selector enums for all three graphs passed again, as did six
exact persisted nominal/controlled-failure results and three raw-extra-field
error records. The model was genuinely pending with no result at this read.
No response was serviced by the verifier.

This candidate's independent API evidence is
`atomic-independent/1794817191612309000/api-readback.json`, including process,
listener, graph, schema, exact run and state responses. Restart/final cooperative
postconditions and exact direct-GET cloud trace/evaluation/feedback verification
remain pending owner manifests and the coordinated read budget. The verifier
has still made zero LangSmith cloud calls. No earlier candidate's native-trace
failure is converted to a pass by this API result.

The same-source final candidate then paused after tool execution, stopped the
owned PID 20798 gracefully and restarted on port 2025 as PID **22196**. The
verifier independently read final run
`01a1e371-f608-7673-bef1-8effa81e2d78` on thread
`01a1e370-037c-75fc-9ff3-7f3a0c9da1a7`; it is successful and its state has the
exact final synthetic result 10, one tool receipt and no pending interrupt.
The final resume request matches the request that was pending after the tool.

Beyond reading the owner's restart booleans, the verifier retrieved that exact
after-tool historical checkpoint from the running API with subgraph state.
Its full request and messages match the before-stop snapshot, including the
model-selected calculator call ID and one ToolMessage with the exact arithmetic,
case hash, execution thread and artifact schema. This proves retained checkpoint
and message content after the restart without another tool dispatch by the
verifier. The current process/listener read shows main PID 64553 still on port
2024, old PID 20798 absent and no port-2026 listener. Evidence is
`atomic-independent/1794817555437165000/model-restart-api-readback.json`.

Native cloud segment and evaluation readbacks remain pending the owner's exact
manifests. The verifier has made zero LangSmith cloud calls, created no run,
serviced no model response and made no server/browser changes during this
verification. Scheduled business execution and verified email acceptance remain
unverified.
