"""Bounded data reads, independent of credential-store and report orchestration."""
from datetime import date, datetime, timezone
import hashlib
import json
import re

TOOLS = ("positions", "assets", "snapshot", "market_snapshot")
ACCOUNT_TOOLS = ("positions", "assets", "snapshot")
SECURITY_TYPES = ("STK", "OPT", "FUT", "FUND")
DEFAULT_TYPES = ("STK", "OPT", "FUT")
MARKET_MAX_SYMBOLS = 8
MARKET_VENUES = ("NASDAQ", "NYSE", "NYSEARCA", "NYSEAMERICAN", "BATS")
MARKET_CLASSES = ("COMMON_STOCK", "ADR", "CLASS_SHARE", "ETF", "FUND", "OTHER")
MARKET_FIELDS = {
    "briefs": frozenset(("latest_price", "latest_time", "pre_close", "open", "high", "low", "volume", "status")),
    "stock_fundamental": frozenset(("market_cap", "float_market_cap", "ttm_eps", "ttm_pe_rate", "pb_rate", "roe", "roa")),
    "financial_daily": frozenset(("shares_outstanding", "market_cap", "pe_ttm", "pb")),
    "financial_report": frozenset(("total_revenue", "net_income", "total_assets", "total_liabilities", "shareholders_equity", "operating_cash_flow")),
}
FX_CURRENCIES = frozenset(("USD", "CAD", "EUR", "GBP", "HKD", "JPY", "SGD", "AUD", "CNY", "CNH"))
CORPORATE_ACTIONS = frozenset(("split", "dividend", "symbol_change", "delisting"))
_HEX64 = re.compile(r"[0-9a-f]{64}")
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,14}")
_ENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_AUTH_ID = re.compile(r"mpa_[0-9a-f]{32}")
MAX_SAMPLE_SELECTION_BYTES = 256 * 1024
SELECTION_SCHEMA = "market-pilot-sample-selection-document/v1"
SELECTION_CONTRACT_SHA256 = "42b3112080e3233d6922ef1b87fab38818cfb34b64757e7e0f7cb060f58f7997"
SELECTION_DOCUMENT_SHA256 = "f3f6e9d5c4eb5f21719225be8208bdd80c108ed6268c230aacb3d1bb1cc811d1"
ROSTER_PACKET_SHA256 = "3005ba73b5be023f03c9614bb1cb3a2b09ff8b86a52c12daa01763d93de60c28"
CALIBRATION_COHORT_SHA256 = "442fbff98f2e02651842891d7c5d31bcec0a2be5311c32d5129400af2a1d3634"
CALIBRATION_ORDERED_SHA256 = "ec29e8afe8975cab2d3f2a82798c4d38b28c68988be5ce6b1b219104c9478214"
PROMOTION_COHORT_SHA256 = "bdd1594ade846603d2796a09e00ac0f5ed657f83a79c9cd278a635dd659717af"
PROMOTION_ORDERED_SHA256 = "b1084fb0254fa2850b1791ff96335c1e9cc958ad654e85868f1651a331f9a3ec"


def _utc(value, require):
    require(isinstance(value, str) and value.endswith("Z"), "TIGER_MARKET_AS_OF_INVALID")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        require(False, "TIGER_MARKET_AS_OF_INVALID")
    require(parsed <= datetime.now(timezone.utc), "TIGER_MARKET_AS_OF_FUTURE")
    return parsed


def _canonical(value, require, code="TIGER_MARKET_SELECTION_INVALID"):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        require(False, code)
    require(len(raw) <= MAX_SAMPLE_SELECTION_BYTES, "TIGER_MARKET_SELECTION_TOO_LARGE")
    return raw


def _digest(value, require):
    return hashlib.sha256(_canonical(value, require)).hexdigest()


