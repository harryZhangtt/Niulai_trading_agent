# Probability authority vertical protocol

## Frozen question

Can one provider-free, process-owned guard prove issue-before-maturity chronology,
one-time protected outcome access, authority-computed scoring, three independent
reviews, and exact-scope transport/factor authorization while rejecting
producer-authored authority artifacts?

The experiment is falsified if a producer can read protected outcome bytes before
a valid grant after maturity, forge or backdate an accepted issuance, rewrite the
state head, reuse a receipt across identity/scope, or obtain authorization without
matured evidence and distinct reviews.

## Authority and identity

One `ProbabilityAuthority` instance is created in one OS process. It owns an
in-memory HMAC-SHA256 key, protected outcome bytes, the transition state, and the
canonical event chain. Producers get serialized public receipts only. Every
receipt binds exactly:

- target and event IDs;
- reset-day horizon and calendar ID;
- as-of timestamp and vintage SHA-256;
- attempt, variant, and holdout IDs;
- canonical forecast payload SHA-256.

The authority takes time only from an injected clock. Callers cannot supply event
times. Every event hashes its complete typed body and prior event hash. Every
state head hashes the prior state head and current event hash. The authority MACs
both the state head and complete receipt with separate domain prefixes.

## Legal sequence

1. `issue` before maturity.
2. `record_maturity` at/after the frozen maturity time.
3. `grant_protected_access` explicitly to the evidence collector, never producer.
4. `access_protected_outcome` exactly once using that grant.
5. `score` computes Brier score inside the authority and binds forecast/outcome.
6. `review` records approved data, statistics, and methodology reviews, using
   three distinct reviewers independent of producer, operator, and collector.
7. `authorize_transport` and `authorize_factor` require the complete exact review
   set and bind their complete purpose-specific scopes.

Replay, duplicate transition, wrong receipt type, unknown receipt, altered chain,
invalid MAC, wrong identity, and wrong authorization scope fail closed.

## Deterministic case

The sanitized case is one SOXL 126-reset-day event forecast. A fixed synthetic
clock and synthetic HMAC key make public evidence reproducible; the key and
outcome bytes are never included in the receipt. The outcome is synthetic and
establishes no probability quality or investment evidence.

## Effects and cleanup

The experiment performs no network access, email, holdings access, orders,
alerts, hooks, configuration, scheduler/runtime activation, or provider call.
The producer probe runs via an isolated Python subprocess in a temporary directory
under this experiment directory; the directory is removed before completion.

## Limits

This demonstrates an experiment process boundary, typed transition semantics,
and MAC authority against producer-authored public files. It is **not** security
against a hostile same-user process with debugger/process-memory/filesystem
privileges. The deterministic synthetic key is not production key management.
There is no durable key store, crash-safe ledger, process authentication, service
transport, cross-platform sandbox proof, real protected cohort, or intended-runtime
acceptance. O0 remains the rollback/default; no L3/L4, transport, factor, trade,
size, alert, or production activation claim follows.
