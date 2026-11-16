"""Provider-free validation for the live acquisition readiness packet.

A valid seal proves only that a repository-derived packet is unchanged. Readiness
also requires every operational field and equivalence review to be complete.
Neither result is provider, source-quality, or investment-alpha evidence.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from shared.research_sources.acquisition_contracts import EffectiveConfigInputs


VERSION_V1 = "live-provider-readiness-1"
VERSION_V2 = "live-provider-readiness-2"
VERSION = "live-provider-readiness-3"
CASE_PACKET_VERSION = "live-provider-case-packet-1"
CASE_PACKET_PATH = "tuning/evals/information_fetch/live_e2e/readiness-case-packet.json"
ROOT = Path(__file__).resolve().parents[4]
_REQUIRED_BUDGETS = {
    "smoke": {
        "search_items": 1, "open_items": 0, "provider_items": 1,
        "fallbacks": 0, "concurrency": 1, "cache_enabled": False,
        "raw_result_limit_bytes": 65536,
    },
    "narrow": {
        "search_items": 1, "open_items": 2, "provider_items": 3,
        "fallbacks": 1, "concurrency": 1, "cache_enabled": False,
        "raw_result_limit_bytes": 65536,
    },
}
REQUIRED_BUDGET = _REQUIRED_BUDGETS["narrow"]
FORBIDDEN_KEYS = frozenset({"quote", "selectedquote", "quotetext", "selectedquotetext"})
_SHA256 = re.compile(r"[a-f0-9]{64}")
_REQUIRED_STOPS = frozenset({
    "no_find", "no_second_query", "no_unchanged_retry", "no_second_alternate",
    "no_provider_switch", "no_curl_substitution", "stop_on_unknown_outcome",
    "stop_on_policy_transient_circuit_or_post_dispatch_deadline",
})
# Each readiness input has one reviewed repository owner.  A caller may update the
# hash for a changed candidate, but cannot substitute an unrelated unchanged file.
_CANONICAL_EFFECTIVE_CONFIG_PATHS = {
    "runner": "investment/research/acquisition_runner.py",
    "driver": "investment/research/acquisition_driver.py",
    "controller": "investment/research/acquisition_orchestration.py",
    "host_web": "shared/research_sources/host_web.py",
    "cache_store": "shared/research_sources/cache.py",
    "taxonomy": "shared/research_sources/acquisition_contracts.py",
    "alternate_policy": "investment/research/acquisition_orchestration.py",
    "evidence_schemas": "tuning/evals/information_fetch/live_e2e/readiness.schema.json",
    "checker": "investment/research/acquisition_trace.py",
    "projection": "investment/research/acquisition_projection.py",
    "backend_model_config": ".job-runtime/config/runtime.json",
    "runtime_interpreter": ".research-sources/.venv/pyvenv.cfg",
    "case_packet": CASE_PACKET_PATH,
    "budgets_deadlines": "docs/plans/live-provider-acquisition-e2e.md",
    "retention_gc_policy": "docs/deployment/acquisition-live-e2e.md",
    "rollback_target": "docs/deployment/acquisition-live-e2e.md",
    "acceptance_policy": "docs/deployment/runtime-acceptance.md",
}

_PACKET_KEYS = frozenset({"schema_version", "run_kind", "status", "question_contract",
    "case", "equivalence_review", "url_policy", "source_contract", "budgets",
    "stop_rules", "identity_rules", "artifacts", "repository_evidence",
    "effective_config", "prohibitions", "limitations", "unresolved"})
_QUESTION_KEYS = frozenset({"id", "facet", "evidence_to_seek", "source_roles",
    "capability_ids", "depends_on", "priority", "stop_rule"})
_CASE_KEYS = frozenset({"case_id", "issuer_id", "canonical_disclosure_id", "question",
    "search_query", "primary_pdf_url", "alternate_html_url", "selection_bias",
    "quote_preselected"})
_REVIEW_KEYS = frozenset({"status", "reviewer_id", "rationale", "caveat",
    "disclosure_date_match", "publisher_control", "release_identity_match",
    "representation_relationship", "title_match"})
_URL_POLICY_KEYS = frozenset({"normalization", "redirects", "allowed_hosts"})
_SOURCE_KEYS = frozenset({"cutoff", "evidence_facet", "required_access_level",
    "required_capability", "source_role", "eligible_body_rules",
    "eligible_pdf_failure_codes", "unparseable_predeclared"})
_BUDGET_KEYS = frozenset({"search_items", "open_items", "provider_items", "fallbacks",
    "concurrency", "cache_enabled", "raw_result_limit_bytes", "run_wall_seconds",
    "provider_call_seconds"})
_IDENTITY_KEYS = frozenset({"experiment_id", "execution_id", "trace_id", "operation_id",
    "attempt_id", "dispatch_id"})
_ARTIFACT_KEYS = frozenset({"artifact_root", "runtime_root", "artifact_root_mode",
    "raw_retention", "reconciliation_owner", "retention_owner", "rollback_target"})
_EFFECTIVE_KEYS = frozenset({"required_inputs", "inputs", "sha256"})
_REF_KEYS = frozenset({"path", "sha256"})
_CASE_PACKET_KEYS = frozenset({"schema_version", "question_contract", "case",
    "equivalence_review", "url_policy", "source_contract"})
_VALIDATED_READY: dict[str, tuple[int, dict[str, Any]]] = {}
_MAX_VALIDATED_READY = 64
_MAX_LIST_ITEMS = 64
_MAX_LIST_TEXT = 2048


class ReadinessError(ValueError):
    pass


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise ReadinessError(code)


def _closed(value: Any, keys: frozenset[str], code: str) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == keys, code)
    return value


def _canonical_relative(value: Any, code: str) -> str:
    _require(isinstance(value, str) and value and "\\" not in value
             and not value.startswith("/") and not value.endswith("/")
             and all(part not in {"", ".", ".."} for part in value.split("/")), code)
    return value


def _safe_list_text(value: str, *, allow_private_label: bool = False) -> bool:
    lowered = value.lower()
    forbidden = ("self_reference", "../", ".research-sources/", "niulai-private/",
                 "/users/", "access_token", "access-token", "api_key", "api-key",
                 "password", "bearer ", "sk-", "github_pat_", "ghp_", "gho_",
                 "ghu_", "ghs_", "ghr_")
    if allow_private_label and lowered == "niulai_private":
        return True
    return ("\x00" not in value and "\\" not in value and not value.startswith("/")
            and not any(marker in lowered for marker in forbidden))


def _bounded_strings(value: Any, code: str, *, minimum: int,
                     maximum: int = _MAX_LIST_ITEMS, unique: bool = False,
                     allow_private_label: bool = False) -> list[str]:
    _require(isinstance(value, list) and minimum <= len(value) <= maximum
             and all(isinstance(item, str) and 0 < len(item) <= _MAX_LIST_TEXT
                     and _safe_list_text(item, allow_private_label=allow_private_label)
                     for item in value), code)
    if unique:
        _require(len(set(value)) == len(value), code)
    return value


def _validate_v3_lists(packet: dict[str, Any]) -> None:
    _bounded_strings(packet.get("prohibitions"), "READINESS_PROHIBITIONS_INVALID",
                     minimum=1, unique=True, allow_private_label=True)
    _bounded_strings(packet.get("limitations"), "READINESS_LIMITATIONS_INVALID",
                     minimum=1)
    stops = _bounded_strings(packet.get("stop_rules"), "READINESS_STOP_RULES_INVALID",
                             minimum=len(_REQUIRED_STOPS), maximum=len(_REQUIRED_STOPS),
                             unique=True)
    _require(set(stops) == _REQUIRED_STOPS, "READINESS_STOP_RULES_INVALID")


def _validate_v3_shape(packet: dict[str, Any]) -> None:
    _closed(packet, _PACKET_KEYS, "READINESS_PACKET_SHAPE_INVALID")
    _closed(packet.get("question_contract"), _QUESTION_KEYS, "READINESS_QUESTION_CONTRACT_INVALID")
    _closed(packet.get("case"), _CASE_KEYS, "READINESS_CASE_INVALID")
    _closed(packet.get("equivalence_review"), _REVIEW_KEYS, "READINESS_EQUIVALENCE_INVALID")
    _closed(packet.get("url_policy"), _URL_POLICY_KEYS, "READINESS_URL_POLICY_INVALID")
    _closed(packet.get("source_contract"), _SOURCE_KEYS, "READINESS_SOURCE_CONTRACT_INVALID")
    _closed(packet.get("budgets"), _BUDGET_KEYS, "READINESS_BUDGET_INVALID")
    _closed(packet.get("identity_rules"), _IDENTITY_KEYS, "READINESS_IDENTITY_RULES_INVALID")
    _closed(packet.get("artifacts"), _ARTIFACT_KEYS, "READINESS_ARTIFACTS_INVALID")
    effective = _closed(packet.get("effective_config"), _EFFECTIVE_KEYS,
                        "READINESS_EFFECTIVE_CONFIG_INVALID")
    _require(isinstance(effective.get("inputs"), dict)
             and all(isinstance(row, dict) and set(row) == _REF_KEYS
                     for row in effective["inputs"].values()),
             "READINESS_EFFECTIVE_CONFIG_INVALID")
    _require(isinstance(packet.get("repository_evidence"), list)
             and all(isinstance(row, dict) and set(row) == _REF_KEYS
                     for row in packet["repository_evidence"]),
             "READINESS_EVIDENCE_INVALID")


def _remember_ready(packet: dict[str, Any], contract: dict[str, Any]) -> None:
    packet_sha = hashlib.sha256(canonical_bytes(packet)).hexdigest()
    _VALIDATED_READY.clear()
    _VALIDATED_READY[packet_sha] = (1, contract)


def _consume_ready(packet: dict[str, Any]) -> dict[str, Any]:
    packet_sha = hashlib.sha256(canonical_bytes(packet)).hexdigest()
    receipt = _VALIDATED_READY.get(packet_sha)
    if receipt is None:
        _VALIDATED_READY.clear()
        raise ReadinessError("READINESS_NOT_VALIDATED")
    count, contract = receipt
    if count == 1:
        del _VALIDATED_READY[packet_sha]
    else:
        _VALIDATED_READY[packet_sha] = (count - 1, contract)
    return contract


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError) as error:
        raise ReadinessError("READINESS_JSON_INVALID") from error


def seal_packet(packet: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(packet, dict), "READINESS_PACKET_INVALID")
    return {"packet": packet, "seal": {"algorithm": "sha256",
        "packet_sha256": hashlib.sha256(canonical_bytes(packet)).hexdigest()}}


def case_packet_projection(packet: dict[str, Any]) -> dict[str, Any]:
    """Return the stable semantic case input, excluding runtime-owned values."""
    _require(isinstance(packet, dict), "READINESS_CASE_PACKET_INVALID")
    required = ("question_contract", "case", "equivalence_review", "url_policy",
                "source_contract")
    _require(all(isinstance(packet.get(key), dict) for key in required),
             "READINESS_CASE_PACKET_INVALID")
    source = {key: value for key, value in packet["source_contract"].items()
              if key != "cutoff"}
    return {"schema_version": CASE_PACKET_VERSION,
            "question_contract": packet["question_contract"],
            "case": packet["case"],
            "equivalence_review": packet["equivalence_review"],
            "url_policy": packet["url_policy"],
            "source_contract": source}


def seal_case_packet(case_packet: dict[str, Any]) -> dict[str, Any]:
    _require(isinstance(case_packet, dict)
             and case_packet.get("schema_version") == CASE_PACKET_VERSION,
             "READINESS_CASE_PACKET_INVALID")
    return {"case_packet": case_packet, "seal": {"algorithm": "sha256",
        "case_packet_sha256": hashlib.sha256(canonical_bytes(case_packet)).hexdigest()}}


def validate_case_packet_envelope(value: Any) -> dict[str, Any]:
    """Validate a sealed semantic case packet without trusting stored hashes."""
    _require(isinstance(value, dict) and set(value) == {"case_packet", "seal"},
             "READINESS_CASE_PACKET_INVALID")
    case_packet, seal = value["case_packet"], value["seal"]
    _require(isinstance(case_packet, dict)
             and set(case_packet) == _CASE_PACKET_KEYS
             and case_packet.get("schema_version") == CASE_PACKET_VERSION
             and isinstance(seal, dict)
             and set(seal) == {"algorithm", "case_packet_sha256"}
             and seal.get("algorithm") == "sha256"
             and seal.get("case_packet_sha256") == hashlib.sha256(
                 canonical_bytes(case_packet)).hexdigest()
             and not _contains_forbidden_key(case_packet),
             "READINESS_CASE_PACKET_INVALID")
    _closed(case_packet["question_contract"], _QUESTION_KEYS,
            "READINESS_CASE_PACKET_INVALID")
    _closed(case_packet["case"], _CASE_KEYS, "READINESS_CASE_PACKET_INVALID")
    _closed(case_packet["equivalence_review"], _REVIEW_KEYS,
            "READINESS_CASE_PACKET_INVALID")
    _closed(case_packet["url_policy"], _URL_POLICY_KEYS,
            "READINESS_CASE_PACKET_INVALID")
    _closed(case_packet["source_contract"], _SOURCE_KEYS - {"cutoff"},
            "READINESS_CASE_PACKET_INVALID")
    return value


def _case_packet_envelope(root: Path, row: dict[str, str]) -> dict[str, Any]:
    _repository_file(root, row, "READINESS_CASE_PACKET_INVALID",
                     expected_path=CASE_PACKET_PATH)
    path = root / row["path"]
    try:
        value = json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError) as error:
        raise ReadinessError("READINESS_CASE_PACKET_INVALID") from error
    return validate_case_packet_envelope(value)

def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        normalized = {re.sub(r"[^a-z0-9]", "", str(key).lower()) for key in value}
        return bool(FORBIDDEN_KEYS & normalized) or any(_contains_forbidden_key(v) for v in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_key(v) for v in value)
    return False


def _canonical_https_url(value: Any, allowed_hosts: set[str]) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname in allowed_hosts
                and parsed.username is None and parsed.password is None
                and not parsed.fragment and parsed.path.startswith("/")
                and urlunsplit(parsed) == value)
    except ValueError:
        return False


def _repository_file(root: Path, row: Any, code: str, *, expected_path: str | None = None) -> str:
    _require(isinstance(row, dict) and set(row) == _REF_KEYS
             and _SHA256.fullmatch(str(row.get("sha256"))) is not None, code)
    _canonical_relative(row["path"], code)
    if expected_path is not None:
        _require(row["path"] == expected_path, code)
    path = root / row["path"]
    _require(path.is_file() and not path.is_symlink()
             and path.resolve().is_relative_to(root), code)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    _require(actual == row["sha256"], code)
    return actual


def canonical_effective_config(root: Path = ROOT) -> dict[str, Any]:
    """Build the only accepted name-to-candidate-path seal for this checkout."""
    root = root.resolve()
    names = [name[:-7] for name in EffectiveConfigInputs.__dataclass_fields__
             if name.endswith("_sha256")]
    _require(set(names) == set(_CANONICAL_EFFECTIVE_CONFIG_PATHS),
             "READINESS_EFFECTIVE_CONFIG_DEFINITION_INVALID")
    rows = {}
    hashes = {}
    for name in names:
        relative = _CANONICAL_EFFECTIVE_CONFIG_PATHS[name]
        path = root / relative
        _require(path.is_file() and not path.is_symlink()
                 and path.resolve().is_relative_to(root),
                 "READINESS_EFFECTIVE_CONFIG_INVALID")
        value = hashlib.sha256(path.read_bytes()).hexdigest()
        rows[name] = {"path": relative, "sha256": value}
        hashes[f"{name}_sha256"] = value
    inputs = EffectiveConfigInputs(**hashes)
    return {"required_inputs": names, "inputs": rows,
            "sha256": hashlib.sha256(canonical_bytes(asdict(inputs))).hexdigest()}


def _question_contract(packet: dict[str, Any]) -> dict[str, Any]:
    value = packet.get("question_contract")
    required = {"id", "facet", "evidence_to_seek", "source_roles", "capability_ids",
                "depends_on", "priority", "stop_rule"}
    _require(isinstance(value, dict) and set(value) == required
             and all(isinstance(value.get(key), str) and value[key].strip()
                     for key in ("id", "facet", "evidence_to_seek", "priority", "stop_rule"))
             and isinstance(value.get("source_roles"), list) and value["source_roles"]
             and all(isinstance(item, str) and item for item in value["source_roles"])
             and isinstance(value.get("capability_ids"), list) and value["capability_ids"]
             and all(isinstance(item, str) and item for item in value["capability_ids"])
             and isinstance(value.get("depends_on"), list)
             and all(isinstance(item, str) for item in value["depends_on"]),
             "READINESS_QUESTION_CONTRACT_INVALID")
    return value


def _derive_live_contract(packet: dict[str, Any]) -> dict[str, Any]:
    """Derive the only live question/proposals authorized by a v2 packet."""
    _require(packet.get("schema_version") == VERSION, "READINESS_VERSION")
    run_kind = packet.get("run_kind")
    _require(run_kind in _REQUIRED_BUDGETS, "READINESS_RUN_KIND_INVALID")
    case = packet["case"]
    question = {**_question_contract(packet), "question": case["question"]}
    search = {
        "operation_id": "search-disclosure", "question_ids": [question["id"]],
        "source_role": question["source_roles"][0],
        "reason": "Find the exact sealed disclosure representations.",
        "arguments": {"search_query": [{"q": case["search_query"]}],
                      "response_length": "long"}, "alternates": [],
    }
    proposals = [search]
    if run_kind == "narrow":
        proposals.append({
            "operation_id": "open-primary", "question_ids": [question["id"]],
            "source_role": question["source_roles"][0],
            "reason": "Open the exact sealed PDF representation.",
            "arguments": {"open": [{"ref_id": case["primary_pdf_url"]}],
                          "response_length": "long"},
            "alternates": [{
                "representation_kind": "html",
                "exact_arguments": {"open": [{"ref_id": case["alternate_html_url"]}],
                                    "response_length": "long"},
                "source_role": question["source_roles"][0],
                "required_capability": packet["source_contract"]["required_capability"],
                "required_access_level": packet["source_contract"]["required_access_level"],
                "canonical_disclosure_id": case["canonical_disclosure_id"],
                "relationship_to_primary": "semantically_equivalent_representation",
                "semantic_equivalence_rationale": packet["equivalence_review"]["rationale"],
                "permitted_trigger_codes": packet["source_contract"]["eligible_pdf_failure_codes"],
                "budget_cost": 1,
            }],
        })
    return {"run_kind": run_kind, "question": question, "proposals": proposals}



def derive_live_contract(packet: dict[str, Any]) -> dict[str, Any]:
    """Consume one prior full ready-v3 validation receipt."""
    _require(isinstance(packet, dict), "READINESS_PACKET_INVALID")
    _require(packet.get("schema_version") != VERSION_V2,
             "READINESS_SELF_REFERENCE_DISABLED")
    _require(packet.get("schema_version") == VERSION, "READINESS_VERSION")
    return _consume_ready(packet)


def _validate_effective_config(packet: dict[str, Any], root: Path) -> None:
    effective = packet.get("effective_config")
    names = [name[:-7] for name in EffectiveConfigInputs.__dataclass_fields__
             if name.endswith("_sha256")]
    _require(isinstance(effective, dict) and effective.get("required_inputs") == names
             and isinstance(effective.get("inputs"), dict)
             and set(effective["inputs"]) == set(names),
             "READINESS_EFFECTIVE_CONFIG_INVALID")
    hashes = {f"{name}_sha256": _repository_file(
        root, effective["inputs"][name], "READINESS_EFFECTIVE_CONFIG_INVALID",
        expected_path=_CANONICAL_EFFECTIVE_CONFIG_PATHS[name])
        for name in names}
    inputs = EffectiveConfigInputs(**hashes)
    expected = hashlib.sha256(canonical_bytes(asdict(inputs))).hexdigest()
    _require(effective.get("sha256") == expected,
             "READINESS_EFFECTIVE_CONFIG_INVALID")
    case_envelope = _case_packet_envelope(root, effective["inputs"]["case_packet"])
    _require(case_envelope["case_packet"] == case_packet_projection(packet),
             "READINESS_CASE_PACKET_MISMATCH")

def _validate_ready(packet: dict[str, Any], root: Path) -> None:
    case = packet.get("case")
    version = packet.get("schema_version")
    if version == VERSION:
        _require(packet.get("run_kind") in _REQUIRED_BUDGETS,
                 "READINESS_RUN_KIND_INVALID")
        _question_contract(packet)
    _require(isinstance(case, dict) and all(isinstance(case.get(key), str)
             and case[key].strip() for key in (
                 "case_id", "issuer_id", "canonical_disclosure_id", "question",
                 "search_query", "primary_pdf_url", "alternate_html_url", "selection_bias")),
             "READINESS_CASE_INVALID")
    policy = packet.get("url_policy")
    _require(isinstance(policy, dict)
             and policy.get("normalization") == "exact_https_url_bytes"
             and policy.get("redirects") == "reject_unless_frozen_target_matches"
             and isinstance(policy.get("allowed_hosts"), list)
             and bool(policy["allowed_hosts"]), "READINESS_URL_POLICY_INVALID")
    allowed_hosts = set(policy["allowed_hosts"])
    _require(all(isinstance(host, str) and host == host.lower() and host.strip()
                 and "/" not in host for host in allowed_hosts), "READINESS_URL_POLICY_INVALID")
    _require(_canonical_https_url(case["primary_pdf_url"], allowed_hosts)
             and _canonical_https_url(case["alternate_html_url"], allowed_hosts),
             "READINESS_URL_INVALID")

    review = packet.get("equivalence_review")
    _require(isinstance(review, dict) and review.get("status") == "approved"
             and isinstance(review.get("reviewer_id"), str) and review["reviewer_id"].strip()
             and isinstance(review.get("rationale"), str) and review["rationale"].strip()
             and all(review.get(key) is True for key in (
                 "disclosure_date_match", "publisher_control", "release_identity_match",
                 "representation_relationship", "title_match")),
             "READINESS_EQUIVALENCE_INVALID")

    artifacts = packet.get("artifacts")
    _require(isinstance(artifacts, dict) and artifacts.get("artifact_root_mode") == "0700"
             and all(isinstance(artifacts.get(key), str) and artifacts[key].strip() for key in (
                 "artifact_root", "runtime_root", "raw_retention", "reconciliation_owner",
                 "retention_owner", "rollback_target")), "READINESS_ARTIFACTS_INVALID")
    source = packet.get("source_contract")
    _require(isinstance(source, dict) and isinstance(source.get("cutoff"), str),
             "READINESS_SOURCE_CONTRACT_INVALID")
    try:
        cutoff = datetime.fromisoformat(source["cutoff"])
    except ValueError:
        raise ReadinessError("READINESS_SOURCE_CONTRACT_INVALID") from None
    _require(cutoff.tzinfo is not None and cutoff.utcoffset() is not None
             and all(isinstance(source.get(key), str) and source[key].strip() for key in (
                 "evidence_facet", "required_access_level", "required_capability", "source_role"))
             and isinstance(source.get("eligible_body_rules"), list)
             and bool(source["eligible_body_rules"]), "READINESS_SOURCE_CONTRACT_INVALID")
    if version == VERSION:
        _validate_v3_lists(packet)
    else:
        stops = packet.get("stop_rules")
        _require(isinstance(stops, list)
                 and all(isinstance(item, str) for item in stops)
                 and _REQUIRED_STOPS.issubset(set(stops)),
                 "READINESS_STOP_RULES_INVALID")


def validate_envelope(envelope: dict[str, Any], *, root: Path = ROOT) -> dict[str, Any]:
    """Validate seal and repository custody, then return a bounded readiness verdict."""
    _VALIDATED_READY.clear()
    _require(isinstance(envelope, dict) and set(envelope) == {"packet", "seal"},
             "READINESS_ENVELOPE_INVALID")
    packet, seal = envelope["packet"], envelope["seal"]
    _require(isinstance(packet, dict) and isinstance(seal, dict)
             and set(seal) == {"algorithm", "packet_sha256"}
             and seal.get("algorithm") == "sha256"
             and seal.get("packet_sha256") == hashlib.sha256(canonical_bytes(packet)).hexdigest(),
             "READINESS_SEAL_INVALID")
    version = packet.get("schema_version")
    _require(version != VERSION_V2, "READINESS_SELF_REFERENCE_DISABLED")
    _require(version in {VERSION_V1, VERSION}, "READINESS_VERSION")
    _require(not _contains_forbidden_key(packet), "READINESS_QUOTE_PRESELECTED")
    if version == VERSION:
        _validate_v3_shape(packet)
        _validate_v3_lists(packet)
    case = packet.get("case", {})
    _require(case.get("quote_preselected") is False, "READINESS_QUOTE_PRESELECTED")
    budgets = packet.get("budgets", {})
    run_kind = packet.get("run_kind", "narrow")
    _require(run_kind in _REQUIRED_BUDGETS
             and all(budgets.get(key) == value
                     for key, value in _REQUIRED_BUDGETS[run_kind].items()),
             "READINESS_BUDGET_INVALID")
    _require(type(budgets.get("run_wall_seconds")) in {int, float, type(None)}
             and type(budgets.get("provider_call_seconds")) in {int, float, type(None)},
             "READINESS_DEADLINE_INVALID")
    if budgets.get("run_wall_seconds") is not None or budgets.get("provider_call_seconds") is not None:
        _require(type(budgets.get("run_wall_seconds")) in {int, float}
                 and type(budgets.get("provider_call_seconds")) in {int, float}
                 and 0 < budgets["provider_call_seconds"] <= budgets["run_wall_seconds"],
                 "READINESS_DEADLINE_INVALID")
    evidence = packet.get("repository_evidence")
    _require(isinstance(evidence, list) and evidence, "READINESS_EVIDENCE_REQUIRED")
    root = root.resolve()
    for row in evidence:
        _require(isinstance(row, dict) and set(row) == {"path", "sha256"},
                 "READINESS_EVIDENCE_INVALID")
        _repository_file(root, row, "READINESS_EVIDENCE_CHANGED")
    unresolved = packet.get("unresolved")
    _require(isinstance(unresolved, list) and all(isinstance(value, str) for value in unresolved),
             "READINESS_UNRESOLVED_INVALID")
    ready = packet.get("status") == "ready" and not unresolved
    if ready:
        _validate_ready(packet, root)
    if version == VERSION:
        _validate_effective_config(packet, root)
    if ready and version == VERSION:
        _remember_ready(packet, _derive_live_contract(packet))
    return {"schema_version": VERSION, "packet_sha256": seal["packet_sha256"],
            "seal_valid": True, "ready_for_provider_authorization_request": ready,
            "structural_evidence_only": True,
            "reason": "READINESS_COMPLETE" if ready else "READINESS_UNRESOLVED"}


def load_and_validate(path: Path, *, root: Path = ROOT) -> dict[str, Any]:
    _require(path.is_file() and not path.is_symlink(), "READINESS_PATH_INVALID")
    try:
        envelope = json.loads(path.read_bytes())
    except (json.JSONDecodeError, OSError) as error:
        raise ReadinessError("READINESS_JSON_INVALID") from error
    return validate_envelope(envelope, root=root)
