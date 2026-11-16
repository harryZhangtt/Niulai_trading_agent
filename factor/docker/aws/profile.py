"""Strict selected-disabled AWS ECS Fargate execution profile.

This module validates and renders inert policy documents only. It performs no AWS
calls, loads no credentials, and cannot activate runtime or data access.
"""
import copy
import hashlib
import json
from pathlib import Path
import re


PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "runtime-profile.json"
MAX_BYTES = 512 * 1024
SHA_IMAGE = re.compile(r"[0-9]{12}\.dkr\.ecr\.[a-z0-9-]+\.amazonaws\.com/[a-z0-9._/-]+@sha256:[a-f0-9]{64}\Z")
ARN = re.compile(r"arn:aws:[a-z0-9-]+:[a-z0-9-]*:[0-9]*:[A-Za-z0-9_+=,.@:/!*?${}-]+\Z")
IAM_ARN = re.compile(r"arn:aws:iam::([0-9]{12}):role/[A-Za-z0-9_+=,.@/-]+\Z")
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,127}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
ROLES = ("controller", "executor", "evaluator", "checker", "publisher")
BLOCKERS = [
    "compute-account-unresolved", "custody-account-unresolved",
    "recovery-account-unresolved", "primary-region-unresolved",
    "recovery-region-unresolved", "controller-image-digest-unresolved",
    "executor-image-digest-unresolved", "evaluator-image-digest-unresolved",
    "checker-image-digest-unresolved", "publisher-image-digest-unresolved",
    "task-role-arns-unresolved", "execution-role-arns-unresolved",
    "private-subnets-unresolved", "security-groups-unresolved",
    "vpc-endpoints-unresolved", "provider-proxy-unresolved",
    "protected-label-version-policy-unresolved", "cloudtrail-audit-unresolved",
    "fargate-platform-acceptance-unverified", "account-receipt-unavailable",
    "network-receipt-unavailable", "image-receipt-unavailable",
    "label-policy-receipt-unavailable", "publication-policy-receipt-unavailable",
]
ENDPOINTS = {
    "controller": ["ecr.api", "ecr.dkr", "s3", "logs", "provider-proxy-internal"],
    "executor": ["ecr.api", "ecr.dkr", "s3", "logs", "dynamodb", "kms"],
    "evaluator": ["ecr.api", "ecr.dkr", "s3", "logs", "kms"],
    "checker": ["ecr.api", "ecr.dkr", "s3", "logs", "kms"],
    "publisher": ["ecr.api", "ecr.dkr", "s3", "logs", "states"],
}
INTENT = {
    "controller": {"provider_proxy": True, "protected_labels": False,
                   "kms_sign": False, "publication": False},
    "executor": {"provider_proxy": False, "protected_labels": False,
                 "kms_sign": False, "publication": False},
    "evaluator": {"provider_proxy": False, "protected_labels": True,
                  "kms_sign": False, "publication": False},
    "checker": {"provider_proxy": False, "protected_labels": True,
                "kms_sign": False, "publication": False},
    "publisher": {"provider_proxy": False, "protected_labels": False,
                  "kms_sign": False, "publication": True},
}
ACTIVE_ACCESS = {key: False for key in ("provider_proxy", "protected_labels",
                                        "kms_sign", "publication")}
ACCOUNT_OWNER = {
    "controller": "compute", "executor": "compute", "evaluator": "custody",
    "checker": "custody", "publisher": "custody",
}
COMMANDS = {
    "controller": ["factor-controller", "run"],
    "executor": ["factor-executor", "run"],
    "evaluator": ["factor-evaluator", "aggregate"],
    "checker": ["factor-checker", "recompute"],
    "publisher": ["factor-publisher", "append"],
}
OUTPUT_SCHEMAS = {
    "controller": "factor-controller-receipt-v1",
    "executor": "factor-executor-structural-v1",
    "evaluator": "factor-evaluator-aggregate-v1",
    "checker": "factor-checker-aggregate-v1",
    "publisher": "factor-publication-catalog-v1",
}
REDACTION_POLICY = "factor-no-sensitive-output-v1"
RESOURCE_FIELDS = {
    "ecr_repository_arns", "log_group_arns", "vpc_endpoint_ids",
    "ecr_layer_bucket_arn", "checkpoint_bucket_arn", "label_bucket_arn", "release_bucket_arn",
    "dynamodb_table_arn", "dataset_kms_key_arn", "label_kms_key_arn",
    "provider_proxy_arn", "publication_state_machine_arn", "label_object_version_id",
}
ACTIVATION_FIELDS = {
    "runtime_invocation", "protected_labels", "publication",
    "production_retention_lock", "account_receipt_sha256",
    "network_receipt_sha256", "image_receipt_sha256",
    "label_policy_receipt_sha256", "publication_policy_receipt_sha256",
}


