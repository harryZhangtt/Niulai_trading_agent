# Local factor health lifecycle v10

This selected-disabled package defines one disposable, health-only Docker lifecycle. It does not run RD-Agent, Qlib, generated code, providers, datasets, evaluation, or publication.

It binds the reconciled Colima VM evidence `95b18403…c910`, the Python 3.11 slim Bookworm index digest `a83ba18a…b39`, and its Linux/arm64 manifest `464bee9a…420`. The dedicated worker uses only Python's standard library and returns success only for `health`; scientific execution exits 2.

The host owns pull, build, immutable image inspection, create, inspect, start, wait, logs, terminal inspection, receipt publication, and removal. The container is non-root, no-network, read-only, capability-free, no-new-privileges, PID/CPU/RAM/swap/tmpfs/log bounded, has no mounts/secrets/Docker socket, and never auto-restarts. It is never created with `--rm`; post-create CLI uncertainty is fenced and retained.

Run inert checks only:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest factor.docker.local.v10.tests.test_contract -v
python3 -B -m factor.docker.local.v10.validator
```

`apply_allowed` and `runnable` remain false. A later reviewed lifecycle activation must explicitly authorize the capability, restart the reconciled VM, pull the pinned base, and persist a private receipt. Passing this package does not establish image availability, containment enforcement, scale, stability, scientific execution, or runtime acceptance.
