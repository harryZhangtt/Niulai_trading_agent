# Secure local Colima activation preflight v4

Date: 2026-11-05

Status: **selected-disabled**

## Problem and evidence

The authorized first start exposed two connected pre-dispatch requirements. The
reviewed long state root produced a 119-byte socket path in main and 160-byte path
in the temporary worktree, above macOS's 104-byte Unix socket limit. Colima 0.10.3
also requires an explicit existing `COLIMA_HOME`; otherwise startup can fall back
to default state. Retrying the old command is prohibited because this is a
**permanent pre-dispatch** path/configuration failure.

No VM or Docker daemon is started by this repair. Frozen v1 architecture and v2
installation evidence remain unchanged and are loaded from the explicit workspace
and bound by physical and canonical hashes.

## Minimal repair

A standard-library preflight receives an explicit absolute workspace argument and
securely creates three private, empty, current-user-owned roots with mode `0700`:

- `$WORKSPACE/.c` for `COLIMA_HOME`;
- `$WORKSPACE/factor/runtime/local/colima-cache` for `COLIMA_CACHE_HOME`;
- `$WORKSPACE/factor/runtime/local/docker-config` for `DOCKER_CONFIG`.

It traverses with directory file descriptors and `O_NOFOLLOW`. Symlink ancestors,
external/home/temp/global paths, traversal, files, non-empty directories, wrong
mode/owner and race-shaped substitutions fail closed. Candidate validation uses
temporary roots only; the main root remains absent until a separately authorized
activation.

The exact environment contains fully expanded absolute paths—no unresolved
workspace token at execution—and profile `factor-mining`. The corrected `.c`
socket path is a 94-byte path. The command preserves 6 CPU, 12 GiB memory, 40 GiB data
disk, 20 GiB root disk, Docker on `vz`, `--activate=false`, no host mounts, no SSH
config, no Kubernetes, and adds `--template=false` to prevent fallback template
state. Global Docker context mutation remains prohibited.

## Activation contract

`factor/docker/local/v4/launcher.py` never invokes Colima or Docker. With
`apply=False` it validates and returns a plan. With `apply=True` it may create only
the three preflight roots and then returns the exact environment, argv and rollback
contract; actual process execution remains outside the module.

The recorded rollback uses the same environment and:

```text
/opt/homebrew/bin/colima delete factor-mining --force
```

Rollback or retry must first preserve unknown-outcome fences and confirm no
scientific attempt is running. Path/config failure remains permanent pre-dispatch;
it is never converted into an infrastructure retry.

## Verification

The tests cover missing-root fallback prevention, explicit cache and Docker config,
secure creation/idempotence, wrong files/modes/owners, non-empty roots, symlinks,
race-shaped failures, absent/unset/relative workspaces, external paths, socket
length, live v2 physical and canonical drift, exact types, bool/integer confusion,
array/null schema handling, duplicate/non-finite JSON, invalid UTF-8 and surrogate
strings, activation argv and rollback.

Passing tests prove only the preflight contract. They do not prove Colima startup,
VM identity, Docker context, daemon behavior, images, releases, container
containment, pressure behavior, factor execution or runtime acceptance. The
candidate stays `runnable:false` and `apply_allowed:false` until independent
review and a separate activation decision.
