# Runtime boundary review for a minimal LangChain/LangGraph pilot

Review date: 2026-11-15. Scope: maintained public source and runbooks in
`shared/job_runtime/`, `mentor/scheduler/`, and `niulai-runtime/`. This review did
not inspect private state, credentials, holdouts or report payloads; run a provider,
register a job, change configuration or send mail. The only mutation is this report.
The report is inert/local; production runtime and its activation boundary are unchanged.

No actual `MENTOR_INIT_OK` hook output was visible in this review fork. Automatic
initialization is therefore unverified. `mentor/AGENTS.md`, `mentor/ROUTING.md` and
`mentor/skills/development-discipline/SKILL.md` were read directly as the disclosed
fallback. This is an exploratory architecture review, not evidence that a framework
migration fixes an observed production orchestration failure.

## Findings

### 1. Keep the installed scheduler authoritative; a graph belongs inside one claimed attempt

The outer runtime already implements business-significant scheduling semantics:

- `shared/job_runtime/engine.py:633` starts a SQLite immediate transaction for a
  claim; `:640` refuses a new claim while the same job has a running or unknown
  slot; `:642` expires slots outside grace; `:683` publishes running state before
  returning the scheduler-created attempt identity at `:697`.
- `shared/job_runtime/engine.py:860` allocates due slots, and `:870` claims only
  when a worker actually starts. `:892` requires the transport to bound its own
  execution and joins workers; `:895` groups work by resource, and `:901` queues
  jobs sharing a credential cache without consuming an attempt while waiting.
- `shared/job_runtime/engine.py:916` requires proof that the old worker can no
  longer execute before recovery; `:949` retains interrupted work as unknown.

These are useful shared infrastructure, not a second implementation of an agent
reasoning loop. Replacing them with a graph would require rediscovering due-window,
single-writer, restart and unknown-outcome semantics. Keep launchd, service ownership,
slot/attempt identity, allocation, resource serialization and effect replay authority
outside the graph. The responsibility map already makes this separation explicit in
`docs/deployment/job-runtime.md:24`.

The typed provider/retry branch should not be treated as the migration's ready-made
production base merely because its source exists. The acceptance contract labels
provider/retry v2 as disabled/source-live and its provider conformance/runtime
boundaries unverified (`docs/deployment/runtime-acceptance.md:73`). This review did
not inspect active private configuration or establish current activation.

### 2. The smallest existing seam is an injected, bounded model turn—not the mentor state machine

`mentor/scheduler/runner.py:677` already accepts injected `model_call` and `verifier`
functions, a variant ID, cancellation, a clock and a cycle limit. It creates the
identity/journal before invocation (`:646`), holds the logical-session lock (`:691`),
and invokes the model through the injected function (`:699`). Graph nodes can own
prompt assembly, a bounded read-only model/tool sequence and output validation
behind that call. Prompt or tool variants can change there while the same frozen
work order and independent verifier remain outside it.

Keep the runner's journal, retained-output custody, verifier and unknown fence:
`mentor/scheduler/runner.py:623` records/verifies the retained result before closing
the cycle; `:701`, `:732` and `:738` fence uncertain execution/processing; `:740`
allows only one cycle per external Engine attempt. The controller already delegates
judgment to supervision and owns no worker/model/transport capability
(`mentor/scheduler/controller.py:1`). Rewriting that controller as graph nodes has
no demonstrated benefit in this review.

There is an important adapter constraint: `mentor/scheduler/runner.py:361` requires
a genuine `MODEL_TURN_COMPLETED` receipt containing a thread ID, retained response
path/digest, requested/observed model information, no automatic retry and no fallback.
A LangChain message list or LangGraph thread ID is not automatically this receipt.
The installed mentor bridge does not expose `model_call` selection in its public
allocation: it calls `run_cycles` directly with the default transport
(`mentor/scheduler/job_adapter.py:309`, `:340`). Start with an explicitly invoked
local candidate harness; production configuration must not silently choose a new
transport or synthesize success receipts.

### 3. Delivery and unknown outcomes must remain outside agent checkpoint/retry control

Niulai's scheduler module is admission only (`niulai-runtime/niulai_runtime/scheduler.py:1`).
Its pure `admit` function checks owner, real calendar, actual due window, production
authorization and the original logical delivery key (`:41`, `:56`, `:72`, `:82`,
`:92`, `:101`). Admission itself explicitly does not provide cross-process duplicate
protection (`:45`).

That protection lives in distinct owners:

- Business work leases and data-recovery scheduling live in
  `niulai-runtime/niulai_runtime/daily_work.py:105` and `:149`. The work ledger
  stops both branches when a prior send is sending, unknown or accepted without
  verified readback (`:121`).
- Immutable message preparation and atomic prepared-to-sending claims live in
  `niulai-runtime/niulai_runtime/delivery.py:222` and `:235`. There is deliberately
  no reset/retry-unknown operation (`:178`). An uncertain call is retained as
  unknown (`:285`); exact-message digest reconciliation is separate (`:266`).
