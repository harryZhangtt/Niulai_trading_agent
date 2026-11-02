# Deploy the shared Codex job runtime

Optional temporary implementation work uses the separately scoped
[development campaign](development-campaign.md). It has its own state and
expiring launchd label; it does not modify the primary job allocations.

Major runtime changes are subject to the shared
[scheduled Codex acceptance and email contract](runtime-acceptance.md): exercise
the changed capability in an actual scheduled session, retain version-specific
evidence, and verify the owner's result email before acceptance claims.

Use this runbook with [the local setup inventory](../local-setup.md). Source
belongs in Git; authentication, absolute device paths, databases and generated
service files belong under the checkout's Git-ignored `.job-runtime/`. Do not
copy that private directory into a repository or treat one device's configuration
as portable credentials for another device.

Any future setup change must update this runbook and the local setup inventory
in the same change. Include the changed dependency or setting, the installation
command, verification evidence, recovery procedure and any remaining limitation.
If code and documentation disagree, verify the deployed source and correct the
documentation before calling deployment complete.

## Architecture and ownership

| Layer | Source | Responsibility |
| --- | --- | --- |
| macOS host | `shared/job_runtime/host.py` | Generate/load launchd definitions, watchdog and lifecycle commands |
| Supervisor | `shared/job_runtime/service.py` | Single service owner, heartbeats, safe allocation reload, cancellation |
| Scheduling engine | `shared/job_runtime/engine.py` | Durable due slots, claims, bounded concurrency and retries |
| Model adapter | `shared/job_runtime/model.py` | One explicit Codex invocation, timeout, receipt parsing and cleanup |
| Job allocation | For example `niulai-runtime/jobs/daily-readiness.json` | Job identity, cadence, prompt and business adapter reference |
| Business adapter | For example `niulai_runtime.job_adapter` | Component-specific admission and side-effect policy |

The infrastructure does not contain Niulai report, broker or email logic. A job
cannot override central retry policy, choose another credential resource group,
or enable a fallback model. The supervisor derives resource groups from the
configured model authentication homes. Jobs sharing one home queue sequentially
without consuming retry attempts while waiting; independent groups can use the
remaining worker capacity.

The current Niulai allocation is **read-only readiness at 13:00 and 19:00
America/New_York**, with a one-hour grace window and Niulai's real XNYS admission
check. Its model prompt cannot collect prices, refresh Tiger, send email or trade.
The original cloud email sender remains a separate production owner until its
explicit cutover. Installing this runtime does not migrate that sender.

## Device prerequisites

- macOS with a logged-in user session, `launchctl` and `/usr/bin/caffeinate`.
- A local checkout that remains at a stable path while registered services run.
- Python 3.12 and a project-local runtime environment. Use the local setup
  inventory's workspace-contained Python installer if Python is not available.
- A supported Codex CLI installation and a model the account can actually run.
  Record its executable path and version on the new device; do not copy another
  device's absolute path blindly.
- Network access and valid Codex authentication. Network/proxy/TLS configuration
  is an existing device prerequisite, not something this installer changes.

The generic engine, host and model adapter use Python's standard library. Niulai's
XNYS gate runs in a separate job-local Python subprocess, declared in that job's
`adapter_config.python`, with a 30-second timeout. It uses the compatible
exchange-calendar environment under `.niulai-state/`; its dependencies do not
need to be installed into `.job-runtime/.venv`. Follow the local setup inventory
for that job's environment and policy before enabling the allocation. The
adapter rejects an escaping executable path instead of selecting another
Python from the system PATH.

Initialize private directories from the checkout root:

```sh
umask 077
mkdir -p .job-runtime/config .job-runtime/logs .job-runtime/tmp \
  .job-runtime/cache .job-runtime/runs .job-runtime/codex-home
chmod 700 .job-runtime .job-runtime/config .job-runtime/logs \
  .job-runtime/tmp .job-runtime/cache .job-runtime/runs \
  .job-runtime/codex-home
TMPDIR="$PWD/.job-runtime/tmp" python3.12 -m venv .job-runtime/.venv
```

Keep any installer caches and temporary files local, for example
`TMPDIR="$PWD/.job-runtime/tmp"` and
`PIP_CACHE_DIR="$PWD/.job-runtime/cache/pip"`. The shared runtime's Python
executable is declared through the private infrastructure configuration's
`python_bin`; use `.job-runtime/.venv/bin/python`, independently of a Niulai
environment. Recreate environments on a new device; virtual environments and
generated plists are not portable source artifacts.

## Authentication and explicit model policy

The model profile contains `codex_bin`, `model`, `effort`, `timeout_seconds` and
`auth_home`. The operational default is explicitly `gpt-6.1-sol`, low effort and
a 120-second deadline. This is a selected profile, not a promise that every
account has access. Confirm access with a bounded real invocation before enabling
recurring work. A model unavailable to the account fails; no silent fallback is
selected.

