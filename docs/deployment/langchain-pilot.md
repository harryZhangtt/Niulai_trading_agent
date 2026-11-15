# Isolated LangChain and LangGraph pilot

This additive experiment lives in `tuning/langchain_pilot/`. It tests a fixed
validation workflow around a small `create_agent` harness. Its only tool wraps
the unchanged Decimal calculator in
`shared/calculation/legacy/valuation/valuation_core.py`. All inputs are synthetic.
It has no trading, account, source-acquisition, email, shell or scheduler tools.
It does not activate a production integration or replace existing services.

## Dependencies and paths

- Explicit host prerequisite: uv (tested 0.13.7) and Python 3.12 (tested 3.12.16).
- The tested environment reuses the workspace-owned Python interpreter already
  below `.job-runtime/python/`, without installing into that environment.
- New environment: `.langchain-pilot/.venv/`.
- Cache/build/temp: `.langchain-pilot/cache/` and `.langchain-pilot/tmp/`.
- Dev persistence and private receipts: `.langchain-pilot/runtime/`.
- Direct pins: LangChain 1.5.0, LangGraph 1.2.22, langchain-openai 1.8.0,
  langgraph-cli[inmem] 0.4.43, python-dotenv 1.2.4. Resolved hash lock includes Agent Server 0.18.0.
- `requirements.lock.txt` is the install contract. `requirements.in` is the small
  explicit direct dependency list. Re-resolve only as a separately tested update.

From the workspace root, with an explicitly available Python 3.12 interpreter:

```sh
mkdir -p .langchain-pilot/cache .langchain-pilot/tmp
UV_CACHE_DIR="$PWD/.langchain-pilot/cache" \
TMPDIR="$PWD/.langchain-pilot/tmp" UV_PYTHON_DOWNLOADS=never \
  uv venv --python /path/to/python3.12 .langchain-pilot/.venv
UV_CACHE_DIR="$PWD/.langchain-pilot/cache" \
TMPDIR="$PWD/.langchain-pilot/tmp" UV_PYTHON_DOWNLOADS=never \
  uv --system-certs pip sync tuning/langchain_pilot/requirements.lock.txt \
    --python .langchain-pilot/.venv/bin/python --require-hashes
```

If a clean device needs Python, keep that download local too, for example with
`UV_PYTHON_INSTALL_DIR="$PWD/.langchain-pilot/python"` and the same local uv
cache/temp variables before `uv python install 3.12.16`. Select that interpreter
explicitly for `uv venv`. No global package or skill installation is required.
The clean-device Python download is a documented alternative, not part of the
current test. The locked dev runtime includes a small source-built package;
`--no-build` incorrectly forces obsolete dependency resolution or fails.

## Model connection and limits

The default is `LANGCHAIN_PILOT_ENGINE=session`: an existing chat session supplies
only model activities through `SessionChatModel`. LangGraph persists each bounded
message/tool request as an interrupt. The host returns an assistant message;
LangChain executes its selected allowlisted tool, maintains workflow state and
checks the result independently. No Platform key, Ferry call, copied login token
or LangSmith key is needed for this mode.

This is cooperative execution. Studio Submit pauses at a model request; this chat
or a later explicitly configured host must read and answer it. There is no native
session wake-up, background dispatcher or automatic polling. Session/model IDs
are declared metadata, not authentication or independently attested model identity.
Binding revisions select the owner for subsequent model-response admission; they
do not revoke a message already admitted at the graph-side binding snapshot.
The adapter and graph cap message sizes and allow at most three model calls.

An optional `LANGCHAIN_PILOT_ENGINE=openai` selects ChatOpenAI Responses at the
explicit `https://api.openai.com/v1` endpoint, requesting `gpt-6.1-sol` with low
effort and 1024 output tokens. Inherited base-URL variables cannot route it to
Ferry; Ferry/Claude-prefixed selections are rejected. This optional engine needs
a Platform key from `OPENAI_API_KEY` or the ignored owner-private
`.langchain-pilot/.env`. Preserve an existing file; the nonsecret example is
`tuning/langchain_pilot/openai.env.example`. The file must be owner-owned, regular,
0600 and at most 16 KiB. Only `OPENAI_API_KEY` is read, at dispatch; schema/input
inspection works without it and missing credentials cause zero HTTP dispatches.
Never copy native subscription tokens or put credentials into chat/source/logs.

The optional API engine streams, uses a 60-second I/O timeout, a 90-second model
wall bound and zero SDK retries. Its smoke process has a 240-second outer bound,
records the created run and requests cancellation on disconnect. SDK failures are
reduced to credential-free codes; unknown outcomes remain fenced. Historical
Ferry timeouts and the unsuccessful native-Codex preflight remain separate
failed/unknown evidence. A live pass for the optional API route is unverified.
Neither engine changes global configuration, shared jobs or the Ferry daemon.

## Run and verify

Run the provider-free checks, configure a declared host session, then start the
server from the workspace root:

```sh
LANGSMITH_TRACING=false LANGCHAIN_TRACING_V2=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m unittest \
  tuning.langchain_pilot.test_graph tuning.langchain_pilot.test_smoke \
  tuning.langchain_pilot.test_openai_route tuning.langchain_pilot.test_session_engine \
  tuning.langchain_pilot.test_session_cli -v
.langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.session_engine \
  configure --session-id <declared-host-session-id>
LANGCHAIN_PILOT_ENGINE=session PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.serve --allow-blocking
```

The launcher runs stock `langgraph dev` on 127.0.0.1:2024, one worker, no hot reload
or automatic browser, and workspace-local persistence/cache/temp. It disables
cloud tracing. `--allow-blocking` is an optional development compatibility flag;
omit it to retain blocking-I/O detection. Source edits need an owned restart.

