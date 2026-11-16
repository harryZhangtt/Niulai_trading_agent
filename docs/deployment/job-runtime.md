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

The current private Niulai allocations run the combined price/holdings business
path at13:00/19:00 America/New_York on XNYS sessions, plus five-minute missing-data
recovery, under the user's explicit parallel-sender authorization. The checked-in
allocation is disabled for safe redeployment. See the [domain runbook](niulai.md)
and actual host/delivery evidence; enabled configuration alone is not proof of a
sent report, and parallel operation is not sole-sender cutover. The earlier
readiness-only sample remains distinct from this business path.

The [local scheduler UI](scheduler-ui.md) reads these actual allocations and
ledgers at`/scheduler`, alongside the datasource frontend. It does not dispatch,
edit or enable jobs and adds no execution/credential dependency to the daemon.

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

### Evaluation-evidence future-write fence

The `evaluation-evidence` store remains `unverified` with `manual_review`
retention. `run_codex` now normalizes its requested run directory before any
launch or directory creation. Every future target at or below
`.job-runtime/evaluations/` fails before launch with
`MODEL_STRICT_PROCESS_TREE_CONTAINMENT_UNAVAILABLE`, including lexical
`..` aliases that normalize into that root. This is a fail-closed hold until a
strict process-tree containment backend is actually available; it does not
repair, migrate, reclassify or accept historical evaluation evidence.

For other run directories, the adapter now gives future child-created files a
`0077` umask, explicitly `fchmod`s parent-created output files to `0600`, and
reads final output through a held run-directory descriptor with identity, mode,
link-count, size and replacement checks. The inherited authentication-lock file
descriptor is intentional. These controls reduce future output-permission and
path-swap risk, but they do **not** contain a detached descendant that calls
`setsid()`. Generic non-evaluation `run_codex` paths therefore retain that
residual process-tree risk and are not promoted as durable evaluation storage.
Umask/fchmod/held-descriptor hardening alone is insufficient to reopen the
evaluation path.

Focused provider-free check:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  shared.job_runtime.tests.test_model
```

This source/test hardening is implemented and passed 33 focused tests in the
current documentation session. It has no intended-runtime future-triggered
scheduled/email acceptance, so the changed capability is not runtime accepted.

### Frozen-disabled strict process-tree containment candidate

`shared/job_runtime/containment.py`, `macos_vm.py` and `vm_assets/` define a
source-only macOS Virtualization.framework containment contract. The candidate
uses a versioned Python/Swift/Linux-guest protocol, private content-addressed
artifacts, no-follow descriptor authority, bounded cancellation/teardown and a
pinned Swift toolchain lock. It exists because the ordinary host process-group
backend cannot contain a descendant that creates a new session with `setsid()`.

The candidate is **not configured or active**. The helper is unbuilt, unsigned,
unentitled and unlaunched; no VM, virtio, cgroup, unrestricted-NAT, launchd or
model-dispatch acceptance has occurred. Do not add its artifacts or profile to
private runtime configuration, and never fall back from a requested strict
backend to the host process backend. The source-only verification command is:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest -v \
  shared.job_runtime.tests.test_containment \
  shared.job_runtime.tests.test_guest_agent \
  shared.job_runtime.tests.test_macos_vm_helper \
  shared.job_runtime.tests.test_containment_protocol
```

The frozen candidate passed 60/60 distinct tests, Python compilation, Swift
`-typecheck`, shell syntax, exact no-build toolchain-lock reproduction and an
independent adversarial review. A future disposable canary requires separate
impact review and explicit authorization; source checks do not satisfy scheduled
runtime acceptance.

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

## Provider-neutral retry v2 candidate: source-live, disabled

The v1 configuration and allocation examples above remain unchanged and describe
the compatibility/current installed path. A separate source-live candidate adds
runtime `schema_version: 2`, durable database schema 8, typed provider results,
provider-neutral retry decisions, replay contracts, reconciliation authority and
scoped circuits. It is not installed, configured, active or production-ready.
Provider-free checks are not scheduled-provider or delivery acceptance.

The candidate contracts are owned by:

- `shared/job_runtime/provider_contract.py` for immutable `ProviderResultV1`,
  `ReplayContractV1` and `ReconciliationProofV1` values;
- `shared/job_runtime/retry_policy.py` for deterministic `RetryPolicyV2` decisions;
- `shared/job_runtime/config.py`, `engine.py` and `service.py` for admission,
  persistence, dispatch gates and provider registry ownership;
- `shared/job_runtime/providers/codex_cli.py` and `claude_host.py` for normalized
  evidence boundaries; and
- `shared/job_runtime/dashboard.py` for a sanitized read-only projection.

### Provider result and retry authority

