"""Strict, inert AWS authority selection and signed-record conformance.

No AWS SDK is imported and no AWS resource is created. Every signed-record
validator requires an injected verifier; fixture cryptography belongs in tests.
"""
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Protocol

PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "deployment-profile.json"
MAX_JSON = 256 * 1024
SHA = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[a-z0-9][a-z0-9_.:-]{0,127}\Z")
VERSION_ID = re.compile(r"[A-Za-z0-9._-]{1,256}\Z")
ARN = re.compile(r"arn:aws[a-z-]*:[a-z0-9-]+:[a-z0-9-]*:[0-9]{0,12}:[A-Za-z0-9_./:=+@-]+\Z")
KMS_ARN = re.compile(r"arn:aws:kms:([a-z0-9-]+):([0-9]{12}):key/(mrk-[A-Za-z0-9-]+)\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
PURPOSES = ("checkpoint", "evaluation", "publication", "revocation")
PUBLICATION_PURPOSES = ("performance_publication", "combination_selection",
                        "ev_publication", "kelly_publication")
ROLE_NAMES = ("kms_key_administrator", "checkpoint_signer", "evaluation_signer",
              "publication_signer", "revocation_officer", "recovery_officer",
              "backup_verifier", "security_auditor")
BLOCKERS = ["aws-organization-unprovisioned", "compute-account-unassigned",
    "custody-account-unassigned", "recovery-account-unassigned",
    "primary-region-unselected", "recovery-region-unselected",
    "s3-object-lock-retention-unapproved", "checkpoint-bucket-unprovisioned",
    "dynamodb-table-unprovisioned", "kms-purpose-keys-unprovisioned",
    "cloudtrail-audit-bucket-unprovisioned", "crr-rtc-unverified",
    "step-functions-publication-unprovisioned", "iam-role-owners-unassigned",
    "account-side-conformance-unrun"]
SIGNATURE_FIELDS = {"signer_key_version", "signer_public_key_sha256",
                    "signature_encoding", "signature"}
LOCKED_OBJECT_KEYS = {"bucket_arn", "key", "version_id", "content_sha256",
    "verified_at", "retain_until", "minimum_retention_days", "object_lock_mode",
    "delete_marker"}
KEY_STATUS_KEYS = {"schema_version", "kind", "key_id", "purpose", "primary_key_arn",
    "replica_key_arn", "alias", "public_key_sha256", "status", "effective_at",
    "previous_status_sha256", "primary_enabled", "replica_enabled", "grants_revoked",
    "policy_sha256"} | SIGNATURE_FIELDS
RECEIPT_KEYS = {"schema_version", "kind", "epoch", "sequence", "manifest_sha256",
    "checkpoint_object_sha256", "issued_at"} | SIGNATURE_FIELDS
COMMIT_KEYS = {"schema_version", "kind", "epoch", "sequence",
    "previous_manifest_sha256", "manifest_sha256", "idempotency_key",
    "checkpoint_object", "commit_receipt", "commit_receipt_object", "writer_region",
    "key_status_sha256", "recovery_transition_sha256", "create_only", "single_writer"} | SIGNATURE_FIELDS
AUTHORIZATION_KEYS = {"schema_version", "kind", "authorization_id", "epoch",
    "sequence", "checkpoint_sha256", "purpose", "payload_sha256", "key_status_sha256",
    "issued_at", "expires_at", "state"} | SIGNATURE_FIELDS
RECOVERY_KEYS = {"schema_version", "kind", "from_region", "to_region", "new_epoch",
    "prior_manifest_sha256", "prior_checkpoint_sha256", "primary_fenced",
    "chain_verified", "merge_heads", "key_status_sha256", "issued_at"} | SIGNATURE_FIELDS


class AwsAuthorityError(ValueError): pass
class UnknownOutcome(AwsAuthorityError): pass

class SignatureVerifier(Protocol):
    def verify(self, unsigned_bytes, signature, *, encoding, key_version,
               public_key_sha256, purpose): ...


def require(condition, code):
    if not condition: raise AwsAuthorityError(code)

def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "AWS_AUTHORITY_DUPLICATE_KEY"); result[key] = value
    return result

