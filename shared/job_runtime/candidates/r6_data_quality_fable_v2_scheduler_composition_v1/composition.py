"""Provider-free scheduler composition from real Config.load jobs into semantic v3."""
from __future__ import annotations

from datetime import datetime
import ast
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping, Optional

from shared.job_runtime.config import load
from shared.job_runtime.engine import Engine, validate_job
from shared.job_runtime.engine_schema import prompt_binding_sha256
from shared.job_runtime.prompt_custody import PromptArtifactStore
from shared.job_runtime.provider_contract import ProviderResultV1
from shared.job_runtime.service import publish_prompt_jobs, resource_jobs
from shared.job_runtime.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.vertical import (
    BundleOwnerV3, CELLS, ClosedDatabaseBridgeV3, ConfigOwnerV3, DesignOwnerV3,
    EFFECTS, GENERATION, IntegrationOwnerV3, MaterializationOwnerV3, MODEL,
    PROMPT_BYTES, PROMPT_SHA256, PROVIDER, ProposalOwnerV3, SOURCE_SHA256,
    SCHEMA9_FINGERPRINT,
    TerminalRawArtifactV3, TerminalRawStoreV3, ProviderResultNormalizerV3,
    VerticalV3Error, canonical_bytes, digest, terminal_evidence, verify_old166,
)

CONTRACT = "r6.scheduler-composition.v1"
PROFILE = "fable-scheduler-v1"
JOB_IDS = ("scheduler-v1-control", "scheduler-v1-treatment")
PROMPT_REL = ".job-runtime/config/prompts/scheduler-v1.txt"
ALLOCATION_REL = ".job-runtime/config/scheduler-v1-allocation.json"
AUTH_REL = ".job-runtime/config/scheduler-v1-auth"
EFFECTS_V1 = dict(EFFECTS)

class CompositionError(ValueError):
    pass

def require(value: bool, code: str) -> None:
    if not value:
        raise CompositionError(code)

