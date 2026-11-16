# Factor-mining production dependency selection snapshot

**Status:** SELECTED — DISABLED — 2026-11-05. Official-source research completed; no account, key, bucket, table, provider entitlement, network or runtime has been provisioned. Every deployment identifier remains null until account-side receipts pass conformance.

## Decision objective

Resolve the seven external dependencies with the smallest managed architecture that preserves strict separation of execution, protected labels, evaluation, signing and publication while scaling without a self-managed cluster or VM fleet.

## Selected architecture

Use AWS only, split across three accounts and a second Region for recovery. This avoids two cloud identity planes and keeps the runtime serverless/task-based.

### Account A — compute

- ECS Fargate Linux controller task.
- Separate ECS Fargate Linux executor tasks; never sidecars in the controller task.
- Private ECR images addressed only by manifest digest.
- DynamoDB on-demand checkpoint index/head with transactional compare-and-set.
- S3 Object-Lock checkpoint/artifact bucket.
- Controller and executor have distinct task roles, task definitions, subnets and security groups.

### Account B — custody and release

- S3 Object-Lock bucket for protected-label versions and evaluation/release evidence.
- Separate Fargate evaluator and independent-checker tasks using fixed image digests.
- Step Functions Standard release workflow.
- Separate KMS signing keys for checkpoint, evaluation, publication and revocation statements.
- Publisher cannot read labels; evaluator/checker cannot publish or administer keys.

### Account C — recovery in a second Region

- Cross-account S3 replication into Object-Lock-enabled destination buckets.
- Multi-Region KMS replicas, with policies/grants/enabled state reviewed separately.
- DynamoDB PITR/backups plus deterministic reconstruction from the immutable checkpoint chain.
- Warm configuration only; no standing compute.

## Resolved seven dependencies

### 1. Durable checkpoint backend

**Selected:** S3 Versioning + Object Lock Compliance for immutable manifests, and a single-Region DynamoDB on-demand table for the linear committed head/index.

Append protocol:

1. Write canonical, signed manifest to a create-only S3 sequence key.
2. Use DynamoDB `TransactWriteItems` to add the immutable sequence row and update `HEAD` only when prior sequence/hash match.
3. Persist a deterministic idempotency key beyond DynamoDB’s short native token window.
4. Write a signed commit receipt to locked S3.
5. Readers verify strong-consistent `HEAD`, exact retained object-version ID, signatures and the chain to genesis.

Single writer Region only. Cross-Region copies are recovery evidence, never concurrent heads.

Official evidence:
- [S3 Object Lock](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock-overview.html)
- [DynamoDB transactions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis.html)
- [DynamoDB PITR](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Point-in-time-recovery.html)

### 2. Signing algorithm and key custodian

**Selected:** AWS-generated customer-managed, multi-Region KMS keys using `ECC_NIST_P256`, `SIGN_VERIFY`, ECDSA/SHA-256. Canonical payloads are SHA-256 hashed client-side and signed as digests.

Purpose-separated keys:

- checkpoint attestation;
- evaluation result;
- publication authorization;
- key-status/revocation statements.

Custody roles:

- `KmsKeyAdministrator`: lifecycle/policy/replica operations; explicitly no signing.
- `CheckpointSignerTaskRole`: checkpoint key only.
- `EvaluationSignerTaskRole`: evaluator key only.
- `PublicationSignerRole`: publication key only, assumed only by the final workflow state.
- `RevocationOfficerRole`: disable replicas/revoke grants/sign revocation state; no ordinary signing.

Asymmetric rotation is manual: create a new key/replicas, append a signed key-status record, switch the purpose alias, remove old signing permissions and retain old public keys for historical verification.

