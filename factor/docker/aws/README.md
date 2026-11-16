# Selected-disabled AWS Fargate execution profile

This package records the selected AWS execution architecture without provisioning or
calling AWS. The tracked profile is `selected-disabled`, every account/Region/ARN/
subnet/security-group/image/endpoint identity is null, and `runnable` is always
false. The synthetic profile exists only for deterministic conformance tests.

## Separation

- Controller and executor are separate Fargate tasks, never sidecars.
- Controller may reach only the internal provider proxy.
- Executor has no public IP, NAT, internet-gateway route, IPv6 or default egress;
  only explicitly scoped ECR/S3/Logs/DynamoDB/KMS endpoints are admitted.
- Evaluator/checker capability intent is exact protected-label-version read in the
  custody account, but active access remains false until receipt-bound activation.
- Publisher capability intent is release-catalog append, but active publication is
  false and it cannot read labels or sign directly.
- Every task has a distinct task role, execution role, subnet and security group.

Every task is one container, digest-only, non-root, read-only, unprivileged, has all
capabilities dropped, no ECS Exec and no Docker socket. These declarations are
candidate policy, not evidence that AWS, networking, IAM or Fargate containment is
active.

## Verify

From the workspace root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m unittest discover \
  -s factor/docker/aws/tests -v
```

Allowed claim: a deterministic selected-disabled profile and inert task/network/IAM
policy templates fail closed on broad or combined concerns. Rendered templates include ECS trust
policies, execution-role ECR/Logs startup policies, concern-specific task-role
allows and explicit denies, exact-version label conditions, and VPC-endpoint
principal/source conditions. They are inert documents, not deployed IAM.

Not established: AWS accounts, entitlements, VPC endpoints, ECR images, Fargate
platform acceptance, hostile-code sandboxing, protected-label custody, a runnable
job, or factor quality.

Official design references:

- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-security-considerations.html
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/fargate-task-networking.html
- https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html
