"""Outcome-free exposure ledger and conservative fresh-split planner.

This module records only immutable references proving that outcomes were seen. It
never stores outcomes, metrics, predictions or performance summaries themselves.
The local ledger is a structural fixture, not canonical production authority.
"""
from bisect import bisect_right
from contextlib import contextmanager
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from factor.source_inventory import contract as source_inventory_contract
from tuning.factor_mining.admission_policy import policy as admission_policy_contract
from tuning.factor_mining.trusted_authority import contract as trusted_authority_contract

ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
MAX_JSON = 64 * 1024
MAX_EVENTS = 512
EXPOSURE_CLASSES = {"raw_outcome", "outcome_summary", "strategy_result", "selection_feedback"}
SOURCE_TYPES = {"public_share", "local_report", "reviewer_receipt", "manual_inventory"}
LIMITATION_CODES = {"reported-unverified", "historical-inventory-incomplete",
                    "date-only-scope", "manual-review-required"}
ADMISSION_POLICY_SHA256 = "d010b96585994ba2bc712ba96d580cbc2cd669b03bbf41eaeee2b855c53c0b9f"
WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
ADMISSION_POLICY_PATH = WORKSPACE_ROOT / "tuning/factor_mining/admission_policy/initial-confirmatory-policy.json"
SOURCE_INVENTORY_PATH = WORKSPACE_ROOT / "factor/source_inventory/candidate-real-inventory.json"
SUBJECT_ROLES = {"spy": ("spy_market",), "oneq": ("oneq_market",),
                 "joint-spy-oneq": ("spy_market", "oneq_market")}
SUBJECT_SEMANTIC_FIELDS = ("role", "source_kind", "entity_scope", "unit",
                           "frequency", "revision_policy", "provider_routes")
READINESS_BLOCKERS = ["trusted-exposure-ledger-backend-unresolved",
                      "outcome-exposure-inventory-incomplete",
                      "calendar-attestation-unresolved",
                      "fresh-validation-coverage-unverified",
                      "fresh-protected-coverage-unverified"]
IDENTITY_BLOCKERS = {
    "dataset_snapshot_sha256": "dataset-snapshot-identity-unresolved",
    "observation_set_sha256": "observation-set-identity-unresolved",
    "feature_snapshot_sha256": "feature-snapshot-identity-unresolved",
    "evaluation_population_sha256": "evaluation-population-identity-unresolved",
}
FORBIDDEN_KEYS = {"value", "values", "metric", "metrics", "result", "results", "return", "returns", "performance", "prediction", "position", "label", "labels", "p_value", "interval"}
FORBIDDEN_TEXT = re.compile(r"(?i)(api[_-]?key|password|bearer\s|secret\s*[=:]|sk-proj-|/users/|/private/)")


class ExposureError(ValueError):
    """Stable, sanitized exposure failure."""


class ExposureWriteFailed(ExposureError):
    """A write failed before its destination effect boundary."""

    def __init__(self):
        super().__init__("EXPOSURE_WRITE_FAILED")
        self.effect_attempted = False


class ExposureWriteDurabilityUnknown(ExposureError):
    """A destination effect was attempted but durability/readback is unconfirmed."""

    def __init__(self, destination, intended_bytes, readback_state=None):
        super().__init__("EXPOSURE_WRITE_DURABILITY_UNKNOWN")
        self.destination = str(Path(destination))
        self.intended_bytes = bytes(intended_bytes)
        self.intended_sha256 = hashlib.sha256(self.intended_bytes).hexdigest()
        self.intended_size_bytes = len(self.intended_bytes)
        self.readback_state = readback_state


def require(condition, code):
    if not condition:
        raise ExposureError(code)


def _pairs(items):
    value = {}
    for key, item in items:
        require(key not in value, "EXPOSURE_DUPLICATE_KEY")
        value[key] = item
    return value


