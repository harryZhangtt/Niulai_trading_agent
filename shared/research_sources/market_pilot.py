"""Pure market-pilot normalization, comparison, and public receipt projection."""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

_HEX64 = re.compile(r"[0-9a-f]{64}")
_UTC_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z")
MISSING_REASONS = frozenset(("provider_missing", "not_applicable", "not_reported", "nonpositive_denominator"))
SECURITY_CLASSES = frozenset(("COMMON_STOCK", "ADR", "CLASS_SHARE", "ETF", "FUND", "OTHER"))
PROVIDERS = frozenset(("tiger", "yahoo"))
FX_CURRENCIES = frozenset(("USD", "CAD", "EUR", "GBP", "HKD", "JPY", "SGD", "AUD", "CNY", "CNH"))
RECEIPT_STATUSES = frozenset(("PASS_PILOT_ONLY", "INCONCLUSIVE_PILOT", "FAILED_PILOT"))
FIELD_COUNT_KEYS = frozenset(("requested", "tiger_observed", "yahoo_observed", "comparable", "matched", "discrepant", "inconclusive"))
ARTIFACT_HASH_KEYS = frozenset(("tiger_raw", "tiger_manifest", "yahoo_chart_raw", "yahoo_fundamentals_raw", "normalized", "comparison", "private_manifest"))
COVERAGE_REASONS = frozenset(("TIGER_FIELD_MISSING", "YAHOO_FIELD_MISSING", "FIELD_NOT_COMPARABLE", "CURRENT_RESTATED_NOT_PIT", "FILING_AFTER_AS_OF", "CURRENCY_OR_UNIT_MISMATCH", "NO_INDEPENDENT_TOLERANCE"))
DISCREPANCY_REASONS = frozenset(("VALUE_OUTSIDE_TOLERANCE", "TIMESTAMP_MISMATCH", "CURRENCY_OR_UNIT_MISMATCH", "CORPORATE_ACTION_UNRESOLVED", "ENTITY_MAPPING_UNRESOLVED"))


class MarketPilotError(ValueError):
    pass


def _require(ok, code):
    if not ok:
        raise MarketPilotError(code)


def _utc(value, code="MARKET_AS_OF_INVALID"):
    _require(isinstance(value, str) and _UTC_STAMP.fullmatch(value), code)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise MarketPilotError(code) from None
    return parsed


def contract_inputs(value):
    required = {"calibration_sha256", "promotion_sha256", "roster_sha256", "sample_selection_sha256"}
    _require(isinstance(value, dict) and set(value) == required
             and all(isinstance(v, str) and _HEX64.fullmatch(v) for v in value.values()),
             "MARKET_CONTRACT_INPUT_INVALID")
    return dict(value)


def validate_as_of(as_of, *, now=None):
    parsed = _utc(as_of)
    now = now or datetime.now(timezone.utc)
    _require(parsed <= now, "MARKET_AS_OF_FUTURE")
    return parsed


def validate_entity_map(records):
    _require(isinstance(records, list) and records, "ENTITY_MAP_INVALID")
    out, entity_classes, provider_intervals = [], {}, {}
    for record in records:
        required = {"entity_id", "valid_from", "valid_to", "venue", "source", "source_ticker",
                    "security_class", "mapping_provenance"}
        _require(isinstance(record, dict) and set(record) == required, "ENTITY_MAP_INVALID")
        _require(record["security_class"] in SECURITY_CLASSES, "ENTITY_CLASS_INVALID")
        _require(all(isinstance(record[k], str) and record[k] for k in
                     ("entity_id", "venue", "source", "source_ticker", "mapping_provenance")), "ENTITY_MAP_INVALID")
        start = date.fromisoformat(record["valid_from"])
        end = date.max if record["valid_to"] is None else date.fromisoformat(record["valid_to"])
        _require(start <= end, "ENTITY_VALIDITY_INVALID")
        provider_key = (record["source"], record["venue"], record["source_ticker"])
        intervals = provider_intervals.setdefault(provider_key, [])
        _require(all(end < prior_start or start > prior_end for prior_start, prior_end in intervals),
                 "ENTITY_MAP_OVERLAP")
        prior_class = entity_classes.get(record["entity_id"])
        _require(prior_class is None or prior_class == record["security_class"], "ENTITY_CLASS_AMBIGUOUS")
        entity_classes[record["entity_id"]] = record["security_class"]
        intervals.append((start, end)); out.append(dict(record))
    return sorted(out, key=lambda r: r["entity_id"])


def map_entity(entity_map, source, venue, ticker, observed_date):
    day = date.fromisoformat(observed_date)
    matches = [r for r in entity_map if r["source"] == source and r["venue"] == venue
               and r["source_ticker"] == ticker and date.fromisoformat(r["valid_from"]) <= day
               and (r["valid_to"] is None or day <= date.fromisoformat(r["valid_to"]))]
    _require(len(matches) == 1, "ENTITY_MAP_AMBIGUOUS")
    return matches[0]


