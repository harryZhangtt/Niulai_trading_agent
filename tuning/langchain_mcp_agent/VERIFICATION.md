# Isolated MCP verification — 2026-11-16

The remote trace-inspection capability passed its scoped real MCP/current-host
round and independent readback. The final local holdings tool acknowledged its
correct result. The final local calculator call timed out at10s; exact native
readback found its completed10 result after14.857335s, while acknowledgement
remains UNKNOWN and fenced. The final two-local-tool acknowledgement gate is
**not PASS**. The prior successful local-client candidate remains historical
evidence and was not relabeled as final-source acceptance.

Selected level: Balanced with independent deliberate breaks, under frozen
`mcp-atomic-v1.1`:14 criteria,36 requirement-derived development cases and14
mutation families. These are shared independent development cases, not blind
holdouts. The designed case count is not a live execution count.

| Evidence | Executed result | Scope |
| --- | --- | --- |
| Implementer client suite | 16 tests, zero skipped/failure/error | Endpoint/protocol/secret/schema/depth/byte/cancel/rate/unknown-effect controls |
| Independent suite | 51 tests, zero skipped/failure/error | Protocol, scope, exact grading, budgets, real disposable HTTP cleanup, persisted LangGraph handoff and checkpoint concurrency/reload |
| Independent deliberate breaks | 14 KILLED; included in the51-test roster | One discriminating in-memory variant per family; original files restored/hashed |
| Real final trace-inspection agent | 4 logical queries,4HTTP,4pages,0retry;3 host model requests; completed | Real hosted query_runs through the new client; two fixed owned synthetic traces |
| Independent real-artifact review | 69 assertions, zero failures | Manifest/source/native references, checkpoint ToolMessages/bytes, bound host replies, exact root/hierarchy/output/scope, route ledger and deployed API graph records |
| Independent local recovery/state review | 35 consistency assertions, zero failures | Original calculator unknown fence/no replay, native recovery limits, final holdings acknowledgement, three retained Studio/API states |
| Final local holdings MCP | PASS, net700/gross1100/cash300/NAV1000 | New-client final-source call, one dispatch/acknowledgement |
| Final local calculator MCP | Transport timeout; UNKNOWN/fenced | One dispatch; native calculation10 later confirmed; no replay or fabricated acknowledgement |
| Original atomic baseline | 339 executed/80 independent, zero skipped/failure/error at its recorded revision | Source/history hashes preserved; not rerun as part of the new MCP suite |
| Calculator cloud evaluation | 7/7 exact output/example/run/feedback readbacks | Existing unchanged atomic producer candidate |
| Holdings cloud evaluation | 26/26 exact output/example/run/feedback readbacks | First unknown preserved; read-only reconciliation, no evaluation replay |

The67 new unittest cases are16 implementer plus51 independent. The14 mutation
tests are included in that total; the69 evidence assertions are reported
separately, as are the35 local recovery assertions. Existing339 proof and its
earlier failed revision remain frozen.

The final source/config/schema/prompt/oracle closure is privately sealed in
`runtime/mcp-agent/manifest-9f21f42c-0125-471a-a2d5-3dc74abb11b5/manifest.json`,
canonical SHA256 `58fea1ddb4ead0ad287f8a2f5f310077857735975f2c2e2f5c79a6abde1fdff0`.
Current source hashes match the independent51-test run and actual completed
round `fc673d4e-013a-47f3-94fc-81ab74b02e9c`.

All runtime paths below are relative to private `.langchain-pilot/`:

- `runtime/mcp-independent/1794821104717829000/`: final suite/log/source manifest,
  independent report,69-assertion live readback, reproducible verification script
  and35-assertion local acknowledgement/unknown-fence supplement. The hashed
  `final-review-manifest.json` indexes the completed independent review.
- `runtime/mcp-agent/fc673d4e-013a-47f3-94fc-81ab74b02e9c/`: actual FileSaver
  checkpoints, host replies, four query result strings/byte counts and comparison.
- `runtime/mcp-agent/local-holdings-final-48e64656-b2e1-4fbc-8675-28c2f33a2979/`:
  final holdings MCP intent/discovery/response/result.
- `runtime/mcp-agent/local-recovery-aa2591ed-d7f2-4eaf-9331-768d4da1a654/`:
  owned native readback of the unique compatible calculator completion. It
  explicitly leaves RPC-to-thread correlation un-attested and delivery unknown.
- `runtime/mcp-client/effects/aa2591ed-d7f2-4eaf-9331-768d4da1a654.*`:
  original dispatching intent and unknown fence; no acknowledgement receipt.
- `runtime/mcp-agent/studio-readiness-97f7d283-202a-451a-909d-28d095b55771.json`
  and `studio-persistent-examples.json`: actual three graph/schema/xray readbacks
  and retained terminal Studio/API thread states.
- `runtime/atomic/7459ededd5d206d3/holdings/`: submitted evaluation26, preserved
  first unknown/output, diagnostic and successful read-only reconciliation.
- `runtime/mcp-agent/local-e2e-5108416a-d3e4-4e34-9eab-644a1021be69/`:
  earlier real local calculator/holdings MCP acknowledgement PASS; historical
  source binding retained, not promoted to final-source proof.

Independent source findings about resume-manifest binding, malformed-call
budgets, inherited tracing, unterminated SSE, attempt/logical deadlines,
external schema references, private app-path/auxiliary fields and checkpoint
concurrency were repaired and validated. The supplied-deadline reproducer first
failed; that failure and the initial verifier fixture/harness failures remain
in `runtime/mcp-independent/`. A stopped three-query round and an earlier
completed serial round remain under their original manifests. No expectations,
old failure histories or source-document revision were weakened or replaced.

The later local calculator timeout is a real operational limit, preserved
separately. The pinned Agent Server MCP implementation waits for the complete
graph output, including this producer's synchronous cloud trace callbacks.
The timeout overlapped cloud evaluation/readback. Server duration exceeds the
frozen client limit; contention alone is not proven as the cause. Increasing
the timeout or replaying the call to obtain a nominal PASS was not attempted.
The client's empty elicitation capabilities select the pinned stateless
`AssistantTool.run_once -> runs.wait(thread_id=None)` path. Its default temporary
thread deletion is consistent with the observed404; the explicit CallThread
elicitation path is separate. This does not attest RPC/thread correlation.
Retained ordinary Studio threads are a different lifecycle. A full asynchronous
lifecycle MCP controller is not implemented.

Graph/API readiness passed: `calculator`, `holdings` and `trading_pilot` are
registered on2025, and xray expands holdings snapshot admission/portfolio
analysis and the cooperative calculator's validation/model/tools workflow.
Three retained ordinary Studio thread results were checked. Actual browser
connection stability remains UNVERIFIED, as do native-host MCP registration,
provider/backend identity attestation, real holdings retrieval, unattended
dispatch, managed LLM evaluators and future scheduled business/email acceptance.
No existing server, browser permission, broker, email, scheduler or global
configuration was changed. Both2024/2025 listeners remain running;2026 is stopped.

The Lark source was read and privately pinned at revision4473 with SHA256
`654269626985fa210b39eb72e2238e7cc2a15a5cb2bc10d170babea2060bc4ba`.
Only generalized [practical takeaways](TAKEAWAYS.md) enter the source report.
See [setup/recovery](../../docs/deployment/langchain-mcp.md). The final snapshot
contains exact source/config/test hashes and evidence references; credentials,
raw source document, private account state and runtime archives are excluded.
