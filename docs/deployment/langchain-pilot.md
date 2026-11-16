# Isolated LangChain and LangGraph pilot

This additive experiment lives in `tuning/langchain_pilot/`. It tests a fixed
validation workflow around a small `create_agent` harness. Its only tool wraps
the unchanged Decimal calculator in
`shared/calculation/legacy/valuation/valuation_core.py`. All inputs are synthetic.
It has no trading, account, source-acquisition, email, shell or scheduler tools.
It does not activate a production integration or replace existing services.
The separate atomic capability lab below adds fixed public calculator and pure
synthetic holdings entry points without replacing this original pilot.

## Dependencies and paths

- Explicit host prerequisite: uv (tested 0.13.7) and Python 3.12 (tested 3.12.16).
- The tested environment reuses the workspace-owned Python interpreter already
  below `.job-runtime/python/`, without installing into that environment.
- New environment: `.langchain-pilot/.venv/`.
- Cache/build/temp: `.langchain-pilot/cache/` and `.langchain-pilot/tmp/`.
- Dev persistence and private receipts: `.langchain-pilot/runtime/`.
- Direct pins: LangChain 1.5.0, LangGraph 1.2.22, langchain-openai 1.8.0,
  langgraph-cli[inmem] 0.4.43, python-dotenv 1.2.4, LangSmith SDK 0.14.17.
  The SDK was already in the resolved hash lock; declaring it directly adds no
  package installation. The lock includes Agent Server 0.18.0.
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

## Opt-in LangSmith prerequisite canary

The separate `observability` CLI traces one **public synthetic atomic calculator**.
It does not enable tracing on the running Agent Server, invoke a model provider,
read holdings, upload private fixtures, deploy the agent or change scheduling.
The default `serve` launcher still forces cloud tracing off. Its native session
model spans and broader Trading Agent instrumentation remain unverified.

LangSmith SDK 0.14.17 is explicitly pinned and already present in the hash lock.
Use an account/workspace key with the permissions needed for the requested Agent,
private prompt, dataset and experiment operations. The client uses the explicit
US API endpoint `https://api.smith.langchain.com`; another region is untested.
It does not inherit an endpoint override from the private credential file.

The key is read only from ignored `.langchain-pilot/langsmith.env`: a regular,
owner-owned, no-symlink file with exact mode 0600 and at most 16 KiB. Its only
field is `LANGSMITH_API_KEY`. The nonsecret template is
`tuning/langchain_pilot/langsmith.env.example`. Preserve an existing private file;
edit the value locally after setting its permissions. Never put the value in
source, arguments, reports or chat. It is separate from a model-provider key.
No OpenAI/Ferry key is needed for this deterministic capability and code grader.

Register or reuse an EXTERNAL Agent with identifier `trading-agent` through the
LangSmith **Connect an existing agent** flow. Registration is a platform record,
not a deployment. The CLI retrieves and checks that identity, then uses its local
environment. Cloud identities, prompt commit, dataset timestamp and receipts stay
in ignored `.langchain-pilot/runtime/langsmith-bootstrap/`, not this runbook.

From the workspace root:

```sh
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.observability bootstrap
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.observability trace
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.observability evaluate
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.verify_observability
```

Only the CLI's explicit allowlisted tracing context is enabled. Bootstrap creates
one private prompt version and three public synthetic examples (nominal, debt,
invalid shares), then rereads their exact contents and pins the dataset `as_of`.
The CLI accepts no arbitrary case input. The runnable's internal fixture check
rejects drift before tools, but LangChain callbacks may record inputs before its
body executes. It is not a pre-trace privacy filter for future private callers.
The canary emits genuine LangChain prompt, validation and calculator-tool spans,
plus a deliberate failure. Evaluation uses a local deterministic code grader;
it is not an online or LLM evaluator and makes no model-call claim. The prompt is
loaded at its recorded commit; the calculator itself does not call a model.

