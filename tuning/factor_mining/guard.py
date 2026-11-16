"""Deterministic factor-experiment admission, quarantine, and promotion guard.

This module controls evidence eligibility; it does not run factors or establish alpha.
Runtime state belongs in an ignored workspace-local ``runtime/`` directory.
"""
from contextlib import contextmanager
from datetime import date
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
OPERATORS = {"gt", "ge", "lt", "le"}
MODES = {"confirmatory", "exploratory", "remediation"}
ROLES = {"development", "validation", "protected"}
RESULTS = {"succeeded", "failed", "invalid"}
MAX_PROTOCOL_BYTES = 1024 * 1024


class GuardError(ValueError):
    """A stable, sanitized deterministic guard rejection."""


def require(condition, code):
    if not condition:
        raise GuardError(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                          allow_nan=False).encode()
    except (TypeError, ValueError):
        raise GuardError("FACTOR_JSON_INVALID") from None


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "FACTOR_JSON_DUPLICATE_KEY")
        result[key] = value
    return result


def _invalid_constant(value):
    raise GuardError("FACTOR_JSON_NONFINITE")


def loads_strict(raw):
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except GuardError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise GuardError("FACTOR_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _name(value, code="FACTOR_ID_INVALID"):
    require(isinstance(value, str) and NAME.fullmatch(value) and value != "replace-me", code)
    return value


def _sha(value, code="FACTOR_SHA_INVALID", *, optional=False):
    if optional and value is None:
        return None
    require(isinstance(value, str) and SHA256.fullmatch(value) and
            value not in {character * 64 for character in "0123"}, code)
    return value


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _strict(value, keys, code):
    require(isinstance(value, dict) and set(value) == set(keys), code)
    return value


def _criterion(value, code):
    _strict(value, {"id", "metric", "operator", "threshold", "period"}, code)
    _name(value["id"], code)
    _name(value["metric"], code)
    require(isinstance(value["operator"], str) and value["operator"] in OPERATORS and
            _finite(value["threshold"]), code)
    _name(value["period"], code)


def validate_protocol(protocol):
    """Validate a frozen protocol without inspecting outcomes."""
    keys = {
        "schema_version", "experiment_id", "version", "mode", "parent_protocol_sha256",
        "hypothesis", "economic_rationale", "data", "factors", "model", "execution",
        "evaluation", "multiplicity", "budget", "promotion_gate", "stopping_rule",
        "overfit_triggers",
    }
    _strict(protocol, keys, "FACTOR_PROTOCOL_SCHEMA")
    require(protocol["schema_version"] == 1, "FACTOR_PROTOCOL_VERSION")
    _name(protocol["experiment_id"], "FACTOR_EXPERIMENT_ID_INVALID")
    require(type(protocol["version"]) is int and protocol["version"] > 0, "FACTOR_PROTOCOL_VERSION")
    require(isinstance(protocol["mode"], str) and protocol["mode"] in MODES,
            "FACTOR_MODE_INVALID")
    _sha(protocol["parent_protocol_sha256"], "FACTOR_PARENT_INVALID", optional=True)
    require((protocol["mode"] == "remediation") == (protocol["parent_protocol_sha256"] is not None),
            "FACTOR_PARENT_REQUIRED")
    for field in ("hypothesis", "economic_rationale", "stopping_rule"):
        require(isinstance(protocol[field], str) and 1 <= len(protocol[field]) <= 4000,
                "FACTOR_PROTOCOL_TEXT_INVALID")

    data = _strict(protocol["data"], {"dataset_id", "snapshot_sha256", "availability_policy", "splits"},
                   "FACTOR_DATA_SCHEMA")
    _name(data["dataset_id"], "FACTOR_DATASET_ID_INVALID")
    _sha(data["snapshot_sha256"], "FACTOR_DATA_SHA_INVALID")
    require(isinstance(data["availability_policy"], str) and data["availability_policy"].strip(),
            "FACTOR_AVAILABILITY_POLICY_REQUIRED")
    require(isinstance(data["splits"], list) and 3 <= len(data["splits"]) <= 32,
            "FACTOR_SPLITS_INVALID")
    split_names = set()
    split_fingerprints = set()
    split_by_role = {}
    protected = 0
    for split in data["splits"]:
        _strict(split, {"name", "role", "start", "end", "fingerprint_sha256"}, "FACTOR_SPLIT_SCHEMA")
        _name(split["name"], "FACTOR_SPLIT_NAME_INVALID")
        require(split["name"] not in split_names and isinstance(split["role"], str) and split["role"] in ROLES,
                "FACTOR_SPLIT_INVALID")
        try:
            start = date.fromisoformat(split["start"])
            end = date.fromisoformat(split["end"])
        except (TypeError, ValueError):
            raise GuardError("FACTOR_SPLIT_RANGE_INVALID") from None
        require(split["start"] == start.isoformat() and split["end"] == end.isoformat() and start < end,
                "FACTOR_SPLIT_RANGE_INVALID")
        _sha(split["fingerprint_sha256"], "FACTOR_SPLIT_SHA_INVALID")
        require(split["fingerprint_sha256"] not in split_fingerprints, "FACTOR_SPLIT_FINGERPRINT_REUSED")
        split_names.add(split["name"])
        split_fingerprints.add(split["fingerprint_sha256"])
        require(split["role"] not in split_by_role, "FACTOR_SPLIT_ROLES_INVALID")
        split_by_role[split["role"]] = split
        protected += split["role"] == "protected"
    require(protected == 1 and set(split_by_role) == ROLES, "FACTOR_SPLIT_ROLES_INVALID")
    require(split_by_role["development"]["end"] <= split_by_role["validation"]["start"] and
            split_by_role["validation"]["end"] <= split_by_role["protected"]["start"],
            "FACTOR_SPLIT_OVERLAP")

    require(isinstance(protocol["factors"], list) and 1 <= len(protocol["factors"]) <= 64,
            "FACTOR_ROSTER_INVALID")
    factor_ids = set()
    for factor in protocol["factors"]:
        _strict(factor, {"id", "family", "transformation", "max_degrees_of_freedom"},
                "FACTOR_FACTOR_SCHEMA")
        _name(factor["id"])
        _name(factor["family"], "FACTOR_FAMILY_INVALID")
        require(factor["id"] not in factor_ids and isinstance(factor["transformation"], str) and
                factor["transformation"].strip() and type(factor["max_degrees_of_freedom"]) is int and
                1 <= factor["max_degrees_of_freedom"] <= 1000, "FACTOR_FACTOR_INVALID")
        factor_ids.add(factor["id"])

    model = _strict(protocol["model"], {"type", "hyperparameters"}, "FACTOR_MODEL_SCHEMA")
    _name(model["type"], "FACTOR_MODEL_TYPE_INVALID")
    require(isinstance(model["hyperparameters"], dict) and len(model["hyperparameters"]) <= 64,
            "FACTOR_MODEL_HYPERPARAMETERS_INVALID")
    execution = _strict(protocol["execution"],
                        {"signal_lag_sessions", "rebalance", "cost_bps", "cash_interest"},
                        "FACTOR_EXECUTION_SCHEMA")
    require(type(execution["signal_lag_sessions"]) is int and execution["signal_lag_sessions"] >= 1 and
            isinstance(execution["rebalance"], str) and execution["rebalance"].strip() and
            _finite(execution["cost_bps"]) and execution["cost_bps"] >= 0 and
            isinstance(execution["cash_interest"], str) and execution["cash_interest"].strip(),
            "FACTOR_EXECUTION_INVALID")
    evaluation = _strict(protocol["evaluation"],
                         {"target", "horizon_sessions", "purge_sessions", "embargo_sessions", "baseline"},
                         "FACTOR_EVALUATION_SCHEMA")
    _name(evaluation["target"], "FACTOR_TARGET_INVALID")
    _name(evaluation["baseline"], "FACTOR_BASELINE_INVALID")
    for key in ("horizon_sessions", "purge_sessions", "embargo_sessions"):
        require(type(evaluation[key]) is int and evaluation[key] >= (1 if key == "horizon_sessions" else 0),
                "FACTOR_EVALUATION_WINDOW_INVALID")

    multiplicity = _strict(protocol["multiplicity"], {"family_id", "method", "alpha", "max_variants"},
                           "FACTOR_MULTIPLICITY_SCHEMA")
    _name(multiplicity["family_id"], "FACTOR_MULTIPLICITY_FAMILY_INVALID")
    _name(multiplicity["method"], "FACTOR_MULTIPLICITY_METHOD_INVALID")
    require(_finite(multiplicity["alpha"]) and 0 < multiplicity["alpha"] < 1 and
            type(multiplicity["max_variants"]) is int and multiplicity["max_variants"] > 0,
            "FACTOR_MULTIPLICITY_INVALID")

    budget = _strict(protocol["budget"], {"max_attempts", "max_variants", "max_protected_uses"},
                     "FACTOR_BUDGET_SCHEMA")
    require(all(type(budget[k]) is int and budget[k] > 0 for k in budget), "FACTOR_BUDGET_INVALID")
    require(budget["max_variants"] <= multiplicity["max_variants"] and
            budget["max_protected_uses"] == 1, "FACTOR_BUDGET_UNSAFE")

    require(isinstance(protocol["promotion_gate"], list) and 1 <= len(protocol["promotion_gate"]) <= 64,
            "FACTOR_PROMOTION_GATE_REQUIRED")
    gate_ids = set()
    for criterion in protocol["promotion_gate"]:
        _criterion(criterion, "FACTOR_PROMOTION_GATE_INVALID")
        require(criterion["id"] not in gate_ids, "FACTOR_PROMOTION_GATE_DUPLICATE")
        gate_ids.add(criterion["id"])

    require(isinstance(protocol["overfit_triggers"], list) and protocol["overfit_triggers"],
            "FACTOR_OVERFIT_TRIGGERS_REQUIRED")
    trigger_ids = set()
    for trigger in protocol["overfit_triggers"]:
        _strict(trigger, {"id", "metric", "operator", "threshold", "action"},
                "FACTOR_OVERFIT_TRIGGER_INVALID")
        _name(trigger["id"], "FACTOR_OVERFIT_TRIGGER_INVALID")
        _name(trigger["metric"], "FACTOR_OVERFIT_TRIGGER_INVALID")
        require(trigger["id"] not in trigger_ids and isinstance(trigger["operator"], str) and
                trigger["operator"] in OPERATORS and _finite(trigger["threshold"]) and
                trigger["action"] == "quarantine",
                "FACTOR_OVERFIT_TRIGGER_INVALID")
        trigger_ids.add(trigger["id"])
    return protocol


def _safe_root(path, *, create=True):
    root = Path(path).absolute()
    parent = root.parent
    require(parent.is_dir() and parent.resolve() == parent, "FACTOR_STATE_PARENT_INVALID")
    if create and not root.exists():
        os.mkdir(root, 0o700)
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
            "FACTOR_STATE_ROOT_INVALID")
    return root