def loads_strict(raw):
    if isinstance(raw, str): raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON, "AWS_AUTHORITY_JSON_SIZE")
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
            parse_constant=lambda _v: (_ for _ in ()).throw(AwsAuthorityError("AWS_AUTHORITY_NONFINITE")))
    except AwsAuthorityError: raise
    except (TypeError, ValueError, UnicodeError): raise AwsAuthorityError("AWS_AUTHORITY_JSON_INVALID") from None
    require(type(value) is dict, "AWS_AUTHORITY_JSON_INVALID"); return value

def canonical(value):
    try: return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError): raise AwsAuthorityError("AWS_AUTHORITY_JSON_INVALID") from None

def digest(value): return hashlib.sha256(canonical(value)).hexdigest()
def clone(value): return loads_strict(canonical(value))
def _strict(value, keys, code): require(type(value) is dict and set(value) == set(keys), code); return value
def _sha(value, code="AWS_AUTHORITY_SHA_INVALID"): require(type(value) is str and SHA.fullmatch(value), code); return value
def _optional_sha(value, code="AWS_AUTHORITY_SHA_INVALID"): require(value is None or type(value) is str and SHA.fullmatch(value), code); return value
def _id(value, code="AWS_AUTHORITY_ID_INVALID"): require(type(value) is str and ID.fullmatch(value), code); return value
def _arn(value, code="AWS_AUTHORITY_ARN_INVALID"): require(type(value) is str and ARN.fullmatch(value), code); return value
def _time(value):
    require(type(value) is str and TIME.fullmatch(value), "AWS_AUTHORITY_TIME_INVALID")
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError: raise AwsAuthorityError("AWS_AUTHORITY_TIME_INVALID") from None
    require(parsed.utcoffset().total_seconds() == 0, "AWS_AUTHORITY_TIME_INVALID"); return parsed

def _null_map(keys): return {key: None for key in keys}
def _unsigned(value): return {key: value[key] for key in value if key != "signature"}
def _signature_fields(value, code):
    _id(value["signer_key_version"], code); _sha(value["signer_public_key_sha256"], code)
    require(value["signature_encoding"] in {"ECDSA_DER_BASE64", "FIXTURE_HMAC_SHA256_HEX"} and
            type(value["signature"]) is str and 1 <= len(value["signature"]) <= 4096, code)

def _verify(value, verifier, purpose, code):
    require(verifier is not None and callable(getattr(verifier, "verify", None)), code)
    _signature_fields(value, code)
    try:
        result = verifier.verify(canonical(_unsigned(value)), value["signature"],
            encoding=value["signature_encoding"], key_version=value["signer_key_version"],
            public_key_sha256=value["signer_public_key_sha256"], purpose=purpose)
    except Exception:
        raise AwsAuthorityError(code) from None
    require(result is True, code)


def expected_profile():
    return {"schema_version":1,"kind":"aws_factor_authority_deployment_profile",
      "selection_id":"aws-fargate-authority-20261105-v1","provider":"aws",
      "status":"selected-disabled","activation_allowed":False,
      "real_operations_allowed":False,"protected_outcomes_allowed":False,"publication_allowed":False,
      "accounts":_null_map(("compute","custody_release","recovery")),
      "regions":_null_map(("primary","recovery")),
      "checkpoint":{"s3_bucket_arn":None,"commit_receipt_bucket_arn":None,
        "dynamodb_table_arn":None,"retention_days":None,"object_lock_mode":"COMPLIANCE",
        "versioning_required":True,"pitr_days":35,"single_writer_region":True,
        "create_only_sequence_objects":True,"strongly_consistent_head":True,
        "idempotency_item_required":True},
      "kms_keys":{purpose:{"key_arn":None,"replica_arn":None,"key_spec":"ECC_NIST_P256",
        "key_usage":"SIGN_VERIFY","algorithm":"ECDSA_SHA_256","multi_region":True,
        "account_scope":"custody_release","shared_mrk_key_id_required":True} for purpose in PURPOSES},
      "roles":_null_map(ROLE_NAMES),
      "audit":{"cloudtrail_bucket_arn":None,"retention_days":None,"object_lock_mode":"COMPLIANCE",
        "log_file_validation_required":True,"data_events_required":True},
      "recovery":{"destination_bucket_arn":None,"replication_role_arn":None,"rtc_required":True,
        "batch_replication_required":True,"single_writer_failover":True,"epoch_transition_required":True},
      "publication":{"state_machine_arn":None,"two_distinct_approvers_required":True,
        "checker_attestation_required":True,"purpose_key_required":True,"immutable_catalog_append":True},
      "entitlement_receipts":_null_map(("organization","object_lock","kms","cloudtrail","replication","publication")),
      "blockers":list(BLOCKERS)}

