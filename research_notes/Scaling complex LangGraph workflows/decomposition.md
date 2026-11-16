# Decomposing complex Trading Agent workflows and durable state

Research date: 2026-11-15. Scope: architecture research only; no implementation, activation, model execution, email, scheduler, hook, MCP, or credential inspection. The existing [migration blueprint](../../docs/plans/langchain-agent-migration.md) describes a proposed composition; this research does not establish that the complete Trading Agent exists. Parent-supplied discovery is saved in `runtime/native-discovery.json`; this worker issued no search queries.

Retrieval: native discovery succeeded according to the coordinator, while native source opening was unavailable. Full official Markdown/HTML was retrieved using direct `curl`, initially requiring sandbox escalation after DNS failures. The coordinator later retrieved the Functional API guide after a worker DNS failure. This is direct-source retrieval, not proof of native-open recovery. Snapshots, SHA-256 hashes, redirect provenance, and installed API inspection are in `runtime/decomposition/`. Version inspection confirmed **LangChain 1.5.0 / LangGraph 1.2.22**; read-only signature/source checks are not runtime tests. Mutable documentation can contain features/examples beyond the inspected API surface.

## 1. Which decomposition fits each kind of complexity?

### Takeaway

Separate business capability, graph scheduling, model autonomy, and deployment. Choose the smallest boundary that solves the actual complexity: ordinary capabilities and explicit nodes for known work, subgraphs for multi-step ownership, agents for model-directed exploration, and a service/job interface only for an independently justified execution boundary.

### Cited Findings

