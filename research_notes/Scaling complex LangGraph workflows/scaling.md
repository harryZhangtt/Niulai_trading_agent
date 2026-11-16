# Independent scaling and execution boundaries for complex LangGraph workflows

## What is independently replaceable, and what is independently deployable?

### Takeaway

A subgraph provides a logical composition boundary. Separate OS workers provide resource and process boundaries; a graph on a separate Agent Server deployment provides a network and deployment boundary. Choose these separately: independent testing, versioning, or replacement can be achieved before adding a service.

### Cited Findings

- Agent Server supports a default single-host mode, a split API/queue mode in which request serving and run execution scale separately, and a distributed runtime that separates orchestration from execution. Its run lifecycle leases work and permits at most one executing run per thread. This describes Agent Server infrastructure, not an automatic property of an OSS subgraph. — [Agent Server, runtime architecture](https://docs.langchain.com/langsmith/agent-server#runtime-architecture)
- `RemoteGraph` calls a deployed graph with a compiled-graph-style interface and can be embedded as a node/subgraph. The official guide warns against calling itself or another graph on the same deployment because of deadlock and resource exhaustion; it recommends local composition there. — [RemoteGraph guide](https://docs.langchain.com/langsmith/use-remote-graph)
- The deployment overview distinguishes the production agent runtime from the LangSmith observability/evaluation platform. Hosting choices use the same Agent Server runtime; installing LangGraph alone does not establish a deployed runtime. — [LangSmith Agent Server overview](https://docs.langchain.com/langsmith/deployment)

Source verification and route, retrieved 2026-11-15:

| Source | Verified response/title and saved evidence | Short source excerpt |
|---|---|---|
| [Scaling](https://docs.langchain.com/langsmith/agent-server-scale) | HTTP 200; “Configure Agent Server for scale”; `runtime/scaling-sources/agent-server-scale.html`, extracted `.txt`, headers | “Request vs. run concurrency” |
| [Runtime](https://docs.langchain.com/langsmith/agent-server#runtime-architecture) | HTTP 200 for official `.md` representation; heading “Agent Server”; `runtime/scaling-sources/agent-server.source`, headers | “Each tier scales independently” |
| [Remote graph](https://docs.langchain.com/langsmith/use-remote-graph) | HTTP 200 for official `.md`; heading “How to interact with a deployment using RemoteGraph”; `.source`, headers | “Avoid calling the same deployment” |
| [Multitasking](https://docs.langchain.com/langsmith/double-texting) | HTTP 200; “Double texting”; `.html`, extracted `.txt`, headers | “Enqueue (default)” |
| [Enqueue](https://docs.langchain.com/langsmith/enqueue-concurrent) | HTTP 200 for official `.md`; heading “Enqueue concurrent”; `.source`, headers | `multitask_strategy="enqueue"` |
| [Runnable configuration](https://reference.langchain.com/python/langchain-core/runnables/config/RunnableConfig) | HTTP 200; Markdown heading “RunnableConfig”; `.source`, headers. Original underscore URL redirected to `langchain-core`. | `max_concurrency: int | None` |
| [Logging](https://docs.langchain.com/langsmith/configurable-logs) | HTTP 200; “Include HTTP headers in server logs”; `.html`, extracted `.txt`, headers | “exclusions take precedence over inclusions” |

The coordinator supplied `runtime/native-discovery.json`: native discovery succeeded, but native opening was reported unavailable (“only search_query works”). This worker made no search-query calls and did not retry native opening. Sources were retrieved directly with curl, not through native search: the first sandbox fetch failed DNS (exit 6); the required escalated retry returned HTTP 200. Later successful direct reads used that approved route. This does not prove native opening recovered. Exact `/langsmith/deployment-architecture` and `/langsmith/enqueue` returned 404; official links in the retrieved scaling and double-texting pages led to `/langsmith/agent-server#runtime-architecture` and `/langsmith/enqueue-concurrent`. `/langsmith/deployment-options` timed out after its bounded fetch and supplies no evidence. `/langsmith/self-hosted` returned HTTP 200 titled “Self-hosted LangSmith”; it concerns platform hosting and is not used to infer agent-worker scaling. No browser fallback or account access was used.

### Inferences

The following is an architecture recommendation, not an implementation claim. It combines the verified runtime distinctions above with the coordinator-supplied workspace constraints.

| Boundary | What it buys | What it does not establish | Trading Agent application |
|---|---|---|---|
| Module or local subgraph with explicit contracts | Independent unit/contract tests; replacement of one implementation; versioned input/output/error schemas; separate ownership | Separate process, memory, CPU/GPU capacity, or deployed release lifecycle | Keep research and holdings as siblings. Keep RD-Agent proposal/coding, Qlib execution, tuning/admission, immutable run state and UI projection distinct. |
| Isolated OS worker/external factor job behind an existing adapter | Separate process lifetime and resource budget; bounded job concurrency; crash/timeout containment; specialized dependencies | Independently managed service, remote graph persistence, or automatic exactly-once effects | Qlib/backtest execution can remain an ordinary job behind its public contract; it need not become an LLM graph or a network service. |
| Separate Agent Server deployment, optionally called through `RemoteGraph` | Independent deployed resources, release/rollback cadence and failure domain when each is explicitly operated | Global provider quota isolation, cross-service atomicity, or a guarantee that parent and child share lifecycle/state | Consider a separate research or factor orchestrator only after its measured load or required isolation cannot be met by the preceding boundaries. |

Use the existing shared web/model/tool adapters rather than copying their internals into each graph. An independently versioned contract is compatible with a single deployment; an independently deployed graph additionally needs operational ownership, admission, authentication, telemetry, state/recovery policy, and release acceptance. Remote graph composition is an available mechanism, not a reason by itself to introduce a service. — Basis: [Runtime architecture](https://docs.langchain.com/langsmith/agent-server#runtime-architecture), [RemoteGraph guide](https://docs.langchain.com/langsmith/use-remote-graph).

### Gaps

- The workspace facts below were supplied by the coordinator and were not established through credential or runtime inspection: LangChain 1.5.0 and LangGraph 1.2.22 are installed; no complete workflow is implemented; pipeline design remains TBD; the model-session engine relies on cooperative manual host replies. Keep them labelled as supplied current state. The live docs may describe Agent Server features newer than any locally admitted server/SDK; package installation is not server capability acceptance.
- No workload measurements, deployment entitlement, independently scaled graph, unattended model-provider admission, or runtime acceptance were verified here. This research cannot certify present production capacity.

## How should concurrency and scale-out be chosen?

### Takeaway

Concurrency is the number of in-flight operations; throughput is completed work per unit time. Start with bounded concurrency and identify the limiting resource. Extra processes help different bottlenecks from extra asynchronous I/O, and neither creates provider quota.

### Cited Findings

- Agent Server separates request concurrency from run concurrency. API replicas serve requests; run slots are queue-worker count multiplied by `N_JOBS_PER_WORKER`. Additional runs wait when slots are occupied. Its sizing approximation divides available slots by average run execution time to estimate steady-state completed runs per second. — [Scaling guide](https://docs.langchain.com/langsmith/agent-server-scale)
- The guide recommends concurrency according to CPU, memory or I/O constraints, warns that greedy workers with too many slots can worsen burst utilization and latency, and warns against blocking the event loop. It distinguishes API, worker, PostgreSQL and Redis load. These are workload-dependent guidance, not universal capacity guarantees. — [Scaling guide](https://docs.langchain.com/langsmith/agent-server-scale)
- `RunnableConfig` exposes a `max_concurrency` field. The remote guide lists the config sent across the deployment boundary: `recursion_limit`, `tags`, `metadata`, and `configurable`; `max_concurrency` is not among them. A local setting therefore must not be represented as a remote capacity limit. — [RunnableConfig API](https://reference.langchain.com/python/langchain-core/runnables/config/RunnableConfig), [RemoteGraph guide](https://docs.langchain.com/langsmith/use-remote-graph)

### Inferences

Proposed staged ladder; every next stage requires an observed bottleneck or a concrete isolation requirement. These are proposed measurements and decision rules, not claims of measured results.

| Stage | Bounded action | Evidence to collect | Signal to move beyond it |
|---|---|---|---|
| 1. Single process and bounded concurrency | Compose local graph/module contracts. Bound graph fan-out, concurrent runs and each provider/tool adapter separately. Use asynchronous I/O where supported. | Arrival and completion rates; queue depth and oldest-item age; submit-to-start time; p50/p95 completion time; step duration; CPU/RSS; event-loop lag; provider requests/tokens and rate-limit responses; cost per completed result | Under a representative sustained load and burst, completion rate stops tracking arrivals or a declared latency/freshness objective is missed. Trace attribution must show which resource is limiting. If the bottleneck is provider quota, constrain admission or obtain capacity instead of adding workers. |
| 2. Isolated workers | Move the identified blocking/resource-intensive operation behind the same adapter into a bounded process/job pool. Budget CPU, memory, disk and GPU separately; retain existing graph contracts. | Sibling research/holdings latency with and without factor jobs; worker CPU/RSS and failures; Qlib job queue age; GPU allocation/utilization where used; cancellation and cleanup outcomes; artifact transfer/checkpoint size | Factor jobs measurably degrade siblings, require incompatible dependencies or resource profiles, or cannot meet job-age objectives with local capacity. Verify worker isolation improves the bottleneck without increasing duplicate work or recovery ambiguity. |
| 3. Separate service/deployed graph | Separate only the affected execution owner; independently size API/worker capacity if using Agent Server. Keep remote calls through the adapter. | Per-service queue age/arrival/completion rates, resource saturation, API latency, persistence load, provider quota utilization, cross-boundary failures, release/rollback and recovery evidence | A bounded worker arrangement cannot meet the declared demand/isolation requirement, or the component has a demonstrated independent release/security/runtime ownership requirement. Compare the improvement with network, state, deployment and maintenance costs. |

For I/O-heavy research/model requests, asynchronous concurrency may overlap waiting, provided a real unattended provider exists. For CPU-heavy factor coding/execution or CPU/GPU backtests, adding asynchronous tasks can increase contention; process/job isolation is the more plausible experiment. A thread offload can protect an event loop from blocking I/O, but it is not evidence of CPU speedup or GPU isolation. — Basis: [Scaling guide](https://docs.langchain.com/langsmith/agent-server-scale), [Runtime architecture](https://docs.langchain.com/langsmith/agent-server#runtime-architecture).

Bound fan-out at every owner, including spawned child jobs and provider retries. Configure admission limits and finite queue/storage policy, with explicit rejection or deferral when capacity is exhausted. Maintain global/provider-specific request and token budgets across workers; distinguish a concurrency cap from requests-per-time or tokens-per-time limits. Monitor queue age and run duration together: a single concurrency number cannot distinguish slow upstream calls, CPU saturation, database writes or a serialized thread. These are application/backpressure recommendations, not a claim that `max_concurrency` automatically enforces all of them.

Use the guide's throughput equation only as a first sizing estimate. Validate against the measured duration distribution, bursts, heterogeneous jobs, per-thread ordering, and shared dependencies. Define project latency, freshness, resource and cost objectives before load testing; do not adopt the documentation's example traffic rates as Trading Agent thresholds. No numeric separation threshold is supported by the present evidence.

The cooperative manual model-session engine is the first relevant current constraint. A queue can represent pending work and factor jobs can be independently tested, but this architecture cannot honestly claim automated model batch execution or worker throughput until an unattended model provider is admitted and exercised. More graph workers cannot manufacture independent host replies.

### Gaps

- No official source inspected here establishes this workspace's provider request/token quotas, Qlib/GPU profile, load distribution or cost objectives. Those require admitted-provider documentation and local measurement.
- `RunnableConfig`'s retrieved API page exposes the field but does not prove every arbitrary coroutine/tool obeys it. Verify the selected graph/batch implementation and explicit adapter limits in a bounded experiment; do not assume a global scheduler.

## How should same-thread work, long-running jobs and uncertain outcomes be handled?

### Takeaway

Use thread identity for ordered stateful work and job identity for independently managed long operations. Graph cancellation, state rollback and transport timeouts do not by themselves establish that an external effect never happened.

### Cited Findings

- Double-texting is an Agent Server feature absent from the OSS framework. Default `enqueue` waits for the current run before subsequent input. `reject` refuses additional work while running; `interrupt` keeps progress and applies new input; `rollback` reverts graph progress and starts with the new input. The guide calls out incomplete tool calls when interrupting. — [Double texting](https://docs.langchain.com/langsmith/double-texting)
- The enqueue example creates two runs on one thread, supplies `multitask_strategy="enqueue"`, waits using the second run's `run_id`, and then reads thread state. — [Enqueue concurrent](https://docs.langchain.com/langsmith/enqueue-concurrent)
- The scaling guide recommends joining or streaming a run rather than repeatedly polling state. — [Scaling guide](https://docs.langchain.com/langsmith/agent-server-scale)
- Server headers are omitted from logs by default. Correlation-header logging is opt-in and supports explicit include/exclude rules, with exclusions winning. — [Configurable logging](https://docs.langchain.com/langsmith/configurable-logs)

### Inferences

- Per-thread serialization limits useful same-thread concurrency even when more workers exist. Use distinct job/run threads only for work that is semantically independent; do not shard a stateful portfolio decision merely to evade ordering. Choose `enqueue` for preserve-and-order, `reject` for a clear busy contract, and interruption/rollback only when the owning tool and side-effect contracts support safe recovery. — Basis: [Runtime lifecycle](https://docs.langchain.com/langsmith/agent-server#run-execution-lifecycle), [Double texting](https://docs.langchain.com/langsmith/double-texting).
- For a long Qlib/backtest or separately deployed run, the parent should persist a handle and references: job/request ID, immutable input/config/version fingerprint, status, timestamps, result/artifact references, and sanitized error/unknown state. Submit, await/join or bounded status checks, retrieve, cancel/reconcile and admission are separate adapter operations. Persist a returned server run ID rather than assuming the parent owns it. — Basis: [Enqueue run handles](https://docs.langchain.com/langsmith/enqueue-concurrent), [RemoteGraph config/run identity](https://docs.langchain.com/langsmith/use-remote-graph).
- Store immutable factor data, code, backtest outputs and evidence outside the parent graph payload. Pass artifact IDs/paths and hashes through public schemas; let tuning/admission retrieve and validate the referenced artifacts. This controls checkpoint/transfer cost and preserves factor-engine ownership. Synthetic/source-discovery success remains distinct from factor-quality evidence. This is the workspace's proposed contract design, not an Agent Server feature claim.
- Bound connect/read/model/tool/job deadlines independently, plus a total request budget. Bound retry count/time and attempt fan-out; retry transient errors only under the owning contract. If submission or an external write times out after it may have been accepted, record an unknown outcome, retain identity, and reconcile before replay. Use an idempotency key only when the provider actually supports the required guarantee; retain the local delivery/effect fence otherwise. Interruption, checkpoint recovery, or rollback must not be described as undoing an already executed external effect. This is failure-containment guidance; the retrieved docs do not establish exactly-once external semantics.
- Record request, parent run, child job and artifact correlation IDs with component/provider timing and error class. Opt into safe correlation headers if a deployed server is later chosen; exclude credentials and private account data. Request tracing should permit attributing an apparent graph bottleneck to provider waiting, CPU/GPU work, queue admission or persistence. — Basis: [Logging guide](https://docs.langchain.com/langsmith/configurable-logs).

### Gaps

- No verified provider-specific timeout, retry, idempotency, cancellation or unknown-result contract was available within this bounded source set. These must be established through the admitted provider and existing adapter contracts before unattended execution.
- No newly scheduled production path was run, changed or accepted. A major runtime change still requires the workspace's actual future-triggered native business session, independent business postconditions, recorded evidence and verified acceptance email. Manual research, installed packages, a graph test, handshake or agent agreement cannot replace that gate. Email actions are outside this task.
- This note is exploratory design research. It adds no services, workers, hooks, MCP entries, schedulers, model providers or active runtime configuration.
