# Claude 502 authority-process candidate v1

This additive candidate models the strict protocol and authority state machine for
a **future** separate process. It is disabled and inert: no socket binding,
process launch, CLI, provider import, environment read, or persistent key path.
Tests use only injected in-memory byte transport.

The authority owns one mutable generation key plus distinct runtime and registrar
capability buffers. Role, exact owner UID, capability, generation, frozen design
digest, caller-supplied bearer session ID, and authority-persisted per-session
sequence are authenticated inside authority dispatch. Registration is accepted
only with the registrar role and registrar capability.

Each operation runs under one lock against a deep copy. Mutation and the session
sequence are applied to that copy, then an append-only signed journal commit stores
the complete sanitized authority snapshot. Append failure or crash-before-commit
restores the prior snapshot. Crash-after-commit leaves memory and journal at the
same state. Recovery verifies generation, design digest, signature, entry digest,
sequence, and hash chain before restoring the latest committed snapshot.

Proofs bind the design digest, exact binding handle/digest, session, and request
sequence. Signed campaign states use one canonical payload for seal, transition,
and verification: exact body, predecessor handle, and optional `next_retry_at`.
Retry transition requires exact proof/state/template binding equality. Retry
authorization requires the cooldown and is one-shot.

Journal state contains only sanitized identifiers, hashes, handles, signed
artifacts, counters, timestamps, session metadata, and safe state. It never stores
key or capability bytes, prompt text/body, credentials, raw headers, or exception
text. Cleanup claims only generation revocation and best-effort mutable-buffer
zeroization. Socket removal, fsync, and process termination are explicitly
`UNOBSERVED_MODEL_ONLY`; this in-process model cannot verify them.

Threat boundary: the future OS process protects gateway/Engine memory from the
signing key. Kernel compromise, sufficiently privileged same-user tracing, and
arbitrary code execution inside that authority process are out of scope. This
harness does not establish OS isolation, a cross-process canary, intended-runtime
acceptance, activation, or production readiness.

Response trust is deliberately limited: the future authenticated owner-only OS
channel plus the one-run capability authenticates the responding authority.
HMAC artifacts are structurally and binding-validated by the client but are not
client-verifiable without sharing the authority key; a separate public-key design
would be required for offline client verification. Pre-transaction authentication
errors terminalize the session and the client refuses further sends.

Revocation is committed to the authoritative journal before best-effort key and
capability zeroization. Recovery therefore restores the revoked state and rejects
all subsequent operations.

Exchange outcomes are explicit: `PreSendFailure` alone proves no handoff and may
be retried at the same sequence. Any close, exception, partial response, or unknown
stage after handoff becomes `AUTHORITY_DISCONNECT_UNKNOWN`, terminalizes the
client, and prohibits replay until journal/state reconciliation. Session IDs are
caller-supplied bearer identifiers, not globally unique credentials. This model
does not claim resistance when a live capability is copied.

Every successful response is deterministically related to its exact request; any
post-handoff type, format, echo, handle, digest, provenance, timing, generation,
operation, session, or sequence mismatch is an unknown terminal outcome.
