# Deterministic factor experiment guard

This package preserves factor-research decisions across turns, compaction and model changes. It controls whether evidence may be used; it does **not** run factors, prove alpha, or prevent a host user from deleting local files.

## Guarantees

- Protocols are strict, canonical JSON and are sealed by SHA-256 before outcome access.
- `(experiment_id, version)` cannot silently change.
- Every variant attempt is an atomically published, append-only, hash-chained record; semantic identity binds factor definitions, model, execution, evaluation, snapshot and split fingerprints, so renaming an unchanged factor is rejected while a genuinely changed specification is counted as a new variant.
- Trial-family budgets span protocol versions, and a protected-split fingerprint can be consumed only once across the ledger. A new version cannot reset either budget.
- Promotion requires every frozen gate plus an independent-check digest.
- Only promoted evidence can select a combination or authorize EV/Kelly publication.
- Declared overfitting triggers quarantine evidence immediately, including after promotion; prior authorization remains historical but all future use is refused.
- A quarantined result remains preserved and ineligible. Continued research requires a new parent-linked remediation protocol with a protected split unused by any ancestor.
- Remediation receives `fresh_validation` status only after all registered attempts finish; the original evidence is never upgraded or erased.
- Protocol/event publication uses no-follow directory descriptors, fsynced temporary files and atomic links; resealing repairs a protocol file left before its lifecycle event.
- The ledger is validated from disk on every operation and resumes in a fresh process.

The state machine is:

```text
sealed -> tested -> promoted | rejected
                 -> quarantined -> remediation_registered
promoted ----------------^  (new declared overfitting evidence)

remediation child: sealed -> fresh_validation -> promoted | rejected
                                  -> quarantined -> remediation_registered -> ...
```

Attempt events do not change lifecycle state. A quarantined/remediation-registered parent cannot support a combination, EV or Kelly; only a separately promoted child can.

## Protocol boundary

Copy `protocol.template.json` and replace every placeholder before sealing. Freeze:

- hypothesis and financial mechanism;
- point-in-time snapshot and development/validation/protected split fingerprints;
- factor families, exact transformations and maximum degrees of freedom;
- model and execution semantics;
- target, horizon, matched baseline, purge and embargo;
- multiplicity family/method and total variant budget;
- promotion criteria, stopping rule and numerical overfitting triggers.

A later exploratory idea uses a new unparented protocol; an overfitting repair uses a parent-linked remediation protocol. Neither may edit an existing version in place. The recent three-year period recovered from the shared history is development-only because it has already been inspected repeatedly.

A variant configuration has exactly one field, `factor_ids`, containing a unique subset of the sealed factor roster. The guard derives transformations, model, execution and complexity from the protocol; attempts cannot add lookahead fields, undeclared factors or run-time hyperparameters.

## CLI

Use an ignored private directory such as `tuning/runtime/factor-mining/<task-id>`:

```sh
python3 -I tuning/factor_mining/cli.py --state <state> seal \
  --protocol <protocol.json>
python3 -I tuning/factor_mining/cli.py --state <state> begin \
  --protocol-sha256 <sha> --variant-id <id> \
  --configuration <variant.json> --split development --split validation
python3 -I tuning/factor_mining/cli.py --state <state> finish \
  --protocol-sha256 <sha> --variant-id <id> --result succeeded \
  --evidence-sha256 <sha>
python3 -I tuning/factor_mining/cli.py --state <state> complete \
  --protocol-sha256 <sha> --evidence-sha256 <sha>
python3 -I tuning/factor_mining/cli.py --state <state> inspect \
  --protocol-sha256 <sha>
```

Use `quarantine` with a JSON object of predeclared trigger IDs to observed values. A remediation protocol names the quarantined parent SHA and must use a new protected-split fingerprint. Use `promote` only with a complete passing gate report. `authorize` is required before `combination_selection`, `ev_publication`, or `kelly_publication`.

CLI failures return only a stable code. Inputs are bounded regular files; the ledger stores hashes and declared metadata, not raw market data, prompts or credentials.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/tests -v
```

Tests cover canonical sealing, version conflicts, hidden retries, variant/holdout budgets, promotion, EV/Kelly authorization, quarantine, same-holdout rejection, fresh remediation, invalid transitions, tamper detection and fresh-process resume.

## Limits

The hash chain is tamper-evident, not an OS access-control boundary. The host still owns filesystem permissions, truthful metric production, protected-data isolation and independent review. A correctly promoted protocol establishes only that the declared guard conditions were met; it does not establish economic truth, future returns or safe position sizing.