- A subgraph is a graph used as a node of another graph. Official uses include reusable node groups and independent team development behind input/output schemas. These are composition benefits, not a claim that a subgraph is a separately deployed service. [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- Graph nodes do work; edges determine what runs next. A node can be ordinary code, and LangChain `create_agent` already produces a graph. An agent need not be reimplemented as a second handwritten loop around that graph. [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api), [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- Anthropic distinguishes predefined workflow paths from agents that choose their process and tools. Its primary-author guidance favors fixed subtasks for chaining, independent work for parallelization, and dynamically discovered subtasks for orchestrator-workers; agent autonomy trades flexibility against cost and compounding errors. This is architectural guidance, not measured evidence for this Trading Agent. [Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- The LangGraph walkthrough begins by identifying distinct process steps, then their work type and required state; it separates LLM, retrieval, action, and user-input steps. [Thinking in the Graph API](https://docs.langchain.com/oss/python/langgraph/thinking-in-graph-api)
- The Functional API wraps existing code with entrypoints/tasks and ordinary language control flow. Its current guide recommends Graph API for new graphs; Functional API lacks a static graph visualization and has different checkpoint organization. It is a migration option, not a reason to rewrite public capabilities. [Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)

### Inferences

The following are recommendations, not implemented features or demonstrated performance gains.

| Boundary | Meaning / trigger | Trading Agent application | Avoid |
| --- | --- | --- | --- |
| Atomic capability | Independently callable input/output/error/evidence contract owned by one component | Existing calculator, acquisition request/readback, coverage validator, factor result reader; keep ordinary functions where adequate | Calling every validator an agent or requiring a graph to use a public function |
| Node | A unit scheduled by the graph with a useful retry/checkpoint/observation boundary | Invoke a capability, record a receipt reference, classify an allowed outcome, or validate a draft | One huge node that hides every stage; equally, microscopic nodes for every local field assignment |
| Subgraph | A multi-step workflow with its own internal state and public result contract | Research analysis with bounded supplementation; a factor wrapper that orchestrates existing owners; a multi-step holdings flow if actually needed | Recreating acquisition dispatch, factor execution, coverage authority, or evaluation inside the parent |
| Agent | Model chooses the next step/tool within explicit permissions and budget | Explore unknown company questions, propose a bounded research plan, choose among registered evidence tools | Giving deterministic calculation, frozen coverage requirements, or admission decisions to model discretion |
| Deployed service / external job | Separate process/remote executor with explicit request identity, lifecycle, resource, and failure contract | Heavy factor execution or a real shared provider bottleneck, once observed and justified | Assuming `add_node(child_graph)` creates workers, queues, autoscaling, or fault isolation |

Apply the four complexity types deliberately:

1. **Known sequence:** use explicit nodes/edges and programmatic gates. Example proposal: frozen request → acquire evidence → analysis/calculation → independent review → coverage → draft/finalization. This is a configurable candidate sequence, not a mandated final pipeline. Local synchronous functions may suffice before graph-level durability is required.
2. **Dynamic fan-out:** when the input yields N independent companies, source requirements, or experiments, validate/freeze that work list and use `Send` or independent tasks. Cardinality changing at runtime does not itself require an autonomous planner or multiple deployed agents. Provider concurrency, exact-query reuse, rate limits, and retry budgets remain with acquisition/shared infrastructure.
3. **Open-ended planning:** use an agent or planner to discover subtasks, then validate its proposed calls against registered capabilities, immutable requirements, budgets, and allowed outcomes. The graph still decides whether the necessary evidence exists. Add specialized agent contexts only when a concrete role/context conflict justifies them.
4. **Long-running external work:** retain the executor as owner of submit/status/result/reconcile. The graph stores a request/attempt identity and evidence references, yields while waiting if needed, and verifies the returned receipt. Do not hold a conversational model loop open merely to poll an unrelated job.

Preserve workspace responsibilities: research and holdings remain sibling capabilities; acquisition, calculator, coverage, factor engine, factor evaluation/admission, and immutable manifests retain distinct owners. Mentor supervises, Tuning evaluates, investment discovery and entry policy remain separate. Parent orchestration can compose their contracts but cannot become their competing source of truth. [Workspace boundary guidance](../../mentor/skills/development-discipline/SKILL.md), [Migration blueprint](../../docs/plans/langchain-agent-migration.md)

### Gaps

- No workload, latency, throughput, or failure measurements in this research justify another process, queue, service, or an agent-per-stage design. Those choices remain exploratory.
- The existing cooperative session model requires host replies. A graph/checkpointer does not establish unattended inference or a sustainable external model service. The blueprint and pilot runbook explicitly limit the current evidence. [Pilot deployment](../../docs/deployment/langchain-pilot.md)
- Anthropic's article was originally published 2024-12-19 and now warns that the tooling landscape changed. Use its decomposition reasoning, not its current or historical SDK/model examples as version evidence.

## 2. How should state, parent/child handoffs, fan-out, and joins work?

### Takeaway

Make the parent a coordinator that stores identities, expected work, receipt references, and unresolved conditions. Give each child a deliberate state schema and each shared field a defined writer/merge rule; a graph's completion or join is insufficient evidence that the business request succeeded.

### Cited Findings

- With different parent/child schemas, a wrapper maps parent state into child input and maps its output back. Directly adding a compiled child fits deliberately shared state channels. Private child history can stay outside the parent interface. [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- Nodes return partial updates. Reducers operate per state key; without a reducer the value is replaced. Input/output schemas constrain invocation data but do not automatically conceal internal channels from streaming. [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- Installed 1.2.22 `LastValue.update` rejects multiple values in one step with `INVALID_CONCURRENT_GRAPH_UPDATE`; the overview's replacement wording must not be read as a safe concurrent last-writer-wins policy. Installed `StateGraph.add_edge([A,B], C)` explicitly waits for **all** named starts; it records a waiting edge. [Installed channel source](../../.langchain-pilot/.venv/lib/python3.12/site-packages/langgraph/channels/last_value.py), [Installed graph source](../../.langchain-pilot/.venv/lib/python3.12/site-packages/langgraph/graph/state.py)
- `Send(node, arg)` dispatches node instances with custom input, supporting runtime map-reduce. `Command` can combine an update with routing; static edges still run when a node returns dynamic routing. `Command.PARENT` can route to a parent, with a reducer required when updating a shared parent key. [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- Pregel executes selected actors in parallel until all complete, a failure occurs, or timeout; their channel writes are invisible to peers until the next step. Checkpointers retain pending writes from successful nodes when another node fails, allowing those completed nodes to be reused on resume. [Pregel runtime](https://docs.langchain.com/oss/python/langgraph/pregel), [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- Installed runner source attempts to cancel outstanding futures and reraises unhandled failures. That is Python runtime behavior, not cancellation or rollback of an already dispatched remote business operation. [Installed runner](../../.langchain-pilot/.venv/lib/python3.12/site-packages/langgraph/pregel/_runner.py)

### Inferences

Recommended handoff shape, to align with existing contracts rather than create a duplicate schema:

| Parent retains | Child/existing owner retains |
| --- | --- |
| Research/task ID; frozen request version/hash; cutoff/config/budget references | Source text/snapshots, model message history, acquisition dispatch records |
| Child invocation/run/attempt identity; expected branch/item manifest | Internal retries, tool calls, job lifecycle, provider caches/rate limits |
| Outcome plus receipt/artifact reference and hash; unresolved gaps | Factor arrays, generated code/execution environments, detailed evaluation evidence |
| Required/optional policy and final completion conditions | Authoritative coverage/admission/finalization validators and their immutable receipts |

A wrapper should admit/validate the frozen child request, invoke the public owner, validate the resulting identity/hash/provenance, then return the smallest parent update. Re-read authoritative receipts during recovery. Preserve the owner's `unknown`, `withheld`, or partial outcome semantics; do not manufacture a successful result from a missing field.

For shared updates:

- Assign scalar completion and budget fields a single writer. Independent workers should return per-item results, not race to overwrite the parent's status.
- For aggregate results use a map keyed by logical item and attempt, with explicit merge/deduplication/conflict rules. An identical receipt can be a no-op; contradictory payloads for the same immutable key should be an error. Keep historical attempts rather than append an unqualified list of success-looking values.
- Prefer deterministic, associative merges for batching; make order-insensitive collections commutative where feasible. Idempotent merges help application-level rereads/replays but do not imply all reducers must mathematically be idempotent. Sort when deriving presentation order.
- Treat private graph state as interface encapsulation. It is not a credentials boundary, cross-tenant isolation, or automatic redaction for tracing/streaming. Keep sensitive data out of exported state and apply the owning component's controls.

For fan-out and fan-in:

- Freeze an **expected item manifest** before dispatch, including required/optional classification, input/config hashes, and max budget. Give each `Send` its own item identity and narrow child input. Limit concurrency using the appropriate execution/owner controls; `Send` alone supplies no provider backpressure policy.
- Fixed required siblings can use a named all-start join. Separate edges from each predecessor do not encode the same all-predecessor condition when branches have unequal lengths or conditional paths. An all-start join also cannot express an optional branch that was never scheduled: model a terminal skip outcome or route through a manifest-aware coordinator.
- Dynamic dispatch needs business accounting beyond the scheduler barrier. Validate the returned keys against the manifest; reject duplicates/conflicts and preserve missing/failed/withheld items. A retry or nested follow-up must not silently change which original items are required.
- Distinguish **node completed** from **business passed**. Returning a terminal error receipt permits coordination to continue, but the coordinator must enforce required-branch failure. Catch only expected errors; blanket exception handling can hide defects or interrupt control flow. Optional failure should be explicit and reported.
- Do not treat a successful parallel sibling as evidence the whole graph committed. Pending-write recovery can preserve its result while the failing sibling remains unfinished. Do not infer that cancellation undid any external action.

Avoid routing a child directly into unrelated parent siblings unless that coupling is the intended public interface; wrapper result mapping is usually easier to audit for these component boundaries. Avoid mixing static edges and `Command.goto` from the same node without explicitly modeling both branches.

### Gaps

- The fan-out/join claims above combine official documentation with installed source inspection; no new executable join/replay demonstration was performed. Variable-depth dynamic fan-out and optional branch handling need a bounded provider-free experiment before integration claims.
- Source-schema privacy does not prove effective account/tenant isolation. No private state or credentials were inspected to assess that boundary.
- Checkpoints represent execution state; the framework documentation does not make them a substitute for this workspace's immutable evidence contracts or independent domain validators.

## 3. What durability and recovery are needed, especially around external effects?

### Takeaway

Select state lifetime and write durability explicitly. Recovery replays code around persisted results; external effects still require idempotency, owner-controlled reconciliation, and stable identities. An interrupt is a resumable wait, not an unattended worker or an authorization policy by itself.

### Cited Findings

- A child compiled with `checkpointer=None` starts each invocation fresh while inheriting parent checkpointing; `True` retains per-thread state; `False` has no child checkpoints/interrupt recovery. Parent checkpointing is required for inherited persistence. Same per-thread child parallel calls conflict in one namespace; stable named wrappers help distinguish different per-thread children. [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- Checkpointers scope graph state to a thread; stores provide application data across threads. RAM savers lose data at process restart. Reusing a thread is not alone a resume instruction: plain input starts new work on accumulated state; `None` resumes unfinished work; `Command(resume=...)` answers an interrupt; historical checkpoint replay reruns later calls. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)
- Durability modes: `sync` persists before the next step; `async` overlaps writing with the next step and has a crash window; `exit` writes when execution exits normally, with error, or by interrupt, and cannot recover an intermediate process crash. Installed `Pregel` documents `async` as default. [Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers), [Installed Pregel](../../.langchain-pilot/.venv/lib/python3.12/site-packages/langgraph/pregel/main.py)
- Interrupts restart the containing node from its beginning; earlier code runs again. Resume values are matched by call order. Avoid swallowing the control-flow exception, changing interrupt order, or unbounded within-node validation loops. Even effects after approval require idempotency if failure occurs after the effect but before node completion. [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
- Tasks return futures and can run in graph nodes. Functional API resume restarts the entrypoint, restoring completed task/subgraph results. Nondeterministic reads and individual effects belong in separate tasks; an unfinished task may run again and needs an idempotency key or reconciliation. Inputs/outputs must meet serialization requirements. [Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)

### Inferences

Choose child lifetime by business identity:

| Pattern | Proposed use | Constraint |
| --- | --- | --- |
| Per-invocation (`None`) | Independent source queries, one company/attempt, independent review workers | Explicitly supply the needed frozen context; parent must have a suitable checkpointer for recovery |
| Per-thread (`True`) | Deliberate continuing research conversation under one stable identity | Serialize same-child access; isolate named namespaces; distinguish new work from resume |
| Stateless (`False`) | Cheap pure derivation or validation whose full rerun is safe | Accept lost internal progress and no child interrupt support |
| Cross-thread store / existing evidence repository | Shared durable facts or immutable results | Preserve owner/version/access rules; do not silently turn prior conversations into current evidence |

For the Trading Agent parent, prefer compact durable coordination state and default per-invocation workers. Make per-thread memory an explicit opt-in for genuine continuation; never accidentally carry company A's private message history or an old attempt into company B. Persist the semantic request ID separately from LangGraph thread/run IDs, and preserve the mapping rather than replacing existing execution identities.

For consequential coordination, explicitly choose `sync` with a verified persistent backend when losing the current committed step would be harmful. For reconstructible read-only drafts, `async` may be a reasonable measured tradeoff. Reserve `exit` for workflows whose entire intervening work can safely be repeated and whose lost progress is acceptable. These are recommended policies, not existing active configuration. `sync` protects the checkpoint-write boundary; it does not make a remote write atomic with that checkpoint.

Distinguish four recovery operations in operator/UI language:

1. **New input on existing thread:** reducer-merge with retained state; do not assume reset.
2. **Resume latest unfinished work:** preserve the frozen request/config, use saved successful work, retry only permitted unfinished work.
3. **Answer an interrupt:** validate a reply against the pending request/approval identity; the containing node restarts.
4. **Replay/fork historical state:** a fresh experiment/effect risk because post-checkpoint LLM/API work can execute again; keep production effects fenced.

For a future external executor/effect adapter, the safe shape is:

1. Freeze a logical request/effect key, immutable payload hash, candidate/config identity, and owner before dispatch. Read them from persisted state on recovery rather than generate a new key for every retry.
2. Put nondeterministic planning inputs and each submission/write in an appropriate task or separate node. Saved completed task results avoid unnecessary work; do not interpret task decoration as exactly-once delivery.
3. Let the existing owner record submitted/accepted/unknown/terminal state and retain the authoritative provider/job identity. If the process dies after provider acceptance but before result persistence, reconcile by that identity/key before replay.
4. Wait/interrupt or later status-read without redispatch. Keep resume/callback correlation explicit and validate returned receipt/input hash before advancing. A graph wait requires a real actor to resume it; it supplies neither an external scheduler nor a continuously callable model.
5. Keep approval, credentials, unknown-delivery fences, archive rules, and business acceptance with the owning component. A syntactically valid `Command(resume=...)` is not proof of authorization. Preserve diagnostic/recovery access when a risky effect is denied.

If multiple statements occur before an interrupt inside one wrapper, assume the wrapper itself can restart; split expensive/nondeterministic/effectful work into persisted tasks or separately completed nodes. Stable task/interrupt control flow matters while unfinished threads exist. Pin candidate graph/prompt/tool/config identities and plan checkpoint migration rather than casually reorder live workflow code.

### Gaps

- No process-crash, persistent-backend, delayed callback, unknown external outcome, or future-triggered runtime test was executed. Documentation and installed source prove API availability/intent, not pilot recovery in those failure windows.
- Installed `task` source explicitly limits cancellable task timeouts to async tasks; a synchronous in-process function cannot be safely cancelled. Read-only source inspection does not prove remote-job termination. [Installed task source](../../.langchain-pilot/.venv/lib/python3.12/site-packages/langgraph/func/__init__.py)
- Later implementation should first demonstrate one inert capability/wrapper path with matching direct-call receipts, then one required failure, optional withheld result, restart/reconciliation boundary, and no external effects. These are proposed validation points; grading/evaluation design belongs to its separate owner.
- Production acceptance remains a separate future-triggered native Codex business run plus independently verified postconditions and acceptance-email receipt. This research authorizes or performs neither deployment nor email. [Runtime acceptance contract](../../docs/deployment/runtime-acceptance.md)

#### Source and version provenance

Primary sources were read in full or by relevant sections from saved full bodies. No source quotations are required for the conclusions. The eight main technical/architectural sources are Subgraphs, Graph API, Pregel, Checkpointers, Interrupts, Functional API, Thinking in the Graph API, and Anthropic's article; Persistence is a short auxiliary overview.

| Requested source | Verified final retrieval / local body |
| --- | --- |
| `docs.langchain.com/oss/python/langgraph/use-subgraphs` | HTTP 200 Markdown; `runtime/decomposition/use-subgraphs.md` |
| `.../durable-execution` | Redirected to `.../persistence.md`; `durable-execution.md` is the persistence body, not the former durable-execution guide |
| `.../persistence` | HTTP 200 Markdown; `persistence.md` |
| `.../graph-api` | HTTP 200 Markdown; `graph-api.md` |
| `.../thinking-in-langgraph` | Redirected to `.../thinking-in-graph-api.md`; saved under requested name |
| `.../pregel` | HTTP 200 Markdown; `pregel.md` |
| `.../checkpointers` | HTTP 200 Markdown; `checkpointers.md` |
| `.../interrupts` | HTTP 200 Markdown; `interrupts.md` |
| `.../functional-api` | Coordinator direct retrieval succeeded; `functional-api.md`; worker subsequently inspected full body |
| `anthropic.com/engineering/building-effective-agents` | Redirected to `anthropic.com/research/building-effective-agents`; HTTP 200 HTML; `anthropic.html` and derived article text |

[`installed-version-review.json`](runtime/decomposition/installed-version-review.json) records installed versions/signatures/source paths. Avoid copying mutable documentation's model strings, event-stream v3 examples, or beta channels into a 1.2.22 implementation without checking their exact installed contracts. No new dependency or service is proposed merely to follow those examples.