class AwsProfileError(ValueError):
    """Stable sanitized profile rejection."""


def require(condition, code):
    if not condition:
        raise AwsProfileError(code)


def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "AWS_PROFILE_DUPLICATE_KEY")
        value[key] = item
    return value


def loads_strict(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "AWS_PROFILE_JSON_SIZE")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _v: (_ for _ in ()).throw(
                              AwsProfileError("AWS_PROFILE_NONFINITE")))
    except AwsProfileError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise AwsProfileError("AWS_PROFILE_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise AwsProfileError("AWS_PROFILE_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _id_list(value, code):
    require(type(value) is list and 1 <= len(value) <= 16 and
            all(type(item) is str and ID.fullmatch(item) for item in value), code)
    return value


def _task(value, role, *, synthetic):
    _strict(value, {"name", "account", "region", "image", "task_role_arn",
                    "execution_role_arn", "subnet_ids", "security_group_ids",
                    "assign_public_ip", "ipv6", "platform_version", "containers",
                    "read_only_root", "user", "privileged", "ecs_exec",
                    "capabilities_drop", "docker_socket", "endpoints", "command",
                    "output_schema_id", "redaction_policy_id", "stdout_policy",
                    "raw_joined_rows_output", "sensitive_logging", "aggregate_only",
                    "capability_intent", "active_access"}, "AWS_PROFILE_TASK_SCHEMA")
    require(value["name"] == role and value["account"] == ACCOUNT_OWNER[role] and
            value["assign_public_ip"] is False and value["ipv6"] is False and
            value["platform_version"] == "1.4.0" and value["containers"] == 1 and
            value["read_only_root"] is True and value["user"] == "65532:65532" and
            value["privileged"] is False and value["ecs_exec"] is False and
            value["capabilities_drop"] == ["ALL"] and value["docker_socket"] is False and
            value["endpoints"] == ENDPOINTS[role] and value["command"] == COMMANDS[role] and
            value["output_schema_id"] == OUTPUT_SCHEMAS[role] and
            value["redaction_policy_id"] == REDACTION_POLICY and
            value["stdout_policy"] == "structured-sanitized-only" and
            value["raw_joined_rows_output"] is False and value["sensitive_logging"] is False and
            value["aggregate_only"] is (role in {"evaluator", "checker"}) and
            value["capability_intent"] == INTENT[role] and
            value["active_access"] == ACTIVE_ACCESS, "AWS_PROFILE_TASK_SECURITY")
    if synthetic:
        require(type(value["region"]) is str and ID.fullmatch(value["region"]) and
                type(value["image"]) is str and SHA_IMAGE.fullmatch(value["image"]) and
                type(value["task_role_arn"]) is str and IAM_ARN.fullmatch(value["task_role_arn"]) and
                type(value["execution_role_arn"]) is str and IAM_ARN.fullmatch(value["execution_role_arn"]),
                "AWS_PROFILE_TASK_IDENTITY")
        _id_list(value["subnet_ids"], "AWS_PROFILE_SUBNETS")
        _id_list(value["security_group_ids"], "AWS_PROFILE_SECURITY_GROUPS")
    else:
        require(value["region"] is None and value["image"] is None and
                value["task_role_arn"] is None and value["execution_role_arn"] is None and
                value["subnet_ids"] == [] and value["security_group_ids"] == [],
                "AWS_PROFILE_TASK_MUST_BLOCK")


def _activation(value):
    _strict(value, ACTIVATION_FIELDS, "AWS_PROFILE_ACTIVATION_SCHEMA")
    require(value == {"runtime_invocation": False, "protected_labels": False,
                      "publication": False, "production_retention_lock": False,
                      "account_receipt_sha256": None, "network_receipt_sha256": None,
                      "image_receipt_sha256": None, "label_policy_receipt_sha256": None,
                      "publication_policy_receipt_sha256": None},
            "AWS_PROFILE_ACTIVATION_FORBIDDEN")


def _resources(value, *, synthetic):
    _strict(value, RESOURCE_FIELDS, "AWS_PROFILE_RESOURCE_SCHEMA")
    ecr = _strict(value["ecr_repository_arns"], set(ROLES), "AWS_PROFILE_ECR_SCHEMA")
    logs = _strict(value["log_group_arns"], set(ROLES), "AWS_PROFILE_LOG_SCHEMA")
    vpce = _strict(value["vpc_endpoint_ids"],
                   {"ecr_api", "ecr_dkr", "s3", "logs", "dynamodb", "kms",
                    "states", "provider_proxy"}, "AWS_PROFILE_ENDPOINT_SCHEMA")
    scalar = RESOURCE_FIELDS - {"ecr_repository_arns", "log_group_arns", "vpc_endpoint_ids"}
    values = list(ecr.values()) + list(logs.values()) + list(vpce.values()) + [value[key] for key in scalar]
    if synthetic:
        for item in list(ecr.values()) + list(logs.values()) + [value[key] for key in scalar - {"label_object_version_id"}]:
            require(type(item) is str and ARN.fullmatch(item), "AWS_PROFILE_RESOURCE_ARN")
        for item in vpce.values():
            require(type(item) is str and ID.fullmatch(item), "AWS_PROFILE_ENDPOINT_ID")
        require(type(value["label_object_version_id"]) is str and
                ID.fullmatch(value["label_object_version_id"]), "AWS_PROFILE_LABEL_VERSION")
    else:
        require(all(item is None for item in values), "AWS_PROFILE_RESOURCE_MUST_BLOCK")


def validate_profile(value):
    _strict(value, {"schema_version", "kind", "profile_id", "status", "runnable",
                    "trust_class", "platform", "accounts", "regions", "activation",
                    "resources", "network", "tasks", "controls", "blockers", "limitations"},
            "AWS_PROFILE_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_aws_fargate_profile" and
            value["profile_id"] == "factor-aws-fargate-v1" and
            value["status"] in {"selected-disabled", "synthetic-fixture"} and
            value["runnable"] is False and
            value["platform"] == {"launch_type": "FARGATE", "os": "LINUX",
                                  "platform_version": "1.4.0",
                                  "cpu_architectures": ["X86_64", "ARM64"]},
            "AWS_PROFILE_VERSION")
    synthetic = value["trust_class"] == "synthetic_fixture"
    require((synthetic and value["status"] == "synthetic-fixture") or
            (value["trust_class"] == "candidate_real" and
             value["status"] == "selected-disabled"), "AWS_PROFILE_TRUST")
    accounts = _strict(value["accounts"], {"compute", "custody", "recovery"}, "AWS_PROFILE_ACCOUNTS")
    regions = _strict(value["regions"], {"primary", "recovery"}, "AWS_PROFILE_REGIONS")
    if synthetic:
        require(all(type(item) is str and re.fullmatch(r"[0-9]{12}", item)
                    for item in accounts.values()) and len(set(accounts.values())) == 3,
                "AWS_PROFILE_ACCOUNTS")
        require(all(type(item) is str and ID.fullmatch(item) for item in regions.values()) and
                regions["primary"] != regions["recovery"], "AWS_PROFILE_REGIONS")
    else:
        require(all(item is None for item in accounts.values()) and
                all(item is None for item in regions.values()), "AWS_PROFILE_MUST_BLOCK")
    _activation(value["activation"])
    _resources(value["resources"], synthetic=synthetic)
    network = _strict(value["network"], {"executor", "controller", "custody"}, "AWS_PROFILE_NETWORK_SCHEMA")
    require(network == {"executor": {"private_ipv4": True, "public_ip": False,
                                     "internet_gateway": False, "nat_gateway": False,
                                     "ipv6": False, "default_egress": False,
                                     "endpoint_only": True},
                        "controller": {"private_ipv4": True, "public_ip": False,
                                       "provider_proxy_only": True},
                        "custody": {"private_ipv4": True, "public_ip": False,
                                    "label_bucket_endpoint_only": True}},
            "AWS_PROFILE_NETWORK_INVALID")
    tasks = _strict(value["tasks"], set(ROLES), "AWS_PROFILE_TASK_ROSTER")
    for role in ROLES:
        _task(tasks[role], role, synthetic=synthetic)
    if synthetic:
        all_role_arns = [tasks[role][key] for role in ROLES
                         for key in ("task_role_arn", "execution_role_arn")]
        require(len(set(all_role_arns)) == len(all_role_arns), "AWS_PROFILE_ROLE_REUSE")
        subnet_sets = [set(tasks[role]["subnet_ids"]) for role in ROLES]
        sg_sets = [set(tasks[role]["security_group_ids"]) for role in ROLES]
        require(all(not left.intersection(right) for i, left in enumerate(subnet_sets)
                    for right in subnet_sets[i + 1:]) and
                all(not left.intersection(right) for i, left in enumerate(sg_sets)
                    for right in sg_sets[i + 1:]), "AWS_PROFILE_NETWORK_REUSE")
        for role in ROLES:
            expected_account = accounts[ACCOUNT_OWNER[role]]; task = tasks[role]
            require(task["region"] == regions["primary"] and
                    task["image"].startswith(expected_account + ".dkr.ecr." + regions["primary"] + ".") and
                    IAM_ARN.fullmatch(task["task_role_arn"]).group(1) == expected_account and
                    IAM_ARN.fullmatch(task["execution_role_arn"]).group(1) == expected_account,
                    "AWS_PROFILE_ACCOUNT_BINDING")
    controls = ["digest-only-ecr", "one-container-per-task", "distinct-task-roles",
                "distinct-security-groups", "nonroot", "read-only-root",
                "drop-all-capabilities", "no-privileged", "no-ecs-exec",
                "no-docker-socket", "executor-no-internet", "exact-version-label-read",
                "no-runner-signing", "no-runner-publication"]
    require(value["controls"] == controls, "AWS_PROFILE_CONTROLS")
    if synthetic:
        require(value["blockers"] == [] and value["limitations"] == ["fixture-only", "not-runnable"],
                "AWS_PROFILE_FIXTURE_STATUS")
    else:
        require(value["blockers"] == BLOCKERS and
                value["limitations"] == ["selected-architecture-only", "no-aws-resources",
                                         "no-credentials", "not-runnable"],
                "AWS_PROFILE_BLOCKED_STATUS")
    return value


def load_profile(path=PROFILE_PATH):
    try:
        return validate_profile(loads_strict(Path(path).read_bytes()))
    except OSError:
        raise AwsProfileError("AWS_PROFILE_UNAVAILABLE") from None


def _object(resource, suffix):
    return None if resource is None else resource + suffix


def _allow(sid, actions, resources, *, vpce=None, extra_condition=None):
    condition = {}
    if vpce is not None:
        condition["StringEquals"] = {"aws:SourceVpce": vpce}
    if extra_condition:
        condition.setdefault("StringEquals", {}).update(extra_condition)
    return {"Sid": sid, "Effect": "Allow", "Action": actions,
            "Resource": resources, "Condition": condition}


def _deny(sid, actions, resources):
    return {"Sid": sid, "Effect": "Deny", "Action": actions,
            "Resource": resources, "Condition": {}}


def _execution_policy(profile, role):
    task = profile["tasks"][role]; resources = profile["resources"]
    return {"Version": "2012-10-17", "Statement": [
        _allow("EcrAuthorization", ["ecr:GetAuthorizationToken"], ["*"],
               vpce=resources["vpc_endpoint_ids"]["ecr_api"]),
        _allow("EcrImagePull", ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
                                 "ecr:BatchGetImage"], [resources["ecr_repository_arns"][role]],
               vpce=resources["vpc_endpoint_ids"]["ecr_dkr"]),
        _allow("WriteTaskLogs", ["logs:CreateLogStream", "logs:PutLogEvents"],
               [_object(resources["log_group_arns"][role], ":log-stream:*")],
               vpce=resources["vpc_endpoint_ids"]["logs"]),
    ]}


