# Secure Colima activation preflight v4

Colima 0.10.3 requires `COLIMA_HOME` to exist; otherwise it can fall back to its
default home. This selected-disabled package fixes that boundary without invoking
Colima or Docker.

`launcher.prepare_roots(workspace, apply=True)` uses standard-library directory
file descriptors, `O_NOFOLLOW`, ownership/mode checks and exact relative roots to
create only:

- `$WORKSPACE/.c` (`COLIMA_HOME`)
- `$WORKSPACE/factor/runtime/local/colima-cache` (`COLIMA_CACHE_HOME`)
- `$WORKSPACE/factor/runtime/local/docker-config` (`DOCKER_CONFIG`)

Each final root must be a private (`0700`), current-user-owned, empty directory.
Existing files, non-empty directories, wrong modes/owners, symlinks, traversal,
global/home/temp paths and race-shaped substitutions fail closed. The main
activation command uses fully expanded absolute environment values and includes
`--template=false`, `--activate=false`, no mounts, no SSH config and no
Kubernetes. Its 94-byte conservative socket path is below macOS's 104-byte limit.

The default validator is read-only. The launcher never invokes Colima or Docker;
it only returns the exact environment, argv and rollback contract. Path/config
failure is permanent pre-dispatch and cannot be retried unchanged. Frozen v2
receipt/profile files are loaded from the supplied workspace and verified by
both physical and canonical hashes.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/docker/local/v4/tests -v
python3 -B -m factor.docker.local.v4.validator
```

Passing this gate does not create a VM, daemon, context, image or container and
does not make the runtime ready.
