"""Exact typed, source-pinned target handoffs that remain impossible to invoke."""
from __future__ import annotations

import base64
import copy
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Mapping

from .contracts import ContractError, P0_ARGUMENT_NAMES, STATUS, canonical_bytes, exact, require, sha256_json, unresolved_pin

_REPO = Path(__file__).resolve().parents[4]

@dataclass(frozen=True)
class SourcePin:
    relative_path: str
    size: int
    sha256: str

P0_SOURCE = SourcePin("shared/job_runtime/candidates/r6_data_quality_attempt_envelope_v1/pipeline.py", 9605, "9a129560ce2bcc8f90daa5b5280d0b67c75ebd21072a123493fa6d5a6cca018e")
RUNNER_SOURCE = SourcePin("shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1/runner.py", 39451, "bc45fceff79a1106ef66c09376075f3bb72a235ac4a23ca69b7344f914ff0bff")
_FIXTURES = {
    "CLAUDE": (
        SourcePin("shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/claude-sanitized-publication.json", 1059, "09a1c6f63d69dcbff713e8f4bc1f50bf856b6f725f3882e7ccab29d2716ebbef"),
        SourcePin("shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/claude-research-material.json", 3988, "81398ba860d803361e39093ebd539b8a7ecb4a2148c0afdb3a5f3b1ec365fbc6"),
    ),
    "CODEX": (
        SourcePin("shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/codex-sanitized-publication.json", 631, "7f246bec5742d30c0520bf6ed3426f1bee993ed273014db42a912083c205900b"),
        SourcePin("shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1/codex-research-material.json", 4078, "e1963190b527721062df7f9a6525766ed443014d16f83be05e411c7707f98c77"),
    ),
}
P0_OPTIONAL_ARGUMENT_NAMES = ("dq_checks", "claimed_readback_digest", "retention_fault")
RUNNER_ARGUMENT_NAMES = ("authority_registry_ref", "owner_root", "map_commitment_ref", "bundle_root")
RUNNER_OPTIONAL_ARGUMENT_NAMES = ("_fixture_boundaries", "_receipt_fault")
_P0_FULL = tuple((name, "POSITIONAL_OR_KEYWORD" if index < 2 else "KEYWORD_ONLY", index < 16) for index, name in enumerate(P0_ARGUMENT_NAMES + P0_OPTIONAL_ARGUMENT_NAMES))
_RUNNER_FULL = tuple((name, "POSITIONAL_OR_KEYWORD" if index < 4 else "KEYWORD_ONLY", index < 4) for index, name in enumerate(RUNNER_ARGUMENT_NAMES + RUNNER_OPTIONAL_ARGUMENT_NAMES))

class TargetSignatureDrift(ContractError):
    pass

class UnresolvedSuccessorBinding(ContractError):
    pass

@dataclass(frozen=True)
class UnresolvedBinding:
    name: str
    expected_type: str
    status: str = "UNRESOLVED_BUILD_TIME_BINDING"

    def __post_init__(self) -> None:
        require(type(self) is UnresolvedBinding, "UNRESOLVED_BINDING_SUBCLASS")
        require(type(self.name) is str and self.name, "UNRESOLVED_BINDING_NAME")
        require(type(self.expected_type) is str and self.expected_type, "UNRESOLVED_BINDING_TYPE")
        require(self.status == "UNRESOLVED_BUILD_TIME_BINDING", "UNRESOLVED_BINDING_STATUS")

    def manifest(self) -> Mapping[str, Any]:
        return {"name": self.name, "expected_type": self.expected_type, "status": self.status, "value": None}


def _read_pin(pin: SourcePin) -> bytes:
    path = _REPO / pin.relative_path
    require(path.is_file() and not path.is_symlink(), "TARGET_SOURCE_NOT_REGULAR")
    raw = path.read_bytes()
    if len(raw) != pin.size or hashlib.sha256(raw).hexdigest() != pin.sha256:
        raise TargetSignatureDrift("TARGET_SOURCE_DRIFT:" + pin.relative_path)
    return raw


def _descriptor(function: Any) -> tuple[tuple[str, str, bool], ...]:
    signature = inspect.signature(function)
    return tuple((parameter.name, parameter.kind.name, parameter.default is inspect.Parameter.empty) for parameter in signature.parameters.values())


def verify_target_signatures() -> Mapping[str, Any]:
    """Verify fixed source bytes before inspecting; never adapts to a moving target."""
    _read_pin(P0_SOURCE)
    _read_pin(RUNNER_SOURCE)
    from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.pipeline import execute
    from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.runner import execute_block
    p0 = _descriptor(execute)
    runner = _descriptor(execute_block)
    if p0 != _P0_FULL:
        raise TargetSignatureDrift("P0_SIGNATURE_DRIFT")
    if runner != _RUNNER_FULL:
        raise TargetSignatureDrift("RUNNER_SIGNATURE_DRIFT")
    return {
        "p0": {"source": P0_SOURCE.__dict__, "required": list(P0_ARGUMENT_NAMES), "optional": list(P0_OPTIONAL_ARGUMENT_NAMES)},
        "runner": {"source": RUNNER_SOURCE.__dict__, "required": list(RUNNER_ARGUMENT_NAMES), "optional": list(RUNNER_OPTIONAL_ARGUMENT_NAMES)},
    }