A provider result records provider, operation, phase, submission state, terminal
proof, status, stable code, failure kind, optional typed HTTP/retry hint and a
bounded sanitized receipt. The result is classification evidence, not permission
to replay. The central decision table is:

| Evidence | Durable disposition | Replay rule |
| --- | --- | --- |
| Terminal with verified proof and no failure | `succeeded` | Never replay |
| Permanent auth, config, model, policy or local-config failure | `terminal_failed` | Never retry unchanged |
| Safe candidate in `not_started` or `connecting`, explicitly `not_submitted` | `retry` if policy, attempt and deadline limits allow | Only a declared automatic phase may retry |
| Typed HTTP 408, 409, 429, 529 or 5xx before submission | Candidate; provider `false` still denies | Honor a valid server minimum wait and local bounds |
| Noncandidate HTTP before submission | `terminal_failed` unless an explicit provider `true` hint applies | Still subject to all replay and policy gates |
| Timeout, reset, partial output or missing terminal after possible/definite submission | `unknown` | Fence; never automatically replay |
| Contradictory terminal proof | `unknown` | Fence and reconcile |

`RetryPolicyV2` accepts a bounded attempt count, positive base and maximum delays,
an optional deadline and exactly `sha256-full-jitter-v1`. The selected delay is
deterministic for the slot, attempt and policy fingerprint. A typed `Retry-After`
value may be milliseconds, seconds, an HTTP date or a typed timestamp; it is a
minimum, never shortened. A past, malformed, over-policy or over-deadline wait
fails closed. The exact selected timestamp is persisted, so restart does not draw
new jitter. Do not independently enable complete SDK and scheduler retry loops:
the scheduler owns durable deferral, unknown fencing and reconciliation and must
account for any provider-client attempts in its total budget.

A v2 replay contract has effect `none`, `idempotent` or
`reconcile_before_replay`; automatic phases may contain only `not_started` and
`connecting`. Even `none` and `idempotent` operate only on an already-safe
pre-submit result. A post-submit unknown requires the named owning reconciliation
adapter to prove the exact outcome `absent`. The immutable proof is bound to the
attempt, operation, slot scope, canonical provider-result digest, evidence digest,
proof digest and recorded time. The engine reloads those bindings from its own
ledger, consumes an accepted proof once and allows only the matching unknown slot
to enter retry wait. Ad hoc values, cross-attempt proofs and blind replay have no
authority.

### Exact v2 configuration and allocation shapes

This is one complete valid v2 example, not an exhaustive display of optional
fields; replace device paths, model names and timing values only with reviewed
owner-private values. Codex profiles may also declare bounded `max_output_bytes`
and `strict_process_tree_containment`; `deadline_seconds` and `jitter` may be
omitted to use their validated defaults. Both profiles are shown for schema
clarity, not as an activation instruction:

```json
{
  "schema_version": 2,
  "python_bin": "/absolute/path/to/checkout/.job-runtime/.venv/bin/python",
  "tick_seconds": 5,
  "heartbeat_seconds": 5,
  "stale_seconds": 90,
  "max_workers": 2,
  "retry": {
    "version": 2,
    "max_attempts": 3,
    "base_delay_seconds": 1,
    "max_delay_seconds": 30,
    "deadline_seconds": 120,
    "jitter": "sha256-full-jitter-v1"
  },
  "model_profiles": {
    "codex-candidate": {
      "provider": "codex_cli",
      "codex_bin": "/absolute/path/to/codex",
      "model": "reviewed-codex-model",
      "effort": "low",
      "timeout_seconds": 120,
      "auth_home": "/absolute/path/to/checkout/.job-runtime/codex-home",
      "circuit": {
        "failure_threshold": 3,
        "open_seconds": 60,
        "probe_seconds": 10
      }
    },
    "claude-candidate": {
      "provider": "claude_host",
      "model": "reviewed-claude-model",
      "timeout_seconds": 120,
      "auth_home": "/absolute/path/to/checkout/.job-runtime/claude-home",
      "circuit": {
        "failure_threshold": 3,
        "open_seconds": 60,
        "probe_seconds": 10
      }
    }
  },
  "allocation_files": [".job-runtime/config/jobs-v2.json"],
  "source_paths": []
}
```

The exact v2 job shape is deliberately smaller than v1. It rejects `replay_safe`,
business `adapter`, `adapter_config`, `completion_adapter`, unknown keys and every
caller-supplied underscore key:

```json
{
  "schema_version": 2,
  "jobs": [
    {
      "id": "provider.retry.codex.candidate.v2",
      "enabled": false,
      "schedule": {
        "kind": "once",
        "at": "2026-11-07T12:00:00+00:00",
        "grace_seconds": 300
      },
      "model_profile": "codex-candidate",
      "prompt_file": "shared/job_runtime/probe-prompt.txt",
      "replay_contract": {
        "version": 1,
        "effect": "none",
        "automatic_phases": ["not_started", "connecting"],
        "slot_operation_scope": "provider.retry.codex.candidate.v2/slot",
        "reconciliation_adapter": null
      }
    },
    {
      "id": "provider.retry.claude.candidate.v2",
      "enabled": false,
      "schedule": {
        "kind": "once",
        "at": "2026-11-07T12:05:00+00:00",
        "grace_seconds": 300
      },
      "model_profile": "claude-candidate",
      "prompt_file": "shared/job_runtime/probe-prompt.txt",
      "replay_contract": {
        "version": 1,
        "effect": "none",
        "automatic_phases": ["not_started", "connecting"],
        "slot_operation_scope": "provider.retry.claude.candidate.v2/slot",
        "reconciliation_adapter": null
      }
    }
  ]
}
```

The service examples use `effect: none` because the production `serve()` path does
not yet register a reconciliation adapter. A `reconcile_before_replay` allocation
is schema-valid only when the owning runtime constructs `Engine` with the exact
reviewed adapter identity; without it, startup fails closed.

Operation and attempt identities, provider-result and retry-decision digests,
reconciliation bindings and circuit generation are centrally derived and persisted.
During loading/service preparation, only trusted runtime code injects
`_replay_contract`, derived `replay_safe`, `_provider`, typed `_retry_policy`,
`_prompt_snapshot` plus `_prompt_sha256`,
`_circuit_scope` (`profile`, `resource_hash`, threshold/open/probe periods) and the
digested `_resource_key`. Allocation keys beginning with `_` are rejected. Provider
and circuit metadata are stripped before the adapter receives its provider-specific
profile. A profile selects one provider; a job cannot replace the registry,
translator, bridge, resource identity or reconciliation authority through prompt
or allocation data.

### Circuit, ledger and migration semantics

Circuits are scoped by provider, profile, credential/resource identity and
configuration generation. Opening a circuit defers work without creating an
attempt. Half-open probes require one durable lease; contenders wait without
consuming attempts. Success closes the matching generation, a qualifying failure
reopens it, and a source/profile/resource generation change cannot inherit stale
probe authority.

Database schema 8 is an additive migration for canonical provider results, retry
decisions, reconciliation records and one-time consumptions, scoped circuit state
and generation, and the per-slot prompt snapshot/digest. Config admission reads a
v2 prompt once through held no-follow descriptors, verifies stable inode metadata
and strict UTF-8, then the first claim durably pins those exact bytes. Retries and
restart use the slot snapshot rather than reopening the source path; the snapshot
columns are immutable after their one allowed initialization. Migration and
backfill are transactional.
Provider results, retry decisions and reconciliation ledgers are immutable; guarded
attempt transitions preserve the original attempt and allow only owned running to
terminal/retry transitions and explicit unknown-to-operator-reconciled handling.
Crash recovery records an old running typed attempt as unknown rather than replaying
it.

Do not run an old writer against a schema-8 database. Before any migration, disable
the candidate, stop/quiesce the service, retain an owner-private database backup
and prove the source/config/schema rollback on a copy. Rollback means restoring a
reviewed compatible source and configuration while preserving the database,
unknown fences, attempts, ledgers and credentials. Never delete or recreate the
live database to make old code start; a v8 database is incompatible with an old
writer unless a separately reviewed rollback or restore has proved otherwise.

### Provider and UI activation boundaries

The Codex normalized structural translator is source-live but remains activation-
blocked. Its sanitized fixture is synthetic structure, not raw Codex semantics;
pinned-source and sanitized-capture conformance are unverified. The service gate
returns `RUNTIME_CODEX_TRANSLATOR_UNVERIFIED` before provider invocation. The
configured model is a request, not provider-reported identity.

The Claude adapter validates sealed host-custody evidence only. It does not invoke
a host, model, network, scheduler or SDK and keeps `runtime_unverified` true. No
production host bridge is available; the service gate returns
`RUNTIME_CLAUDE_HOST_BRIDGE_UNAVAILABLE` without invocation. Neither provider path
has scheduled or Gmail acceptance, and no production-readiness claim is permitted.

The dashboard projection is read-only and has no dispatch, retry, reconcile,
circuit-reset, configuration or enable controls. It exposes only sanitized status,
phase, submission/proof state, stable code, delayed-until source, replay
authorization, circuit state/probe eligibility, unknown fence and queue depth.
Provider receipts, prompts, resource identities and paths are bounded, hashed,
allowlisted or redacted; malformed or secret-bearing provider rows degrade to an
unavailable detail instead of leaking raw evidence. UI/API fields do not grant
runtime authority.