Provision the workspace-owned Codex home through a supported login:

```sh
CODEX_HOME="$PWD/.job-runtime/codex-home" codex login
CODEX_HOME="$PWD/.job-runtime/codex-home" codex login status
```

A separately authorized one-time secure seed of an existing login is another
setup operation, not a scheduler fallback. Never print authentication files,
paste tokens into prompts, or copy a live rotating cache to multiple active
devices. Each deployed device must own and refresh its actual supported login.
The adapter refuses a missing or unsafe local auth file; it never falls back to
the user's global auth cache or global configuration. Keep directories 0700 and
private configuration/authentication files 0600.

The adapter uses `codex exec` with an explicit model, read-only sandbox,
ephemeral session, isolated paths and disabled command/app/web tools. It checks
the event stream for a real completed turn and final output. Exit zero or a
model's claim that it finished is insufficient. `requested_model` records the
enforced selection; `observed_model` remains unknown unless the CLI actually
emits it. See [the model adapter contract](../../shared/job_runtime/docs/model.md).

## Infrastructure configuration and job allocation

Create `.job-runtime/config/runtime.json` as an owner-private file. It contains
the schema version, declared Python executable, tick/heartbeat/watchdog periods,
worker limit, central retries, model profiles, allocation files and local source
paths. Resolve device paths from the checkout root when constructing the file;
JSON does not expand `$PWD`, `~` or shell variables for you.

Current operational values are a five-second scheduler tick, five-second
heartbeat, 90-second stale heartbeat threshold, two workers and at most three
attempts. Backoff starts at 30 seconds and is capped at 120 seconds. These belong
to infrastructure configuration, not individual job allocations.

For a new device, the following is a non-secret configuration template. Replace
every `/absolute/path/` placeholder with that device's verified path before
saving it as `.job-runtime/config/runtime.json` with mode 0600. The example uses
a disabled generic probe rather than requiring any Niulai account state:

```json
{
  "schema_version": 1,
  "python_bin": "/absolute/path/to/checkout/.job-runtime/.venv/bin/python",
  "tick_seconds": 5,
  "heartbeat_seconds": 5,
  "stale_seconds": 90,
  "max_workers": 2,
  "retry": {"max_attempts": 3, "backoff_seconds": 30, "max_backoff_seconds": 120},
  "model_profiles": {
    "default": {
      "codex_bin": "/absolute/path/to/codex",
      "model": "gpt-6.1-sol",
      "effort": "low",
      "timeout_seconds": 120,
      "auth_home": "/absolute/path/to/checkout/.job-runtime/codex-home"
    }
  },
  "allocation_files": [".job-runtime/config/jobs.json"],
  "source_paths": []
}
```

Save this companion allocation as `.job-runtime/config/jobs.json`, also 0600:

```json
{
  "schema_version": 1,
  "jobs": [{
    "id": "deployment.readiness.v1",
    "enabled": false,
    "schedule": {"kind": "interval", "seconds": 300, "grace_seconds": 300},
    "replay_safe": true,
    "model_profile": "default",
    "prompt_file": "shared/job_runtime/probe-prompt.txt"
  }]
}
```

Validate authentication and a manual transport probe first, then enable one
bounded future `once` probe for actual scheduler acceptance. Do not leave test
allocations continuously enabled unless that recurrence is intended. Add the
Niulai allocation and its source path only after its separate job-local gate
environment and private policy are ready.

Allocation files have `schema_version: 1` and a `jobs` array. Each job declares:

- A stable `id`, `enabled` flag and explicit `replay_safe` value.
- `model_profile`, referencing an existing centrally configured profile.
- A workspace-relative `prompt_file`.
- A schedule: `daily` with IANA timezone, `times` and `grace_seconds`; `interval`
  with `seconds` and optional grace; or `once` with an aware ISO `at` and grace.
- An optional workspace-source `adapter` and its component-specific
  `adapter_config`.

Private job policies may reference `.niulai-state/` or another component's own
private state, but must exist and pass that adapter's checks before enablement.
An adapter source path is validated before import. Unknown job fields, duplicate
JSON keys, escaping paths and unsafe private configuration permissions fail closed.
Niulai's readiness adapter declares `policy`, `actor` and
`python: ".niulai-state/.venv/bin/python"` separately from the infrastructure
`python_bin`. Its subprocess receives workspace-local temporary paths and no
permission to send email.

Schedule edits with an existing job ID are deliberately rejected by the engine.
Treat a change in cadence or job identity as a migration: disable/reconcile the
old allocation and its delivery records first. A new scheduler ID alone is not
authorization to repeat a business email or complete an old production slot.