def _same_typed(value, expected):
    if type(value) is not type(expected): return False
    if isinstance(expected, dict): return set(value)==set(expected) and all(_same_typed(value[k], expected[k]) for k in expected)
    if isinstance(expected, list): return len(value)==len(expected) and all(_same_typed(a,b) for a,b in zip(value,expected))
    return value==expected

def validate_profile(value): require(_same_typed(value, expected_profile()), "AWS_AUTHORITY_PROFILE_INVALID"); return value
def load_profile(path=PROFILE_PATH):
    try: return validate_profile(loads_strict(Path(path).read_bytes()))
    except OSError: raise AwsAuthorityError("AWS_AUTHORITY_PROFILE_UNAVAILABLE") from None
def profile_sha256(value=None): return digest(validate_profile(value if value is not None else load_profile()))


def templates():
    return {"s3_checkpoint_object":{"key_format":"checkpoints/{sequence:020d}.json","if_none_match":"*",
      "retain_object_version_id":True,"content_sha256_required":True,"retain_until_required":True,
      "reject_delete_marker":True,"versioning":True,"object_lock_mode":"COMPLIANCE"},
      "s3_commit_receipt_object":{"key_format":"commit-receipts/{sequence:020d}.json",
        "separate_locked_bucket":True,"retain_object_version_id":True,"content_sha256_required":True,
        "retain_until_required":True,"object_lock_mode":"COMPLIANCE"},
      "dynamodb_transaction":{"actions":["Put IDEMP#<key> IF attribute_not_exists(pk)",
        "Put SEQ#<sequence> IF attribute_not_exists(pk)",
        "Update HEAD IF sequence=:prior_sequence AND manifest_sha256=:prior_sha256"],
        "client_request_token_not_authoritative":True,"consistent_read":True,"single_region":True},
      "kms":{purpose:{"key_spec":"ECC_NIST_P256","usage":"SIGN_VERIFY",
        "algorithm":"ECDSA_SHA_256","message_type":"DIGEST","separate_key":True,
        "manual_rotation":True,"same_account_replicas":True,"shared_mrk_key_id":True} for purpose in PURPOSES},
      "separation":{"key_admin_can_sign":False,"signer_can_administer":False,
        "evaluator_can_publish":False,"publisher_can_read_labels":False,"recovery_has_standing_access":False},
      "publication":{"workflow":"STEP_FUNCTIONS_STANDARD","checker_required":True,
        "distinct_human_approvals":2,"one_time_authenticated_callback":True,"publication_signature_required":True},
      "recovery":{"source":"S3_CRR_RTC","destination_object_lock":True,
        "initial_batch_replication":True,"merge_heads":False,"new_epoch_required":True,
        "signed_transition_required":True,"storage_account_separate":True,"kms_account":"custody_release"}}


def validate_locked_object(value, code="AWS_AUTHORITY_OBJECT_INVALID"):
    _strict(value, LOCKED_OBJECT_KEYS, code); _arn(value["bucket_arn"], code); _sha(value["content_sha256"], code)
    verified, retained = _time(value["verified_at"]), _time(value["retain_until"])
    require(type(value["key"]) is str and 1 <= len(value["key"]) <= 512 and
      type(value["version_id"]) is str and VERSION_ID.fullmatch(value["version_id"]) and
      type(value["minimum_retention_days"]) is int and value["minimum_retention_days"] >= 1 and
      retained >= verified + timedelta(days=value["minimum_retention_days"]) and
      value["object_lock_mode"]=="COMPLIANCE" and value["delete_marker"] is False, code)
    return value