def loads_strict(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= MAX_JSON, "EXPOSURE_JSON_SIZE")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              ExposureError("EXPOSURE_NONFINITE")))
    except ExposureError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise ExposureError("EXPOSURE_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise ExposureError("EXPOSURE_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _id(value, code="EXPOSURE_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def _sha(value, code="EXPOSURE_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _day(value, code="EXPOSURE_DATE_INVALID"):
    require(type(value) is str and DAY.fullmatch(value), code)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise ExposureError(code) from None
    return value


def _time(value):
    require(type(value) is str and TIME.fullmatch(value), "EXPOSURE_TIME_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ExposureError("EXPOSURE_TIME_INVALID") from None
    require(parsed.utcoffset().total_seconds() == 0, "EXPOSURE_TIME_INVALID")
    return parsed


def _scan(value):
    def visit(item):
        if type(item) is dict:
            require(not (set(item) & FORBIDDEN_KEYS), "EXPOSURE_OUTCOME_FIELD_FORBIDDEN")
            for nested in item.values():
                visit(nested)
        elif type(item) is list:
            for nested in item:
                visit(nested)
        elif type(item) is str:
            require(not FORBIDDEN_TEXT.search(item), "EXPOSURE_SENSITIVE_CONTENT")
    visit(value)


def _validate_provenance(value):
    _strict(value, {"source_type", "source_ref_sha256", "limitations"},
            "EXPOSURE_PROVENANCE_SCHEMA")
    require(type(value["source_type"]) is str and value["source_type"] in SOURCE_TYPES,
            "EXPOSURE_SOURCE_TYPE_INVALID")
    _sha(value["source_ref_sha256"])
    require(type(value["limitations"]) is list and len(value["limitations"]) <= 16 and
            all(type(item) is str and item in LIMITATION_CODES
                for item in value["limitations"]), "EXPOSURE_LIMITATIONS_INVALID")
    _scan(value)
    return value


def _tracked_source_inventory():
    try:
        inventory = source_inventory_contract.load_inventory(SOURCE_INVENTORY_PATH)
    except Exception:
        raise ExposureError("EXPOSURE_SOURCE_INVENTORY_INVALID") from None
    return inventory, source_inventory_contract.inventory_sha256(inventory)


def _semantic_subject_sha256(subject_id):
    require(type(subject_id) is str and subject_id in SUBJECT_ROLES,
            "EXPOSURE_SUBJECT_INVALID")
    inventory, inventory_sha256 = _tracked_source_inventory()
    try:
        semantic_inventory = source_inventory_contract.semantic_inventory(inventory)
        entries = {entry["role"]: entry for entry in semantic_inventory["entries"]}
        roles = []
        for role in SUBJECT_ROLES[subject_id]:
            require(role in entries and
                    all(field in entries[role] for field in SUBJECT_SEMANTIC_FIELDS),
                    "EXPOSURE_SUBJECT_INVENTORY_MISMATCH")
            roles.append({field: entries[role][field] for field in SUBJECT_SEMANTIC_FIELDS})
    except ExposureError:
        raise
    except Exception:
        raise ExposureError("EXPOSURE_SUBJECT_INVENTORY_MISMATCH") from None
    return digest({"source_inventory_sha256": inventory_sha256,
                   "subject_id": subject_id, "role_semantics": roles})


def validate_event(value):
    _strict(value, {"schema_version", "kind", "ledger_genesis_sha256", "sequence",
                    "previous_event_sha256", "event_id", "exposure_class",
                    "semantic_subject_id", "source_inventory_sha256",
                    "evidence_sha256", "observed_at",
                    "latest_affected_session", "provenance"}, "EXPOSURE_EVENT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_outcome_exposure" and
            type(value["sequence"]) is int and value["sequence"] > 0,
            "EXPOSURE_EVENT_INVALID")
    _sha(value["ledger_genesis_sha256"], "EXPOSURE_GENESIS_SHA_INVALID")
    if value["previous_event_sha256"] is not None:
        _sha(value["previous_event_sha256"])
    _id(value["event_id"])
    _semantic_subject_sha256(value["semantic_subject_id"])
    _inventory, inventory_sha256 = _tracked_source_inventory()
    require(value["source_inventory_sha256"] == inventory_sha256,
            "EXPOSURE_SUBJECT_INVENTORY_MISMATCH")
    require(type(value["exposure_class"]) is str and
            value["exposure_class"] in EXPOSURE_CLASSES, "EXPOSURE_CLASS_INVALID")
    _sha(value["evidence_sha256"])
    observed = _time(value["observed_at"])
    affected = _day(value["latest_affected_session"])
    require(observed.date() > date.fromisoformat(affected), "EXPOSURE_BACKDATED_INVALID")
    _validate_provenance(value["provenance"])
    _scan(value)
    return value


def validate_readiness(value):
    expected = {"schema_version": 1, "kind": "factor_exposure_readiness",
                "status": "draft_blocked", "authoritative": False,
                "blockers": READINESS_BLOCKERS, "canonical_ledger_receipt_sha256": None,
                "latest_inventory_cutoff": None, "t_seen": None}
    require(type(value) is dict and type(value.get("schema_version")) is int and
            value == expected, "EXPOSURE_READINESS_INVALID")
    return value


def load_readiness(path):
    return validate_readiness(_read_json(path))


def semantic_exposure_sha256(value):
    validate_event(value)
    return digest({"exposure_class": value["exposure_class"],
                   "semantic_subject_sha256": _semantic_subject_sha256(value["semantic_subject_id"]),
                   "latest_affected_session": value["latest_affected_session"]})


def _read_json(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise ExposureError("EXPOSURE_RECORD_UNAVAILABLE") from None
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and
                0 < info.st_size <= MAX_JSON, "EXPOSURE_RECORD_INVALID")
        raw = b""
        while len(raw) < info.st_size:
            chunk = os.read(descriptor, info.st_size - len(raw))
            require(chunk, "EXPOSURE_RECORD_INVALID")
            raw += chunk
        return loads_strict(raw)
    except ExposureError:
        raise
    except OSError:
        raise ExposureError("EXPOSURE_RECORD_INVALID") from None
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _destination_state(path, payload):
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unavailable"
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                info.st_size != len(payload)):
            return "different"
        raw = b""
        while len(raw) < info.st_size:
            chunk = os.read(descriptor, info.st_size - len(raw))
            if not chunk:
                return "different"
            raw += chunk
        return "match" if secrets.compare_digest(raw, payload) else "different"
    except OSError:
        return "unavailable"
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass


def _fsync_parent(path, payload):
    directory = None
    try:
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        os.fsync(directory)
        os.close(directory)
        directory = None
    except OSError:
        raise ExposureWriteDurabilityUnknown(path, payload) from None
    finally:
        if directory is not None:
            try:
                os.close(directory)
            except OSError:
                pass


def _atomic_write(path, payload, replace=False):
    path = Path(path)
    require(type(payload) is bytes and payload, "EXPOSURE_WRITE_FAILED")
    state = _destination_state(path, payload)
    if state == "match":
        _fsync_parent(path, payload)
        return
    if not replace and state == "different":
        raise ExposureError("EXPOSURE_IMMUTABLE_CONFLICT")
    temporary = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = None
    effect_attempted = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            require(type(written) is int and written > 0, "EXPOSURE_WRITE_FAILED")
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
                    raise ExposureWriteDurabilityUnknown(path, payload) from None
                raise ExposureError("EXPOSURE_IMMUTABLE_CONFLICT") from None
            os.unlink(temporary)
        _fsync_parent(path, payload)
    except ExposureError:
        raise
    except OSError:
        state = _destination_state(path, payload)
        if effect_attempted:
            raise ExposureWriteDurabilityUnknown(path, payload, state) from None
        raise ExposureWriteFailed() from None
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


def _write_reconciled(path, payload, replace=False):
    try:
        _atomic_write(path, payload, replace=replace)
    except ExposureWriteDurabilityUnknown as error:
        require(error.destination == str(Path(path)) and
                error.intended_sha256 == hashlib.sha256(payload).hexdigest() and
                error.intended_bytes == payload,
                "EXPOSURE_WRITE_RECONCILIATION_INVALID")
        if _destination_state(path, payload) != "match":
            raise
        _atomic_write(path, payload, replace=replace)
    except ExposureWriteFailed:
        _atomic_write(path, payload, replace=replace)


@contextmanager
def _lock(root):
    path = root / "lock"; descriptor = None; locked = False
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_NOFOLLOW)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(),
                "EXPOSURE_LOCK_INVALID")
        fcntl.flock(descriptor, fcntl.LOCK_EX); locked = True
        yield
    except ExposureError:
        raise
    except OSError:
        raise ExposureError("EXPOSURE_LOCK_INVALID") from None
    finally:
        if descriptor is not None:
            if locked:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            try:
                os.close(descriptor)
            except OSError:
                pass


