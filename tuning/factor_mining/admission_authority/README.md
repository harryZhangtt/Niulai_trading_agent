# Development-only factor admission authority

This package defines one fixed factor-admission authority namespace and a bounded
local ledger for **synthetic contract verification only**. The ledger path is
fixed by tracked policy as `factor/runtime/admission-authority`; public production
opening does not accept a caller-selected state path.

The structural fixture proves:

- tracked policy/genesis and workspace binding;
- monotonic global sequence and prior-event hash chain;
- immutable events plus an exact checkpoint;
- a validated synthetic PIT builder-receipt binding;
- one-time random fixture nonces and an atomic pre-execution claim event;
- permanent unknown/fenced state after a claimed nonce crashes before terminal receipt;
- full validation of the actual adapter-v2 request, runner receipt and structural-proof bytes;
- full validation of the actual evaluator request/receipt and exact runner lineage;
- truthful success/failure terminal events; hash-only receipt APIs are rejected;
- fail-closed mutation, stale/missing checkpoint, copied-root and nonce-reuse checks;
- deterministic authority implementation identity over behavior-bearing code and policy;
- stable pre-effect write failures separated from `AUTHORITY_WRITE_DURABILITY_UNKNOWN`;
- intended byte/hash/destination tracking and exact-readback reconciliation after
  link, replace or parent-directory fsync uncertainty; only an exact intended-byte
  readback is replayed, while missing, unavailable or different readback stays unknown;
- idempotent landed event/checkpoint completion without duplicate append;
- exact one-event orphan recovery under the authority lock when checkpoint
  publication failed before effect; and
- sanitized lock acquisition/cleanup and atomic I/O failures with
  immutable-conflict distinction.

It is deliberately `development-only-blocked`. It has no durable external
checkpoint store, trusted signer keys, accepted recovery policy, trusted runner,
evaluator, independent checker or publication policy. Deleting and explicitly
reprovisioning a local fixture is not a production reset defense. No real
protocol, protected outcome, performance, EV or Kelly publication is allowed.

The tracked admission policy remains `draft_blocked`; binding its SHA here freezes
identity but does not make it sealable.

Run the checks from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/admission_authority/tests -v
```

Allowed claim: a provider-free synthetic authority fixture detects local lineage,
checkpoint, binding and one-time nonce violations while keeping all scientific
and publication claims withheld.

Not established: process authenticity against a hostile same-user process,
non-resettable or externally durable production authority, signatures, independent
execution/evaluation, protected-label custody, real dataset acceptance, promotion
or publication authorization. Exact local readback plus a successful parent fsync
reconciles this fixture's retry decision; it is not proof of remote media durability
or an independently witnessed effect.
