"""Provider-neutral source inventory and attestation-request contract.

Tracked candidate records describe requirements, not accepted providers or data. This
module never downloads values, authenticates a source, or authorizes a real run.
"""
import hashlib
import json
import math
from pathlib import Path
import re

MAX_BYTES = 256 * 1024
ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,95}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
FORBIDDEN = re.compile(
    r"(?i)(api[_-]?key|client[_-]?secret|access[_-]?token|refresh[_-]?token|"
    r"auth[_-]?token|aws[_-]?access[_-]?key[_-]?id|aws[_-]?secret[_-]?access[_-]?key|"
    r"private[_-]?key|x-api-key|credential|session[_-]?cookie|\bcookie\b|\bsharpe\b|"
    r"password|bearer\s|sk-proj-|"
    r"\b(?:token|secret|key)[\"']?\s*[=:]\s*|/users/|/private/|"
    r"protected[_-]?(label|outcome|metric)|raw[_-]?(value|payload)|account[_-]?id)"
)

ROLES = ("real_yield", "credit_spread", "cash_rate", "spy_market", "oneq_market")
CANDIDATE_LIMITATIONS = [
    "selected-routes-disabled", "provider-unverified", "license-unverified",
    "availability-unverified", "no-values", "no-outcomes", "not-run-authorized",
]
SYNTHETIC_LIMITATIONS = [
    "fixture-only", "no-real-provider", "no-values", "no-outcomes",
    "not-run-authorized",
]
BLOCKERS = [
    "source-authority-unverified",
    "source-version-unverified",
    "vintage-history-unverified",
    "available-at-basis-unverified",
    "acquisition-receipts-unavailable",
    "license-unresolved",
    "redistribution-unresolved",
    "retention-unresolved",
    "calendar-authority-unresolved",
    "security-master-unresolved",
    "corporate-actions-unresolved",
    "executable-price-policy-unresolved",
    "total-return-policy-unresolved",
    "cost-policy-unresolved",
    "missingness-coverage-unverified",
    "provider-accounts-unprovisioned",
    "provider-api-access-unprovisioned",
    "provider-entitlements-unverified",
    "provider-orders-unverified",
    "provider-license-receipts-unavailable",
    "provider-retention-receipts-unavailable",
    "pit-route-receipts-unavailable",
]
ROUTE_FIELDS = {
    "route_alias", "role", "priority", "provider_id", "product_id", "series_id",
    "endpoint_id", "schema_id", "pit_method", "security_identity_policy",
    "effective_interval_policy", "mapping_version_policy", "event_identity_policy",
    "correction_policy", "cancellation_policy", "version_selection_policy",
    "price_adjustment", "dividend_reinvestment_policy",
    "total_return_formula_version", "admissibility", "rights_codes", "blockers",
    "account_receipt_sha256", "api_access_receipt_sha256", "order_receipt_sha256",
    "entitlement_receipt_sha256", "license_receipt_sha256",
    "retention_receipt_sha256", "pit_receipt_sha256",
}
ROUTE_RECEIPT_FIELDS = (
    "account_receipt_sha256", "api_access_receipt_sha256", "order_receipt_sha256",
    "entitlement_receipt_sha256", "license_receipt_sha256",
    "retention_receipt_sha256", "pit_receipt_sha256",
)
ENTRY_FIELDS = {
    "inventory_alias", "role", "provider_routes", "source_kind", "entity_scope",
    "unit", "frequency",
    "revision_policy", "source_authority_id", "source_version",
    "vintage_history_complete", "vintage_history_receipt_sha256",
    "available_at_basis", "available_at_receipt_sha256",
    "acquisition_receipt_sha256", "license_id", "redistribution",
    "retention_policy_id", "calendar_id", "calendar_attestation_sha256",
    "security_master_id", "security_master_attestation_sha256",
    "corporate_action_policy_id", "executable_price_policy_id",
    "total_return_policy_id", "cost_policy_id", "missingness_policy_id",
    "missingness_coverage_receipt_sha256",
}
INVENTORY_FIELDS = {
    "schema_version", "kind", "inventory_id", "version", "trust_class",
    "status", "structural_ready", "real_ready", "entries", "blockers",
    "limitations",
}
REQUEST_FIELDS = {
    "schema_version", "kind", "purpose", "inventory_sha256", "trust_class",
    "requested_roles", "required_receipt_fields", "status", "real_ready",
    "blockers",
}
REQUIRED_RECEIPT_FIELDS = [
    "source_authority_id", "provider_id", "product_id", "series_id",
    "source_version", "vintage_history_complete", "vintage_history_receipt_sha256",
    "available_at_basis", "available_at_receipt_sha256",
    "acquisition_receipt_sha256", "license_id", "redistribution",
    "retention_policy_id", "calendar_id", "calendar_attestation_sha256",
    "security_master_id", "security_master_attestation_sha256",
    "corporate_action_policy_id", "executable_price_policy_id",
    "total_return_policy_id", "cost_policy_id", "missingness_policy_id",
    "missingness_coverage_receipt_sha256", "raw_identity_sha256",
    "normalized_identity_sha256",
]
ROLE_SEMANTICS = {
    "real_yield": {
        "source_kind": "macro",
        "entity_scope": "global", "unit": "percent", "frequency": "daily",
        "revision_policy": "revisable",
    },
    "credit_spread": {
        "source_kind": "macro",
        "entity_scope": "global", "unit": "percent", "frequency": "daily",
        "revision_policy": "revisable",
    },
    "cash_rate": {
        "source_kind": "cash",
        "entity_scope": "global", "unit": "percent", "frequency": "daily",
        "revision_policy": "revisable",
    },
    "spy_market": {
        "source_kind": "market", "entity_scope": "instrument",
        "unit": "usd", "frequency": "session", "revision_policy": "revisable",
    },
    "oneq_market": {
        "source_kind": "market", "entity_scope": "instrument",
        "unit": "usd", "frequency": "session", "revision_policy": "revisable",
    },
}
ROUTE_SEMANTIC_FIELDS = ROUTE_FIELDS - {"route_alias"} - set(ROUTE_RECEIPT_FIELDS)
COMMON_ROUTE_BLOCKERS = [
    "account-unprovisioned", "api-access-receipt-unavailable",
    "entitlement-unverified", "order-receipt-unavailable",
    "license-receipt-unavailable", "retention-receipt-unavailable",
    "pit-receipt-unavailable",
]
SELECTED_ROUTES = {
    "real_yield": [
        {"priority": "primary", "provider_id": "fred", "product_id": "fred-alfred",
         "series_id": "dfii5", "endpoint_id": "fred-series-observations",
         "schema_id": "fred-vintage-observations-v1",
         "pit_method": "alfred-vintage-realtime-intervals",
         "identifier_policy": "not-applicable", "price_adjustment": "not-applicable",
         "admissibility": "selected-disabled",
         "rights_codes": ["terms-confirmation-required", "attribution-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["alfred-vintage-conformance-unverified"]},
        {"priority": "fallback", "provider_id": "federal-reserve-board",
         "product_id": "h15-ddp", "series_id": "dfii5",
         "endpoint_id": "h15-ddp-values", "schema_id": "h15-ddp-v1",
         "pit_method": "contemporaneous-capture-required",
         "identifier_policy": "not-applicable", "price_adjustment": "not-applicable",
         "admissibility": "fallback-disabled",
         "rights_codes": ["fallback-only", "contemporaneous-capture-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["contemporaneous-capture-archive-unavailable"]},
    ],
    "credit_spread": [
        {"priority": "primary", "provider_id": "fred", "product_id": "alfred-ice-bofa",
         "series_id": "bamlc0a0cm", "endpoint_id": "fred-series-observations",
         "schema_id": "fred-vintage-observations-v1",
         "pit_method": "alfred-vintage-realtime-intervals",
         "identifier_policy": "not-applicable", "price_adjustment": "not-applicable",
         "admissibility": "selected-disabled",
         "rights_codes": ["internal-research-only", "no-redistribution", "ice-license-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["ice-rights-confirmation-unavailable"]},
        {"priority": "fallback", "provider_id": "ice",
         "product_id": "consolidated-history", "series_id": "bamlc0a0cm",
         "endpoint_id": "ice-consolidated-history", "schema_id": "ice-index-history-v1",
         "pit_method": "licensed-vintage-history",
         "identifier_policy": "not-applicable", "price_adjustment": "not-applicable",
         "admissibility": "fallback-disabled",
         "rights_codes": ["licensed-entitlement-required", "internal-research-only", "no-redistribution"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["ice-direct-entitlement-unavailable"]},
    ],
    "cash_rate": [
        {"priority": "primary", "provider_id": "fred", "product_id": "fred-alfred",
         "series_id": "dff", "endpoint_id": "fred-series-observations",
         "schema_id": "fred-vintage-observations-v1",
         "pit_method": "alfred-vintage-realtime-intervals",
         "identifier_policy": "not-applicable", "price_adjustment": "not-applicable",
         "admissibility": "selected-disabled",
         "rights_codes": ["terms-confirmation-required", "attribution-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["alfred-vintage-conformance-unverified"]},
        {"priority": "fallback", "provider_id": "new-york-fed",
         "product_id": "markets-data-api", "series_id": "effr",
         "endpoint_id": "nyfed-markets-reference-rates", "schema_id": "nyfed-effr-v1",
         "pit_method": "contemporaneous-archive-required",
         "identifier_policy": "not-applicable", "price_adjustment": "not-applicable",
         "admissibility": "fallback-disabled",
         "rights_codes": ["fallback-only", "contemporaneous-archive-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["contemporaneous-archive-unavailable"]},
    ],
    "spy_market": [],
    "oneq_market": [],
}
for _role, _symbol in (("spy_market", "spy"), ("oneq_market", "oneq")):
    SELECTED_ROUTES[_role] = [
        {"priority": "primary", "provider_id": "databento", "product_id": "equs-mini",
         "series_id": _symbol, "endpoint_id": "databento-timeseries-and-reference",
         "schema_id": "ohlcv-1d-unadjusted-plus-pit-actions-v1",
         "pit_method": "versioned-pit-corporate-actions",
         "identifier_policy": "pit-security-master-no-ticker-splice",
         "price_adjustment": "unadjusted-only", "admissibility": "selected-disabled",
         "rights_codes": ["contract-confirmation-required", "unadjusted-bars-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["databento-contract-confirmation-unavailable", "corporate-action-pit-conformance-unverified"]},
        {"priority": "fallback", "provider_id": "massive", "product_id": "stocks",
         "series_id": _symbol, "endpoint_id": "massive-aggregates-dividends-splits",
         "schema_id": "massive-unadjusted-actions-v1",
         "pit_method": "archive-or-correction-feed-required",
         "identifier_policy": "pit-security-master-no-ticker-splice",
         "price_adjustment": "unadjusted-only", "admissibility": "fallback-disabled",
         "rights_codes": ["commercial-terms-required", "cache-deletion-required", "unadjusted-bars-required"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["massive-commercial-terms-unverified", "massive-cache-deletion-unverified", "correction-feed-or-archive-unavailable"]},
        {"priority": "cross-check", "provider_id": "tiger", "product_id": "openapi-quote-corp-action",
         "series_id": _symbol, "endpoint_id": "tiger-stock-quote-and-corp-action",
         "schema_id": "tiger-operational-cross-check-v1", "pit_method": "not-pit-admissible",
         "identifier_policy": "pit-security-master-no-ticker-splice",
         "price_adjustment": "unadjusted-only", "admissibility": "cross-check-only",
         "rights_codes": ["cross-check-only", "not-pit-admissible", "no-research-admission"],
         "blockers": COMMON_ROUTE_BLOCKERS + ["tiger-retention-redistribution-unverified", "not-pit-admissible"]},
    ]
for _role, _routes in SELECTED_ROUTES.items():
    for _route in _routes:
        _route["role"] = _role
        _route.pop("identifier_policy", None)
        if _role in {"spy_market", "oneq_market"}:
            _route.update({
                "security_identity_policy": "provider-native-listing-id-required",
                "effective_interval_policy": "effective-start-end-required",
                "mapping_version_policy": "mapping-version-required",
                "event_identity_policy": ("event-unique-id-required" if _route["provider_id"] == "databento"
                                          else "provider-event-or-archive-hash-required"),
                "correction_policy": ("ts-record-correction-chain" if _route["provider_id"] == "databento"
                                      else "correction-feed-or-archive-required"),
                "cancellation_policy": ("ts-record-cancel-excludes-event" if _route["provider_id"] == "databento"
                                        else "cancellation-history-required"),
                "version_selection_policy": ("max-ts-record-per-event-as-of-cutoff" if _route["provider_id"] == "databento"
                                             else "archive-as-of-cutoff-required"),
                "dividend_reinvestment_policy": "effective-date-next-close-reinvestment-v1",
                "total_return_formula_version": "pit-total-return-log-v1",
            })
            if _route["provider_id"] == "tiger":
                _route.update({key: "not-pit-admissible" for key in (
                    "effective_interval_policy", "mapping_version_policy",
                    "event_identity_policy", "correction_policy",
                    "cancellation_policy", "version_selection_policy",
                    "dividend_reinvestment_policy", "total_return_formula_version")})
                _route["blockers"] += ["tiger-action-revision-history-unavailable",
                                       "tiger-contemporaneous-archive-unavailable"]
        else:
            _route.update({
                "security_identity_policy": "not-applicable",
                "effective_interval_policy": "not-applicable",
                "mapping_version_policy": "not-applicable",
                "event_identity_policy": "not-applicable",
                "correction_policy": "not-applicable",
                "cancellation_policy": "not-applicable",
                "version_selection_policy": "not-applicable",
                "dividend_reinvestment_policy": "not-applicable",
                "total_return_formula_version": "not-applicable",
            })
UNRESOLVED_FIELDS = (
    "source_authority_id", "source_version", "vintage_history_complete",
    "vintage_history_receipt_sha256", "available_at_basis",
    "available_at_receipt_sha256", "acquisition_receipt_sha256", "license_id",
    "redistribution", "retention_policy_id", "calendar_id",
    "calendar_attestation_sha256", "security_master_id",
    "security_master_attestation_sha256", "corporate_action_policy_id",
    "executable_price_policy_id", "total_return_policy_id", "cost_policy_id",
    "missingness_policy_id", "missingness_coverage_receipt_sha256",
)
RECEIPT_IDENTITY_FIELDS = (
    "provider_id", "product_id", "series_id", "raw_identity_sha256",
    "normalized_identity_sha256",
)


class InventoryError(ValueError):
    """Stable rejection without provider/private diagnostics."""


def require(condition, code):
    if not condition:
        raise InventoryError(code)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "SOURCE_INVENTORY_DUPLICATE_KEY")
        result[key] = value
    return result


def loads_strict(raw):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES,
            "SOURCE_INVENTORY_JSON_SIZE")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(
                              InventoryError("SOURCE_INVENTORY_NONFINITE")))
    except InventoryError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise InventoryError("SOURCE_INVENTORY_JSON_INVALID") from None


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise InventoryError("SOURCE_INVENTORY_JSON_INVALID") from None


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _strict(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)
    return value


def _id(value, code="SOURCE_INVENTORY_ID_INVALID"):
    require(type(value) is str and ID.fullmatch(value), code)
    return value


def _sha(value, code="SOURCE_INVENTORY_SHA_INVALID"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _scan(value):
    text = canonical(value).decode("ascii")
    require(FORBIDDEN.search(text) is None, "SOURCE_INVENTORY_SENSITIVE_CONTENT")


def _same_typed(value, expected):
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return set(value) == set(expected) and all(
            _same_typed(value[key], expected[key]) for key in expected)
    if isinstance(expected, list):
        return len(value) == len(expected) and all(
            _same_typed(left, right) for left, right in zip(value, expected))
    return value == expected


def _validate_limitations(value, trust_class):
    expected = (CANDIDATE_LIMITATIONS if trust_class == "candidate_real"
                else SYNTHETIC_LIMITATIONS)
    require(_same_typed(value, expected), "SOURCE_INVENTORY_LIMITATIONS_INVALID")
    _scan(value)


def _route_semantic(route):
    return {key: route[key] for key in sorted(ROUTE_SEMANTIC_FIELDS)}


def _validate_route(route, role, trust_class):
    _strict(route, ROUTE_FIELDS, "SOURCE_INVENTORY_ROUTE_SCHEMA")
    alias = _id(route["route_alias"], "SOURCE_INVENTORY_ROUTE_ALIAS")
    if trust_class == "candidate_real":
        require(all(route[key] is None for key in ROUTE_RECEIPT_FIELDS),
                "SOURCE_INVENTORY_ROUTE_RECEIPT_MUST_BE_NULL")
        require(type(route["rights_codes"]) is list and route["rights_codes"] and
                type(route["blockers"]) is list and route["blockers"],
                "SOURCE_INVENTORY_ROUTE_POLICY_INVALID")
    else:
        market = role in {"spy_market", "oneq_market"}
        expected = {
            "role": role, "priority": "primary", "provider_id": "synthetic-provider",
            "product_id": "synthetic-fixture", "series_id": "synthetic-" + role,
            "endpoint_id": "synthetic-endpoint", "schema_id": "synthetic-schema-v1",
            "pit_method": "synthetic-known-at",
            "security_identity_policy": ("provider-native-listing-id-required"
                                         if market else "not-applicable"),
            "effective_interval_policy": ("effective-start-end-required"
                                          if market else "not-applicable"),
            "mapping_version_policy": ("mapping-version-required"
                                       if market else "not-applicable"),
            "event_identity_policy": ("event-unique-id-required"
                                      if market else "not-applicable"),
            "correction_policy": ("ts-record-correction-chain"
                                  if market else "not-applicable"),
            "cancellation_policy": ("ts-record-cancel-excludes-event"
                                    if market else "not-applicable"),
            "version_selection_policy": ("max-ts-record-per-event-as-of-cutoff"
                                         if market else "not-applicable"),
            "price_adjustment": ("unadjusted-only" if market else "not-applicable"),
            "dividend_reinvestment_policy": ("effective-date-next-close-reinvestment-v1"
                                             if market else "not-applicable"),
            "total_return_formula_version": ("pit-total-return-log-v1"
                                             if market else "not-applicable"),
            "admissibility": "fixture-only", "rights_codes": ["synthetic-only"],
            "blockers": [],
        }
        require(_same_typed(_route_semantic(route), expected),
                "SOURCE_INVENTORY_SYNTHETIC_ROUTE_INVALID")
        for key in ROUTE_RECEIPT_FIELDS:
            _sha(route[key], "SOURCE_INVENTORY_SYNTHETIC_ROUTE_INVALID")
    return alias


def _validate_entry(entry, trust_class):
    _strict(entry, ENTRY_FIELDS, "SOURCE_INVENTORY_ENTRY_SCHEMA")
    alias = _id(entry["inventory_alias"])
    role = entry["role"]
    require(role in ROLES, "SOURCE_INVENTORY_ROLE_INVALID")
    expected = ROLE_SEMANTICS[role]
    for key, expected_value in expected.items():
        require(_same_typed(entry[key], expected_value),
                "SOURCE_INVENTORY_ROLE_SEMANTICS_DRIFT")
    routes = entry["provider_routes"]
    require(type(routes) is list and routes, "SOURCE_INVENTORY_ROUTE_ROSTER")
    route_aliases = set()
    for route in routes:
        route_alias = _validate_route(route, role, trust_class)
        require(route_alias not in route_aliases, "SOURCE_INVENTORY_ROUTE_DUPLICATE")
        route_aliases.add(route_alias)
    if trust_class == "candidate_real":
        expected_routes = SELECTED_ROUTES[role]
        actual_semantics = sorted((_route_semantic(route) for route in routes),
                                  key=canonical)
        require(actual_semantics == sorted(expected_routes, key=canonical),
                "SOURCE_INVENTORY_SELECTED_ROUTE_DRIFT")
        require(all(entry[key] is None for key in UNRESOLVED_FIELDS),
                "SOURCE_INVENTORY_GUESSED_EVIDENCE")
    elif trust_class == "synthetic_fixture":
        require(len(routes) == 1, "SOURCE_INVENTORY_SYNTHETIC_ROUTE_INVALID")
        for key in ("source_authority_id", "source_version", "available_at_basis",
                    "license_id", "redistribution", "retention_policy_id",
                    "calendar_id", "security_master_id", "corporate_action_policy_id",
                    "executable_price_policy_id", "total_return_policy_id",
                    "cost_policy_id", "missingness_policy_id"):
            _id(entry[key], "SOURCE_INVENTORY_SYNTHETIC_FIELD")
        require(entry["vintage_history_complete"] is True,
                "SOURCE_INVENTORY_SYNTHETIC_FIELD")
        for key in ("vintage_history_receipt_sha256", "available_at_receipt_sha256",
                    "acquisition_receipt_sha256", "calendar_attestation_sha256",
                    "security_master_attestation_sha256",
                    "missingness_coverage_receipt_sha256"):
            _sha(entry[key], "SOURCE_INVENTORY_SYNTHETIC_FIELD")
    else:
        raise InventoryError("SOURCE_INVENTORY_TRUST_CLASS")
    return alias, role


def validate_inventory(value):
    _strict(value, INVENTORY_FIELDS, "SOURCE_INVENTORY_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_source_inventory" and
            type(value["version"]) is int and value["version"] == 1,
            "SOURCE_INVENTORY_VERSION")
    _id(value["inventory_id"])
    trust_class = value["trust_class"]
    require(trust_class in {"candidate_real", "synthetic_fixture"},
            "SOURCE_INVENTORY_TRUST_CLASS")
    require(value["real_ready"] is False, "SOURCE_INVENTORY_REAL_READY_FORBIDDEN")
    require(type(value["entries"]) is list and len(value["entries"]) == len(ROLES),
            "SOURCE_INVENTORY_ROSTER")
    aliases = set(); roles = set()
    for entry in value["entries"]:
        alias, role = _validate_entry(entry, trust_class)
        require(alias not in aliases and role not in roles, "SOURCE_INVENTORY_DUPLICATE")
        aliases.add(alias); roles.add(role)
    require(roles == set(ROLES), "SOURCE_INVENTORY_ROSTER")
    if trust_class == "candidate_real":
        require(value["status"] == "selected_disabled_unverified" and
                value["structural_ready"] is False and value["blockers"] == BLOCKERS,
                "SOURCE_INVENTORY_BLOCKERS")
    else:
        require(value["status"] == "synthetic_fixture" and
                value["structural_ready"] is True and value["blockers"] == [],
                "SOURCE_INVENTORY_SYNTHETIC_STATUS")
    _validate_limitations(value["limitations"], trust_class)
    _scan(value)
    return value


def semantic_inventory(value):
    value = validate_inventory(value)
    entries = []
    for item in value["entries"]:
        semantic = {key: item[key] for key in sorted(
            ENTRY_FIELDS - {"inventory_alias", "provider_routes"})}
        semantic["provider_routes"] = sorted(
            (_route_semantic(route) for route in item["provider_routes"]), key=canonical)
        entries.append(semantic)
    return {
        "schema_version": value["schema_version"],
        "kind": value["kind"],
        "trust_class": value["trust_class"],
        "entries": sorted(entries, key=lambda item: item["role"]),
    }


def inventory_sha256(value):
    return digest(semantic_inventory(value))


def create_attestation_request(inventory):
    inventory = validate_inventory(inventory)
    synthetic = inventory["trust_class"] == "synthetic_fixture"
    request = {
        "schema_version": 1,
        "kind": "factor_source_attestation_request",
        "purpose": "pit-factor-data-attestation",
        "inventory_sha256": inventory_sha256(inventory),
        "trust_class": inventory["trust_class"],
        "requested_roles": list(ROLES),
        "required_receipt_fields": list(REQUIRED_RECEIPT_FIELDS),
        "status": "fixture_only" if synthetic else "blocked",
        "real_ready": False,
        "blockers": [] if synthetic else list(BLOCKERS),
    }
    return validate_attestation_request(request)


def validate_attestation_request(value):
    _strict(value, REQUEST_FIELDS, "SOURCE_ATTESTATION_REQUEST_SCHEMA")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and
            value["kind"] == "factor_source_attestation_request" and
            value["purpose"] == "pit-factor-data-attestation" and
            value["requested_roles"] == list(ROLES) and
            value["required_receipt_fields"] == REQUIRED_RECEIPT_FIELDS and
            value["real_ready"] is False,
            "SOURCE_ATTESTATION_REQUEST_INVALID")
    _sha(value["inventory_sha256"])
    if value["trust_class"] == "candidate_real":
        require(value["status"] == "blocked" and value["blockers"] == BLOCKERS,
                "SOURCE_ATTESTATION_REQUEST_BLOCKED")
    elif value["trust_class"] == "synthetic_fixture":
        require(value["status"] == "fixture_only" and value["blockers"] == [],
                "SOURCE_ATTESTATION_REQUEST_FIXTURE")
    else:
        raise InventoryError("SOURCE_ATTESTATION_REQUEST_TRUST")
    _scan(value)
    return value


def load_inventory(path):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError:
        raise InventoryError("SOURCE_INVENTORY_FILE_UNAVAILABLE") from None
    return validate_inventory(loads_strict(raw))
