# Factor-mining production selection: local Docker/Colima candidate

Date: 2026-11-05

Decision state: **selected-disabled**

Contract owner: factor-mining Engine/authority
Activation owner: user-approved production operator (not this candidate package)

## Decision

Select a local Colima VM using Docker with the Apple Virtualization Framework
(`vz`) as the disabled successor candidate to paid GCP activation. The proposed
VM envelope is 6 CPU, 12 GiB memory, and 40 GiB disk. This selection replaces the
*planned activation target*; it does not modify, activate, delete, or claim to
supersede the frozen GCP/AWS source artifacts.

The immediate capability is intentionally smaller than a deployment: exact JSON
contracts, strict schemas, a no-side-effect validator, adversarial fixtures, and
standard-library tests under `factor/docker/local/`. There is no Compose file and
no host/runtime action. This is staged host-impacting material whose activation
boundary remains closed by `runnable=false`, `apply_allowed=false`, null runtime
identity and artifact fields, and explicit blockers.

## Why local replaces paid GCP activation

The expected benefit is avoiding ongoing cloud compute/control-plane cost while
retaining a bounded single-host path adequate for early factor-mining attempts.
Local execution also reduces provisioning surface for the first narrow runtime
acceptance. Those are planning assumptions, not measured savings or performance.

The cheapest adequate architecture is one Colima VM, Docker, static host headroom,
default executor concurrency 1, and an explicit burst ceiling of 2. No observed
workload currently justifies a pressure daemon, Kubernetes, Swarm, Redis,
autoscaling, or preemption. Compose scaling, if a later apply artifact is approved,
must remain explicit and authority-driven.

## Trade-offs and assumptions

| Dimension | Local candidate | Paid GCP activation | Evidence status |
| --- | --- | --- | --- |
| Direct infrastructure cost | Expected lower by using an existing host | Expected recurring cloud cost | Unmeasured; no prices or utilization sampled |
| Capacity | Fixed 6 CPU / 12 GiB / 40 GiB VM; 1 executor default, explicit max 2 | Potentially elastic | Local sufficiency unmeasured |
| Availability | Depends on one laptop/host and operator lifecycle | Cloud control plane could provide stronger availability | No availability test |
| Isolation | Docker-in-Colima declarations with executor containment | Cloud task boundary could provide stronger tenancy separation | No hostile-workload or host containment test |
| Operations | Fewer services, but host pressure and sleep/stop matter | More provisioning/IAM/network operations | No lifecycle measurement |
| Scaling | Explicit only; no autoscaling/preemption claim | Cloud scaling remains possible in the frozen design | Contract fact only |
| Cost attribution | Local electricity, storage, wear, and operator time remain | Provider bill is visible | Neither cost measured |

Capacity and cost assumptions must not be promoted to facts until representative
attempt duration, peak/resident memory, CPU saturation, disk growth, log growth,
thermal behavior, and host-interference measurements exist. Burst concurrency 2
is a ceiling to test, not a promised operating point.

## Safety and authority contract

Docker restart is `no` for every service. `unless-stopped` was rejected here
because it cannot express bounded restart/backoff or restart-storm admission.
The Engine owns leases, attempt retries, and unknown-outcome reconciliation. A
transient attempt may be retried at most once, permanent failure is not retried,
and unknown outcome is fenced until reconciliation. A future host authority owns
stable-service lifecycle: at most 3 restarts per 300 seconds with 5/15/45-second
backoff, exact health/readiness gates, admission closure on a storm, and
identity/image/network/health reconciliation. This lifecycle remains blocked and
unverified; container restart is never scientific retry.

Static headroom is primary pressure safety. Pressure blocks new leases. A running
bounded attempt is finished or cancelled; its memory is never auto-shrunk. Colima
stop is permitted only after the queue is drained and there is no running or
unknown attempt. This candidate adds no background pressure daemon.

All future Colima configuration, cache, and runtime state is confined beneath
`$WORKSPACE/factor/runtime/local`, with exact environment
`COLIMA_HOME=$WORKSPACE/factor/runtime/local/colima` and
`COLIMA_PROFILE=factor-mining`. The default `~/.colima` state is prohibited and
must fail closed. The existing repository runtime ignore rule covers this root.
Exact Colima config `autoActivate: false` prevents startup from mutating the global
current Docker context. After future activation, context `colima-factor-mining`
must be discovered and validated without changing Docker's global current context;
every Docker wrapper
command must pass `--context colima-factor-mining` explicitly. No context exists
or is changed as part of this selection.

Executor policy is no network, no Docker socket, no secrets, no active mounts,
read-only root, bounded tmpfs, `cap_drop: ALL`, `no-new-privileges`, 2 CPU hard
limit, 4 GiB memory hard limit, 2 GiB reservation, memory-swap equal to 4 GiB
(no additional swap), PID limit 512, and CPU shares 256. Controller is capped at
1 CPU / 1 GiB. Controller, proxy, evaluator, and checker also declare PID 512 and
memory-swap equal to their exact memory hard limit with zero additional swap. All
services declare local logs capped at 10 MiB × 3.

