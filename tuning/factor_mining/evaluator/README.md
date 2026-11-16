# Fixture-only factor evaluator receipt

This package consumes the frozen synthetic runner receipt v2 contract owned by
`investment/factor_mining/rdagent_adapter/v2/` and emits one deterministic,
outcome-free evaluator receipt. It binds the fixed admission authority, frozen admission
policy, synthetic dataset identities, split fingerprints, semantic configuration and
one-time nonce lineage. The evaluator does not duplicate or loosen the runner schema.
A request embeds the exact runner request, receipt and canonical outcome-free structural
proof, and is accepted only after the live `FixtureAuthority` verifies the recorded
runner event. Hash-only or shaped-but-unrecorded runner claims are rejected.

The receipt registers the complete frozen sensitivity, control and quarantine-trigger
rosters, but it does not evaluate them. It contains no labels, predictions, metrics,
p-values, intervals, positions or protected results. Its only scientific verdict and
performance claim are `withheld`; independent checking is `unavailable`.

Run from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/evaluator/tests -v
```

Allowed claim: a synthetic runner receipt can be structurally bound to a deterministic,
complete-roster evaluator receipt without outcome access.

Not established: trusted evaluator execution, independent checking, scientific
Pass/Fail/Inconclusive, promotion, performance publication, EV, Kelly, protected-label
custody or production readiness.
