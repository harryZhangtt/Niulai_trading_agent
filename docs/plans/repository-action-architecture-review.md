# Repository architecture and gradual action migration

Source review, 2026-10-31. This is a review/implementation plan, not a runtime
refactor. Two independent read-only reviews checked the findings. No Niulai
source, private archive, active allocation, credential or runtime behavior was
changed by this review.

## What exists

At inspection `investment/` has 18 Python source modules excluding tests/runtime:
15 excluding package initializers and `__main__`, with six CLI entry modules.
Executable files include domain libraries, orchestration, gates, projections and
acceptance harnesses. They should not all become model-callable actions.

Exactly three actions are registered in
[runtime.py](../../shared/actions/runtime.py), all version `1.1.1` at inspection:

| Action | Input/output schemas | Current implementation binding |
| --- | --- | --- |
| `evidence.acquire_document` | `Acquire` → `AcquireResult` | `_run` → `fetch.fetch_arxiv` / `fetch_document` |
| `evidence.read` | `Read` → `ReadResult` | `_run` → verified source receipt + `fetch.passages` |
| `evidence.compare_numeric` | `Compare` → `ComparisonResult` | `_run` → `_numeric` → original Niulai `evidence_crosscheck.calculate` |

`SPECS` is the current discovery authority. `_run` separately maps IDs to
implementations. [contracts.json](../../shared/actions/contracts.json) supplies
the schemas. Pipeline JSON selects registered capabilities; it is not another
handler registry. A read-only AST/schema-name check found all three IDs, handler
branches and schema references consistent today. The scaling issue is manual
synchronization, not a demonstrated catalog mismatch.

An action is a bounded capability with typed input/output, trusted implementation,
authorization, effects/error semantics, limits, version and receipt. A script is
an implementation or CLI form. One action may compose several modules; one module
may support several separately contracted actions. Do not equate files and actions.

## Material architecture findings

1. **Bindings and dependency closure are spread across files.** Descriptor metadata
   is in `runtime.SPECS`, handlers in `_run`, schemas in `contracts.json`, working-tree
   hashes in `runtime.manifest`, frozen file selection in `releases._paths`, and
   mandatory files in `verify_release`. Linking separate schema/code files is
   appropriate; maintaining the binding/dependency relationship repeatedly is not.
2. **Action releases are currently coupled.** Every action bundles the whole action
   package/contracts, fetch/artifact helpers, model/business adapters and legacy
   comparator. An unrelated change can alter all action hashes and trigger version
   reuse rejection. Keep conservative coverage initially, then derive common
   protocol-core and per-action closure from one trusted definition. Do not omit
   dependencies just to obtain stable hashes.
3. **A catalog refactor needs release-format compatibility.**
   [releases.py](../../shared/actions/releases.py) parses a literal `SPECS` assignment
   from frozen `runtime.py` using `ast.literal_eval`, and checks historical action
   IDs against current `runtime.SPECS`. Moving/computing that variable or deleting
   an ID can break resolution. Introduce a versioned manifest with hash-bound
   descriptor, handler, schemas and closure; preserve strict format-1 verification.
   Never rewrite old bundles or manufacture historical source.
4. **Infrastructure has some domain coupling.** Actions import private `_stream`
   from the email-capable job business transport; campaigns also use process
   supervision. A small shared process primitive has concrete reuse. The research
   runner also special-cases numeric comparison for domain authorization; replace
   that gradually with a host-selected policy contract applied to every action.
   The model cannot choose its own verifier.
5. **Naming obscures responsibilities.** `investment/research/pipeline.py` is a
   legacy-backed completion facade; `execution.py` is the ordered runner. Generic
   artifacts live under `shared.research_sources.artifacts` despite broader use.
   Clarify these boundaries with documentation and compatibility exports before
   moving files. A broad directory rename would add risk without proving behavior.
6. **Niulai is still a live dependency.** Several maintained paths import, execute
   or stage its files. Calculator copies did not migrate all callers. The new
   `contribution.py` does import maintained valuation operators, so calculation
   README wording about no active imports anywhere is historical copy-stage text;
   production migration is still a separate claim.

