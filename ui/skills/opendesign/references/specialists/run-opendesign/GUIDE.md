---
name: run-opendesign
description: Serve only dedicated OpenDesign artifacts on loopback with an owned, bounded server and verify a real preview.
---

# Bounded local preview

Resolve the dedicated artifact root inside the workspace (normally
`ui/runtime/<task>/opendesign/`). Do not serve the repository root: it contains
private runtime state. Validate that the root contains the expected viewer and
manifest before starting.

Use Python's standard-library HTTP server bound to `127.0.0.1` and an available
ephemeral port, with `directory` set to the artifact root. Capture the process or
server-thread handle; bound the browser operation and explicitly stop/join that
owned server afterward. If a fixed port is requested and occupied, select a free
port or report the conflict; do not kill or reuse an unverified other process.
No npx install, global cache, privileged bind or daemon is required.

Verify the viewer responds, the manifest is valid JSON and an actual mockup can
be opened and interacted with through the browser. Test a missing artifact as a
failure rather than treating HTTP startup as success. Prevent path traversal and
symlink escape when supplying a custom server. Keep logs and screenshots under
the task's runtime directory. A preview handed back after its server is stopped
must be identified as an artifact/link for a later local run, not a live service.

The original fixed-port/background-server instructions are retained in
UPSTREAM-SKILL.md for provenance; this workspace's containment and lifecycle
rules take precedence.
