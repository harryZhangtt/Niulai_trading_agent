# Fixed Colima activation boundary v6

The public API has no injectable runner or status attestation. Actual execution is
possible only with explicit apply, exact capability and parent approval, and then
uses fixed internal subprocess and reconciliation functions. Tests use the
private `_activate_for_test` seam and never invoke Colima or Docker.

The transaction adds a private workspace-local `HOME` root to the three v4 roots,
holds cooperative lock and directory FDs across child completion, revalidates the
workspace pathname device/inode immediately before spawn, launches with
`shell=False`, a closed environment, fd-backed cwd, `pass_fds`, and a new process
session. Timeout sends process-group TERM then KILL and is always unknown with
roots retained.

Success requires child zero plus independently parsed fixed Colima and Docker
status commands proving exact profile, context socket beneath `COLIMA_HOME`, and
unchanged true host global Docker context. Otherwise outcome is failed only when
no VM is proven, or unknown with no blind retry.

The lock remains cooperative; malicious same-user mutation after the final check
is explicitly outside scope and is not claimed prevented.
