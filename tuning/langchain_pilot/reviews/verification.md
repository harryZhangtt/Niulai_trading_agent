# Independent pilot verification

Reviewed on 2026-11-15 against the frozen balanced criteria in
`tuning/langchain_pilot/ACCEPTANCE.md:3–26`. This review owns this report and,
after an explicit follow-up assignment, the independent `test_smoke.py` controls.
No implementation, criteria, configuration, processes or private production
state were changed by this verifier. No provider or network calls were made. Missing actual
`MENTOR_INIT_OK` output was disclosed; mentor policy/router and the local
development-discipline skill were read directly. The backend-testing skill's
independent-verifier and exception-safety procedures were applied.

**Verdict: one material finding found and repaired; no remaining material source
finding in this bounded review. Pilot acceptance still has insufficient evidence.**
The inspected isolated-live Ferry attempt failed. The repaired source passes all
16 current offline tests. This pilot does not satisfy production runtime acceptance.

## Finding V-01 — smoke success is not bound to the created run

**Medium, LC-04 / LC-05; repaired and independently retested offline.** In the
initially reviewed revision, `smoke.py:49–51` captured the newly created run ID,
but `smoke.py:71–78` accepted the first run returned by `runs.list`, then overwrote
the captured ID. It never verifies that these IDs match. It also collects error
stream events without rejecting them (`smoke.py:62–68`). A successful state value
alone does not establish the outcome of the exact submitted run.

An independent offline negative control used the real `smoke.main` with an
in-memory SDK double and all filesystem writes mocked. The stream callback
created `expected-run` and emitted an error for that run. State retrieval returned
`{"result":{"status":"passed","per_share":"10"}}`; run listing returned
`[{"run_id":"different-run","status":"success"}]`. The runner recorded
`status=passed, run_id=different-run`. An assertion that the receipt retain the
created identity failed. Thus an interleaved/stale or inconsistent run response
can produce false completion even though the submitted run is not successful.
This is an evidence-integrity defect in the synthetic smoke runner, not evidence
of a trading or delivery effect.

The implementer repaired this in smoke source SHA-256
`5d2044b4590791be66c00150e216209b8fa45da5d36a7fd55dc8295c3525277b`.
The current implementation rejects error streams and mismatched metadata
(`smoke.py:68–74`), queries the exact callback ID and checks returned identity/status
(`smoke.py:78–82`), then accepts only that stream's final values with the expected
case ID (`smoke.py:83–88`). The verifier's nominal/inverse regression tests pass
(`test_smoke.py:83–169`). This repairs the source-level defect; it does not turn
the failed earlier live attempt into success.

## Executed evidence

Interpreter: `.langchain-pilot/.venv/bin/python` (Python 3.12). Every executed
command set `LANGSMITH_TRACING=false`, `LANGCHAIN_TRACING_V2=false` and
`PYTHONDONTWRITEBYTECODE=1`, with `-B`.

```sh
.langchain-pilot/.venv/bin/python -B -m unittest tuning.langchain_pilot.test_graph tuning.langchain_pilot.test_smoke -v
```

Initial verification executed the supplied **6 tests: 6 passed, 0 failed,
0 skipped**, followed by an inline, provider-free suite of **8 tests: 7 passed,
1 failed, 0 skipped**, exposing V-01. The inline tests were not added to source.
After the repair, the current combined suite executed **16 tests: 16 passed,
0 failed, 0 skipped** (the original 6 plus 10 independent smoke controls).
Across these three invocations: **30 test executions, 29 passed, 1 failed,
0 skipped**; the earlier failure is retained as defect-discovery evidence.

| Independent control | Result |
| --- | --- |
| Nine malformed/boundary numeric cases across cash flows, terminal value, rate, debt and shares reject before any model invocation | PASS |
| Model-supplied tool arguments cannot substitute a different case | PASS |
| Extra public-input messages cannot inject a successful tool receipt | PASS |
| Model exception propagates after one attempted model call | PASS |
| Repeated tool selections stop after exactly three model calls | PASS |
| A cooperative model handler times out and receives cancellation | PASS |
| Caller cancellation reaches a cooperative model handler | PASS |
| Smoke completion must retain the exact newly created run identity | Initially FAIL — V-01; repaired-source regression PASS |

The ten retained smoke tests additionally distinguish exact-run success from a
failed exact run, wrong `runs.get` identity, wrong stream metadata, missing
creation identity, and a stale latest-thread result. Cancellation remains
`unknown` and requests cleanup only for the captured exact run. A pre-identity
timeout does not guess a run, and cleanup failure does not hide the original
cancellation. All SDK interactions and artifact writes are mocked in this suite.

The middleware timeout test shortened only the in-memory wait to 0.01 seconds,
while asserting that the implementation requested 90 seconds. These tests prove
cooperative cancellation of the middleware handler, not SDK/gateway cancellation,
server shutdown or absence of a live orphan. No source mutations were performed.

## Criterion traceability and limits