def normalize_observation(row, *, entity_map, as_of):
    """Normalize one explicit provider row without fills, clipping, or fuzzy joins."""
    cutoff = validate_as_of(as_of)
    required = {"source", "venue", "ticker", "field", "value", "observed_date", "filing_date",
                "currency", "unit", "scale", "missing_reason", "current_restated"}
    _require(isinstance(row, dict) and set(row) == required, "OBSERVATION_SCHEMA_INVALID")
    _require(isinstance(row["source"], str) and row["source"] in PROVIDERS, "OBSERVATION_SOURCE_INVALID")
    _require(type(row["current_restated"]) is bool, "CURRENT_RESTATED_INVALID")
    entity = map_entity(entity_map, row["source"], row["venue"], row["ticker"], row["observed_date"])
    observed = date.fromisoformat(row["observed_date"])
    _require(observed <= cutoff.date(), "OBSERVATION_AFTER_AS_OF")
    filing = None if row["filing_date"] is None else date.fromisoformat(row["filing_date"])
    if filing is not None:
        _require(filing <= cutoff.date(), "FILING_DATE_LEAKAGE")
    missing = row["missing_reason"]
    _require(missing is None or missing in MISSING_REASONS, "MISSING_REASON_INVALID")
    value = None
    if row["value"] is None:
        _require(missing is not None, "MISSING_REASON_REQUIRED")
    else:
        _require(missing is None, "VALUE_MISSING_CONFLICT")
        try:
            value = Decimal(str(row["value"]))
        except InvalidOperation:
            raise MarketPilotError("VALUE_INVALID") from None
        _require(value.is_finite(), "VALUE_INVALID")
        if row["field"] in ("pe", "pe_ttm", "pb", "price_to_book") and value <= 0:
            value, missing = None, "nonpositive_denominator"
    _require(isinstance(row["scale"], int) and -18 <= row["scale"] <= 18, "SCALE_INVALID")
    _require(isinstance(row["unit"], str) and row["unit"], "UNIT_INVALID")
    _require(row["currency"] is None or (isinstance(row["currency"], str) and re.fullmatch(r"[A-Z]{3}", row["currency"])), "CURRENCY_INVALID")
    warning = "current_restated_not_historical_pit" if row["current_restated"] else None
    return {"entity_id": entity["entity_id"], "security_class": entity["security_class"],
            "source": row["source"], "field": row["field"], "value": None if value is None else str(value),
            "observed_date": observed.isoformat(), "filing_date": None if filing is None else filing.isoformat(),
            "currency": row["currency"], "unit": row["unit"], "scale": row["scale"],
            "missing_reason": missing, "pit_eligible": filing is not None and warning is None,
            "warning": warning}


def normalize_fx(row, *, as_of):
    required = {"source", "date", "from_currency", "to_currency", "rate", "direction"}
    _require(isinstance(row, dict) and set(row) == required, "FX_SCHEMA_INVALID")
    _require(row["source"] in PROVIDERS, "FX_SOURCE_INVALID")
    _require(isinstance(row["from_currency"], str) and row["from_currency"] in FX_CURRENCIES
             and isinstance(row["to_currency"], str) and row["to_currency"] in FX_CURRENCIES,
             "FX_CURRENCY_INVALID")
    _require(row["from_currency"] != row["to_currency"], "FX_CURRENCY_PAIR_INVALID")
    try:
        observed = date.fromisoformat(row["date"])
    except (TypeError, ValueError):
        raise MarketPilotError("FX_DATE_INVALID") from None
    _require(observed <= validate_as_of(as_of).date(), "FX_AFTER_AS_OF")
    _require(row["direction"] == f"{row['from_currency']}_PER_{row['to_currency']}", "FX_DIRECTION_INVALID")
    try:
        rate = Decimal(str(row["rate"]))
    except (InvalidOperation, TypeError, ValueError):
        raise MarketPilotError("FX_RATE_INVALID") from None
    _require(rate.is_finite() and rate > 0, "FX_RATE_INVALID")
    return {**row, "rate": str(rate)}


def bind_corporate_actions(actions, entity_map, *, as_of):
    allowed = {"split", "dividend", "symbol_change", "delisting"}
    cutoff = validate_as_of(as_of).date()
    out = []
    for action in actions:
        _require(isinstance(action, dict) and set(action) == {"source", "venue", "ticker", "action_type", "effective_date", "details"}, "ACTION_SCHEMA_INVALID")
        _require(action["source"] in PROVIDERS, "ACTION_SOURCE_INVALID")
        _require(action["action_type"] in allowed and isinstance(action["details"], dict), "ACTION_TYPE_INVALID")
        try:
            effective = date.fromisoformat(action["effective_date"])
        except (TypeError, ValueError):
            raise MarketPilotError("ACTION_DATE_INVALID") from None
        _require(effective <= cutoff, "ACTION_AFTER_AS_OF")
        entity = map_entity(entity_map, action["source"], action["venue"], action["ticker"], action["effective_date"])
        # Symbol changes are evidence only; they never rewrite or stitch maps.
        out.append({**action, "entity_id": entity["entity_id"], "automatic_ticker_stitch": False})
    return out


