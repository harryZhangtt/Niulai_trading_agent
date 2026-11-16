# Synthetic point-in-time dataset contract

This package is a provider-free structural boundary for factor-mining data. It
validates and materializes the tracked `synthetic-pit-v1` fixture with Python's
standard library only. It does not import or execute RD-Agent or Qlib.

The contract keeps four identities distinct:

- `observation_set_sha256`: canonical source/series/calendar/universe/raw-vintage
  evidence, invariant to paths, row order, dataset names and repackaging;
- `label_commitment_sha256`: synthetic custodian commitment whose values are never
  returned in features, samples or builder receipts;
- `feature_snapshot_sha256`: observation identity plus the transform/execution
  policy and canonical feature rows;
- `evaluation_population_sha256`: observation set, label roster/commitment,
  target and semantic split policy used as the anti-relabeling population key.

Split fingerprints are derived from the evaluation population and ordered semantic
sample membership. Callers cannot supply them. Renaming sample aliases or a split
does not create fresh protected evidence. Calendar-position horizon, purge and
embargo checks, maturity cutoffs, source revision policies and role/foreign-key
checks fail closed before identities are emitted.

The builder receipt binds loaded function behavior plus the module constants,
regular expressions, closed ASCII artifact-path grammar, complete Decimal context
(precision, rounding, exponent bounds, capitals, clamp, empty flags and exact traps),
operator set and artifact roster that affect validation. It separately records the full feature artifact and
the requested cropped output scope/hash/count; it never derives code identity by
rereading a mutable source file.

The JSON Schemas document and test the exact structural envelope accepted by the
runtime where JSON Schema can express it. Runtime validators remain authoritative
for relational rules such as date ordering, count relationships, calendar links,
purge/embargo and hash reconciliation; schema validity alone is never acceptance.

Run the bounded checks from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s factor/dataset/tests -v
```

Allowed claim: the synthetic fixture deterministically validates, selects PIT
vintages, materializes features and derives stable evidence/split identities
without exposing its synthetic labels.

Not established: provider authenticity, historical real-data availability,
protected-label custody, engine consumption, predictive quality, economics,
alpha, EV, Kelly, or production readiness. Every real source and label authority
requires separately accepted receipts and the canonical admission authority.