The provider-free campaign uses synthetic providers, clocks, crashes,
reconciliation and external-effect sentinels with real temporary SQLite state. It
covers preconnect and typed HTTP retries, valid/malformed `Retry-After`, overload
circuit open/half-open/close/reopen and scope isolation, permanent auth/config,
provider retry true/false, post-submit reset, timeout, partial/missing terminal,
restart and crash points, deadlines/grace/shutdown/contenders, exception/cancel,
immutability, config drift and v1 compatibility. These checks establish only the
source contract. Future activation must satisfy the separate acceptance contract
below, including both intended provider lanes and exact email readback.

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

### Schema9 Service prompt-artifact handoff candidate (2026-11-07)

The disabled source candidate publishes schema2 prompt captures into the immutable
workspace CAS, strips raw captures before Engine admission and opens verified
descriptors in Service before provider invocation. Its explicit side-file migrator
now takes the Service `service.lock` nonblocking before source validation and holds
it through SQLite backup, candidate construction, exchange, readback and any
rollback; an active writer fails with fixed code `MIGRATION_WRITER_ACTIVE`.

Every forward or rollback exchange remains outcome-unknown until exact path,
inode, schema and SHA-256 readback classifies it. An effect-then-exception is
reconciled from that readback rather than reported as an ordinary failure. Unknown
forward or rollback state preserves the candidate, exchanged peer and recovery
backup. The sealed migration receipt binds the exact active and exchanged-legacy
paths, before/after inodes and file hashes, schema hashes, and complete per-table
source and target counts and row digests. Receipt parsing requires the exact table
set for the declared source version and canonical schema9 target, and recomputes
both aggregate row-inventory digests. Rollback also rereads both databases and
requires their complete inventories to match the receipt before exchange.

Production migration and rollback are fixed to the maintained Darwin
`darwin_rename_swap`; the receipt binds a SHA-256 digest of that implementation's
source. Fault-injection swaps are private test-only inputs with their own source
digest, so a callable spoofing only module and qualified name cannot satisfy a
receipt. Rollback requires the receipt, applies the same safe-file checks to both
paths, and accepts only the bound legacy peer and exact schema9 candidate identity;
an arbitrary schema9 file, path/hash/inventory drift or a post-evidence fence fails
closed.

The hardened disposable tests cover real Darwin exchange, prompt canary/plaintext
absence, every pre-swap phase, held-lock contention and duration, forward and
rollback effect-then-exception, throwing post-swap hooks, callable-identity spoofing,
removed/extra/rehashed receipt inventories, wrong peer/path/hash and candidate
identity, complete target inventory, cleanup, unknown-state evidence retention,
idempotent rollback and the evidence fence. The focused suite passed 21 tests in
the project job-runtime environment; after the provider source freeze, the complete
job-runtime suite passed 471 tests in the project research environment that carries
the pinned `jsonschema` dependency needed by `test_review_campaign`.
Fresh-host reproduction declares that test-only pin in
`shared/job_runtime/test-requirements.txt` and installs it into the separate
`.job-runtime/test-venv`; generated launchd services continue to use the
production runtime interpreter and do not gain `jsonschema` as a runtime
dependency.

No migration or activation was run in this change. The active database remained
schema 8 at SHA-256
`33d960d8fba258f249edaad4ed9f9ab533f2fab058a729072bd2d53ad872914b`.
The earlier disposable SQLite-backup campaign remains candidate evidence only.
Owner-approved active migration, a future scheduled native-host exercise, exact
business/readback acceptance and owner email notification remain required before
any production-readiness or activation claim.

Focused migration tests passed 21/21 and the earlier unchanged-family full job-runtime suite passed 471/471 after the PromptArtifactStore concurrency fix. After the launcher, stale-fixture, shellless-business, and protocol-v3 prompt-custody repairs, the current complete shared/job_runtime suite passes 510/510 in the workspace-owned test environment carrying the declared `jsonschema` pin. This remains local candidate evidence, not activation acceptance.

Schema-1 protocol-v3 adapters now receive immutable `prompt_sha256` and
`prompt_length` values computed from one owner-checked, no-follow, stable read
before adapter preparation; a later dispatch uses that same decoded capture and
never reopens the prompt path. Terminal adapter returns remain terminal. Business
profiles may use `phase=business` with `shell=false`; with
`approval_mode=automatic_review`, generated Codex arguments keep the shell feature
disabled and expose neither shell writable roots nor `--add-dir` grants. Existing
`business` profiles with `shell=true` retain their current private-root behavior.
These source/test changes do not migrate the database, alter active configuration,
regenerate plists, load services, or authorize delivery.
