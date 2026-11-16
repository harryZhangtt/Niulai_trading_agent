# One-shot Colima activation transaction v5

This selected-disabled package closes the activation race between private root
creation and Colima process launch. It does not run by default.

The one-shot API accepts an explicit absolute workspace, acquires a cooperative
workspace-local `flock` through `O_NOFOLLOW`, creates only the exact private roots
transactionally, retains workspace/root file descriptors and device/inode
identities, then revalidates ancestors, identities, owner, mode and emptiness
immediately before an injected process runner. The lock and descriptors remain
held through child completion and status reconciliation.

Actual execution requires all three: `apply=True`, the exact activation
capability, and explicit parent approval. The subprocess implementation uses
`shell=False`, an allowlisted closed environment and workspace cwd. Tests inject
fake runners and probes; they never invoke Colima or Docker.

Success requires child exit zero plus an independent status probe proving the
exact profile is running, the expected context is rooted under the explicit
`DOCKER_CONFIG`, and global current context is unchanged. Timeout, daemon/status
uncertainty, or mismatch yields `unknown` and forbids blind retry. A failed start
is `failed` only when status proves no VM exists; then only empty directories
created by this attempt are removed deepest-first.

The lock is cooperative among conforming same-user processes. It does not prevent
a malicious same-user process from mutating paths outside this protocol; that
threat is explicit and outside the claim.