def _selection_ref(value, require):
    require(isinstance(value, dict) and set(value) == {"bytes", "path", "sha256"},
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    require(type(value["bytes"]) is int and value["bytes"] > 0
            and isinstance(value["path"], str) and 1 <= len(value["path"]) <= 512
            and isinstance(value["sha256"], str) and _HEX64.fullmatch(value["sha256"]),
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")


def _selection_query_record(record, require):
    require(isinstance(record, dict) and set(record) == {"entity_id", "roster_row_sha256", "security_class", "symbol", "venue"},
            "TIGER_MARKET_SELECTION_RECORD_INVALID")
    require(isinstance(record["symbol"], str) and _SYMBOL.fullmatch(record["symbol"])
            and isinstance(record["entity_id"], str) and _ENTITY.fullmatch(record["entity_id"])
            and record["venue"] in MARKET_VENUES and record["security_class"] in MARKET_CLASSES
            and isinstance(record["roster_row_sha256"], str) and _HEX64.fullmatch(record["roster_row_sha256"]),
            "TIGER_MARKET_SELECTION_RECORD_INVALID")
    base = {key: record[key] for key in ("entity_id", "security_class", "symbol", "venue")}
    require(record["roster_row_sha256"] == _digest(base, require), "TIGER_MARKET_ROSTER_BINDING_INVALID")
    return dict(record)


def _selection_detail_record(record, query_record, require):
    keys = {"entity_id", "query_roster_binding_sha256", "rank", "rank_sha", "roster_row_sha256",
            "security_class", "symbol", "venue"}
    require(isinstance(record, dict) and set(record) == keys, "TIGER_MARKET_SELECTION_RECORD_INVALID")
    require(type(record["rank"]) is int and record["rank"] > 0
            and all(isinstance(record[key], str) and _HEX64.fullmatch(record[key])
                    for key in ("query_roster_binding_sha256", "rank_sha", "roster_row_sha256")),
            "TIGER_MARKET_SELECTION_RECORD_INVALID")
    expected = {key: record[key] for key in ("entity_id", "security_class", "symbol", "venue")}
    expected["roster_row_sha256"] = record["query_roster_binding_sha256"]
    require(query_record == expected, "TIGER_MARKET_SELECTION_RECORD_MISMATCH")
    _selection_query_record(query_record, require)


def _selection_cohort(value, expected_id, expected_cohort_hash, expected_ordered_hash, require):
    keys = {"adaptive", "cohort_id", "cohort_sha256", "ordered_query_symbols_sha256",
            "query_symbol_records", "records", "reorder_allowed", "reuse_allowed", "size"}
    require(isinstance(value, dict) and set(value) == keys, "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    require(value["cohort_id"] == expected_id and value["adaptive"] is False
            and value["reorder_allowed"] is False and value["reuse_allowed"] is False
            and type(value["size"]) is int and 1 <= value["size"] <= MARKET_MAX_SYMBOLS
            and isinstance(value["records"], list) and isinstance(value["query_symbol_records"], list)
            and len(value["records"]) == value["size"] == len(value["query_symbol_records"]),
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    records = [_selection_query_record(item, require) for item in value["query_symbol_records"]]
    for detail, query_record in zip(value["records"], records):
        _selection_detail_record(detail, query_record, require)
    require(value["cohort_sha256"] == _digest(value["records"], require) == expected_cohort_hash,
            "TIGER_MARKET_SELECTION_COHORT_INVALID")
    require(value["ordered_query_symbols_sha256"] == _digest(records, require) == expected_ordered_hash,
            "TIGER_MARKET_SELECTION_ORDER_INVALID")
    require(len({item["symbol"] for item in records}) == len(records)
            and len({item["entity_id"] for item in records}) == len(records),
            "TIGER_MARKET_SELECTION_DUPLICATE")
    return records


def _sample_selection(document, contract, symbols, require):
    raw = _canonical(document, require)
    document_sha = hashlib.sha256(raw).hexdigest()
    require(document_sha == contract["sample_selection_sha256"] == SELECTION_DOCUMENT_SHA256,
            "TIGER_MARKET_SELECTION_HASH_MISMATCH")
    top_keys = {"algorithm", "builder", "cohorts", "contract_sha256", "eligibility", "invariants",
                "roster", "schema_version"}
    require(isinstance(document, dict) and set(document) == top_keys
            and document["schema_version"] == SELECTION_SCHEMA
            and document["contract_sha256"] == SELECTION_CONTRACT_SHA256,
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    algorithm = document["algorithm"]
    require(isinstance(algorithm, dict) and set(algorithm) == {"name", "rank_preimage_exact_keys", "seed", "sort_order", "version"}
            and algorithm["name"] == "sha256_ranked_without_replacement"
            and algorithm["seed"] == "market-pilot-calibration-20261110-v1"
            and algorithm["version"] == "market-pilot-sample-selection/v1"
            and algorithm["rank_preimage_exact_keys"] == ["algorithm", "roster_packet_sha256", "roster_row_sha256", "seed", "version"]
            and algorithm["sort_order"] == ["rank_sha", "raw_symbol", "roster_row_sha256"],
            "TIGER_MARKET_SELECTION_BOUNDARY_INVALID")
    builder = document["builder"]
    require(isinstance(builder, dict) and set(builder) == {"path", "sha256", "version"}
            and builder["version"] == "market-pilot-sample-selection-builder/v1"
            and isinstance(builder["path"], str) and 1 <= len(builder["path"]) <= 512
            and isinstance(builder["sha256"], str) and _HEX64.fullmatch(builder["sha256"]),
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    roster = document["roster"]
    require(isinstance(roster, dict) and set(roster) == {"normalized_rows", "packet", "row_count", "validation_receipt"}
            and type(roster["row_count"]) is int and roster["row_count"] > 0,
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    for key in ("normalized_rows", "packet", "validation_receipt"):
        _selection_ref(roster[key], require)
    require(contract["roster_sha256"] == roster["packet"]["sha256"] == ROSTER_PACKET_SHA256,
            "TIGER_MARKET_SELECTION_ROSTER_INVALID")
    eligibility = document["eligibility"]
    require(isinstance(eligibility, dict) and set(eligibility) == {"common_stock_claim", "eligible_count", "exact_predicates", "query_security_class", "query_venue", "security_name_semantic_inference_used"}
            and eligibility["common_stock_claim"] is False and eligibility["security_name_semantic_inference_used"] is False
            and eligibility["query_security_class"] == "OTHER" and eligibility["query_venue"] == "NASDAQ"
            and type(eligibility["eligible_count"]) is int and eligibility["eligible_count"] > 0
            and eligibility["exact_predicates"] == {"etf": "N", "financial_status": "N", "next_shares": "N", "test_issue": "N"},
            "TIGER_MARKET_SELECTION_BOUNDARY_INVALID")
    require(document["invariants"] == {"adaptive_selection_allowed": False, "cohort_reuse_allowed": False,
            "cohorts_disjoint": True, "order_frozen": True, "promotion_authorized": False,
            "reorder_allowed": False, "without_replacement": True},
            "TIGER_MARKET_SELECTION_BOUNDARY_INVALID")
    cohorts = document["cohorts"]
    require(isinstance(cohorts, dict) and set(cohorts) == {"calibration", "reserved_promotion"},
            "TIGER_MARKET_SELECTION_SCHEMA_INVALID")
    calibration = _selection_cohort(cohorts["calibration"], "calibration", CALIBRATION_COHORT_SHA256,
                                    CALIBRATION_ORDERED_SHA256, require)
    promotion = _selection_cohort(cohorts["reserved_promotion"], "reserved_promotion", PROMOTION_COHORT_SHA256,
                                  PROMOTION_ORDERED_SHA256, require)
    require(set(item["symbol"] for item in calibration).isdisjoint(item["symbol"] for item in promotion),
            "TIGER_MARKET_SELECTION_COHORT_INVALID")
    require(symbols == calibration, "TIGER_MARKET_CALIBRATION_ONLY")
    return document_sha


def _market_query(query, require):
    args = query["arguments"]
    expected = {"as_of", "authorization_id", "authorization_sha256", "corporate_action_start", "corporate_actions", "contract", "fields", "fx_currencies", "sample_selection", "symbols"}
    require(isinstance(args, dict) and set(args) == expected, "TIGER_MARKET_ARGUMENTS_INVALID")
    require(isinstance(args["authorization_id"], str) and _AUTH_ID.fullmatch(args["authorization_id"]), "TIGER_MARKET_AUTHORIZATION_INVALID")
    require(isinstance(args["authorization_sha256"], str) and _HEX64.fullmatch(args["authorization_sha256"]), "TIGER_MARKET_AUTHORIZATION_INVALID")
    as_of = _utc(args["as_of"], require)
    try:
        begin = date.fromisoformat(args["corporate_action_start"])
    except (TypeError, ValueError):
        require(False, "TIGER_MARKET_DATE_INVALID")
    require(begin <= as_of.date() and (as_of.date() - begin).days <= 366, "TIGER_MARKET_DATE_INVALID")
    contract = args["contract"]
    require(isinstance(contract, dict) and set(contract) == {"calibration_sha256", "promotion_sha256", "roster_sha256", "sample_selection_sha256"}
            and all(isinstance(v, str) and _HEX64.fullmatch(v) for v in contract.values()), "TIGER_MARKET_CONTRACT_INVALID")
    records = args["symbols"]
    require(isinstance(records, list) and 1 <= len(records) <= MARKET_MAX_SYMBOLS, "TIGER_MARKET_BATCH_INVALID")
    normalized = [_selection_query_record(record, require) for record in records]
    require(len({item["symbol"] for item in normalized}) == len(normalized)
            and len({item["entity_id"] for item in normalized}) == len(normalized), "TIGER_MARKET_DUPLICATE_SYMBOL")
    _sample_selection(args["sample_selection"], contract, normalized, require)
    fields = args["fields"]
    require(isinstance(fields, dict) and set(fields) == set(MARKET_FIELDS), "TIGER_MARKET_FIELDS_INVALID")
    clean_fields = {}
    for group, allowed in MARKET_FIELDS.items():
        selected = fields[group]
        require(isinstance(selected, list) and selected and len(selected) == len(set(selected))
                and all(isinstance(v, str) and v in allowed for v in selected), "TIGER_MARKET_FIELDS_INVALID")
        clean_fields[group] = list(selected)
    fx = args["fx_currencies"]
    require(isinstance(fx, list) and fx and len(fx) == len(set(fx)) and "USD" in fx
            and all(v in FX_CURRENCIES for v in fx), "TIGER_MARKET_FX_INVALID")
    actions = args["corporate_actions"]
    require(isinstance(actions, list) and actions and len(actions) == len(set(actions))
            and all(v in CORPORATE_ACTIONS for v in actions), "TIGER_MARKET_ACTION_INVALID")
    return {"tool": "market_snapshot", "arguments": {**args, "symbols": normalized, "fields": clean_fields,
            "fx_currencies": list(fx), "corporate_actions": list(actions)}}


def validate_query(query, require):
    require(isinstance(query, dict) and set(query) == {"tool", "arguments"}, "TIGER_QUERY_INVALID")
    require(query["tool"] in TOOLS, "TIGER_TOOL_NOT_ALLOWED")
    if query["tool"] == "market_snapshot":
        return _market_query(query, require)
    args = query["arguments"]
    require(isinstance(args, dict), "TIGER_ARGUMENTS_INVALID")
    allowed = {"security_types"} if query["tool"] != "assets" else set()
    require(set(args) <= allowed, "TIGER_ARGUMENTS_INVALID")
    types = args.get("security_types", list(DEFAULT_TYPES))
    require(isinstance(types, list) and 1 <= len(types) <= 4
            and all(isinstance(t, str) and t in SECURITY_TYPES for t in types)
            and len(set(types)) == len(types), "TIGER_SECURITY_TYPES_INVALID")
    return {"tool": query["tool"], "arguments": {"security_types": types} if allowed else {}}


def execute_query(n, profile, query, require, write_json, out):
    """Called only while the lease, profile lock and rotation callback are held."""
    if query["tool"] == "market_snapshot":
        from .market import execute_market_query
        return execute_market_query(n, profile, query, require, write_json, out)
    started = datetime.now(timezone.utc).isoformat()
    with n.profile_lock(profile):
        # Existing transferred grant includes quote consent. Preserve its exact
        # scope validation; this interface neither requests consent nor uses quotes.
        Session, make = n.sdk_classes(include_quotes=True)
        sdk = Session(issuer=n.ISSUER, home=str(profile), surface=n.SURFACE, client_name=n.CLIENT_NAME)
        n.validate_token(sdk.status(), require_quotes=True)
        broker = make(sdk)
        accounts = broker.get_managed_accounts()
        require(isinstance(accounts, list), "TIGER_ACCOUNTS_INVALID")
        standard = [a for a in accounts if getattr(a, "account_type", None) == "STANDARD"]
        require(len(standard) == 1, "STANDARD_ACCOUNT_AMBIGUOUS")
        refs = n.account_refs(profile, accounts)
        account = standard[0]
        pin = {"account": account.account, "ref": refs[account.account]}
        data = {}
        if query["tool"] in ("positions", "snapshot"):
            data["holdings"] = n.fetch_account(broker, pin, tuple(query["arguments"]["security_types"]))
        if query["tool"] in ("assets", "snapshot"):
            data["assets"] = n.fetch_assets_account(broker, pin)
        # Preserve partial evidence privately, but never call it a successful read.
        for name, payload in data.items():
            write_json(out / (name + ".json"), payload)
        require(all(p.get("ok") is True and p.get("sourceReadStatus") == "complete"
                    for p in data.values()), "TIGER_READ_INCOMPLETE")
        envelope = {"schema_version": 1, "provider": "tiger", "tool": query["tool"],
                    "query_started_at": started, "query_completed_at": datetime.now(timezone.utc).isoformat(),
                    "source_read_status": "complete", "cached_fallback_used": False,
                    "request": query, "data": data}
        # Original response timestamps, unknown quote times, scope evidence,
        # coverage limits and decimal strings stay in the normalized payloads.
        write_json(out / "query.json", envelope)
        result = {"status": "queried", "tool": query["tool"], "source_read_status": "complete",
                  "holdings_read": "holdings" in data, "assets_read": "assets" in data,
                  "files": [name + ".json" for name in data] + ["query.json"]}
        if "holdings" in data:
            result["holdings_count"] = len(data["holdings"]["positions"])
        return result
