# Local Docker installation evidence and profile v2

This additive package records a read-only observation of installed Homebrew
binaries. Package installation is distinct from activation: the candidate remains
`selected-disabled`, `runnable=false`, `apply_allowed=false`, and
`autoActivate=false`.

## Artifacts

- `installation-receipt.json` records aware observation time, Darwin/arm64 host,
  sanitized path/version/hash command evidence, Lima dependency, Homebrew service
  state, exact-name process absence, and an unchanged/absent `~/.docker` check.
- `runtime-profile-v2.json` binds that receipt and references the frozen v1 tree.
  It resolves only the four v1 path/version blockers supported by exact evidence.
- `*-v2.schema.json` are Draft 2020-12 exact-value schemas. Every object is closed
  and every property is required.
- `validator.py` is standard-library-only and reads files/hashes only.
- `tests/` verifies duplicate-key/non-finite rejection, exact schemas, binary
  evidence, activation nonclaims, v1 freeze, blocker retention, command absence,
  and plan nonclaims.

## Evidence boundary

Observed installed executables are Colima 0.10.3, Docker CLI 29.9.3, Compose
5.7.0, Buildx 0.38.2, and Lima 2.2.1. Their package presence does not prove a
Docker daemon, Colima VM, Docker context, image, release, capacity, lifecycle,
pressure behavior, network/mount/OCI conformance, or runtime acceptance. No Docker
server or context query was made. Homebrew reported the Colima service as `none`,
and an exact-name process check returned no matches; those absence checks do not
establish a VM identity.

The profile preserves exact future state values
`COLIMA_HOME=$WORKSPACE/factor/runtime/local/colima`,
`COLIMA_PROFILE=factor-mining`, and expected future context
`colima-factor-mining`; actual context and VM identities remain null.

## Inert checks

From the workspace root, these invoke Python only:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/docker/local/v2/tests -v
python3 -B -m factor.docker.local.v2.validator
python3 -m py_compile factor/docker/local/v2/validator.py factor/docker/local/v2/tests/test_contract.py
```

The package contains no deployment, service activation, context mutation,
container, network, package-management mutation, setup-refresh, or commit action.
