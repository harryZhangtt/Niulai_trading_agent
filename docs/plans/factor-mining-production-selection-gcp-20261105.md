# Lightweight GCP factor-mining deployment selection

**Status:** FROZEN — DISABLED — 2026-11-05. This supersedes the AWS deployment candidate because the user has no AWS account and requires lower setup and credential overhead. The candidate is frozen by `factor/deployment/gcp-freeze-v1.json`; any byte or policy change requires a new version and full review. No Google Cloud account, billing project, API, key, bucket, VPC or job has been created.

## Objective

Use one Google identity/billing plane and scale-to-zero managed services while keeping controller, executor, protected labels, evaluator, checker, signer and publisher separated by projects, service accounts, storage/KMS policy and network boundaries.

## Project layout

### `factor-control`

- Cloud Storage dual-region checkpoint/catalog bucket with Bucket Lock only after acceptance.
- Sequence-named immutable checkpoint objects created only with generation precondition `ifGenerationMatch=0`; no mutable head.
- Five Cloud KMS `EC_SIGN_P256_SHA256` signing purposes: checkpoint, evaluation, independent checker, publication and revocation. Evaluator and checker never share a signing key.
- Cloud Run checkpoint/signing gateway with no label access.
- Aggregated Audit Logs sink and locked log bucket candidate.

### `factor-exec`

- Cloud Run Job controller with its own service account and Secret Manager provider-proxy references only.
- Separate Cloud Run Job executor using second-generation isolation and a dedicated service account with no standing provider, label, signing or publication permission.
- Artifact Registry images addressed only by immutable digest.
- Executor all-traffic Direct VPC egress with default-deny firewall and only explicit private Google API/storage paths. Container isolation alone is not treated as internet denial or proof that arbitrary hostile code is safe.

### `factor-custody`

- Protected-label Cloud Storage bucket encrypted with a separate CMEK and exact retained object versions.
- Fixed evaluator and independent-checker Cloud Run Jobs with separate service accounts and aggregate-only/redacted outputs.
- Workflows publication gate requiring checker attestation plus two distinct approval records over the exact manifest digest.
- Publisher has no label access; signer validates the complete immutable bundle.

A separate recovery project is not required initially: dual-region retained evidence and exported public verification keys provide continuity. Recovery never creates a concurrent writer and must append a signed epoch transition.

## Resolved dependencies

1. **Durable checkpoint backend:** retained sequence-addressed Cloud Storage objects, generation-match-zero create-only writes, contiguous signed chain, no mutable current object.
2. **Signing/custody:** Cloud KMS P-256 keys; key administrator cannot sign and each purpose service account can use only one key.
3. **Recovery/revocation:** no standing recovery role; time-bound restore into a recovery prefix/project plus signed epoch transition. Revocation disables future signing and appends a signed status record without deleting history.
4. **Checker/publication:** fixed independent checker Job, Workflows gate, two distinct approvals, separate publication signer and immutable catalog append.
5. **PIT data:** FRED/ALFRED for DFII5/DFF; FRED internal-use with licensed ICE fallback for BAMLC0A0CM; Databento PIT bars/actions for SPY/ONEQ, Massive fallback, Tiger cross-check only.
6. **Protected labels:** custody project bucket/key; ingest writes only, evaluator/checker exact-version reads only, executor no role.
7. **Linux platform:** separate Cloud Run Job per concern; no sidecars as trust boundaries.

## Why this is lightweight

- no Kubernetes cluster or node fleet;
- no self-managed servers;
- no cross-cloud identity;
- no always-on runner;
- Cloud Run Jobs scale to zero and support parallel tasks;
- three projects under one billing account;
- attached service accounts instead of static keys;
- one interactive `gcloud` login for provisioning.

## Credential and network model

- No service-account JSON keys.
- Human provisioning uses short-lived `gcloud`/ADC login.
- Workloads use dedicated attached service accounts.
- Provider credentials live in Secret Manager and are readable only by controller/provider-proxy identity.
- Executor receives no provider credential, protected label, KMS-signing or publication capability.
- Direct VPC all-traffic routing plus firewall and VPC Service Controls candidates contain egress; domain allowlists alone are insufficient.

## Minimum user actions

1. Create/sign into a Google Cloud account and enable billing or the free trial.
2. Run `gcloud auth login` and `gcloud auth application-default login` interactively.
3. Confirm project prefix and primary/dual-region location.
4. Explicitly approve irreversible production Bucket Lock only after disposable-bucket conformance.

Everything else can be prepared disabled with null project/resource identities.

## Disabled profile requirements

- `status=selected-disabled`
- billing account, projects, locations, buckets, KMS keys, Jobs, Workflows, service accounts, VPC/subnet/firewall and provider receipts null
- APIs disabled
- runtime invocation false
- protected-label access false
- publication false
- production retention lock false
- real values/outcomes forbidden
- `runnable=false`

## Security limits

- Cloud Run’s VMM/microVM, seccomp/Sandbox2 and namespace layers reduce risk but do not guarantee arbitrary generated code is safe.
- Sidecars share an instance network namespace and are not separate trust domains.
- Stateless execution does not prevent credential misuse or exfiltration; identity and egress must remain empty/denied for the executor.
- Bucket Lock is irreversible after locking and remains disabled until explicit approval.

## Official sources

- [Cloud Storage Bucket Lock](https://docs.cloud.google.com/storage/docs/bucket-lock)
- [Cloud Storage generation preconditions/API](http://googleapis.github.io/google-api-python-client/docs/dyn/storage_v1.objects.html)
- [Cloud KMS asymmetric algorithm reference](https://googleapis.dev/nodejs/kms/1.2.1/google.cloud.kms.v1.html)
- [Cloud Run Jobs](https://docs.cloud.google.com/run/docs/create-jobs)
- [Cloud Run security](https://docs.cloud.google.com/run/docs/securing/security)
- [Cloud Run Job service identity](https://docs.cloud.google.com/run/docs/configuring/jobs/service-identity)
- [Cloud Run Direct VPC egress](https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc)
- [VPC Service Controls](https://docs.cloud.google.com/vpc-service-controls/docs/overview)
- [Cloud KMS separation of duties](https://docs.cloud.google.com/kms/docs/separation-of-duties)
- [Cloud Audit Logs](https://docs.cloud.google.com/logging/docs/audit)

## Supersession and nonclaims

`factor-mining-production-selection-20261105.md` and AWS profiles are disabled comparison evidence only. They are not the activation path. This snapshot selects a candidate architecture but does not prove billing, projects, IAM, storage, KMS, networking, provider entitlement or runtime acceptance.
