# Frozen persistent credential-history contract

Revision: credential-history-v2, 2026-11-16. User explicitly requested persistent
database storage after accepting that old history is unavailable. This candidate
adds future history; it does not remove the original local unknown fence.

Impact: staged host-impacting source until published. Owner remains the exact
existing owner-private Tiger Site/R2 object. D1 stores scalar immutable receipts,
not credentials. Activation boundary is one private deployment after isolated
lifecycle/failure/rollback checks. Affected effects are credential-store writes
and history projection only; no broker, new consent, scheduler, email, host hooks
or active MCP configuration. The original saved version is the rollback owner.

| ID | Action / observable requirement | Forbidden outcome |
| --- | --- | --- |
| CH-01 | Keep existing encrypted R2 profile and conditional ETag owner. New credential checkpoint and immutable receipt/outbox enter the same conditional write. | A new credential owner, destructive migration, profile value in D1, credential commit without durable pending receipt |
| CH-02 | New commit ID binds original lease ID, exact normalized profile digest and release request; replay reads the original receipt after other commits. | Matching commit ID with different lease/body acknowledged, most-recent-only lookup, invented old receipt |
| CH-03 | D1 metadata projection is idempotent and compared field-for-field before pending receipts are pruned by another conditional R2 write. | Pending receipt erased after failure/lost/mismatched projection; pruning a concurrent newer state |
| CH-04 | D1 unavailable/malformed/conflicting results preserve R2 pending state; bounded pending capacity rejects before a further credential write. | Unbounded retry, swallowed loss, empty success, indefinitely growing pending state |
| CH-05 | GET health/history are bounded and read-only, return only fixed metadata, and distinguish unrecorded legacy head, pending projection and projected history. | GET flush/lease/refresh, profile/cipher/key output, old history certified by an activation baseline |
| CH-06 | Schema-only D1 migration creates receipt/activation tables; one explicit idempotent activation records an observed legacy baseline as unverified. | Request-time DDL, copying credentials into SQL, changing past migration files, seeding synthetic credential data in production |
| CH-07 | Old acquire/checkpoint/release interfaces remain bounded; old source can read encrypted state after candidate rollback. Unknown local fences stay intact. | Breaking custody, dumping raw exceptions, widening read scopes, bypassing uncertainty to obtain live PASS |
| CH-08 | Exact source/SQL/pins frozen; real SQLite isolated tests cover restart/concurrency, before/after-ack failure, secret sinks and deliberate breaks. Native deployment/readback prove storage separately. | Mock-only query success, zero/skipped test PASS, source drift, hot host registration, scheduled acceptance claims |

Limits: history starts with checkpoints accepted by the new protocol. In-flight
legacy source may create a detectable gap; its missing history is not repaired by
baseline capture. R2 remains the authoritative pending outbox and credential
state; D1 remains the durable metadata history. The same-user host is not an OS
isolation boundary. Future scheduled runtime/business/email acceptance remains
unverified until the existing acceptance contract is exercised.
