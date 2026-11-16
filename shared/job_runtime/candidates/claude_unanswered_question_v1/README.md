# Claude unanswered-question candidate v1

Inert, provider-free Track B scaffolding. It never calls a provider, network, process, or host API and cannot answer a real question. Live status is always `BLOCKED_HOST_CONTRACT_UNOBSERVED` until exact sanitized Claude Code 2.1.322 unanswered-question and answer-ack captures provide typed host authority.

Synthetic fixtures are non-authoritative. Their only safe capability is `local_noop_preference`; caller category is ignored as authority, every typed effect blocks, and normalized prompt/label/description scanning is defense in depth. The policy uses runtime-owned finite integer monotonic nanoseconds and becomes due at exactly 300,000,000,000 ns.

The owner-private ledger uses `fcntl.flock`, `O_NOFOLLOW`, regular-file/owner/mode/link checks, full writes, file and parent fsync, a strict hash chain and lock-file head seal. The durable `SUBMITTING` operation binds immutable question identity and ordered selected-option digest; `SUBMITTING`, `UNKNOWN`, and `ACKED` never replay.

The runtime adapter owns storage setup: its containing directory must already exist, then it calls `create_owner_private_directory()` for the final mode-0700 ledger parent before constructing `AnswerLedger`. `AnswerLedger` never creates a directory. It descriptor-walks every absolute parent component without following symlinks, pins the final directory device/inode, and rejects missing, replaced, non-owner, non-0700, or invalid-link parents.