RUNTIME_ROOTS = (
    "shared/job_runtime/config.py", "shared/job_runtime/engine.py",
    "shared/job_runtime/engine_schema.py", "shared/job_runtime/prompt_custody.py",
    "shared/job_runtime/provider_contract.py", "shared/job_runtime/retry_policy.py",
    "shared/job_runtime/service.py",
    "shared/job_runtime/candidates/r6_data_quality_fable_v2_semantic_vertical_v3/vertical.py",
    "shared/job_runtime/candidates/r6_data_quality_fable_v2_scheduler_composition_v1/composition.py",
)
TEST_RUNTIME = {
    "python3.9.6": {"implementation": "CPython", "version": "3.9.6",
        "executable": "/usr/bin/python3"},
    "python3.12.16": {"implementation": "CPython", "version": "3.12.16",
        "executable": ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"},
}
EXPECTED_TEST_RESULTS = {
    "python3.9.6_scheduler": {"command": "/usr/bin/python3 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_scheduler_composition_v1.test_composition -q", "passed": 11, "failed": 0, "result": "OK"},
    "python3.12.16_scheduler": {"command": ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_scheduler_composition_v1.test_composition -q", "passed": 11, "failed": 0, "result": "OK"},
    "python3.9.6_combined": {"command": "/usr/bin/python3 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_scheduler_composition_v1.test_composition shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.test_vertical shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v1.test_vertical shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v2.test_vertical -q", "passed": 38, "failed": 0, "result": "OK"},
    "python3.12.16_composition_semantic_v3": {"command": ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_scheduler_composition_v1.test_composition shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.test_vertical -q", "passed": 21, "failed": 0, "result": "OK"},
}
INNER_PACKET_KEYS = {"contract", "version", "status", "config", "allocation", "prompt",
    "cas_jobs", "cas_custody", "test_enabled_job_ids", "dispositions", "schema9_fingerprint",
    "provider_rows", "database", "raw_artifacts", "bundle", "authority", "stage_outputs",
    "transitions", "second_cell_crash", "cleanup", "old166", "semantic_review", "runtime_manifest",
    "test_runtime", "portability", "effects", "sanitized", "packet_sha256"}
OUTER_PACKET_KEYS = {"contract", "version", "nominal_second_cell_crash", "malformed_injection",
    "unknown_missing_injection", "test_runtime", "test_results", "effects", "sanitized",
    "packet_sha256"}
ALLOCATION_JOB_KEYS = {"id", "enabled", "schedule", "model_profile", "prompt_file", "replay_contract"}
CAS_JOB_KEYS = {"id", "enabled", "schedule", "model_profile", "provider", "prompt_artifact",
    "replay_contract", "retry_policy_fingerprint", "resource_key", "circuit_scope"}
PROVIDER_ROW_KEYS = {"attempt_id", "slot_id", "canonical_json", "canonical_sha256", "provider",
    "operation_id", "phase", "submission", "terminal_proof", "status", "failure_kind",
    "prompt_binding_sha256", "job_id", "artifact_ref", "sha256", "length", "version",
    "source_identity_sha256", "generation", "proof_origin"}

PORTABILITY = {
    "source_identity": "Exact native Config.load capture identity; instance-bound metadata authority, not a portable content hash.",
    "portable_prompt_identity": {"sha256": PROMPT_SHA256, "bytes": PROMPT_BYTES,
        "source_fixture_sha256": SOURCE_SHA256, "source_fixture_bytes": 2065},
    "database_physical_descriptors": "Case-bounded diagnostics only; SQLite layout and UUID-bearing bytes are not cross-run reproducibility claims.",
    "reproducible_authority": "Schema-9 fingerprint, exact joined logical rows, embedded raw/bundle bytes, descriptor bindings, and the dependency-closed runtime manifest.",
    "retention_boundary": "Sanitized provider-free fixture and architecture receipts only; no live database, CAS, credentials, or service state retained.",
}

def _module_path(repo_root: Path, module: str) -> Optional[Path]:
    if not (module == "shared" or module.startswith("shared.")):
        return None
    base = repo_root.joinpath(*module.split("."))
    direct = base.with_suffix(".py")
    package = base / "__init__.py"
    return direct if direct.is_file() else package if package.is_file() else None

def _module_name(repo_root: Path, path: Path) -> str:
    rel = path.relative_to(repo_root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)

def runtime_manifest(repo_root: Path) -> dict[str, Any]:
    pending = [repo_root / item for item in RUNTIME_ROOTS]
    members: dict[str, dict[str, Any]] = {}
    while pending:
        path = pending.pop()
        rel = path.relative_to(repo_root).as_posix()
        if rel in members:
            continue
        raw = path.read_bytes()
        members[rel] = {"path": rel, "bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}
        parent = path.parent
        while parent != repo_root:
            init = parent / "__init__.py"
            if init.is_file():
                pending.append(init)
            parent = parent.parent
        module = _module_name(repo_root, path)
        package = module if path.name == "__init__.py" else module.rsplit(".", 1)[0]
        for node in ast.walk(ast.parse(raw, filename=str(path))):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    parent = package.split(".")
                    keep = len(parent) - node.level + 1
                    prefix = ".".join(parent[:keep])
                    target = prefix + (("." + node.module) if node.module else "")
                else:
                    target = node.module or ""
                targets.append(target)
            elif isinstance(node, ast.Import):
                targets.extend(alias.name for alias in node.names)
            for target in targets:
                dependency = _module_path(repo_root, target)
                if dependency is not None:
                    pending.append(dependency)
    return {"contract": "r6.scheduler-runtime-manifest.v1", "roots": list(RUNTIME_ROOTS),
        "members": [members[key] for key in sorted(members)]}

SEMANTIC_REVIEW_REL = "tuning/architecture/r6_data_quality_fable_v2_semantic_vertical_v3/independent-review-v3.json"
SEMANTIC_REVIEW_FILE_SHA256 = "cba379f946a68957fb5a6cd73c774c6f1ed270116fd49c14db68b932397cdea8"
SEMANTIC_REVIEW_RECEIPT_SHA256 = "82197a7f30f86bf86f36b1af1e78596b5e8a2d8c8d928eade84a6f10c705176b"
SEMANTIC_REVIEWED = {
    "old166_lock_sha256": "c519b805d726cf846d8c432fb441cd5d89bfd2e8497cbea8d01eca8ea3c6d46c",
    "old166_members_digest": "eb89b752c2c0d1cb7fba0475d8914051f6c007586dcfbb3d61be34e79eb35355",
    "old166_members_verified": 166,
    "packet_canonical_sha256": "ca0ef288628976d8dab35177dfc10500c7bb456ee6b655fb18059d6e79bcb4c6",
    "packet_file_sha256": "ca0ef288628976d8dab35177dfc10500c7bb456ee6b655fb18059d6e79bcb4c6",
    "prompt_bytes": 526, "prompt_sha256": PROMPT_SHA256,
    "prompt_source_bytes": 2065, "prompt_source_sha256": SOURCE_SHA256,
    "source_closure_sha256": "6d960fb66de20efe093fab98a1ba4407e65479de92ba46e8e0f917d5aa37b32f",
    "source_sha256": "8163c301aa287ac91f2496ba5e2d69943abca2f1cc2fca50734ae6e7d46e6a42",
    "test_sha256": "066ce3104fe127c4deff43d0aa57ba4f821300c70ec42514dfe33c9ef5a0dde0",
}

def verify_semantic_review(repo_root: Path) -> dict[str, Any]:
    path = repo_root / SEMANTIC_REVIEW_REL
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == SEMANTIC_REVIEW_FILE_SHA256,
            "SEMANTIC_REVIEW_FILE_SHA256")
    receipt = json.loads(raw)
    require(set(receipt) == {"contract", "version", "scope", "reviewer_role", "recording_authority",
            "recorded_at", "verdict", "findings", "effects", "reviewed", "producer_tests",
            "does_not_establish", "supersession", "receipt_sha256"}
            and receipt["contract"] == "r6-semantic-vertical-v3-independent-review-receipt"
            and receipt["version"] == 1 and receipt["scope"] == "provider-free-semantic-vertical-v3"
            and receipt["verdict"] == "CLEAN" and receipt["findings"] == {"P0": 0, "P1": 0, "P2": 0}
            and receipt["effects"] == {"provider": 0, "network": 0, "email": 0, "business": 0,
                "ixic": 0, "publication": 0, "live_scheduler": 0}
            and receipt["reviewed"] == SEMANTIC_REVIEWED
            and receipt["supersession"] == {"externally_supersedes_pending_pre_review_labels": True,
                "reason_not_in_source_closure": "avoid-independent-review-self-cycle",
                "reviewed_artifacts_modified": False, "source_closure_member": False},
            "SEMANTIC_REVIEW_CONTRACT")
    payload = dict(receipt); claimed = payload.pop("receipt_sha256")
    require(claimed == SEMANTIC_REVIEW_RECEIPT_SHA256 == digest(payload),
            "SEMANTIC_REVIEW_RECEIPT_SHA256")
    return {"path": SEMANTIC_REVIEW_REL, "file_sha256": SEMANTIC_REVIEW_FILE_SHA256,
        "receipt_sha256": SEMANTIC_REVIEW_RECEIPT_SHA256, "verdict": "CLEAN",
        "scope": "provider-free-semantic-vertical-v3", "reviewed": dict(SEMANTIC_REVIEWED)}

def packet_sha256(packet: Mapping[str, Any]) -> str:
    payload = dict(packet)
    payload.pop("packet_sha256", None)
    return digest(payload)

def seal_packet(packet: Mapping[str, Any]) -> dict[str, Any]:
    sealed = dict(packet)
    require("packet_sha256" not in sealed, "PACKET_ALREADY_SEALED")
    sealed["packet_sha256"] = packet_sha256(sealed)
    return sealed

def _descriptor_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {"version": row["version"], "ref": row["artifact_ref"],
        "sha256": row["sha256"], "length": row["length"],
        "source_identity_sha256": row["source_identity_sha256"],
        "generation": row["generation"], "proof_origin": row["proof_origin"]}

def verify_packet(packet: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    packet = dict(packet)
    require(set(packet) == INNER_PACKET_KEYS, "PACKET_KEYS")
    require(packet["packet_sha256"] == packet_sha256(packet), "PACKET_SHA256")
    require(packet["contract"] == CONTRACT and packet["version"] == 1
            and packet["status"] == "CLEAN_PROVIDER_FREE", "PACKET_CONTRACT")
    require(packet["effects"] == EFFECTS_V1 and packet["sanitized"] is True, "PACKET_EFFECTS")
    require(set(packet["config"]) == {"document", "sha256", "loaded_sha256"}
            and packet["config"]["sha256"] == digest(packet["config"]["document"])
            == packet["config"]["loaded_sha256"], "PACKET_CONFIG")
    require(set(packet["allocation"]) == {"document", "sha256", "loaded_job_ids"}
            and packet["allocation"]["sha256"] == digest(packet["allocation"]["document"])
            and packet["allocation"]["loaded_job_ids"] == list(JOB_IDS), "PACKET_ALLOCATION")
    allocation = packet["allocation"]["document"]
    require(set(allocation) == {"schema_version", "jobs"} and allocation["schema_version"] == 2
            and type(allocation["jobs"]) is list and len(allocation["jobs"]) == 2,
            "PACKET_ALLOCATION_SCHEMA")
    for index, job in enumerate(allocation["jobs"]):
        require(set(job) == ALLOCATION_JOB_KEYS and job["id"] == JOB_IDS[index]
                and job["enabled"] is False
                and set(job["schedule"]) == {"kind", "at", "grace_seconds"}
                and job["schedule"]["kind"] == "once" and type(job["schedule"]["at"]) is str
                and job["schedule"]["grace_seconds"] == 240
                and set(job["replay_contract"]) == {"version", "effect", "automatic_phases",
                    "slot_operation_scope", "reconciliation_adapter"}
                and job["replay_contract"]["version"] == 1
                and job["replay_contract"]["effect"] == "none"
                and job["replay_contract"]["automatic_phases"] == ["not_started"]
                and job["replay_contract"]["reconciliation_adapter"] is None,
                "PACKET_ALLOCATION_JOB")
    prompt_raw = base64.b64decode(packet["prompt"]["raw_b64"], validate=True)
    require(set(packet["prompt"]) == {"sha256", "bytes", "source_sha256", "source_bytes", "raw_b64"}
            and (len(prompt_raw), hashlib.sha256(prompt_raw).hexdigest()) ==
                (packet["prompt"]["bytes"], packet["prompt"]["sha256"])
            == (PROMPT_BYTES, PROMPT_SHA256)
            and (packet["prompt"]["source_bytes"], packet["prompt"]["source_sha256"])
                == (2065, SOURCE_SHA256), "PACKET_PROMPT_RAW")
    require(packet["semantic_review"] == verify_semantic_review(repo_root), "PACKET_SEMANTIC_REVIEW")
    require(packet["runtime_manifest"] == runtime_manifest(repo_root), "PACKET_RUNTIME_MANIFEST")
    require(packet["test_runtime"] == TEST_RUNTIME and packet["portability"] == PORTABILITY,
            "PACKET_METADATA")
    require(packet["schema9_fingerprint"] == SCHEMA9_FINGERPRINT
            == packet["database"]["schema_fingerprint"], "PACKET_SCHEMA9")
    require(packet["cleanup"] == {"sidecars": [], "snapshots": []}, "PACKET_CLEANUP")
    require(set(packet["database"]) == {"contract", "version", "schema_fingerprint",
            "source_descriptor", "snapshot_descriptor", "source_connection_closed",
            "snapshot_connection_closed", "immutable_read_closed", "engine_tick_returned_before_snapshot",
            "owned_lifecycle", "joined_rows"} and packet["database"]["joined_rows"] == 2,
            "PACKET_DATABASE")
    for name in ("source_descriptor", "snapshot_descriptor"):
        value = packet["database"][name]
        require(set(value) == {"sha256", "bytes"} and type(value["bytes"]) is int
                and value["bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", value["sha256"]),
                "PACKET_DATABASE_DESCRIPTOR")
    require(all(packet["database"][name] is True for name in
            ("source_connection_closed", "snapshot_connection_closed", "immutable_read_closed",
             "engine_tick_returned_before_snapshot", "owned_lifecycle")), "PACKET_DATABASE_LIFECYCLE")
    jobs = packet["cas_jobs"]; custody = packet["cas_custody"]; rows = packet["provider_rows"]
    require(type(jobs) is list and type(custody) is list and type(rows) is list
            and len(jobs) == len(custody) == len(rows) == 2
            and [item["id"] for item in jobs] == list(JOB_IDS)
            and [item["job_id"] for item in custody] == list(JOB_IDS)
            and [item["job_id"] for item in rows] == list(JOB_IDS)
            and all(item["enabled"] is False for item in jobs)
            and packet["test_enabled_job_ids"] == list(JOB_IDS), "PACKET_JOB_CARDINALITY")
    for index, job in enumerate(jobs):
        source = allocation["jobs"][index]
        require(set(job) == CAS_JOB_KEYS
                and set(job["prompt_artifact"]) == {"version", "ref", "sha256", "length",
                    "source_identity_sha256", "generation", "proof_origin"}
                and set(job["replay_contract"]) == {"version", "effect", "automatic_phases",
                    "slot_operation_scope", "reconciliation_adapter"}
                and all(job[field] == source[field] for field in
                    ("id", "enabled", "schedule", "model_profile", "replay_contract"))
                and set(rows[index]) == PROVIDER_ROW_KEYS, "PACKET_JOB_SCHEMA")
    require(set(packet["dispositions"]) == set(CELLS), "PACKET_DISPOSITIONS")
    require(type(packet["bundle"]["cells"]) is list and len(packet["bundle"]["cells"]) == 2,
            "PACKET_BUNDLE_CARDINALITY")
    BundleOwnerV3.validate(packet["bundle"])
    require(type(packet["raw_artifacts"]) is dict and len(packet["raw_artifacts"]) == 2
            and set(packet["raw_artifacts"]) == {cell["terminal_artifact_ref"] for cell in packet["bundle"]["cells"]},
            "PACKET_RAW_CARDINALITY")
    require(set(packet["authority"]) == {"prompt_descriptors", "cell_bindings", "provider_results"}
            and all(set(packet["authority"][name]) == set(CELLS) for name in packet["authority"]),
            "PACKET_AUTHORITY")
    for index, cell in enumerate(CELLS):
        receipt = custody[index]
        require(set(receipt) == {"job_id", "descriptor", "verified", "opened_sha256",
                "opened_bytes", "lease_closed"} and receipt["verified"] is True
                and receipt["lease_closed"] is True
                and (receipt["opened_sha256"], receipt["opened_bytes"]) ==
                    (PROMPT_SHA256, PROMPT_BYTES), "PACKET_CAS_CUSTODY")
        descriptor = jobs[index]["prompt_artifact"]
        require(descriptor == receipt["descriptor"] == _descriptor_from_row(rows[index])
                == packet["authority"]["prompt_descriptors"][cell], "PACKET_DESCRIPTOR_CONTINUITY")
        binding_descriptor = {"artifact_ref": descriptor["ref"], "sha256": descriptor["sha256"],
            "length": descriptor["length"], "version": descriptor["version"],
            "source_identity_sha256": descriptor["source_identity_sha256"],
            "generation": descriptor["generation"], "proof_origin": descriptor["proof_origin"]}
        binding = prompt_binding_sha256(rows[index]["job_id"], rows[index]["slot_id"], binding_descriptor)
        require(binding == rows[index]["prompt_binding_sha256"]
                == packet["authority"]["cell_bindings"][cell]
                == packet["bundle"]["cells"][index]["prompt_binding_sha256"],
                "PACKET_BINDING_CONTINUITY")
        canonical_value = json.loads(rows[index]["canonical_json"])
        require(packet["dispositions"][cell] == canonical_value["receipt"]["parser_disposition"]
                == packet["bundle"]["cells"][index]["disposition"],
                "PACKET_DISPOSITION_CONTINUITY")
        canonical = rows[index]["canonical_json"].encode("utf-8")
        require(hashlib.sha256(canonical).hexdigest() == rows[index]["canonical_sha256"]
                == packet["authority"]["provider_results"][cell]
                == packet["bundle"]["cells"][index]["provider_result_sha256"],
                "PACKET_PROVIDER_RESULT_CONTINUITY")
        bundle_cell = packet["bundle"]["cells"][index]
        artifact = packet["raw_artifacts"][bundle_cell["terminal_artifact_ref"]]
        require(set(artifact) == {"sha256", "bytes", "raw_b64"}, "PACKET_RAW_SHAPE")
        raw = base64.b64decode(artifact["raw_b64"], validate=True)
        require((hashlib.sha256(raw).hexdigest(), len(raw)) == (artifact["sha256"], artifact["bytes"])
                == (bundle_cell["raw_sha256"], bundle_cell["raw_bytes"])
                and raw == base64.b64decode(bundle_cell["raw_b64"], validate=True),
                "PACKET_RAW_CONTINUITY")
        encoded = base64.b64decode(bundle_cell["bundle_b64"], validate=True)
        core = {key: value for key, value in bundle_cell.items()
                if key not in {"bundle_sha256", "bundle_bytes", "raw_b64", "bundle_b64"}}
        require(encoded == canonical_bytes(core)
                and (hashlib.sha256(encoded).hexdigest(), len(encoded)) ==
                    (bundle_cell["bundle_sha256"], bundle_cell["bundle_bytes"]),
                "PACKET_BUNDLE_CONTINUITY")
    owners = (IntegrationOwnerV3, DesignOwnerV3, MaterializationOwnerV3,
              ProposalOwnerV3, ConfigOwnerV3)
    require(type(packet["transitions"]) is list and len(packet["transitions"]) == 5
            and type(packet["stage_outputs"]) is list and len(packet["stage_outputs"]) == 5
            and [item["output"]["contract"] for item in packet["transitions"]]
                == [owner.CONTRACT for owner in owners]
            and packet["stage_outputs"] == [item["output"] for item in packet["transitions"]],
            "PACKET_STAGE_ORDER")
    predecessor = packet["bundle"]
    for owner, transition in zip(owners, packet["transitions"]):
        require(transition["input"] == predecessor, "PACKET_TRANSITION_CHAIN")
        owner.validate_input(transition, packet["authority"])
        require(transition["receipt"]["input_digest"] == digest(transition["input"])
                and transition["receipt"]["output_digest"] == digest(transition["output"]),
                "PACKET_TRANSITION_DIGEST")
        predecessor = transition["output"]
    crash = packet["second_cell_crash"]
    if crash is not None:
        require(set(crash) == {"fault", "signal", "synchronization", "actual_process_interruption",
                "existing_files_unchanged", "recovered", "preexisting_sha256"}
                and crash["fault"] == "SIGKILL_AFTER_SECOND_CELL_RAW_FSYNC" and crash["signal"] == 9
                and crash["synchronization"] == "external_fifo_reader_handshake"
                and crash["actual_process_interruption"] is True
                and crash["existing_files_unchanged"] is True and crash["recovered"] is True
                and crash["preexisting_sha256"] == {
                    "control/control.raw": packet["bundle"]["cells"][0]["raw_sha256"],
                    "control/control.bundle.json": packet["bundle"]["cells"][0]["bundle_sha256"],
                    "treatment/treatment.raw": packet["bundle"]["cells"][1]["raw_sha256"]},
                "PACKET_CRASH_RECEIPT")
    require(packet["old166"] == verify_old166(repo_root), "PACKET_OLD166")
    return packet

def assemble_evidence_packet(cases: Mapping[str, Mapping[str, Any]],
                             test_results: Mapping[str, Any]) -> dict[str, Any]:
    require(tuple(cases) == ("nominal_second_cell_crash", "malformed_injection",
            "unknown_missing_injection") and dict(test_results) == EXPECTED_TEST_RESULTS,
            "EVIDENCE_CASE_ORDER")
    return seal_packet({"contract": "r6.scheduler-composition-evidence-packet.v1", "version": 1,
        **{name: dict(value) for name, value in cases.items()}, "test_runtime": TEST_RUNTIME,
        "test_results": dict(test_results), "effects": dict(EFFECTS_V1), "sanitized": True})

def verify_evidence_packet(packet: Mapping[str, Any], repo_root: Path) -> dict[str, Any]:
    packet = dict(packet)
    require(set(packet) == OUTER_PACKET_KEYS, "EVIDENCE_PACKET_KEYS")
    require(packet["packet_sha256"] == packet_sha256(packet), "EVIDENCE_PACKET_SHA256")
    require(packet["contract"] == "r6.scheduler-composition-evidence-packet.v1"
            and packet["version"] == 1 and packet["test_runtime"] == TEST_RUNTIME
            and packet["test_results"] == EXPECTED_TEST_RESULTS
            and packet["effects"] == EFFECTS_V1 and packet["sanitized"] is True,
            "EVIDENCE_PACKET_CONTRACT")
    for name in ("nominal_second_cell_crash", "malformed_injection", "unknown_missing_injection"):
        verify_packet(packet[name], repo_root)
    require(packet["nominal_second_cell_crash"]["second_cell_crash"] is not None
            and packet["malformed_injection"]["second_cell_crash"] is None
            and packet["unknown_missing_injection"]["second_cell_crash"] is None,
            "EVIDENCE_CRASH_CASES")
    require(packet["nominal_second_cell_crash"]["dispositions"] == {"control": "PASS", "treatment": "PASS"}
            and packet["malformed_injection"]["dispositions"] == {"control": "PASS", "treatment": "MALFORMED"}
            and packet["unknown_missing_injection"]["dispositions"] == {"control": "UNKNOWN", "treatment": "MISSING"},
            "EVIDENCE_CASE_DISPOSITIONS")
    return packet

def config_documents(scheduled: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    schedule = {"kind": "once", "at": scheduled.isoformat(), "grace_seconds": 240}
    config = {"schema_version": 2, "tick_seconds": 5, "heartbeat_seconds": 10,
        "stale_seconds": 60, "max_workers": 1,
        "retry": {"version": 2, "max_attempts": 1, "base_delay_seconds": 1,
            "max_delay_seconds": 1, "deadline_seconds": 240, "jitter": "sha256-full-jitter-v1"},
        "model_profiles": {PROFILE: {"provider": PROVIDER, "model": MODEL, "effort": "low",
            "timeout_seconds": 300, "auth_home": AUTH_REL, "max_budget_usd": 0.02}},
        "allocation_files": [ALLOCATION_REL], "source_paths": []}
    allocation = {"schema_version": 2, "jobs": [{"id": JOB_IDS[index], "enabled": False,
        "schedule": dict(schedule), "model_profile": PROFILE, "prompt_file": PROMPT_REL,
        "replay_contract": {"version": 1, "effect": "none", "automatic_phases": ["not_started"],
            "slot_operation_scope": f"scheduler/v1/{cell}", "reconciliation_adapter": None}}
        for index, cell in enumerate(CELLS)]}
    return config, allocation

def install_documents(workspace: Path, source: Path, scheduled: datetime) -> tuple[Path, dict[str, Any], dict[str, Any], bytes]:
    source_raw = source.read_bytes()
    require((len(source_raw), hashlib.sha256(source_raw).hexdigest()) == (2065, SOURCE_SHA256), "SOURCE_FIXTURE")
    prompt = json.loads(source_raw)["prompt_utf8"].encode()
    require((len(prompt), hashlib.sha256(prompt).hexdigest()) == (PROMPT_BYTES, PROMPT_SHA256), "PROMPT_526")
    config, allocation = config_documents(scheduled)
    workspace.chmod(0o700); private = workspace / ".job-runtime"; private.mkdir(mode=0o700, exist_ok=True); private.chmod(0o700)
    base = private / "config"; (base / "prompts").mkdir(mode=0o700, parents=True, exist_ok=True)
    base.chmod(0o700); (base / "prompts").chmod(0o700)
    (base / "scheduler-v1-auth").mkdir(mode=0o700, exist_ok=True); (base / "scheduler-v1-auth").chmod(0o700)
    prompt_path = workspace / PROMPT_REL; prompt_path.write_bytes(prompt); prompt_path.chmod(0o600)
    allocation_path = workspace / ALLOCATION_REL; allocation_path.write_bytes(canonical_bytes(allocation)); allocation_path.chmod(0o600)
    config_path = base / "scheduler-v1.json"; config_path.write_bytes(canonical_bytes(config)); config_path.chmod(0o600)
    return config_path, config, allocation, prompt

def load_publish_enrich(workspace: Path, config_path: Path, prompt: bytes) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    old = Path.cwd(); os.chdir(workspace)
    try: loaded_config, loaded_jobs = load(config_path, workspace)
    finally: os.chdir(old)
    require([job["id"] for job in loaded_jobs] == list(JOB_IDS)
            and all(job["enabled"] is False for job in loaded_jobs), "LOAD_JOBS")
    require(all(job["_prompt_capture"].sha256 == PROMPT_SHA256
                and job["_prompt_capture"].length == PROMPT_BYTES for job in loaded_jobs), "LOAD_PROMPT_CAPTURE")
    published = publish_prompt_jobs(workspace, loaded_jobs, GENERATION)
    store = PromptArtifactStore(workspace); cas_receipts = []
    for job in published:
        descriptor = job["_prompt_artifact"]
        require(store.verify(descriptor), "CAS_VERIFY")
        with store.open(descriptor) as lease:
            opened = b"".join(lease.chunks())
            require(opened == prompt and lease.closed is False, "CAS_OPEN")
        require(lease.closed, "CAS_CLOSE")
        cas_receipts.append({"job_id": job["id"], "descriptor": {"version": descriptor.version,
            "ref": descriptor.ref,
            "sha256": descriptor.sha256, "length": descriptor.length,
            "source_identity_sha256": descriptor.source_identity_sha256,
            "generation": descriptor.generation, "proof_origin": descriptor.provenance},
            "verified": True, "opened_sha256": hashlib.sha256(opened).hexdigest(),
            "opened_bytes": len(opened), "lease_closed": True})
    enriched = resource_jobs(loaded_config, published)
    require(len(enriched) == 2, "RESOURCE_JOB_COUNT")
    for job in enriched:
        validate_job(job)
        require(job["_provider"] == PROVIDER and job["_retry_policy"].max_attempts == 1
                and job["_replay_contract"].effect.value == "none"
                and isinstance(job["_resource_key"], str) and len(job["_resource_key"]) == 64,
                "RESOURCE_JOB_TYPED")
    return loaded_config, loaded_jobs, published, enriched, cas_receipts

def _plain_job(job: Mapping[str, Any]) -> dict[str, Any]:
    artifact = job["_prompt_artifact"]
    contract = job["_replay_contract"]
    policy = job["_retry_policy"]
    return {"id": job["id"], "enabled": job["enabled"], "schedule": job["schedule"],
        "model_profile": job["model_profile"], "provider": job["_provider"],
        "prompt_artifact": {"version": artifact.version, "ref": artifact.ref, "sha256": artifact.sha256,
            "length": artifact.length, "source_identity_sha256": artifact.source_identity_sha256,
            "generation": artifact.generation, "proof_origin": artifact.provenance},
        "replay_contract": {"version": contract.version, "effect": contract.effect.value,
            "automatic_phases": [phase.value for phase in contract.automatic_phases],
            "slot_operation_scope": contract.slot_operation_scope,
            "reconciliation_adapter": contract.reconciliation_adapter},
        "retry_policy_fingerprint": policy.fingerprint, "resource_key": job["_resource_key"],
        "circuit_scope": job["_circuit_scope"]}

def run_engine(workspace: Path, enriched: list[dict[str, Any]], dispositions: Mapping[str, str],
               scheduled: datetime, run_id: str) -> tuple[Path, list[dict[str, Any]], dict[str, TerminalRawArtifactV3]]:
    require(set(dispositions) == set(CELLS), "DISPOSITION_MAP")
    test_jobs = []
    for source in enriched:
        candidate = dict(source); candidate["enabled"] = True; validate_job(candidate); test_jobs.append(candidate)
    store = TerminalRawStoreV3(workspace / ".job-runtime" / "scheduler-composition-terminal" / run_id)
    artifacts: dict[str, TerminalRawArtifactV3] = {}
    def dispatch(job: Mapping[str, Any], context: Mapping[str, Any]) -> ProviderResultV1:
        cell = CELLS[JOB_IDS.index(job["id"])]
        artifact = store.persist(cell, terminal_evidence(dispositions[cell])); artifacts[artifact.ref] = artifact
        return ProviderResultNormalizerV3.normalize(artifact, operation_id=context["operation_id"],
            cell_id=cell, binding=context["prompt_binding_sha256"])
    state = workspace / ".job-runtime" / ("scheduler-composition-engine-" + run_id)
    engine = Engine(state, test_jobs, test_jobs[0]["_retry_policy"], dispatch,
                    workspace_root=workspace, max_workers=1)
    engine.tick(scheduled)
    require(len(artifacts) == 2, "ENGINE_ARTIFACTS")
    return state / "schedule.sqlite", test_jobs, artifacts

def _authority_and_transitions(bundle: Mapping[str, Any], jobs: list[Mapping[str, Any]],
                               scheduled: datetime) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    descriptors = {cell: dict(jobs[index]["prompt_artifact"]) for index, cell in enumerate(CELLS)}
    authority = {"prompt_descriptors": descriptors,
        "cell_bindings": {item["cell_id"]: item["prompt_binding_sha256"] for item in bundle["cells"]},
        "provider_results": {item["cell_id"]: item["provider_result_sha256"] for item in bundle["cells"]}}
    transitions = [IntegrationOwnerV3.build(bundle, authority)]
    transitions.append(DesignOwnerV3.build(transitions[-1], authority))
    transitions.append(MaterializationOwnerV3.build(transitions[-1], authority, scheduled))
    transitions.append(ProposalOwnerV3.build(transitions[-1], authority))
    transitions.append(ConfigOwnerV3.build(transitions[-1], authority))
    return authority, transitions

def build_with_second_cell_crash(rows: list[dict[str, Any]], artifacts: Mapping[str, TerminalRawArtifactV3],
                                 target: Path, reference: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    reference_bundle = BundleOwnerV3.build(rows, artifacts, reference)
    target.mkdir(mode=0o700)
    treatment_root = target / CELLS[1]; treatment_root.mkdir(mode=0o700)
    publication_gate = treatment_root / f"{CELLS[1]}.bundle.json"
    os.mkfifo(publication_gate, 0o600)
    pid = os.fork()
    if pid == 0:
        try:
            BundleOwnerV3.build(rows, artifacts, target)
        except BaseException:
            os._exit(87)
        os._exit(0)
    writer = None
    deadline = datetime.now().timestamp() + 10
    while datetime.now().timestamp() < deadline:
        waited, _ = os.waitpid(pid, os.WNOHANG)
        require(waited == 0, "SECOND_CELL_CHILD_EXITED_EARLY")
        try:
            writer = os.open(publication_gate, os.O_WRONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            break
        except OSError as error:
            require(error.errno in (6, 35), "SECOND_CELL_GATE_OPEN")
    require(writer is not None, "SECOND_CELL_GATE_TIMEOUT")
    # A nonblocking FIFO writer opens only when the child is blocked on the read
    # end, after treatment.raw was fsynced/closed and before bundle publication.
    os.kill(pid, 9)
    waited, status = os.waitpid(pid, 0)
    os.close(writer)
    require(waited == pid and os.WIFSIGNALED(status) and os.WTERMSIG(status) == 9,
            "SECOND_CELL_PROCESS_INTERRUPTION")
    publication_gate.unlink()
    before = {path.relative_to(target).as_posix(): path.read_bytes()
              for path in target.rglob("*") if path.is_file()}
    require(f"{CELLS[0]}/{CELLS[0]}.bundle.json" in before
            and f"{CELLS[1]}/{CELLS[1]}.raw" in before
            and f"{CELLS[1]}/{CELLS[1]}.bundle.json" not in before,
            "SECOND_CELL_CRASH_POINT")
    recovered = BundleOwnerV3.build(rows, artifacts, target)
    after_existing = {name: (target / name).read_bytes() for name in before}
    require(before == after_existing and recovered == reference_bundle, "SECOND_CELL_NO_REPLACE")
    return recovered, {"fault": "SIGKILL_AFTER_SECOND_CELL_RAW_FSYNC", "signal": 9,
        "synchronization": "external_fifo_reader_handshake", "actual_process_interruption": True,
        "existing_files_unchanged": True, "recovered": True,
        "preexisting_sha256": {name: hashlib.sha256(data).hexdigest()
                               for name, data in before.items()}}

def execute(*, repo_root: Path, source_path: Path, workspace: Path, output_root: Path,
            scheduled: datetime, dispositions: Optional[Mapping[str, str]] = None,
            second_cell_crash: bool = False) -> dict[str, Any]:
    config_path, config_doc, allocation_doc, prompt = install_documents(workspace, source_path, scheduled)
    loaded_config, loaded_jobs, published, enriched, cas_receipts = load_publish_enrich(workspace, config_path, prompt)
    selected = dict(dispositions or {"control": "PASS", "treatment": "PASS"})
    database, test_jobs, artifacts = run_engine(workspace, enriched, selected, scheduled,
                                                hashlib.sha256(canonical_bytes(selected)).hexdigest()[:12])
    bridge = ClosedDatabaseBridgeV3.snapshot(database, [job["id"] for job in test_jobs])
    leftovers = [suffix for suffix in ("-wal", "-shm", "-journal") if Path(str(database) + suffix).exists()]
    snapshots = list(database.parent.glob(f".{database.name}.v3-*.snapshot"))
    require(not leftovers and not snapshots, "DB_SNAPSHOT_CLEANUP")
    output_root = Path(output_root)
    if second_cell_crash:
        bundle, crash = build_with_second_cell_crash(bridge["rows"], artifacts, output_root,
            output_root.with_name(output_root.name + "-reference"))
    else:
        bundle = BundleOwnerV3.build(bridge["rows"], artifacts, output_root); crash = None
    plain_jobs = [_plain_job(job) for job in enriched]
    authority, transitions = _authority_and_transitions(bundle, plain_jobs, scheduled)
    old166 = verify_old166(repo_root)
    packet = {"contract": CONTRACT, "version": 1, "status": "CLEAN_PROVIDER_FREE",
        "config": {"document": config_doc, "sha256": digest(config_doc),
            "loaded_sha256": digest(loaded_config)},
        "allocation": {"document": allocation_doc, "sha256": digest(allocation_doc),
            "loaded_job_ids": [job["id"] for job in loaded_jobs]},
        "prompt": {"sha256": PROMPT_SHA256, "bytes": PROMPT_BYTES,
            "source_sha256": SOURCE_SHA256, "source_bytes": 2065,
            "raw_b64": base64.b64encode(prompt).decode("ascii")},
        "cas_jobs": plain_jobs, "cas_custody": cas_receipts,
        "test_enabled_job_ids": [job["id"] for job in test_jobs],
        "dispositions": selected, "schema9_fingerprint": bridge["receipt"]["schema_fingerprint"],
        "provider_rows": bridge["rows"], "database": bridge["receipt"],
        "raw_artifacts": {ref: {"sha256": item.sha256, "bytes": item.length,
            "raw_b64": base64.b64encode(item.raw).decode("ascii")} for ref, item in artifacts.items()},
        "bundle": bundle, "authority": authority,
        "stage_outputs": [item["output"] for item in transitions], "transitions": transitions,
        "second_cell_crash": crash, "cleanup": {"sidecars": [], "snapshots": []},
        "old166": old166, "semantic_review": verify_semantic_review(repo_root),
        "runtime_manifest": runtime_manifest(repo_root),
        "test_runtime": TEST_RUNTIME, "portability": PORTABILITY,
        "effects": dict(EFFECTS_V1), "sanitized": True}
    packet = seal_packet(packet)
    verify_packet(packet, repo_root)
    packet_sha = packet["packet_sha256"]
    return {"packet": packet, "packet_sha256": packet_sha, "bridge": bridge, "bundle": bundle,
        "authority": authority, "transitions": transitions, "artifacts": artifacts,
        "loaded_jobs": loaded_jobs, "enriched_jobs": enriched, "effects": dict(EFFECTS_V1),
        "decision": {"packet_sha256": packet_sha, "status": "PENDING_INDEPENDENT_REVIEW"},
        "producer": {"packet_sha256": packet_sha, "status": "PENDING_INDEPENDENT_REVIEW"}}
