"""Development-only canonical authority contract for synthetic factor verification.

This module models one fixed authority namespace, immutable event ordering and
one-time fixture nonces. It is not a durable or signed production authority and
refuses real protocols, protected outcomes and every publication purpose.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import types

from factor.dataset import build_snapshot
from tuning.factor_mining.admission_policy import policy as admission_policy_contract


PACKAGE = Path(__file__).resolve().parent
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = PACKAGE / "authority-policy.json"
GENESIS_PATH = PACKAGE / "authority-genesis.json"
ADMISSION_POLICY_PATH = PACKAGE.parent / "admission_policy/initial-confirmatory-policy.json"
ADMISSION_POLICY_SHA256 = "d010b96585994ba2bc712ba96d580cbc2cd669b03bbf41eaeee2b855c53c0b9f"
AUTHORITY_ID = "factor-admission-main-v1"
WORKSPACE_ID = "trading-agent"
LEDGER_RELATIVE_PATH = "factor/runtime/admission-authority"
FIXTURE_PURPOSE = "synthetic-contract-verification"
SHA = re.compile(r"[a-f0-9]{64}\Z")
TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
MAX_JSON = 256 * 1024
BLOCKERS = [
    "durable-external-checkpoint-store-unresolved",
    "trusted-signer-keys-unresolved",
    "disaster-recovery-policy-unresolved",
    "trusted-runner-policy-unresolved",
    "trusted-evaluator-policy-unresolved",
    "independent-checker-policy-unresolved",
    "publication-authorization-policy-unresolved",
]
NULL_POLICIES = [
    "durable_checkpoint_store_id", "trusted_signer_policy_sha256",
    "recovery_policy_sha256", "runner_policy_sha256", "evaluator_policy_sha256",
    "independent_checker_policy_sha256", "publication_policy_sha256",
]
EVENT_TYPES = frozenset({"dataset_bound", "fixture_nonce_issued", "fixture_nonce_claimed",
                         "fixture_runner_terminal", "fixture_evaluator_terminal"})
PAYLOAD_KEYS = {
    "dataset_bound": frozenset({"purpose", "trust_class", "admission_policy_sha256",
        "builder_receipt_sha256", "observation_set_sha256", "feature_snapshot_sha256",
        "evaluation_population_sha256", "split_spec_sha256", "split_fingerprints",
        "fixture_only", "performance_claim"}),
    "fixture_nonce_issued": frozenset({"purpose", "trust_class", "admission_policy_sha256",
        "dataset_event_sha256", "semantic_config_sha256", "nonce_sha256",
        "observation_set_sha256", "feature_snapshot_sha256", "evaluation_population_sha256",
        "split_fingerprints", "protected_outcomes_allowed"}),
    "fixture_nonce_claimed": frozenset({"purpose", "trust_class", "nonce_sha256",
        "nonce_event_sha256", "dataset_event_sha256", "semantic_config_sha256",
        "claim_status", "outcome_accessed"}),
    "fixture_runner_terminal": frozenset({"purpose", "trust_class", "nonce_sha256",
        "nonce_event_sha256", "claim_event_sha256", "dataset_event_sha256",
        "semantic_config_sha256", "request_sha256", "runner_receipt_sha256",
        "runner_implementation_sha256", "artifact_sha256", "artifact_size_bytes",
        "terminal_status", "failure_code", "outcome_accessed", "protected_labels_accessed",
        "performance_claim"}),
    "fixture_evaluator_terminal": frozenset({"purpose", "trust_class", "nonce_sha256",
        "runner_event_sha256", "runner_receipt_sha256", "evaluator_request_sha256",
        "evaluator_receipt_sha256", "evaluator_implementation_sha256", "terminal_status",
        "scientific_verdict", "independent_check_status", "outcome_accessed",
        "protected_labels_accessed", "performance_claim"}),
}


class AuthorityError(ValueError):
    """Stable, sanitized authority failure."""


class AuthorityWriteFailed(AuthorityError):
    """A write failed before its destination effect boundary."""

    def __init__(self):
        super().__init__("AUTHORITY_WRITE_FAILED")
        self.effect_attempted = False


class AuthorityWriteDurabilityUnknown(AuthorityError):
    """A destination effect was attempted but durability/readback is unconfirmed."""

    def __init__(self, destination, intended_bytes, readback_state=None):
        super().__init__("AUTHORITY_WRITE_DURABILITY_UNKNOWN")
        self.destination = str(Path(destination))
        self.intended_bytes = bytes(intended_bytes)
        self.intended_sha256 = hashlib.sha256(self.intended_bytes).hexdigest()
        self.intended_size_bytes = len(self.intended_bytes)
        self.readback_state = readback_state


def require(condition, code):
    if not condition:
        raise AuthorityError(code)


def _same_typed(value, expected):
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(_same_typed(value[key], expected[key]) for key in expected)
    if isinstance(expected, list):
        return len(value) == len(expected) and all(_same_typed(a, b) for a, b in zip(value, expected))
    return value == expected


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError):
        raise AuthorityError("AUTHORITY_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _safe_semantic(value):
    if isinstance(value, types.CodeType):
        return _code_semantics(value)
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, re.Pattern):
        return {"pattern": value.pattern, "flags": value.flags}
    if isinstance(value, (tuple, list)):
        return [_safe_semantic(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_safe_semantic(item) for item in value), key=canonical)
    if isinstance(value, dict):
        return {str(key): _safe_semantic(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, type):
        return {"type_ref": f"{value.__module__}.{value.__qualname__}"}
    return {"type_ref": f"{type(value).__module__}.{type(value).__qualname__}"}


def _code_semantics(code):
    return {"name": code.co_name, "argcount": code.co_argcount,
            "posonlyargcount": getattr(code, "co_posonlyargcount", 0),
            "kwonlyargcount": code.co_kwonlyargcount, "flags": code.co_flags,
            "bytecode": code.co_code.hex(), "names": list(code.co_names),
            "varnames": list(code.co_varnames),
            "constants": [_safe_semantic(item) for item in code.co_consts]}


def _function_semantics(function):
    return {"code": _code_semantics(function.__code__),
            "defaults": _safe_semantic(function.__defaults__),
            "kwdefaults": _safe_semantic(function.__kwdefaults__),
            "annotations": _safe_semantic(function.__annotations__)}


def _class_semantics(cls):
    members = []
    ignored = {"__dict__", "__weakref__", "__doc__", "__module__"}
    for name, descriptor in sorted(cls.__dict__.items()):
        if name in ignored:
            continue
        if isinstance(descriptor, staticmethod):
            value = {"kind": "staticmethod", "function": _function_semantics(descriptor.__func__)}
        elif isinstance(descriptor, classmethod):
            value = {"kind": "classmethod", "function": _function_semantics(descriptor.__func__)}
        elif isinstance(descriptor, property):
            value = {"kind": "property",
                     "get": None if descriptor.fget is None else _function_semantics(descriptor.fget),
                     "set": None if descriptor.fset is None else _function_semantics(descriptor.fset),
                     "delete": None if descriptor.fdel is None else _function_semantics(descriptor.fdel)}
        elif isinstance(descriptor, types.FunctionType):
            value = {"kind": "method", "function": _function_semantics(descriptor)}
        else:
            value = {"kind": "attribute", "value": _safe_semantic(descriptor)}
        members.append({"name": name, **value})
    return {"module": cls.__module__, "qualname": cls.__qualname__,
            "roster": [member["name"] for member in members], "members": members}


def implementation_sha256():
    functions = [{"symbol": name, "function": _function_semantics(value)}
                 for name, value in globals().items()
                 if isinstance(value, types.FunctionType) and value.__module__ == __name__]
    policy, policy_sha = load_policy()
    genesis, genesis_sha = load_genesis()
    material = {"python_cache_tag": sys.implementation.cache_tag,
                "authority_id": AUTHORITY_ID, "workspace_id": WORKSPACE_ID,
                "ledger_relative_path": LEDGER_RELATIVE_PATH,
                "admission_policy_sha256": ADMISSION_POLICY_SHA256,
                "authority_policy_sha256": policy_sha, "genesis_sha256": genesis_sha,
                "max_json": MAX_JSON, "max_events": policy["max_events"],
                "blockers": BLOCKERS, "null_policies": NULL_POLICIES,
                "event_types": sorted(EVENT_TYPES),
                "payload_keys": {key: sorted(value) for key, value in sorted(PAYLOAD_KEYS.items())},
                "regexes": {"sha": [SHA.pattern, SHA.flags], "id": [ID.pattern, ID.flags],
                            "time": [TIME.pattern, TIME.flags]},
                "policy_status": policy["status"], "genesis_status": genesis["status"],
                "functions": sorted(functions, key=lambda item: item["symbol"]),
                "classes": [_class_semantics(FixtureAuthority)]}
    return digest(material)


def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "AUTHORITY_DUPLICATE_KEY")
        value[key] = item
    return value


def loads_strict(raw):
    try:
        require(type(raw) in {bytes, str} and len(raw) <= MAX_JSON, "AUTHORITY_JSON_SIZE")
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              AuthorityError("AUTHORITY_NONFINITE")))
    except AuthorityError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise AuthorityError("AUTHORITY_JSON_INVALID") from None


def _strict(value, keys, code):
    require(type(value) is dict and set(value) == set(keys), code)
    return value


def _sha(value, code="AUTHORITY_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _optional_sha(value, code="AUTHORITY_SHA_INVALID"):
    require(value is None or type(value) is str and SHA.fullmatch(value), code)
    return value


def _id(value, code="AUTHORITY_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def _timestamp(value):
    require(type(value) is str and TIME.fullmatch(value), "AUTHORITY_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise AuthorityError("AUTHORITY_TIME_INVALID") from None
    require(parsed.tzinfo is not None and parsed.utcoffset().total_seconds() == 0,
            "AUTHORITY_TIME_INVALID")
    return value


def _read_json(path, maximum=MAX_JSON):
    path = Path(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise AuthorityError("AUTHORITY_RECORD_UNAVAILABLE") from None
    try:
        details = os.fstat(descriptor)
        require(stat.S_ISREG(details.st_mode) and details.st_uid == os.getuid() and
                0 < details.st_size <= maximum, "AUTHORITY_RECORD_INVALID")
        chunks = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            require(chunk, "AUTHORITY_RECORD_INVALID")
            chunks.append(chunk)
            remaining -= len(chunk)
        return loads_strict(b"".join(chunks))
    except AuthorityError:
        raise
    except OSError:
        raise AuthorityError("AUTHORITY_RECORD_INVALID") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def validate_policy(value):
    expected = {
        "schema_version": 1,
        "kind": "factor_admission_authority_policy",
        "authority_id": AUTHORITY_ID,
        "workspace_id": WORKSPACE_ID,
        "epoch": 1,
        "status": "development-only-blocked",
        "ledger_relative_path": LEDGER_RELATIVE_PATH,
        "admission_policy_sha256": ADMISSION_POLICY_SHA256,
        "allowed_trust_classes": ["synthetic"],
        "allowed_purposes": [FIXTURE_PURPOSE],
        "max_events": 256,
        "blockers": BLOCKERS,
        "durable_checkpoint_store_id": None,
        "trusted_signer_policy_sha256": None,
        "recovery_policy_sha256": None,
        "runner_policy_sha256": None,
        "evaluator_policy_sha256": None,
        "independent_checker_policy_sha256": None,
        "publication_policy_sha256": None,
        "real_protocols_allowed": False,
        "protected_outcomes_allowed": False,
        "performance_publication_allowed": False,
        "ev_publication_allowed": False,
        "kelly_publication_allowed": False,
    }
    require(_same_typed(value, expected), "AUTHORITY_POLICY_INVALID")
    return value


def load_policy():
    value = validate_policy(_read_json(POLICY_PATH))
    try:
        frozen = admission_policy_contract.load_policy(ADMISSION_POLICY_PATH)
    except Exception:
        raise AuthorityError("AUTHORITY_ADMISSION_POLICY_INVALID") from None
    require(admission_policy_contract.digest(frozen) == ADMISSION_POLICY_SHA256,
            "AUTHORITY_ADMISSION_POLICY_MISMATCH")
    return value, digest(value)


def validate_genesis(value, policy_sha256):
    expected = {
        "schema_version": 1,
        "kind": "factor_admission_authority_genesis",
        "authority_id": AUTHORITY_ID,
        "workspace_id": WORKSPACE_ID,
        "epoch": 1,
        "authority_policy_sha256": policy_sha256,
        "admission_policy_sha256": ADMISSION_POLICY_SHA256,
        "created_at": "2026-11-05T00:00:00Z",
        "trust_class": "synthetic-structural-only",
        "status": "development-only-blocked",
    }
    require(_same_typed(value, expected), "AUTHORITY_GENESIS_INVALID")
    return value


def load_genesis():
    _policy, policy_sha = load_policy()
    value = validate_genesis(_read_json(GENESIS_PATH), policy_sha)
    return value, digest(value)


def _canonical_workspace(workspace_root):
    supplied = Path(workspace_root).absolute()
    require(supplied.exists() and supplied.is_dir(), "AUTHORITY_WORKSPACE_INVALID")
    for candidate in (supplied, *supplied.parents):
        require(not candidate.is_symlink(), "AUTHORITY_WORKSPACE_SYMLINK")
    try:
        resolved = supplied.resolve(strict=True)
    except OSError:
        raise AuthorityError("AUTHORITY_WORKSPACE_INVALID") from None
    require(resolved == supplied and resolved.stat().st_uid == os.getuid(),
            "AUTHORITY_WORKSPACE_INVALID")
    return resolved


def _workspace_binding(workspace_root):
    root = _canonical_workspace(workspace_root)
    details = root.stat()
    return digest({"authority_id": AUTHORITY_ID, "workspace_id": WORKSPACE_ID,
                   "realpath": str(root), "device": details.st_dev, "inode": details.st_ino})


def _ledger_root(workspace_root):
    workspace = _canonical_workspace(workspace_root)
    _workspace_binding(workspace)
    relative = Path(LEDGER_RELATIVE_PATH)
    require(not relative.is_absolute() and ".." not in relative.parts,
            "AUTHORITY_LEDGER_PATH_INVALID")
    current = workspace
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists():
            require(current.is_dir() and not current.is_symlink() and
                    current.stat().st_uid == os.getuid(), "AUTHORITY_LEDGER_PATH_INVALID")
    return workspace / relative


def _ensure_parent(root, workspace):
    current = workspace
    for part in Path(LEDGER_RELATIVE_PATH).parts[:-1]:
        current = current / part
        if not current.exists():
            os.mkdir(current, 0o700)
        require(current.is_dir() and not current.is_symlink() and
                current.stat().st_uid == os.getuid(), "AUTHORITY_LEDGER_PATH_INVALID")


def _destination_state(path, payload):
    """Return a sanitized readback state without following destination symlinks."""
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unavailable"
    try:
        details = os.fstat(descriptor)
        if (not stat.S_ISREG(details.st_mode) or details.st_uid != os.getuid() or
                details.st_size != len(payload)):
            return "different"
        chunks = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                return "different"
            chunks.append(chunk)
            remaining -= len(chunk)
        return "match" if secrets.compare_digest(b"".join(chunks), payload) else "different"
    except OSError:
        return "unavailable"
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _raise_write_failure(path, payload, *, effect_attempted):
    state = _destination_state(path, payload)
    if effect_attempted:
        raise AuthorityWriteDurabilityUnknown(path, payload, state) from None
    raise AuthorityWriteFailed() from None


def _fsync_parent(path, payload):
    directory = None
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(directory)
        os.close(directory)
        directory = None
    except OSError:
        raise AuthorityWriteDurabilityUnknown(path, payload) from None
    finally:
        if directory is not None:
            try:
                os.close(directory)
            except OSError:
                pass


def _atomic_write(path, payload, *, replace=False):
    path = Path(path)
    require(type(payload) is bytes and payload, "AUTHORITY_WRITE_FAILED")
    state = _destination_state(path, payload)
    if state == "match":
        _fsync_parent(path, payload)
        return
    if not replace and state == "different":
        raise AuthorityError("AUTHORITY_IMMUTABLE_CONFLICT")

    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = None
    effect_attempted = False
    try:
        require(path.parent.is_dir() and not path.parent.is_symlink(),
                "AUTHORITY_WRITE_FAILED")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            require(type(written) is int and written > 0, "AUTHORITY_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        effect_attempted = True
        if replace:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path, follow_symlinks=False)
            except FileExistsError:
                if _destination_state(path, payload) == "match":
                    raise AuthorityWriteDurabilityUnknown(path, payload) from None
                raise AuthorityError("AUTHORITY_IMMUTABLE_CONFLICT") from None
            os.unlink(temporary)
        _fsync_parent(path, payload)
    except AuthorityError:
        raise
    except OSError:
        _raise_write_failure(path, payload, effect_attempted=effect_attempted)
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        except OSError:
            pass


def _write_reconciled(path, payload, *, replace=False):
    """Retry only after exact destination readback fences an unknown write effect."""
    try:
        _atomic_write(path, payload, replace=replace)
    except AuthorityWriteDurabilityUnknown as error:
        require(error.destination == str(Path(path)) and
                error.intended_sha256 == hashlib.sha256(payload).hexdigest() and
                error.intended_bytes == payload,
                "AUTHORITY_WRITE_RECONCILIATION_INVALID")
        if _destination_state(path, payload) != "match":
            raise
        _atomic_write(path, payload, replace=replace)
    except AuthorityWriteFailed:
        _atomic_write(path, payload, replace=replace)


def _record_bytes(value):
    return canonical(value) + b"\n"


def _checkpoint(genesis_sha, workspace_binding, sequence=0, last_event=None, chain=None):
    return {"schema_version": 1, "kind": "factor_authority_checkpoint",
            "authority_id": AUTHORITY_ID, "epoch": 1,
            "workspace_binding_sha256": workspace_binding,
            "genesis_sha256": genesis_sha, "sequence": sequence,
            "last_event_sha256": last_event,
            "chain_sha256": chain or genesis_sha}


def _validate_checkpoint(value, genesis_sha, workspace_binding):
    _strict(value, {"schema_version", "kind", "authority_id", "epoch",
                    "workspace_binding_sha256", "genesis_sha256", "sequence",
                    "last_event_sha256", "chain_sha256"}, "AUTHORITY_CHECKPOINT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_authority_checkpoint" and
            value["authority_id"] == AUTHORITY_ID and type(value["epoch"]) is int and
            value["epoch"] == 1 and value["workspace_binding_sha256"] == workspace_binding and
            value["genesis_sha256"] == genesis_sha and type(value["sequence"]) is int and
            value["sequence"] >= 0, "AUTHORITY_CHECKPOINT_INVALID")
    _optional_sha(value["last_event_sha256"]); _sha(value["chain_sha256"])
    require((value["sequence"] == 0) == (value["last_event_sha256"] is None),
            "AUTHORITY_CHECKPOINT_INVALID")
    return value


def _validate_provision(value, genesis_sha, policy_sha, workspace_binding):
    _strict(value, {"schema_version", "kind", "authority_id", "workspace_id", "epoch",
                    "genesis_sha256", "authority_policy_sha256", "workspace_binding_sha256",
                    "trust_class", "status"}, "AUTHORITY_PROVISION_SCHEMA")
    expected = {"schema_version": 1, "kind": "factor_authority_provision",
                "authority_id": AUTHORITY_ID, "workspace_id": WORKSPACE_ID, "epoch": 1,
                "genesis_sha256": genesis_sha, "authority_policy_sha256": policy_sha,
                "workspace_binding_sha256": workspace_binding,
                "trust_class": "synthetic", "status": "structural-fixture-only"}
    require(_same_typed(value, expected), "AUTHORITY_PROVISION_INVALID")
    return value


def provision_fixture_authority(workspace_root):
    workspace = _canonical_workspace(workspace_root)
    binding = _workspace_binding(workspace)
    root = _ledger_root(workspace)
    require(not root.exists(), "AUTHORITY_ALREADY_PROVISIONED")
    _ensure_parent(root, workspace)
    os.mkdir(root, 0o700)
    os.mkdir(root / "events", 0o700)
    policy, policy_sha = load_policy()
    genesis, genesis_sha = load_genesis()
    _atomic_write(root / "policy.json", _record_bytes(policy))
    _atomic_write(root / "genesis.json", _record_bytes(genesis))
    provision = {"schema_version": 1, "kind": "factor_authority_provision",
                 "authority_id": AUTHORITY_ID, "workspace_id": WORKSPACE_ID, "epoch": 1,
                 "genesis_sha256": genesis_sha, "authority_policy_sha256": policy_sha,
                 "workspace_binding_sha256": binding, "trust_class": "synthetic",
                 "status": "structural-fixture-only"}
    _atomic_write(root / "provision.json", _record_bytes(provision))
    _atomic_write(root / "checkpoint.json", _record_bytes(_checkpoint(genesis_sha, binding)))
    _atomic_write(root / "lock", b"fixture-lock\n")
    return {"authority_id": AUTHORITY_ID, "root": str(root),
            "genesis_sha256": genesis_sha, "workspace_binding_sha256": binding,
            "status": "development-only-blocked"}


def _event_filename(sequence, event_sha):
    return f"{sequence:020d}-{event_sha}.json"


def _split_fingerprints(value):
    _strict(value, {"development", "validation", "protected"},
            "AUTHORITY_SPLIT_FINGERPRINTS_INVALID")
    for identity in value.values():
        _sha(identity, "AUTHORITY_SPLIT_FINGERPRINTS_INVALID")
    return value


def _validate_payload(event_type, payload):
    require(type(payload) is dict, "AUTHORITY_EVENT_PAYLOAD_INVALID")
    if event_type == "dataset_bound":
        _strict(payload, PAYLOAD_KEYS[event_type], "AUTHORITY_DATASET_PAYLOAD_SCHEMA")
        require(payload["purpose"] == FIXTURE_PURPOSE and payload["trust_class"] == "synthetic" and
                payload["admission_policy_sha256"] == ADMISSION_POLICY_SHA256 and
                type(payload["fixture_only"]) is bool and payload["fixture_only"] is True and
                payload["performance_claim"] == "withheld", "AUTHORITY_DATASET_PAYLOAD_INVALID")
        for key in ("builder_receipt_sha256", "observation_set_sha256",
                    "feature_snapshot_sha256", "evaluation_population_sha256",
                    "split_spec_sha256"):
            _sha(payload[key], "AUTHORITY_DATASET_PAYLOAD_INVALID")
        _split_fingerprints(payload["split_fingerprints"])
    elif event_type == "fixture_nonce_issued":
        _strict(payload, PAYLOAD_KEYS[event_type], "AUTHORITY_NONCE_PAYLOAD_SCHEMA")
        require(payload["purpose"] == FIXTURE_PURPOSE and payload["trust_class"] == "synthetic" and
                payload["admission_policy_sha256"] == ADMISSION_POLICY_SHA256 and
                type(payload["protected_outcomes_allowed"]) is bool and
                payload["protected_outcomes_allowed"] is False,
                "AUTHORITY_NONCE_PAYLOAD_INVALID")
        for key in ("dataset_event_sha256", "semantic_config_sha256", "nonce_sha256",
                    "observation_set_sha256", "feature_snapshot_sha256",
                    "evaluation_population_sha256"):
            _sha(payload[key], "AUTHORITY_NONCE_PAYLOAD_INVALID")
        _split_fingerprints(payload["split_fingerprints"])
    elif event_type == "fixture_nonce_claimed":
        _strict(payload, PAYLOAD_KEYS[event_type], "AUTHORITY_CLAIM_PAYLOAD_SCHEMA")
        require(payload["purpose"] == FIXTURE_PURPOSE and payload["trust_class"] == "synthetic" and
                payload["claim_status"] == "claimed-unknown-until-terminal" and
                type(payload["outcome_accessed"]) is bool and payload["outcome_accessed"] is False,
                "AUTHORITY_CLAIM_PAYLOAD_INVALID")
        for key in ("nonce_sha256", "nonce_event_sha256", "dataset_event_sha256",
                    "semantic_config_sha256"):
            _sha(payload[key], "AUTHORITY_CLAIM_PAYLOAD_INVALID")
    elif event_type == "fixture_runner_terminal":
        _strict(payload, PAYLOAD_KEYS[event_type], "AUTHORITY_RUNNER_PAYLOAD_SCHEMA")
        require(payload["purpose"] == FIXTURE_PURPOSE and payload["trust_class"] == "synthetic" and
                payload["terminal_status"] in {"synthetic-structural-complete", "failed"} and
                type(payload["outcome_accessed"]) is bool and payload["outcome_accessed"] is False and
                type(payload["protected_labels_accessed"]) is bool and
                payload["protected_labels_accessed"] is False and
                payload["performance_claim"] == "withheld" and
                type(payload["artifact_size_bytes"]) is int and payload["artifact_size_bytes"] >= 0,
                "AUTHORITY_RUNNER_PAYLOAD_INVALID")
        for key in ("nonce_sha256", "nonce_event_sha256", "claim_event_sha256",
                    "dataset_event_sha256", "semantic_config_sha256", "request_sha256", "runner_receipt_sha256",
                    "runner_implementation_sha256"):
            _sha(payload[key], "AUTHORITY_RUNNER_PAYLOAD_INVALID")
        if payload["terminal_status"] == "synthetic-structural-complete":
            _sha(payload["artifact_sha256"], "AUTHORITY_RUNNER_PAYLOAD_INVALID")
            require(payload["artifact_size_bytes"] > 0 and payload["failure_code"] is None,
                    "AUTHORITY_RUNNER_PAYLOAD_INVALID")
        else:
            require(payload["artifact_sha256"] is None and payload["artifact_size_bytes"] == 0 and
                    payload["failure_code"] == "FIXED_WORKER_REJECTED",
                    "AUTHORITY_RUNNER_PAYLOAD_INVALID")
    elif event_type == "fixture_evaluator_terminal":
        _strict(payload, PAYLOAD_KEYS[event_type], "AUTHORITY_EVALUATOR_PAYLOAD_SCHEMA")
        require(payload["purpose"] == FIXTURE_PURPOSE and payload["trust_class"] == "synthetic" and
                payload["terminal_status"] == "synthetic-structural-complete" and
                payload["scientific_verdict"] == "withheld" and
                payload["independent_check_status"] == "unavailable" and
                type(payload["outcome_accessed"]) is bool and payload["outcome_accessed"] is False and
                type(payload["protected_labels_accessed"]) is bool and
                payload["protected_labels_accessed"] is False and
                payload["performance_claim"] == "withheld", "AUTHORITY_EVALUATOR_PAYLOAD_INVALID")
        for key in ("nonce_sha256", "runner_event_sha256", "runner_receipt_sha256",
                    "evaluator_request_sha256", "evaluator_receipt_sha256",
                    "evaluator_implementation_sha256"):
            _sha(payload[key], "AUTHORITY_EVALUATOR_PAYLOAD_INVALID")
    else:
        raise AuthorityError("AUTHORITY_EVENT_TYPE_INVALID")
    return payload


def _validate_event(value):
    _strict(value, {"schema_version", "kind", "authority_id", "epoch", "sequence",
                    "previous_event_sha256", "previous_chain_sha256", "event_type",
                    "created_at", "payload"}, "AUTHORITY_EVENT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_authority_event" and value["authority_id"] == AUTHORITY_ID and
            type(value["epoch"]) is int and value["epoch"] == 1 and
            type(value["sequence"]) is int and value["sequence"] > 0 and
            type(value["event_type"]) is str, "AUTHORITY_EVENT_INVALID")
    _optional_sha(value["previous_event_sha256"]); _sha(value["previous_chain_sha256"])
    _timestamp(value["created_at"])
    _validate_payload(value["event_type"], value["payload"])
    return value


def _event_chain(previous_chain, event_sha):
    return digest({"previous_chain_sha256": previous_chain, "event_sha256": event_sha})


def _validate_relationships(records):
    prior = []
    for record in records:
        event = record["event"]
        payload = event["payload"]
        event_type = event["event_type"]
        if event_type == "fixture_nonce_issued":
            datasets = [item for item in prior
                        if item["event"]["event_type"] == "dataset_bound" and
                        item["event_sha256"] == payload["dataset_event_sha256"]]
            require(len(datasets) == 1, "AUTHORITY_NONCE_DATASET_RELATION_INVALID")
            bound = datasets[0]["event"]["payload"]
            require(payload["observation_set_sha256"] == bound["observation_set_sha256"] and
                    payload["feature_snapshot_sha256"] == bound["feature_snapshot_sha256"] and
                    payload["evaluation_population_sha256"] == bound["evaluation_population_sha256"] and
                    payload["split_fingerprints"] == bound["split_fingerprints"],
                    "AUTHORITY_NONCE_IDENTITY_MISMATCH")
            require(not any(item["event"]["event_type"] == "fixture_nonce_issued" and
                            item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]
                            for item in prior), "AUTHORITY_NONCE_DUPLICATE")
        elif event_type == "fixture_nonce_claimed":
            nonces = [item for item in prior
                      if item["event"]["event_type"] == "fixture_nonce_issued" and
                      item["event_sha256"] == payload["nonce_event_sha256"] and
                      item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]]
            require(len(nonces) == 1, "AUTHORITY_CLAIM_NONCE_RELATION_INVALID")
            issued = nonces[0]["event"]["payload"]
            require(payload["dataset_event_sha256"] == issued["dataset_event_sha256"] and
                    payload["semantic_config_sha256"] == issued["semantic_config_sha256"],
                    "AUTHORITY_CLAIM_BINDING_MISMATCH")
            require(not any(item["event"]["event_type"] in
                            {"fixture_nonce_claimed", "fixture_runner_terminal"} and
                            item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]
                            for item in prior), "AUTHORITY_NONCE_ALREADY_CLAIMED")
        elif event_type == "fixture_runner_terminal":
            claims = [item for item in prior
                      if item["event"]["event_type"] == "fixture_nonce_claimed" and
                      item["event_sha256"] == payload["claim_event_sha256"] and
                      item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]]
            require(len(claims) == 1, "AUTHORITY_RUNNER_CLAIM_RELATION_INVALID")
            claimed = claims[0]["event"]["payload"]
            require(payload["nonce_event_sha256"] == claimed["nonce_event_sha256"] and
                    payload["dataset_event_sha256"] == claimed["dataset_event_sha256"] and
                    payload["semantic_config_sha256"] == claimed["semantic_config_sha256"],
                    "AUTHORITY_RUNNER_BINDING_MISMATCH")
            require(not any(item["event"]["event_type"] == "fixture_runner_terminal" and
                            item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]
                            for item in prior), "AUTHORITY_RUNNER_DUPLICATE")
        elif event_type == "fixture_evaluator_terminal":
            runners = [item for item in prior
                       if item["event"]["event_type"] == "fixture_runner_terminal" and
                       item["event_sha256"] == payload["runner_event_sha256"] and
                       item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]]
            require(len(runners) == 1, "AUTHORITY_EVALUATOR_RUNNER_RELATION_INVALID")
            runner = runners[0]["event"]["payload"]
            require(payload["runner_receipt_sha256"] == runner["runner_receipt_sha256"],
                    "AUTHORITY_EVALUATOR_BINDING_MISMATCH")
            require(not any(item["event"]["event_type"] == "fixture_evaluator_terminal" and
                            item["event"]["payload"]["nonce_sha256"] == payload["nonce_sha256"]
                            for item in prior), "AUTHORITY_EVALUATOR_DUPLICATE")
        prior.append(record)
    return records


@contextmanager
def _exclusive_lock(root):
    path = root / "lock"
    descriptor = None
    locked = False
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        details = os.fstat(descriptor)
        require(stat.S_ISREG(details.st_mode) and details.st_uid == os.getuid(),
                "AUTHORITY_LOCK_INVALID")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        locked = True
    except AuthorityError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        raise AuthorityError("AUTHORITY_LOCK_INVALID") from None
    try:
        yield
    finally:
        if locked:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            os.close(descriptor)
        except OSError:
            pass


class FixtureAuthority:
    """Structural authority available only for synthetic contract verification."""

    def __init__(self, workspace_root):
        self.workspace = _canonical_workspace(workspace_root)
        self.binding = _workspace_binding(self.workspace)
        self.root = _ledger_root(self.workspace)
        self.policy, self.policy_sha = load_policy()
        self.genesis, self.genesis_sha = load_genesis()
        self._verify()

    def _verify_root(self):
        require(self.root.is_dir() and not self.root.is_symlink() and
                self.root.stat().st_uid == os.getuid(), "AUTHORITY_NOT_PROVISIONED")
        events = self.root / "events"
        require(events.is_dir() and not events.is_symlink() and
                events.stat().st_uid == os.getuid(), "AUTHORITY_EVENTS_INVALID")
        require(_read_json(self.root / "policy.json") == self.policy,
                "AUTHORITY_POLICY_MISMATCH")
        require(_read_json(self.root / "genesis.json") == self.genesis,
                "AUTHORITY_GENESIS_MISMATCH")
        _validate_provision(_read_json(self.root / "provision.json"), self.genesis_sha,
                            self.policy_sha, self.binding)

    def _reconstruct(self, *, recover_checkpoint=False):
        self._verify_root()
        previous_event = None
        chain = self.genesis_sha
        records = []
        names = []
        try:
            with os.scandir(self.root / "events") as entries:
                for entry in entries:
                    names.append(entry.name)
                    require(len(names) <= self.policy["max_events"], "AUTHORITY_EVENT_LIMIT")
        except AuthorityError:
            raise
        except OSError:
            raise AuthorityError("AUTHORITY_EVENTS_INVALID") from None
        paths = [self.root / "events" / name for name in sorted(names)]
        for expected, path in enumerate(paths, 1):
            require(path.is_file() and not path.is_symlink() and path.suffix == ".json",
                    "AUTHORITY_EVENT_FILE_INVALID")
            value = _validate_event(_read_json(path))
            event_sha = digest(value)
            require(path.name == _event_filename(expected, event_sha) and
                    value["sequence"] == expected and
                    value["previous_event_sha256"] == previous_event and
                    value["previous_chain_sha256"] == chain,
                    "AUTHORITY_EVENT_CHAIN_INVALID")
            chain = _event_chain(chain, event_sha)
            previous_event = event_sha
            records.append({"event": value, "event_sha256": event_sha,
                            "chain_sha256": chain})
        _validate_relationships(records)
        expected_checkpoint = _checkpoint(self.genesis_sha, self.binding, len(records),
                                          previous_event, chain)
        actual = _validate_checkpoint(_read_json(self.root / "checkpoint.json"),
                                      self.genesis_sha, self.binding)
        if actual != expected_checkpoint and recover_checkpoint:
            require(len(records) == actual["sequence"] + 1 and
                    actual == _checkpoint(
                        self.genesis_sha, self.binding, len(records) - 1,
                        records[-2]["event_sha256"] if len(records) > 1 else None,
                        records[-2]["chain_sha256"] if len(records) > 1 else self.genesis_sha),
                    "AUTHORITY_CHECKPOINT_STALE")
            _write_reconciled(self.root / "checkpoint.json",
                              _record_bytes(expected_checkpoint), replace=True)
            actual = expected_checkpoint
        require(actual == expected_checkpoint, "AUTHORITY_CHECKPOINT_STALE")
        return records, actual

    def _verify(self):
        with _exclusive_lock(self.root):
            return self._reconstruct(recover_checkpoint=True)

    def status(self):
        records, checkpoint = self._verify()
        return {"authority_id": AUTHORITY_ID, "status": self.policy["status"],
                "active": False, "sequence": checkpoint["sequence"],
                "blockers": list(self.policy["blockers"]), "events": len(records)}

    def assert_active(self):
        raise AuthorityError("AUTHORITY_PRODUCTION_BLOCKED")

    def _append_factory(self, event_type, payload_factory):
        with _exclusive_lock(self.root):
            records, checkpoint = self._reconstruct(recover_checkpoint=True)
            require(checkpoint["sequence"] < self.policy["max_events"], "AUTHORITY_EVENT_LIMIT")
            payload = payload_factory(records)
            require(type(payload) is dict, "AUTHORITY_EVENT_PAYLOAD_INVALID")
            sequence = checkpoint["sequence"] + 1
            event = {"schema_version": 1, "kind": "factor_authority_event",
                     "authority_id": AUTHORITY_ID, "epoch": 1, "sequence": sequence,
                     "previous_event_sha256": checkpoint["last_event_sha256"],
                     "previous_chain_sha256": checkpoint["chain_sha256"],
                     "event_type": event_type,
                     "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                     "payload": payload}
            _validate_event(event)
            event_sha = digest(event)
            chain = _event_chain(checkpoint["chain_sha256"], event_sha)
            _validate_relationships([*records, {"event": event, "event_sha256": event_sha,
                                                "chain_sha256": chain}])
            event_bytes = _record_bytes(event)
            checkpoint_bytes = _record_bytes(
                _checkpoint(self.genesis_sha, self.binding, sequence, event_sha, chain))
            _write_reconciled(self.root / "events" / _event_filename(sequence, event_sha),
                              event_bytes)
            _write_reconciled(self.root / "checkpoint.json", checkpoint_bytes, replace=True)
            return {"event": event, "event_sha256": event_sha, "chain_sha256": chain}

    def _append(self, event_type, payload):
        return self._append_factory(event_type, lambda _records: payload)

    def _events(self, event_type=None):
        records, _checkpoint_value = self._verify()
        return [record for record in records
                if event_type is None or record["event"]["event_type"] == event_type]

    def bind_fixture_dataset(self, dataset_root):
        try:
            build = build_snapshot(dataset_root)
        except Exception:
            raise AuthorityError("AUTHORITY_DATASET_INVALID") from None
        require(build.get("fixture_only") is True and build.get("performance_claim") == "withheld",
                "AUTHORITY_DATASET_TRUST_INVALID")
        receipt = build.get("builder_receipt")
        require(type(receipt) is dict and receipt.get("trust_class") == "synthetic" and
                receipt.get("performance_claim") == "withheld" and
                digest(receipt) == build.get("builder_receipt_sha256"),
                "AUTHORITY_DATASET_RECEIPT_INVALID")
        fields = ("observation_set_sha256", "feature_snapshot_sha256",
                  "evaluation_population_sha256", "split_spec_sha256")
        require(all(receipt.get(key) == build.get(key) and SHA.fullmatch(build.get(key, ""))
                    for key in fields), "AUTHORITY_DATASET_BINDING_INVALID")
        split_fingerprints = build.get("split_fingerprints")
        require(type(split_fingerprints) is dict and set(split_fingerprints) ==
                {"development", "validation", "protected"} and
                all(type(value) is str and SHA.fullmatch(value)
                    for value in split_fingerprints.values()),
                "AUTHORITY_DATASET_SPLITS_INVALID")
        payload = {"purpose": FIXTURE_PURPOSE, "trust_class": "synthetic",
                   "admission_policy_sha256": ADMISSION_POLICY_SHA256,
                   "builder_receipt_sha256": build["builder_receipt_sha256"],
                   "observation_set_sha256": build["observation_set_sha256"],
                   "feature_snapshot_sha256": build["feature_snapshot_sha256"],
                   "evaluation_population_sha256": build["evaluation_population_sha256"],
                   "split_spec_sha256": build["split_spec_sha256"],
                   "split_fingerprints": dict(sorted(split_fingerprints.items())),
                   "fixture_only": True, "performance_claim": "withheld"}
        return self._append("dataset_bound", payload)

    def issue_fixture_nonce(self, dataset_event_sha256, semantic_config_sha256):
        _sha(dataset_event_sha256); _sha(semantic_config_sha256)
        raw_nonce = secrets.token_hex(32)
        nonce_sha = hashlib.sha256(bytes.fromhex(raw_nonce)).hexdigest()
        def make_payload(records):
            matches = [record for record in records
                       if record["event"]["event_type"] == "dataset_bound" and
                       record["event_sha256"] == dataset_event_sha256]
            require(len(matches) == 1, "AUTHORITY_DATASET_EVENT_UNKNOWN")
            require(not any(record["event"]["payload"].get("nonce_sha256") == nonce_sha
                            for record in records), "AUTHORITY_NONCE_COLLISION")
            binding = matches[0]["event"]["payload"]
            return {"purpose": FIXTURE_PURPOSE, "trust_class": "synthetic",
                    "admission_policy_sha256": ADMISSION_POLICY_SHA256,
                    "dataset_event_sha256": dataset_event_sha256,
                    "semantic_config_sha256": semantic_config_sha256,
                    "nonce_sha256": nonce_sha,
                    "observation_set_sha256": binding["observation_set_sha256"],
                    "feature_snapshot_sha256": binding["feature_snapshot_sha256"],
                    "evaluation_population_sha256": binding["evaluation_population_sha256"],
                    "split_fingerprints": binding["split_fingerprints"],
                    "protected_outcomes_allowed": False}
        event = self._append_factory("fixture_nonce_issued", make_payload)
        return {"nonce": raw_nonce, "nonce_sha256": nonce_sha,
                "event_sha256": event["event_sha256"], "purpose": FIXTURE_PURPOSE}

    def verify_fixture_binding(self, raw_nonce, binding):
        try:
            from investment.factor_mining.rdagent_adapter.v2 import contracts as runner_contracts
            runner_contracts.validate_binding(binding)
        except Exception:
            raise AuthorityError("AUTHORITY_FIXTURE_BINDING_INVALID") from None
        require(type(raw_nonce) is str and re.fullmatch(r"[a-f0-9]{64}", raw_nonce),
                "AUTHORITY_NONCE_INVALID")
        nonce_sha = hashlib.sha256(bytes.fromhex(raw_nonce)).hexdigest()
        require(binding["nonce_sha256"] == nonce_sha, "AUTHORITY_NONCE_MISMATCH")
        records, _checkpoint_value = self._verify()
        datasets = [record for record in records
                    if record["event"]["event_type"] == "dataset_bound" and
                    record["event_sha256"] == binding["dataset_event_sha256"]]
        nonces = [record for record in records
                  if record["event"]["event_type"] == "fixture_nonce_issued" and
                  record["event_sha256"] == binding["nonce_event_sha256"] and
                  record["event"]["payload"]["nonce_sha256"] == nonce_sha]
        require(len(datasets) == 1 and len(nonces) == 1,
                "AUTHORITY_FIXTURE_BINDING_UNKNOWN")
        dataset = datasets[0]["event"]["payload"]
        issued = nonces[0]["event"]["payload"]
        require(issued["dataset_event_sha256"] == binding["dataset_event_sha256"] and
                issued["semantic_config_sha256"] == binding["semantic_config_sha256"] and
                dataset["builder_receipt_sha256"] == binding["builder_receipt_sha256"] and
                dataset["observation_set_sha256"] == binding["observation_set_sha256"] and
                dataset["feature_snapshot_sha256"] == binding["feature_snapshot_sha256"] and
                dataset["evaluation_population_sha256"] == binding["evaluation_population_sha256"] and
                dataset["split_fingerprints"] == binding["split_fingerprints"] and
                issued["observation_set_sha256"] == binding["observation_set_sha256"] and
                issued["feature_snapshot_sha256"] == binding["feature_snapshot_sha256"] and
                issued["evaluation_population_sha256"] == binding["evaluation_population_sha256"] and
                issued["split_fingerprints"] == binding["split_fingerprints"],
                "AUTHORITY_FIXTURE_BINDING_MISMATCH")
        require(not any(record["event"]["event_type"] in
                        {"fixture_nonce_claimed", "fixture_runner_terminal"} and
                        record["event"]["payload"]["nonce_sha256"] == nonce_sha
                        for record in records), "AUTHORITY_NONCE_ALREADY_CLAIMED")
        return {"dataset_event": datasets[0], "nonce_event": nonces[0],
                "nonce_sha256": nonce_sha, "binding": binding}

    def claim_fixture_nonce(self, raw_nonce, binding):
        self.verify_fixture_binding(raw_nonce, binding)
        nonce_sha = binding["nonce_sha256"]
        def make_payload(records):
            datasets = [record for record in records
                        if record["event"]["event_type"] == "dataset_bound" and
                        record["event_sha256"] == binding["dataset_event_sha256"]]
            nonces = [record for record in records
                      if record["event"]["event_type"] == "fixture_nonce_issued" and
                      record["event_sha256"] == binding["nonce_event_sha256"] and
                      record["event"]["payload"]["nonce_sha256"] == nonce_sha]
            require(len(datasets) == 1 and len(nonces) == 1,
                    "AUTHORITY_FIXTURE_BINDING_UNKNOWN")
            issued = nonces[0]["event"]["payload"]
            require(issued["dataset_event_sha256"] == binding["dataset_event_sha256"] and
                    issued["semantic_config_sha256"] == binding["semantic_config_sha256"],
                    "AUTHORITY_CLAIM_BINDING_MISMATCH")
            require(not any(record["event"]["event_type"] in
                            {"fixture_nonce_claimed", "fixture_runner_terminal"} and
                            record["event"]["payload"]["nonce_sha256"] == nonce_sha
                            for record in records), "AUTHORITY_NONCE_ALREADY_CLAIMED")
            return {"purpose": FIXTURE_PURPOSE, "trust_class": "synthetic",
                    "nonce_sha256": nonce_sha, "nonce_event_sha256": binding["nonce_event_sha256"],
                    "dataset_event_sha256": binding["dataset_event_sha256"],
                    "semantic_config_sha256": binding["semantic_config_sha256"],
                    "claim_status": "claimed-unknown-until-terminal", "outcome_accessed": False}
        return self._append_factory("fixture_nonce_claimed", make_payload)

    def _runner_material(self, request, receipt, artifact_bytes, *, raw_nonce=None):
        try:
            from investment.factor_mining.rdagent_adapter.v2 import contracts as runner_contracts
            from investment.factor_mining.rdagent_adapter.v2 import fixed_worker
            from investment.factor_mining.rdagent_adapter.v2 import runner as runner_module
            runner_contracts.validate_request(request)
            runner_contracts.validate_receipt(receipt, request)
        except Exception:
            raise AuthorityError("AUTHORITY_RUNNER_RECEIPT_INVALID") from None
        if raw_nonce is not None:
            self.verify_fixture_binding(raw_nonce, request["authority_binding"])
        require(receipt["runner_implementation_sha256"] == runner_module.implementation_sha256(),
                "AUTHORITY_RUNNER_IMPLEMENTATION_MISMATCH")
        if receipt["status"] == "synthetic-structural-complete":
            require(type(artifact_bytes) is bytes and artifact_bytes and
                    hashlib.sha256(artifact_bytes).hexdigest() == receipt["artifact"]["sha256"] and
                    len(artifact_bytes) == receipt["artifact"]["size_bytes"],
                    "AUTHORITY_RUNNER_ARTIFACT_MISMATCH")
            try:
                proof = runner_contracts.loads_strict(
                    artifact_bytes, request["limits"]["artifact_bytes"],
                    "AUTHORITY_RUNNER_ARTIFACT_SIZE")
            except Exception:
                raise AuthorityError("AUTHORITY_RUNNER_ARTIFACT_INVALID") from None
            binding = request["authority_binding"]
            expected = {"schema_version": 1, "kind": "synthetic_authority_binding_proof",
                        "worker_version": fixed_worker.WORKER_VERSION,
                        "request_sha256": runner_contracts.request_sha256(request),
                        "builder_receipt_sha256": binding["builder_receipt_sha256"],
                        "observation_set_sha256": binding["observation_set_sha256"],
                        "feature_snapshot_sha256": binding["feature_snapshot_sha256"],
                        "evaluation_population_sha256": binding["evaluation_population_sha256"],
                        "split_fingerprints": binding["split_fingerprints"],
                        "outcome_accessed": False, "protected_labels_accessed": False,
                        "performance_claim": "withheld"}
            require(proof == expected and artifact_bytes == runner_contracts.canonical(proof),
                    "AUTHORITY_RUNNER_ARTIFACT_INVALID")
            artifact_sha = receipt["artifact"]["sha256"]
            artifact_size = receipt["artifact"]["size_bytes"]
        else:
            require(artifact_bytes is None and receipt["artifact"] is None,
                    "AUTHORITY_RUNNER_ARTIFACT_MISMATCH")
            artifact_sha = None
            artifact_size = 0
        return {"contracts": runner_contracts,
                "request_sha256": runner_contracts.request_sha256(request),
                "receipt_sha256": runner_contracts.digest(receipt),
                "artifact_sha256": artifact_sha, "artifact_size_bytes": artifact_size}

    def record_fixture_runner_receipt(self, raw_nonce, request, receipt, artifact_bytes):
        material = self._runner_material(request, receipt, artifact_bytes)
        binding = request["authority_binding"]
        require(type(raw_nonce) is str and re.fullmatch(r"[a-f0-9]{64}", raw_nonce),
                "AUTHORITY_NONCE_INVALID")
        nonce_sha = hashlib.sha256(bytes.fromhex(raw_nonce)).hexdigest()
        require(nonce_sha == binding["nonce_sha256"], "AUTHORITY_NONCE_MISMATCH")
        def make_payload(records):
            claims = [record for record in records
                      if record["event"]["event_type"] == "fixture_nonce_claimed" and
                      record["event"]["payload"]["nonce_sha256"] == nonce_sha and
                      record["event"]["payload"]["nonce_event_sha256"] == binding["nonce_event_sha256"]]
            require(len(claims) == 1, "AUTHORITY_RUNNER_CLAIM_REQUIRED")
            require(not any(record["event"]["event_type"] == "fixture_runner_terminal" and
                            record["event"]["payload"]["nonce_sha256"] == nonce_sha
                            for record in records), "AUTHORITY_NONCE_REUSED")
            return {"purpose": FIXTURE_PURPOSE, "trust_class": "synthetic",
                    "nonce_sha256": nonce_sha,
                    "nonce_event_sha256": binding["nonce_event_sha256"],
                    "claim_event_sha256": claims[0]["event_sha256"],
                    "dataset_event_sha256": binding["dataset_event_sha256"],
                    "semantic_config_sha256": binding["semantic_config_sha256"],
                    "request_sha256": material["request_sha256"],
                    "runner_receipt_sha256": material["receipt_sha256"],
                    "runner_implementation_sha256": receipt["runner_implementation_sha256"],
                    "artifact_sha256": material["artifact_sha256"],
                    "artifact_size_bytes": material["artifact_size_bytes"],
                    "terminal_status": receipt["status"], "failure_code": receipt["failure_code"],
                    "outcome_accessed": receipt["outcome_accessed"],
                    "protected_labels_accessed": receipt["protected_labels_accessed"],
                    "performance_claim": receipt["performance_claim"]}
        return self._append_factory("fixture_runner_terminal", make_payload)

    def verify_fixture_runner_event(self, event_sha256, request, receipt, artifact_bytes):
        _sha(event_sha256)
        material = self._runner_material(request, receipt, artifact_bytes)
        binding = request["authority_binding"]
        records, _checkpoint_value = self._verify()
        matches = [record for record in records
                   if record["event"]["event_type"] == "fixture_runner_terminal" and
                   record["event_sha256"] == event_sha256]
        claims = [record for record in records
                  if record["event"]["event_type"] == "fixture_nonce_claimed" and
                  record["event"]["payload"]["nonce_sha256"] == binding["nonce_sha256"] and
                  record["event"]["payload"]["nonce_event_sha256"] == binding["nonce_event_sha256"]]
        require(len(matches) == 1, "AUTHORITY_RUNNER_EVENT_UNKNOWN")
        require(len(claims) == 1, "AUTHORITY_RUNNER_CLAIM_REQUIRED")
        payload = matches[0]["event"]["payload"]
        expected = {"purpose": FIXTURE_PURPOSE, "trust_class": "synthetic",
                    "nonce_sha256": binding["nonce_sha256"],
                    "nonce_event_sha256": binding["nonce_event_sha256"],
                    "claim_event_sha256": claims[0]["event_sha256"],
                    "dataset_event_sha256": binding["dataset_event_sha256"],
                    "semantic_config_sha256": binding["semantic_config_sha256"],
                    "request_sha256": material["request_sha256"],
                    "runner_receipt_sha256": material["receipt_sha256"],
                    "runner_implementation_sha256": receipt["runner_implementation_sha256"],
                    "artifact_sha256": material["artifact_sha256"],
                    "artifact_size_bytes": material["artifact_size_bytes"],
                    "terminal_status": receipt["status"], "failure_code": receipt["failure_code"],
                    "outcome_accessed": receipt["outcome_accessed"],
                    "protected_labels_accessed": receipt["protected_labels_accessed"],
                    "performance_claim": receipt["performance_claim"]}
        require(payload == expected, "AUTHORITY_RUNNER_EVENT_MISMATCH")
        return matches[0]

    def record_fixture_evaluator_receipt(self, runner_event_sha256, evaluator_request,
                                         evaluator_receipt):
        _sha(runner_event_sha256)
        try:
            from tuning.factor_mining.evaluator import contract as evaluator_contract
            evaluator_contract.validate_request(evaluator_request, fixture_authority=self)
            evaluator_contract.validate_receipt(evaluator_receipt, request=evaluator_request)
        except Exception:
            raise AuthorityError("AUTHORITY_EVALUATOR_RECEIPT_INVALID") from None
        require(evaluator_receipt["evaluator_implementation_sha256"] ==
                evaluator_contract.evaluator_implementation_sha256(),
                "AUTHORITY_EVALUATOR_IMPLEMENTATION_MISMATCH")
        runner_receipt = evaluator_request["runner_receipt"]
        binding = runner_receipt["authority_binding"]
        records, _checkpoint_value = self._verify()
        runners = [record for record in records
                   if record["event"]["event_type"] == "fixture_runner_terminal" and
                   record["event_sha256"] == runner_event_sha256]
        require(len(runners) == 1, "AUTHORITY_RUNNER_EVENT_UNKNOWN")
        runner_payload = runners[0]["event"]["payload"]
        require(runner_payload["nonce_sha256"] == binding["nonce_sha256"] and
                runner_payload["runner_receipt_sha256"] == evaluator_contract.digest(runner_receipt) and
                runner_payload["terminal_status"] == "synthetic-structural-complete",
                "AUTHORITY_EVALUATOR_RUNNER_MISMATCH")
        evaluator_request_sha = evaluator_contract.digest(evaluator_request)
        evaluator_receipt_sha = evaluator_contract.digest(evaluator_receipt)
        nonce_sha = binding["nonce_sha256"]
        def make_payload(current):
            require(not any(record["event"]["event_type"] == "fixture_evaluator_terminal" and
                            record["event"]["payload"]["nonce_sha256"] == nonce_sha
                            for record in current), "AUTHORITY_EVALUATOR_REUSED")
            return {"purpose": FIXTURE_PURPOSE, "trust_class": "synthetic",
                    "nonce_sha256": nonce_sha, "runner_event_sha256": runner_event_sha256,
                    "runner_receipt_sha256": evaluator_contract.digest(runner_receipt),
                    "evaluator_request_sha256": evaluator_request_sha,
                    "evaluator_receipt_sha256": evaluator_receipt_sha,
                    "evaluator_implementation_sha256": evaluator_receipt["evaluator_implementation_sha256"],
                    "terminal_status": evaluator_receipt["terminal_status"],
                    "scientific_verdict": evaluator_receipt["scientific_verdict"],
                    "independent_check_status": evaluator_receipt["independent_check_status"],
                    "outcome_accessed": evaluator_receipt["outcome_accessed"],
                    "protected_labels_accessed": evaluator_receipt["protected_labels_accessed"],
                    "performance_claim": evaluator_receipt["performance_claim"]}
        return self._append_factory("fixture_evaluator_terminal", make_payload)

    def record_fixture_runner(self, *_args, **_kwargs):
        raise AuthorityError("AUTHORITY_HASH_ONLY_RECEIPT_REJECTED")

    def record_fixture_evaluator(self, *_args, **_kwargs):
        raise AuthorityError("AUTHORITY_HASH_ONLY_RECEIPT_REJECTED")

    def authorize(self, _purpose, _payload):
        raise AuthorityError("AUTHORITY_PUBLICATION_BLOCKED")


def open_fixture_authority(workspace_root):
    return FixtureAuthority(workspace_root)


def open_authority():
    """Open the fixed real workspace root; it remains blocked until externally provisioned."""
    authority = FixtureAuthority(WORKSPACE_ROOT)
    authority.assert_active()
    return authority