## Install and verify

Run these commands from the checkout root. They retain generated files under
`.job-runtime/`; `install-session` registers them with the current user's GUI
launchd domain without adding filesystem entries outside the workspace.

```sh
PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/.venv/bin/python -m shared.job_runtime.host generate \
  --workspace "$PWD" --config "$PWD/.job-runtime/config/runtime.json"

PYTHONDONTWRITEBYTECODE=1 TMPDIR="$PWD/.job-runtime/tmp" \
  .job-runtime/.venv/bin/python -m shared.job_runtime.host install-session \
  --workspace "$PWD" --config "$PWD/.job-runtime/config/runtime.json"

PYTHONDONTWRITEBYTECODE=1 .job-runtime/.venv/bin/python \
  -m shared.job_runtime.host status --workspace "$PWD" \
  --config "$PWD/.job-runtime/config/runtime.json"
```

Registration is one acceptance item. Also verify fresh `heartbeat.json`,
`status.json` and `watchdog.json`, then observe a future one-time model probe
actually execute from the service. Preserve its scheduled/start/completion times,
attempt ID and parsed transport receipt privately. A manually run model command
does not prove scheduled awakening.

For restart-at-login persistence, the only installer-created external filesystem
entries are these two symlinks under the current user's `~/Library/LaunchAgents`:

```text
com.local.trading-agent.job-runtime.plist
com.local.trading-agent.job-runtime.watchdog.plist
```

They point to the corresponding generated plists inside this checkout. This
workspace-boundary exception must be explicitly authorized before running:

```sh
PYTHONDONTWRITEBYTECODE=1 .job-runtime/.venv/bin/python \
  -m shared.job_runtime.host install-persistent --workspace "$PWD" \
  --config "$PWD/.job-runtime/config/runtime.json"
```

The installer refuses conflicting files. The label is currently shared per user,
so use one active workspace deployment for that user. Unload an old checkout
before deploying another; do not assume an already registered label uses the new
checkout. Regenerate plists after moving the workspace, changing the Python path,
or deploying on a different device. Their absolute paths and captured environment
belong to that device.

## Wake and recovery semantics

launchd starts the service at load and keeps it alive. The service holds its own
exclusive lock. A separate watchdog runs every 60 seconds and checks registration,
heartbeats, startup grace and a conservative batch-duration limit. It can request
graceful termination of a stale service; launchd then restarts it. It does not
replay uncertain business actions.

`caffeinate -i` keeps the logged-in Mac from idle sleeping while the service is
running. It does not power on a shut-down Mac, bypass closed-lid sleep, maintain a
logged-out GUI session or guarantee network/provider availability. It creates a
live power assertion rather than changing `pmset` or global power settings.
The Codex app window need not stay open because the service invokes the CLI.

The durable engine records each due slot and attempt before dispatch. Interval
outages coalesce old intervals instead of flooding the model. Daily jobs retain
their wall-clock timezone across DST; nonexistent local times are recorded as
missed and ambiguous wall-clock times run once. A due slot outside grace is
missed, never silently completed. The business adapter still owns exchange
holidays and any permitted retrospective/catch-up policy.

Known transient model/provider errors can retry only for a replay-safe job,
within the central attempt/deadline limits. Authentication, unsupported model and
configuration failures are permanent operational failures. Timeouts, cancellation,
invalid receipts and process death can leave `unknown`; they are not automatically
resent. On restart, old running attempts become unknown after supervisor ownership
is established. Reconcile exact process/transport evidence before manually
resolving them. Do not delete `schedule.sqlite` or credential locks to force a retry.

## Change, reload and remove

Validate source/tests and private configuration before loading a change. Reload
configuration and allocations between ticks with:

```sh
PYTHONDONTWRITEBYTECODE=1 .job-runtime/.venv/bin/python \
  -m shared.job_runtime.host reload --workspace "$PWD" \
  --config "$PWD/.job-runtime/config/runtime.json"
```

An accepted signal is not proof that a reload passed. Inspect the next status
update and actual affected job run. Running attempts keep their original inputs.
Adapter imports must resolve to exactly one source within the workspace or its
declared `source_paths`; the imported file must match that expected origin.
Ambiguous, external or already-loaded mismatched modules fail admission. Changing
module origins can require a controlled restart because reload does not unload
Python modules already in memory.
A change to host Python, plist paths or captured environment needs regenerated
plists and a controlled unload/reinstall, not only SIGHUP. Preserve the database
and unfinished-attempt evidence during that operation.

Stop both session services:

```sh
PYTHONDONTWRITEBYTECODE=1 .job-runtime/.venv/bin/python \
  -m shared.job_runtime.host uninstall-session --workspace "$PWD" \
  --config "$PWD/.job-runtime/config/runtime.json"
```

