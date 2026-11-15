# Acquisition, evidence, calculation and factor-boundary review

Recommendation: finish the existing single-calculator pilot before extending its
tool set. LangChain can own model invocation and tool selection; LangGraph can
sequence those calls and deterministic checks. Existing evidence, financial math,
dispatch and credential owners should remain authoritative. A framework migration
of those owners is unnecessary for the current A/B requirement.

This is a source-only architecture review. No providers were invoked, no
credentials/private artifacts/protected outcomes were read, and no tests were run. Actual
`MENTOR_INIT_OK` output was unavailable in this fork; `mentor/AGENTS.md`,
`mentor/ROUTING.md` and `mentor/skills/development-discipline/SKILL.md` were read
directly as the disclosed fallback. The parent reports the current real-provider
pilot E2E as **unverified** after gateway timeouts. This review does not change
that status or establish investment alpha.

## 1. The existing calculator is already the right first tool

**Implemented source, isolated pilot; production acceptance unverified.**
`shared/calculation/legacy/valuation/valuation_core.py:50-66` exposes
`equity_value` with explicit inputs, finite Decimal arithmetic, a 40-digit local
context and separate enterprise/equity/per-share outputs. It needs no new
calculation service. The calculation catalog explicitly describes the copy and
its validation/operators as inactive candidates
(`shared/calculation/README.md:3-12`, `:82-95`); its broad certification is not
implied by this one primitive.

The current pilot already uses the appropriate thin adaptation:
`tuning/langchain_pilot/graph.py:64-78` validates a bounded case, calls the
existing primitive and returns Decimal strings. Its tool receives the case from
workflow state. The agent does not choose new financial assumptions through tool
arguments. `graph.py:113-151` requires a successful tool receipt bound to an
actual model call, checks per-share value with a separate rational-arithmetic
oracle, and requires the final answer to match the tool result.

Keep that boundary and complete its provider E2E. Do not add a calculator agent,
general expression executor, validation-runner service or new finance abstraction
to answer this test. An output-parity gate deliberately makes compliant variants
produce the same answer; this experiment can establish orchestration and
prompt/transport behavior, not better valuation or research quality. The
independent bounded oracle is useful verification, not redundant production math.

## 2. Acquisition fits typed tools; evidence policy belongs outside the agent

**Implemented public interfaces; current deployment not established by this
review.** Useful wrappers already exist as ordinary Python functions:
`discover_openalex` returns `access_level='metadata'`
(`shared/research_sources/fetch.py:167-178`), `fetch_arxiv` requires an exact
version and confirms it against Atom plus HTML (`:143-164`), and
`fetch_document` admits an explicit official-host HTML route (`:219-225`).
`passages` returns bounded exact text, offsets, continuation and the receipt hash
(`:228-238`). Document receipts preserve raw/text artifacts, revision availability
and provenance while explicitly declining truth/independence certification
(`:127-140`). Preserve these distinct result types in tool outputs.

For a later retrieval graph, use deterministic nodes to load the
coordinator-owned requirements contract and validate evidence; use tools only for
discovery, admitted acquisition and bounded passage reading. The coordinator pin
is deliberately outside the worker packet
(`investment/research/requirements.py:32-45`). The model must not silently lower
the requirement, relabel metadata as reading, or edit the expected hash.

Keep `coverage.validate` authoritative for access, cutoff, artifact hashes, exact
passages, model linkage, distinct lineage and hash-bound independent review
(`investment/research/coverage.py:27-114`). Keep maintained finalization/completion
as application-owned nodes or explicit coordinator steps; both revalidate that
contract around preserved Niulai gates
(`investment/research/pipeline.py:29-53`). Do not expose legacy migration scripts
as alternative completion tools. These deterministic gates verify recorded
bindings; they do not establish the truth of the review (`coverage.py:111-114`).

## 3. Avoid a fourth acquisition state authority

**Demonstrated implementation overlap, not proof that existing owners can be
deleted.** `AcquisitionController` already owns proposal admission, reserve
budgets, deduplication and typed fallback
(`investment/research/acquisition_orchestration.py:221-322`). `AcquisitionDriver`
owns durable cross-component handoffs rather than provider invocation
(`investment/research/acquisition_driver.py:1-5`, `:99-127`).
`HostedAcquisitionRunner` independently owns dispatch permission through its
durable journal and an injected provider/deadline contract
(`investment/research/acquisition_runner.py:102-108`). The direct-source batch
route also already owns cache reuse, deadline/provider-call reservations,
bounded retries and unknown-outcome stopping
(`shared/research_sources/batch.py:131-225`).

