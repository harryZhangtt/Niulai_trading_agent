# One-shot local Colima activation transaction v5

Date: 2026-11-06

Status: **selected-disabled**

## Goal

Close the remaining local activation transaction gap without changing frozen
v1–v4 contracts or invoking Colima/Docker in tests. The launcher owns one atomic
attempt from cooperative lock acquisition through private-root creation, process
completion, post-spawn reconciliation and sanitized receipt.

## Contract

Activation takes the exact absolute workspace. It requires explicit `apply`, the
`factor-local-v5-start` capability and parent approval. Default invocation is
read-only and returns the plan.

The launcher acquires `.factor-colima-activation.lock` with `O_NOFOLLOW` and
nonblocking exclusive `flock`. This is a **cooperative** same-user lock, not a
claim against a malicious same-user actor. That hostile mutation threat remains
outside scope.

It transactionally creates the three reviewed `0700`, current-owner, empty roots,
tracking only directories this attempt created. Workspace and final-root file
descriptors plus device/inode identities remain open. Immediately before spawn,
it walks parents without following symlinks and compares device/inode, owner,
mode and emptiness. Pre-spawn failure removes only empty created directories in
deepest-first order.

The child runner receives exact argv, `shell=False`, workspace cwd and a closed
environment allowlist. Tests inject fake runners; no real Colima or Docker command
is used.

## Reconciliation and outcomes

Child exit zero is not success by itself. An injected status probe must prove:

- profile `factor-mining` is running;
- context is exactly `colima-factor-mining`;
- context configuration belongs to the explicit workspace `DOCKER_CONFIG`;
- global current Docker context is unchanged.

Only then is outcome `success`. A nonzero/Popen failure is `failed` only when the
probe proves no VM exists, permitting cleanup of this attempt's empty created
directories. Timeout, unavailable status, running-but-mismatched identity, or any
other ambiguous state is `unknown`; roots are retained for reconciliation and
**no blind retry** is allowed.

## Failure injection

Tests cover each root-creation failure, existing non-empty roots, pre-spawn rename
and symlink substitution, lock contention, Popen error, nonzero exit, timeout,
unknown status, status mismatch, exact environment/argv, predecessor drift,
receipt type/schema mutation, cooperative-lock limitations and cleanup ownership.

## Nonclaims

This package does not prove hostile same-user containment, Colima startup, VM or
context identity, Docker daemon behavior, image/release readiness, factor
execution or runtime acceptance. It remains selected-disabled. Real execution
requires a separate explicit apply/capability and parent approval after review.
