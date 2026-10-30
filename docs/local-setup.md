# Local deployment source of truth

Update this guide or its linked runbooks in the same change as any installation,
dependency, configuration, runtime-path, credential-handling or recovery change.
Keep private values out of documentation and the sanitized inventory.

| Component | Source | Private state | Runbook |
| --- | --- | --- | --- |
| Shared wake/scheduling/models/retries | `shared/job_runtime/` | `.job-runtime/` | [Job runtime](deployment/job-runtime.md) |
| Investment evidence requirements and coverage | `investment/research/` | `.niulai-state/reports/investment-research/` | [Investment source contract](../investment/research/README.md) |
| Research-source acquisition | `shared/research_sources/` | `.research-sources/`, `.niulai-state/reports/research-sources/` | [Source tools](../shared/research_sources/README.md) |
| Niulai admission/report/email adapters | `niulai-runtime/`, preserved `niulai/` | `.niulai-state/` | [Niulai](deployment/niulai.md) |
| Shared Tiger credentials/query gateway | `shared/tiger/`, shared MCP portal | `.niulai-state/` | [Tiger gateway](../shared/tiger/README.md) |
| Market-data adapters | `shared/market_data_mcp/` | `.market-data-mcp/` | [Shared and tuning](deployment/shared-and-tuning.md) |
| Mentor validation/tuning | `mentor/`, `tuning/` | component runtime directories | [Shared and tuning](deployment/shared-and-tuning.md) |
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