def validate_genesis(value):
    _strict(value, {"schema_version", "kind", "ledger_id", "created_at", "trust_class",
                    "authoritative"}, "EXPOSURE_GENESIS_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_exposure_ledger_genesis" and
            value["trust_class"] == "synthetic-local" and
            value["authoritative"] is False, "EXPOSURE_GENESIS_INVALID")
    _id(value["ledger_id"], "EXPOSURE_LEDGER_ID_INVALID"); _time(value["created_at"])
    return value


def _safe_uncreated_root(value):
    root = Path(value).absolute()
    require(not root.exists(), "EXPOSURE_PROVISION_INVALID")
    require(root.parent.is_dir() and not root.parent.is_symlink() and
            root.parent.stat().st_uid == os.getuid(), "EXPOSURE_PROVISION_INVALID")
    current = root.parent
    while True:
        require(current.exists() and current.is_dir() and not current.is_symlink(),
                "EXPOSURE_PROVISION_INVALID")
        if current == current.parent:
            break
        current = current.parent
    return root


class SyntheticExposureLedger:
    """Local structural ledger; never authoritative for production admission."""
    def __init__(self, root):
        self.root = Path(root).absolute()
        require(self.root.is_dir() and not self.root.is_symlink() and
                self.root.resolve() == self.root and self.root.stat().st_uid == os.getuid(),
                "EXPOSURE_ROOT_INVALID")
        require((self.root / "events").is_dir() and not (self.root / "events").is_symlink(),
                "EXPOSURE_ROOT_INVALID")
        self.genesis = validate_genesis(_read_json(self.root / "genesis.json"))
        self.genesis_sha256 = digest(self.genesis)
        with _lock(self.root):
            self._recover_locked()

    @classmethod
    def provision(cls, root):
        root = _safe_uncreated_root(root)
        os.mkdir(root, 0o700); os.mkdir(root / "events", 0o700)
        genesis = {"schema_version": 1, "kind": "factor_exposure_ledger_genesis",
                   "ledger_id": "exposure-" + secrets.token_hex(16),
                   "created_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
                   "trust_class": "synthetic-local", "authoritative": False}
        validate_genesis(genesis); genesis_sha256 = digest(genesis)
        _atomic_write(root / "genesis.json", canonical(genesis) + b"\n")
        _atomic_write(root / "head.json", canonical({"schema_version": 1,
                                                      "ledger_id": genesis["ledger_id"],
                                                      "ledger_genesis_sha256": genesis_sha256,
                                                      "sequence": 0, "last_event_sha256": None,
                                                      "t_seen": None}) + b"\n")
        _atomic_write(root / "lock", b"synthetic-lock\n")
        return cls(root)

    def _expected_head(self, records):
        t_seen = None
        for record in records:
            affected = record["event"]["latest_affected_session"]
            t_seen = max(t_seen, affected) if t_seen else affected
        return {"schema_version": 1, "ledger_id": self.genesis["ledger_id"],
                "ledger_genesis_sha256": self.genesis_sha256,
                "sequence": len(records),
                "last_event_sha256": records[-1]["event_sha256"] if records else None,
                "t_seen": t_seen}

    def _validate_head(self, value):
        _strict(value, {"schema_version", "ledger_id", "ledger_genesis_sha256",
                        "sequence", "last_event_sha256", "t_seen"},
                "EXPOSURE_HEAD_INVALID")
        require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
                value["ledger_id"] == self.genesis["ledger_id"] and
                value["ledger_genesis_sha256"] == self.genesis_sha256 and
                type(value["sequence"]) is int and value["sequence"] >= 0,
                "EXPOSURE_HEAD_INVALID")
        if value["last_event_sha256"] is not None:
            _sha(value["last_event_sha256"], "EXPOSURE_HEAD_INVALID")
        if value["t_seen"] is not None:
            _day(value["t_seen"], "EXPOSURE_HEAD_INVALID")
        require((value["sequence"] == 0) == (value["last_event_sha256"] is None) and
                (value["sequence"] == 0) == (value["t_seen"] is None),
                "EXPOSURE_HEAD_INVALID")
        return value

    def _scan_records(self):
        paths = []
        try:
            with os.scandir(self.root / "events") as entries:
                for entry in entries:
                    require(len(paths) < MAX_EVENTS, "EXPOSURE_EVENT_LIMIT")
                    paths.append(Path(entry.path))
        except ExposureError:
            raise
        except OSError:
            raise ExposureError("EXPOSURE_EVENTS_INVALID") from None
        paths.sort()
        prior = None; semantics = set(); evidence = set(); event_ids = set()
        records = []
        for sequence, path in enumerate(paths, 1):
            try:
                valid_path = path.is_file() and not path.is_symlink() and path.suffix == ".json"
            except OSError:
                raise ExposureError("EXPOSURE_EVENTS_INVALID") from None
            require(valid_path, "EXPOSURE_EVENT_FILE_INVALID")
            value = validate_event(_read_json(path)); identity = digest(value)
            require(value["ledger_genesis_sha256"] == self.genesis_sha256,
                    "EXPOSURE_GENESIS_MISMATCH")
            require(value["sequence"] == sequence and value["previous_event_sha256"] == prior and
                    path.name == f"{sequence:020d}-{identity}.json",
                    "EXPOSURE_CHAIN_INVALID")
            semantic = semantic_exposure_sha256(value)
            require(semantic not in semantics and value["evidence_sha256"] not in evidence and
                    value["event_id"] not in event_ids, "EXPOSURE_DUPLICATE_EVIDENCE")
            semantics.add(semantic); evidence.add(value["evidence_sha256"])
            event_ids.add(value["event_id"]); prior = identity
            records.append({"event": value, "event_sha256": identity})
        return records

    def _reconstruct(self):
        records = self._scan_records()
        expected = self._expected_head(records)
        actual = self._validate_head(_read_json(self.root / "head.json"))
        require(actual == expected, "EXPOSURE_HEAD_STALE")
        return records, actual

    def _recover_locked(self):
        records = self._scan_records()
        expected = self._expected_head(records)
        actual = self._validate_head(_read_json(self.root / "head.json"))
        if actual == expected:
            return records, actual
        require(len(records) == actual["sequence"] + 1 and
                actual == self._expected_head(records[:-1]), "EXPOSURE_HEAD_STALE")
        _write_reconciled(self.root / "head.json", canonical(expected) + b"\n", replace=True)
        return records, expected

    def append(self, record):
        with _lock(self.root):
            records, head = self._recover_locked()
            value = dict(record)
            value["schema_version"] = 1; value["kind"] = "factor_outcome_exposure"
            value["ledger_genesis_sha256"] = self.genesis_sha256
            _inventory, source_inventory_sha256 = _tracked_source_inventory()
            value["source_inventory_sha256"] = source_inventory_sha256
            value["sequence"] = head["sequence"] + 1
            value["previous_event_sha256"] = head["last_event_sha256"]
            validate_event(value)
            semantic = semantic_exposure_sha256(value)
            require(all(semantic_exposure_sha256(item["event"]) != semantic and
                        item["event"]["evidence_sha256"] != value["evidence_sha256"] and
                        item["event"]["event_id"] != value["event_id"]
                        for item in records), "EXPOSURE_DUPLICATE_EVIDENCE")
            identity = digest(value)
            _write_reconciled(self.root / "events" / f"{value['sequence']:020d}-{identity}.json",
                               canonical(value) + b"\n")
            t_seen = max(head["t_seen"], value["latest_affected_session"]) if head["t_seen"] else value["latest_affected_session"]
            _write_reconciled(self.root / "head.json", canonical({"schema_version": 1,
                          "ledger_id": self.genesis["ledger_id"],
                          "ledger_genesis_sha256": self.genesis_sha256,
                          "sequence": value["sequence"], "last_event_sha256": identity,
                          "t_seen": t_seen}) + b"\n", replace=True)
            return {"event": value, "event_sha256": identity, "t_seen": t_seen,
                    "authoritative": False}

    def status(self):
        with _lock(self.root):
            records, head = self._recover_locked()
        return {**head, "events": len(records), "authoritative": False,
                "status": "development-only-blocked"}