def compare(primary, secondary, *, absolute_tolerance):
    _require(primary["source"] == "tiger" and secondary["source"] == "yahoo", "PROVIDER_ROLE_INVALID")
    keys = ("entity_id", "field", "observed_date", "currency", "unit", "scale")
    _require(all(primary.get(k) == secondary.get(k) for k in keys), "SEMANTIC_MISMATCH")
    _require(isinstance(absolute_tolerance, str), "TOLERANCE_INVALID")
    try:
        tolerance = Decimal(absolute_tolerance)
    except (InvalidOperation, ValueError, TypeError):
        raise MarketPilotError("TOLERANCE_INVALID") from None
    _require(tolerance.is_finite() and tolerance >= 0, "TOLERANCE_INVALID")
    if primary["value"] is None or secondary["value"] is None:
        return {"status": "INCONCLUSIVE_MISSING", "selected_value": None, "averaged": False}
    difference = abs(Decimal(primary["value"]) - Decimal(secondary["value"]))
    status = "MATCH" if difference <= tolerance else "UNRESOLVED_DISCREPANCY"
    return {"status": status, "absolute_difference": str(difference), "selected_value": None, "averaged": False}


def _count_map(value, expected_keys, code):
    _require(isinstance(value, dict) and set(value) == expected_keys, code)
    _require(all(type(item) is int and item >= 0 for item in value.values()), code)
    return dict(value)


def _reason_list(value, allowed, code):
    _require(isinstance(value, list) and len(value) == len(set(value))
             and all(isinstance(item, str) and item in allowed for item in value), code)
    return list(value)


def sanitized_receipt(private_manifest):
    """Project a closed public schema; no provider strings, paths, URLs, symbols, or values."""
    required = {"status", "started_at", "completed_at", "provider_attempts", "symbol_count",
                "field_counts", "artifact_sha256", "coverage_reasons", "discrepancy_reasons",
                "checkpoint_committed", "release_requested"}
    _require(isinstance(private_manifest, dict) and required <= private_manifest.keys(), "RECEIPT_INPUT_INVALID")
    _require(private_manifest["status"] in RECEIPT_STATUSES, "RECEIPT_STATUS_INVALID")
    started = _utc(private_manifest["started_at"], "RECEIPT_TIMESTAMP_INVALID")
    completed = _utc(private_manifest["completed_at"], "RECEIPT_TIMESTAMP_INVALID")
    _require(started <= completed, "RECEIPT_TIMESTAMP_INVALID")
    provider_attempts = _count_map(private_manifest["provider_attempts"], PROVIDERS, "RECEIPT_PROVIDER_ATTEMPTS_INVALID")
    _require(all(item <= 1 for item in provider_attempts.values()), "RECEIPT_PROVIDER_ATTEMPTS_INVALID")
    _require(type(private_manifest["symbol_count"]) is int and 0 <= private_manifest["symbol_count"] <= 8,
             "RECEIPT_SYMBOL_COUNT_INVALID")
    field_counts = _count_map(private_manifest["field_counts"], FIELD_COUNT_KEYS, "RECEIPT_FIELD_COUNTS_INVALID")
    artifacts = private_manifest["artifact_sha256"]
    _require(isinstance(artifacts, dict) and artifacts and set(artifacts) <= ARTIFACT_HASH_KEYS
             and all(isinstance(value, str) and _HEX64.fullmatch(value) for value in artifacts.values()),
             "RECEIPT_HASH_INVALID")
    _require(type(private_manifest["checkpoint_committed"]) is bool
             and type(private_manifest["release_requested"]) is bool, "RECEIPT_BOOLEAN_INVALID")
    receipt = {
        "status": private_manifest["status"], "started_at": private_manifest["started_at"],
        "completed_at": private_manifest["completed_at"], "provider_attempts": provider_attempts,
        "symbol_count": private_manifest["symbol_count"], "field_counts": field_counts,
        "artifact_sha256": dict(artifacts),
        "coverage_reasons": _reason_list(private_manifest["coverage_reasons"], COVERAGE_REASONS, "RECEIPT_COVERAGE_REASONS_INVALID"),
        "discrepancy_reasons": _reason_list(private_manifest["discrepancy_reasons"], DISCREPANCY_REASONS, "RECEIPT_DISCREPANCY_REASONS_INVALID"),
        "checkpoint_committed": private_manifest["checkpoint_committed"],
        "release_requested": private_manifest["release_requested"],
    }
    canonical = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt["receipt_sha256"] = hashlib.sha256(canonical).hexdigest()
    return receipt