def _task_policy(profile, role):
    r = profile["resources"]; ep = r["vpc_endpoint_ids"]
    statements = []
    if role == "controller":
        statements.append(_allow("InvokeProviderProxy", ["execute-api:Invoke"],
                                 [r["provider_proxy_arn"]], vpce=ep["provider_proxy"]))
    elif role == "executor":
        statements.extend([
            _allow("ReadDataset", ["s3:GetObject"], [_object(r["checkpoint_bucket_arn"], "/datasets/*")], vpce=ep["s3"]),
            _allow("UseRunIndex", ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                   [r["dynamodb_table_arn"]], vpce=ep["dynamodb"]),
            _allow("DecryptDataset", ["kms:Decrypt"], [r["dataset_kms_key_arn"]], vpce=ep["kms"]),
        ])
    elif role in {"evaluator", "checker"}:
        statements.extend([
            _allow("ReadPredictionBundle", ["s3:GetObject"],
                   [_object(r["checkpoint_bucket_arn"], "/predictions/*")], vpce=ep["s3"]),
            _allow("ReadExactLabelVersion", ["s3:GetObjectVersion"],
                   [_object(r["label_bucket_arn"], "/labels/*")], vpce=ep["s3"],
                   extra_condition={"s3:VersionId": r["label_object_version_id"]}),
            _allow("DecryptLabels", ["kms:Decrypt"], [r["label_kms_key_arn"]], vpce=ep["kms"]),
        ])
    else:
        statements.extend([
            _allow("ReadReleaseEvidence", ["s3:GetObject"],
                   [_object(r["checkpoint_bucket_arn"], "/evaluation/*")], vpce=ep["s3"]),
            _allow("AppendReleaseCatalog", ["s3:PutObject"],
                   [_object(r["release_bucket_arn"], "/catalog/*")], vpce=ep["s3"]),
            _allow("CompletePublicationWorkflow", ["states:SendTaskSuccess", "states:SendTaskFailure"],
                   [r["publication_state_machine_arn"]], vpce=ep["states"]),
        ])
    if role not in {"evaluator", "checker"}:
        statements.append(_deny("DenyProtectedLabels", ["s3:GetObject", "s3:GetObjectVersion", "kms:Decrypt"],
                                [_object(r["label_bucket_arn"], "/labels/*"), r["label_kms_key_arn"]]))
    statements.append(_deny("DenySigning", ["kms:Sign"], ["*"]))
    if role != "publisher":
        statements.append(_deny("DenyPublication", ["s3:PutObject", "states:SendTaskSuccess", "states:SendTaskFailure"],
                                [_object(r["release_bucket_arn"], "/catalog/*"), r["publication_state_machine_arn"]]))
    return {"Version": "2012-10-17", "Statement": statements}