def _month_end_origins(sessions):
    result = []
    for index, session in enumerate(sessions):
        current = session[:7]
        if index + 1 < len(sessions) and sessions[index + 1][:7] != current:
            result.append(session)
    return result


def _plan_fresh_splits(*, sessions, t_seen, as_of_session, horizon_sessions=126,
                      purge_sessions=126, embargo_sessions=21,
                      validation_origins=24, protected_origins=36):
    require(type(sessions) is list and len(sessions) == len(set(sessions)) and sessions == sorted(sessions) and
            all(type(item) is str and DAY.fullmatch(item) for item in sessions),
            "EXPOSURE_CALENDAR_INVALID")
    for item in sessions:
        _day(item)
    _day(t_seen); _day(as_of_session)
    require(t_seen <= as_of_session and as_of_session in sessions and
            type(horizon_sessions) is int and horizon_sessions > 0 and
            type(purge_sessions) is int and purge_sessions >= horizon_sessions and
            type(embargo_sessions) is int and embargo_sessions >= 0 and
            type(validation_origins) is int and validation_origins > 0 and
            type(protected_origins) is int and protected_origins > 0,
            "EXPOSURE_SPLIT_POLICY_INVALID")
    as_of_pos = sessions.index(as_of_session)
    seen_pos = bisect_right(sessions, t_seen) - 1
    require(seen_pos >= 0, "EXPOSURE_T_SEEN_BEFORE_CALENDAR")
    calendar_sha256 = digest({"sessions": sessions})
    parameters = {"horizon_sessions": horizon_sessions,
                  "purge_sessions": purge_sessions,
                  "embargo_sessions": embargo_sessions,
                  "validation_origins": validation_origins,
                  "protected_origins": protected_origins,
                  "monthly_origin_rule": "last-session-of-month"}
    origins = _month_end_origins(sessions)
    origin_positions = {origin: sessions.index(origin) for origin in origins}
    earliest_validation = seen_pos + purge_sessions + 1
    eligible_validation = [origin for origin in origins
                           if origin_positions[origin] >= earliest_validation and
                           origin_positions[origin] + horizon_sessions <= as_of_pos]
    validation = eligible_validation[:validation_origins]
    validation_deficit = max(0, validation_origins - len(validation))
    if validation_deficit:
        return {"schema_version": 1, "status": "inconclusive_awaiting_fresh_data",
                "authoritative": False, "sealable": False,
                "t_seen": t_seen, "as_of_session": as_of_session,
                "calendar_sha256": calendar_sha256, "parameters": parameters,
                "validation_deficit": validation_deficit,
                "protected_deficit": protected_origins, "validation": validation,
                "protected": [], "split_identities": None}
    protected_start = (origin_positions[validation[-1]] + horizon_sessions +
                       purge_sessions + embargo_sessions + 1)
    eligible_protected = [origin for origin in origins
                          if origin_positions[origin] >= protected_start and
                          origin_positions[origin] + horizon_sessions <= as_of_pos]
    protected = eligible_protected[:protected_origins]
    protected_deficit = max(0, protected_origins - len(protected))
    status = "ready" if protected_deficit == 0 else "inconclusive_awaiting_fresh_data"
    identities = None
    if status == "ready":
        policy = {**parameters, "calendar_sha256": calendar_sha256,
                  "t_seen": t_seen, "as_of_session": as_of_session}
        identities = {
            "validation": digest({"role": "validation", "policy": policy,
                                  "ordered_origins": validation}),
            "protected": digest({"role": "protected", "policy": policy,
                                 "ordered_origins": protected}),
        }
    return {"schema_version": 1, "status": status,
            "authoritative": False, "sealable": False, "t_seen": t_seen,
            "as_of_session": as_of_session, "calendar_sha256": calendar_sha256,
            "parameters": parameters, "validation_deficit": 0,
            "protected_deficit": protected_deficit, "validation": validation,
            "protected": protected, "split_identities": identities}