def _load_json(pin: SourcePin) -> Mapping[str, Any]:
    raw = _read_pin(pin)
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ContractError("TARGET_FIXTURE_JSON") from exc
    require(type(value) is dict, "TARGET_FIXTURE_SHAPE")
    return value


def _checks(enabled: bool) -> list[Mapping[str, str]] | None:
    if not enabled:
        return None
    names = ("source_catalog_freshness", "evidence_metadata_completeness", "lineage_metadata_completeness", "official_evidence_conflict", "duplicate_fact_citation", "dq_publication_quality")
    return [{"name": name, "status": "PASS", "code": "CHECK_PASS"} for name in names]


def _encode(value: Any) -> Any:
    if type(value) is UnresolvedBinding:
        return value.manifest()
    if type(value) is bytes:
        return {"encoding": "base64", "data": base64.b64encode(value).decode("ascii"), "bytes": len(value), "sha256": hashlib.sha256(value).hexdigest()}
    return copy.deepcopy(value)


def _encode_json_value(value: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = canonical_bytes(value)
    return {"encoding": "canonical-json", "data": raw.decode("ascii"), "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

@dataclass(frozen=True)
class P0ExecuteHandoff:
    order_index: int
    provider_port: str
    target_pin: Mapping[str, Any]
    required_arguments: Mapping[str, Any]
    optional_arguments: Mapping[str, Any]

    def __post_init__(self) -> None:
        require(type(self.order_index) is int and 0 <= self.order_index < 4, "P0_ORDER_INDEX")
        require(self.provider_port in ("CLAUDE", "CODEX"), "P0_PROVIDER_PORT")
        unresolved_pin(self.target_pin, "p0_attempt_envelope")
        exact(self.required_arguments, P0_ARGUMENT_NAMES, "P0_REQUIRED_ARGUMENT_SHAPE")
        exact(self.optional_arguments, P0_OPTIONAL_ARGUMENT_NAMES, "P0_OPTIONAL_ARGUMENT_SHAPE")
        require(type(self.required_arguments["adapter"]) is UnresolvedBinding, "P0_ADAPTER_BINDING")
        require(type(self.required_arguments["bundle_root"]) is UnresolvedBinding, "P0_BUNDLE_ROOT_BINDING")
        require(type(self.required_arguments["readback"]) is dict, "P0_READBACK_VALUE")
        require(type(self.required_arguments["raw"]) is bytes, "P0_RAW_VALUE")
        require(type(self.required_arguments["provider_publication_artifact"]) is dict, "P0_PUBLICATION_VALUE")
        require(type(self.required_arguments["research_material"]) is dict, "P0_RESEARCH_VALUE")

    def manifest(self) -> Mapping[str, Any]:
        verify_target_signatures()
        value = {
            "version": 2,
            "candidate_status": STATUS,
            "target_package": "shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1",
            "target_api": "execute",
            "target_pin": copy.deepcopy(self.target_pin),
            "cell_id": self.required_arguments["cell_id"],
            "order_index": self.order_index,
            "provider_port": self.provider_port,
            "required_argument_names": list(P0_ARGUMENT_NAMES),
            "argument_values": {
                name: (_encode_json_value(self.required_arguments[name]) if name in ("provider_publication_artifact", "research_material") else _encode(self.required_arguments[name]))
                for name in P0_ARGUMENT_NAMES
            },
            "optional_argument_names": list(P0_OPTIONAL_ARGUMENT_NAMES),
            "optional_argument_values": {name: _encode(self.optional_arguments[name]) for name in P0_OPTIONAL_ARGUMENT_NAMES},
            "effects_executed": False,
        }
        return value

    def invoke(self) -> None:
        verify_target_signatures()
        unresolved_pin(self.target_pin, "p0_attempt_envelope")
        raise UnresolvedSuccessorBinding("P0_FINAL_SUCCESSOR_PIN_UNRESOLVED")

@dataclass(frozen=True)
class EvaluationRunnerHandoff:
    target_pin: Mapping[str, Any]
    required_arguments: Mapping[str, Any]
    optional_arguments: Mapping[str, Any]
    p0_handoff_sha256: tuple[str, ...]

    def __post_init__(self) -> None:
        unresolved_pin(self.target_pin, "evaluation_runner")
        exact(self.required_arguments, RUNNER_ARGUMENT_NAMES, "RUNNER_REQUIRED_ARGUMENT_SHAPE")
        exact(self.optional_arguments, RUNNER_OPTIONAL_ARGUMENT_NAMES, "RUNNER_OPTIONAL_ARGUMENT_SHAPE")
        require(all(type(self.required_arguments[name]) is UnresolvedBinding for name in RUNNER_ARGUMENT_NAMES), "RUNNER_BINDING_TYPE")
        require(self.optional_arguments == {"_fixture_boundaries": None, "_receipt_fault": None}, "RUNNER_OPTIONAL_VALUES")

    def manifest(self) -> Mapping[str, Any]:
        verify_target_signatures()
        return {
            "version": 2,
            "candidate_status": STATUS,
            "target_package": "shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1",
            "target_api": "execute_block",
            "target_pin": copy.deepcopy(self.target_pin),
            "required_argument_names": list(RUNNER_ARGUMENT_NAMES),
            "argument_values": {name: _encode(self.required_arguments[name]) for name in RUNNER_ARGUMENT_NAMES},
            "optional_argument_names": list(RUNNER_OPTIONAL_ARGUMENT_NAMES),
            "optional_argument_values": copy.deepcopy(self.optional_arguments),
            "cell_order": ["R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3"],
            "p0_handoff_sha256": list(self.p0_handoff_sha256),
            "completed_cell_count": len(self.p0_handoff_sha256),
            "all_four_present": len(self.p0_handoff_sha256) == 4,
            "partial_comparison": False,
            "countable": False,
            "effects_executed": False,
        }

    def invoke(self) -> None:
        verify_target_signatures()
        unresolved_pin(self.target_pin, "evaluation_runner")
        raise UnresolvedSuccessorBinding("RUNNER_FINAL_SUCCESSOR_PIN_UNRESOLVED")


def build_p0_handoff(plan: Mapping[str, Any], admission: Mapping[str, Any], pin: Mapping[str, Any]) -> P0ExecuteHandoff:
    verify_target_signatures()
    provider = plan["provider_port"]
    artifact_pin, research_pin = _FIXTURES[provider]
    artifact = copy.deepcopy(_load_json(artifact_pin))
    research = copy.deepcopy(_load_json(research_pin))
    raw = canonical_bytes({"fixture": "provider-free-v2", "provider_port": provider, "cell_id": plan["cell_id"]})
    payload = admission["p0_payload"]
    readback = {
        "version": 1,
        "job_id": payload["job_id"], "slot_id": payload["slot_id"], "attempt_id": payload["attempt_id"],
        "operation_id": payload["operation_id"], "prompt_binding_sha256": payload["prompt_binding_sha256"],
        "transaction": "BEGIN_IMMEDIATE_POST_WRITE_READBACK", "counts": {"job": 1, "slot": 1, "attempt": 1},
    }
    binding = {
        "cell_id": plan["cell_id"], "job_id": payload["job_id"], "slot_id": payload["slot_id"],
        "attempt_id": payload["attempt_id"], "operation_id": payload["operation_id"],
        "prompt_binding_sha256": payload["prompt_binding_sha256"], "canonical_engine_readback_digest": sha256_json(readback),
        "source_cutoff_sha256": payload["source_cutoff_sha256"],
    }
    raw_sha = hashlib.sha256(raw).hexdigest()
    artifact_sha = sha256_json(artifact)
    for body in research.values():
        body["binding"] = copy.deepcopy(binding)
        body["provider_terminal"] = admission["terminal_state"]
        body["raw_sha256"] = raw_sha
        body["publication_artifact_sha256"] = artifact_sha
    required = {
        "adapter": UnresolvedBinding("adapter", "PrimitiveAdapter"),
        "bundle_root": UnresolvedBinding("bundle_root", "Path"),
        "cell_id": plan["cell_id"], "blind_addon_label": plan["blind_addon_label"], "checks_enabled": plan["checks_enabled"],
        "job_id": payload["job_id"], "slot_id": payload["slot_id"], "attempt_id": payload["attempt_id"],
        "operation_id": payload["operation_id"], "prompt_binding_sha256": payload["prompt_binding_sha256"],
        "readback": readback, "raw": raw, "provider_publication_artifact": artifact, "research_material": research,
        "terminal_state": admission["terminal_state"], "source_cutoff_sha256": payload["source_cutoff_sha256"],
    }
    optional = {"dq_checks": _checks(plan["checks_enabled"]), "claimed_readback_digest": None, "retention_fault": None}
    return P0ExecuteHandoff(plan["order_index"], provider, copy.deepcopy(pin), required, optional)


def build_runner_handoff(p0_manifests: list[Mapping[str, Any]], pin: Mapping[str, Any]) -> EvaluationRunnerHandoff:
    verify_target_signatures()
    required = {
        "authority_registry_ref": UnresolvedBinding("authority_registry_ref", "Mapping[str, Any]"),
        "owner_root": UnresolvedBinding("owner_root", "Path"),
        "map_commitment_ref": UnresolvedBinding("map_commitment_ref", "Mapping[str, Any]"),
        "bundle_root": UnresolvedBinding("bundle_root", "Path"),
    }
    optional = {"_fixture_boundaries": None, "_receipt_fault": None}
    return EvaluationRunnerHandoff(copy.deepcopy(pin), required, optional, tuple(sha256_json(item) for item in p0_manifests))

__all__ = [
    "EvaluationRunnerHandoff", "P0ExecuteHandoff", "P0_SOURCE", "RUNNER_SOURCE",
    "TargetSignatureDrift", "UnresolvedBinding", "UnresolvedSuccessorBinding",
    "build_p0_handoff", "build_runner_handoff", "verify_target_signatures",
]
