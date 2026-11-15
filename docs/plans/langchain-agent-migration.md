# Incremental LangGraph migration

Decision, 2026-11-15: use the working local calculator E2E to establish a model
boundary, then migrate one read-only research path. This is an exploratory
integration plan. It does not establish improved research quality, investment
alpha, unattended execution or production acceptance.

The observed benefit is inspectable workflow state and a replaceable model engine.
The cheapest adequate implementation is a thin graph over maintained Python
interfaces. Do not copy the existing agent into a second source tree or maintain
an import-sync process. Preserve `niulai/` and `niulai-private/`.

## Ownership and state

| Owner | Responsibility | Boundary |
| --- | --- | --- |
| Investment research, `investment/research/` | Business workflow, typed inputs/results, evidence references and domain gates | A future graph sequences public functions. Alpha discovery and entry policy remain separately testable. |
| Model adapter, currently `tuning/langchain_pilot/session_model.py` | Messages/tool schemas in; assistant message/tool selection out | No tool receipts, financial-input replacement, business approval or workflow reconstruction from chat. Session binding is separate from graph state. |
| Shared adapters, `shared/research_sources/`, `shared/calculation/` | Bounded acquisition, provenance, passage access and calculation | Import public interfaces; credentials and provider/replay permissions stay with their owners. |
| Research contracts, `investment/research/requirements.py`, `coverage.py`, `pipeline.py` | Coordinator pin, source coverage and maintained finalization/completion | The model cannot relax requirements or approve its own evidence. Graphs do not bypass these gates. |
| Tuning, `tuning/evals/` | Frozen cases, budgets, fingerprints, traces, grading and admission | Grade independently reopened evidence; LangSmith is an optional derived trace view. |
| Mentor, `mentor/` | Work orders, experiment guidance, progress and blocker review | Guidance does not become business-state or effect authority. |
| Existing runtime and delivery owners | Due-slot claims, resource locks, outbox, logical delivery keys and unknown reconciliation | A later graph runs inside one claimed attempt. A graph checkpoint cannot authorize a provider replay or resend. |
| Factor components | RD-Agent proposals/coding, Qlib execution, evaluation/admission, immutable run state and UI projection | Keep their contracts separate. Source discovery and fixture passes do not establish factor quality. |

LangGraph owns reasoning checkpoints, messages and references to owner-issued
receipts. The acquisition journal, evidence store and outbox remain authoritative
for their own transitions. Do not duplicate their budgets or legal transitions
as a second business ledger inside graph state.

Keep the pilot adapter local until a concrete second consumer needs it. At that
point, extract only the proven model-message contract into shared infrastructure;
do not introduce a general agent platform in advance of that need. Session IDs
are declared metadata, not authentication or proof of the underlying model.

## Next vertical slice

The proposed next implementation belongs with investment research, with its
experiment/driver under tuning. These nodes are not implemented by this plan:

1. Load a coordinator-pinned requirements contract and an explicitly admitted,
   frozen public-evidence fixture.
2. Read bounded passages through the existing source interface; retain revision,
   offsets and artifact hashes.
3. Ask the pluggable model for analysis and tool selection; let LangChain execute
   the allowlisted tools. Reuse the existing calculator if needed.
4. Write a draft packet to a unique experiment directory, then invoke the
   existing coverage check. Report failure explicitly.

Stop this first slice at a validated draft. It has zero broker, email, live
acquisition, scheduler-registration or production-publication effects. A later
full-research slice must call `investment.research.pipeline.finalize` and
`complete`, using an actually performed, hash-bound independent review; fabricated
review fields cannot be used to make a fixture pass. The maintained pipeline
preserves the Niulai validators and adds source coverage.

## Validation before expansion

Freeze the following specification before executing the migration experiment.
The question is whether orchestration preserves the existing behavior and
recovery boundaries, not whether the new agent makes better investment choices.

| Gate | Baseline / candidate | Required observable result |
| --- | --- | --- |
| Adapter contract | Existing session adapter, then any new engine | Wrong request/session/revision and malformed replies are rejected; a valid reply can recover; ambiguous dispatch stays fenced. Tools execute in LangChain. |
| Domain parity | Maintained functions called directly / the same functions wrapped by the graph | Identical normalized values and evidence references on one valid fixture. No hidden fallback or altered source requirements. |
| Domain failures | Same fixture with a required passage missing, then with one artifact hash changed | Both paths reject; neither publishes a completion artifact. These are distinct negative cases. |
| Recovery | Pending model request, graceful restart, explicit rebind and corrected reply | Same thread/messages/tool receipts survive. No completed tool is replayed. Actual second-host handoff requires separate live evidence. |
| Local integration | Public Agent Server API and Studio, real host replies | Exact run identity/status, reopened final state and independent result validation agree; errors yield visible failure. |

Use one run per declared deterministic case first. Permit at most three model
turns per case, the same frozen tool schemas/prompts/model setting in both arms,
and the existing per-call bounds. Record host wall time and tool/provider-call
counts separately from correctness; leave unavailable token/cost observations
null. The session engine is cooperative: human/host waiting time is not evidence
of autonomous model latency. Stop on any correctness, evidence, duplicate-effect
or hidden-failure violation and repair that mechanism before adding cases/tools.

Freeze case inputs, source closure, grader closure and candidate fingerprints.
Reuse `tuning/evals/evidence_runtime/contracts.py` for a sealed comparison when
running arms; provide a workload-specific independent grader. The worker packet
excludes answers, but same-user filesystem access is not a blind holdout. Report
every tried variant and failure. A small development suite supports only the
scoped migration gate; stochastic quality comparisons need a separately declared
experiment and appropriate repeats/splits.

Do not weaken the specialized acquisition EIY checker for arbitrary prompt,
model, tool or graph changes: its matched treatment contract is narrower.
Research-quality and alpha/entry-policy experiments follow mentor experiment
design and evidence/overfitting guidance separately, holding other factors fixed.

## Activation and allowed claims

The current local synthetic calculator graph has cooperative E2E evidence.
It does not automatically wake a native chat session. The optional direct OpenAI
API engine has no verified live pass without a separately supplied Platform key.
No whole-agent migration or production cutover has occurred.

Before any production runtime activation, stage a disabled candidate, preserve
owned backups, prove failure containment/rollback and follow
`docs/deployment/runtime-acceptance.md`. Acceptance requires an actual future
scheduled Codex business run, independent business postconditions and verified
acceptance-email readback. Manual local runs and unit tests cannot replace it.

Source-only component reviews: `tuning/langchain_pilot/reviews/acquisition.md`,
`runtime.md` and `skills-evaluation.md`. Setup and current execution instructions:
[local pilot runbook](../deployment/langchain-pilot.md).