def _validate_candidate_plan(candidate, head, evidence):
    _strict(candidate, {"schema_version", "status", "authoritative", "sealable", "t_seen",
                        "as_of_session", "calendar_sha256", "parameters",
                        "validation_deficit", "protected_deficit", "validation",
                        "protected", "split_identities"},
            "EXPOSURE_CANDIDATE_PLAN_SCHEMA")
    require(type(candidate["schema_version"]) is int and candidate["schema_version"] == 1 and
            candidate["status"] in {"ready", "inconclusive_awaiting_fresh_data"} and
            candidate["authoritative"] is False and candidate["sealable"] is False and
            candidate["t_seen"] == head["t_seen"] and
            candidate["calendar_sha256"] == evidence["calendar_identity_sha256"],
            "EXPOSURE_CANDIDATE_PLAN_INVALID")
    _day(candidate["t_seen"]); _day(candidate["as_of_session"])
    parameters = _strict(candidate["parameters"],
                         {"horizon_sessions", "purge_sessions", "embargo_sessions",
                          "validation_origins", "protected_origins", "monthly_origin_rule"},
                         "EXPOSURE_CANDIDATE_PARAMETERS")
    require(all(type(parameters[key]) is int and parameters[key] > 0
                for key in ("horizon_sessions", "purge_sessions", "validation_origins",
                            "protected_origins")) and
            parameters["purge_sessions"] >= parameters["horizon_sessions"] and
            type(parameters["embargo_sessions"]) is int and parameters["embargo_sessions"] >= 0 and
            parameters["monthly_origin_rule"] == "last-session-of-month",
            "EXPOSURE_CANDIDATE_PARAMETERS")
    require(type(candidate["validation_deficit"]) is int and
            0 <= candidate["validation_deficit"] <= parameters["validation_origins"] and
            type(candidate["protected_deficit"]) is int and
            0 <= candidate["protected_deficit"] <= parameters["protected_origins"] and
            type(candidate["validation"]) is list and type(candidate["protected"]) is list and
            len(candidate["validation"]) == parameters["validation_origins"] - candidate["validation_deficit"] and
            len(candidate["protected"]) == parameters["protected_origins"] - candidate["protected_deficit"] and
            candidate["validation"] == sorted(set(candidate["validation"])) and
            candidate["protected"] == sorted(set(candidate["protected"])),
            "EXPOSURE_CANDIDATE_MEMBERSHIP")
    for item in candidate["validation"] + candidate["protected"]:
        _day(item)
    if candidate["status"] == "ready":
        require(candidate["validation_deficit"] == candidate["protected_deficit"] == 0,
                "EXPOSURE_CANDIDATE_STATUS")
        identities = _strict(candidate["split_identities"], {"validation", "protected"},
                             "EXPOSURE_CANDIDATE_IDENTITIES")
        policy = {**parameters, "calendar_sha256": candidate["calendar_sha256"],
                  "t_seen": candidate["t_seen"], "as_of_session": candidate["as_of_session"]}
        expected = {
            "validation": digest({"role": "validation", "policy": policy,
                                  "ordered_origins": candidate["validation"]}),
            "protected": digest({"role": "protected", "policy": policy,
                                 "ordered_origins": candidate["protected"]}),
        }
        require(identities == expected, "EXPOSURE_CANDIDATE_IDENTITIES")
    else:
        require(candidate["split_identities"] is None and
                candidate["validation_deficit"] + candidate["protected_deficit"] > 0,
                "EXPOSURE_CANDIDATE_STATUS")
    return candidate