def validate_key_status(value, verifier):
    _strict(value, KEY_STATUS_KEYS, "AWS_AUTHORITY_KEY_STATUS_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and
      value["kind"]=="aws_kms_key_status" and value["purpose"] in PURPOSES and
      value["status"] in {"active","retired","revoked"}, "AWS_AUTHORITY_KEY_STATUS_INVALID")
    _id(value["key_id"]); primary=KMS_ARN.fullmatch(value["primary_key_arn"]); replica=KMS_ARN.fullmatch(value["replica_key_arn"])
    require(primary and replica and primary.group(2)==replica.group(2) and
      primary.group(1)!=replica.group(1) and primary.group(3)==replica.group(3),
      "AWS_AUTHORITY_KMS_REPLICA_INVALID")
    _id(value["alias"]); _sha(value["public_key_sha256"]); _optional_sha(value["previous_status_sha256"])
    _sha(value["policy_sha256"]); _time(value["effective_at"])
    if value["status"]=="active":
        require(value["primary_enabled"] is True and value["replica_enabled"] is True and value["grants_revoked"] is False,
                "AWS_AUTHORITY_KEY_CONVERGENCE_INVALID")
    else:
        require(value["primary_enabled"] is False and value["replica_enabled"] is False and value["grants_revoked"] is True,
                "AWS_AUTHORITY_KEY_CONVERGENCE_INVALID")
    _verify(value, verifier, "revocation", "AWS_AUTHORITY_KEY_SIGNATURE_INVALID")
    return value

def validate_key_rotation(old_status,new_status,verifier):
    old_status=validate_key_status(old_status,verifier); new_status=validate_key_status(new_status,verifier)
    require(old_status["status"] in {"retired","revoked"} and new_status["status"]=="active" and
      old_status["purpose"]==new_status["purpose"] and old_status["alias"]==new_status["alias"] and
      old_status["key_id"]!=new_status["key_id"] and new_status["previous_status_sha256"]==digest(old_status) and
      _time(new_status["effective_at"])>_time(old_status["effective_at"]), "AWS_AUTHORITY_KEY_ROTATION_INVALID")
    return new_status

def historical_public_key(key_status,purpose,verifier):
    key_status=validate_key_status(key_status,verifier)
    require(key_status["purpose"]==purpose,"AWS_AUTHORITY_KEY_PURPOSE_INVALID")
    return key_status["public_key_sha256"]


def validate_commit_receipt(value, verifier, key_status):
    _strict(value, RECEIPT_KEYS, "AWS_AUTHORITY_RECEIPT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and
      value["kind"]=="aws_checkpoint_commit_receipt" and type(value["epoch"]) is int and
      type(value["sequence"]) is int, "AWS_AUTHORITY_RECEIPT_INVALID")
    _sha(value["manifest_sha256"]); _sha(value["checkpoint_object_sha256"]); _time(value["issued_at"])
    status=validate_key_status(key_status,verifier)
    require(status["purpose"]=="checkpoint" and status["status"]=="active" and
      value["signer_key_version"]==status["key_id"] and
      value["signer_public_key_sha256"]==status["public_key_sha256"], "AWS_AUTHORITY_RECEIPT_SIGNER_INVALID")
    _verify(value,verifier,"checkpoint","AWS_AUTHORITY_RECEIPT_SIGNATURE_INVALID"); return value


