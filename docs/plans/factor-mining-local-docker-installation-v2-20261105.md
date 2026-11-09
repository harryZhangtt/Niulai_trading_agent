# Factor-mining local Docker installation evidence/profile v2

Date: 2026-11-05

State: **selected-disabled**

Owner: factor Docker local candidate

Activation owner: separately authorized production operator

## Scope and decision

This additive candidate records point-in-time installed-tool observations. It does
not establish daemon, VM, Docker-context, or broader runtime activation history.
The profile remains `runnable=false`, `apply_allowed=false`, and
`autoActivate=false`. It contains no apply or service-start procedure.

The smallest useful capability is an immutable installation receipt, a profile
that references the frozen v1 contract tree, strict closed schemas, and a
standard-library validator/test suite. It does not establish production readiness.
The candidate contains no package-mutation, daemon/VM start, Docker server/context,
container, network, hook, UI, shared-runtime, or scheduler activation procedure.
This change does update the selected-disabled setup documentation, sanitized
inventory, and consistency lock described below.

## Read-only installed-tool observation

Source: `installed-tool-observation`

Observed at: `2026-11-05T19:43:52+08:00`

Host: Darwin arm64

| Tool | Installed version/build | Absolute executable path | SHA-256 |
| --- | --- | --- | --- |
| Colima | 0.10.3; commit `00f6c297e92a82c04a4ab507db0a61435650d7e8` | `/opt/homebrew/bin/colima` | `55278419bd4288e4ab11eb30be13f5e655f3886c0979b68e435df910dbc9bbdf` |
| Docker CLI | 29.9.3; build `5457199aa5` | `/opt/homebrew/bin/docker` | `07e3a894d913ccbd07b11d984edde25b0d683bfc2fec986d3e378eef035bc219` |
| Compose | 5.7.0 | `/opt/homebrew/lib/docker/cli-plugins/docker-compose` | `f826c82d69e24647e080eab992f8aa0abc14ade04762780044c4a7602b7275fc` |
| Buildx | 0.38.2 | `/opt/homebrew/lib/docker/cli-plugins/docker-buildx` | `b0c443c3bafc5fd0e7d6cbb19478ce0d0b35122e5e257b53bd714ce80ab123a6` |
| Lima dependency | 2.2.1 | `/opt/homebrew/bin/limactl` | `e79b14815dc7e51629e064dba950120c4c9323e2b8ba6a52fe816b15f7f9803d` |

Paths came from executable lookup for Colima, Docker, and Lima, and Homebrew
prefix plus the installed CLI-plugin path for Compose and Buildx. Version-only
commands and file hashing were used; no Docker server or context command was
used. The receipt preserves sanitized command/output fields and no credentials.

Homebrew service observation was exactly `colima none`. An exact executable-name
filter found no Colima, Lima, Lima host-agent, QEMU, VZ, or gvproxy process. This
is absence evidence at one timestamp, not a durable service guarantee and not a
VM identity. Before and after repeating the version/hash probes, `~/.docker` was
absent with zero entries and the same aggregate state hash
`5ad38304b535c2987dbd24657c1a11b884984ff600d9f389deb0d4e634fee792`;
no `~/.docker` filesystem creation, content change, or metadata change was
observed during those probes. Docker-context and VM state were not inspected and
remain unknown; no activation-history inference is made.

## Frozen v1 source reference

V2 references the explicit 18-entry `V1_MANIFEST` under `factor/docker/local`;
it fails closed on every additional behavior-bearing v1 file. Only explicit
incidental names (`.DS_Store`, `editor.swp`, `__pycache__`) and numeric version
directories such as `v2/` are ignored. Manifest records contain relative path,
NUL, file SHA-256, and line feed in manifest order, then are hashed together.

- Frozen v1 tree SHA-256:
  `405fd69ce4cecdf128a925082aa0e3f1a1c8a8ab179c6dc98b7a3a6c56ada2f4`
- Frozen v1 runtime profile file SHA-256:
  `0018efdecd22659125880e398f831ab7e93ede52e81724908d2c17c467950d1a`
- V2 installation receipt canonical SHA-256:
  `ecc4d2651e22b5e1d32c9cf32ac3bee2f3cfaa60dbf6cc13d8de4af6aaf67a8a`

Only these exact-evidence v1 blockers are marked resolved:

- `colima-version-unverified`
- `docker-version-unverified`
- `colima-path-unverified`
- `docker-path-unverified`

## Retained activation blockers

The candidate retains blockers for all unobserved activation and runtime facts:

- Docker context and VM identity;
- controller, proxy, executor, evaluator, and checker image digests;
- release digest;
- host headroom;
- disposable lifecycle and stable lifecycle conformance;
- pressure behavior;
- future I/O sources, promotion root, and mount/I/O conformance;
- internal/egress network identities and dual-network conformance;
- Linux userspace/base release, OCI architecture, in-image verifier digests, and
  image-contract conformance;
- official-source live-verification receipts; and
- future-triggered scheduled runtime acceptance and required email evidence.

The future workspace-local state remains exactly
`$WORKSPACE/factor/runtime/local/colima` with profile `factor-mining`. The expected
future context name remains `colima-factor-mining`, but actual context and VM
identity fields are null with explicit `uninspected-unknown` state. Point-in-time
service/process absence does not resolve either identity or runtime history.

## Evidence and nonclaims

Passing tests proves exact parsing, schema closure, receipt/profile binding,
installed binary evidence equality, v1 freeze equality, and disabled-state
invariants. It does not prove daemon availability, VM creation, context creation,
image availability, release readiness, isolation, capacity, pressure handling,
lifecycle behavior, network/mount/OCI conformance, factor quality, production
readiness, or runtime acceptance.

The selected-disabled runbook, sanitized inventory, and setup lock are updated in
this change. Existing GCP/AWS, UI, shared runtime, hooks, active runtime
configuration, and scheduler behavior remain untouched.

## Setup source-of-truth integration

This selected-disabled candidate is recorded in `docs/local-setup.md` and the
sanitized optional-candidate entry in
`docs/deployment/setup-inventory.json`. The setup consistency lock is refreshed
with those source and documentation paths in this change. The inventory preserves
the exact observed versions, paths, hashes, host architecture and observation
time without credentials or private payloads.

This setup integration does not authorize package mutation, daemon or VM startup,
Docker context inspection or mutation, container/network creation, scheduler
activation, or production use. The candidate remains optional, non-runnable and
selected-disabled; all retained blockers and separate activation acceptance gates
still apply.
