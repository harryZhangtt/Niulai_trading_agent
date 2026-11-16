# Strict fixed Colima activation boundary v7

This selected-disabled version removes the nonfunctional fd-backed cwd claim. It
retains workspace/root fds and lock, immediately rechecks the exact workspace
pathname device/inode, then starts only with that exact pathname as cwd. Malicious
same-user mutation after that check remains explicitly outside scope.

Timeout always returns unknown with roots retained. The process is started in a
new session; timeout sends TERM, waits bounded grace, then always attempts KILL on
the original process group even if the leader exited, catching ProcessLookup and
bounding final leader reap.

Fixed status probes require return code zero, bounded output and strict JSON.
Success requires exact Colima profile/running state and an existing Unix socket
whose strict resolved path remains beneath strict resolved COLIMA_HOME with no
`..` or symlink escape, plus unchanged true global context.

Public activation has no injected runner/probe. Tests use a private seam and patch
fixed command helpers; no Colima or Docker command is called.