def _trust_policy(account_id, source_arn):
    return {"Version": "2012-10-17", "Statement": [{
        "Sid": "EcsTasksOnly", "Effect": "Allow",
        "Principal": {"Service": "ecs-tasks.amazonaws.com"},
        "Action": ["sts:AssumeRole"],
        "Condition": {"StringEquals": {"aws:SourceAccount": account_id},
                      "ArnLike": {"aws:SourceArn": source_arn}},
    }]}


def _endpoint_statement(sid, principals, actions, resources, vpce):
    return {"Sid": sid, "Effect": "Allow", "Principal": {"AWS": principals},
            "Action": actions, "Resource": resources,
            "Condition": {"StringEquals": {"aws:SourceVpce": vpce}}}


def _endpoint_policy(profile, endpoint):
    r = profile["resources"]; tasks = profile["tasks"]
    execution = [tasks[role]["execution_role_arn"] for role in ROLES]
    task = {role: tasks[role]["task_role_arn"] for role in ROLES}
    vpce = r["vpc_endpoint_ids"][endpoint]
    if endpoint == "ecr_api":
        statements = [_endpoint_statement("EcrAuthorization", execution,
                      ["ecr:GetAuthorizationToken"], ["*"], vpce)]
    elif endpoint == "ecr_dkr":
        statements = [_endpoint_statement("EcrImagePull", execution,
                      ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",
                       "ecr:BatchGetImage"], list(r["ecr_repository_arns"].values()), vpce)]
    elif endpoint == "logs":
        statements = [_endpoint_statement("TaskLogStreams", execution,
                      ["logs:CreateLogStream", "logs:PutLogEvents"],
                      [_object(value, ":log-stream:*") for value in r["log_group_arns"].values()], vpce)]
    elif endpoint == "s3":
        statements = [
            _endpoint_statement("EcrLayerObjects", execution, ["s3:GetObject"],
                                [r["ecr_layer_bucket_arn"]], vpce),
            _endpoint_statement("ExecutorDatasetObjects", [task["executor"]], ["s3:GetObject"],
                                [_object(r["checkpoint_bucket_arn"], "/datasets/*")], vpce),
            _endpoint_statement("CustodyPredictionObjects", [task["evaluator"], task["checker"]],
                                ["s3:GetObject"],
                                [_object(r["checkpoint_bucket_arn"], "/predictions/*")], vpce),
            _endpoint_statement("ExactProtectedLabelVersions", [task["evaluator"], task["checker"]],
                                ["s3:GetObjectVersion"],
                                [_object(r["label_bucket_arn"], "/labels/*")], vpce),
            _endpoint_statement("PublisherEvidenceRead", [task["publisher"]], ["s3:GetObject"],
                                [_object(r["checkpoint_bucket_arn"], "/evaluation/*")], vpce),
            _endpoint_statement("PublisherCatalogAppend", [task["publisher"]], ["s3:PutObject"],
                                [_object(r["release_bucket_arn"], "/catalog/*")], vpce),
        ]
    elif endpoint == "dynamodb":
        statements = [_endpoint_statement("ExecutorRunIndex", [task["executor"]],
                      ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
                      [r["dynamodb_table_arn"]], vpce)]
    elif endpoint == "kms":
        statements = [
            _endpoint_statement("ExecutorDatasetDecrypt", [task["executor"]], ["kms:Decrypt"],
                                [r["dataset_kms_key_arn"]], vpce),
            _endpoint_statement("CustodyLabelDecrypt", [task["evaluator"], task["checker"]],
                                ["kms:Decrypt"], [r["label_kms_key_arn"]], vpce),
        ]
    elif endpoint == "states":
        statements = [_endpoint_statement("PublisherCallback", [task["publisher"]],
                      ["states:SendTaskSuccess", "states:SendTaskFailure"],
                      [r["publication_state_machine_arn"]], vpce)]
    else:
        statements = [_endpoint_statement("ControllerProviderProxy", [task["controller"]],
                      ["execute-api:Invoke"], [r["provider_proxy_arn"]], vpce)]
    return {"Version": "2012-10-17", "Statement": statements}


