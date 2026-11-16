# Scalable factor Docker runner

## Status

This profile is **development-only and blocked**. It defines and statically verifies a scalable two-container boundary, but cannot build or run on this machine because Docker/Colima, buildx, reviewed hash-complete wheel locks, accepted image digests, an allow-listing provider proxy, a frozen dataset and a sealed experiment protocol are absent.

Run the static gate:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m factor.docker.verify
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/docker/tests -v
```

Expected: `FACTOR_DOCKER_STATIC_OK` with `runnable: false`. A blocked result is success for the current source-only stage; changing it to ready without real digests/locks is a defect.

## Roles

### Controller

The future controller image contains the pinned RD-Agent wheel and a maintained adapter for proposal, coding and redacted feedback serialization only. It never runs generated code, contains Qlib, launches containers or receives the Docker socket. It can reach only a separately administered provider proxy on an internal Docker network. Requests carry credential references, never values; the proxy owns provider allowlists, secrets, budgets and egress.

The tracked `controller_worker.py` currently supports `health` only and rejects prepare/feedback. It is not RD-Agent execution.

### Executor

The future executor contains only Qlib at `2fb9380…`, reviewed CPU runtime dependencies and the trusted executor wrapper. It receives a sealed request, generated-code bundle and frozen dataset through read-only mounts. It runs with network disabled, a read-only root, non-root UID/GID 65532, all capabilities dropped, no-new-privileges, seccomp, PID/CPU/RAM/ulimit bounds and tmpfs scratch. It never receives provider credentials or RD-Agent provider clients.

The tracked `executor_worker.py` currently supports `health` only and rejects execution.

### Host orchestrator

The host—not either container—will own Docker argv, bounded queue leases, deterministic names, timeout/cancel, receipt validation, immutable evidence publication and crash reconciliation. Neither container receives `/var/run/docker.sock`; nested Docker is prohibited. Do not use `--rm`: stopped containers remain until the host validates and durably publishes their receipt.

`runtime.py` currently constructs and tests exact controller/executor argv only. It does not invoke Docker.

## Reproducible build contract

Both images use this exact multiarch base identity:

```text
python:3.10-slim-bookworm@sha256:5be5aaecb962a41567bc8041f1e9e3432cb085b037fe057f9a562630b2e4b370
```

Python 3.10 is past scheduled upstream support as of this workspace date. The profile is therefore development-only. Production promotion must either document a time-bounded owner-approved patched-base/CVE exception or migrate the separately tested image profile to Python 3.11.

The Dockerfiles accept only offline wheelhouses plus `pip --no-index --require-hashes` lock files. Those files deliberately do not exist yet. The tracked `*.unresolved.json` records prevent an accidental floating resolution.

Before image acceptance:

1. Fully hydrate the pinned Git objects; require clean trees, `git fsck --full`, no LFS pointers/submodules/unresolved promisor objects.
2. Create normalized source archives with fixed order, owner, mode and `SOURCE_DATE_EPOCH`; extend the existing source lock with archive/manifest/acquisition receipt hashes.
3. Resolve controller and executor closures separately on native CPython 3.10 for `manylinux_2_28_x86_64` and `manylinux_2_28_aarch64`.
4. Reject VCS/direct URL/path/editable/floating/unhashed/yanked dependencies and every unreviewed transitive sdist.
5. Build RD-Agent and Qlib wheels offline twice. Verify wheel completeness; Qlib must contain/import `rolling` and `expanding` native extensions with matching architecture/ELF/auditwheel/numerical evidence.
6. Assemble role-specific wheelhouses, hashes, SBOMs and license inventories. Controller must exclude Qlib/executor/build tools; executor must exclude RD-Agent/provider/build tools.
7. Build/test both architectures natively, then create the multiarch manifest from tested digests only. Record image, SBOM, provenance, policy, source and dependency-lock digests in `image-lock.json` and change status only after review.

Generated artifacts belong under ignored `factor/runtime/builds/` and a content-addressed OCI registry, never Git.

## Runtime policy

Initial bounded concurrency is two active runs, one controller/provider stage and two executors. Queue wait does not consume an attempt. Default stage retry cap should be two total attempts and only for classified transient daemon/proxy failures or unknown infrastructure outcomes. Invalid input, pin/policy/auth/integrity/security failures are permanent.

Deterministic identity is `(request_sha256, stage, attempt_number)`. On recovery, the host inspects the deterministic container name and immutable state:

- valid terminal receipt: publish/reconcile idempotently;
- running container: reattach/wait, never duplicate;
- exited without receipt: record receipt missing and consume the attempt;
- absent after durable dispatch without receipt: mark outcome unknown; never describe it as an ordinary retry;
- cancellation: persist intent, TERM/grace/KILL, verify absence, then publish cancelled or cleanup failure.

## Promotion boundary

Static checks, health-only worker output and mocked argv do not establish image buildability, container containment, provider access, Qlib execution, factor correctness or alpha. Real promotion requires daemon-gated inspection, adversarial executor probes, native multiarch image tests, a stub-proxy end-to-end loop, two cache-cold deterministic runs, then separately authorized provider/data execution under the existing overfitting guard and immutable manifest system.
