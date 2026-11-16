# Isolated LangChain MCP setup and recovery

This component makes the deployed Agent Server and hosted LangSmith Remote MCP
usable through a bounded project-local client. The inspection experiment lives
in `tuning/langchain_mcp_agent/`; shared HTTP/protocol handling lives in
`shared/langchain_mcp/`. Importing either component registers no MCP server with
Codex. `shared/langchain_mcp/host-candidate.json` stays disabled.

Use the existing hash-locked `.langchain-pilot/.venv/` described in
[the pilot runbook](langchain-pilot.md). The new client explicitly uses the
already locked requests 2.34.2, jsonschema 4.26.0, python-dotenv 1.2.4 and
urllib3 2.8.0; the agent uses LangChain 1.5.0 and LangGraph 1.2.22. Verify exact
versions against `requirements.lock.txt` on the target device. No global install,
new package installation, FastMCP server, MongoDB or Redis is needed.

The exact endpoints are `http://127.0.0.1:2025/mcp` and
`https://api.smith.langchain.com/mcp`. Local discovery exposes `calculator`,
`holdings`, and `calculator_session`; Studio uses `trading_pilot` for that last
graph. Remote discovery exposes `query_runs`; `fetch_runs` is deprecated and
is not an automatic fallback. Actual negotiated protocols are checked against
the supported 2025-06-18/2025-11-25 set. Every selected tool schema is hashed
and checked on subsequent connections. External schema references, inherited
proxies, redirects and endpoint overrides are rejected.

The remote key stays in `.langchain-pilot/langsmith.env`, a no-symlink, regular,
owner-owned 0600 file containing only `LANGSMITH_API_KEY`. Resolve it on dispatch;
never paste it into an MCP config, model prompt, argument, log or report. The
client sends it only to the exact remote endpoint in the `X-Api-Key` header.

Private state is under `.langchain-pilot/runtime/mcp-client/` (pacing, attempts,
effect fences) and `.langchain-pilot/runtime/mcp-agent/` (sealed manifests,
checkpoints, internal host replies and measured tool results). The document
snapshot stays separately in `runtime/mcp-review/`. Caches and temporary tests
stay under `.langchain-pilot/cache/` and `.langchain-pilot/tmp/`. Do not copy
private state or credentials to another device.

The existing port-2024 and atomic port-2025 servers are separate. Preserve the
2024 server. Never run two atomic servers against `runtime/atomic-server/`.
The atomic server's launch and graceful recovery contract remains owned by the
pilot runbook; this client does not restart or configure it.

## Owned synthetic E2E

Run from the workspace root with tracing explicitly disabled:

```sh
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m unittest \
    tuning.langchain_mcp_agent.test_client \
    tuning.langchain_mcp_agent.test_independent
```

`python -B -m tuning.langchain_mcp_agent prepare` is an integration-owner
preflight for the two recorded synthetic traces. It validates exact native
readback independently, preserves the actual raw root/hierarchy/outputs, and
seals the source/config/schema/prompt/criterion closure. It is not a general
private trace importer or inspection fallback. `reseal --manifest <owned-path>`
creates a new candidate after a repair using the preserved oracle; it never
rewrites old manifests or accepted/failed rounds.

```sh
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_mcp_agent \
    self-test --manifest <owned-private-manifest>
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_mcp_agent \
    start --manifest <owned-private-manifest>
```

Self-test invokes both local tools once and checks calculator 10 and holdings
net 700/gross 1100/cash 300/NAV 1000. It creates synthetic graph runs/traces;
do not blindly repeat after an unknown result. Each call has a persisted intent,
receipt and permanent replay fence. `MCPClient.effect_status(intent_id)` is
read-only diagnosis. Missing acknowledgement remains unknown unless an exact
owned server identity can be reconciled independently; this client never clears
the fence or guesses that a timeout means nothing executed.

The Agent Server MCP tool waits for a complete graph result. The observed final
calculator self-test timed out at10s while its owned native execution completed
after14.857335s; transport acknowledgement remains UNKNOWN/fenced and was not
replayed. Native readback is separate business-postcondition evidence. A finished
MCP thread returned404 by the state API, while the retained ordinary Studio/API
example threads remained available. Their private IDs/state URLs are recorded
in `runtime/mcp-agent/studio-persistent-examples.json`. Do not treat MCP tool
history as durable Studio thread history or silently bypass MCP with an API
call. Long-running async lifecycle control is a separate integration contract.

The agent uses current `create_agent` and `SessionChatModel`. The current host
supplies assistant messages through private internal handoff; the framework
executes `inspect_trace` over real MCP. The user-facing Studio tests use the
deterministic graphs and do not ask the user for raw resume JSON. There is no
unattended model provider or automatic background dispatcher. The private
`pending.json`, runner `pending`/`respond`/`report` operations and file checkpoint
permit the same host to resume without reconstructing tools or results. Resume
requires the exact saved manifest, source closure, request and session binding.

Each round permits four logical inspections, one per calculator/holdings ×
full/compact pair. Invalid calls count before argument validation. At most five
model requests are admitted. Query scope is generated from the sealed private
manifest: exact workspace/project/trace, fixed time window, fields and cursor
limits. The grader checks exact node set, actual root, parent ancestry, terminal
status, full outputs and private-payload allowlist. Full/compact comparisons count
the actual serialized response's UTF-8 bytes, separately from HTTP attempts,
decoded wire bytes, pages, tokens and cost.

## Policy and failure recovery

`shared/langchain_mcp/policy.json` owns a 10-second HTTP attempt and 30-second
logical-read deadline, two replay-safe read attempts, two query pages, a 0.5-second
read/warmup delay and 15-second query interval. Responses are bounded to 2 MiB
and logical decoded bytes to 4 MiB; tool schemas to 256 KiB, depth to 32, and
discovery to 100 tools. Smaller safety limits are allowed; larger limits fail.
The pinned requests/urllib3 body path uses `read1` and the remaining absolute
socket timeout; an unavailable bounded reader fails visibly. Owned response
bodies and sessions close on success, malformed response, timeout or cancellation.

Warmup is the delayed MCP initialize/list handshake, with recorded protocol and
schemas. Valid numeric/HTTP-date `Retry-After` takes precedence. A delay beyond
the remaining budget defers rather than dispatching early. Only semantically
classified remote reads retry 429; local graph calls can create state and execute
once. Permanent auth/schema/protocol errors stop. One retry authority prevents
inner/outer retry multiplication. Pacing holds its lock through transport and
starts the next interval after completion.

Keep failures, unknown effects and failed manifests. Stop invoking the candidate
to roll back; no host config, scheduler, browser, email or broker change needs
undoing. Reusing a new candidate requires new owned source/schema evidence.
Activation in the native host remains a separate disabled rollout under
[MCP stability](../mcp-stability.md), with disposable lifecycle/failure tests,
owned backups and tested rollback. Scheduled business/email acceptance remains
unverified under [runtime acceptance](runtime-acceptance.md).

Official references: [Agent Server MCP](https://docs.langchain.com/langsmith/server-mcp),
[LangSmith Remote MCP](https://docs.langchain.com/langsmith/langsmith-remote-mcp).
The document's older agent examples were adapted to the installed current API;
the private source revision and content hash are preserved by reference only.
