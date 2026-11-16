"""Provider-free DatasetSnapshot v1 validator and synthetic materializer.

This module proves deterministic identity flow only. It does not authenticate a
real provider, expose protected labels, execute RD-Agent/Qlib, or establish alpha.
"""
from datetime import date, datetime, timezone
from decimal import (Clamped, Context, Decimal, DivisionByZero, FloatOperation, Inexact,
                     InvalidOperation, Overflow, ROUND_HALF_EVEN, Rounded, Subnormal,
                     Underflow, localcontext)
import hashlib
import json
from pathlib import Path
import re
import types


class DatasetError(ValueError):
    pass


ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
PATH = re.compile(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\Z")
MAX_FILE = 2 * 1024 * 1024
ARTIFACT_NAMES = {
    "sources", "series", "calendar", "universe", "observations", "label_roster",
    "label_values", "label_authority", "transformations", "execution", "splits",
}
SEMANTIC_OBSERVATION_ARTIFACTS = ("sources", "series", "calendar", "universe", "observations")
CLOSED_OPERATORS = {"identity", "lag", "difference", "rolling_mean"}
DECIMAL_PRECISION = 34
DECIMAL_ROUNDING = ROUND_HALF_EVEN
DECIMAL_EMIN = -999999
DECIMAL_EMAX = 999999
DECIMAL_CAPITALS = 1
DECIMAL_CLAMP = 0
DECIMAL_SIGNAL_NAMES = ("Clamped", "DivisionByZero", "FloatOperation", "Inexact",
                        "InvalidOperation", "Overflow", "Rounded", "Subnormal", "Underflow")
DECIMAL_TRAPS = frozenset({"DivisionByZero", "InvalidOperation", "Overflow"})
DECIMAL_FLAGS = frozenset()
IMPLEMENTATION_CONSTANT_NAMES = (
    "ID", "SHA", "DECIMAL", "DATE", "TIME", "PATH", "MAX_FILE", "ARTIFACT_NAMES",
    "SEMANTIC_OBSERVATION_ARTIFACTS", "CLOSED_OPERATORS", "DECIMAL_PRECISION",
    "DECIMAL_ROUNDING", "DECIMAL_EMIN", "DECIMAL_EMAX", "DECIMAL_CAPITALS",
    "DECIMAL_CLAMP", "DECIMAL_SIGNAL_NAMES", "DECIMAL_TRAPS", "DECIMAL_FLAGS",
    "IMPLEMENTATION_CONSTANT_NAMES",
)


def require(condition, code):
    if not condition:
        raise DatasetError(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False).encode()
    except (TypeError, ValueError):
        raise DatasetError("DATASET_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "DATASET_DUPLICATE_KEY")
        result[key] = value
    return result


def loads(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              DatasetError("DATASET_NONFINITE")))
    except DatasetError:
        raise
    except (json.JSONDecodeError, UnicodeError, TypeError):
        raise DatasetError("DATASET_JSON_INVALID") from None


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _id(value, code="DATASET_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def _sha(value, code="DATASET_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _date(value, code="DATASET_DATE_INVALID"):
    require(type(value) is str and DATE.fullmatch(value), code)
    try:
        date.fromisoformat(value)
    except ValueError:
        raise DatasetError(code) from None
    return value


def _time(value, code="DATASET_TIME_INVALID"):
    require(type(value) is str and TIME.fullmatch(value), code)
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        raise DatasetError(code) from None


def _decimal(value, code="DATASET_DECIMAL_INVALID"):
    require(type(value) is str and DECIMAL.fullmatch(value) and len(value) <= 80, code)
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise DatasetError(code) from None
    require(number.is_finite() and (value == "0" or not value.startswith("-0")) and
            ("." not in value or not value.endswith("0")), code)
    return value


def _arithmetic_context():
    signals = {signal.__name__: signal for signal in
               (Clamped, DivisionByZero, FloatOperation, Inexact, InvalidOperation,
                Overflow, Rounded, Subnormal, Underflow)}
    require(tuple(sorted(signals)) == tuple(sorted(DECIMAL_SIGNAL_NAMES)),
            "DATASET_DECIMAL_CONTEXT_INVALID")
    return Context(prec=DECIMAL_PRECISION, rounding=DECIMAL_ROUNDING,
                   Emin=DECIMAL_EMIN, Emax=DECIMAL_EMAX,
                   capitals=DECIMAL_CAPITALS, clamp=DECIMAL_CLAMP,
                   flags=[signals[name] for name in sorted(DECIMAL_FLAGS)],
                   traps=[signals[name] for name in sorted(DECIMAL_TRAPS)])


def decimal_text(value):
    with localcontext(_arithmetic_context()):
        number = Decimal(value)
        if not number:
            return "0"
        rendered = format(number.normalize(), "f")
        return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _safe_path(root, relative):
    require(type(relative) is str and relative and len(relative) <= 256 and
            PATH.fullmatch(relative), "DATASET_ARTIFACT_PATH_INVALID")
    path = Path(relative)
    require(not path.is_absolute() and ".." not in path.parts and
            all(part not in {"", "."} for part in path.parts),
            "DATASET_ARTIFACT_PATH_INVALID")
    target = root / path
    require(target.is_file() and not target.is_symlink() and target.resolve().is_relative_to(root),
            "DATASET_ARTIFACT_PATH_INVALID")
    return target


def _read(root, reference):
    _strict(reference, {"path", "sha256", "size_bytes", "rows"},
            "DATASET_ARTIFACT_REF_INVALID")
    path = _safe_path(root, reference["path"])
    raw = path.read_bytes()
    require(0 < len(raw) <= MAX_FILE and reference["size_bytes"] == len(raw) and
            hashlib.sha256(raw).hexdigest() == _sha(reference["sha256"]) and
            type(reference["rows"]) is int and 1 <= reference["rows"] <= 100000,
            "DATASET_ARTIFACT_MISMATCH")
    return raw


def _jsonl(raw, expected_rows):
    require(raw.endswith(b"\n"), "DATASET_JSONL_CANONICAL")
    rows = [loads(line) for line in raw.decode("utf-8").splitlines()]
    require(len(rows) == expected_rows and raw == b"".join(canonical(row) + b"\n" for row in rows),
            "DATASET_JSONL_CANONICAL")
    return rows


def _json(raw, expected_rows=1):
    value = loads(raw)
    require(expected_rows == 1 and raw == canonical(value) + b"\n", "DATASET_JSON_CANONICAL")
    return value


def _scan(value):
    text = canonical(value).decode("ascii").lower()
    forbidden = ("/users/", "/private/", "api_key", "apikey", "bearer ", "password",
                 "secret=", "sk-proj-", "protected_metric", "recovered_metric")
    require(not any(marker in text for marker in forbidden), "DATASET_REDACTION_FAILED")


def validate_label_authority_receipt(value):
    _strict(value, {"schema_version", "authority_id", "authority_kind", "label_roster_sha256",
                    "label_commitment_sha256", "target_definition_sha256", "limitations"},
            "DATASET_LABEL_AUTHORITY_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["authority_kind"] == "synthetic_fixture" and
            type(value["limitations"]) is list and value["limitations"] and
            all(type(item) is str and 0 < len(item) <= 500 for item in value["limitations"]),
            "DATASET_LABEL_AUTHORITY_INVALID")
    _id(value["authority_id"])
    for field in ("label_roster_sha256", "label_commitment_sha256",
                  "target_definition_sha256"):
        _sha(value[field])
    _scan(value)
    return value


def validate_builder_receipt(value):
    fields = {"schema_version", "kind", "builder_code_sha256", "dataset_id",
              "observation_set_sha256", "label_roster_sha256",
              "label_authority_receipt_sha256", "feature_snapshot_sha256",
              "evaluation_population_sha256", "split_spec_sha256", "split_fingerprints",
              "full_feature_artifact_sha256", "full_feature_rows", "output_scope",
              "output_feature_artifact_sha256", "output_feature_rows", "sample_rows",
              "trust_class", "performance_claim"}
    _strict(value, fields, "DATASET_BUILDER_RECEIPT_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "synthetic_pit_builder_receipt" and
            value["trust_class"] == "synthetic" and value["performance_claim"] == "withheld",
            "DATASET_BUILDER_RECEIPT_INVALID")
    _id(value["dataset_id"])
    for field in ("builder_code_sha256", "observation_set_sha256", "label_roster_sha256",
                  "label_authority_receipt_sha256", "feature_snapshot_sha256",
                  "evaluation_population_sha256", "split_spec_sha256",
                  "full_feature_artifact_sha256", "output_feature_artifact_sha256"):
        _sha(value[field])
    require(type(value["split_fingerprints"]) is dict and
            set(value["split_fingerprints"]) == {"development", "validation", "protected"} and
            all(SHA.fullmatch(identity) for identity in value["split_fingerprints"].values()),
            "DATASET_BUILDER_RECEIPT_SPLITS_INVALID")
    scope = _strict(value["output_scope"], {"start", "end"},
                    "DATASET_BUILDER_RECEIPT_SCOPE_INVALID")
    require(_date(scope["start"]) <= _date(scope["end"]) and
            type(value["full_feature_rows"]) is int and value["full_feature_rows"] >= 1 and
            type(value["output_feature_rows"]) is int and value["output_feature_rows"] >= 0 and
            type(value["sample_rows"]) is int and value["sample_rows"] >= 1 and
            value["output_feature_rows"] <= value["full_feature_rows"],
            "DATASET_BUILDER_RECEIPT_SCOPE_INVALID")
    return value


def load_snapshot(root):
    supplied = Path(root).absolute()
    require(supplied.is_dir() and not supplied.is_symlink(), "DATASET_ROOT_INVALID")
    root = supplied.resolve()
    descriptor_path = _safe_path(root, "dataset.json")
    descriptor = _json(descriptor_path.read_bytes())
    _strict(descriptor, {"schema_version", "kind", "dataset_id", "provenance", "created_at",
                         "numeric_encoding", "timezone_policy", "artifacts", "limitations"},
            "DATASET_SCHEMA_INVALID")
    require(type(descriptor["schema_version"]) is int and descriptor["schema_version"] == 1 and
            descriptor["kind"] == "pit_factor_dataset" and
            descriptor["provenance"] == "synthetic_fixture" and
            descriptor["numeric_encoding"] == "canonical-decimal-string-v1" and
            descriptor["timezone_policy"] == "utc-rfc3339-v1",
            "DATASET_VERSION_INVALID")
    _id(descriptor["dataset_id"]); _time(descriptor["created_at"])
    require(type(descriptor["limitations"]) is list and descriptor["limitations"] and
            all(type(item) is str and 0 < len(item) <= 500 for item in descriptor["limitations"]),
            "DATASET_LIMITATIONS_INVALID")
    artifacts = descriptor["artifacts"]
    require(type(artifacts) is dict and set(artifacts) == ARTIFACT_NAMES,
            "DATASET_ARTIFACT_ROSTER_INVALID")
    values = {}
    for name, reference in artifacts.items():
        raw = _read(root, reference)
        values[name] = (_jsonl(raw, reference["rows"]) if reference["path"].endswith(".jsonl")
                        else _json(raw, reference["rows"]))
    _scan({"descriptor": descriptor, "values": values})
    return descriptor, values


def _validate_sources(rows):
    ids = {}
    for row in rows:
        _strict(row, {"source_id", "authority_id", "authority_kind", "source_version",
                      "receipt_sha256", "revision_policy", "trust_class"},
                "DATASET_SOURCE_SCHEMA")
        sid = _id(row["source_id"]); require(sid not in ids, "DATASET_SOURCE_DUPLICATE")
        _id(row["authority_id"]); _id(row["source_version"], "DATASET_SOURCE_VERSION_INVALID")
        require(row["authority_kind"] == "synthetic_fixture" and
                row["trust_class"] == "synthetic" and
                row["revision_policy"] in {"immutable", "revisable"},
                "DATASET_SOURCE_AUTHORITY_INVALID")
        _sha(row["receipt_sha256"]); ids[sid] = row
    return ids


def _validate_series(rows, source_ids):
    result = {}
    for row in rows:
        _strict(row, {"series_id", "source_id", "role", "entity_scope", "unit", "frequency",
                      "calendar_id", "revision_policy", "missing_policy"},
                "DATASET_SERIES_SCHEMA")
        sid = _id(row["series_id"]); require(sid not in result, "DATASET_SERIES_DUPLICATE")
        source_id = _id(row["source_id"])
        require(source_id in source_ids and row["role"] in
                {"feature_input", "price", "cash", "cost"} and
                row["entity_scope"] in {"global", "instrument"} and
                row["frequency"] == "session" and row["revision_policy"] ==
                source_ids[source_id]["revision_policy"] and row["missing_policy"] in
                {"reject", "explicit_null"}, "DATASET_SERIES_INVALID")
        _id(row["unit"]); _id(row["calendar_id"])
        result[sid] = row
    return result


def _validate_calendar(rows, source_ids):
    result = {}
    previous = None
    calendar_ids = set()
    calendar_versions = set()
    for row in rows:
        _strict(row, {"calendar_id", "calendar_version", "session_date", "open_at", "close_at",
                      "previous_session", "next_session", "source_id"}, "DATASET_CALENDAR_SCHEMA")
        calendar_ids.add(_id(row["calendar_id"])); calendar_versions.add(_id(row["calendar_version"]))
        session = _date(row["session_date"])
        opened, closed = _time(row["open_at"]), _time(row["close_at"])
        require(_id(row["source_id"]) in source_ids and opened < closed and
                opened.date().isoformat() == session and closed.date().isoformat() == session,
                "DATASET_CALENDAR_FOREIGN_KEY_INVALID")
        require(session not in result and (previous is None or previous < session),
                "DATASET_CALENDAR_ORDER_INVALID")
        result[session] = row; previous = session
    sessions = list(result)
    for index, session in enumerate(sessions):
        expected_previous = sessions[index - 1] if index else None
        expected_next = sessions[index + 1] if index + 1 < len(sessions) else None
        require(result[session]["previous_session"] == expected_previous and
                result[session]["next_session"] == expected_next,
                "DATASET_CALENDAR_LINK_INVALID")
    require(len(calendar_ids) == 1 and len(calendar_versions) == 1,
            "DATASET_CALENDAR_ID_INVALID")
    return sessions, result, next(iter(calendar_ids))


def _effective_time(row):
    return max(_time(row["observed_at"]), _time(row["available_at"]),
               _time(row["recorded_at"]))


def _validate_universe(rows, sessions, source_ids, calendar_id):
    result = {}
    for row in rows:
        _strict(row, {"calendar_id", "session_date", "entity_id", "eligible", "vintage_id",
                      "observed_at", "available_at", "recorded_at", "source_id"},
                "DATASET_UNIVERSE_SCHEMA")
        key = (_id(row["entity_id"]), _date(row["session_date"]), _id(row["vintage_id"]))
        require(row["calendar_id"] == calendar_id and key[1] in sessions and
                _id(row["source_id"]) in source_ids and
                type(row["eligible"]) is bool and key not in result,
                "DATASET_UNIVERSE_INVALID")
        _time(row["observed_at"]); _effective_time(row); result[key] = row
    logical = {}
    for row in result.values():
        identity = (row["entity_id"], row["session_date"])
        logical.setdefault(identity, []).append(row)
    for rows_for_identity in logical.values():
        source_roster = {row["source_id"] for row in rows_for_identity}
        require(len(source_roster) == 1, "DATASET_UNIVERSE_SOURCE_AMBIGUOUS")
        source_id = next(iter(source_roster))
        require(source_ids[source_id]["revision_policy"] == "revisable" or
                len(rows_for_identity) == 1, "DATASET_UNIVERSE_IMMUTABLE_VINTAGE_INVALID")
    return result


def _validate_observations(rows, series, sessions):
    result = {}
    for row in rows:
        _strict(row, {"series_id", "entity_id", "period_end", "vintage_id", "value",
                      "missing_reason", "observed_at", "available_at", "recorded_at",
                      "source_revision", "source_row_sha256"}, "DATASET_OBSERVATION_SCHEMA")
        sid = _id(row["series_id"]); require(sid in series, "DATASET_OBSERVATION_SERIES_INVALID")
        entity = row["entity_id"]
        require((entity is None) == (series[sid]["entity_scope"] == "global"),
                "DATASET_OBSERVATION_ENTITY_INVALID")
        if entity is not None: _id(entity)
        period = _date(row["period_end"]); require(period in sessions, "DATASET_OBSERVATION_PERIOD_INVALID")
        vintage = _id(row["vintage_id"]); key = (sid, entity, period, vintage)
        require(key not in result, "DATASET_OBSERVATION_DUPLICATE")
        if row["value"] is None:
            require(row["missing_reason"] in {"not_reported", "source_gap", "invalid"},
                    "DATASET_MISSING_REASON_INVALID")
        else:
            _decimal(row["value"]); require(row["missing_reason"] is None,
                                            "DATASET_MISSING_REASON_INVALID")
        require(_time(row["observed_at"]).date().isoformat() == period,
                "DATASET_OBSERVATION_TIME_INVALID")
        _effective_time(row); _id(row["source_revision"]); _sha(row["source_row_sha256"])
        result[key] = row
    logical_counts = {}
    for sid, entity, period, _vintage in result:
        logical_counts[(sid, entity, period)] = logical_counts.get((sid, entity, period), 0) + 1
    require(all(series[sid]["revision_policy"] == "revisable" or count == 1
                for (sid, _entity, _period), count in logical_counts.items()),
            "DATASET_IMMUTABLE_VINTAGE_INVALID")
    return result


def _validate_labels(roster, values, sessions, calendar, entity_ids,
                     target_definition_sha256, snapshot_created_at):
    roster_by_alias = {}
    roster_by_semantic = {}
    for row in roster:
        _strict(row, {"sample_id", "label_id", "entity_id", "origin_session", "window_start_session",
                      "window_end_session", "maturity_at", "target_definition_sha256",
                      "availability_state", "missing_reason"}, "DATASET_LABEL_ROSTER_SCHEMA")
        alias = _id(row["sample_id"])
        require(alias not in roster_by_alias, "DATASET_LABEL_DUPLICATE")
        for field in ("origin_session", "window_start_session", "window_end_session"):
            require(_date(row[field]) in sessions, "DATASET_LABEL_SESSION_INVALID")
        entity = _id(row["entity_id"])
        require(entity in entity_ids and row["target_definition_sha256"] == target_definition_sha256 and
                row["origin_session"] < row["window_start_session"] <= row["window_end_session"] and
                _time(calendar[row["window_end_session"]]["close_at"]) <
                _time(row["maturity_at"]) <= snapshot_created_at and
                row["availability_state"] == "synthetic_mature" and row["missing_reason"] is None,
                "DATASET_LABEL_WINDOW_INVALID")
        _id(row["label_id"])
        semantic = {
            "target_definition_sha256": target_definition_sha256,
            "entity_id": entity, "origin_session": row["origin_session"],
            "window_start_session": row["window_start_session"],
            "window_end_session": row["window_end_session"],
            "maturity_at": row["maturity_at"],
        }
        semantic_id = digest(semantic)
        require(semantic_id not in roster_by_semantic, "DATASET_LABEL_SEMANTIC_DUPLICATE")
        roster_by_alias[alias] = {**row, "semantic_sample_sha256": semantic_id}
        roster_by_semantic[semantic_id] = semantic
    values_by_semantic = {}
    for row in values:
        _strict(row, {"sample_id", "value", "unit"}, "DATASET_LABEL_VALUE_SCHEMA")
        alias = _id(row["sample_id"])
        require(alias in roster_by_alias, "DATASET_LABEL_VALUE_INVALID")
        semantic_id = roster_by_alias[alias]["semantic_sample_sha256"]
        require(semantic_id not in values_by_semantic, "DATASET_LABEL_VALUE_INVALID")
        values_by_semantic[semantic_id] = {"semantic_sample_sha256": semantic_id,
                                           "value": _decimal(row["value"]),
                                           "unit": _id(row["unit"])}
    require(set(roster_by_semantic) == set(values_by_semantic), "DATASET_LABEL_VALUE_INVALID")
    return roster_by_alias, roster_by_semantic, values_by_semantic


def _select_vintage(observations, sid, entity, session, cutoff):
    choices = [(_effective_time(row), row) for (series_id, row_entity, period, _), row
               in observations.items()
               if series_id == sid and row_entity == entity and period == session and
               _effective_time(row) <= cutoff]
    if not choices:
        return None
    newest_time = max(item[0] for item in choices)
    latest = [row for effective, row in choices if effective == newest_time]
    require(len(latest) == 1, "DATASET_VINTAGE_AMBIGUOUS")
    return latest[0]


def _eligible(universe, entity, session, cutoff):
    choices = [( _effective_time(row), row) for (eid, day, _), row in universe.items()
               if eid == entity and day == session and _effective_time(row) <= cutoff]
    require(choices, "DATASET_UNIVERSE_NOT_AVAILABLE")
    newest = max(time for time, _ in choices)
    latest = [row for time, row in choices if time == newest]
    require(len(latest) == 1, "DATASET_UNIVERSE_AMBIGUOUS")
    return latest[0]["eligible"], latest[0]["vintage_id"]


def _transforms(value, series):
    require(type(value) is dict and set(value) == {"schema_version", "transforms"} and
            value["schema_version"] == 1 and type(value["transforms"]) is list and
            1 <= len(value["transforms"]) <= 32, "DATASET_TRANSFORM_SCHEMA")
    result = []
    outputs = set()
    for item in value["transforms"]:
        _strict(item, {"transform_id", "output_series_id", "input_series_id", "operator",
                       "lookback_sessions", "min_periods"}, "DATASET_TRANSFORM_ITEM_SCHEMA")
        _id(item["transform_id"]); output = _id(item["output_series_id"])
        require(output not in outputs and _id(item["input_series_id"]) in series and
                item["operator"] in CLOSED_OPERATORS and type(item["lookback_sessions"]) is int and
                0 <= item["lookback_sessions"] <= 252 and type(item["min_periods"]) is int and
                1 <= item["min_periods"] <= max(1, item["lookback_sessions"] + 1),
                "DATASET_TRANSFORM_INVALID")
        outputs.add(output); result.append(item)
    return result


def _execution(value, series, calendar_id):
    _strict(value, {"schema_version", "calendar_id", "information_cutoff", "signal_lag_sessions",
                    "trade_at", "price_series_id", "cost_bps", "cash_series_id"},
            "DATASET_EXECUTION_SCHEMA")
    require(value["schema_version"] == 1 and value["calendar_id"] == calendar_id and
            value["information_cutoff"] == "session_close" and
            type(value["signal_lag_sessions"]) is int and value["signal_lag_sessions"] >= 1 and
            value["trade_at"] == "next_session_close" and value["price_series_id"] in series and
            series[value["price_series_id"]]["role"] == "price" and
            series[value["price_series_id"]]["entity_scope"] == "instrument" and
            value["cash_series_id"] in series and series[value["cash_series_id"]]["role"] == "cash" and
            series[value["cash_series_id"]]["entity_scope"] == "global",
            "DATASET_EXECUTION_INVALID")
    _id(value["calendar_id"]); _decimal(value["cost_bps"])
    return value


def _splits(value, sessions):
    _strict(value, {"schema_version", "target_definition_sha256", "horizon_sessions", "purge_sessions",
                    "embargo_sessions", "splits"}, "DATASET_SPLIT_SCHEMA")
    require(value["schema_version"] == 1 and type(value["horizon_sessions"]) is int and
            value["horizon_sessions"] > 0 and type(value["purge_sessions"]) is int and
            value["purge_sessions"] >= value["horizon_sessions"] and
            type(value["embargo_sessions"]) is int and value["embargo_sessions"] >= 0,
            "DATASET_SPLIT_POLICY_INVALID")
    _sha(value["target_definition_sha256"])
    result = []
    roles = []
    split_ids = set()
    for item in value["splits"]:
        _strict(item, {"id", "role", "start", "end"}, "DATASET_SPLIT_ITEM_SCHEMA")
        split_id = _id(item["id"])
        require(split_id not in split_ids and
                item["role"] in {"development", "validation", "protected"},
                "DATASET_SPLIT_ROLE_INVALID")
        split_ids.add(split_id)
        start, end = _date(item["start"]), _date(item["end"])
        require(start in sessions and end in sessions and start <= end,
                "DATASET_SPLIT_RANGE_INVALID")
        roles.append(item["role"]); result.append(item)
    require(roles == ["development", "validation", "protected"] and
            result[0]["end"] < result[1]["start"] and result[1]["end"] < result[2]["start"],
            "DATASET_SPLIT_ORDER_INVALID")
    return result


def _code_constant(value):
    if isinstance(value, types.CodeType):
        return _code_semantics(value)
    if value is None or type(value) in {bool, int, float, str}:
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, re.Pattern):
        return {"regex": value.pattern, "flags": value.flags}
    if isinstance(value, (tuple, list)):
        return [_code_constant(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_code_constant(item) for item in value), key=canonical)
    if isinstance(value, dict):
        return {str(key): _code_constant(item) for key, item in sorted(value.items())}
    return {"type": type(value).__name__, "repr": repr(value)}


def _code_semantics(code):
    return {"name": code.co_name, "argcount": code.co_argcount,
            "kwonlyargcount": code.co_kwonlyargcount, "flags": code.co_flags,
            "bytecode": code.co_code.hex(), "names": list(code.co_names),
            "varnames": list(code.co_varnames),
            "constants": [_code_constant(item) for item in code.co_consts]}


def loaded_implementation_sha256():
    functions = [{"symbol": name, "code": _code_semantics(value.__code__)}
                 for name, value in globals().items()
                 if callable(value) and getattr(value, "__module__", None) == __name__ and
                 hasattr(value, "__code__")]
    constants = {name: _code_constant(globals()[name]) for name in IMPLEMENTATION_CONSTANT_NAMES}
    return digest({"functions": sorted(functions, key=lambda item: item["symbol"]),
                   "constants": constants})


def build_snapshot(root, *, start=None, end=None):
    descriptor, values = load_snapshot(root)
    source_ids = _validate_sources(values["sources"])
    series = _validate_series(values["series"], source_ids)
    sessions, _calendar, calendar_id = _validate_calendar(values["calendar"], source_ids)
    require(all(item["calendar_id"] == calendar_id for item in series.values()),
            "DATASET_SERIES_CALENDAR_INVALID")
    universe = _validate_universe(values["universe"], sessions, source_ids, calendar_id)
    entity_ids = {row["entity_id"] for row in values["universe"]}
    observations = _validate_observations(values["observations"], series, sessions)
    split_items = _splits(values["splits"], sessions)
    roster, semantic_roster, label_values = _validate_labels(
        values["label_roster"], values["label_values"], sessions, _calendar, entity_ids,
        values["splits"]["target_definition_sha256"], _time(descriptor["created_at"]))
    transforms = _transforms(values["transformations"], series)
    execution = _execution(values["execution"], series, calendar_id)

    observation_semantics = {name: sorted(values[name], key=lambda row: canonical(row))
                             for name in SEMANTIC_OBSERVATION_ARTIFACTS}
    observation_set_sha256 = digest(observation_semantics)
    label_roster_sha256 = digest([semantic_roster[key] for key in sorted(semantic_roster)])
    label_commitment_sha256 = digest({"synthetic_fixture_values":
                                      [label_values[key] for key in sorted(label_values)]})
    authority = validate_label_authority_receipt(values["label_authority"])
    require(authority["label_roster_sha256"] == label_roster_sha256 and
            authority["label_commitment_sha256"] == label_commitment_sha256 and
            authority["target_definition_sha256"] == values["splits"]["target_definition_sha256"],
            "DATASET_LABEL_AUTHORITY_MISMATCH")
    _id(authority["authority_id"])
    label_authority_receipt_sha256 = digest(authority)
    split_spec_semantics = {
        "schema_version": values["splits"]["schema_version"],
        "target_definition_sha256": values["splits"]["target_definition_sha256"],
        "horizon_sessions": values["splits"]["horizon_sessions"],
        "purge_sessions": values["splits"]["purge_sessions"],
        "embargo_sessions": values["splits"]["embargo_sessions"],
        "splits": [{key: item[key] for key in ("role", "start", "end")}
                   for item in split_items],
    }
    split_spec_sha256 = digest(split_spec_semantics)
    evaluation_population_sha256 = digest({
        "observation_set_sha256": observation_set_sha256,
        "label_roster_sha256": label_roster_sha256,
        "label_commitment_sha256": label_commitment_sha256,
        "target_definition_sha256": values["splits"]["target_definition_sha256"],
        "split_spec_sha256": split_spec_sha256,
    })

    session_start = start or sessions[0]; session_end = end or sessions[-1]
    require(session_start in sessions and session_end in sessions and session_start <= session_end,
            "DATASET_MATERIALIZATION_RANGE_INVALID")
    entities = sorted({row["entity_id"] for row in values["universe"]})
    feature_rows = []
    for session in sessions:
        cutoff = datetime.fromisoformat(_calendar[session]["close_at"][:-1] + "+00:00")
        for entity in entities:
            eligible, universe_vintage = _eligible(universe, entity, session, cutoff)
            if not eligible:
                continue
            features = {}
            for transform in transforms:
                input_id = transform["input_series_id"]
                source_entity = None if series[input_id]["entity_scope"] == "global" else entity
                lookback = transform["lookback_sessions"]
                position = sessions.index(session)
                if position < lookback:
                    features[transform["output_series_id"]] = None
                    continue
                window_sessions = sessions[position - lookback:position + 1]
                window = []
                unavailable = False
                for historic_session in window_sessions:
                    chosen = _select_vintage(observations, input_id, source_entity,
                                             historic_session, cutoff)
                    if chosen is None or chosen["value"] is None:
                        if series[input_id]["missing_policy"] == "reject":
                            raise DatasetError("DATASET_REQUIRED_OBSERVATION_MISSING")
                        unavailable = True
                        break
                    window.append(Decimal(chosen["value"]))
                if unavailable or len(window) < transform["min_periods"]:
                    features[transform["output_series_id"]] = None
                    continue
                with localcontext(_arithmetic_context()):
                    current = window[-1]; prior = window[0]
                    operator = transform["operator"]
                    if operator == "identity": output = current
                    elif operator == "lag": output = prior
                    elif operator == "difference": output = current - prior
                    else: output = sum(window, Decimal(0)) / Decimal(len(window))
                    features[transform["output_series_id"]] = decimal_text(output)
            feature_rows.append({"entity_id": entity, "session_date": session,
                                 "information_cutoff": _calendar[session]["close_at"],
                                 "universe_vintage_id": universe_vintage,
                                 "features": dict(sorted(features.items()))})
    feature_rows.sort(key=lambda row: (row["session_date"], row["entity_id"]))
    feature_artifact_sha256 = digest(feature_rows)
    feature_snapshot_sha256 = digest({
        "observation_set_sha256": observation_set_sha256,
        "transformations": values["transformations"], "execution": execution,
        "feature_artifact_sha256": feature_artifact_sha256,
    })

    session_positions = {session: index for index, session in enumerate(sessions)}
    for row in roster.values():
        require(session_positions[row["window_end_session"]] -
                session_positions[row["origin_session"]] == values["splits"]["horizon_sessions"],
                "DATASET_LABEL_HORIZON_INVALID")
    for before, after in zip(split_items, split_items[1:]):
        prior_rows = [row for row in roster.values()
                      if before["start"] <= row["origin_session"] <= before["end"]]
        require(prior_rows and
                max(session_positions[row["window_end_session"]] for row in prior_rows) +
                values["splits"]["embargo_sessions"] < session_positions[after["start"]] and
                session_positions[before["end"]] + values["splits"]["purge_sessions"] +
                values["splits"]["embargo_sessions"] < session_positions[after["start"]],
                "DATASET_PURGE_EMBARGO_INVALID")

    split_fingerprints = {}
    sample_rows = []
    assigned = set()
    for split in split_items:
        keys = []
        for row in sorted(roster.values(), key=lambda item: item["semantic_sample_sha256"]):
            if split["start"] <= row["origin_session"] <= split["end"]:
                semantic_id = row["semantic_sample_sha256"]
                require(semantic_id not in assigned, "DATASET_SAMPLE_PARTITION_INVALID")
                matching = next((item for item in feature_rows
                                 if item["entity_id"] == row["entity_id"] and
                                 item["session_date"] == row["origin_session"]), None)
                require(matching is not None, "DATASET_SAMPLE_FEATURE_MISSING")
                key = {"semantic_sample_sha256": semantic_id, "entity_id": row["entity_id"],
                       "origin_session": row["origin_session"],
                       "feature_cutoff": matching["information_cutoff"],
                       "universe_vintage_id": matching["universe_vintage_id"],
                       "window_start_session": row["window_start_session"],
                       "window_end_session": row["window_end_session"],
                       "maturity_at": row["maturity_at"]}
                keys.append(key); sample_rows.append({"split_id": split["id"], **key})
                assigned.add(semantic_id)
        require(keys, "DATASET_SPLIT_EMPTY")
        split_fingerprints[split["role"]] = digest({
            "evaluation_population_sha256": evaluation_population_sha256,
            "split_spec_sha256": split_spec_sha256, "role": split["role"],
            "ordered_sample_keys": keys,
        })
    require(assigned == set(semantic_roster), "DATASET_SAMPLE_PARTITION_INVALID")
    output_features = [row for row in feature_rows
                       if session_start <= row["session_date"] <= session_end]
    builder_receipt = {
        "schema_version": 1, "kind": "synthetic_pit_builder_receipt",
        "builder_code_sha256": loaded_implementation_sha256(),
        "dataset_id": descriptor["dataset_id"],
        "observation_set_sha256": observation_set_sha256,
        "label_roster_sha256": label_roster_sha256,
        "label_authority_receipt_sha256": label_authority_receipt_sha256,
        "feature_snapshot_sha256": feature_snapshot_sha256,
        "evaluation_population_sha256": evaluation_population_sha256,
        "split_spec_sha256": split_spec_sha256,
        "split_fingerprints": split_fingerprints,
        "full_feature_artifact_sha256": feature_artifact_sha256,
        "full_feature_rows": len(feature_rows),
        "output_scope": {"start": session_start, "end": session_end},
        "output_feature_artifact_sha256": digest(output_features),
        "output_feature_rows": len(output_features),
        "sample_rows": len(sample_rows),
        "trust_class": "synthetic", "performance_claim": "withheld",
    }
    validate_builder_receipt(builder_receipt)
    return {
        "schema_version": 1, "kind": "pit_factor_dataset_build",
        "dataset_snapshot_sha256": digest(descriptor),
        "observation_set_sha256": observation_set_sha256,
        "label_roster_sha256": label_roster_sha256,
        "label_commitment_sha256": label_commitment_sha256,
        "label_authority_receipt_sha256": label_authority_receipt_sha256,
        "feature_snapshot_sha256": feature_snapshot_sha256,
        "feature_artifact_sha256": feature_artifact_sha256,
        "evaluation_population_sha256": evaluation_population_sha256,
        "split_spec_sha256": split_spec_sha256,
        "split_fingerprints": split_fingerprints,
        "builder_receipt": builder_receipt,
        "builder_receipt_sha256": digest(builder_receipt),
        "output_feature_artifact_sha256": digest(output_features),
        "features": output_features,
        "samples": sample_rows,
        "fixture_only": True,
        "performance_claim": "withheld",
    }
