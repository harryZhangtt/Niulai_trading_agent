# Selected-disabled GCP authority profile

This package encodes the lightweight GCP control-plane selection without creating or calling any Google Cloud resource. The tracked profile is exact, selected-disabled and contains only null deployment identities.

It specifies:

- three projects under one billing account;
- dual-region Cloud Storage checkpoints/catalog, Bucket Lock only after acceptance;
- sequence object names and `ifGenerationMatch=0`, with no mutable head;
- four purpose-separated Cloud KMS `EC_SIGN_P256_SHA256` keys;
- checkpoint/signing gateway, locked Audit Logs bucket and Workflows publication gate;
- recovery fencing and signed epoch transitions;
- no standing recovery role, no label access from control/execution, and no publication from evaluator.

The serializable fixture backend is a lock-protected conformance model. It requires provider-style object receipts with generation/metageneration, generation-match-zero, versioning and locked retention metadata, and demonstrates restart-persistent idempotency/unknown-outcome reconciliation; it is not Cloud Storage. Every signed validator requires an injected verifier and a tracked purpose-key registry; fixture HMAC is accepted only on `synthetic_fixture` records and is not Cloud KMS.

Publication authorization requires a cryptographically validated current checkpoint, current checkpoint/evaluation/checker/publication key statuses, a signed evaluation aggregate receipt, a separately signed independent-checker receipt and two distinct approvals signed by distinct approver keys over the same checkpoint, manifest and policy version. Recovery must be later than the prior checkpoint and uses a current revocation key. Cloud Storage metadata is accepted only through a verifier-derived provider receipt bound to request ID, ADC principal hash, API method/resource, raw-response commitment, generation/metageneration, generation-match-zero, versioning and locked retention state; callers cannot self-assert that receipt.

Run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/trusted_authority/gcp/tests -v
```

Allowed claim: selected GCP authority requirements and structural relationships fail closed offline.

Not established: billing, project ownership, Bucket Lock, retention duration, IAM, Cloud KMS custody, Audit Logs, Workflows, VPC controls, deployment, provider access, protected evaluation or publication.

Official references:

- https://docs.cloud.google.com/storage/docs/bucket-lock
- http://googleapis.github.io/google-api-python-client/docs/dyn/storage_v1.objects.html
- https://googleapis.dev/nodejs/kms/1.2.1/google.cloud.kms.v1.html
- https://docs.cloud.google.com/kms/docs/separation-of-duties
- https://docs.cloud.google.com/logging/docs/audit
