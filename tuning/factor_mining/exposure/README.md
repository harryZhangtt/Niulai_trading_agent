# Outcome-exposure inventory and fresh-split planner

This package records outcome access **without recording outcomes**. Each local
`SyntheticExposureLedger` receives a random immutable genesis/ledger identity and
is a deterministic development fixture, not canonical admission authority. Its
random immutable genesis makes every local root a distinct non-authoritative
identity; `t_seen` can only stay fixed or move later as evidence is added. Exposure
subjects use the closed `spy`, `oneq`, and `joint-spy-oneq` registry derived from the
tracked candidate source inventory's canonical entry and provider-route semantics—
callers cannot supply subject hashes. Missing or malformed semantic fields fail as
the stable sanitized `EXPOSURE_SUBJECT_INVENTORY_MISMATCH`, never a raw lookup
exception. Exposure writes also separate pre-effect failure from
`EXPOSURE_WRITE_DURABILITY_UNKNOWN`, retain intended bytes/hash/destination and
reconcile only exact event/head readback before retry; missing, unavailable or
different readback stays unknown and is never replayed. Filesystem enumeration, enum
shape and cleanup failures cross the public boundary only as stable
`ExposureError` codes. Duplicate identity uses subject, class and affected scope,
not event/evidence/provenance wrappers. Provenance limitations use a closed code vocabulary so metrics cannot be
smuggled through free text. A separately accepted durable backend must bind the
same history before a real protocol can seal.

`plan_fresh_splits_from_ledger` derives `t_seen` only from the reconstructed
ledger head and binds candidate memberships to explicit calendar, universe,
label-roster and source-inventory identity references. Validation begins after the
declared purge. Protected origins begin only after the last validation origin's
horizon maturity plus a second purge and embargo. Every selected origin must have
a mature horizon by `as_of_session`. Missing origins return
`inconclusive_awaiting_fresh_data`; older inspected history is never moved into a
protected role.

The public readiness result is always `blocked_nonsealable` and
`authoritative:false` while the tracked readiness blockers remain. It binds the
ledger genesis/head, the candidate-disabled `trusted_authority` deployment profile,
frozen admission-policy SHA, tracked source inventory, calendar/universe/label
identities, nullable dataset/observation/feature/evaluation identities and the
complete candidate plan digest/content. Runtime validation requires the exact
attested session list and deterministically recomputes every candidate membership;
structural JSON Schema validation alone is insufficient. A
new local root or caller-supplied earlier date cannot produce an authoritative
ready state. The low-level pure planner is private and also labels candidate
output as non-authoritative/non-sealable.

Run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/exposure/tests -v
```

Allowed claim: synthetic references are append-only/hash-chained and the planner
computes conservative candidate memberships without outcome values.

Not established: complete historical exposure inventory, authoritative `T_seen`,
accepted calendar/data custody, fresh coverage, a sealable protocol, scientific
verdict, performance, EV or Kelly publication.