def validate_recovery_transition(value, *, prior_epoch, prior_manifest_sha256,
                                  prior_checkpoint_sha256, key_status, verifier):
    _strict(value,RECOVERY_KEYS,"AWS_AUTHORITY_RECOVERY_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and
      value["kind"]=="aws_recovery_epoch_transition" and type(value["new_epoch"]) is int and
      value["new_epoch"]>prior_epoch and value["prior_manifest_sha256"]==_sha(prior_manifest_sha256) and
      value["prior_checkpoint_sha256"]==_sha(prior_checkpoint_sha256) and
      value["primary_fenced"] is True and value["chain_verified"] is True and value["merge_heads"] is False and
      value["from_region"]!=value["to_region"], "AWS_AUTHORITY_RECOVERY_INVALID")
    _id(value["from_region"]); _id(value["to_region"]); _sha(value["key_status_sha256"]); _time(value["issued_at"])
    status=validate_key_status(key_status,verifier)
    require(status["purpose"]=="revocation" and status["status"]=="active" and
      value["key_status_sha256"]==digest(status) and value["signer_key_version"]==status["key_id"] and
      value["signer_public_key_sha256"]==status["public_key_sha256"], "AWS_AUTHORITY_RECOVERY_SIGNER_INVALID")
    _verify(value,verifier,"revocation","AWS_AUTHORITY_RECOVERY_SIGNATURE_INVALID"); return value


def validate_checkpoint_commit(candidate,current=None,*,key_status,verifier,
                               recovery_transition=None,recovery_key_status=None):
    _strict(candidate,COMMIT_KEYS,"AWS_AUTHORITY_COMMIT_SCHEMA")
    require(type(candidate["schema_version"]) is int and candidate["schema_version"]==1 and
      candidate["kind"]=="aws_checkpoint_commit" and type(candidate["epoch"]) is int and
      candidate["epoch"]>=1 and type(candidate["sequence"]) is int and candidate["sequence"]>=1 and
      candidate["create_only"] is True and candidate["single_writer"] is True,"AWS_AUTHORITY_COMMIT_INVALID")
    _optional_sha(candidate["previous_manifest_sha256"]); _sha(candidate["manifest_sha256"]); _id(candidate["idempotency_key"])
    _id(candidate["writer_region"]); _sha(candidate["key_status_sha256"]); _optional_sha(candidate["recovery_transition_sha256"])
    checkpoint=validate_locked_object(candidate["checkpoint_object"]); receipt_object=validate_locked_object(candidate["commit_receipt_object"])
    status=validate_key_status(key_status,verifier)
    receipt=validate_commit_receipt(candidate["commit_receipt"],verifier,key_status)
    require(checkpoint["key"]==f"checkpoints/{candidate['sequence']:020d}.json" and checkpoint["content_sha256"]==candidate["manifest_sha256"] and
      receipt_object["key"]==f"commit-receipts/{candidate['sequence']:020d}.json" and
      receipt_object["content_sha256"]==digest(receipt) and checkpoint["bucket_arn"]!=receipt_object["bucket_arn"] and
      receipt["epoch"]==candidate["epoch"] and receipt["sequence"]==candidate["sequence"] and
      receipt["manifest_sha256"]==candidate["manifest_sha256"] and receipt["checkpoint_object_sha256"]==digest(checkpoint),
      "AWS_AUTHORITY_OBJECT_INVALID")
    require(status["purpose"]=="checkpoint" and status["status"]=="active" and
      candidate["key_status_sha256"]==digest(status) and candidate["signer_key_version"]==status["key_id"] and
      candidate["signer_public_key_sha256"]==status["public_key_sha256"],"AWS_AUTHORITY_COMMIT_SIGNER_INVALID")
    _verify(candidate,verifier,"checkpoint","AWS_AUTHORITY_COMMIT_SIGNATURE_INVALID")
    if current is None:
        require(candidate["epoch"]==1 and candidate["sequence"]==1 and candidate["previous_manifest_sha256"] is None and
          candidate["recovery_transition_sha256"] is None,"AWS_AUTHORITY_HEAD_CONFLICT")
    else:
        _strict(current,{"epoch","sequence","manifest_sha256","writer_region"},"AWS_AUTHORITY_HEAD_SCHEMA")
        require(candidate["sequence"]==current["sequence"]+1 and candidate["previous_manifest_sha256"]==_sha(current["manifest_sha256"]),
                "AWS_AUTHORITY_HEAD_CONFLICT")
        if candidate["epoch"]==current["epoch"]:
            require(candidate["writer_region"]==current["writer_region"] and candidate["recovery_transition_sha256"] is None,
                    "AWS_AUTHORITY_HEAD_CONFLICT")
        else:
            require(recovery_transition is not None and recovery_key_status is not None,"AWS_AUTHORITY_HEAD_CONFLICT")
            validate_recovery_transition(recovery_transition,prior_epoch=current["epoch"],
                prior_manifest_sha256=current["manifest_sha256"],prior_checkpoint_sha256=digest(current),
                key_status=recovery_key_status,verifier=verifier)
            require(candidate["epoch"]==current["epoch"]+1 and candidate["writer_region"]==recovery_transition["to_region"] and
              candidate["recovery_transition_sha256"]==digest(recovery_transition),"AWS_AUTHORITY_HEAD_CONFLICT")
    return candidate