| Criterion | Evidence and status |
| --- | --- |
| LC-01 | PARTIAL: local environment exists; direct requirements are pinned and the lock contains resolved hashes. Installation and global-environment non-mutation were not independently rerun. |
| LC-02 | PARTIAL: fake-model public-graph tests prove tool execution and rejection of hallucinated/no-tool answers. State binding is explicit at `graph.py:73–79`; the independent Fraction oracle and exact final-answer comparison are at `graph.py:121–159`. Real inference has no successful receipt in the inspected evidence. |
| LC-03 | PASS for tested atomic cases: validation precedes the agent edge (`graph.py:106–118, 179–184`); supplied and independent negative controls observed zero model calls. |
| LC-04 | NOT ACCEPTED: source maps the server graph correctly (`langgraph.json:2–5`), and V-01 is repaired offline, but the inspected live attempt failed. No live API call was executed by this verifier. |
| LC-05 | PARTIAL: tool/model failures and call limits pass offline; provider retries are disabled (`graph.py:93–96`). The graph exposes only the calculator tool (`graph.py:163–175`). Cooperative timeout/cancellation passed. Live cancellation/readback and cleanup are unverified; the latest receipt reports a cleanup error. |
| LC-06 | NOT RUN: no stop/restart or process inspection was authorized for this verifier. The launcher confines dev-server working state and binds loopback (`serve.py:17–29`), but source is not restart evidence. No Studio/browser interaction was tested. |
| LC-07 | PARTIAL: this bounded independent source review is complete; other source-review deliverables are outside this verifier's assigned ownership. |
| LC-08 | NOT RUN: setup installation, documentation synchronization and setup audit are outside this unit-only assignment. No setup-complete claim is made. |

Read-only inspection was limited to the allowed synthetic `live-*/receipt.json`
files. Three earlier Anthropic-protocol receipts were failed, and another remained
`started` despite a retained elapsed time of 419.975 seconds; their source hashes
differ from this candidate. They are neither current-candidate passes nor proof
that the current timeout is broken. The current Ferry receipt at
`.langchain-pilot/runtime/live-1794754669222256000/receipt.json` ended **failed**
after **90.712 seconds**, with `error_type=ValueError`,
`cleanup_error_type=HTTPStatusError`, and no result. Its source hashes match those
for the initially reviewed candidate; smoke source was subsequently repaired.
The receipt alone does not establish the underlying transport error or
terminal cleanup state. Actual backend identity remains unverified.

The smoke receipt hashes the client's current files and reads its model name from
the client's environment (`smoke.py:40–47`). This is not independent proof of the
source/model already loaded in a server started with `--no-reload`
(`serve.py:23–25`). Preserve server-start fingerprints/configuration with future
execution evidence; do not infer that binding from the receipt alone.

## Adapter suitability and remaining acceptance boundary

The narrow adapter is appropriate for this exploratory calculation path: it
delegates to the unchanged pure `equity_value` function (`graph.py:65–69`;
`shared/calculation/legacy/valuation/valuation_core.py:50–66`) and keeps model
choice away from calculator inputs. The tested contrast case distinguishes debt
and cash-flow changes. The arithmetic gate checks per-share value, not the
validity of forecasts, valuation assumptions, source provenance or investment
quality. It does not require a scheduler, trading or email migration.

The baseline/concise context switch (`graph.py:108–113`) is only a prompt variant
hook. It does not establish matched A/B evaluation, durable experiment admission,
production state ownership, or a general runtime adapter. Those integrations
should remain behind their existing owner contracts.

Live inference, exact-run completion, server restart/persistence and Studio
interaction were intentionally not rerun. No production, load or recovery tests
were executed. A major production integration still requires a real future-triggered
Codex business session and independently verified email synchronization under
`docs/deployment/runtime-acceptance.md`; local tests, this review and an eventual
manual pilot pass cannot replace it.

## Reviewed fingerprints

Installed versions observed: langchain 1.5.0, langgraph 1.2.22,
langchain-openai 1.8.0, langgraph-cli 0.4.43, langgraph-api 0.18.0.

| Source | SHA-256 |
| --- | --- |
| ACCEPTANCE.md | `2a4ae9bb57568ecec785100f705d265560456ee1c781e6d9704363c5d35d78ca` |
| graph.py | `265064306fbcd2052bd15be38b84fc3f7ec98b4056ba4792c7c07d0f5dfe7894` |
| smoke.py — initially reviewed / failed live attempt | `abdb269bc258240757a9e33626b593a68456234c556fbea361f566b653135387` |
| smoke.py — repaired, 16-test pass | `5d2044b4590791be66c00150e216209b8fa45da5d36a7fd55dc8295c3525277b` |
| serve.py | `ca994af70dd47e20fe1a2ce35f980ecfe5ebd7d5471deb9235cbbf38aff204ed` |
| test_graph.py | `fe5582ad7f040b2a7b74d08be0f13d54fb3e9d5e90bcce42aeeb8432b5195aeb` |
| test_smoke.py | `82a04da42a2e8b4d3055afb1ff80ea98fb998f374d73a0f8ac887b426e9177ab` |
| requirements.in | `0f21ca07381cb027dc6e823c4e38cb0bd78c778421967c44419148346d083027` |
| requirements.lock.txt | `21f06a21c79b807a14ee657eaac795276731450907ca83745359c23cc228fd2d` |
| langgraph.json | `9293b5014c77a2a2561ecd5e7b4f87a8a45a2684767702994d5a19d613400f8f` |
