"""Provider-neutral trusted-authority contracts and fixture conformance harness.

Nothing here provisions production trust. The tracked profile is disabled; the
in-memory backend and HMAC signer are synthetic test doubles only.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
import re
from typing import Protocol

PACKAGE = Path(__file__).resolve().parent
PROFILE_PATH = PACKAGE / "deployment-profile.json"
MAX_JSON_BYTES = 128 * 1024
AUTHORITY_ID = "factor-admission-main-v1"
WORKSPACE_ID = "trading-agent"
PROFILE_ID = "factor-trusted-authority-v1"
SYNTHETIC_SIGNER_POLICY = "fixture-synthetic-hmac-sha256"
PURPOSES = {
    "performance_publication", "combination_selection",
    "ev_publication", "kelly_publication",
}
BLOCKERS = [
    "durable-checkpoint-backend-unselected",
    "trusted-signing-algorithm-unselected",
    "key-custody-owner-unassigned",
    "rotation-revocation-policy-unaccepted",
    "recovery-owner-and-policy-unaccepted",
    "independent-checker-policy-unaccepted",
    "publication-authorization-service-unselected",
]
SHA = re.compile(r"[a-f0-9]{64}\Z")
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")


class TrustedAuthorityError(ValueError):
    """Stable sanitized trusted-authority rejection."""


class UnknownOutcome(TrustedAuthorityError):
    """A fixture backend stored a write but hid the response."""


def require(condition, code):
    if not condition:
        raise TrustedAuthorityError(code)


def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "TRUSTED_AUTHORITY_DUPLICATE_KEY")
        value[key] = item
    return value


def loads_strict(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON_BYTES,
            "TRUSTED_AUTHORITY_JSON_SIZE")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              TrustedAuthorityError("TRUSTED_AUTHORITY_NONFINITE")))
    except TrustedAuthorityError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise TrustedAuthorityError("TRUSTED_AUTHORITY_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise TrustedAuthorityError("TRUSTED_AUTHORITY_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _clone(value):
    """Return a canonical deep copy so fixture backend state never escapes."""
    return loads_strict(canonical(value))


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _id(value, code="TRUSTED_AUTHORITY_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def _sha(value, code="TRUSTED_AUTHORITY_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _optional_sha(value, code="TRUSTED_AUTHORITY_SHA_INVALID"):
    require(value is None or type(value) is str and SHA.fullmatch(value), code)
    return value


def _time(value):
    require(type(value) is str and TIME.fullmatch(value),
            "TRUSTED_AUTHORITY_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise TrustedAuthorityError("TRUSTED_AUTHORITY_TIME_INVALID") from None
    require(parsed.utcoffset().total_seconds() == 0,
            "TRUSTED_AUTHORITY_TIME_INVALID")
    return parsed


def validate_profile(value):
    expected = {
        "schema_version": 1,
        "kind": "trusted_authority_deployment_profile",
        "profile_id": PROFILE_ID,
        "authority_id": AUTHORITY_ID,
        "workspace_id": WORKSPACE_ID,
        "status": "candidate-disabled",
        "checkpoint_backend_id": None,
        "signer_policy_sha256": None,
        "key_custody_owner_id": None,
        "recovery_policy_sha256": None,
        "recovery_owner_id": None,
        "independent_checker_policy_sha256": None,
        "publication_service_id": None,
        "allowed_purposes": [],
        "real_operations_allowed": False,
        "protected_outcomes_allowed": False,
        "publication_allowed": False,
        "blockers": BLOCKERS,
    }
    require(type(value) is dict and set(value) == set(expected) and
            all(type(value[key]) is type(expected[key]) and value[key] == expected[key]
                for key in expected), "TRUSTED_AUTHORITY_PROFILE_INVALID")
    return value


def load_profile(path=PROFILE_PATH):
    try:
        value = loads_strict(Path(path).read_bytes())
    except OSError:
        raise TrustedAuthorityError("TRUSTED_AUTHORITY_PROFILE_UNAVAILABLE") from None
    return validate_profile(value)


def assert_active(profile):
    validate_profile(profile)
    raise TrustedAuthorityError("TRUSTED_AUTHORITY_PROFILE_BLOCKED")


class DurableCheckpointBackend(Protocol):
    """Port only. No production implementation is selected in this package."""
    def latest(self): ...
    def publish(self, checkpoint, *, unknown_after_write=False): ...
    def import_recovery(self, checkpoints): ...


def _checkpoint_unsigned(value):
    return {key: value[key] for key in value if key != "signature"}


def _authorization_unsigned(value):
    return {key: value[key] for key in value if key != "signature"}


def validate_checkpoint(value):
    _strict(value, {"schema_version", "kind", "authority_id", "workspace_id",
                    "epoch", "sequence", "previous_checkpoint_sha256",
                    "ledger_head_sha256", "issued_at", "key_id", "signer_policy",
                    "status", "signature"}, "TRUSTED_AUTHORITY_CHECKPOINT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "trusted_authority_checkpoint" and
            value["authority_id"] == AUTHORITY_ID and
            value["workspace_id"] == WORKSPACE_ID and
            type(value["epoch"]) is int and value["epoch"] >= 1 and
            type(value["sequence"]) is int and value["sequence"] >= 1 and
            value["signer_policy"] == SYNTHETIC_SIGNER_POLICY and
            value["status"] in {"active", "quarantined", "revoked"},
            "TRUSTED_AUTHORITY_CHECKPOINT_INVALID")
    _optional_sha(value["previous_checkpoint_sha256"])
    _sha(value["ledger_head_sha256"]); _sha(value["signature"])
    _id(value["key_id"]); _time(value["issued_at"])
    require((value["sequence"] == 1) ==
            (value["previous_checkpoint_sha256"] is None),
            "TRUSTED_AUTHORITY_CHECKPOINT_INVALID")
    return value


def validate_authorization(value):
    _strict(value, {"schema_version", "kind", "authorization_id", "authority_id",
                    "workspace_id", "checkpoint_sha256", "epoch", "sequence",
                    "purpose", "payload_sha256", "issued_at", "expires_at", "key_id",
                    "signer_policy", "state", "signature"},
            "TRUSTED_AUTHORITY_AUTHORIZATION_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "trusted_authority_authorization" and
            value["authority_id"] == AUTHORITY_ID and
            value["workspace_id"] == WORKSPACE_ID and
            type(value["epoch"]) is int and value["epoch"] >= 1 and
            type(value["sequence"]) is int and value["sequence"] >= 1 and
            value["purpose"] in PURPOSES and
            value["signer_policy"] == SYNTHETIC_SIGNER_POLICY and
            value["state"] in {"active", "revoked"},
            "TRUSTED_AUTHORITY_AUTHORIZATION_INVALID")
    _id(value["authorization_id"]); _id(value["key_id"])
    _sha(value["checkpoint_sha256"]); _sha(value["payload_sha256"])
    _sha(value["signature"])
    issued = _time(value["issued_at"]); expires = _time(value["expires_at"])
    require(issued < expires, "TRUSTED_AUTHORITY_AUTHORIZATION_INVALID")
    return value


class FixtureSigner:
    """Synthetic HMAC test double; forbidden by the disabled real profile."""
    def __init__(self, key_id, secret):
        _id(key_id)
        require(type(secret) is bytes and len(secret) >= 32,
                "TRUSTED_AUTHORITY_FIXTURE_KEY_INVALID")
        self.key_id = key_id
        self._secret = secret
        self.revoked = False

    def sign(self, unsigned):
        require(not self.revoked, "TRUSTED_AUTHORITY_KEY_REVOKED")
        return hmac.new(self._secret, canonical(unsigned), hashlib.sha256).hexdigest()

    def verify(self, unsigned, signature, *, require_active=False):
        _sha(signature)
        expected = hmac.new(self._secret, canonical(unsigned), hashlib.sha256).hexdigest()
        require((not require_active or not self.revoked) and
                hmac.compare_digest(expected, signature),
                "TRUSTED_AUTHORITY_SIGNATURE_INVALID")
        return True

    def revoke(self):
        self.revoked = True


class FixtureKeyring:
    def __init__(self):
        self._keys = {}
        self.active_key_id = None

    def add(self, signer, *, activate=False):
        require(isinstance(signer, FixtureSigner) and signer.key_id not in self._keys,
                "TRUSTED_AUTHORITY_KEY_CONFLICT")
        self._keys[signer.key_id] = signer
        if activate:
            self.active_key_id = signer.key_id

    def rotate(self, signer):
        self.add(signer, activate=True)

    def revoke(self, key_id):
        require(key_id in self._keys, "TRUSTED_AUTHORITY_KEY_UNKNOWN")
        self._keys[key_id].revoke()
        if self.active_key_id == key_id:
            self.active_key_id = None

    def active(self):
        require(self.active_key_id in self._keys,
                "TRUSTED_AUTHORITY_ACTIVE_KEY_UNAVAILABLE")
        return self._keys[self.active_key_id]

    def get(self, key_id):
        require(key_id in self._keys, "TRUSTED_AUTHORITY_KEY_UNKNOWN")
        return self._keys[key_id]


class MemoryCheckpointBackend:
    """Bounded in-memory conformance fixture, never a durable backend."""
    def __init__(self, backend_id="fixture-memory-backend"):
        _id(backend_id)
        self.backend_id = backend_id
        self._checkpoints = []

    def latest(self):
        return None if not self._checkpoints else _clone(self._checkpoints[-1])

    def publish(self, checkpoint, *, unknown_after_write=False):
        checkpoint = validate_checkpoint(_clone(checkpoint))
        latest = None if not self._checkpoints else self._checkpoints[-1]
        expected_sequence = 1 if latest is None else latest["sequence"] + 1
        expected_epoch = 1 if latest is None else latest["epoch"]
        require(checkpoint["sequence"] == expected_sequence and
                checkpoint["epoch"] >= expected_epoch and
                checkpoint["previous_checkpoint_sha256"] ==
                (None if latest is None else digest(latest)) and
                (latest is None or
                 _time(checkpoint["issued_at"]) > _time(latest["issued_at"])),
                "TRUSTED_AUTHORITY_CHECKPOINT_ROLLBACK")
        stored = _clone(checkpoint)
        self._checkpoints.append(stored)
        if unknown_after_write:
            raise UnknownOutcome("TRUSTED_AUTHORITY_UNKNOWN_OUTCOME")
        return _clone(stored)

    def reconcile(self, checkpoint_sha256):
        _sha(checkpoint_sha256)
        latest = None if not self._checkpoints else self._checkpoints[-1]
        return latest is not None and digest(latest) == checkpoint_sha256

    def import_recovery(self, checkpoints):
        require(type(checkpoints) is list and checkpoints,
                "TRUSTED_AUTHORITY_RECOVERY_INVALID")
        candidate = MemoryCheckpointBackend(self.backend_id)
        for checkpoint in checkpoints:
            candidate.publish(checkpoint)
        latest = None if not self._checkpoints else self._checkpoints[-1]
        if latest is not None:
            require(len(candidate._checkpoints) >= latest["sequence"] and
                    digest(candidate._checkpoints[latest["sequence"] - 1]) == digest(latest) and
                    candidate._checkpoints[-1]["epoch"] >= latest["epoch"],
                    "TRUSTED_AUTHORITY_RECOVERY_ROLLBACK")
        self._checkpoints = [_clone(value) for value in candidate._checkpoints]
        return self.latest()

    def exported(self):
        return [_clone(value) for value in self._checkpoints]


def validate_recovery_bundle(value):
    _strict(value, {"schema_version", "kind", "authority_id", "workspace_id",
                    "checkpoints"}, "TRUSTED_AUTHORITY_RECOVERY_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "trusted_authority_recovery_bundle" and
            value["authority_id"] == AUTHORITY_ID and
            value["workspace_id"] == WORKSPACE_ID and
            type(value["checkpoints"]) is list and
            1 <= len(value["checkpoints"]) <= 1024,
            "TRUSTED_AUTHORITY_RECOVERY_INVALID")
    for checkpoint in value["checkpoints"]:
        validate_checkpoint(checkpoint)
    return value


def export_recovery_bundle(backend):
    require(isinstance(backend, MemoryCheckpointBackend),
            "TRUSTED_AUTHORITY_FIXTURE_ONLY")
    checkpoints = backend.exported()
    require(checkpoints, "TRUSTED_AUTHORITY_RECOVERY_INVALID")
    return validate_recovery_bundle({
        "schema_version": 1, "kind": "trusted_authority_recovery_bundle",
        "authority_id": AUTHORITY_ID, "workspace_id": WORKSPACE_ID,
        "checkpoints": checkpoints,
    })


def import_recovery_bundle(backend, keyring, bundle):
    require(isinstance(backend, MemoryCheckpointBackend) and
            isinstance(keyring, FixtureKeyring), "TRUSTED_AUTHORITY_FIXTURE_ONLY")
    bundle = validate_recovery_bundle(bundle)
    for checkpoint in bundle["checkpoints"]:
        verify_checkpoint(checkpoint, keyring)
    return backend.import_recovery(bundle["checkpoints"])


def issue_checkpoint(backend, keyring, *, ledger_head_sha256, issued_at,
                     status="active", epoch=None):
    require(isinstance(backend, MemoryCheckpointBackend) and
            isinstance(keyring, FixtureKeyring), "TRUSTED_AUTHORITY_FIXTURE_ONLY")
    signer = keyring.active(); latest = backend.latest()
    sequence = 1 if latest is None else latest["sequence"] + 1
    selected_epoch = (1 if latest is None else latest["epoch"]) if epoch is None else epoch
    unsigned = {
        "schema_version": 1, "kind": "trusted_authority_checkpoint",
        "authority_id": AUTHORITY_ID, "workspace_id": WORKSPACE_ID,
        "epoch": selected_epoch, "sequence": sequence,
        "previous_checkpoint_sha256": None if latest is None else digest(latest),
        "ledger_head_sha256": _sha(ledger_head_sha256), "issued_at": issued_at,
        "key_id": signer.key_id, "signer_policy": SYNTHETIC_SIGNER_POLICY,
        "status": status,
    }
    checkpoint = {**unsigned, "signature": signer.sign(unsigned)}
    signer.verify(unsigned, checkpoint["signature"])
    return validate_checkpoint(checkpoint)


def verify_checkpoint(checkpoint, keyring):
    checkpoint = validate_checkpoint(checkpoint)
    keyring.get(checkpoint["key_id"]).verify(
        _checkpoint_unsigned(checkpoint), checkpoint["signature"])
    return checkpoint


def issue_authorization(checkpoint, keyring, *, authorization_id, purpose,
                        payload_sha256, issued_at, expires_at):
    checkpoint = verify_checkpoint(checkpoint, keyring)
    require(checkpoint["status"] == "active", "TRUSTED_AUTHORITY_NOT_ACTIVE")
    require(_time(issued_at) >= _time(checkpoint["issued_at"]) and
            _time(expires_at) > _time(issued_at),
            "TRUSTED_AUTHORITY_AUTHORIZATION_TIME_INVALID")
    signer = keyring.active()
    unsigned = {
        "schema_version": 1, "kind": "trusted_authority_authorization",
        "authorization_id": _id(authorization_id), "authority_id": AUTHORITY_ID,
        "workspace_id": WORKSPACE_ID, "checkpoint_sha256": digest(checkpoint),
        "epoch": checkpoint["epoch"], "sequence": checkpoint["sequence"],
        "purpose": purpose, "payload_sha256": _sha(payload_sha256),
        "issued_at": issued_at, "expires_at": expires_at, "key_id": signer.key_id,
        "signer_policy": SYNTHETIC_SIGNER_POLICY, "state": "active",
    }
    authorization = {**unsigned, "signature": signer.sign(unsigned)}
    signer.verify(unsigned, authorization["signature"])
    return validate_authorization(authorization)


def lookup_authorization(authorization, backend, keyring, *, purpose,
                         payload_sha256, now):
    authorization = validate_authorization(authorization)
    latest = backend.latest()
    require(latest is not None and digest(latest) == authorization["checkpoint_sha256"],
            "TRUSTED_AUTHORITY_AUTHORIZATION_STALE")
    verify_checkpoint(latest, keyring)
    keyring.get(authorization["key_id"]).verify(
        _authorization_unsigned(authorization), authorization["signature"],
        require_active=True)
    require(latest["status"] == "active" and authorization["state"] == "active" and
            authorization["purpose"] == purpose and
            authorization["payload_sha256"] == _sha(payload_sha256) and
            _time(authorization["issued_at"]) <= _time(now) <
            _time(authorization["expires_at"]),
            "TRUSTED_AUTHORITY_AUTHORIZATION_DENIED")
    return authorization
