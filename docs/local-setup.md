# Local deployment source of truth

For the2026-10-31 recurring email addition, use the
[Niulai business runbook](../niulai-runtime/docs/recurring.md): private parallel
authorization, branch checkpoints/retries, canonical `[CODEX]` reports and exact
native Gmail verification. Parallel sending is authorized; it is not sole-sender
cutover. Future scheduled business acceptance still applies.

Update this guide or its linked runbooks in the same change as any installation,
dependency, configuration, runtime-path, credential-handling or recovery change.
Keep private values out of documentation and the sanitized inventory.

| Component | Source | Private state | Runbook |
| --- | --- | --- | --- |
| Scoped evidence/actions/phase runtime | `shared/actions/`, `shared/research_sources/store.py`, `investment/research/` | Existing private research roots and `.job-runtime/runs/` | [Research runtime](deployment/investment-research.md) |
| Shared wake/scheduling/models/retries and frozen-disabled strict containment source candidate | `shared/job_runtime/` | `.job-runtime/` | [Job runtime](deployment/job-runtime.md) |
| Copied calculation candidate (inactive) | `shared/calculation/` | `.job-runtime/calculation/` | [Calculations](deployment/calculation.md) |
| Investment evidence requirements and coverage | `investment/research/` | `.niulai-state/reports/investment-research/` | [Investment source contract](../investment/research/README.md) |
| Project-local `$investment-review` instruction entrypoint | `investment/skills/investment-review/`, `.agents/skills/investment-review` discovery link | Existing private investment research roots; no new environment | [Review entrypoint setup and rollback](../investment/research/README.md#project-local-investment-review-entrypoint) |
| Research-source acquisition and proxy calibration candidates | `shared/research_sources/` | `.research-sources/`, `.niulai-state/reports/research-sources/` | [Source tools](../shared/research_sources/README.md) |
| Optional Jev source labeling and development evaluation | `shared/typed_judge/`, `investment/research/source_labeler.py`, `tuning/evals/label_accuracy/` | Existing private research roots, `.job-runtime/credentials/` and acceptance records | [Jev setup and recovery](deployment/jev-labeling.md) |
| Native search + EgoLite candidate (disabled) | `shared/web_access/`, `tuning/evals/browser_cooperation/` | `.research-sources/web-access/` | [Browser cooperation](deployment/web-access.md) |
| Niulai admission/report/email adapters | `niulai-runtime/`, preserved `niulai/` | `.niulai-state/` | [Niulai](deployment/niulai.md) |
| Shared Tiger credentials/query gateway and manual market calibration candidate | `shared/tiger/`, shared MCP portal | `.niulai-state/` | [Tiger gateway](../shared/tiger/README.md) |
| Market-data adapters | `shared/market_data_mcp/` | `.market-data-mcp/` | [Shared and tuning](deployment/shared-and-tuning.md) |
| Isolated LangChain MCP and cooperative trace inspection | `shared/langchain_mcp/`, `tuning/langchain_mcp_agent/` | `.langchain-pilot/runtime/mcp-client/`, `.langchain-pilot/runtime/mcp-agent/` | [LangChain MCP](deployment/langchain-mcp.md) |
| Mentor validation/tuning | `mentor/`, `tuning/` | component runtime directories | [Shared and tuning](deployment/shared-and-tuning.md) |
| Provider-free Storage Governance registry, bounded metadata auditor and advisory planner | `shared/storage_governance/` | optional private reports in `.job-runtime/storage-governance/`; registered stores remain owned by their components | [Storage governance](deployment/storage-governance.md) |
| Information Yield v5 frozen-disabled provider-free candidate | Lane A `shared/research_sources/information_yield_v5_contracts.py` and `tuning/evals/information_fetch/information_yield/`; Lane B `investment/research/information_yield_projection_v5.py` and `ui/datasource/` | fixed non-portable root `tuning/runtime/information-yield-v5` (currently absent); no private state is portable | [Shared and tuning](deployment/shared-and-tuning.md), [Datasource](deployment/datasource.md), [acquisition E2E](deployment/acquisition-live-e2e.md) |
| Mentor scheduled work orders, read-only scheduler projection and pure disabled two-slot resilience candidate | `mentor/scheduler/`, `ui/datasource/src/scheduler-resilience-mvp/` | ignored mentor/session runtime plus existing `.job-runtime/` acceptance/reconciliation evidence; candidate remains `enabled:false` | [Mentor scheduler](deployment/mentor-scheduler.md), [scheduler UI](deployment/scheduler-ui.md) |
| Local datasource UI and temporal runtime inspection | `ui/datasource/`, `investment/research/datasource*.py` | Existing private research roots and `ui/runtime/` | [Datasource](deployment/datasource.md) |
| UI guidance and isolated React/browser verification | `ui/` | `ui/runtime/` | [Frontend](deployment/frontend.md) |
| Claude CLI skill discovery, explicit dollar aliases and nonblocking mentor startup (receipt gates reverted) | `shared/claude_skills/`, `mentor/session_init.py`, disabled `mentor/mentor_guard.py` and `mentor/enforcement-lock.json`, `CLAUDE.md`, `.claude/settings.json`, `.claude/skills/` | Ignored mentor rollback copies/session state plus scratch tests; authorized user skill links and one user prompt-alias hook | [Claude skills](deployment/claude-skills.md) |
| Factor-mining source pins, synthetic PIT identities, frozen-disabled GCP architecture/provider contracts, apply-disabled activation/IaC, immutable manifests and read-only observability | `factor/`, `tuning/factor_mining/`, `shared/factor_mining/`, `investment/factor_mining/rdagent_adapter/`, `ui/datasource/src/factorMining/` | `factor/runtime/`, component runtime test roots and existing `ui/runtime/`; future Google account resources remain external/unprovisioned | [Factor mining](deployment/factor-mining.md) |

UI skills also have repository discovery links and a compact SessionStart
definition parallel to mentor startup. Source/protocol checks pass, while actual
automatic UI hook execution remains unverified pending supported trust review
and the required scheduled-runtime/email acceptance. See the frontend runbook;
do not treat a definition, direct script test or discovered skill as execution.

The private archive is not mutable runtime state. Root `.codex/config.toml` is
workspace-wide: currently live web search only. MCP candidates remain inactive;
follow [MCP stability](mcp-stability.md). Do not copy private state as a deployment bundle.

Mentor startup uses the separate `.codex/hooks.json` and six repository-local
skill discovery links. Review the SessionStart definition through `/hooks` once
on each local host, then verify a fresh initialization marker. The router loads
with the mentor policy; missing or failed initialization must be disclosed. See
the [startup runbook](deployment/shared-and-tuning.md#mentor-startup-and-selective-skill-discovery)
for activation limits and repeatable checks.

The options adapters are disabled candidates in the shared market-data portal:
Market Data's no-key AAPL demo and the keyed Alpaca/Massive scopes have passed
isolated live checks. Reprovision keys on another device through hidden local
prompts. Scheduled Codex/email acceptance remains unverified. No paid feed fallback
or active market MCP registration is supplied. See the shared runbook for exact
data delays, bounded scopes and deployment status.

## Provider-free Storage Governance setup

Storage Governance uses only the Python standard library and adds no provider,
daemon, database service, queue, workflow engine or credential. The source and
registry are current; the audit CLI is inert until invoked. It retains one
`WorkspaceSnapshot` from registry read through every scan and CLI publication,
using descriptor-relative no-follow operations and retarget detection. Report
publication accepts an owner-controlled, non-group/world-writable workspace
(including `0755`); `.job-runtime` and `.job-runtime/storage-governance/` must be
owner-owned exact-`0700`, and the report is `0600`. Cleanup closes every held
descriptor while preserving an earlier primary error.

The quarantined registry declares 16 stores: 10 current workspace stores, one
planned non-authoritative factor registry, four unverified workspace stores, and
one unverified external agent-memory reference. The workspace-unverified set is
`evaluation-evidence`, `investment-research-evidence`, `ui-artifacts`, and the
mixed `ui/runtime` evidence/cache/projection store; all use manual-review
retention. Both `.market-data-mcp/credentials` and the legacy
`.market-data-mcp/credentials.json` are registered credential roots. These are
metadata declarations, not proof of existence, completeness, safety, or audit.

A historical private report exists at
`.job-runtime/storage-governance/audit-20261112.json`, mode `0600`, with SHA-256
`ba8b760b8bc1233d06ca10c8fc8c7d90e0bbd56c0a8b5a8a7299331cbce50907`; its
planner recorded `performed: false`. It is pre-quarantine evidence. This
documentation task ran no new audit, created no report, and performed no
permission, retention, move, or delete action. Do not copy runtime state between
devices.

From the workspace root, validate the registry and run its focused tests:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -c \
  'from pathlib import Path; from shared.storage_governance import load_registry; root=Path.cwd(); load_registry(root / "shared/storage_governance/registry.json", root)'
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s shared/storage_governance/tests -p 'test_*.py' -v
```

Do not create an audit report as an installation probe. If an owner separately
authorizes a real metadata audit, use the bounded CLI in the runbook. It performs
depth-first no-follow metadata traversal, checks owner and exact declared
generated-file modes, and includes exact SQLite `-journal`, `-wal` and `-shm`
sidecar metadata without reading contents. Trigger evaluability is
metric-specific: boolean existence when known, truncation on inspected snapshots,
positive symlink/permission findings even when incomplete, and negative
symlink/permission plus count/bytes only when inspection is complete. External and
workspace-unverified stores are uninspected and not evaluable. The planner routes
`manual_review` retention and every non-current status to manual review. Registry
screening includes finite `gho_`, `AIza`, and `xapp-` patterns as defense in depth,
not exhaustive detection; never put credential values into registry metadata.
Preserve the zero-delete boundary.

Do not bulk-normalize historical permissions. For each quarantined store, its
owner must privately inventory exact affected entries, classify evidence versus
explicitly public-safe artifacts, and require future private writers to create
`0600` files and `0700` directories. A migration remains disabled until a private
backup and manifest, finite dry run, bounded canary, exact mode/content-identity
readback, rollback drill, unknown-outcome reconciliation, and owner review pass.
Recovery keeps the original and backup until acceptance; any failed readback or
rollback leaves the store `unverified` with `manual_review` retention. See the
[evidence-permission quarantine plan](plans/storage-governance-evidence-permissions.md).
No automatic remediation is configured.

Future-writer hardening is source-implemented without changing the quarantine:

- `.job-runtime/evaluations/...` model targets, after absolute normalization,
  fail before launch with `MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE`.
  Generic non-evaluation model runs still lack strict detached-descendant
  containment; child umask, parent `fchmod` and held-FD output checks do not
  remove that residual risk.
- Research artifact writes use descriptor-bound exact-`0700` directories and
  `0600` temp/content/pointer files, reject permissive existing CAS entries,
  fence post-effect durability failures as `PublicationOutcomeUnknown`, buffer
  producer output, and revalidate source coverage at completion. New-primary
  SQLite mode is covered; existing databases and sidecars are not.
- `ui/artifacts/` stays ignored confidential history. Its observed real root is
  `0755`, so the create-only publisher fails closed by default. It accepts only
  new `ui/artifacts/future-private-v1/...` destinations from bounded stdin or a
  stable exact-`0600` staging file. Unknown post-link outcomes require
  reconciliation; CLI output omits hash/size, and public publication is absent.
  The root ignore fence is `.gitignore`; do not negate it for the private
  namespace.

Run the focused future-writer checks without invoking the storage audit:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  shared.job_runtime.tests.test_model
PYTHONDONTWRITEBYTECODE=1 .research-sources/.venv/bin/python -B -m unittest -v \
  shared.research_sources.tests.test_artifacts \
  investment.research.tests.test_sources
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  ui.tests.test_private_artifacts
```

These checks prove local/provider-free contracts only. They do not make any
store current, migrate history, or satisfy future-triggered scheduled/email
runtime acceptance.

SQLite remains the local choice while operation is single-host with serialized
writes. PostgreSQL, object storage, a queue and a durable workflow engine are
migration options only after the measured triggers in the runbook. None is a
current setup prerequisite.

## Shared scheduler bootstrap on another Mac

Temporary acquisition A/B review continuation uses the separate
[six-hour review/capture runbook](deployment/review-campaign.md), existing research
Python environment and existing model/auth owner. It requires explicit finite
schedule activation and new future-session acceptance; it is not automatically
enabled by installing the shared scheduler.

Prerequisites: private checkout, installed and authenticated Codex CLI, Python 3
for bootstrapping, and an interactive macOS login. Linux/systemd and Windows
host installers are not implemented. From the workspace root:

```sh
mkdir -p .job-runtime/tmp .job-runtime/cache .job-runtime/bin
chmod 700 .job-runtime
python3 -m venv .job-runtime/bootstrap
TMPDIR="$PWD/.job-runtime/tmp" PIP_CACHE_DIR="$PWD/.job-runtime/cache/pip" \
  .job-runtime/bootstrap/bin/python -m pip install --no-cache-dir \
  -r shared/job_runtime/bootstrap-requirements.txt
UV_CACHE_DIR="$PWD/.job-runtime/cache/uv" \
UV_PYTHON_INSTALL_DIR="$PWD/.job-runtime/python" \
UV_PYTHON_BIN_DIR="$PWD/.job-runtime/bin" TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/bootstrap/bin/uv python install 3.12.16
UV_CACHE_DIR="$PWD/.job-runtime/cache/uv" \
UV_PYTHON_INSTALL_DIR="$PWD/.job-runtime/python" \
UV_PYTHON_BIN_DIR="$PWD/.job-runtime/bin" TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/bootstrap/bin/uv venv --python 3.12 .job-runtime/.venv
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 \
  .job-runtime/.venv/bin/python -m shared.job_runtime.setup \
  --workspace "$PWD" --codex-bin "$(command -v codex)" \
  --auth-source "$HOME/.codex/auth.json"
```

This prepares an empty allocation and reads the explicitly selected auth source
once, without printing it. Prefer a fresh supported login on another device;
never synchronize active rotating auth caches. Existing private config/auth is
preserved on repeat preparation. Add reviewed allocation paths and declared
source paths to `.job-runtime/config/runtime.json`. Niulai additionally requires
its job-local environment and private policy; it is not an infrastructure dependency.

Models, concurrency, retry and timeout policy belong to infrastructure. A job
declares its schedule, prompt and adapter and selects a model profile. The
`.job-runtime/test-venv` below is test-only and is never referenced by generated
launchd service arguments; `jsonschema` remains outside the production scheduler
dependency set. Validate:

```sh
UV_CACHE_DIR="$PWD/.job-runtime/cache/uv" \
UV_PYTHON_INSTALL_DIR="$PWD/.job-runtime/python" \
UV_PYTHON_BIN_DIR="$PWD/.job-runtime/bin" TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/bootstrap/bin/uv venv --python 3.12 .job-runtime/test-venv
UV_CACHE_DIR="$PWD/.job-runtime/cache/uv" TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/bootstrap/bin/uv pip install \
  --python .job-runtime/test-venv/bin/python \
  -r shared/job_runtime/test-requirements.txt
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/test-venv/bin/python -m unittest discover -s shared/job_runtime/tests -v
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/.venv/bin/python -m shared.job_runtime.host generate \
  --workspace "$PWD" --config "$PWD/.job-runtime/config/runtime.json"
```

Use `install-session` for this login. After explicit authorization for the two
outside-workspace links, `install-persistent` creates links in
`~/Library/LaunchAgents`. Other generated files remain local. Regenerate paths on
every device or workspace move; unload a previous checkout first because service
labels are per-user and static. See the runbook for start/status/reload/removal.

The service prevents idle sleep while active. Shutdown, logout, forced/lid sleep,
network loss, revoked auth and provider outages remain execution limits. Inspect
actual receipts; a requested model name is not an independently reported backend
identity. A scheduled readiness proof is not proof of automatic business delivery.

## Required setup-change workflow

Major runtime changes also require the
[scheduled Codex acceptance and email contract](deployment/runtime-acceptance.md).
Record actual evidence for the changed version; setup-doc consistency alone does
not establish runtime acceptance. All agents must carry this rule into handoffs.

1. Update source/configuration and this guide or the linked component runbook.
2. Update `deployment/setup-inventory.json` when prerequisites, paths, activation
   status, versions or recovery change. Never add private values.
3. Run `python3 shared/setup_audit.py --refresh`, then `--check`.

The gate fingerprints declared setup-sensitive source and documentation. It
rejects changed setup source without a documentation update. It does not inspect
private state or prove deployment on devices not actually tested.

The mentor now includes the local `development-discipline` procedure and a matched
decision-quality/routing-cost screen. It uses repository instructions and an
offline artifact gate; it does not install a background enforcer. See the mentor
section of [Shared and tuning](deployment/shared-and-tuning.md) for local paths,
optional tokenizer requirements, reproduction and evidence limits.

The preparation helper creates configuration/allocation files with exclusive
creation and never overwrites an existing login or policy during concurrent or
repeated preparation. `auth_present` is file presence, not a live login check.

The [2026-11-02 UI skill expansion](../ui/tests/expansion-report.md) records the
22-entrypoint catalog, selective resolver, independent browser checks and external
Pencil/extension/runtime acceptance limits. Follow the frontend runbook for paths
and reproduction; no global skill or browser installation is required.

The optional native EgoLite skill transport and its closed host capability are
covered in [browser runtime deployment](deployment/web-access.md). It requires
real `/skills` activation; direct CLI probes alone do not accept it. The candidate
uses an isolated temporary common-Engine allocation and leaves recurring jobs
unchanged until their own integration/acceptance.

The [datasource runbook](deployment/datasource.md#registered-controlled-native-acquisition-comparisons) also documents bounded registered native-comparison projection and its separate quality, lineage and availability denominators. It uses the existing local dependencies and read-only API. Its [provider-free acquisition rehearsal](deployment/datasource.md#provider-free-acquisition-driver-trace-rehearsal) uses the same pinned `.research-sources/.venv`, workspace-local private roots and injected counting fake; it installs no provider SDK and makes no network call. The [Codex/Claude hosted-session contract](deployment/datasource.md#codex-and-claude-code-hosted-live-session-entrypoints) reuses that environment and adds no Anthropic SDK or MCP: each host cooperatively invokes its own installed web tool and returns one exact bounded JSON result. Seal separate host profiles, opaque credential-readiness receipts, execution IDs and non-overlapping artifact/cache roots. Actual runner roots must remain non-symlinked and private. Preserve an ambiguous dispatch journal for reconciliation rather than deleting or replaying it.

The [Harry UI session wrapper](../ui/tests/harry-ui-session-report.md) is the
authorized user-scope exception for cross-repository UI guidance. Its portable
build, exclusive publication and owned rollback are in the frontend runbook.
Generated portable distributions remain ignored and are rebuilt from source.
Intent/token evaluation precedes publication. Activation is once per native
conversation. The [runtime persistence repair](../ui/portable/runtime_verification/report.md)
adds private target-local thread receipts, restore-before-routing and explicit
disable/re-enable behavior across compaction and resume. Implicit discovery is
enabled without auto-enabling a fresh thread. Owned atomic upgrades retain exact
rollback payloads; no global settings or hooks are changed. Fresh scheduled
v3 execution passed10/10 tasks with actual compaction/resume and independent
raw-evidence/cleanup verification and exact configured-owner email readback. The original
and strict-v2 failures remain preserved; automatic repository hooks are separate
and still unverified.

The [local scheduler dashboard](deployment/scheduler-ui.md) is available at
`http://localhost:7270/scheduler` in the existing datasource app. It projects
registered jobs, per-job schedules/next sends, stored instructions, history and
policy-bound production messages. Its fixed mentor provider instead exposes only
an exact bounded status union and suppresses prompts, generic history, outputs and
private acceptance evidence. The completed grouped mentor UI covers work order and
window, scheduler/dispatch, session, every progress limit, safeguards and replay
authorization, six acceptance gates, evaluation/overfitting controls, runtime
acceptance/email and the recovery timeline. Exact unavailable inner evidence stays
distinct from a valid outer partial scheduler response.

It reuses existing private ledgers in read-only mode; it adds no job execution,
reconciliation, replay authorization or email transport and does not copy private
runtime state into source. Final checks passed28/28 Python,10/10 Node, datasource
typecheck, a98-module production build and12/12 scheduler browser cases. The guarded
live pass made31 allowed read-only requests with zero writes, blocked/non-loopback/
unknown API or output requests and page errors; nine static private files were
byte-equal and24 recent UI artifacts had zero credential-category matches. The
current mentor acceptance nevertheless remains failed and operator-reconciled as
`definitely_not_dispatched`; email is pending and no replay is authorized. These UI
results do not establish dispatch repair, email delivery or runtime acceptance.

The [optional personal Claude/Ferry setup](deployment/claude-ferry.md) records the
explicitly requested user settings merge and catalog verification. It is separate
from the Codex scheduler and is not an automatic project setup requirement.

The [optional Codex route split](deployment/codex-ferry.md) uses native OpenAI
defaults and an explicit `codex --profile ferry` opt-in. It adds no proxy or daemon;
Ferry's catalog override belongs to that profile. Existing sessions can retain
their selected provider. The [isolated LangChain pilot](deployment/langchain-pilot.md)
keeps dependencies and dev-server state local. Its default session engine accepts
model replies from an explicitly configured chat session; LangChain owns tools,
workflow state and result checks. Cooperative calculator E2Es returned `"10"` and
`"15"` with one tool call. No API key, Ferry route or copied login token is needed
for this mode, and no automatic session wake-up/dispatcher is provided. A later
session can rebind and continue the same graph thread through the public CLI.
The optional official OpenAI API engine separately requires `OPENAI_API_KEY` or
the ignored owner-private `.langchain-pilot/.env`; its live pass is unverified.
The Agent Server uses `127.0.0.1:2024`, separate from dashboard port 7270. Native
Chrome Studio connection/graph visibility were verified, with cloud tracing
disabled. Commit `989149d` passed the graceful restart canary, preserving eight
prior threads and returning `"15"` with one tool call and independent readback.
The current additive observability candidate passed 51 provider-free controls. Full agent migration,
unattended execution, actual second-host handoff and scheduled production/email
acceptance remain unverified. See the [incremental migration plan](plans/langchain-agent-migration.md).

The pilot also provides a separate opt-in [LangSmith atomic prerequisite canary](deployment/langchain-pilot.md#opt-in-langsmith-prerequisite-canary).
It explicitly pins the already-locked LangSmith SDK 0.14.17 and reads only the
owner-private, ignored `.langchain-pilot/langsmith.env` for platform authentication.
It does not enable tracing on the running Agent Server. It uses public synthetic
calculator cases, a pinned private prompt and a deterministic code evaluator;
model calls, actual holdings and the full research pipeline remain separate gates.
Keep keys and cloud/runtime receipts out of source control. Preserve unknown
attempts and reconcile their recorded identities before rerunning effects.

The [Harry UI and mentor installation handoff](handoffs/skills-installation-20261104.md)
records scope, entrypoints, session behavior, provenance, measured limits and
safe verification/rebuild procedures for another agent or device.

## Frozen-disabled Information Yield v5 setup boundary

O0 remains active and default. Rejected v3/v4 generations are not upgraded or used
as fallback. The additive v5 family is provider-free and disabled: the
`INFORMATION_YIELD_V5_ENABLED` flag is off, no locator has separate approval, and
`tuning/runtime/information-yield-v5` must remain absent during setup sync. The
flag or a locator/reference alone is never authorization. See the linked shared,
datasource and acquisition runbooks for the exact fixed-root, custody, retention
and rollback contracts.

The scheduler resilience addition is likewise a pure, finite, two-slot candidate
with `enabled:false`. Its builder/preflight and read-only `mentor.resilience`
projection add no materializer or scheduler registration. There is no database migration,
provider call, network, email or business effect. Runtime `spec_sha256` enforcement,
host-freshness review, explicit activation and future runtime acceptance remain
blockers.
