# Execution observability handover

User split this work out on 2026-10-31. The main orchestrator continues evidence,
cache, fallback, immutable actions and phase execution verification. This notice
hands the optional audit/replay surface to the next owner; it is not acceptance
of a production dashboard.

## Scope and files

- `investment/research/report.py`, `report.css`, `tests/test_report.py`: standalone,
  private HTML projection of existing hashed receipts. Four focused checks pass.
- `investment/research/audit.py`, `tests/test_audit.py`: UUID execution lookup,
  immutable chained audit snapshots and atomic latest pointer; four focused
  checks pass, including optional audit/render failure not changing domain status.
- `investment/research/run_pilot.py`: best-effort audit/export/render integration;
  returns `execution_id`, `audit_ref`, `observability_diagnostics` and optional
  `view_ref`/`html_ref`. These additions have targeted wrapper tests; fresh scheduled
  acceptance of the changed combined runtime is still pending.
- `investment/research/examples/earnings-query.pipeline.json`: external ordered
  phase recipe for the reviewed NVIDIA Q1 FY2025 revenue reconciliation. This is
  a historical fixed-fact pilot, not a general/latest earnings analyst.

Tool Strategy was inspected READ ONLY at
`~/tool_strategy_i18n_ts/src/features/case-replay/`, especially
`CaseReplaySurface/ReplayReady` and `NodeRunDetailSheet/BasicInfoSection`.
No source was copied or changed there. The adaptation uses progressive phase
and call details, separate recorded/missing states, and an ordered timeline.
Do not modify that repository.

## Data contract

The authoritative runner report supplies `run_id` (execution ID),
`pipeline_id`/`pipeline_version`, `started_at`/`finished_at`, `counts`, `events`,
`action_records`, `input_manifest.config_ref`/`request_ref`, `phases`,
`phase_refs`, `final_ref`, and observed model usage. Action records bind request,
arguments, outcome and execution receipt references. The acquisition mode and
receipts are in the request's `acquisition`; `source_ref` preserves original
provider/source/availability/retrieval metadata. Per-phase data may contain
`conclusion`, `explanation`, `unresolved_gaps` and `evidence_refs`.

Resolve and hash-check references. Missing data stays missing. Do not display raw
prompts, credentials, complete arguments or arbitrary provider payloads. Keep
execution success, evidence support and runtime acceptance separate. Cost stays
unknown without a real billing observation.

## Nonblocking boundary

Audit/display are optional, bounded best-effort projections. Their exceptions
return sanitized diagnostics without changing the domain execution verdict.
The audit writer uses a nonblocking per-execution lock. Authoritative action
receipts, effect fences, dependency checks and checkpoints remain safety-critical:
unknown effects cannot be replayed merely because a display log is unavailable.
No new service, database, queue, active MCP registration or frontend dependency
is needed for this handover.

## Verification and next owner

`ui/runtime/replay-check.json` and screenshots contain the local browser check.
Desktop 1280×800 and mobile 390×844 passed without page overflow; keyboard
Enter expanded the timeline with visible focus. The bounded preview and browser
were closed.
The projection used an existing real record: two phases, two calls, one explicitly
cached source. This is historical rendering evidence, not new scheduled runtime
acceptance. All files and preview artifacts are workspace-local.

Next: inspect this working-tree diff; finish any missing mobile/keyboard check;
check partial/blocked/live cases and the nonblocking error contract; optionally
add a thin execution list/view entrypoint. Coordinate before changing
`execution.py`, `run_pilot.py`, pipeline examples or shared source/actions files:
these belong to the main runtime verification. Keep all new files here. Read
root/mentor/UI AGENTS and routers, and apply selected design skills. A material
runtime change needs the future scheduled Codex session, independent
postconditions and configured-owner verified notification described in
`docs/deployment/runtime-acceptance.md`. No current claim of full observability
acceptance or ongoing background monitoring is made.

## Coordination with control-platform owner

The control/UI task owns new `investment/control/` work. Core `execution.py`,
`run_pilot.py`, source/actions and examples remain with the runtime orchestrator
until coordinated. Current `execution.run` accepts config/request, output directory,
model callback, critical guard, finalizer, optional checkpoint, pause boundary,
release directory and UUID execution ID. It freezes selected current releases at
fresh run start and reuses exact releases on resume. It does not yet accept an
arbitrary historical published-pipeline release-binding map for a fresh run.
Treat that as a gap; do not bypass private `_configuration` to imply support.
Acquisition still precedes the ordered runner. Per-run resource scoping beyond
the domain guards is also separate from JSON type validation.

Do not nest `run_codex` below a waiting `run_business` using the same authentication
home: the outer turn holds its lock. The scheduled validation finishes its
shell-enabled source session first, then runs the application-owned tool-free
phase model loop. No copied auth home or nested seatbelt is required.

## Configuration, versioning and enforcement expansion

The user expanded this handover to cover action/pipeline version management,
configuration CRUD, effective runtime bindings, case replay and evaluation of
configuration compliance versus result correctness. See the reviewed
[implementation plan](configurable-pipeline-platform.md) for exact lifecycle,
public interfaces, sandbox limits, evidence presentation and incremental gates.
The platform is proposed; no new runtime or active configuration is installed
by this planning change.

Three read-only agent reviews inspected runtime enforcement, Tool Strategy's
replay/configuration interactions and configuration/scheduler ownership. No Tool
Strategy source was copied or modified. Both canonical loaders were manually
invoked on 2026-10-31 and returned `MENTOR_INIT_OK` and `UI_INIT_OK`, verifying
six and seven skill sources/discovery links. All 16 initialization tests passed.
Automatic host SessionStart execution remains unverified; the manual receipt is
under `mentor/runtime/observability-control-initialization/receipt.json`.