## Different catalogs should remain different

| Surface | Meaning |
| --- | --- |
| `shared.actions.registry()` / `SPECS` | Executable approved capabilities |
| `shared/research_sources/catalog.json` | Provider capabilities/limitations for routing |
| `investment/research/catalog.py` | Read-only import of research metadata/notes into an index |
| `shared/calculation/manifest.json` | Source/copy lineage, hashes and known scope |
| Published action/pipeline manifests | Frozen identities for release/runtime, not editable duplicate catalogs |

Do not merge research content, providers and executable permissions into one
catalog. Generate the action discovery/UI view from authoritative definitions;
retain separately typed source and provenance catalogs.

## Which investment modules should be actions?

| Role | Current modules/operations | Treatment |
| --- | --- | --- |
| Domain libraries | `requirements`, `coverage`, `routing`, `use_policy`, `contribution` | Keep callable/testable libraries; wrap only required public operations |
| Bounded candidates | Requirement freeze, scoped coverage assessment, `calculate_scenario` | Thin typed adapters when a real pipeline needs authorization/version/receipt |
| Mixed workflow | `pilot.prepare`, `Pilot` guards/finalizer | Explicit preparation/domain policy contracts, not one unrestricted model tool |
| Host orchestration | `execution`, `run_pilot`, `contribution_run`, completion facade | Host owns sequence, model sessions, checkpoints and completion |
| Optional projection | `audit`, `report`, CSS | Bounded read-only surfaces; no domain-success authority |
| Evaluation/acceptance | Tests, `acceptance`, `pilot_acceptance` | Independent checks, not tools an evaluated agent uses to award itself acceptance |
| Corpus import | `catalog.import_catalog` | Scoped host/admin ingestion; not automatically an agent tool |

Pure operators stay below scripts/actions in `shared/calculation/operators/`.
For example, a scenario action composes numerical functions with units, assumptions,
precision and error contracts; every Decimal helper does not need a separate
action call. `contribution.py` importing `d`/`pv` directly is appropriate for its
host-owned calculation. Host-only gates remain inaccessible to model proposals,
even if an administrative catalog describes them.

## Target ownership and one binding definition

```text
shared/
  actions/               protocol, registry checks, bounded dispatch, releases
  calculation/           numerical operators, preserved copies, validation
  research_sources/      acquisition, receipts, evidence store/index
  job_runtime/           common wake/slots/model/auth/retry
  tiger/                 broker lease/auth/transport; separate reporting later
investment/
  actions/               domain adapters + explicit application catalog composition
  research/              requirements, evidence/use policy, coverage, completion
  workflows/             named workflows/configuration, moved gradually
  control/               draft/publish/activation; consumes registered versions
  observability/         safe projections when control needs a shared surface
  holdings/              future maintained holdings/report domain
  runtime/               ignored private artifacts
mentor/                  supervision and engineering/evidence guidance
tuning/                  experiments and independent evaluations
ui/                      UI guidance, pinned tooling and verification artifacts
niulai/                  preserved source during gradual migration
niulai-runtime/          compatibility/runtime facade while consumers migrate
niulai-private/          preserved archive, outside code cleanup
```

This is an ownership map, not an immediate move of every file. Start with needed
action definitions and a migration ledger. Preserve public imports through thin
compatibility exports. Keep the ordered runner in its present domain until a real
second consumer justifies extracting a generic engine.

Each action has one trusted definition linking:

```text
id/version/owner
input and output schema refs
trusted handler binding
effects, error/retry owner and resource-policy registration
explicit code/dependency closure and environment requirements
```

Definitions live with their owning adapters. An explicit composition root,
initially `investment/actions/catalog.py`, selects the approved set and supplies
it to the generic dispatcher. Infrastructure need not import investment domains.
No folder scanning, automatic plugin loading or model-supplied import paths.
Keep format-1 registrations behind compatibility handling during transition.