In another terminal, discover or create a thread and read its pending request:

```sh
.langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.session_engine list
.langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.session_engine \
  start --case-file tuning/langchain_pilot/examples/valuation-case.json
.langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.session_engine \
  pending --thread-id <thread-id>
```

The host reads the returned messages/tools and supplies only this envelope on
stdin to `respond --thread-id <thread-id> --session-id <current-session-id>
--revision <current-revision>`:

```json
{
  "request_id": "<pending-request-id>",
  "binding": {
    "protocol": "session-model-v1", "engine_id": "codex-session",
    "session_id": "<current-session-id>", "revision": 1
  },
  "message": {"tool_calls": [{"name": "calculate_valuation", "args": {}}]}
}
```

Copy the exact current binding returned by the CLI, including revision. After the
tool runs, read the next request and submit assistant `content` containing the
exact JSON answer instructed by that request. Do not submit tool messages or
replace the financial inputs. A later session uses `configure` with its own ID,
then `list` and `pending` for the same thread; messages and completed tools stay
in LangGraph rather than being reconstructed in the new chat.

The CLI checks exact run identity/status, stream errors and run-bound interrupt
or final-result evidence. Private per-request attempt receipts preserve every
rejection/failure. Only a confirmed graph rejection of the same pending request
allows a new attempt. Processed, failed, dispatching or unknown receipts require
reconciliation before replay. Rejections and failures exit nonzero. Do not delete
receipts or resume an ambiguous dispatch to obtain a pass.

For the optional API engine, start a separate owned server invocation with
`LANGCHAIN_PILOT_ENGINE=openai` before running `python -m
tuning.langchain_pilot.smoke`. That smoke client assumes autonomous API inference;
it does not service cooperative session interrupts. A health response or graph
visibility alone is insufficient. The independent graph gate requires a real,
bound calculator receipt and exact arithmetic/answer agreement. Baseline/concise
variants expose a configuration seam, not a measured A/B quality improvement.

Studio connection URL: `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`.
On 2026-11-15 the user's authenticated Studio page was connected through
**Connect a local server**, with Base URL `http://127.0.0.1:2024` and no custom
headers. Native Chrome accessibility readback showed `trading_pilot` and the
`validate_input -> agent -> validate_result` graph. This is actual browser
connection/graph evidence, separate from the CLI's printed URL. Studio displayed
a missing `LANGSMITH_API_KEY` notice; cloud tracing remains disabled. On another
device, hosted authentication and browser-local connection consent may still be
required. Do not copy browser cookies or credentials to reproduce the connection.

Port 7270 is reserved for the existing datasource/scheduler dashboard. It does
not serve the Agent Server protocol. Keep that app and this development server
on separate ports. The launcher supports an explicit `--port` if needed; Studio
must use the same chosen endpoint.

## Studio input

In Studio's **Case** field, paste the inner valuation object:

```json
{"case_id":"debt-test","fcff":["220"],"terminal_ev":"0","rate":"0.1","net_debt":"50","shares":"10"}
```

**View Raw** instead accepts `{"case": { ...the valuation fields... }}`. One exact
accidental extra `case` wrapper is normalized. Missing cases give an actionable
error; extra fields, nonfinite numbers and invalid financial inputs remain
rejected before a model request. This synthetic example expects per-share `"15"`.
Submit will pause for this session to supply a model reply in session mode.

## Current integration and evidence

The graph directly imports the existing calculator; no agent source copy or
import-sync process is needed. Acquisition, evidence completion, runtime and
delivery retain separate owners. The next proposed slice and validation gates
are in [the migration plan](../plans/langchain-agent-migration.md). That plan does
not implement the whole Trading Agent.

On 2026-11-15 cooperative public-API E2Es completed with actual host assistant
replies, one LangChain calculator tool call and independent final checks: the
original synthetic case returned `"10"`, and the user's debt case returned `"15"`.
A graceful restart at a pending model request preserved its messages and tool
receipt; rebinding revisions rejected a stale reply and allowed completion on
the same host. This establishes neither production crash durability nor an actual
second-native-host handoff.

The latest recovery candidate passed 42 provider-free tests with zero skipped,
and an independent bounded re-review reported no remaining findings for the
reviewed reproductions. These include malformed/nonfinite response recovery,
rebind rejection followed by a valid reply, preserved unknown fences, visible
run failure and rejection of another run's projected success. The active
`--no-reload` server still uses the prior source; the latest source's live restart
canary is pending. Tests and review do not upgrade that unverified boundary.

Historical Ferry failures/unknowns are retained separately. The optional official
API route has no verified live inference pass. No native automatic dispatcher,
production scheduler, broker, email or cloud tracing has been activated.

## Stop, recover and acceptance

Stop the foreground server with Ctrl-C. Restart with the same launch command,
then inspect a completed synthetic thread without creating another run:

```sh
LANGSMITH_TRACING=false .langchain-pilot/.venv/bin/python \
  -m tuning.langchain_pilot.smoke --inspect-thread <thread-id>
```

The dev server uses local persistence intended for development. A successful
graceful stop/restart is not production crash-recovery or exactly-once evidence.
Preserve failed and unknown attempts; do not delete runtime state to obtain a
pass. Rollback is stopping this local process and ceasing to invoke the pilot;
there is no production configuration to revert. Dependencies and state remain
isolated and ignored.

The pilot's frozen criteria are `tuning/langchain_pilot/ACCEPTANCE.md`.
Major production runtime integration remains unverified until the actual
future-triggered Codex business session and exact acceptance-email readback under
`runtime-acceptance.md`. A manual synthetic run cannot satisfy that gate.

## Setup consistency

Update this runbook and the sanitized setup inventory together, then run:

```sh
python3 shared/setup_audit.py --refresh
python3 shared/setup_audit.py --check
```