Official evidence:
- [AWS KMS asymmetric keys](https://docs.aws.amazon.com/kms/latest/developerguide/symmetric-asymmetric.html)
- [AWS KMS key policies](https://docs.aws.amazon.com/kms/latest/developerguide/key-policies.html)
- [Multi-Region KMS keys](https://docs.aws.amazon.com/kms/latest/developerguide/multi-region-keys-overview.html)
- [KMS rotation](https://docs.aws.amazon.com/kms/latest/developerguide/rotate-keys.html)

### 3. Recovery and revocation owners

**Selected role ownership:**

- `RecoveryOfficerRole`: no standing write/sign/decrypt access; time-bounded restore/reconstruction only after independent approval.
- `RevocationOfficerRole`: disable every Regional key copy, revoke grants, append signed revocation; cannot publish or read labels.
- `BackupVerifierRole`: read-only destination evidence and signature verification; cannot activate writer.
- `SecurityAuditRole`: read-only CloudTrail/audit evidence, no runtime administration.

Recovery is single-writer failover: fence primary, verify contiguous replicated chain, rebuild/restore head, append an epoch transition, then allow a new writer. Never merge two heads.

### 4. Independent checker and publication service

**Selected:** separate fixed-image Fargate evaluator and checker tasks in the custody account, followed by Step Functions Standard publication authorization.

Publication requires:

- exact committed checkpoint;
- evaluator signature;
- independently recomputed checker attestation;
- two distinct human approval records over the exact manifest digest;
- publication-key signature;
- immutable release catalog append.

Approvers cannot sign or publish; publisher cannot read labels; signer validates the complete bundle itself. Do not copy unauthenticated emailed callback links from tutorials; callbacks must be authenticated and one-time.

Official evidence:
- [Step Functions callback integration](https://docs.aws.amazon.com/step-functions/latest/dg/connect-to-resource.html)
- [Step Functions human approval tutorial](https://docs.aws.amazon.com/step-functions/latest/dg/tutorial-human-approval.html)

### 5. Licensed PIT providers for the five roles

#### DFII5 real yield

**Primary:** FRED/ALFRED `DFII5` using vintage dates plus observation `realtime_start`/`realtime_end`.

**Fallback:** Federal Reserve H.15 DDP value source; it is not equivalent vintage evidence unless releases were captured contemporaneously.

- [DFII5 series](https://fred.stlouisfed.org/series/DFII5)
- [FRED vintage dates API](https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html)
- [FRED observations API](https://fred.stlouisfed.org/docs/api/fred/series_observations.html)

#### BAMLC0A0CM corporate OAS

**Primary:** FRED/ALFRED `BAMLC0A0CM` for internal research, preserving vintage receipts.

**Fallback:** directly licensed ICE Consolidated History / ICE index entitlement.

ICE owns the series. FRED access does not grant publication, redistribution or third-party delivery. Raw values remain private and the account/order schedule must explicitly permit retention and intended use.

- [BAMLC0A0CM series](https://fred.stlouisfed.org/series/BAMLC0A0CM)
- [ALFRED series](https://alfred.stlouisfed.org/series?seid=BAMLC0A0CM)
- [ICE Consolidated History](https://www.ice.com/fixed-income-data-services/access-and-delivery/connectivity-and-feeds/ice-consolidated-history)
- [ICE data disclaimer](https://www.ice.com/fixed-income-data-services/data-and-analytics/disclaimer)

#### DFF cash rate

**Primary:** FRED/ALFRED `DFF` vintage workflow.

**Fallback:** New York Fed Markets Data API EFFR, contemporaneously archived because the opened API documentation does not provide an ALFRED-style revision ledger.

- [DFF series](https://fred.stlouisfed.org/series/DFF)
- [New York Fed Markets API](https://markets.newyorkfed.org/static/docs/markets-api.html)

#### SPY and ONEQ market data/actions

**Primary:** Databento US Equities Mini `EQUS.MINI` unadjusted `ohlcv-1d`, plus Reference corporate actions with `pit=True` and version timestamps. Reconstruct total return locally from only actions available at each cutoff.

**Fallback:** Massive unadjusted aggregate bars plus dividends/splits, admissible as strict PIT only with contemporaneous archives or a contracted correction feed.

Tiger Open API remains an execution/operational cross-check only until written retention/redistribution terms and action-revision timestamps are obtained.

- [Databento SPY catalog](https://databento.com/catalog/us-equities/EQUS.MINI/etf/SPY)
- [Databento ONEQ catalog](https://databento.com/catalog/us-equities/EQUS.MINI/etf/ONEQ)
- [Databento corporate actions](https://databento.com/docs/api-reference-reference/corporate-actions/corporate-actions-get-range)
- [Databento licensing/pricing](https://databento.com/pricing)
- [Massive aggregates](https://massive.com/docs/rest/stocks/aggregates/custom-bars)
- [Massive market-data terms](https://massive.com/legal/market-data-terms-of-service)
- [Tiger stock quote API](https://docs-en.itigerup.com/docs/quote-stock)
- [Tiger corporate actions](https://docs-en.itigerup.com/docs/corp-action-cpp)

### 6. Protected-label custodian

**Selected:** custody/release AWS account, separate Object-Lock S3 bucket and symmetric customer-managed label KMS key.

- `LabelIngestRole`: write/encrypt only.
- `EvaluationTaskRole`: read exact object versions/decrypt during fixed evaluator task only.
- `ControllerTaskRole` and `ExecutorTaskRole`: explicit bucket/key-policy deny.
- Raw joined prediction/label rows never leave custody.
- Evaluator emits only signed aggregate evidence.
- Break-glass read requires time-bound independent approval and alarmed audit evidence.

### 7. Accepted Linux execution platform

**Selected:** ECS Fargate Linux platform 1.4+, private ECR, separate task definitions for controller and executor.

Executor network:

- private IPv4-only subnet;
- no public IP, internet gateway route, NAT or IPv6;
- endpoint-only ECR/S3/CloudWatch/KMS/DynamoDB access;
- endpoint/resource policies scoped to executor role;
- no protected labels, signing or publication permissions;
- read-only root, non-root UID, dropped capabilities, no privileged mode and no ECS Exec.

Controller and executor must be different tasks because containers in one task share a network namespace/resources.

- [Fargate security](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html)
- [Fargate task networking](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html)
- [ECR VPC endpoints](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html)

## Minimality and future scale

Why this is the minimum adequate production candidate:

- no Kubernetes cluster;
- no self-managed hosts;
- no always-on runner/evaluator fleet;
- Fargate scales per task;
- DynamoDB is on-demand;
- S3/KMS/Step Functions are managed services;
- separation is enforced by accounts, IAM/key/bucket policies, networks and task roles rather than application conventions.

Unavoidable fixed complexity:

- three accounts and two Regions;
- private interface endpoints;
- four signing purposes and manual asymmetric-key rotation;
- locked retention makes mistaken objects undeletable until expiry;
- cross-account replication and quarterly recovery exercises.

## Disabled implementation snapshot

Implementation must begin with every switch false/null:

- `deployment_status = selected-disabled`
- account IDs and Regions: `null`
- bucket/table/key/task/workflow ARNs: `null`
- provider account/entitlement/license receipts: `null`
- runtime invocation: `false`
- publication: `false`
- Object Lock production retention lock: `false`
- protected-label access: `false`

Allowed now:

- strict schemas and candidate profiles;
- IAM/bucket/key/network/task-definition policy generation;
- conformance tests with synthetic accounts/ARNs;
- negative authorization/network/recovery tests;
- cost model with workload variables left explicit.

Not allowed before account receipts:

- API enablement/provisioning;
- creating accounts, buckets, keys, roles, endpoints or jobs;
- storing real values or labels;
- real runner/evaluator invocation;
- locking production retention;
- publishing factor performance, EV or Kelly.

## Double-verification checklist

- Verify every selected official URL is still current.
- Confirm Regions support Fargate, required VPC endpoints, S3 Object Lock, CRR/RTC and multi-Region KMS.
- Obtain written ICE and Databento retention/redistribution terms for this use.
- Verify FRED API terms and required attribution/non-endorsement.
- Confirm account ownership, approver groups and break-glass process.
- Price endpoint-hours, Fargate duration/concurrency, Object-Lock storage/replication, CloudTrail data events, DynamoDB transactions/PITR, KMS keys/signatures and Step Functions.
- Run synthetic IAM/network/rollback/recovery/publication conformance before changing any enable flag.

## Decision boundary

This snapshot selects the architecture and providers; it does not claim they are provisioned, entitled, active or accepted. Those facts require account-side receipts and the future runtime acceptance gate.
