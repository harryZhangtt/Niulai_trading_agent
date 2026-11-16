"""Disabled GCP activation scaffolding bound to the live frozen design.

The generated Terraform JSON is inert: every resource has literal ``count = 0``.
No cloud SDK, provider, backend, provisioner, credential, or apply operation exists.
"""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from factor.deployment import gcp_freeze


PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "activation-profile.json"
FREEZE_SHA256 = "593b5d6078ff6bdcb8d4777ae7123ae754a373b55b4e47433a5e9acd7ba7188d"
DESIGN_ID = "gcp-cloud-run-factor-mining-20261105-v1"
MAX_JSON = 2 * 1024 * 1024
ID = re.compile(r"[a-z][a-z0-9-]{2,62}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
TF_REF = re.compile(r"\$\{([a-z0-9_]+)\.([a-z0-9_]+)\.[^}]+\}")
RECEIPT_POLICY_VERSION = "gcp-factor-activation-receipts-v1"
BLOCKERS = [
    "gcp-billing-account-unconfigured", "gcp-organization-folder-unconfigured",
    "gcp-project-prefix-unconfigured", "gcp-projects-unprovisioned",
    "gcp-locations-unselected", "gcloud-principal-unverified", "gcp-apis-disabled",
    "gcp-service-accounts-unprovisioned", "gcp-storage-and-retention-unprovisioned",
    "gcp-kms-purpose-keys-unprovisioned", "gcp-cloud-run-jobs-unprovisioned",
    "gcp-vpc-firewall-vpcsc-unverified", "provider-entitlements-and-licenses-unverified",
    "protected-label-custody-unprovisioned", "account-side-conformance-unrun",
]
ACTIVATION_KEYS = (
    "create_projects", "enable_apis", "create_resources", "runtime_invocation",
    "protected_label_access", "publication", "production_bucket_lock", "enforce_vpc_sc",
)
PROJECT_KEYS = ("control", "execution", "custody")
RESOURCE_GROUPS = {
    "buckets": ("checkpoint_catalog", "audit_logs", "protected_labels"),
    "kms_keys": ("checkpoint", "evaluation", "checker", "publication", "revocation", "labels"),
    "jobs": ("checkpoint_gateway", "controller", "executor", "evaluator", "checker", "publisher"),
    "service_accounts": ("checkpoint", "controller", "executor", "evaluator", "checker",
                         "publisher", "checkpoint_signer", "evaluation_signer",
                         "checker_signer", "publication_signer", "revocation_signer"),
    "network": ("control_vpc", "control_subnet", "execution_vpc", "execution_subnet",
                "custody_vpc", "custody_subnet", "restricted_dns_zone",
                "executor_allow_firewall", "executor_deny_firewall", "vpc_sc_perimeter"),
    "workflows": ("publication",), "logging": ("audit_sink", "audit_bucket"),
}
ONBOARDING_COMMANDS = [
    "gcloud auth login", "gcloud auth application-default login",
    "gcloud billing accounts list", "gcloud projects list",
]
CLOSED_PERMISSIONS = {
    "checkpoint": ["storage.objects.create", "storage.objects.get"],
    "controller": ["run.jobs.run", "secretmanager.versions.access", "storage.objects.get", "storage.objects.create"],
    "executor": ["storage.objects.get", "storage.objects.create"],
    "evaluator": ["storage.objects.get", "storage.objects.create", "cloudkms.cryptoKeyVersions.useToDecrypt"],
    "checker": ["storage.objects.get", "storage.objects.create"],
    "checkpoint_signer": ["cloudkms.cryptoKeyVersions.useToSign"],
    "evaluation_signer": ["cloudkms.cryptoKeyVersions.useToSign"],
    "checker_signer": ["cloudkms.cryptoKeyVersions.useToSign"],
    "publication_signer": ["cloudkms.cryptoKeyVersions.useToSign"],
    "revocation_signer": ["cloudkms.cryptoKeyVersions.useToSign"],
    "publisher": ["storage.objects.get", "storage.objects.create", "workflows.callbacks.sendHttpCallback"],
}
FORBIDDEN_TERRAFORM_KEYS = {
    "provider", "backend", "provisioner", "local-exec", "remote-exec", "for_each",
}


class ActivationError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise ActivationError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "GCP_ACTIVATION_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_strict(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON, "GCP_ACTIVATION_JSON_SIZE")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _v: (_ for _ in ()).throw(
                               ActivationError("GCP_ACTIVATION_NONFINITE")))
    except ActivationError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise ActivationError("GCP_ACTIVATION_JSON_INVALID") from None
    require(type(value) is dict, "GCP_ACTIVATION_SCHEMA")
    return value


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise ActivationError("GCP_ACTIVATION_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _sha(value, code="GCP_ACTIVATION_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _time(value):
    require(type(value) is str and TIME.fullmatch(value), "GCP_ACTIVATION_TIME_INVALID")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ActivationError("GCP_ACTIVATION_TIME_INVALID") from None


def _verify_live_freeze():
    try:
        value = gcp_freeze.load_and_validate()
        raw = gcp_freeze.MANIFEST.read_bytes()
    except Exception:
        raise ActivationError("GCP_ACTIVATION_FREEZE_INVALID") from None
    require(value["design_id"] == DESIGN_ID and value["status"] == "frozen-disabled" and
            hashlib.sha256(raw).hexdigest() == FREEZE_SHA256,
            "GCP_ACTIVATION_FREEZE_MISMATCH")
    return value


def _resources_null():
    return {group: {name: None for name in names} for group, names in RESOURCE_GROUPS.items()}


def candidate_profile():
    return {
        "schema_version": 1, "kind": "gcp_factor_activation_profile",
        "design_id": DESIGN_ID, "freeze_manifest_sha256": FREEZE_SHA256,
        "trust_class": "candidate_real", "status": "selected-disabled",
        "apply_allowed": False, "billing_account_id": None, "organization_id": None,
        "folder_id": None, "project_prefix": None,
        "projects": {key: None for key in PROJECT_KEYS},
        "locations": {"primary_region": None, "dual_region": None, "kms_location": None},
        "gcloud_principal_sha256": None, "resources": _resources_null(),
        "activation": {key: False for key in ACTIVATION_KEYS},
        "activation_receipts": {key: None for key in ACTIVATION_KEYS},
        "synthetic_conformance_receipt_sha256": None,
        "runtime_acceptance_receipt_sha256": None,
        "explicit_owner_approval_sha256": None,
        "provider_configured": False, "backend_configured": False,
        "blockers": list(BLOCKERS),
    }


def _synthetic_profile_base():
    value = candidate_profile()
    value["trust_class"] = "synthetic_fixture"
    value["billing_account_id"] = "synthetic-billing"
    value["project_prefix"] = "synthetic-factor"
    value["projects"] = {"control": "synthetic-factor-control",
                         "execution": "synthetic-factor-exec",
                         "custody": "synthetic-factor-custody"}
    value["locations"] = {"primary_region": "synthetic-us-central1",
                          "dual_region": "synthetic-us",
                          "kms_location": "synthetic-us"}
    value["gcloud_principal_sha256"] = "a" * 64
    for group, entries in value["resources"].items():
        for name in entries:
            entries[name] = f"synthetic-{group.replace('_', '-')}-{name.replace('_', '-')}"
    return value


def profile_binding_sha256(profile):
    value = dict(profile)
    for key in ("synthetic_conformance_receipt_sha256",
                "runtime_acceptance_receipt_sha256", "explicit_owner_approval_sha256"):
        value[key] = None
    return digest(value)


def synthetic_profile():
    value = _synthetic_profile_base()
    receipts = synthetic_receipt_bundle(value)
    value["synthetic_conformance_receipt_sha256"] = digest(receipts["conformance"])
    value["runtime_acceptance_receipt_sha256"] = digest(receipts["runtime"])
    value["explicit_owner_approval_sha256"] = digest(receipts["approval"])
    return value


def validate_profile(value):
    _verify_live_freeze()
    if value == candidate_profile():
        return value
    require(value == synthetic_profile(), "GCP_ACTIVATION_PROFILE_INVALID")
    return value


def load_profile(path=PROFILE_PATH):
    try:
        return validate_profile(loads_strict(Path(path).read_bytes()))
    except OSError:
        raise ActivationError("GCP_ACTIVATION_PROFILE_UNAVAILABLE") from None


def onboarding_plan():
    return {
        "schema_version": 1, "kind": "gcp_factor_onboarding_plan",
        "design_id": DESIGN_ID, "freeze_manifest_sha256": FREEZE_SHA256,
        "owner": "human-account-owner", "interactive": True, "executed": False,
        "commands": list(ONBOARDING_COMMANDS),
        "required_confirmations": ["billing-account", "project-prefix",
                                   "primary-region", "dual-region"],
    }


def validate_onboarding(value):
    _verify_live_freeze()
    require(value == onboarding_plan(), "GCP_ONBOARDING_INVALID")
    return value


def _body(*, depends_on=(), **kwargs):
    value = {"count": 0, **kwargs}
    if depends_on:
        value["depends_on"] = list(depends_on)
    return value


def _add(resources, resource_type, name, body):
    resources.setdefault(resource_type, {})[name] = body


def _ref(resource_type, name, attribute):
    return "${" + resource_type + "." + name + "." + attribute + "}"


def _base_document(profile):
    projects, locations = profile["projects"], profile["locations"]
    resources = {}
    for concern in PROJECT_KEYS:
        _add(resources, "google_project", concern,
             _body(project_id=projects[concern], billing_account=profile["billing_account_id"]))
    services = ["storage.googleapis.com", "cloudkms.googleapis.com", "run.googleapis.com",
                "artifactregistry.googleapis.com", "secretmanager.googleapis.com",
                "compute.googleapis.com", "dns.googleapis.com", "workflows.googleapis.com",
                "logging.googleapis.com", "accesscontextmanager.googleapis.com",
                "iam.googleapis.com"]
    for concern in PROJECT_KEYS:
        project_ref = _ref("google_project", concern, "project_id")
        for service in services:
            _add(resources, "google_project_service", f"{concern}_{service.split('.')[0]}",
                 _body(project=project_ref, service=service, disable_on_destroy=False,
                       depends_on=[f"google_project.{concern}"]))
    role_concerns = {}
    for role, permissions in CLOSED_PERMISSIONS.items():
        concern = "execution" if role in {"controller", "executor"} else (
            "control" if role in {"checkpoint", "checkpoint_signer", "revocation_signer"}
            else "custody")
        role_concerns[role] = concern
        iam_api = f"google_project_service.{concern}_iam"
        project_ref = _ref("google_project", concern, "project_id")
        _add(resources, "google_project_iam_custom_role", role,
             _body(project=project_ref, role_id=f"factor_{role}", permissions=permissions,
                   stage="GA", depends_on=[iam_api]))
        _add(resources, "google_service_account", role,
             _body(project=project_ref, account_id=None, depends_on=[iam_api]))
    for bucket, concern in (("checkpoint_catalog", "control"), ("audit_logs", "control"),
                            ("protected_labels", "custody")):
        _add(resources, "google_storage_bucket", bucket,
             _body(project=_ref("google_project", concern, "project_id"),
                   location=locations["dual_region"], uniform_bucket_level_access=True,
                   public_access_prevention="enforced",
                   retention_policy=[{"is_locked": False, "retention_period": None}],
                   depends_on=[f"google_project_service.{concern}_storage"]))
    for concern in ("control", "custody"):
        _add(resources, "google_kms_key_ring", concern,
             _body(project=_ref("google_project", concern, "project_id"),
                   location=locations["kms_location"], name=f"factor-{concern}",
                   depends_on=[f"google_project_service.{concern}_cloudkms"]))
    for purpose in ("checkpoint", "evaluation", "checker", "publication", "revocation", "labels"):
        concern = "custody" if purpose in {"evaluation", "checker", "publication", "labels"} else "control"
        _add(resources, "google_kms_crypto_key", purpose,
             _body(name=f"factor-{purpose}",
                   key_ring=_ref("google_kms_key_ring", concern, "id"),
                   purpose="ENCRYPT_DECRYPT" if purpose == "labels" else "ASYMMETRIC_SIGN",
                   version_template={"algorithm": None if purpose == "labels" else "EC_SIGN_P256_SHA256"},
                   depends_on=[f"google_kms_key_ring.{concern}"]))
    for concern in PROJECT_KEYS:
        _add(resources, "google_compute_network", concern,
             _body(project=_ref("google_project", concern, "project_id"),
                   auto_create_subnetworks=False,
                   depends_on=[f"google_project_service.{concern}_compute"]))
        _add(resources, "google_compute_subnetwork", concern,
             _body(project=_ref("google_project", concern, "project_id"),
                   network=_ref("google_compute_network", concern, "id"),
                   private_ip_google_access=True,
                   depends_on=[f"google_compute_network.{concern}"]))
    _add(resources, "google_dns_managed_zone", "restricted_googleapis",
         _body(project=_ref("google_project", "execution", "project_id"), visibility="private",
               depends_on=["google_project_service.execution_dns",
                           "google_compute_network.execution"]))
    _add(resources, "google_compute_firewall", "executor_allow_restricted_vip",
         _body(network=_ref("google_compute_network", "execution", "id"), direction="EGRESS",
               priority=1000, destination_ranges=["199.36.153.4/30"],
               allow=[{"protocol": "tcp", "ports": ["443"]}],
               depends_on=["google_compute_network.execution"]))
    _add(resources, "google_compute_firewall", "executor_deny_all",
         _body(network=_ref("google_compute_network", "execution", "id"), direction="EGRESS",
               priority=65534, destination_ranges=["0.0.0.0/0"], deny=[{"protocol": "all"}],
               depends_on=["google_compute_firewall.executor_allow_restricted_vip"]))
    _add(resources, "google_access_context_manager_service_perimeter", "factor_data",
         _body(dry_run=True, services=["storage.googleapis.com", "cloudkms.googleapis.com"],
               depends_on=["google_project_service.control_accesscontextmanager",
                           "google_project_service.custody_accesscontextmanager"]))
    _add(resources, "google_logging_project_bucket_config", "audit",
         _body(project=_ref("google_project", "control", "project_id"), retention_days=None,
               locked=False, depends_on=["google_project_service.control_logging"]))
    _add(resources, "google_logging_project_sink", "audit",
         _body(project=_ref("google_project", "control", "project_id"),
               destination=_ref("google_logging_project_bucket_config", "audit", "id"),
               depends_on=["google_logging_project_bucket_config.audit"]))
    _add(resources, "google_workflows_workflow", "publication",
         _body(project=_ref("google_project", "custody", "project_id"), source_contents=None,
               service_account=_ref("google_service_account", "publisher", "email"),
               depends_on=["google_project_service.custody_workflows",
                           "google_service_account.publisher"]))
    job_roles = {"checkpoint_gateway": "checkpoint", "controller": "controller",
                 "executor": "executor", "evaluator": "evaluator",
                 "checker": "checker", "publisher": "publisher"}
    for name, role in job_roles.items():
        concern = role_concerns[role]
        _add(resources, "google_cloud_run_v2_job", name,
             _body(project=_ref("google_project", concern, "project_id"),
                   location=locations["primary_region"], name=f"factor-{name}",
                   template=[{"template": [{"containers": [{"image": None}],
                              "service_account": _ref("google_service_account", role, "email"),
                              "vpc_access": [{"network_interfaces": [{
                                  "network": _ref("google_compute_network", concern, "id"),
                                  "subnetwork": _ref("google_compute_subnetwork", concern, "id")}],
                                  "egress": "ALL_TRAFFIC"}]}]}],
                   depends_on=[f"google_project_service.{concern}_run",
                               f"google_service_account.{role}",
                               f"google_compute_subnetwork.{concern}"]))
    bucket_bindings = {
        "checkpoint_writer": ("checkpoint_catalog", "checkpoint"),
        "controller_handoff": ("checkpoint_catalog", "controller"),
        "executor_handoff": ("checkpoint_catalog", "executor"),
        "evaluator_labels": ("protected_labels", "evaluator"),
        "checker_labels": ("protected_labels", "checker"),
        "publisher_catalog": ("checkpoint_catalog", "publisher"),
    }
    for name, (bucket, member) in bucket_bindings.items():
        _add(resources, "google_storage_bucket_iam_member", name,
             _body(bucket=_ref("google_storage_bucket", bucket, "name"),
                   role=_ref("google_project_iam_custom_role", member, "name"),
                   member="serviceAccount:" + _ref("google_service_account", member, "email"),
                   depends_on=[f"google_storage_bucket.{bucket}",
                               f"google_project_iam_custom_role.{member}",
                               f"google_service_account.{member}"]))
    for purpose, member in (("checkpoint", "checkpoint_signer"),
                            ("evaluation", "evaluation_signer"),
                            ("checker", "checker_signer"),
                            ("publication", "publication_signer"),
                            ("revocation", "revocation_signer"),
                            ("labels", "evaluator")):
        _add(resources, "google_kms_crypto_key_iam_member", purpose,
             _body(crypto_key_id=_ref("google_kms_crypto_key", purpose, "id"),
                   role="roles/cloudkms.cryptoKeyDecrypter" if purpose == "labels" else "roles/cloudkms.signerVerifier",
                   member="serviceAccount:" + _ref("google_service_account", member, "email"),
                   depends_on=[f"google_kms_crypto_key.{purpose}",
                               f"google_service_account.{member}"]))
    _add(resources, "google_iam_deny_policy", "executor_forbidden_capabilities",
         _body(parent=_ref("google_project", "execution", "id"),
               display_name="Executor forbidden capabilities",
               rules=[{"deny_rule": {"denied_principals": [
                   "principal://iam.googleapis.com/projects/-/serviceAccounts/" +
                   _ref("google_service_account", "executor", "email")],
                   "denied_permissions": [
                       "cloudkms.googleapis.com/cloudkms.cryptoKeyVersions.useToSign",
                       "secretmanager.googleapis.com/secretmanager.versions.access"]}}],
               depends_on=["google_project.execution", "google_service_account.executor"]))
    return {"terraform": {"required_version": ">= 1.6.0"}, "resource": resources}


def _lock_document(profile):
    resources = {}
    for bucket in ("checkpoint_catalog", "audit_logs", "protected_labels"):
        _add(resources, "google_storage_bucket", bucket,
             _body(name=profile["resources"]["buckets"][bucket],
                   retention_policy=[{"is_locked": True, "retention_period": 86400}],
                   lifecycle_rule=[]))
    return {"terraform": {"required_version": ">= 1.6.0"}, "resource": resources}


def _receipt_common(value, kind, fields):
    require(type(value) is dict and set(value) == fields and value["schema_version"] == 1 and
            value["kind"] == kind and value["design_id"] == DESIGN_ID and
            value["freeze_manifest_sha256"] == FREEZE_SHA256 and
            value["policy_version"] == RECEIPT_POLICY_VERSION,
            "GCP_ACTIVATION_RECEIPT_INVALID")
    _sha(value["profile_binding_sha256"], "GCP_ACTIVATION_RECEIPT_INVALID")
    _sha(value["base_terraform_sha256"], "GCP_ACTIVATION_RECEIPT_INVALID")
    _time(value["issued_at"] if "issued_at" in value else value["approved_at"])
    return value


def validate_conformance_receipt(value, profile):
    fields = {"schema_version", "kind", "receipt_id", "design_id",
              "freeze_manifest_sha256", "policy_version", "profile_binding_sha256",
              "base_terraform_sha256", "checks_sha256", "status", "issued_at"}
    _receipt_common(value, "gcp_synthetic_conformance_receipt", fields)
    require(value["receipt_id"] == "synthetic-conformance-v1" and
            value["profile_binding_sha256"] == profile_binding_sha256(profile) and
            value["base_terraform_sha256"] == digest(_base_document(profile)) and
            value["status"] == "passed", "GCP_ACTIVATION_CONFORMANCE_INVALID")
    _sha(value["checks_sha256"], "GCP_ACTIVATION_CONFORMANCE_INVALID")
    return value


def validate_runtime_receipt(value, profile, conformance):
    fields = {"schema_version", "kind", "receipt_id", "design_id",
              "freeze_manifest_sha256", "policy_version", "profile_binding_sha256",
              "base_terraform_sha256", "conformance_receipt_sha256", "runtime_slot_id",
              "owner_identity_sha256", "status", "issued_at"}
    _receipt_common(value, "gcp_runtime_acceptance_receipt", fields)
    require(value["receipt_id"] == "synthetic-runtime-v1" and
            value["profile_binding_sha256"] == profile_binding_sha256(profile) and
            value["base_terraform_sha256"] == digest(_base_document(profile)) and
            value["conformance_receipt_sha256"] == digest(conformance) and
            type(value["runtime_slot_id"]) is str and ID.fullmatch(value["runtime_slot_id"]) and
            value["status"] == "passed" and _time(value["issued_at"]) >= _time(conformance["issued_at"]),
            "GCP_ACTIVATION_RUNTIME_INVALID")
    _sha(value["owner_identity_sha256"], "GCP_ACTIVATION_RUNTIME_INVALID")
    return value


def validate_owner_approval(value, profile, conformance, runtime):
    fields = {"schema_version", "kind", "receipt_id", "design_id",
              "freeze_manifest_sha256", "policy_version", "profile_binding_sha256",
              "base_terraform_sha256", "lock_terraform_candidate_sha256",
              "conformance_receipt_sha256", "runtime_acceptance_receipt_sha256",
              "owner_identity_sha256", "status", "approved_at", "irreversible"}
    _receipt_common(value, "gcp_bucket_lock_owner_approval", fields)
    require(value["receipt_id"] == "synthetic-owner-approval-v1" and
            value["profile_binding_sha256"] == profile_binding_sha256(profile) and
            value["base_terraform_sha256"] == digest(_base_document(profile)) and
            value["lock_terraform_candidate_sha256"] == digest(_lock_document(profile)) and
            value["conformance_receipt_sha256"] == digest(conformance) and
            value["runtime_acceptance_receipt_sha256"] == digest(runtime) and
            value["status"] == "approved" and value["irreversible"] is True and
            _time(value["approved_at"]) >= _time(runtime["issued_at"]),
            "GCP_ACTIVATION_APPROVAL_INVALID")
    _sha(value["owner_identity_sha256"], "GCP_ACTIVATION_APPROVAL_INVALID")
    return value


def synthetic_receipt_bundle(profile=None):
    profile = profile or _synthetic_profile_base()
    binding = profile_binding_sha256(profile)
    base_sha = digest(_base_document(profile))
    conformance = {
        "schema_version": 1, "kind": "gcp_synthetic_conformance_receipt",
        "receipt_id": "synthetic-conformance-v1", "design_id": DESIGN_ID,
        "freeze_manifest_sha256": FREEZE_SHA256, "policy_version": RECEIPT_POLICY_VERSION,
        "profile_binding_sha256": binding, "base_terraform_sha256": base_sha,
        "checks_sha256": "1" * 64, "status": "passed",
        "issued_at": "2026-11-05T00:00:00Z",
    }
    runtime = {
        "schema_version": 1, "kind": "gcp_runtime_acceptance_receipt",
        "receipt_id": "synthetic-runtime-v1", "design_id": DESIGN_ID,
        "freeze_manifest_sha256": FREEZE_SHA256, "policy_version": RECEIPT_POLICY_VERSION,
        "profile_binding_sha256": binding, "base_terraform_sha256": base_sha,
        "conformance_receipt_sha256": digest(conformance),
        "runtime_slot_id": "synthetic-future-slot-1", "owner_identity_sha256": "2" * 64,
        "status": "passed", "issued_at": "2026-11-05T01:00:00Z",
    }
    approval = {
        "schema_version": 1, "kind": "gcp_bucket_lock_owner_approval",
        "receipt_id": "synthetic-owner-approval-v1", "design_id": DESIGN_ID,
        "freeze_manifest_sha256": FREEZE_SHA256, "policy_version": RECEIPT_POLICY_VERSION,
        "profile_binding_sha256": binding, "base_terraform_sha256": base_sha,
        "lock_terraform_candidate_sha256": digest(_lock_document(profile)),
        "conformance_receipt_sha256": digest(conformance),
        "runtime_acceptance_receipt_sha256": digest(runtime),
        "owner_identity_sha256": "3" * 64, "status": "approved",
        "approved_at": "2026-11-05T02:00:00Z", "irreversible": True,
    }
    return {"conformance": conformance, "runtime": runtime, "approval": approval}


def validate_receipt_bundle(profile, receipts):
    require(type(receipts) is dict and set(receipts) == {"conformance", "runtime", "approval"},
            "GCP_ACTIVATION_RECEIPTS_INVALID")
    conformance = validate_conformance_receipt(receipts["conformance"], profile)
    runtime = validate_runtime_receipt(receipts["runtime"], profile, conformance)
    approval = validate_owner_approval(receipts["approval"], profile, conformance, runtime)
    require(profile["synthetic_conformance_receipt_sha256"] == digest(conformance) and
            profile["runtime_acceptance_receipt_sha256"] == digest(runtime) and
            profile["explicit_owner_approval_sha256"] == digest(approval),
            "GCP_ACTIVATION_RECEIPTS_MISMATCH")
    return receipts


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _validate_dag(document, code):
    resources = document["resource"]
    identities = {f"{resource_type}.{name}" for resource_type, values in resources.items()
                  for name in values}
    graph = {identity: [] for identity in identities}
    for resource_type, values in resources.items():
        for name, body in values.items():
            identity = f"{resource_type}.{name}"
            dependencies = body.get("depends_on", [])
            require(type(dependencies) is list and all(type(item) is str and item in identities
                    for item in dependencies), code)
            graph[identity] = dependencies
            for match in TF_REF.finditer(canonical(body).decode()):
                require(f"{match.group(1)}.{match.group(2)}" in identities, code)
    visiting, visited = set(), set()
    def visit(identity):
        require(identity not in visiting, code)
        if identity in visited:
            return
        visiting.add(identity)
        for dependency in graph[identity]:
            visit(dependency)
        visiting.remove(identity); visited.add(identity)
    for identity in sorted(identities):
        visit(identity)
    return document


def _validate_terraform(document, expected, code):
    require(document == expected and set(document) == {"terraform", "resource"} and
            set(document["terraform"]) == {"required_version"}, code)
    for by_name in document["resource"].values():
        require(type(by_name) is dict and by_name, code)
        for body in by_name.values():
            require(type(body) is dict and body.get("count") == 0, code)
    require(not (set(_walk_keys(document)) & FORBIDDEN_TERRAFORM_KEYS), code)
    return _validate_dag(document, code)


def render_base_terraform(profile):
    profile = validate_profile(profile)
    return _validate_terraform(_base_document(profile), _base_document(profile),
                               "GCP_TERRAFORM_BASE_INVALID")


def render_bucket_lock_terraform(profile, receipts):
    profile = validate_profile(profile)
    validate_receipt_bundle(profile, receipts)
    return _validate_terraform(_lock_document(profile), _lock_document(profile),
                               "GCP_TERRAFORM_LOCK_INVALID")


def _activation_plan(profile, base_document, lock_document, receipts=None):
    receipt_hashes = {"conformance": None, "runtime": None, "approval": None}
    receipts_ready = False
    if receipts is not None:
        validate_receipt_bundle(profile, receipts)
        receipt_hashes = {key: digest(value) for key, value in receipts.items()}
        receipts_ready = True
    return {
        "schema_version": 1, "kind": "gcp_factor_activation_plan",
        "design_id": DESIGN_ID, "freeze_manifest_sha256": FREEZE_SHA256,
        "status": "selected-disabled", "apply_allowed": False,
        "base_terraform_sha256": digest(base_document),
        "bucket_lock_terraform_candidate_sha256": digest(lock_document),
        "receipt_sha256s": receipt_hashes,
        "lock_gate_ready": receipts_ready,
        "activation_order": [
            {"stage": "projects-and-audit", "enabled": False, "irreversible": False, "requires": []},
            {"stage": "identities-and-iam", "enabled": False, "irreversible": False,
             "requires": ["projects-and-audit"]},
            {"stage": "storage-kms-network", "enabled": False, "irreversible": False,
             "requires": ["identities-and-iam"]},
            {"stage": "synthetic-conformance", "enabled": False, "irreversible": False,
             "requires": ["storage-kms-network"]},
            {"stage": "runtime-acceptance", "enabled": False, "irreversible": False,
             "requires": ["synthetic-conformance"]},
            {"stage": "vpc-sc-publication-readiness", "enabled": False, "irreversible": False,
             "requires": ["runtime-acceptance"]},
            {"stage": "production-bucket-lock", "enabled": False, "irreversible": True,
             "requires": ["synthetic-conformance-receipt", "runtime-acceptance-receipt",
                          "explicit-owner-approval"]},
        ],
    }


def validate_activation_plan(value, profile, base_document, lock_document, receipts=None):
    profile = validate_profile(profile)
    base_document = _validate_terraform(base_document, _base_document(profile),
                                        "GCP_TERRAFORM_BASE_INVALID")
    if receipts is not None:
        validate_receipt_bundle(profile, receipts)
    lock_document = _validate_terraform(lock_document, _lock_document(profile),
                                        "GCP_TERRAFORM_LOCK_INVALID")
    expected = _activation_plan(profile, base_document, lock_document, receipts)
    require(value == expected and value["base_terraform_sha256"] == digest(base_document) and
            value["bucket_lock_terraform_candidate_sha256"] == digest(lock_document) and
            value["activation_order"][-1]["stage"] == "production-bucket-lock",
            "GCP_ACTIVATION_PLAN_INVALID")
    return value


def render_activation_plan(profile, receipts=None):
    profile = validate_profile(profile)
    base = render_base_terraform(profile)
    lock = _validate_terraform(_lock_document(profile), _lock_document(profile),
                               "GCP_TERRAFORM_LOCK_INVALID")
    return validate_activation_plan(_activation_plan(profile, base, lock, receipts),
                                    profile, base, lock, receipts)
