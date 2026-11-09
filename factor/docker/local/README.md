# Selected-disabled local Docker/Colima factor-mining candidate

This package is a **proposed contract**, not an installed or active runtime. It
selects a local Colima VM with Docker and `vz` as the replacement candidate for
paid GCP activation, but it is deliberately non-runnable:

- `status` is `selected-disabled`;
- `runnable` and `apply_allowed` are both `false`;
- all live Docker/Colima versions, executable paths, Docker context, VM identity,
  image digests, and release digest are null blockers;
- future Colima state is pinned to `COLIMA_HOME=$WORKSPACE/factor/runtime/local/colima`
  and `COLIMA_PROFILE=factor-mining`; implicit `~/.colima` use fails closed;
- there is no Compose file or command that starts Docker, Colima, a daemon, a
  container, or a network.

## Contract files

- `runtime-profile.json`: exact 6 CPU / 12 GiB / 40 GiB Colima VM selection,
  Docker + `vz`, static-headroom pressure policy, concurrency, authority,
  retry/restart rules, unknown-outcome fence, blockers, and nonclaims.
- `service-declarations.json`: separate stable (`controller`, `proxy`) and
  scientific-attempt (`executor`, `evaluator`, `checker`) declarations. Docker
  restart is `no` for every service; bounded stable restart is host-authority
  owned. Scaling is explicit only.
- `source-inventory.json`: official-reference URLs, titles, scoped claims, and
  an affirmative record that no source was live-fetched in this task.
- `*-v1.schema.json`: Draft 2020-12 closed, exact-value schemas. Every object has
  `additionalProperties: false` and complete `required` keys.
- `validator.py`: standard-library duplicate-key rejection, schema-subset
  validation, semantic validation, CLI, and deterministic SHA-256 reporting.
- `fixtures/`: valid mirrors and adversarial invalid inputs.

The schema validator intentionally supports only the exact closed-schema subset
emitted by this package. It is not represented as a general JSON Schema engine.
Semantic validation remains authoritative.

## Safety model

Static host headroom is the primary pressure control; there is no custom pressure
daemon, Kubernetes, Swarm, Redis, autoscaling, or preemption. Executor concurrency
is 1 by default. A burst to at most 2 requires an explicit Engine/authority choice.
Under pressure, admission blocks new leases and the current bounded attempt is
finished or cancelled; running memory is never auto-shrunk. Colima may be stopped
only after the queue drains and there is no running or unknown attempt.

The Engine owns leases and attempt retries. A transient attempt may be retried at
most once. Permanent failures are not retried. Any unknown outcome is fenced and
must be reconciled before retry. Docker restart is `no` for all services because
`unless-stopped` cannot express bounded restart-storm safety. A future host
authority may restart stable services at most 3 times in 300 seconds with exact
5/15/45-second backoff, health/readiness gates, blocked admission on a storm, and
identity/image/network/health reconciliation. This remains unverified and blocked.

The executor declaration fixes a 2 CPU hard limit, 4 GiB memory hard limit, 2 GiB
reservation, memory-swap equal to the hard limit (no additional swap), PID limit
512, and CPU shares 256. It also requires read-only root, bounded tmpfs, no
network, no Docker socket, no secrets, no active mounts, all capabilities dropped,
and `no-new-privileges`. Controller, proxy, evaluator, and checker also declare
exact CPU/memory, PID 512, and memory-swap equal to memory with zero additional
swap. Local log rotation is 10 MiB × 3 files for every service.

Future I/O is closed and blocked on unresolved identities: only read-only
request/bundle/dataset directories at `/input/request`, `/input/bundle`, and
`/input/dataset` are admissible, with no symlinks/path escape/socket/secrets.
Output is staged in a 1 GiB bounded tmpfs and only the Engine may promote the
allowlist after successful host plus in-image verification; destination identity
is null and unknown promotion is fenced.

Future networking is also blocked: internal and egress network identities are
null. Controller may attach only to internal and reach the proxy; proxy is the
sole service allowed the internal+egress dual attachment; executor, evaluator,
and checker have no attachments. Direct controller egress or proxy bypass fails.

Every role requires a Linux userspace/base release, OCI Linux platform plus
architecture, immutable image digest, host verifier, and additive in-image
verifier. Base releases, base/image/verifier digests, and architecture remain null
blockers; these declarations are not image evidence.

These are machine-validated declarations, not evidence that a Docker Engine or
Colima VM enforces them on this host.

## Workspace-local host state and context fence

All future Colima configuration, cache, and runtime artifacts must remain beneath
`$WORKSPACE/factor/runtime/local`; the repository's existing `**/runtime/` ignore
rule covers that root. A future wrapper must export the exact `COLIMA_HOME` and
`COLIMA_PROFILE` values above before any Colima operation. Missing/mismatched
values or use of the default `~/.colima` state fail closed. Exact Colima config
`autoActivate: false` prevents startup from selecting a global Docker context.

After separately approved activation, the operator must discover and validate the
context name `colima-factor-mining` without changing Docker's global current
context. Every future Docker wrapper invocation must pass the explicit argument
pair `--context colima-factor-mining`. This is a future wrapper contract, not a
claim that the context exists, and no context was inspected or changed here.

## Reproduce inert checks

Run from the workspace root. These commands do not invoke Docker or Colima.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s factor/docker/local/tests -v
python3 -B -m factor.docker.local.validator
python3 -m py_compile \
  factor/docker/local/validator.py \
  factor/docker/local/tests/test_contract.py
```

The CLI returns contract hashes and `apply_allowed: false`. This candidate has
no Compose artifact and authorizes no deployment command.

## Evidence boundary

Tested behavior is limited to deterministic parsing, duplicate-key/non-finite
rejection, closed exact schemas, semantic invariants, invalid fixtures, and CLI
hash output. No installation, daemon check, container lifecycle, network action,
pressure event, workload, capacity measurement, cost measurement, or runtime
acceptance was performed. Official references are inventory only and were not
live-fetched in this task. The coordinating session reported live verification on
2026-11-05, but supplied no exact receipts/receipt URLs to this artifact; that
report is recorded as unavailable/not adopted and receipt import remains a blocker.
