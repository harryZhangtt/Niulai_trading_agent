# Initial factor admission policy

`initial-confirmatory-policy.json` freezes the choices that can be made before any
new target outcome is accessed. `policy.py` validates that exact policy and emits
a canonical SHA-256 identity. This is separate from the existing experiment guard:
it neither seals a protocol nor authorizes an attempt.

The policy is deliberately `draft_blocked`. Its inventory section must contain the
complete fixed blocker roster, all real-data and authority-policy identities remain
`null`, and performance, EV and Kelly publication remain false. Five P0 controls
must exist before any real run: one canonical non-resettable ledger authority;
trusted dataset/split attestation; a guard-issued runner nonce plus trusted terminal
receipt; an evaluator-derived complete verdict plus independent receipt; and
authorization-bound performance publication that is revalidated against current
quarantine state. Point-in-time authority, `T_seen`, stable observation/evaluation
population identities, exact chronological splits, fresh coverage/label maturity
and cost validity must also be established before a future protocol can bind this
policy. Do not edit this record to insert guessed hashes, receipts or dates.

Validate it from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/admission_policy/tests -v
```

Allowed claim: the first candidate's hypothesis, formula, universe, portfolio and
baseline mapping, execution/evaluation policy, multiplicity, budgets, decision
rules, controls, quarantine triggers and stopping rule are frozen in a deterministic
pre-outcome draft.

Not allowed: the policy is sealable; real source timing or licenses are verified;
fresh confirmation coverage exists; any protected split is identified; a run is
authorized; or any factor, EV or Kelly result is supported.