This command does **not** remove login symlinks. Under the same explicit external
filesystem authorization, remove only links whose resolved targets are exactly
the matching files under this checkout's `.job-runtime/launchd/`. Preserve any
other user's or application's files. Then verify both launchd labels are absent.
Keep private run evidence until reconciliation and retention requirements are met.

## Operational evidence and portability limits

Source tests are under `shared/job_runtime/tests/`. Keep test temporary files,
logs, Python caches and captured model output within `.job-runtime/`. The private
engine database is `.job-runtime/engine/schedule.sqlite`; model attempts live under
`.job-runtime/runs/`; host logs and heartbeat/status files are separate.

For every deployment, record Python/Codex versions, configured model/effort,
registered label paths, effective service PID, fresh heartbeat/watchdog status,
one actual scheduled model completion and any restart recovery result. Record
unverified items explicitly. No local test certifies perpetual on-time service.

The scheduling/model interfaces can be reused, while `host.py` is a macOS host
adapter and the current executor/supervisor use POSIX file locks and process-group
signals. Another operating system needs an equivalent supervised service,
wake/availability strategy and lifecycle test; Windows also needs replacements
for those POSIX mechanisms. A launchd plist is not a Linux or Windows deployment.
Standalone email/Tiger delivery ownership is a separate acceptance gate.
Readiness-model success is not a portfolio-email cutover receipt.

## Business approval and postconditions

Business execution is separate from readiness. An explicit business profile may
select `approval_mode: automatic_review`, which uses the supported
`--approve-for-me` route (on-request review with workspace-write) rather than
`approval_policy=never`. It does not change global Gmail permissions or bypass
a reviewer rejection. A business job may declare a trusted completion_adapter;
Niulai requires canonical report/PDF integrity, fresh-source timestamps and a
verified accepted delivery-ledger row in addition to a completed model turn.
The first full test was blocked before verified delivery; its unknown outbox
record remains held. A user-authorized corrected test uses a separate request ID.

## Delivery happened but final-summary formatting failed

Never repeat an external effect solely because the model summary was rejected.
`Engine.reconcile_failed_delivery` accepts independent verified delivery evidence
only for whitelisted final-format failures after a completed CLI turn. It keeps
the original failed attempt immutable, writes an immutable reconciliation record
and updates the slot without dispatching. Conflicting evidence is rejected.
Trusted completion adapters may automatically verify canonical artifacts and
accepted/readback delivery after a harmless formatting failure; rejected fields,
sensitive output, path violations and tool approval denials are excluded.


## Explicit private writable scope for business jobs

A central business model profile may set `writable_roots`, for example
`[".job-runtime/calculation"]`. An explicit list replaces the historical default
Niulai grant. With no field, Niulai behavior is preserved. Job allocations and
model context cannot add roots. The executor rejects source/absolute/traversal,
symlink, missing/foreign-owner directories and any ancestor/descendant overlap
with its auth home before launching. Each selected root must be an existing
relative private directory under `.job-runtime/` or `.niulai-state/`. The receipt
records sanitized relative grants. This changes no global approval or app setting.

The first scheduled calculator trial started on time but returned blocked before
a report; source inspection found only Niulai state was granted while calculator
outputs use separate calculator state. The failed attempt remains recorded. A
new scheduled trial after the explicit scope and service-code restart is required
before claiming the calculator profile works. Restart the daemon after Python
executor source changes; config SIGHUP alone does not reload imported code.


The calculator's second trial exposed a macOS nested-sandbox restriction, not a
reason to expand global approvals. Its component now uses the existing adapter
interface for an attempt-scoped host request bridge: Codex calls a fixed client,
the host runs the unchanged OS-restricted compute workers, and the completion
adapter verifies trusted host evidence. There is no new persistent daemon or
network listener. The allocator remains separate from generic scheduling/model/
retry infrastructure; numeric formulas remain below this adapter.
# Safe configuration reload, 2026-10-31

SIGHUP validates enabled allocations against persisted schedule hashes before
replacing the working engine. A rejected reload leaves the current engine running
and writes a sanitized`reload-status.json`. Changing a persisted schedule requires
a new job ID; editing a one-time job's timestamp is not a postponement mechanism.
Preserve earlier attempts and verify quiescence before an intentional restart.
An invalid config on cold startup still needs correction; reload retention is
not a bypass of allocation validation or unknown-outcome fences.

The datasource integration exposed a strict response-schema rejection for
`uniqueItems`. The investment executor omits this unsupported transport constraint
while still enforcing the complete original schema locally. The shared model
adapter classifies `invalid_json_schema` / invalid response-format schema errors
as permanent configuration rejection rather than retryable transport failure.
The first failed scheduled receipt remains preserved; a repair requires new proof.