Current mounts remain empty. Future I/O may instantiate only the closed blocked
contract: read-only request, bundle, and dataset directories at fixed `/input/*`
destinations, no symlinks/path escape/socket/secrets, and 1 GiB bounded tmpfs
output. Only the Engine may promote an allowlist after successful host plus
in-image verification; the host destination identity is null and unknown
promotion is fenced.

Future network identities remain null. Controller is internal-only and proxy-only;
proxy alone has internal+egress dual attachment; executor/evaluator/checker have
no attachment. Controller egress attachment, direct egress, or bypass is denied.
Every image additionally requires Linux userspace/base release, OCI Linux platform
and architecture, immutable digest, host verification, and an additive in-image
verifier. Base/image/verifier digests and architecture remain unresolved blockers.

## Safe activation prerequisites

Activation requires a separate reviewed change and explicit user decision. Before
that request, all of the following must be complete:

1. Resolve and receipt-bind actual Colima/Docker versions and executable paths,
   VM identity, all image digests, and the release digest. With the exact
   workspace-local Colima environment set, discover and validate Docker context
   `colima-factor-mining`; prove `~/.colima` is not read or written, prove all
   Colima artifacts stay under the ignored `factor/runtime/local` root, and do not
   change the global current Docker context. Mutable image tags are not acceptable.
2. Produce a separately staged, default-disabled apply artifact whose validation
   may instantiate only the closed future input/output and dual-network contracts;
   it must not add other mounts, destinations, network attachments, secrets,
   socket access, privilege, resources, restart, scaling, or logging. Every Docker
   wrapper path must inject `--context colima-factor-mining`; implicit/global
   context use must fail closed and `autoActivate` must remain false.
3. Measure host idle/active headroom and representative workload CPU, memory,
   disk, duration, logs, thermal impact, and host responsiveness at concurrency 1;
   test concurrency 2 separately before authorizing burst.
4. Run a disposable lifecycle with bounded startup/use/timeout, malformed input,
   pressure admission, cancellation, Engine retry, unknown fencing,
   daemon/VM interruption, cleanup, and rollback checks. Verify messaging,
   notifications, diagnosis, and recovery stay available through failures.
5. Demonstrate exact input mounts and output promotion, dual-network isolation,
   executor network denial, absence of Docker socket/secrets/unlisted mounts,
   read-only root, tmpfs bounds, privilege/capability controls, every service's
   resource/swap/PID limits, log rotation, bounded stable lifecycle and storm
   admission in the intended host runtime. Receipt-bind Linux/base releases, OCI
   OS/architecture, immutable image digests, and both host and additive in-image
   verifier results.
6. Verify queue-drain and running/unknown-attempt gates before Colima stop. Test
   stale lease reconciliation and prove no duplicate scientific attempt after an
   unknown outcome.
7. Obtain the required future-triggered scheduled Codex runtime acceptance in the
   intended runtime, with independent business postconditions and the required
   `[CODEX]` email evidence. Manual/unit validation is not a substitute.
8. Update applicable local setup documentation and sanitized inventory only in
   the separately authorized activation change, then pass their audit gates.

Until every blocker is resolved, `runnable` and `apply_allowed` remain false.

## Rollback

Before activation, rollback is deletion/rejection of the isolated local candidate;
it has no active effect. For a later canary, retain the previously accepted runtime
unchanged, stop new local lease admission, let the bounded current attempt finish
or cancel it, reconcile every unknown attempt, drain the queue, then stop the
local services/Colima only after all stop preconditions pass. Restore scheduling
to the prior accepted owner without replaying unknown work. Preserve receipts and
failure evidence; do not weaken fences to accelerate rollback.

The frozen GCP/AWS artifacts are reference alternatives, not modified rollback
machinery. This plan does not claim they are funded, active, or ready.

## Official-reference inventory and source freeze

`factor/docker/local/source-inventory.json` records official Colima and Docker
URLs, titles, and narrowly scoped claims. No source was live-fetched in this task;
each entry is marked `reference-not-live-verified`. The coordinating session
reported live verification dated 2026-11-05, but exact receipts/receipt URLs were
not supplied to this artifact. The report is recorded as unavailable/not adopted,
and importing exact receipts remains a blocker. The inventory is design input,
not execution or enforcement evidence.

## Honest nonclaims

This selection does not establish installed software, valid paths/context, a
running VM/daemon, image availability, release identity, container containment,
host isolation, network denial, pressure handling, retry correctness, capacity,
performance, cost savings, reliability, factor quality, production readiness, or
runtime acceptance. Passing validators proves only the proposed documents match
the selected-disabled contracts. No Compose, Docker, Colima, daemon, container,
network, package, hook, scheduler, UI, shared runtime, or active configuration was
created or changed by this candidate.
