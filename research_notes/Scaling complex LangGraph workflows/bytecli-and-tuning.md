# ByteCLI references and component tuning for complex LangGraph workflows

## What do the ByteDance sources add beyond the official framework documentation?

### Takeaway

Fresh bytedcli source reads succeeded in the root session. The most useful practitioner contribution is a division between task planning, bounded research work, deterministic tools, model judgment, and delivery, together with role-specific context and explicit completion signals. These are candidate design patterns, not measured evidence that adding agents improves this Trading Agent.

### Cited Findings

- 王济维’s **《基于LangGraph.js的MultiAgent工程实践（AI抖音-任务助手）》** describes Coordinator, Planner, Researcher, Designer, and Writer roles. Its `planning`, `next`, and `deliver` tools communicate a structured plan, task index, and completion status: success, failure, or more information needed. It separates a task list/current task index from messages and projects different message subsets into each role. Article creation metadata: **2025-08-08 UTC**; freshly read full `data.markdown`, not a generated summary. — [ByteTech article](https://bytetech.info/articles/7536140286804639763)
- The same practitioner article separates graph execution from the HTTP connection using persisted run status and cancellation signaling. It aggregates high-frequency model events before queueing asynchronous storage for later display. Its future-work list still includes fuller continuation and task management; therefore the article should not be represented as complete production acceptance. — [ByteTech article](https://bytetech.info/articles/7536140286804639763)
- 李世奇’s **《基于 LangGraph 的 MCP Security Scan Multi-Agent 开发实践》** distinguishes deterministic Code Scanner, atomic Tools, an LLM for analysis without tool selection, an Agent for autonomous tool-assisted work, a Supervisor for routing, and an Evaluator for second review. Its six stages are input, project analysis, feature extraction, risk identification, review, and report. Article creation metadata: **2025-04-29 UTC**; freshly read full source. — [ByteTech security workflow](https://bytetech.info/articles/7498383477415346215)
- That security workflow proposes second review to reduce uncertain or false-positive findings, but its displayed implementation includes placeholder results and hardcoded routing choices. The existence of an `Evaluator` node is not independent evaluation evidence, nor proof that undetected risks have been found. — [ByteTech security workflow](https://bytetech.info/articles/7498383477415346215)
- 丁同勤’s **《探秘 LangGraph：从 LangChain 基础到多智能体复杂系统搭建》** supplies supervisor/swarm and planner/executor/replanner examples, memory trimming/summarization, checkpoint/thread configuration, and human interruption. Its Agentic RAG loop explicitly terminates on adequate information **or a maximum loop count**. Article creation metadata: **2025-10-15 UTC**; freshly read relevant full-content sections. — [ByteTech complex systems tutorial](https://bytetech.info/articles/7560970795804327971)
- **《LangGraph 深度解析：从有状态工作流到生产级 Agent》** recommends orthogonal state fields, separate conversation and tool-output fields, and a unique `thread_id` for independent sessions. Current read succeeded; the bytedcli response supplies no author, publication date, or document revision. — [Feishu workflow document](https://bytedance.larkoffice.com/docx/SjwYdI31joFUyzxYwVqceFwsnmd)
- The original reference, currently titled **《LangChain 与 LangGraph 核心功能学习资料（超详解）》**, was freshly fetched through bytedcli. It explains `tags`, `run_name`, `metadata`, reducers, and subgraphs, but contains inconsistent claims about `create_agent` being a DAG versus handling a tool/model loop. Current response has **no revision**: do not relabel this fresh read as revision 181. The old revision-181 record belongs to the earlier local architecture note. — [Original reference](https://bytedance.larkoffice.com/docx/DER6dCHBhokjaVxB1d3cOatMnHb); [previous local note](</Users/bytedance/Desktop/Trading Agent/docs/architecture/langchain-design-notes.md>)

### Inferences

- Translate the security article’s distinctions into capability contracts: deterministic acquisition/normalization/calculation stay ordinary functions or tools; model judgment receives their bounded outputs; a coordinator owns routing. Promote a capability to an Agent or subgraph when its own tool selection, context, or multi-step recovery justifies that cost.
- Use a handoff envelope containing task ID, status, input/output schema version, source/evidence references, remaining uncertainty, and budget consumption. A narrative answer or `deliver(success)` alone should not authorize downstream completion or an external effect.
- Project context by role and task. Keep source handles, numeric facts, citations, and completion state intact; trim irrelevant conversation and tool noise. Test information loss as well as token savings before adopting summarization.
- Treat event replay for display, checkpoint resumption, and replay of external business effects as distinct operations. Each effect’s owning component must retain its delivery/approval/unknown fence.
- Evaluate a review node as a treatment: compare false positives **and false negatives**, additional latency, and token cost. A second model reviewing the first model’s answer may share the same blind spots.

### Gaps

- These practitioner sources provide implementations, examples, and anecdotes, not a matched, independent benchmark proving superior quality, throughput, or investment alpha for the proposed decomposition.
- Some examples use older `create_react_agent`, `MemorySaver`, or JavaScript APIs. Mutable API behavior must be checked against the project’s locked packages before implementation; tutorial code is not version acceptance.
- The worker’s initial query returned per-source failures despite exit 0: Feishu keychain access and ByteTech network failure. These **did not remain the final access outcome**: root-context searches and exact reads succeeded. No login, credential copy, or configuration change was needed. A small workspace-only CLI launcher changes only its log destination; it is a research helper, not an active Trading Agent integration.
- Fresh source packets: `runtime/bytetech-complex-systems.json`, `runtime/bytetech-multiagent-practice.json`, `runtime/bytetech-security-workflow.json`, `runtime/lark-original-reference.json`, and `runtime/lark-production-workflow.json`. Keep raw internal metadata out of the user-facing report.

## What does current official LangSmith documentation actually support?

### Takeaway

The same experiment machinery can evaluate a whole graph, its intermediate behavior, or an individual node. This supports a layered evaluation design without requiring every tuning attempt to rerun the entire research pipeline.

### Cited Findings

- **How to evaluate a graph** demonstrates end-to-end output evaluation, intermediate checks from graph state/messages, and checks using a `Run` object’s child traces when state lacks the needed information. It also directly evaluates `app.nodes["agent"]` through a target wrapper to isolate a node’s cost and behavior. Async graph nodes require `aevaluate`; the examples expose `max_concurrency`. — [Official graph evaluation](https://docs.langchain.com/langsmith/evaluate-graph)
- **How to evaluate agents** defines evaluation as a target function, dataset/examples, and evaluator functions receiving actual and reference outputs. Each call creates an experiment; per-example details can include associated traces when instrumented. Its experiment `metadata` supports model, prompt, and tool columns and grouping/filtering, with grouped feedback, latency, and token summaries. — [Official application evaluation](https://docs.langchain.com/langsmith/evaluate-llm-application)
- **Manage prompts programmatically** supports pulling a prompt by commit hash or commit tag, and storing a prompt together with model configuration or an output schema. It documents process-wide prompt caching with stale-while-revalidate behavior. Thus a bare mutable prompt name plus an experiment label is weaker provenance than the resolved prompt commit and configuration actually used. — [Official prompt management](https://docs.langchain.com/langsmith/manage-prompts-programmatically)

### Inferences

- Evaluate a capability/subgraph through a thin input/output adapter using fixtures at its contract boundary. Preserve both a test with known upstream inputs and a later test with actual upstream outputs: the first localizes faults, the second tests propagation.
- Keep trajectory checks for consequential invariants: permitted tools, argument correctness, evidence handoff, loop limits, and forbidden effect/replay. Judge semantic outcome quality separately. Do not require one exact call order when several valid trajectories produce a correct result.
- Attach correlation fields such as task ID, component, run/parent ID, experiment ID, case ID, candidate revision, and attempt. Keep them separate from raw account data. Missing child traces are an observability gap; they are not evidence that a model/tool call did not occur.
- For reproducible comparisons, resolve the actual prompt commit and record a content hash together with model/provider, sampling parameters, adapter version, tool descriptions, and schema. Do not silently use a new `latest` prompt midway through an experiment.

### Gaps

- These three pages do not establish specific dataset-split or privacy-masking API behavior. Split and privacy proposals below are evaluation policy recommendations, not claims that platform enforcement is already installed.
- `/langsmith/evaluate-intermediate-steps.md` returned HTTP 404. The graph page itself contains an intermediate-step section; only fetched pages are cited here. Official sources were retrieved directly as HTML, not through a repaired native-open route.
- Documentation mechanisms are not verified runtime behavior of the current cooperative manually serviced session engine. This research performed no model tracing, prompt upload, dataset mutation, evaluation run, deployment, or activation.

## Which component-level tuning strategy fits this Trading Agent?

### Takeaway

Start with one observed capability failure and one interpretable treatment. Combine deterministic contract checks, independent quality rubrics, and a small matched end-to-end comparison; expand to interactions and ablations only when the earlier evidence justifies them. Research quality and synthetic conformance remain distinct from investment alpha.

### Cited Findings

- The workspace evaluation contract separates alpha discovery, entry policy, and mentor behavior; it holds selection fixed when testing entry and entry fixed when testing selection. It requires matched cases, protected holdouts, realistic budgets, temporal/company dependence, and effect/uncertainty reporting. — [Local evaluation context](</Users/bytedance/Desktop/Trading Agent/mentor/skills/evaluation-design/references/investment-context.md>)
- The workspace experiment contract begins with an observed failure or labeled exploratory hypothesis; it initially changes one interpretable factor, logs every attempted variant, freezes cases/budgets/graders, and tests interactions deliberately. Missing evidence is inconclusive; a valid critical violation can reject a candidate. — [Local experiment context](</Users/bytedance/Desktop/Trading Agent/mentor/skills/experiment-design/references/investment-context.md>); [promotion decision contract](</Users/bytedance/Desktop/Trading Agent/mentor/skills/evaluation-design/references/promotion-gate.md>)

### Inferences

The following is a proposed evaluation matrix, not an implemented framework or observed performance result.

| Capability | Deterministic or contract metrics | Separate quality/outcome metrics |
| --- | --- | --- |
| Source acquisition | Read success/error/unknown, source ID and as-of date, required-source coverage, parsed schema, bounded timeout/retry, permitted fallback | Relevance, primary-source support, contradictions, stale or wrong-period evidence |
| Calculation | Exact arithmetic or declared numerical tolerance, units/currency, invalid/missing-input rejection | Whether the requested financial quantity is correctly defined and interpreted |
| Holdings/portfolio | Symbol/account/currency mapping, deduplication, declared-scope totals, schema, stale/missing-data status | Correctness of exposure/concentration interpretation; no unsupported all-account completeness claim |
| Investment research | Required evidence contract/finalization, citations resolvable, numeric/as-of consistency, unresolved gaps retained | Claim support, falsifiability, completeness, calibrated uncertainty, incremental selection value when prospectively measured |
| Entry policy | Fixed candidate stream, decision validity, effect authorization, stale inputs, unknown reconciliation | Decision value after costs, fills/unfilled orders, waiting, and missed opportunities |
| Factor workflow | Proposal/code/data/backtest/admission contract, immutable run identifiers, leakage checks | Out-of-sample performance against frozen benchmarks and costs; discovery or synthetic execution is not factor quality |
| Orchestration | Handoff schemas, task IDs, reducer/deduplication rules, cancellation/resume, loop bounds, no cross-task contamination | Completion of the user’s actual deliverables, useful recovery, justified routing, total latency/tokens/cost |

1. **Freeze a manifest.** Pin model/provider and parameters; prompt commit/content hash; tool/adapter versions and descriptions; schema and reducer versions; dataset snapshot/split; grader/rubric; graph/config revision; dependency versions; resource limits. Record an actual resolved version, not only a friendly experiment name.
2. **Keep splits meaningful.** Use development cases for iteration, a validation set for candidate selection, and a protected final holdout or new prospective stream. Stratify by observed failures, complexity, long context, unavailable sources, conflicting evidence, and recovery. For financial outcomes, split by time/company and publication availability where appropriate; random row splitting does not remove dependence or future knowledge in model weights.
3. **Separate error budgets.** Report success, valid partial, failed, and unknown separately, always with a denominator. Predeclare allowed total calls, retry count, wall time, tokens/cost, loop/replan count, and timeout. Critical effect, credential, fabricated-source, or unknown-replay violations cannot be averaged away by a strong overall score. Missing outcomes stay visible.
4. **Run one-factor matched A/B first.** An example exploratory treatment is narrower researcher context, with model/tools/data/graph/budget held fixed. Measure evidence support/completeness and cost, not token reduction alone. Repeat stochastic runs when their variation could change the decision; log failures and all tried variants.
5. **Then test propagation and interactions.** Check whether improved acquisition actually improves synthesis, whether a review node rescues or erases valid findings, and whether routing/context changes interact. Ablate one stage while keeping inputs and budget comparable; pipeline A/B estimates total benefit, while a component ablation investigates contribution. Neither alone proves a causal mechanism without the controlled contrast.
6. **Measure whole-pipeline postconditions.** Require the final evidence/delivery contract, preserved uncertainty, correct scope, all accepted deliverables, and bounded resource use. Report per-component metrics next to pipeline metrics so a good final narrative cannot hide acquisition or calculation failures.
7. **Keep observation privacy explicit.** Use the minimum authorized trace fields and sanitized fixtures; retain source handles/hashes instead of private account records where practical. Do not assume `tags` or tracing instrumentation enforces credential or privacy boundaries. Avoid uploading raw holdings, tokens, headers, or private source history as diagnostic convenience.

### Gaps

- The coordinator’s stated baseline is LangChain **1.5.0**, LangGraph **1.2.22**, and the cooperative manually serviced session engine. Calculator cloud atomic **3/3** is scoped historical evidence; holdings synthetic **8 cases/67 tests** is local conformance evidence. There is no claimed holdings cloud/live/model-trace acceptance or complete pipeline acceptance here. This worker did not independently rerun those checks.
- Synthetic fixture success proves only the tested contract. Generalization needs unseen representative cases; investment alpha needs independently specified prospective or appropriately uncontaminated outcome evidence, benchmark/horizon/cost controls, and uncertainty.
- A major runtime candidate still requires the workspace’s real future scheduled native business execution, independent postconditions, and exact verified email receipt. Manual experiments or LangSmith scores cannot replace that acceptance gate. This task sent no email and activated nothing. — [Runtime acceptance contract](</Users/bytedance/Desktop/Trading Agent/docs/deployment/runtime-acceptance.md>)
