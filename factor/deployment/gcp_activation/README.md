# Disabled GCP activation scaffolding

This package binds the frozen GCP design `gcp-cloud-run-factor-mining-20261105-v1`
to inert activation inputs and actual modeled Terraform JSON documents. It performs
no Google Cloud operation and contains no provider/backend block, credential,
service-account key, provisioner or apply operation.

The tracked candidate keeps billing, organization/folder, projects, locations,
principal, buckets, KMS keys, Jobs, service accounts, network, Workflows and logging
identities null. Every activation flag and receipt is false/null.

## Documents

- Base Terraform JSON contains only `terraform.required_version` and `resource`.
  Every resource has literal `count: 0`, valid Terraform references and an exact
  dependency DAG.
- Bucket Lock Terraform JSON is separate and cannot be rendered from the tracked
  candidate. Its synthetic path requires three complete, mutually bound records:
  synthetic conformance, runtime acceptance and explicit irreversible owner approval.
- Activation-plan metadata is separate from Terraform JSON. Bucket Lock is the final
  stage. Actual runtime/publication enablement is outside this disabled candidate and
  can happen only after account-side acceptance.
- The synthetic fixture populates fake identities for rendering but remains
  `selected-disabled`, `apply_allowed: false`, and every resource remains count zero.

The resource graph covers projects/APIs, service accounts, custom roles, exact bucket
and KMS bindings, Cloud Run Jobs, per-concern VPC/subnet references, restricted API
DNS/firewall intent, VPC-SC dry-run, Workflows and audit logging. Each checkpoint,
evaluation, checker, publication and revocation key has a distinct signer service
account and role; publication and revocation never share a principal. Executor
storage is bucket-scoped; signing and provider-secret permissions are explicitly
denied. Activation validation independently re-derives the canonical base and lock
Terraform documents, so recomputing a forged plan hash cannot bless altered project,
bucket or IAM content.

## Verify

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s factor/deployment/gcp_activation/tests -v
```

## User-owned onboarding commands

Recorded but never executed:

- `gcloud auth login`
- `gcloud auth application-default login`
- `gcloud billing accounts list`
- `gcloud projects list`

Account terms, billing, project prefix, locations and irreversible Bucket Lock
approval remain human-owned actions.

## Nonclaims

This is not an initialized Terraform backend, authenticated provider, account,
enabled API, IAM grant, bucket, key, network, Cloud Run Job, protected-label path,
runtime invocation or publication authorization. It has not been passed through the
Terraform binary or Google Cloud APIs. Account-side conformance and the workspace
future-runtime/email acceptance gate remain required.
