# Credential history candidate

This source adds structured persistent history to the existing remote credential
owner. It is staged, not active. `ACCEPTANCE.md` freezes the outcomes before code.
The original source/deployment and local uncertainty fence remain preserved.

The profile remains encrypted in R2. A checkpoint writes profile plus a sanitized
pending receipt atomically under the same ETag; D1 receives immutable metadata.
Exact D1 readback precedes conditional outbox pruning. History queries read only;
activation records an observed legacy baseline as unverified, never an old commit
acknowledgement. No credential/profile/cipher values belong in D1 or public output.

Implementation, exact isolated SQLite tests, rollback evidence and deployment
instructions will be added before activation. No active MCP or global change is
part of this candidate.