def _trusted_policy_hashes():
    try:
        authority_profile = trusted_authority_contract.validate_profile(
            trusted_authority_contract.load_profile())
        authority_profile_sha256 = trusted_authority_contract.digest(authority_profile)
        admission = admission_policy_contract.load_policy(ADMISSION_POLICY_PATH)
    except Exception:
        raise ExposureError("EXPOSURE_TRUST_PROFILE_INVALID") from None
    admission_sha256 = admission_policy_contract.digest(admission)
    require(admission_sha256 == ADMISSION_POLICY_SHA256 and
            authority_profile["status"] == "candidate-disabled" and
            authority_profile["real_operations_allowed"] is False,
            "EXPOSURE_TRUST_PROFILE_MISMATCH")
    return authority_profile_sha256, admission_sha256


def validate_fresh_split_readiness(value, *, sessions):
    _strict(value, {"schema_version", "kind", "status", "authoritative", "sealable",
                    "blockers", "ledger_binding", "identity_bindings", "candidate_plan",
                    "candidate_plan_sha256", "integration_identity_sha256"},
            "EXPOSURE_FRESH_READINESS_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_fresh_split_readiness" and
            value["status"] == "blocked_nonsealable" and
            value["authoritative"] is False and value["sealable"] is False,
            "EXPOSURE_FRESH_READINESS_INVALID")
    ledger = _strict(value["ledger_binding"],
                     {"ledger_id", "ledger_genesis_sha256", "sequence",
                      "last_event_sha256", "t_seen"}, "EXPOSURE_FRESH_READINESS_LEDGER")
    _id(ledger["ledger_id"]); _sha(ledger["ledger_genesis_sha256"])
    require(type(ledger["sequence"]) is int and ledger["sequence"] >= 0,
            "EXPOSURE_FRESH_READINESS_LEDGER")
    if ledger["last_event_sha256"] is not None:
        _sha(ledger["last_event_sha256"])
    if ledger["t_seen"] is not None:
        _day(ledger["t_seen"])
    require((ledger["sequence"] == 0) == (ledger["last_event_sha256"] is None) and
            (ledger["sequence"] == 0) == (ledger["t_seen"] is None),
            "EXPOSURE_FRESH_READINESS_LEDGER")
    identity_fields = {"authority_deployment_profile_sha256", "admission_policy_sha256",
                       "source_inventory_sha256", "dataset_snapshot_sha256",
                       "observation_set_sha256", "feature_snapshot_sha256",
                       "evaluation_population_sha256", "calendar_identity_sha256",
                       "universe_identity_sha256", "label_roster_sha256"}
    identities = _strict(value["identity_bindings"], identity_fields,
                         "EXPOSURE_FRESH_READINESS_IDENTITIES")
    for key, identity in identities.items():
        if key in IDENTITY_BLOCKERS and identity is None:
            continue
        _sha(identity, "EXPOSURE_FRESH_READINESS_IDENTITIES")
    require(identities["calendar_identity_sha256"] == digest({"sessions": sessions}),
            "EXPOSURE_CALENDAR_IDENTITY_MISMATCH")
    authority_sha, admission_sha = _trusted_policy_hashes()
    require(identities["authority_deployment_profile_sha256"] == authority_sha and
            identities["admission_policy_sha256"] == admission_sha,
            "EXPOSURE_TRUST_PROFILE_MISMATCH")
    expected_blockers = list(READINESS_BLOCKERS) + [blocker for key, blocker in
        IDENTITY_BLOCKERS.items() if identities[key] is None]
    require(value["blockers"] == expected_blockers, "EXPOSURE_FRESH_READINESS_BLOCKERS")
    candidate = value["candidate_plan"]
    require((candidate is None) == (ledger["t_seen"] is None),
            "EXPOSURE_FRESH_READINESS_CANDIDATE")
    if candidate is not None:
        _validate_candidate_plan(candidate, ledger, {
            "calendar_identity_sha256": identities["calendar_identity_sha256"]})
        parameters = candidate["parameters"]
        recomputed = _plan_fresh_splits(
            sessions=sessions, t_seen=ledger["t_seen"],
            as_of_session=candidate["as_of_session"],
            horizon_sessions=parameters["horizon_sessions"],
            purge_sessions=parameters["purge_sessions"],
            embargo_sessions=parameters["embargo_sessions"],
            validation_origins=parameters["validation_origins"],
            protected_origins=parameters["protected_origins"])
        require(candidate == recomputed, "EXPOSURE_CANDIDATE_RECOMPUTE_MISMATCH")
    candidate_sha = digest(candidate) if candidate is not None else None
    require(value["candidate_plan_sha256"] == candidate_sha,
            "EXPOSURE_FRESH_READINESS_CANDIDATE_SHA")
    expected_identity = digest({"ledger_binding": ledger, "identity_bindings": identities,
                                "blockers": expected_blockers,
                                "candidate_plan": candidate,
                                "candidate_plan_sha256": candidate_sha})
    require(value["integration_identity_sha256"] == expected_identity,
            "EXPOSURE_FRESH_READINESS_IDENTITY")
    return value


