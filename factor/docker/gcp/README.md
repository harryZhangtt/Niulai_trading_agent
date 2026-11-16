# Selected-disabled GCP Cloud Run Jobs profile

This package is an inert, standard-library contract for the lightweight GCP design in `docs/plans/factor-mining-production-selection-gcp-20261105.md`. It performs no `gcloud`/API call, loads no credential and cannot provision or run a Job.

The tracked candidate keeps billing/project/Region/bucket/key/job/image/network/service-account identities null, every activation flag false, and `runnable:false`. The synthetic fixture renders a modeled subset of the provider-native Cloud Run v2 Job resource plus separate local contract metadata. IAM, firewall, DNS and VPC-SC outputs are explicitly inert candidate policy specifications—not deployable provider API resources.

Concern boundaries:

- controller: provider-proxy reference only;
- executor: no secret, label, KMS-signing or publication capability; Direct VPC `all-traffic`, default-deny egress and explicit restricted storage path only;
- evaluator/checker: separate custody identities, exact-version label intent, aggregate-only structured output;
- publisher/signing gateway: separate identity and immutable catalog/workflow intent.

Every concern is a separate Cloud Run v2 Job resource using the modeled `Job.template.template` ExecutionTemplate→TaskTemplate shape. Sidecars and execution overrides are forbidden because containers in one instance share a network namespace and overrides can change reviewed semantics. Executor egress uses Direct VPC `ALL_TRAFFIC`, restricted Google API VIP `199.36.153.4/30`, private DNS, an allow-443 rule and a lower-priority deny-all rule; invocation grants `run.jobs.run` while explicitly denying `run.jobs.runWithOverrides`/job updates. Second-generation microVM/seccomp/Sandbox2 isolation does not prove arbitrary hostile code is safe; network, IAM, immutable-image, resource and outcome fences remain required.

Local contracts cover structural controller/executor receipts, exact object-version-bound evaluator/checker aggregate receipts, and an inactive publication catalog. They forbid raw joined rows, label emission and unstructured sensitive logs. These contracts are schemas and validators only; the corresponding fixed job binaries are not implemented or deployed here.

Verification:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover -s factor/docker/gcp/tests -v
```

Allowed claim: selected-disabled GCP runtime requirements and synthetic policy relationships fail closed offline.

Not established: Google account/billing, projects/APIs, Cloud Run isolation acceptance, VPC/firewall/VPC-SC enforcement, real images, protected-label access, provider credentials, execution or publication.

Official references:

- https://docs.cloud.google.com/run/docs/create-jobs
- https://docs.cloud.google.com/run/docs/securing/security
- https://docs.cloud.google.com/run/docs/configuring/jobs/service-identity
- https://docs.cloud.google.com/run/docs/configuring/vpc-direct-vpc
- https://docs.cloud.google.com/vpc-service-controls/docs/overview
