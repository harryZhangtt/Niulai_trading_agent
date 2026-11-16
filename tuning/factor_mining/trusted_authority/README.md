# Trusted authority ports (candidate disabled)

This package defines provider-neutral contracts for durable checkpoint storage,
signer/key policy, recovery and purpose-specific authorization lookup. The tracked
`deployment-profile.json` is deliberately `candidate-disabled`: backend, signer,
key owner, recovery owner, checker and publication identities are null, every real
operation is false, and all blockers are mandatory.

The in-memory backend and HMAC signer are **synthetic conformance fixtures only**.
They exercise monotonic checkpoint chains, unknown-outcome reconciliation,
rotation/revocation, rollback-safe recovery and current purpose/payload/expiry
lookup. HMAC bytes in tests are not production credentials or an accepted signing
algorithm. `assert_active` always fails for the tracked profile.

Run from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/trusted_authority/tests -v
```

Allowed claim: authority backend/signer/recovery/authorization ports have a strict,
provider-neutral envelope and a bounded synthetic conformance harness.

Not established: a selected durable backend, non-resettable production history,
trusted cryptography or key custody, accepted recovery ownership, independent
checking, protected-label custody, real execution, promotion, performance, EV,
Kelly or publication authorization.