def _root_fd(root):
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _subdir_fd(root_fd, name, *, create=True):
    require(NAME.fullmatch(name), "FACTOR_STATE_SUBDIR_INVALID")
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=root_fd)
        except FileExistsError:
            pass
    try:
        return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd)
    except FileNotFoundError:
        raise GuardError("FACTOR_STATE_SUBDIR_MISSING") from None
    except OSError:
        raise GuardError("FACTOR_STATE_SUBDIR_INVALID") from None


def _read_regular_at(directory_fd, name, maximum, missing_code):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    except OSError:
        raise GuardError(missing_code) from None
    try:
        details = os.fstat(fd)
        require(stat.S_ISREG(details.st_mode) and 0 < details.st_size <= maximum, missing_code)
        chunks = []
        remaining = details.st_size
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            require(chunk, missing_code)
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_all(fd, payload):
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        require(written > 0, "FACTOR_STATE_WRITE_FAILED")
        view = view[written:]


def _publish_at(directory_fd, name, payload, exists_code):
    token = hashlib.sha256(payload).hexdigest()[:16]
    temporary = None
    fd = None
    for suffix in range(16):
        candidate = f".tmp-{os.getpid()}-{token}-{suffix}"
        try:
            fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory_fd)
            temporary = candidate
            break
        except FileExistsError:
            continue
    require(fd is not None and temporary is not None, "FACTOR_TEMPFILE_EXHAUSTED")
    try:
        _write_all(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.link(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
                follow_symlinks=False)
    except FileExistsError:
        raise GuardError(exists_code) from None
    finally:
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
    os.fsync(directory_fd)


@contextmanager
def _lock(root):
    root_fd = _root_fd(root)
    try:
        fd = os.open("ledger.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600,
                     dir_fd=root_fd)
        require(stat.S_ISREG(os.fstat(fd).st_mode), "FACTOR_LOCK_INVALID")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    finally:
        os.close(root_fd)


def _events(root):
    root_fd = _root_fd(root)
    try:
        try:
            events_fd = _subdir_fd(root_fd, "events", create=False)
        except GuardError as error:
            if str(error) == "FACTOR_STATE_SUBDIR_MISSING":
                return []
            raise
        try:
            names = sorted(name for name in os.listdir(events_fd)
                           if re.fullmatch(r"[0-9]{20}\.json", name))
            events = []
            previous = "0" * 64
            for sequence, name in enumerate(names, 1):
                require(name == f"{sequence:020d}.json", "FACTOR_LEDGER_SEQUENCE_INVALID")
                raw = _read_regular_at(events_fd, name, MAX_PROTOCOL_BYTES,
                                       "FACTOR_LEDGER_RECORD_INVALID")
                event = loads_strict(raw)
                require(isinstance(event, dict) and set(event) ==
                        {"sequence", "event", "protocol_sha256", "data", "previous_digest", "event_digest"},
                        "FACTOR_LEDGER_RECORD_INVALID")
                observed = event["event_digest"]
                unsigned = {key: event[key] for key in event if key != "event_digest"}
                require(event["sequence"] == sequence and event["previous_digest"] == previous and
                        observed == digest(unsigned), "FACTOR_LEDGER_CHAIN_INVALID")
                _name(event["event"], "FACTOR_EVENT_INVALID")
                _sha(event["protocol_sha256"], "FACTOR_EVENT_PROTOCOL_INVALID")
                require(isinstance(event["data"], dict), "FACTOR_EVENT_DATA_INVALID")
                events.append(event)
                previous = observed
            return events
        finally:
            os.close(events_fd)
    finally:
        os.close(root_fd)


def _append(root, event, protocol_sha256, data):
    events = _events(root)
    unsigned = {
        "sequence": len(events) + 1,
        "event": _name(event, "FACTOR_EVENT_INVALID"),
        "protocol_sha256": _sha(protocol_sha256, "FACTOR_EVENT_PROTOCOL_INVALID"),
        "data": data,
        "previous_digest": events[-1]["event_digest"] if events else "0" * 64,
    }
    record = dict(unsigned, event_digest=digest(unsigned))
    root_fd = _root_fd(root)
    try:
        events_fd = _subdir_fd(root_fd, "events")
        try:
            _publish_at(events_fd, f"{unsigned['sequence']:020d}.json", canonical(record),
                        "FACTOR_EVENT_EXISTS")
        finally:
            os.close(events_fd)
    finally:
        os.close(root_fd)
    return record


def _protocol_records(root):
    root_fd = _root_fd(root)
    try:
        try:
            protocols_fd = _subdir_fd(root_fd, "protocols", create=False)
        except GuardError as error:
            if str(error) == "FACTOR_STATE_SUBDIR_MISSING":
                return []
            raise
        try:
            records = []
            for name in sorted(os.listdir(protocols_fd)):
                if name.startswith(".tmp-"):
                    continue
                require(re.fullmatch(r"[a-f0-9]{64}\.json", name), "FACTOR_PROTOCOL_REGISTRY_INVALID")
                raw = _read_regular_at(protocols_fd, name, MAX_PROTOCOL_BYTES,
                                       "FACTOR_PROTOCOL_REGISTRY_INVALID")
                require(hashlib.sha256(raw).hexdigest() == name[:-5], "FACTOR_PROTOCOL_CHANGED")
                records.append((name[:-5], validate_protocol(loads_strict(raw))))
            return records
        finally:
            os.close(protocols_fd)
    finally:
        os.close(root_fd)


def _publish_protocol(root, protocol_sha256, payload):
    root_fd = _root_fd(root)
    try:
        protocols_fd = _subdir_fd(root_fd, "protocols")
        try:
            _publish_at(protocols_fd, protocol_sha256 + ".json", payload, "FACTOR_PROTOCOL_EXISTS")
        finally:
            os.close(protocols_fd)
    finally:
        os.close(root_fd)


def load_protocol(state_directory, protocol_sha256):
    root = _safe_root(state_directory, create=False)
    _sha(protocol_sha256, "FACTOR_PROTOCOL_REF_INVALID")
    root_fd = _root_fd(root)
    try:
        protocols_fd = _subdir_fd(root_fd, "protocols", create=False)
        try:
            raw = _read_regular_at(protocols_fd, protocol_sha256 + ".json", MAX_PROTOCOL_BYTES,
                                   "FACTOR_PROTOCOL_NOT_FOUND")
        finally:
            os.close(protocols_fd)
    finally:
        os.close(root_fd)
    require(hashlib.sha256(raw).hexdigest() == protocol_sha256, "FACTOR_PROTOCOL_CHANGED")
    return validate_protocol(loads_strict(raw))


def _protocol_events(events, protocol_sha256):
    return [event for event in events if event["protocol_sha256"] == protocol_sha256]


def lifecycle(events, protocol_sha256):
    state = None
    if any(event["event"] == "remediation_registered" and
           event["data"].get("child_protocol_sha256") == protocol_sha256 for event in events):
        state = "sealed"
    for event in _protocol_events(events, protocol_sha256):
        name = event["event"]
        if name == "protocol_sealed":
            require(state is None, "FACTOR_LIFECYCLE_INVALID")
            state = "sealed"
        elif name == "testing_completed":
            require(state == "sealed", "FACTOR_LIFECYCLE_INVALID")
            state = event["data"]["state"]
        elif name == "protocol_quarantined":
            require(state in {"sealed", "tested", "fresh_validation", "promoted"},
                    "FACTOR_LIFECYCLE_INVALID")
            state = "quarantined"
        elif name == "remediation_registered":
            require(state == "quarantined", "FACTOR_LIFECYCLE_INVALID")
            state = "remediation_registered"
        elif name == "protocol_promoted":
            require(state in {"tested", "fresh_validation"}, "FACTOR_LIFECYCLE_INVALID")
            state = "promoted"
        elif name == "protocol_rejected":
            require(state in {"tested", "fresh_validation", "quarantined", "remediation_registered"},
                    "FACTOR_LIFECYCLE_INVALID")
            state = "rejected"
    return state


def _compare(operator, observed, threshold):
    return {"gt": observed > threshold, "ge": observed >= threshold,
            "lt": observed < threshold, "le": observed <= threshold}[operator]


def _read_protocol_source(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        raise GuardError("FACTOR_PROTOCOL_SOURCE_INVALID") from None
    try:
        details = os.fstat(fd)
        require(stat.S_ISREG(details.st_mode) and 0 < details.st_size <= MAX_PROTOCOL_BYTES,
                "FACTOR_PROTOCOL_SOURCE_INVALID")
        raw = b""
        while len(raw) < details.st_size:
            chunk = os.read(fd, min(65536, details.st_size - len(raw)))
            require(chunk, "FACTOR_PROTOCOL_SOURCE_INVALID")
            raw += chunk
        return raw
    finally:
        os.close(fd)


def _protected_fingerprints(protocol):
    return {split["fingerprint_sha256"] for split in protocol["data"]["splits"]
            if split["role"] == "protected"}


def _validate_remediation(root, events, protocol):
    parent_sha = protocol["parent_protocol_sha256"]
    require(lifecycle(events, parent_sha) == "quarantined", "FACTOR_PARENT_NOT_QUARANTINED")
    child_protected = _protected_fingerprints(protocol)
    seen = set()
    cursor = parent_sha
    while cursor is not None:
        require(cursor not in seen, "FACTOR_REMEDIATION_LINEAGE_CYCLE")
        seen.add(cursor)
        ancestor = load_protocol(root, cursor)
        require(_protected_fingerprints(ancestor).isdisjoint(child_protected),
                "FACTOR_REMEDIATION_HOLDOUT_REUSED")
        cursor = ancestor["parent_protocol_sha256"]


def seal(protocol_path, state_directory):
    protocol = validate_protocol(loads_strict(_read_protocol_source(protocol_path)))
    payload = canonical(protocol)
    protocol_sha256 = hashlib.sha256(payload).hexdigest()
    root = _safe_root(state_directory)
    with _lock(root):
        events = _events(root)
        existing = None
        for observed_sha, prior in _protocol_records(root):
            same_experiment = prior["experiment_id"] == protocol["experiment_id"]
            same_family = prior["multiplicity"]["family_id"] == protocol["multiplicity"]["family_id"]
            if same_experiment:
                require(prior["multiplicity"] == protocol["multiplicity"],
                        "FACTOR_FAMILY_CONTRACT_CHANGED")
            if same_family:
                require(prior["multiplicity"] == protocol["multiplicity"],
                        "FACTOR_FAMILY_CONTRACT_CHANGED")
            if (same_experiment and prior["version"] == protocol["version"]):
                require(observed_sha == protocol_sha256, "FACTOR_PROTOCOL_VERSION_CONFLICT")
                existing = observed_sha
                break
        state = lifecycle(events, protocol_sha256)
        if protocol["mode"] == "remediation" and state is None:
            _validate_remediation(root, events, protocol)
        if existing is None:
            _publish_protocol(root, protocol_sha256, payload)
        if state is None:
            if protocol["mode"] == "remediation":
                _append(root, "remediation_registered", protocol["parent_protocol_sha256"],
                        {"child_protocol_sha256": protocol_sha256})
            else:
                _append(root, "protocol_sealed", protocol_sha256,
                        {"experiment_id": protocol["experiment_id"], "version": protocol["version"],
                         "mode": protocol["mode"], "parent_protocol_sha256": None})
            state = "sealed"
        require(state == "sealed", "FACTOR_PROTOCOL_ALREADY_ADVANCED")
    return {"protocol_sha256": protocol_sha256, "state": state}


def _variant_configuration(protocol, configuration, split_names):
    _strict(configuration, {"factor_ids"}, "FACTOR_VARIANT_CONFIG_INVALID")
    factor_ids = configuration["factor_ids"]
    require(isinstance(factor_ids, list) and factor_ids and
            all(isinstance(factor_id, str) for factor_id in factor_ids) and
            len(factor_ids) == len(set(factor_ids)), "FACTOR_VARIANT_CONFIG_INVALID")
    declared = {factor["id"]: factor for factor in protocol["factors"]}
    require(set(factor_ids) <= set(declared), "FACTOR_VARIANT_FACTOR_UNDECLARED")
    semantic_factors = [{key: factor[key] for key in
                         ("family", "transformation", "max_degrees_of_freedom")}
                        for factor in (declared[factor_id] for factor_id in factor_ids)]
    semantic_factors.sort(key=lambda factor: canonical(factor))
    splits = {split["name"]: split for split in protocol["data"]["splits"]}
    semantic = {
        "factors": semantic_factors,
        "model": protocol["model"],
        "execution": protocol["execution"],
        "evaluation": protocol["evaluation"],
        "data_snapshot_sha256": protocol["data"]["snapshot_sha256"],
        "split_fingerprints": sorted(splits[name]["fingerprint_sha256"] for name in split_names),
    }
    return {"factor_ids": sorted(factor_ids), "semantic_sha256": digest(semantic)}


def begin_attempt(state_directory, protocol_sha256, variant_id, configuration, split_names):
    _name(variant_id, "FACTOR_VARIANT_ID_INVALID")
    require(isinstance(split_names, list) and split_names and len(split_names) == len(set(split_names)),
            "FACTOR_ATTEMPT_SPLITS_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        protocol = load_protocol(root, protocol_sha256)
        events = _events(root)
        require(lifecycle(events, protocol_sha256) == "sealed", "FACTOR_PROTOCOL_NOT_OPEN")
        own = _protocol_events(events, protocol_sha256)
        attempts = [event for event in own if event["event"] == "attempt_started"]
        all_attempts = [event for event in events if event["event"] == "attempt_started"]
        family_id = protocol["multiplicity"]["family_id"]
        family_attempts = [event for event in all_attempts if event["data"]["family_id"] == family_id]
        require(len(attempts) < protocol["budget"]["max_attempts"], "FACTOR_ATTEMPT_BUDGET_EXHAUSTED")
        splits = {split["name"]: split for split in protocol["data"]["splits"]}
        require(set(split_names) <= set(splits), "FACTOR_ATTEMPT_SPLIT_UNKNOWN")
        configuration = _variant_configuration(protocol, configuration, split_names)
        config_sha = configuration["semantic_sha256"]
        require(all(event["data"]["variant_id"] != variant_id for event in attempts), "FACTOR_VARIANT_EXISTS")
        require(all(event["data"]["configuration_sha256"] != config_sha for event in family_attempts),
                "FACTOR_HIDDEN_RETRY_REJECTED")
        require(len(family_attempts) < protocol["multiplicity"]["max_variants"] and
                len(attempts) < protocol["budget"]["max_variants"],
                "FACTOR_VARIANT_BUDGET_EXHAUSTED")
        selected_protected = [splits[name] for name in split_names if splits[name]["role"] == "protected"]
        uses_protected = bool(selected_protected)
        protected_fingerprint = selected_protected[0]["fingerprint_sha256"] if selected_protected else None
        prior_protected = {event["data"]["protected_fingerprint_sha256"] for event in all_attempts
                           if event["data"]["protected_fingerprint_sha256"] is not None}
        require(not uses_protected or protected_fingerprint not in prior_protected,
                "FACTOR_PROTECTED_HOLDOUT_EXHAUSTED")
        record = _append(root, "attempt_started", protocol_sha256,
                         {"variant_id": variant_id, "configuration_sha256": config_sha,
                          "factor_ids": configuration["factor_ids"],
                          "split_names": split_names, "uses_protected": uses_protected,
                          "protected_fingerprint_sha256": protected_fingerprint,
                          "family_id": family_id})
    return record


def finish_attempt(state_directory, protocol_sha256, variant_id, result, evidence_sha256):
    _name(variant_id, "FACTOR_VARIANT_ID_INVALID")
    require(isinstance(result, str) and result in RESULTS, "FACTOR_ATTEMPT_RESULT_INVALID")
    _sha(evidence_sha256, "FACTOR_EVIDENCE_SHA_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        load_protocol(root, protocol_sha256)
        events = _events(root)
        own = _protocol_events(events, protocol_sha256)
        starts = [e for e in own if e["event"] == "attempt_started" and e["data"]["variant_id"] == variant_id]
        finishes = [e for e in own if e["event"] == "attempt_finished" and e["data"]["variant_id"] == variant_id]
        require(len(starts) == 1 and not finishes, "FACTOR_ATTEMPT_NOT_FINISHABLE")
        return _append(root, "attempt_finished", protocol_sha256,
                       {"variant_id": variant_id, "result": result, "evidence_sha256": evidence_sha256})


def complete_testing(state_directory, protocol_sha256, evidence_sha256):
    _sha(evidence_sha256, "FACTOR_EVIDENCE_SHA_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        protocol = load_protocol(root, protocol_sha256)
        events = _events(root)
        require(lifecycle(events, protocol_sha256) == "sealed", "FACTOR_TESTING_NOT_COMPLETABLE")
        own = _protocol_events(events, protocol_sha256)
        starts = {event["data"]["variant_id"]: event for event in own
                  if event["event"] == "attempt_started"}
        finishes = {event["data"]["variant_id"]: event for event in own
                    if event["event"] == "attempt_finished"}
        require(starts and set(starts) == set(finishes), "FACTOR_ATTEMPTS_INCOMPLETE")
        successful_protected = [finish for variant_id, finish in finishes.items()
                                if finish["data"]["result"] == "succeeded" and
                                starts[variant_id]["data"]["uses_protected"]]
        require(successful_protected, "FACTOR_PROTECTED_SUCCESS_REQUIRED")
        require(any(finish["data"]["evidence_sha256"] == evidence_sha256
                    for finish in successful_protected), "FACTOR_COMPLETION_EVIDENCE_UNBOUND")
        state = "fresh_validation" if protocol["mode"] == "remediation" else "tested"
        _append(root, "testing_completed", protocol_sha256,
                {"state": state, "evidence_sha256": evidence_sha256})
    return {"protocol_sha256": protocol_sha256, "state": state}


def quarantine(state_directory, protocol_sha256, observations, evidence_sha256):
    require(isinstance(observations, dict) and observations, "FACTOR_OVERFIT_OBSERVATIONS_REQUIRED")
    _sha(evidence_sha256, "FACTOR_EVIDENCE_SHA_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        protocol = load_protocol(root, protocol_sha256)
        events = _events(root)
        state = lifecycle(events, protocol_sha256)
        require(state in {"sealed", "tested", "fresh_validation", "promoted"},
                "FACTOR_PROTOCOL_NOT_QUARANTINABLE")
        if state == "sealed":
            own = _protocol_events(events, protocol_sha256)
            require(any(event["event"] == "attempt_finished" and
                        event["data"]["evidence_sha256"] == evidence_sha256 for event in own),
                    "FACTOR_QUARANTINE_EVIDENCE_UNBOUND")
        triggers = {item["id"]: item for item in protocol["overfit_triggers"]}
        fired = []
        for trigger_id, observed in observations.items():
            require(trigger_id in triggers and _finite(observed), "FACTOR_OVERFIT_OBSERVATION_INVALID")
            trigger = triggers[trigger_id]
            if _compare(trigger["operator"], observed, trigger["threshold"]):
                fired.append({"id": trigger_id, "observed": observed})
        require(fired, "FACTOR_OVERFIT_TRIGGER_NOT_MET")
        _append(root, "protocol_quarantined", protocol_sha256,
                {"reason": "declared_overfit_trigger", "triggers": fired,
                 "evidence_sha256": evidence_sha256})
    return {"protocol_sha256": protocol_sha256, "state": "quarantined", "triggers": fired}


def promote(state_directory, protocol_sha256, gate_report, independent_check_sha256):
    _sha(independent_check_sha256, "FACTOR_INDEPENDENT_CHECK_INVALID")
    require(isinstance(gate_report, dict), "FACTOR_GATE_REPORT_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        protocol = load_protocol(root, protocol_sha256)
        events = _events(root)
        require(lifecycle(events, protocol_sha256) in {"tested", "fresh_validation"},
                "FACTOR_PROTOCOL_NOT_PROMOTABLE")
        require(set(gate_report) == {item["id"] for item in protocol["promotion_gate"]},
                "FACTOR_GATE_REPORT_INCOMPLETE")
        checked = {}
        for criterion in protocol["promotion_gate"]:
            observed = gate_report[criterion["id"]]
            require(_finite(observed) and _compare(criterion["operator"], observed, criterion["threshold"]),
                    "FACTOR_PROMOTION_GATE_FAILED")
            checked[criterion["id"]] = observed
        _append(root, "protocol_promoted", protocol_sha256,
                {"gate_report": checked, "independent_check_sha256": independent_check_sha256})
    return {"protocol_sha256": protocol_sha256, "state": "promoted"}


def reject(state_directory, protocol_sha256, evidence_sha256, reason):
    _sha(evidence_sha256, "FACTOR_EVIDENCE_SHA_INVALID")
    _name(reason, "FACTOR_REJECTION_REASON_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        load_protocol(root, protocol_sha256)
        events = _events(root)
        require(lifecycle(events, protocol_sha256) in
                {"tested", "fresh_validation", "quarantined", "remediation_registered"},
                "FACTOR_PROTOCOL_NOT_REJECTABLE")
        _append(root, "protocol_rejected", protocol_sha256,
                {"reason": reason, "evidence_sha256": evidence_sha256})
    return {"protocol_sha256": protocol_sha256, "state": "rejected"}


def authorize_use(state_directory, protocol_sha256s, purpose, evidence_sha256):
    require(isinstance(purpose, str) and purpose in
            {"combination_selection", "ev_publication", "kelly_publication"},
            "FACTOR_USE_PURPOSE_INVALID")
    _sha(evidence_sha256, "FACTOR_EVIDENCE_SHA_INVALID")
    require(isinstance(protocol_sha256s, list) and protocol_sha256s and
            len(protocol_sha256s) == len(set(protocol_sha256s)), "FACTOR_USE_PROTOCOLS_INVALID")
    root = _safe_root(state_directory)
    with _lock(root):
        events = _events(root)
        ordered = sorted(protocol_sha256s)
        for protocol_sha256 in ordered:
            load_protocol(root, protocol_sha256)
            require(lifecycle(events, protocol_sha256) == "promoted", "FACTOR_EVIDENCE_NOT_ELIGIBLE")
        authorization = {"purpose": purpose, "protocol_sha256s": ordered,
                         "evidence_sha256": evidence_sha256}
        authorization["authorization_sha256"] = digest(authorization)
        _append(root, "evidence_use_authorized", ordered[0], authorization)
    return authorization


def inspect_state(state_directory, protocol_sha256):
    root = _safe_root(state_directory, create=False)
    protocol = load_protocol(root, protocol_sha256)
    events = _events(root)
    own = _protocol_events(events, protocol_sha256)
    return {
        "protocol_sha256": protocol_sha256,
        "experiment_id": protocol["experiment_id"],
        "version": protocol["version"],
        "mode": protocol["mode"],
        "parent_protocol_sha256": protocol["parent_protocol_sha256"],
        "state": lifecycle(events, protocol_sha256),
        "attempts_started": sum(e["event"] == "attempt_started" for e in own),
        "attempts_finished": sum(e["event"] == "attempt_finished" for e in own),
        "protected_uses": sum(e["event"] == "attempt_started" and e["data"]["uses_protected"] for e in own),
        "event_count": len(own),
        "ledger_head_sha256": events[-1]["event_digest"] if events else None,
    }
