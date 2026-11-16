"""Synthetic acquisition-to-PIT normalization handoff.

No tracked response contains values. This contract proves timestamp, revision,
listing and correction mapping only; it authenticates no provider response.
"""
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from . import contract

PACKAGE = Path(__file__).resolve().parent
CANDIDATE = PACKAGE / "candidate-real-inventory.json"
SHA = re.compile(r"[a-f0-9]{64}\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\Z")
MAX_RECORDS = 128
RESPONSE_FIELDS = {
    "schema_version", "kind", "trust_class", "source_format", "role",
    "route_policy_sha256", "acquisition_receipt_sha256", "records",
}
ALFRED_FIELDS = {
    "record_id", "date", "value_present", "value_commitment_sha256",
    "realtime_start", "realtime_end", "recorded_at", "source_row_sha256",
}
DATABENTO_FIELDS = {
    "record_id", "listing_id", "mapping_version", "event_unique_id",
    "event_action", "event_effective_at", "effective_start", "effective_end",
    "ts_created", "ts_record", "recorded_at", "value_present",
    "value_commitment_sha256", "source_row_sha256",
}
NORMALIZED_FIELDS = {
    "logical_key", "semantic_row_id", "observed_at", "published_at",
    "available_at", "recorded_at", "vintage_id", "supersedes_vintage_id",
    "source_row_sha256", "value_commitment_sha256", "value_included",
    "listing_id", "mapping_version", "event_unique_id", "event_action",
    "effective_start", "effective_end", "vintage_end_at",
    "provider_version_at", "provider_created_at",
}
RECEIPT_FIELDS = {
    "schema_version", "kind", "trust_class", "source_format", "role",
    "route_policy_sha256", "acquisition_receipt_sha256", "response_sha256",
    "normalization_policy", "normalized_records", "values_included",
}