There is repeated head/lock/atomic-write plumbing between controller and driver
(`acquisition_orchestration.py:187-205`; `acquisition_driver.py:68-86`), and the
driver's recovery imports reach into the controller's private `_head`
(`acquisition_driver.py:129-145`). These are concrete maintenance seams. They are
not evidence that budgets, receipt custody and replay fencing are unnecessary.
Adding LangGraph counters/checkpoints as competing business truth would duplicate
these responsibilities further.

For the pilot, retain these modules unchanged. A future acquisition graph should
store owner-issued identifiers/receipt references and sequence public methods;
the existing owners decide whether an effect may execute or replay. Avoid
automatic graph retries around provider dispatch or an entire batch. If a
subsequent acquisition integration actually needs recovery access, expose one
narrow public reservation-read method instead of teaching the graph to read
private state or introducing a generalized workflow/state service. This review
does not recommend deleting versioned contracts solely because several versions
exist.

## 4. Tiger is a later adapter, not a first-pilot read-only shortcut

**Existing gateway; market calibration remains a manual unregistered candidate.**
Tiger's shared boundary owns leases, restore/checkpoint, local concurrency and
unresolved-outcome fencing (`shared/tiger/README.md:3-15`, `:79-100`). Its launcher
requires fresh native service context passed through hidden input/private pipes;
it does not independently provide unattended authentication (`:40-47`). One
portal/worker attempt is intentional (`:85-91`). A broker read can therefore
cause credential-persistence effects even though it places no order.

A later LangChain tool should call the existing gateway through a host-owned
capability, receive a sanitized receipt/projection, and leave credentials and
native service context outside prompts, graph checkpoints and tracing. Do not
wrap `queries.execute_query` directly, synthesize authorization, introduce model
retries, or bypass an unresolved fence. The market-calibration authorization is
explicitly owner-issued and may not be auto-issued by workers/tools
(`shared/tiger/README.md:123-155`). No Tiger invocation is necessary for the
current calculator experiment.

## 5. Factor data is contract-ready, not engine-ready

**Source-only engines, fixture contracts and disabled deployment candidate.**
`factor/README.md:7-21` states RD-Agent/Qlib have not been installed/imported/run
and keeps two Qlib revision environments separate. The intended Qlib subprocess
bridge is deferred (`:23-35`); the `shared/qlib_bridge/` path is absent in this
checkout. Do not describe it as an implemented integration.

An eventual graph may orchestrate an isolated RD-Agent/Qlib adapter and read a
sanitized run projection. Keep point-in-time data identities, engine revisions,
evaluation/admission and run publication in their existing owners. The manifest
registry validates legal transitions and artifacts before publishing immutable
content plus its head (`shared/factor_mining/manifest.py:636-659`); the projection
loads through that registry and identifies itself as read-only
(`shared/factor_mining/projection.py:100-135`). A LangGraph checkpoint must not
substitute for either. Do not import upstream engines or deserialize their pickle
outputs in the graph host (`factor/README.md:35`). The frozen-disabled cloud
scaffold and synthetic fixture chain establish no real factor quality
(`factor/README.md:37-39`).

## Minimal adaptation sketch

The immediate graph already has the needed shape:

```text
validated synthetic case
  -> prepare fixed state + variant prompt
  -> create_agent(tools=[calculate_valuation])
  -> independent result/receipt verifier
  -> bounded pilot result
```

This is implemented in `tuning/langchain_pilot/graph.py:154-178`. Use the same
tool, case validation and verifier for each prompt variant. Finish the unresolved
provider E2E before adding another capability.

The smallest acquisition extension afterward is one frozen-source passage tool,
without any new fetcher, cache, evidence database or research completion path:

```python
# Illustrative candidate only; not added or executed by this review.
from langchain.tools import ToolRuntime, tool
from shared.research_sources.fetch import passages

@tool
def read_evidence_passage(source_id: str, runtime: ToolRuntime,
                          start: int = 0, max_chars: int = 3000) -> dict:
    """Read an exact bounded passage from coordinator-selected source material."""
    ref = runtime.context["source_refs"][source_id]
    return passages(ref, start=start, max_chars=max_chars)
```

The coordinator supplies a closed mapping of public development-source IDs to
verified receipt references outside model messages. The tool accepts IDs, not
arbitrary filesystem paths. Treat returned source text as untrusted evidence.
Keep `passages`' existing range/access/hash checks; surrounding nodes retain the
frozen cutoff/requirements checks. This extension tests evidence reading and
tool plumbing, not live acquisition, full company completion or alpha.

## Acceptance boundary

This report changes documentation only and activates nothing. Source inspection,
local unit results or manual provider E2E cannot accept production adoption. A
major integration requires the actual future-triggered Codex business session,
candidate-bound independent postconditions and verified acceptance email under
`docs/deployment/runtime-acceptance.md:9-21`, `:47-68`. Missing execution remains
unverified; observed failure remains failed. Preserve all unknown-outcome fences
and the existing owner/approval boundaries.
