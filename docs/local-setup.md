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
| Shared wake/scheduling/models/retries | `shared/job_runtime/` | `.job-runtime/` | [Job runtime](deployment/job-runtime.md) |
| Copied calculation candidate (inactive) | `shared/calculation/` | `.job-runtime/calculation/` | [Calculations](deployment/calculation.md) |
| Investment evidence requirements and coverage | `investment/research/` | `.niulai-state/reports/investment-research/` | [Investment source contract](../investment/research/README.md) |
| Research-source acquisition | `shared/research_sources/` | `.research-sources/`, `.niulai-state/reports/research-sources/` | [Source tools](../shared/research_sources/README.md) |
| Optional Jev source labeling and development evaluation | `shared/typed_judge/`, `investment/research/source_labeler.py`, `tuning/evals/label_accuracy/` | Existing private research roots, `.job-runtime/credentials/` and acceptance records | [Jev setup and recovery](deployment/jev-labeling.md) |
| Native search + EgoLite candidate (disabled) | `shared/web_access/`, `tuning/evals/browser_cooperation/` | `.research-sources/web-access/` | [Browser cooperation](deployment/web-access.md) |
| Niulai admission/report/email adapters | `niulai-runtime/`, preserved `niulai/` | `.niulai-state/` | [Niulai](deployment/niulai.md) |
| Shared Tiger credentials/query gateway | `shared/tiger/`, shared MCP portal | `.niulai-state/` | [Tiger gateway](../shared/tiger/README.md) |
| Market-data adapters | `shared/market_data_mcp/` | `.market-data-mcp/` | [Shared and tuning](deployment/shared-and-tuning.md) |
| Mentor validation/tuning | `mentor/`, `tuning/` | component runtime directories | [Shared and tuning](deployment/shared-and-tuning.md) |
| Local datasource UI and temporal runtime inspection | `ui/datasource/`, `investment/research/datasource*.py` | Existing private research roots and `ui/runtime/` | [Datasource](deployment/datasource.md) |
| UI guidance and isolated React/browser verification | `ui/` | `ui/runtime/` | [Frontend](deployment/frontend.md) |

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
declares its schedule, prompt and adapter and selects a model profile. Validate:

```sh
PYTHONPATH="$PWD" PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/.venv/bin/python -m unittest discover -s shared/job_runtime/tests -v
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

The [datasource runbook](deployment/datasource.md#registered-controlled-native-acquisition-comparisons) also documents bounded registered native-comparison projection and its separate quality, lineage and availability denominators. It uses the existing local dependencies and read-only API.

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