def _render(profile):
    profile = validate_profile(profile)
    tasks = profile["tasks"]
    return {
        "schema_version": 1, "kind": "factor_aws_fargate_templates",
        "profile_sha256": digest(profile), "runnable": False,
        "activation": copy.deepcopy(profile["activation"]),
        "task_definitions": [{
            "family": "factor-" + role, "launch_type": "FARGATE",
            "platform_version": "1.4.0", "container_count": 1,
            "image": tasks[role]["image"], "task_role_arn": tasks[role]["task_role_arn"],
            "execution_role_arn": tasks[role]["execution_role_arn"],
            "readonly_root_filesystem": True, "user": "65532:65532",
            "privileged": False, "ecs_exec": False,
            "linux_capabilities_drop": ["ALL"], "command": list(COMMANDS[role]),
            "output_schema_id": OUTPUT_SCHEMAS[role],
            "redaction_policy_id": REDACTION_POLICY,
            "stdout_policy": "structured-sanitized-only",
            "raw_joined_rows_output": False, "sensitive_logging": False,
            "aggregate_only": role in {"evaluator", "checker"},
            "active_access": copy.deepcopy(ACTIVE_ACCESS),
        } for role in ROLES],
        "trust_policies": {role: {
            "task": _trust_policy(profile["accounts"][ACCOUNT_OWNER[role]],
                                  None if profile["accounts"][ACCOUNT_OWNER[role]] is None or
                                  profile["regions"]["primary"] is None else
                                  "arn:aws:ecs:{}:{}:task/*".format(
                                      profile["regions"]["primary"],
                                      profile["accounts"][ACCOUNT_OWNER[role]])),
            "execution": _trust_policy(profile["accounts"][ACCOUNT_OWNER[role]],
                                       None if profile["accounts"][ACCOUNT_OWNER[role]] is None or
                                       profile["regions"]["primary"] is None else
                                       "arn:aws:ecs:{}:{}:task/*".format(
                                           profile["regions"]["primary"],
                                           profile["accounts"][ACCOUNT_OWNER[role]])),
        } for role in ROLES},
        "execution_role_policies": {role: _execution_policy(profile, role) for role in ROLES},
        "task_role_policies": {role: _task_policy(profile, role) for role in ROLES},
        "endpoint_policies": {endpoint: _endpoint_policy(profile, endpoint)
                              for endpoint in profile["resources"]["vpc_endpoint_ids"]},
        "network": copy.deepcopy(profile["network"]),
    }


def render_templates(profile):
    """Render deterministic inert policies. Null candidate fields remain non-deployable."""
    return _render(profile)


def validate_templates(value, profile):
    require(value == _render(profile), "AWS_TEMPLATE_INVALID")
    return value
