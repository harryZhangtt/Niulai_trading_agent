# Local Docker/Colima activation path repair v3

This package records one observed, permanent pre-dispatch failure: the original
workspace-local `COLIMA_HOME=$WORKSPACE/factor/runtime/local/colima` produces a
119-byte Lima socket path in the main checkout (160 bytes in the temporary
worktree), exceeding macOS `UNIX_PATH_MAX=104`. No VM or daemon started.

The versioned repair changes only Colima state placement to
`COLIMA_HOME=$WORKSPACE/.c`. With profile `factor-mining`, the conservative
worst-case socket path is 94 bytes. `/.c/` is ignored at repository root. The
Docker client configuration remains under
`$WORKSPACE/factor/runtime/local/docker-config`.

`runtime-profile-v3.json` and `activation-command-v3.json` remain
`selected-disabled`; `runnable`, `apply_allowed`, and `executed` remain false.
The profile keeps the reviewed 6 CPU / 12 GiB / 40 GiB Docker-on-`vz` envelope,
`autoActivate=false`, no host mounts, no SSH config, and no Kubernetes. Docker's
global current context must not change.

The validator requires the exact main workspace, workspace containment, no
symlink ancestors, an absent `.c` before activation, and a UTF-8 socket path
strictly shorter than 104 bytes. External, temporary, home-global, traversal,
long, pre-existing, and type-confused paths fail closed. It performs no Colima
or Docker operation.

Run the inert gate from the main workspace:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/docker/local/v3/tests -v
python3 -B -m factor.docker.local.v3.validator
```

The activation command is data only. It may be executed only after this v3
candidate passes independent review and the operator separately authorizes the
retry. Rollback uses the same workspace-local environment and the recorded
`colima delete factor-mining --force` argv. A deterministic path/configuration
failure is permanent pre-dispatch and must never be retried unchanged.
