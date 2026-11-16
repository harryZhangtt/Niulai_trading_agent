# Factor-mining local Docker installation evidence/profile v2

Date: 2026-11-05

State: **selected-disabled**

Owner: factor Docker local candidate

Activation owner: separately authorized production operator

## Scope and decision

This additive candidate records installed-tool evidence without activating any
service or runtime. Homebrew package installation is not daemon or VM activation.
The profile remains `runnable=false`, `apply_allowed=false`, and
`autoActivate=false`. It contains no apply or service-start procedure.

The smallest useful capability is an immutable installation receipt, a profile
that references the frozen v1 contract tree, strict closed schemas, and a
standard-library validator/test suite. It does not establish production readiness.
No package, daemon, VM, Docker server/context, container, network, global
configuration, hook, UI, shared runtime, setup audit, or scheduler was changed.

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
there was no home Docker configuration creation, content change, metadata change,
or global context mutation.

## Frozen v1 source reference

V2 does not modify v1. It references the 18-file `factor/docker/local` v1 tree,
excluding `v2/**` and `__pycache__/**`, using sorted records of relative path,
NUL, file SHA-256, and line feed, then SHA-256 over their concatenation.

- Frozen v1 tree SHA-256:
  `ba79cf54ea34bdd09f063c1809060d6f9564b5d8f46aa726aff750ffea8c7908`
- Frozen v1 runtime profile file SHA-256:
  `0018efdecd22659125880e398f831ab7e93ede52e81724908d2c17c467950d1a`
- V2 installation receipt canonical SHA-256:
  `c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327`

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
future context name remains `colima-factor-mining`, but both actual context and VM
identities are null. Service/process absence does not resolve either identity.

## Evidence and nonclaims

Passing tests proves exact parsing, schema closure, receipt/profile binding,
installed binary evidence equality, v1 freeze equality, and disabled-state
invariants. It does not prove daemon availability, VM creation, context creation,
image availability, release readiness, isolation, capacity, pressure handling,
lifecycle behavior, network/mount/OCI conformance, factor quality, production
readiness, or runtime acceptance.

No existing runbook, local setup, inventory, or lock file is changed by this
candidate. Existing GCP/AWS, UI, shared runtime, hooks, and active configuration
remain untouched.

## Coordinator handoff after owner freeze

After all owners freeze their additive artifacts, the coordinator may make one
separately reviewed documentation/inventory change. The exact additive handoff is:

1. `docs/local-setup.md`: add a “Factor-mining local Docker installed-tool
   evidence v2” subsection linking the v2 receipt/profile; record the five exact
   versions, paths, hashes, Darwin arm64 observation time, package-installed versus
   activation distinction, and retained blockers. Do not present the candidate as
   runnable or accepted.
2. `docs/deployment/factor-mining.md`: add the v2 candidate to the local-runtime
   artifact list, preserving v1 as frozen; state that v2 resolves only four
   path/version blockers and does not supersede runtime acceptance.
3. `docs/deployment/setup-inventory.json`: add sanitized installed-tool inventory
   records for Colima, Docker CLI, Compose, Buildx, and Lima with exact version,
   build/commit where applicable, executable path, SHA-256, source
   `installed-tool-observation`, `observed_at`, host platform/architecture, and
   state `installed-package-observed`; add a selected-disabled profile reference.
4. `docs/deployment/setup-lock.json`: add only the lock entries required by those
   new inventory records, binding the same versions and hashes; retain activation,
   daemon, VM, and context identities as unresolved rather than inventing values.
5. Run the repository setup inventory refresh/check gates only in that coordinator
   change, after resolving concurrent-owner inventory edits. Record the resulting
   inventory/lock hashes and any remaining audit blocker.

This handoff is a list, not authorization to perform those edits or activate the
runtime in this task.