class FixtureDynamoBackend:
    """Lock-protected atomic conformance fixture, not DynamoDB."""
    def __init__(self):
        self._lock=threading.Lock(); self._idempotency={}; self._sequences={}; self._head=None
    def latest(self): return None if self._head is None else clone(self._head)
    def transact_commit(self,candidate,*,key_status,verifier,recovery_transition=None,
                        recovery_key_status=None,unknown_after_write=False):
        with self._lock:
            key=candidate.get("idempotency_key"); candidate_sha=digest(candidate)
            if key in self._idempotency:
                stored=self._idempotency[key]
                require(stored["candidate_sha256"]==candidate_sha,"AWS_AUTHORITY_IDEMPOTENCY_CONFLICT")
                return clone(stored["commit"]),False
            validated=validate_checkpoint_commit(candidate,self._head,key_status=key_status,verifier=verifier,
                recovery_transition=recovery_transition,recovery_key_status=recovery_key_status)
            sequence=validated["sequence"]
            require(sequence not in self._sequences,"AWS_AUTHORITY_SEQUENCE_CONFLICT")
            current={"epoch":validated["epoch"],"sequence":sequence,
                     "manifest_sha256":validated["manifest_sha256"],"writer_region":validated["writer_region"]}
            self._idempotency[key]={"candidate_sha256":candidate_sha,"sequence":sequence,"commit":clone(validated)}
            self._sequences[sequence]=clone(validated); self._head=current
            if unknown_after_write: raise UnknownOutcome("AWS_AUTHORITY_UNKNOWN_OUTCOME")
            return clone(validated),True
    def reconcile(self,idempotency_key,candidate_sha256):
        with self._lock:
            value=self._idempotency.get(idempotency_key)
            return value is not None and value["candidate_sha256"]==candidate_sha256


def validate_authorization(value,*,current_checkpoint,purpose,payload_sha256,key_status,verifier,now):
    _strict(value,AUTHORIZATION_KEYS,"AWS_AUTHORITY_AUTHORIZATION_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"]==1 and value["kind"]=="aws_publication_authorization" and
      value["purpose"] in PUBLICATION_PURPOSES and value["purpose"]==purpose and value["state"]=="active" and
      type(value["epoch"]) is int and type(value["sequence"]) is int,"AWS_AUTHORITY_AUTHORIZATION_DENIED")
    _id(value["authorization_id"]); _sha(value["checkpoint_sha256"]); _sha(value["payload_sha256"]); _sha(value["key_status_sha256"])
    issued,expires,current_time=_time(value["issued_at"]),_time(value["expires_at"]),_time(now)
    require(issued<=current_time<expires and issued<expires and value["payload_sha256"]==_sha(payload_sha256) and
      value["checkpoint_sha256"]==digest(current_checkpoint) and value["epoch"]==current_checkpoint["epoch"] and
      value["sequence"]==current_checkpoint["sequence"],"AWS_AUTHORITY_AUTHORIZATION_DENIED")
    status=validate_key_status(key_status,verifier)
    require(status["purpose"]=="publication" and status["status"]=="active" and value["key_status_sha256"]==digest(status) and
      value["signer_key_version"]==status["key_id"] and value["signer_public_key_sha256"]==status["public_key_sha256"],
      "AWS_AUTHORITY_AUTHORIZATION_SIGNER_INVALID")
    _verify(value,verifier,"publication","AWS_AUTHORITY_AUTHORIZATION_SIGNATURE_INVALID"); return value