class HandoffError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise HandoffError(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise HandoffError("SOURCE_HANDOFF_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _sha(value, code="SOURCE_HANDOFF_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _id(value, code="SOURCE_HANDOFF_ID_INVALID"):
    return contract._id(value, code)


def _date(value):
    require(type(value) is str and DATE.fullmatch(value), "SOURCE_HANDOFF_DATE_INVALID")
    try: date.fromisoformat(value)
    except ValueError: raise HandoffError("SOURCE_HANDOFF_DATE_INVALID") from None
    return value


def _time(value):
    require(type(value) is str and TIME.fullmatch(value), "SOURCE_HANDOFF_TIME_INVALID")
    try: parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError: raise HandoffError("SOURCE_HANDOFF_TIME_INVALID") from None
    require(parsed.utcoffset().total_seconds() == 0, "SOURCE_HANDOFF_TIME_INVALID")
    return parsed


def _timestamp(value):
    _time(value)
    return value


def _route_policy(role, source_format):
    inventory = contract.load_inventory(CANDIDATE)
    entry = next(item for item in inventory["entries"] if item["role"] == role)
    provider = "fred" if source_format == "alfred" else "databento"
    matches = [route for route in entry["provider_routes"]
               if route["provider_id"] == provider and route["priority"] == "primary"]
    require(len(matches) == 1, "SOURCE_HANDOFF_ROUTE_UNAVAILABLE")
    return digest(contract._route_semantic(matches[0]))


def validate_response(value):
    _strict(value, RESPONSE_FIELDS, "SOURCE_HANDOFF_RESPONSE_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "synthetic_source_acquisition_response" and
            value["trust_class"] == "synthetic_fixture" and
            value["source_format"] in {"alfred", "databento"} and
            value["role"] in contract.ROLES and
            type(value["records"]) is list and 1 <= len(value["records"]) <= MAX_RECORDS,
            "SOURCE_HANDOFF_RESPONSE_INVALID")
    require(value["route_policy_sha256"] == _route_policy(
        value["role"], value["source_format"]), "SOURCE_HANDOFF_ROUTE_MISMATCH")
    _sha(value["acquisition_receipt_sha256"])
    if value["source_format"] == "alfred":
        require(value["role"] in {"real_yield", "credit_spread", "cash_rate"},
                "SOURCE_HANDOFF_FORMAT_ROLE")
        _validate_alfred(value["records"])
    else:
        require(value["role"] in {"spy_market", "oneq_market"},
                "SOURCE_HANDOFF_FORMAT_ROLE")
        _validate_databento(value["records"])
    contract._scan(value)
    return value


def _version_semantic(row):
    return {key: row[key] for key in sorted(set(row) - {"record_id"})}


def _validate_alfred(records):
    ids = set(); vintages = {}
    for row in records:
        _strict(row, ALFRED_FIELDS, "SOURCE_HANDOFF_ALFRED_SCHEMA")
        rid = _id(row["record_id"]); require(rid not in ids, "SOURCE_HANDOFF_DUPLICATE")
        ids.add(rid); _date(row["date"]); _date(row["realtime_start"])
        vintage_key = (row["date"], row["realtime_start"])
        semantic = _version_semantic(row)
        if vintage_key in vintages:
            require(vintages[vintage_key] == semantic,
                    "SOURCE_HANDOFF_VINTAGE_AMBIGUOUS")
        else:
            vintages[vintage_key] = semantic
        if row["realtime_end"] is not None: _date(row["realtime_end"])
        require(row["realtime_end"] is None or row["realtime_start"] <= row["realtime_end"],
                "SOURCE_HANDOFF_REALTIME_RANGE")
        require(row["value_present"] is False, "SOURCE_HANDOFF_VALUE_FORBIDDEN")
        _sha(row["value_commitment_sha256"]); _sha(row["source_row_sha256"])
        _time(row["recorded_at"])


def _validate_databento(records):
    ids = set(); event_listings = {}; versions = set(); event_versions = {}
    event_rows = {}
    for row in records:
        _strict(row, DATABENTO_FIELDS, "SOURCE_HANDOFF_DATABENTO_SCHEMA")
        rid = _id(row["record_id"]); require(rid not in ids, "SOURCE_HANDOFF_DUPLICATE")
        ids.add(rid); listing = _id(row["listing_id"]); version = _id(row["mapping_version"])
        event = _id(row["event_unique_id"])
        require(event_listings.setdefault(event, listing) == listing,
                "SOURCE_HANDOFF_TICKER_SPLICE")
        event_version = (event, row["ts_record"])
        semantic = _version_semantic(row)
        if event_version in event_versions:
            require(event_versions[event_version] == semantic,
                    "SOURCE_HANDOFF_VINTAGE_AMBIGUOUS")
        else:
            event_versions[event_version] = semantic
            event_rows.setdefault(event, []).append(row)
        require(not versions or version in versions,
                "SOURCE_HANDOFF_MAPPING_VERSION_DRIFT")
        versions.add(version)
        require(row["event_action"] in {"new", "correct", "cancel"},
                "SOURCE_HANDOFF_EVENT_ACTION")
        for key in ("event_effective_at", "effective_start", "ts_created",
                    "ts_record", "recorded_at"):
            _time(row[key])
        if row["effective_end"] is not None: _time(row["effective_end"])
        require(row["effective_end"] is None or
                _time(row["effective_start"]) <= _time(row["effective_end"]),
                "SOURCE_HANDOFF_EFFECTIVE_RANGE")
        require(_time(row["ts_created"]) <= _time(row["ts_record"]) <=
                _time(row["recorded_at"]), "SOURCE_HANDOFF_RECORD_TIME")
        require(row["value_present"] is False, "SOURCE_HANDOFF_VALUE_FORBIDDEN")
        _sha(row["value_commitment_sha256"]); _sha(row["source_row_sha256"])
    for rows in event_rows.values():
        ordered = sorted(rows, key=lambda item: _time(item["ts_record"]))
        require(ordered[0]["event_action"] == "new" and
                all(item["event_action"] in {"correct", "cancel"}
                    for item in ordered[1:]) and
                all(item["event_action"] != "cancel" for item in ordered[:-1]),
                "SOURCE_HANDOFF_EVENT_LIFECYCLE")


def _action_rank(action):
    return {"observation": 0, "new": 0, "correct": 1, "cancel": 2}[action]


def _source_order(row, source_format):
    if source_format == "alfred":
        version = row["realtime_start"] + "T00:00:00Z"
        created = version
        logical = (row["date"], row["realtime_start"])
        action = "observation"
    else:
        version = row["ts_record"]; created = row["ts_created"]
        logical = (row["event_unique_id"], row["ts_record"])
        action = row["event_action"]
    available = max((version, row["recorded_at"]), key=_time)
    return (_time(available), _time(version), _time(created), _action_rank(action),
            canonical(_version_semantic(row)), logical)


def _normalized_order(row):
    return (_time(row["available_at"]), _time(row["provider_version_at"]),
            _time(row["provider_created_at"]), _action_rank(row["event_action"]))


def normalize_response(value):
    value = validate_response(value)
    normalized = []
    prior = {}
    sorted_rows = sorted(value["records"], key=lambda row:
                         _source_order(row, value["source_format"]))
    seen_versions = set()
    for row in sorted_rows:
        version_key = ((row["date"], row["realtime_start"])
                       if value["source_format"] == "alfred"
                       else (row["event_unique_id"], row["ts_record"]))
        if version_key in seen_versions:
            continue
        seen_versions.add(version_key)
        if value["source_format"] == "alfred":
            observed = row["date"] + "T00:00:00Z"
            published = row["realtime_start"] + "T00:00:00Z"
            recorded = row["recorded_at"]
            available = max((published, recorded), key=_time)
            logical = value["role"] + "--" + row["date"]
            listing = None; mapping = "alfred-vintage-v1"; event = None
            action = "observation"; effective_start = None; effective_end = None
            provider_version_at = published; provider_created_at = published
            vintage_end_at = (None if row["realtime_end"] is None
                              else row["realtime_end"] + "T00:00:00Z")
        else:
            observed = row["event_effective_at"]; published = row["ts_created"]
            recorded = row["recorded_at"]
            available = max((row["ts_record"], recorded), key=_time)
            logical = row["listing_id"] + "--" + row["event_unique_id"]
            listing = row["listing_id"]; mapping = row["mapping_version"]
            event = row["event_unique_id"]; action = row["event_action"]
            effective_start = row["effective_start"]; effective_end = row["effective_end"]
            vintage_end_at = None; provider_version_at = row["ts_record"]
            provider_created_at = row["ts_created"]
        vintage = digest({"logical_key": logical, "available_at": available,
                          "source_row_sha256": row["source_row_sha256"]})
        item = {
            "logical_key": logical, "semantic_row_id": digest({"logical_key": logical}),
            "observed_at": observed, "published_at": published,
            "available_at": available, "recorded_at": recorded,
            "vintage_id": vintage, "supersedes_vintage_id": prior.get(logical),
            "source_row_sha256": row["source_row_sha256"],
            "value_commitment_sha256": row["value_commitment_sha256"],
            "value_included": False, "listing_id": listing,
            "mapping_version": mapping, "event_unique_id": event,
            "event_action": action, "effective_start": effective_start,
            "effective_end": effective_end, "vintage_end_at": vintage_end_at,
            "provider_version_at": provider_version_at,
            "provider_created_at": provider_created_at,
        }
        prior[logical] = vintage; normalized.append(item)
    receipt = {
        "schema_version": 1, "kind": "synthetic_source_normalization_receipt",
        "trust_class": "synthetic_fixture", "source_format": value["source_format"],
        "role": value["role"], "route_policy_sha256": value["route_policy_sha256"],
        "acquisition_receipt_sha256": value["acquisition_receipt_sha256"],
        "response_sha256": digest(value),
        "normalization_policy": ("alfred-date-value-realtime-v1"
                                 if value["source_format"] == "alfred"
                                 else "databento-ts-record-event-v1"),
        "normalized_records": normalized, "values_included": False,
    }
    return validate_receipt(receipt)


def validate_receipt(value):
    _strict(value, RECEIPT_FIELDS, "SOURCE_HANDOFF_RECEIPT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "synthetic_source_normalization_receipt" and
            value["trust_class"] == "synthetic_fixture" and
            value["source_format"] in {"alfred", "databento"} and
            value["role"] in contract.ROLES and value["values_included"] is False and
            type(value["normalized_records"]) is list and value["normalized_records"],
            "SOURCE_HANDOFF_RECEIPT_INVALID")
    for key in ("route_policy_sha256", "acquisition_receipt_sha256", "response_sha256"):
        _sha(value[key])
    expected_policy = ("alfred-date-value-realtime-v1" if value["source_format"] == "alfred"
                       else "databento-ts-record-event-v1")
    require(value["normalization_policy"] == expected_policy,
            "SOURCE_HANDOFF_NORMALIZATION_POLICY")
    for row in value["normalized_records"]:
        _strict(row, NORMALIZED_FIELDS, "SOURCE_HANDOFF_NORMALIZED_SCHEMA")
        _id(row["logical_key"]); _sha(row["semantic_row_id"])
        for key in ("observed_at", "published_at", "available_at", "recorded_at"):
            _time(row[key])
        _sha(row["vintage_id"]); _sha(row["source_row_sha256"])
        _sha(row["value_commitment_sha256"])
        require(row["supersedes_vintage_id"] is None or SHA.fullmatch(row["supersedes_vintage_id"]),
                "SOURCE_HANDOFF_SUPERSESSION")
        require(row["value_included"] is False, "SOURCE_HANDOFF_VALUE_FORBIDDEN")
        for key in ("listing_id", "mapping_version", "event_unique_id", "event_action"):
            require(row[key] is None or type(row[key]) is str,
                    "SOURCE_HANDOFF_NORMALIZED_FIELD")
        for key in ("effective_start", "effective_end", "vintage_end_at",
                    "provider_version_at", "provider_created_at"):
            if row[key] is not None:
                _time(row[key])
    contract._scan(value)
    return value


def select_as_of(receipt, cutoff):
    receipt = validate_receipt(receipt); cutoff_time = _time(cutoff)
    chosen = {}
    for row in receipt["normalized_records"]:
        if _time(row["available_at"]) <= cutoff_time:
            current = chosen.get(row["logical_key"])
            if current is None or _normalized_order(current) < _normalized_order(row):
                chosen[row["logical_key"]] = row
            elif _normalized_order(current) == _normalized_order(row):
                require(current == row, "SOURCE_HANDOFF_VINTAGE_AMBIGUOUS")
    return [row for _, row in sorted(chosen.items()) if row["event_action"] != "cancel"]
