# Selected-disabled AWS factor authority

This package freezes the AWS authority selection from
`docs/plans/factor-mining-production-selection-20261105.md` without calling AWS or
creating an account, bucket, table, key, role, workflow or entitlement.

The selected design uses three accounts, a single writer Region, S3 Versioning and
Object Lock Compliance for immutable checkpoint and separately locked signed commit
receipts, DynamoDB transactions for the linear head plus durable idempotency item,
four purpose-separated multi-Region KMS P-256 signing keys, a locked CloudTrail
audit bucket, one-way CRR/RTC recovery and a Step Functions publication gate.
Every deployment identifier and owner is null, all activation flags are false, and
fifteen blockers remain mandatory.

Run the standard-library conformance tests from the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s tuning/factor_mining/trusted_authority/aws/tests -v
```

Allowed claim: the selected AWS requirements, separation and offline record
relationships are deterministic and fail closed in synthetic conformance tests.
Those records bind exact retained S3 versions/content/retention, idempotent
transaction identity, purpose-specific signed authorization, converged primary and
replica key status, revocation/history and signed fenced recovery epochs.

Not established: an AWS Organization/account/Region, retention policy, bucket,
table, KMS key, IAM owner, CloudTrail trail, replication rule, Step Functions
workflow, signature, recovery or publication authorization. The profile cannot be
activated by filling guessed ARNs.

Official references:

- S3 Object Lock: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-overview.html
- DynamoDB transactions: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html
- DynamoDB PITR: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Point-in-time-recovery.html
- KMS asymmetric keys: https://docs.aws.amazon.com/kms/latest/developerguide/symmetric-asymmetric.html
- Multi-Region KMS: https://docs.aws.amazon.com/kms/latest/developerguide/multi-region-keys-overview.html
- S3 replication: https://docs.aws.amazon.com/AmazonS3/latest/userguide/replication.html
- Step Functions callbacks: https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html
- CloudTrail integrity: https://docs.aws.amazon.com/awscloudtrail/latest/userguide/cloudtrail-log-file-validation-intro.html