Generate CLI/UI discovery, release manifests and documentation summaries from
those definitions. Control and workflow modules must not maintain another handler
registry. Pipelines grant a scoped subset of catalog capabilities. A deployment
may contain many frozen release snapshots without creating many editable sources
of truth. Effect labels alone do not enforce resource scope or OS containment.

Focused registry checks should cover unique IDs/versions, schema refs, trusted
handler coverage and dependency declarations. New-format release tests must
resolve old-format bundles and detect missing dependencies. Frozen manifests
carry exact code/schema identity, not merely a current function name.

## Live legacy dependency map

| Maintained consumer | Still reads/stages original Niulai source |
| --- | --- |
| `shared/actions/runtime.py` | Numeric comparator `evidence_crosscheck.py` |
| `shared/actions/releases.py`, pilot acceptance fingerprint | Comparator path and old frozen layout |
| `investment/research/pipeline.py` | `finalize_research`, `research_completion` and validators/store/schema closure |
| `niulai-runtime/.../e2e_prepare.py`, `daily_prices.py` | Price parser/state/report, price view/PDF files and fonts |
| `niulai-runtime/.../e2e_guard.py`, `daily_report.py` | Holdings code used for independent verification/report composition |
| `shared/tiger/bridge.py` | Holdings Python/fonts, Tiger adapter, five-day fetch and report pipeline |
| `shared/calculation/__main__.py verify` | Original paths for source/copy parity, even if execution uses copies |

Public job templates do not prove installed private allocations are inactive.
Inspect supported foreground, recurring, retry and recovery routes before
retirement. Historical bundles have their own copied bytes and retain their old
layout/readers independently of eventual live-source cleanup.

## Gradual copy, verify, switch and retire

Record each capability's original symbol/path/hash, complete dependency/assets
closure, destination, owner, callers, parity/correctness evidence, replacement
action/pipeline versions, scheduled/recovery acceptance and retirement state.
Never copy private state into that ledger or fixtures.

1. Inventory direct/staged imports, root-relative schemas/assets, release builders,
   independent graders, deployment commands and installed/recovery consumers.
   New capabilities should not add original-source dependencies.
2. Copy a bounded closure unchanged with hashes, layout, assets and notices.
   The standalone comparator is a smaller first candidate than the full-research
   gate. Use a component-local compatibility area; keep the original untouched.
3. Verify byte parity, relocation/import origins and accepted/rejected behavior.
   Check independent expected results separately: parity preserves known legacy
   defects and is not numerical correctness. Fixes get separate versions/evidence.
4. Switch one maintained facade/action to the copy. Publish a new action/pipeline
   version and update dependency/verifier fingerprints. Never change old releases.
5. Compare without duplicate business effects, then exercise the intended future
   scheduled Codex path, independent postconditions, restart/recovery and verified
   owner result notification. Preserve failures and unknown-effect fences.
6. Retire original callers only after foreground, scheduled, retry/recovery,
   deployment and provenance tools use the replacement. Keep compatibility exports
   while those consumers migrate.
7. Review deletion only after retirement evidence. A grep result alone does not
   establish unused code; check allocations, recovery, assets, release readers
   and supported consumers outside this process. Preserve historical bundles and
   provenance. The user's intended eventual dead-code deletion is not deletion
   now, and does not include `niulai-private/`.

The full-research gate requires more than copying two scripts: validators derive
schema/policy roots from `__file__` and import evidence/store/queue modules. Preserve
that closure or test a trusted asset-root interface. The narrow revenue pilot
cannot replace the full-research gate. Holdings/Tiger is a later larger slice
that must preserve credential, lease/checkpoint and reporting boundaries.

First validate today's registry/compatibility contract, then copy the standalone
comparator and verify it behind the existing facade as a new release. Design
release-format evolution before moving `SPECS`. Next add one needed domain/calculation
action and immutable pipeline binding from the
[platform plan](configurable-pipeline-platform.md). Folder moves follow accepted
boundaries rather than precede them.

Runtime changes require [scheduled acceptance](../deployment/runtime-acceptance.md).
Setup changes also update runbooks/inventory and pass the setup audit. This review
installs no actions, changes no runtime behavior and deletes no preserved source.