- The domain prepares a claim only from finalized maintained snapshots
  (`niulai-runtime/niulai_runtime/daily_job.py:175`), commits the outbox claim before
  the prompt is released (`:219`), and independently checks readback, drafts and
  freshness (`:309`). The service verifies source generations/claims and delegates
  commit (`shared/job_runtime/service.py:564`, `:602`, `:624`, `:635`). It rejects
  model-authored success without a host-owned completion verification (`:654`, `:666`).

A graph may produce a draft result/artifact reference for these owners. It should
not own Gmail, reset the outbox, invent a new logical key per retry, or resume a
send node after an ambiguous outcome. Framework persistence cannot substitute for
the exact-effect reconciliation policy. This distinction also preserves the
authorized parallel Codex/ChatGPT operation rather than implying sender cutover
(`docs/deployment/niulai.md:3`, `:18`).

### 4. Most apparent duplication is layered authority; the actual utility duplication is smaller

Engine slots answer “may this scheduled attempt run?”, mentor journals answer
“which cycle/output/evidence was durably committed?”, and Niulai work/outbox state
answers “may this business report/message advance?”. Their identities and terminal
conditions differ. The mentor bridge binds the Engine attempt into the cycle
(`mentor/scheduler/job_adapter.py:340`), and its receipt retains both identities
(`:295`). These stores should not become competing graph checkpoints.

There is concrete small-scale duplication in private-path checks, JSON/hash helpers
and atomic file publication. Compare `niulai-runtime/niulai_runtime/daily_work.py:35`
and `:56` with `mentor/scheduler/runner.py:105` and `:119`, and the shared service's
`shared/job_runtime/service.py:158`. Even these helpers have different contracts:
for example the mentor helper fsyncs the containing directory (`runner.py:127`),
while the daily helper itself does not (`daily_work.py:56`); the domain adds its own
directory fsync around claim publication (`daily_job.py:206`). A framework will not
remove this I/O correctness work. Do not bundle utility consolidation into the
first pilot; any later shared helper needs an exact common contract and its own
failure checks.

### 5. Current evidence supports an isolated experiment, not production adoption

The existing pilot deliberately has synthetic inputs and no account, acquisition,
email, shell or scheduler tools (`docs/deployment/langchain-pilot.md:3`). The parent
review reports a local API and six boundary tests; real provider E2E remains
unverified after timeouts. This review neither reran those checks nor inferred
provider success from source/API availability. Pilot source is being edited
concurrently, so this report does not certify a candidate fingerprint.

Likewise the maintained mentor runbook records a failed installed future-triggered
attempt before a model process/thread, pending result email and no authorized replay
(`docs/deployment/mentor-scheduler.md:3`); its isolated model/failure-campaign evidence
is a different level of proof (`:144`). This review did not independently reopen
the private evidence and makes no current active-runtime claim.

Any later production adoption changes a provider/adapter/runtime path and must
remain disabled until the required staging/rollback checks and explicit activation
decision. Acceptance then requires an actual future-triggered scheduled Codex
business execution of that exact candidate and independently verified email, with
execution and email verdicts separate (`docs/deployment/runtime-acceptance.md:9`,
`:16`, `:29`, `:47`, `:138`). A manual graph run, shell/unit checks, local API,
handshake or reviewer agreement cannot satisfy that gate. This documentation-only
review does not require another business effect (`:13`).

## Minimal adapter sketch

This is a proposed local harness sketch, not implemented/activated code. It
preserves the existing transport result without translating a graph checkpoint into
a provider receipt. A compiled graph can add pure prompt/validation nodes around
the same single transport call; it receives no delivery capability. Compile once
for each explicitly selected prompt variant and invoke it through the runner's
existing `model_call` seam.

```python
from langgraph.graph import END, START, StateGraph
from shared.job_runtime.model import run_codex

def graph_model_call(prompt_variant):
    def turn(state):
        args = state["args"]
        result = run_codex(
            args["profile"], prompt_variant(args["prompt"]),
            args["workspace"], args["run_dir"], context=args["context"],
        )
        return {"transport_result": result}  # Keep genuine failure/unknown/receipt.

    builder = StateGraph(dict)
    builder.add_node("one_read_only_turn", turn)
    builder.add_edge(START, "one_read_only_turn")
    builder.add_edge("one_read_only_turn", END)
    compiled = builder.compile()  # No graph-owned retry, resume or effects.

    def call(profile, prompt, workspace, run_dir, *, context):
        return compiled.invoke({"args": {
            "profile": profile, "prompt": prompt, "workspace": workspace,
            "run_dir": run_dir, "context": context,
        }})["transport_result"]
    return call
```

This tests whether explicit graph composition makes a bounded prompt variant easier
to inspect without changing transport authority. It is not a full LangChain provider
replacement and does not prove a multi-tool agent loop. For that separate change,
first define and verify a real receipt/custody adapter satisfying the existing
runner contract; do not fabricate those fields from graph state. Keep read-only
model failures visible to the runner rather than introducing an inner retry loop.

Recommended first action: use the already isolated pilot to establish one genuine
provider/tool/result path, then compare an unchanged baseline against one explicit
variant. Leave scheduler, mentor state, report construction, business work, outbox,
email and production allocations alone until that bounded experiment establishes
incremental value and its next integration seam is separately authorized.
