# Strict fixed local activation boundary v7

Date: 2026-11-06

Status: **selected-disabled**

V7 removes the false fd-backed-cwd claim. The transaction still holds the
workspace and root descriptors and cooperative lock, but immediately before spawn
it resolves and lstats the **exact workspace pathname**, requiring the same
workspace device/inode as the retained fd. Popen then uses that exact pathname as
cwd. A malicious same-user mutation after the check remains explicitly outside
scope and is not claimed prevented.

Timeout is always unknown with roots retained. The fixed runner starts a new
process session. After timeout it sends TERM to the process group, waits bounded
grace, then always attempts SIGKILL against the original process group even if the
leader exited, catches ProcessLookup, and performs a bounded leader reap. No
status observation can turn a timeout into failed/retryable.

Fixed probes require command return code exactly zero, bounded stdout/stderr and
strict JSON. Colima status must be exactly profile `factor-mining` and `Running`.
The Docker context must identify an absolute `unix://` endpoint without `..`; the
socket must exist, strictly resolve, be a Unix socket, and remain within strictly
resolved COLIMA_HOME without symlink escape. True host global context is captured
before and after and must remain identical.

The production public API accepts no runner/status injection. Tests use only the
private seam and patch fixed command helpers. They include a harmless real
`/bin/pwd -P` cwd check and a real process-group timeout case where the leader
exits on TERM while a descendant ignores TERM. No Colima or Docker command is
called by tests.

Frozen v6, v5, v4 and v2 artifacts are loaded and hash-bound. Passing this gate
does not establish actual VM/context/image/release/runtime readiness.