def plan_fresh_splits_from_ledger(*, ledger, readiness, sessions, as_of_session,
                                  calendar_identity_sha256, universe_identity_sha256,
                                  label_roster_sha256,
                                  dataset_snapshot_sha256=None, observation_set_sha256=None,
                                  feature_snapshot_sha256=None,
                                  evaluation_population_sha256=None,
                                  horizon_sessions=126, purge_sessions=126,
                                  embargo_sessions=21, validation_origins=24,
                                  protected_origins=36):
    require(isinstance(ledger, SyntheticExposureLedger), "EXPOSURE_LEDGER_REQUIRED")
    validate_readiness(readiness)
    for identity in (calendar_identity_sha256, universe_identity_sha256,
                     label_roster_sha256):
        _sha(identity, "EXPOSURE_ATTESTATION_IDENTITY_INVALID")
    for identity in (dataset_snapshot_sha256, observation_set_sha256,
                     feature_snapshot_sha256, evaluation_population_sha256):
        require(identity is None or type(identity) is str and SHA.fullmatch(identity),
                "EXPOSURE_ATTESTATION_IDENTITY_INVALID")
    calculated_calendar = digest({"sessions": sessions})
    require(calendar_identity_sha256 == calculated_calendar,
            "EXPOSURE_CALENDAR_IDENTITY_MISMATCH")
    authority_sha, admission_sha = _trusted_policy_hashes()
    _inventory, source_inventory_sha256 = _tracked_source_inventory()
    ledger_status = ledger.status(); t_seen = ledger_status["t_seen"]
    ledger_binding = {"ledger_id": ledger_status["ledger_id"],
                      "ledger_genesis_sha256": ledger_status["ledger_genesis_sha256"],
                      "sequence": ledger_status["sequence"],
                      "last_event_sha256": ledger_status["last_event_sha256"],
                      "t_seen": t_seen}
    identities = {"authority_deployment_profile_sha256": authority_sha,
                  "admission_policy_sha256": admission_sha,
                  "source_inventory_sha256": source_inventory_sha256,
                  "dataset_snapshot_sha256": dataset_snapshot_sha256,
                  "observation_set_sha256": observation_set_sha256,
                  "feature_snapshot_sha256": feature_snapshot_sha256,
                  "evaluation_population_sha256": evaluation_population_sha256,
                  "calendar_identity_sha256": calendar_identity_sha256,
                  "universe_identity_sha256": universe_identity_sha256,
                  "label_roster_sha256": label_roster_sha256}
    blockers = list(readiness["blockers"]) + [blocker for key, blocker in
        IDENTITY_BLOCKERS.items() if identities[key] is None]
    candidate = None
    if t_seen is not None:
        candidate = _plan_fresh_splits(
            sessions=sessions, t_seen=t_seen, as_of_session=as_of_session,
            horizon_sessions=horizon_sessions, purge_sessions=purge_sessions,
            embargo_sessions=embargo_sessions, validation_origins=validation_origins,
            protected_origins=protected_origins)
    candidate_sha = digest(candidate) if candidate is not None else None
    integration_identity = digest({"ledger_binding": ledger_binding,
                                   "identity_bindings": identities,
                                   "blockers": blockers, "candidate_plan": candidate,
                                   "candidate_plan_sha256": candidate_sha})
    return validate_fresh_split_readiness({
        "schema_version": 1, "kind": "factor_fresh_split_readiness",
        "status": "blocked_nonsealable", "authoritative": False, "sealable": False,
        "blockers": blockers, "ledger_binding": ledger_binding,
        "identity_bindings": identities, "candidate_plan": candidate,
        "candidate_plan_sha256": candidate_sha,
        "integration_identity_sha256": integration_identity}, sessions=sessions)