Unknown writes are not silently replayed. If bootstrap stopped after cloud objects
were created, `observability reconcile-bootstrap` only rereads them and completes
the local manifest after exact validation. It cannot recreate missing objects.
If a trace is not immediately readable, retain its `trace-attempt-*.json` receipt
and use `observability reconcile-trace --attempt <owned-filename>`; this reads
those exact run IDs and never reruns the capability. The SDK can acknowledge
writes before query visibility. On rate limits, pause reads and honor the service
window instead of creating more target runs.

The independent readback checks experiment run/example bindings, outputs and
persisted feedback, the positive and controlled-failure traces, project counts,
and absence of the credential in the retrieved payloads. Readiness is scoped to
this atomic path. All deliberate trials remain in the test project; their error
rate is a controlled-test statistic, not real Trading Agent reliability.

Current proof and failures are retained privately. Independent cloud readback
confirmed three run/example/output bindings and three persisted passing feedback
records, the exact positive/tool and controlled-failure spans, and matching
monitoring counters. It also checked the retrieved payloads for the credential.
The test project contains four roots and two deliberate failures across the
retained trace trials. The overall migration gate stays unverified until the
applicable atomic capabilities and model-session tracing are exercised. Managed
online/LLM evaluators and actual holdings were not activated. Legacy SDK read helpers currently emit a deprecation
notice for removal after 2027-01-31; changing those pinned interfaces is a separate
source/runtime check, not a reason to replace the environment globally.

## Atomic capability lab — staged candidate

The atomic lab uses the same locked environment and the separate
[`atomic-langgraph.json`](../../tuning/langchain_pilot/atomic-langgraph.json).
Its [frozen acceptance contract](../../tuning/langchain_pilot/ATOMIC_ACCEPTANCE.md),
[independent semantic cases](../../tuning/langchain_pilot/tests/atomic_contract_cases.json)
and [independent verification report](../../tuning/langchain_pilot/VERIFICATION.md)
define the scoped gate. The final recorded candidate has 339 local tests with zero
skips, failures or errors, including 80 independent checks and all sixty
HOLD cases. The 196 designed cases are not a count of automatically executed
tests. Later source/configuration changes need applicable new evidence.

| Registered graph ID | Capability | Execution boundary |
| --- | --- | --- |
| `calculator` | Deterministic existing Decimal calculator through an actual LangChain tool | Tool-only; no model inference |
| `trading_pilot` | Existing calculator agent with real cooperative `SessionChatModel` | Host supplies assistant messages; actual tool executes in LangChain; persisted logical cap of three model requests |
| `holdings` | Pure `investment/portfolio` snapshot adapter and maintained holdings analytics | Synthetic receipts only; actual `portfolio_analysis_tool`; no acquisition, credentials or model inference |

The cooperative graph admits public tool-only replies with no prose, or a final
numeric JSON answer containing only `per_share` and `synthetic: true`. The final
receipt/schema and exact arithmetic gate still apply. Declared host/model labels
are not authenticated backend identity. There is no unattended dispatcher or
provider fallback in this lab.

In Studio **View Raw**, use the outer public envelope:

```json
{"request":{"case_id":"nominal"}}
```

In Studio's **Request** field, use only `{"case_id":"nominal"}`. Each graph's
schema publishes its exact fixed selector enum; arbitrary valuation/account
objects, paths, URLs, extra fields and unknown selectors are rejected before
exporting child callbacks. Calculator `nominal` expects per-share `10`, historical
`debt` expects `15`, and the independent `public-calc-debt` expects `7` from its
different declared inputs. `invalid-shares` is an expected invalid-input result.
Do not substitute similarly named fixtures or edit failed expected outputs.

