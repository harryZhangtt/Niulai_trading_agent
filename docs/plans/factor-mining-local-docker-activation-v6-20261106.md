# Fixed local Colima activation boundary v6

Date: 2026-11-06

Status: **selected-disabled**

This version closes the production activation gaps left by the injectable v5
prototype. Public `activate()` accepts no runner or status-probe implementation.
Real execution requires explicit apply, the exact capability and parent approval,
then uses fixed internal Colima/Docker subprocess and parsing paths. Injection is
available only through a private test seam.

The transaction owns four private empty `0700` roots: Colima home, Colima cache,
Docker config, and workspace-local HOME. It holds workspace and final-root file
descriptors plus a cooperative `flock` through child completion. Immediately
before spawn it resolves/lstats the original workspace pathname and requires the
same device/inode as the held fd, then rechecks every root identity, mode, owner
and emptiness. The child cwd is `/dev/fd/<workspace_fd>` with that fd passed.

The environment is closed to six exact keys. The process uses `shell=False` and a
new session. Timeout always yields unknown, retains roots, sends process-group
TERM, waits a bounded grace, then KILLs if needed. It cannot become failed merely
because a status probe later says no VM.

Before spawn the launcher captures the true host-global Docker context using the
original HOME, not transaction `DOCKER_CONFIG`. After child completion fixed
commands parse Colima status and the named context from transaction Docker config,
then recapture global context. Success requires child zero, exact running profile,
context `colima-factor-mining`, Docker endpoint beneath `COLIMA_HOME`, and global
context unchanged. Mismatch or unavailable evidence is unknown; no blind retry.

The lock coordinates conforming same-user processes only. A malicious same-user
mutation after the immediate pre-spawn check is explicitly outside scope; this
contract does not overclaim prevention.

Tests patch fixed subprocess internals at the private seam only and perform no
Colima or Docker call. Frozen v5, v4 and v2 artifacts are loaded and hash-bound.
Passing tests does not establish real VM/context/image/release/runtime acceptance.
