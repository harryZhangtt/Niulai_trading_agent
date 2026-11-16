# Factor-mining local Docker activation path repair v3

Date: 2026-11-05

Status: **selected-disabled**

## Observed failure

The first explicitly authorized Colima start used the frozen v2 state root
`$WORKSPACE/factor/runtime/local/colima`. It failed before VM creation because
Lima constructed a Unix socket path 160 bytes long from the temporary worktree.
The same path would be 119 bytes in the main checkout. macOS limits this Unix
socket path to fewer than 104 bytes. No VM was created or started, no Docker
daemon or context was activated, and no image or container ran.

This is a deterministic local path/configuration error. It is classified as a
**permanent pre-dispatch** failure, not transient infrastructure failure. Retrying
the same command is prohibited.

## Minimal versioned repair

Preserve the frozen v1 architecture and v2 installation evidence. Change only
Colima's workspace-local state root to:

```text
COLIMA_HOME=$WORKSPACE/.c
COLIMA_PROFILE=factor-mining
```

The conservative Lima socket path is then 94 bytes. The repository root ignores
`/.c/`. Docker client state remains at
`$WORKSPACE/factor/runtime/local/docker-config`. No global `~/.colima`,
temporary, external, or symlinked path is permitted.

The activation argv remains selected-disabled data and preserves:

- profile `factor-mining`;
- `autoActivate=false` / `--activate=false`;
- Docker runtime on `vz`;
- 6 CPU, 12 GiB memory, 40 GiB data disk, 20 GiB root disk;
- no host mounts, no SSH config, no Kubernetes;
- no global Docker context mutation.

`factor/docker/local/v3/validator.py` requires the exact main workspace, strict
workspace containment, no symlink ancestor, an absent `.c` before activation,
and a UTF-8 socket path below 104 bytes. It rejects the original 119-byte path,
the observed 160-byte worktree path, global/home/temp/external paths, traversal,
pre-existing state and type confusion.

## Frozen predecessor bindings

- v1 tree: `ba79cf54ea34bdd09f063c1809060d6f9564b5d8f46aa726aff750ffea8c7908`
- v2 installation receipt canonical hash:
  `c292459b46de9da23c7a90da3a439f71d83353aa14e2f4e43e91c2fd48e03327`
- v2 runtime profile canonical hash:
  `40c391e025b06da28555939d5face923469a5bd8db611d9f555529588db9a81d`

Neither predecessor is modified.

## Activation and rollback boundaries

The v3 command remains `executed:false`, `runnable:false`, and
`apply_allowed:false` until independent review. After approval, the operator may
run only the exact environment and argv in `activation-command-v3.json`.

Rollback uses the same workspace-local environment and the recorded argv:

```text
/opt/homebrew/bin/colima delete factor-mining --force
```

Before rollback, verify no scientific attempt is running or unknown. A later
runtime lifecycle must still satisfy all v1/v2 image, release, containment,
network, pressure, retry, reconciliation and scheduled-acceptance blockers.

## Nonclaims

This repair does not establish that a VM, daemon, Docker context, image,
container, factor workload or runtime acceptance exists. Validation proves only
that the corrected state path fits the macOS socket limit and that the disabled
command is bound to the prior reviewed contracts. It does not authorize blind
retry, setup refresh, global configuration, image build or scientific execution.