The holdings roster has 26 fixed selectors, including the six independent public
HOLD aliases. It distinguishes confirmed requested-scope empty from failed,
partial and unknown reads, and preserves account/currency/type scope. Partial
type retrieval rejects with explicit missing-type gaps. Monetary strings remain
exact; the public projection rounds rate/percentage metrics to twelve decimal
places with ROUND_HALF_EVEN. Query age and optional caller-supplied quote cutoff
are separate. Missing quote time and daily PnL remain unknown; matching account
labels and hashes do not prove authentication, a live read or lease release.

The port-2026 staging process is stopped. The separately verified self-test endpoint is
`http://127.0.0.1:2025`; the original port-2024 process/configuration and the
datasource app on 7270 are preserved. The intended Studio URL is
`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2025`.
Actual ownership/discovery/schema/run/state for that endpoint passed. Browser
connection stability remains unverified; a printed URL or API health is not
browser evidence. Use Graph mode, select `calculator`, `holdings` or
`trading_pilot`, then select and activate its assistant in Settings / Manage
Assistants. Do not use the original port2024 to find the separate atomic roster.
Exact `/assistants/<resolved-id>/graph?xray=true` readback confirmed holdings
`snapshot_admission -> portfolio_analysis` and the cooperative calculator's
validation/model/tools subgraphs. Deterministic calculator uses an actual tool
runnable and has no model subgraph. Chrome Local Network Access permission can
prevent Studio from connecting even when the local API works; see
[official connection guidance](https://docs.langchain.com/langsmith/troubleshooting-studio).

Launch the owned local candidate from the workspace root after selecting and
checking its explicit port:

```sh
LANGCHAIN_PILOT_ENGINE=session PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.serve \
    --atomic --port 2025 --allow-blocking
```

Atomic launch uses `strict_cli.py`, which checks locked Agent Server 0.18.0 and
refuses automatic port fallback even if a bind race occurs after the initial
probe. One worker, no hot reload/browser, local CLI analytics disabled, and local
cache/temp confinement apply. `--allow-blocking` is the development compatibility
flag; it is not a production acceptance waiver. The lab's dev persistence is
`.langchain-pilot/runtime/atomic-server/`, separate from the original
`.langchain-pilot/runtime/server/`. Cooperative binding history and per-request
receipts retain the existing session-engine owner and must not be deleted to
clear a failure.
Start atomic runs through Studio's fixed selector or the matching public API
envelope. For host servicing, pass the chosen lab endpoint explicitly to
`session_engine --url http://127.0.0.1:2025 pending` and `respond`, together with
the exact thread/request/binding identities described above. The CLI defaults
to the original port 2024; its raw `start --case-file` input belongs to the
original graph and is not the atomic fixed-selector ingress.

Cloud tracing remains off globally, including on the original server. Only an
explicit `--atomic --cloud-tracing` launch attaches exporting callbacks to the
already admitted fixed synthetic capability child. It requires a verified local
profile for the selected kind. The existing owner-private LangSmith credential
contract above applies; no credential, real holdings or provider API input is
needed for the deterministic calculator/holdings capability itself.

The separate `atomic_cloud` CLI supports kinds `calculator`, `calculator_session`
and `holdings`. Profiles, pinned prompt commit, dataset version/as-of, exact cloud
identities, evaluation claims and trace attempts stay under
`.langchain-pilot/runtime/atomic/<source-fingerprint-prefix16>/<kind>/`.
Changing the source closure selects a new candidate directory; do not copy an old
profile into it or alter receipts to bypass source/roster drift checks.

The following are bounded synthetic entry points. Retain exact candidate-owned
receipts; do not repeat bootstrap/evaluation to obtain cleaner evidence:

```sh
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.atomic_cloud \
    bootstrap --kind calculator
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.atomic_cloud \
    bootstrap --kind holdings
LANGSMITH_TRACING=false PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.atomic_cloud \
    bootstrap --kind calculator_session
LANGCHAIN_PILOT_ENGINE=session PYTHONDONTWRITEBYTECODE=1 \
  .langchain-pilot/.venv/bin/python -B -m tuning.langchain_pilot.serve \
    --atomic --cloud-tracing --port 2025 --allow-blocking
```

Use `evaluate --kind calculator` or `evaluate --kind holdings` once per owned
candidate trial, then `check-evaluation --kind <kind>` for exact stored
run/example/output and `atomic_contract_correct` feedback readback. The CLI
deliberately refuses unattended `evaluate --kind calculator_session`; cooperative
evaluation requires the owner/host to service model interrupts. No automatic host
service or successful cooperative cloud evaluation is claimed here.

Unknown bootstrap writes are fenced. Use `reconcile-bootstrap --kind <kind>` to
read the saved exact IDs/content; it never recreates missing objects. Native
callback copies share the exact attempt delivery-error and span-ID ledger.
Unknown trace export blocks another invocation/resume on the same thread until
`check-trace --kind <kind> --attempt <owned-UUID>.json` performs exact readback.
The attempt argument is an owned filename under that candidate/kind's `traces/`,
not an arbitrary filesystem path. Readback verifies the actual root/children,
parents, outcome and local result; it does not rerun the capability. Preserve
unknown evaluation claims and use `check-evaluation` to reconcile stored outcomes
instead of repeating an uncertain write. Honor service read windows/429 delays.

Cloud pacing and read retries are configured in
`tuning/langchain_pilot/cloud-read-policy.json`. Defaults are a 0.5-second read
interval, 15 seconds between read-only query requests, 0.05 seconds between
writes, at most three read attempts and a 180-second total wait budget. These
are conservative pilot settings, not a statement of the account's quota.
Warmup performs a delayed read-only `/info` request before the owned operation.
The project-local `rate_policy.py` records warmup, pacing waits, dispatch,
acknowledgement, 429, scheduled retry and exhaustion under private
`.langchain-pilot/runtime/cloud-rate/attempts/`. Records contain endpoint shapes,
attempt numbers, delays and resolved policy, never bodies, keys or headers.
Numeric and HTTP-date `Retry-After` values take precedence over bounded fallback
backoff. A delay exceeding the remaining budget stops the read. Write requests
execute once; unknown writes retain their owning bootstrap/trace/evaluation
fence. Read and query clocks are distinct, so a write cannot reset query pacing.
Changing policy changes the candidate fingerprint; use a controlled restart and
new owned candidate profile rather than copying old receipts.

The 2026-11-16 live trial observed `/runs/query` throttling. Exact-ID GET reads
can reconcile immutable roots and their actual `child_run_ids` without that
query route; verify the returned set and actual parents before reconstructing
the tree. This is readback, never re-execution. LangSmith supplies the public
default `dataset_split: ["base"]`; admission permits that exact value or absence
and rejects other split metadata before evaluation/export.

On candidate7459ededd5d206d3, all nine owned native trace readbacks passed,
including cooperative model/tool segments and a controlled holdings failure.
Calculator cloud evaluation is verified7/7 after read-only reconciliation of
delayed ingestion; it was not rerun. Holding26-case evaluation is verified26/26
after a preserved first unknown and read-only reconciliation; it was not rerun.
Historical three-case calculator cloud proof above
belongs to its earlier canary and does not certify these new resources. Local conformance
does not establish URL readiness, live account/quote freshness, autonomous model
dispatch or production durability. No real holdings, provider API dispatch,
trading/order, email or scheduler effect is authorized by the lab. Major-runtime
acceptance remains unverified under [runtime-acceptance.md](runtime-acceptance.md).

The new isolated client performs the same calculator/holdings operations over
the server's existing `/mcp` endpoint and reads exact traces over hosted
LangSmith Remote MCP. The cooperative inspection agent, rate/resource controls,
private snapshot and setup are documented in [LangChain MCP](langchain-mcp.md).
Native-host MCP registration stays disabled; no provider inference, real holdings
retrieval or scheduled business acceptance is implied by that isolated proof.

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
