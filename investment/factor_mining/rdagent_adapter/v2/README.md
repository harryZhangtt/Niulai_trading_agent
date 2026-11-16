# RD-Agent adapter v2 synthetic receipt boundary

This package is a fixture-only request/runner-receipt contract. It composes the
blocked admission policy, development-only authority nonce and synthetic PIT
dataset identities without executing RD-Agent, Qlib, generated code or protected
labels.

The raw nonce is supplied out of band to the fixed repository-owned runner. Only
its SHA-256 commitment appears in request, artifact and receipt data. `run_fixed`
requires the live `FixtureAuthority` and verifies the nonce and complete ledger
binding before one-time `RunnerState` consumption or dataset access. The request
has only an artifact-size bound; it does not advertise an unenforced timeout.

Run from the workspace root:

```sh
PYTHONWARNINGS=error::ResourceWarning PYTHONDONTWRITEBYTECODE=1 \
  python3 -B -m unittest discover \
  -s investment/factor_mining/rdagent_adapter/v2/tests -v
```

Allowed claim: after the live fixture authority validates and atomically claims
the nonce and attested dataset binding, a fixed synthetic worker emits an
outcome-free receipt solely from the request's authority, policy, dataset and
semantic-configuration identities. The runner does not open dataset or label files.

Not established: externally durable production nonce state, production isolation, generated-code
execution, RD-Agent/Qlib consumption, real/protected data access, scientific
verdicts, performance, alpha, EV, Kelly or publication authorization. V1 and v2 remain
separate versioned namespaces; this package makes no broader claim about v1 history.
