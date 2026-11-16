"""Fresh v3 actual-prompt semantic vertical.

No provider client is imported. Deterministic terminal evidence crosses the real
Engine/schema-9 provider-result boundary, then public owner contracts create an
immutable raw-first bundle and downstream transition receipts.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import sqlite3
import stat
from typing import Any, Mapping, Optional, Sequence

from shared.job_runtime.config import load as load_config
from shared.job_runtime.engine import Engine, validate_job
from shared.job_runtime.engine_schema import SCHEMA9_FINGERPRINT, prompt_binding_sha256, verify_schema9
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1, PromptArtifactStore
from shared.job_runtime.provider_contract import (FailureKind, Phase, ProviderResultV1,
    ReplayContractV1, ReplayEffect, ResultStatus, Submission, TerminalProof)
from shared.job_runtime.retry_policy import RetryPolicyV2

PROMPT_SHA256 = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
SOURCE_SHA256 = "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a"
PROMPT_BYTES = 526
MODEL = "claude-fable-5-1"
PROVIDER = "claude_host"
GENERATION = "r6-data-quality-fable-v3-source526"
CELLS = ("control", "treatment")
DISPOSITIONS = ("PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN")
EFFECTS = {"provider": 0, "network": 0, "email": 0, "business": 0, "ixic": 0, "publication": 0}
OWNER_CHAIN = ("integration", "design", "materialization", "proposal", "config")

class VerticalV3Error(ValueError):
    pass

def require(test: bool, code: str) -> None:
    if not test:
        raise VerticalV3Error(code)

def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")

def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

def file_descriptor(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

def file_identity(path: Path) -> tuple[int, int, int, int]:
    info = path.stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)

def capture_actual_prompt(source: Path) -> tuple[bytes, PromptArtifactDescriptorV1, dict[str, Any]]:
    source = Path(source)
    info = source.lstat()
    require(stat.S_ISREG(info.st_mode) and not source.is_symlink(), "PROMPT_SOURCE_CUSTODY")
    raw = source.read_bytes()
    require((len(raw), hashlib.sha256(raw).hexdigest()) == (2065, SOURCE_SHA256), "PROMPT_SOURCE_HASH")
    value = json.loads(raw)
    prompt = value["prompt_utf8"].encode("utf-8")
    require((len(prompt), hashlib.sha256(prompt).hexdigest()) == (PROMPT_BYTES, PROMPT_SHA256),
            "PROMPT_ACTUAL_BYTES")
    descriptor = PromptArtifactDescriptorV1(1, f"pa1:sha256:{PROMPT_SHA256}:{PROMPT_BYTES}",
        PROMPT_SHA256, PROMPT_BYTES, SOURCE_SHA256, GENERATION, "native_v1")
    return prompt, descriptor, {"ref": descriptor.ref, "sha256": descriptor.sha256,
        "bytes": descriptor.length, "source_identity_sha256": descriptor.source_identity_sha256,
        "generation": descriptor.generation, "proof_origin": descriptor.provenance}

@dataclass(frozen=True)
class TerminalEvidence:
    raw: bytes
    phase: Phase
    submission: Submission

@dataclass(frozen=True)
class TerminalRawArtifactV3:
    ref: str
    raw: bytes
    sha256: str
    length: int
    phase: Phase
    submission: Submission

class TerminalRawStoreV3:
    """Persists exact terminal bytes before the owning parser sees them."""
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)

    def persist(self, cell_id: str, evidence: TerminalEvidence) -> TerminalRawArtifactV3:
        require(cell_id in CELLS and type(evidence.raw) is bytes, "TERMINAL_RAW_INPUT")
        sha = hashlib.sha256(evidence.raw).hexdigest()
        ref = f"tr3:sha256:{sha}:{len(evidence.raw)}:{cell_id}"
        path = self.root / f"{cell_id}.terminal.raw"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(evidence.raw)
            while view:
                count = os.write(fd, view)
                require(count > 0, "TERMINAL_RAW_WRITE")
                view = view[count:]
            os.fsync(fd)
        finally:
            os.close(fd)
        observed = path.read_bytes()
        require(observed == evidence.raw, "TERMINAL_RAW_PERSISTENCE")
        return TerminalRawArtifactV3(ref, observed, sha, len(observed), evidence.phase, evidence.submission)

class ProviderResultNormalizerV3:
    """Owning parser derives disposition only from a persisted raw artifact."""
    CONTRACT = "r6.provider-result-normalizer.v3"
    VERSION = 3

    @classmethod
    def normalize(cls, artifact: TerminalRawArtifactV3, *, operation_id: str,
                  cell_id: str, binding: str) -> ProviderResultV1:
        require(artifact.sha256 == hashlib.sha256(artifact.raw).hexdigest()
                and artifact.length == len(artifact.raw), "PARSER_RAW_ARTIFACT")
        disposition: str
        terminal_proof = TerminalProof.ABSENT
        failure = FailureKind.UNKNOWN
        status = ResultStatus.UNKNOWN
        code = "UNKNOWN_OUTCOME"
        parsed: Any = None
        try:
            parsed = json.loads(artifact.raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            disposition, code, failure = "MALFORMED", "MALFORMED_TERMINAL", FailureKind.PROVIDER
            status = ResultStatus.FAILED
        else:
            if artifact.phase is Phase.NOT_STARTED and parsed == {"stopped": True}:
                disposition, code, failure, status = "STOP", "STOPPED", FailureKind.POLICY, ResultStatus.FAILED
            elif artifact.phase is Phase.TERMINAL and parsed == {"terminal": "pass"}:
                disposition, code, failure, status = "PASS", "COMPLETED", FailureKind.NONE, ResultStatus.SUCCEEDED
                terminal_proof = TerminalProof.VERIFIED
            elif artifact.phase is Phase.TERMINAL and parsed == {"terminal": "fail"}:
                disposition, code, failure, status = "FAIL", "TERMINAL_FAILED", FailureKind.PROVIDER, ResultStatus.FAILED
                terminal_proof = TerminalProof.VERIFIED
            elif artifact.phase in (Phase.SUBMITTED, Phase.STREAMING) and isinstance(parsed, dict) and "terminal" not in parsed:
                disposition, code, failure = "MISSING", "MISSING_TERMINAL", FailureKind.MISSING_TERMINAL
            else:
                disposition, code, failure = "UNKNOWN", "UNKNOWN_OUTCOME", FailureKind.UNKNOWN
        receipt = {"contract": cls.CONTRACT, "version": cls.VERSION, "cell_id": cell_id,
            "artifact_sha256": PROMPT_SHA256, "binding_sha256": binding,
            "terminal_artifact_ref": artifact.ref, "terminal_sha256": artifact.sha256,
            "terminal_bytes": artifact.length, "parser_disposition": disposition,
            "parsed_terminal": parsed.get("terminal") if isinstance(parsed, dict) else None}
        return ProviderResultV1(PROVIDER, operation_id, artifact.phase, artifact.submission,
            terminal_proof, status, code, failure_kind=failure, receipt=receipt)

def terminal_evidence(name: str) -> TerminalEvidence:
    require(name in DISPOSITIONS, "DISPOSITION_CASE_INVALID")
    return {
        "PASS": TerminalEvidence(b'{"terminal":"pass"}', Phase.TERMINAL, Submission.DEFINITELY_SUBMITTED),
        "FAIL": TerminalEvidence(b'{"terminal":"fail"}', Phase.TERMINAL, Submission.DEFINITELY_SUBMITTED),
        "STOP": TerminalEvidence(b'{"stopped":true}', Phase.NOT_STARTED, Submission.NOT_SUBMITTED),
        "MALFORMED": TerminalEvidence(b'{"terminal":', Phase.TERMINAL, Submission.DEFINITELY_SUBMITTED),
        "MISSING": TerminalEvidence(b'{"progress":1}', Phase.STREAMING, Submission.DEFINITELY_SUBMITTED),
        "UNKNOWN": TerminalEvidence(b'{"transport":"ambiguous"}', Phase.CONNECTING, Submission.NOT_SUBMITTED),
    }[name]

def build_jobs(descriptor: PromptArtifactDescriptorV1, scheduled: datetime, *, prefix: str) -> list[dict[str, Any]]:
    jobs = []
    for index, cell in enumerate(CELLS):
        job = {"id": f"{prefix}-{cell}", "enabled": True, "replay_safe": False,
            "schedule": {"kind": "once", "at": scheduled.isoformat(), "grace_seconds": 240},
            "_provider": PROVIDER, "_prompt_artifact": descriptor,
            "_retry_policy": RetryPolicyV2(1, 1, 1, 240),
            "_replay_contract": ReplayContractV1(ReplayEffect.NONE, (Phase.NOT_STARTED,), f"v3/{cell}"),
            "_resource_key": "r6-v3-provider-free"}
        validate_job(job)
        jobs.append(job)
    return jobs

def run_engine(workspace: Path, descriptor: PromptArtifactDescriptorV1, disposition: str,
               scheduled: datetime, prefix: str) -> tuple[Path, list[dict[str, Any]], dict[str, TerminalRawArtifactV3]]:
    jobs = build_jobs(descriptor, scheduled, prefix=prefix)
    store = TerminalRawStoreV3(workspace / ".job-runtime" / "r6-v3-terminal-artifacts" / prefix)
    artifacts: dict[str, TerminalRawArtifactV3] = {}
    def dispatch(job: Mapping[str, Any], context: Mapping[str, Any]) -> ProviderResultV1:
        cell = CELLS[0] if job["id"].endswith("control") else CELLS[1]
        artifact = store.persist(cell, terminal_evidence(disposition))
        artifacts[artifact.ref] = artifact
        return ProviderResultNormalizerV3.normalize(artifact,
            operation_id=context["operation_id"], cell_id=cell,
            binding=context["prompt_binding_sha256"])
    state = workspace / ".job-runtime" / f"r6-v3-{prefix}"
    engine = Engine(state, jobs, RetryPolicyV2(1, 1, 1, 240), dispatch,
                    workspace_root=workspace, max_workers=1)
    engine.tick(scheduled)
    database = state / "schedule.sqlite"
    require(len(artifacts) == 2, "ENGINE_TERMINAL_ARTIFACT_COUNT")
    return database, jobs, artifacts

class ClosedDatabaseBridgeV3:
    CONTRACT = "r6.closed-schema9-bridge.v3"
    VERSION = 3

    @classmethod
    def snapshot(cls, database: Path, job_ids: Sequence[str]) -> dict[str, Any]:
        # Ownership is established by opening only after Engine.tick returned and by
        # this method owning every source/snapshot connection until both are closed.
        before_identity = file_identity(database)
        before = file_descriptor(database)
        snapshot = database.with_name(f".{database.name}.v3-{os.getpid()}.snapshot")
        require(not snapshot.exists(), "DB_SNAPSHOT_EXISTS")
        source = sqlite3.connect(f"file:{database}?mode=ro", uri=True, timeout=10)
        target = sqlite3.connect(snapshot)
        source_closed = target_closed = False
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close(); target_closed = True
            source.close(); source_closed = True
        after = file_descriptor(database)
        require(before == after, "DB_SOURCE_CHANGED")
        snap_descriptor = file_descriptor(snapshot)
        connection = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            schema = verify_schema9(connection)
            marks = ",".join("?" for _ in job_ids)
            rows = [dict(row) for row in connection.execute(f"""SELECT
              p.attempt_id,p.slot_id,p.canonical_json,p.canonical_sha256,p.provider,
              p.operation_id,p.phase,p.submission,p.terminal_proof,p.status,p.failure_kind,
              p.prompt_binding_sha256,s.job_id,s.artifact_ref,s.sha256,s.length,s.version,
              s.source_identity_sha256,s.generation,s.proof_origin
              FROM provider_results p JOIN attempts a ON a.attempt_id=p.attempt_id
              JOIN slots s ON s.slot_id=p.slot_id AND a.slot_id=s.slot_id
              JOIN prompt_artifacts d ON d.ref=s.artifact_ref AND d.sha256=s.sha256
              WHERE s.job_id IN ({marks}) ORDER BY s.job_id""", tuple(job_ids))]
        finally:
            connection.close()
            snapshot.unlink()
        require(schema == SCHEMA9_FINGERPRINT and len(rows) == len(job_ids), "DB_JOIN_INVALID")
        for row in rows:
            descriptor = {"artifact_ref": row["artifact_ref"], "sha256": row["sha256"],
                "length": row["length"], "version": row["version"],
                "source_identity_sha256": row["source_identity_sha256"],
                "generation": row["generation"], "proof_origin": row["proof_origin"]}
            binding = prompt_binding_sha256(row["job_id"], row["slot_id"], descriptor)
            require(binding == row["prompt_binding_sha256"] and row["operation_id"] ==
                    f"attempt/{row['attempt_id']}/prompt/{binding}", "DB_NATIVE_BINDING")
            require(hashlib.sha256(row["canonical_json"].encode()).hexdigest() == row["canonical_sha256"],
                    "DB_PROVIDER_RESULT_DIGEST")
        return {"rows": rows, "receipt": {"contract": cls.CONTRACT, "version": cls.VERSION,
            "schema_fingerprint": schema, "source_descriptor": before,
            "snapshot_descriptor": snap_descriptor, "source_connection_closed": source_closed,
            "snapshot_connection_closed": target_closed, "immutable_read_closed": True,
            "engine_tick_returned_before_snapshot": True, "owned_lifecycle": True,
            "joined_rows": len(rows)}}

class BundleOwnerV3:
    CONTRACT = "r6.actual-prompt-bundle.v3"
    VERSION = 3
    ROOT_KEYS = {"contract", "version", "prompt_sha256", "cells"}
    CELL_KEYS = {"contract", "version", "cell_id", "disposition", "attempt_id", "operation_id",
        "prompt", "prompt_binding_sha256", "provider_result_sha256", "terminal_artifact_ref",
        "raw_sha256", "raw_bytes", "denominator_included", "publication_attempts",
        "unknown_fenced", "bundle_sha256", "bundle_bytes", "raw_b64", "bundle_b64"}

    @classmethod
    def build(cls, rows: Sequence[Mapping[str, Any]], artifacts: Mapping[str, TerminalRawArtifactV3],
              root: Path, *, fault_after_raw: bool = False) -> dict[str, Any]:
        if root.exists():
            require(root.is_dir() and not root.is_symlink(), "BUNDLE_ROOT_CUSTODY")
        else:
            root.mkdir(mode=0o700, parents=False, exist_ok=False)
        cells = []
        for index, row in enumerate(rows):
            result = ProviderResultV1(**json.loads(row["canonical_json"]))
            require(result.canonical_sha256 == row["canonical_sha256"], "BUNDLE_PROVIDER_RESULT_DIGEST")
            receipt = dict(result.receipt)
            require(set(receipt) == {"contract", "version", "cell_id", "artifact_sha256",
                "binding_sha256", "terminal_artifact_ref", "terminal_sha256", "terminal_bytes",
                "parser_disposition", "parsed_terminal"}, "BUNDLE_PARSER_RECEIPT_SHAPE")
            ref = receipt["terminal_artifact_ref"]
            require(ref in artifacts, "BUNDLE_TERMINAL_ARTIFACT_MISSING")
            artifact = artifacts[ref]
            raw = artifact.raw
            require(receipt["terminal_sha256"] == artifact.sha256 == hashlib.sha256(raw).hexdigest()
                    and receipt["terminal_bytes"] == artifact.length == len(raw),
                    "BUNDLE_TERMINAL_ARTIFACT_MISMATCH")
            require(receipt["binding_sha256"] == row["prompt_binding_sha256"]
                    and receipt["artifact_sha256"] == PROMPT_SHA256,
                    "BUNDLE_PROMPT_BINDING_MISMATCH")
            disposition = receipt["parser_disposition"]
            cell = receipt["cell_id"]
            require(cell == CELLS[index] and disposition in DISPOSITIONS, "BUNDLE_CELL_ORDER")
            cell_root = root / cell; cell_root.mkdir(mode=0o700, exist_ok=True)
            raw_path = cell_root / f"{cell}.raw"
            bundle_path = cell_root / f"{cell}.bundle.json"
            if raw_path.exists():
                require(raw_path.read_bytes() == raw, "BUNDLE_RAW_DRIFT")
            else:
                raw_fd = os.open(raw_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    os.write(raw_fd, raw); os.fsync(raw_fd)
                finally: os.close(raw_fd)
            if fault_after_raw and index == 0 and not bundle_path.exists():
                raise VerticalV3Error("INJECTED_CRASH_AFTER_RAW")
            core = {"contract": cls.CONTRACT, "version": cls.VERSION, "cell_id": cell,
                "disposition": disposition, "attempt_id": row["attempt_id"],
                "operation_id": row["operation_id"], "prompt": {"sha256": PROMPT_SHA256,
                    "bytes": PROMPT_BYTES, "ref": f"pa1:sha256:{PROMPT_SHA256}:{PROMPT_BYTES}"},
                "prompt_binding_sha256": row["prompt_binding_sha256"],
                "provider_result_sha256": row["canonical_sha256"],
                "terminal_artifact_ref": artifact.ref,
                "raw_sha256": artifact.sha256, "raw_bytes": artifact.length,
                "denominator_included": True, "publication_attempts": 0,
                "unknown_fenced": disposition in ("MISSING", "UNKNOWN")}
            encoded = canonical_bytes(core)
            if bundle_path.exists():
                require(bundle_path.read_bytes() == encoded, "BUNDLE_FILE_DRIFT")
            else:
                fd = os.open(bundle_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    os.write(fd, encoded); os.fsync(fd)
                finally: os.close(fd)
            cells.append({**core, "bundle_sha256": hashlib.sha256(encoded).hexdigest(),
                          "bundle_bytes": len(encoded), "raw_b64": base64.b64encode(raw).decode("ascii"),
                          "bundle_b64": base64.b64encode(encoded).decode("ascii")})
        return cls.validate({"contract": cls.CONTRACT, "version": cls.VERSION,
            "prompt_sha256": PROMPT_SHA256, "cells": cells})

    @classmethod
    def validate(cls, value: Mapping[str, Any]) -> dict[str, Any]:
        value = dict(value)
        require(set(value) == cls.ROOT_KEYS and value["contract"] == cls.CONTRACT
                and value["version"] == cls.VERSION and value["prompt_sha256"] == PROMPT_SHA256
                and type(value["cells"]) is list and len(value["cells"]) == 2,
                "BUNDLE_CONTRACT")
        for index, cell in enumerate(value["cells"]):
            require(set(cell) == cls.CELL_KEYS and cell["cell_id"] == CELLS[index]
                    and cell["prompt"] == {"sha256": PROMPT_SHA256, "bytes": 526,
                        "ref": f"pa1:sha256:{PROMPT_SHA256}:526"}
                    and hashlib.sha256(base64.b64decode(cell["raw_b64"])).hexdigest() == cell["raw_sha256"]
                    and len(base64.b64decode(cell["raw_b64"])) == cell["raw_bytes"]
                    and hashlib.sha256(base64.b64decode(cell["bundle_b64"])).hexdigest() == cell["bundle_sha256"]
                    and len(base64.b64decode(cell["bundle_b64"])) == cell["bundle_bytes"],
                    "BUNDLE_CELL_CONTRACT")
        return value

def _validate_cell_maps(descriptors: Mapping[str, Any], bindings: Mapping[str, Any],
                        results: Mapping[str, Any], expected: Mapping[str, Any], code: str) -> None:
    require(type(expected) is dict and set(expected) == {"prompt_descriptors", "cell_bindings", "provider_results"}, code)
    require(type(descriptors) is dict and type(bindings) is dict and type(results) is dict
            and tuple(descriptors) == CELLS and tuple(bindings) == CELLS and tuple(results) == CELLS,
            code)
    for cell in CELLS:
        descriptor = descriptors[cell]
        require(type(descriptor) is dict and set(descriptor) == {"version", "ref", "sha256", "length",
                    "source_identity_sha256", "generation", "proof_origin"}
                and descriptor == expected["prompt_descriptors"][cell]
                and descriptor["version"] == 1
                and descriptor["ref"] == f"pa1:sha256:{PROMPT_SHA256}:{PROMPT_BYTES}"
                and descriptor["sha256"] == PROMPT_SHA256
                and descriptor["length"] == PROMPT_BYTES
                and type(descriptor["source_identity_sha256"]) is str
                and re.fullmatch(r"[0-9a-f]{64}", descriptor["source_identity_sha256"])
                and descriptor["generation"] == GENERATION
                and descriptor["proof_origin"] == "native_v1"
                and type(bindings[cell]) is str and re.fullmatch(r"[0-9a-f]{64}", bindings[cell])
                and bindings[cell] == expected["cell_bindings"][cell]
                and type(results[cell]) is str and re.fullmatch(r"[0-9a-f]{64}", results[cell])
                and results[cell] == expected["provider_results"][cell], code)

def _stage_common(owner: str, predecessor: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    return {"contract": f"r6.{owner}-owner.v3", "version": 3,
        "predecessor_contract": predecessor["contract"], "predecessor_version": predecessor["version"],
        "input_digest": digest(predecessor), "activation": False, "effects": dict(EFFECTS),
        "prompt_descriptors": {cell: dict(authority["prompt_descriptors"][cell]) for cell in CELLS},
        "cell_bindings": {cell: authority["cell_bindings"][cell] for cell in CELLS},
        "provider_results": {cell: authority["provider_results"][cell] for cell in CELLS}}

def _receipt(owner: str, predecessor: Mapping[str, Any], output: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
    return {"owner_contract": f"r6.{owner}-owner.v3", "owner_version": 3,
        "predecessor_contract": predecessor["contract"], "predecessor_version": predecessor["version"],
        "input_digest": digest(predecessor), "output_digest": digest(output),
        "prompt_descriptor_map_digest": digest(authority["prompt_descriptors"]),
        "cell_bindings": {cell: authority["cell_bindings"][cell] for cell in CELLS},
        "provider_results": {cell: authority["provider_results"][cell] for cell in CELLS}}

def _envelope(owner: str, predecessor: Mapping[str, Any], output: Mapping[str, Any],
              authority: Mapping[str, Any]) -> dict[str, Any]:
    return {"input": predecessor, "output": output,
            "receipt": _receipt(owner, predecessor, output, authority)}

def _validate_envelope(value: Mapping[str, Any], owner_contract: str,
                       predecessor_contract: str, authority: Mapping[str, Any], code: str) -> None:
    require(type(value) is dict and set(value) == {"input", "output", "receipt"}
            and type(value["input"]) is dict and type(value["output"]) is dict
            and type(value["receipt"]) is dict, code)
    source, output, receipt = value["input"], value["output"], value["receipt"]
    require(output.get("contract") == owner_contract and output.get("version") == 3
            and source.get("contract") == predecessor_contract and source.get("version") == 3
            and set(receipt) == {"owner_contract", "owner_version", "predecessor_contract",
                "predecessor_version", "input_digest", "output_digest",
                "prompt_descriptor_map_digest", "cell_bindings", "provider_results"}
            and receipt["owner_contract"] == owner_contract and receipt["owner_version"] == 3
            and receipt["predecessor_contract"] == predecessor_contract
            and receipt["predecessor_version"] == 3
            and receipt["input_digest"] == digest(source) == output.get("input_digest")
            and receipt["output_digest"] == digest(output)
            and receipt["prompt_descriptor_map_digest"] == digest(authority["prompt_descriptors"]), code)
    _validate_cell_maps(output["prompt_descriptors"], output["cell_bindings"], output["provider_results"], authority, code)
    _validate_cell_maps(output["prompt_descriptors"], receipt["cell_bindings"], receipt["provider_results"], authority, code)

def _validate_output(value: Mapping[str, Any], predecessor: Mapping[str, Any], keys: set[str],
                     owner: str, authority: Mapping[str, Any]) -> None:
    require(type(value) is dict and set(value) == keys
            and value["contract"] == f"r6.{owner}-owner.v3" and value["version"] == 3
            and value["predecessor_contract"] == predecessor["contract"]
            and value["predecessor_version"] == predecessor["version"]
            and value["input_digest"] == digest(predecessor)
            and value["activation"] is False and value["effects"] == EFFECTS,
            owner.upper() + "_OUTPUT")
    _validate_cell_maps(value["prompt_descriptors"], value["cell_bindings"], value["provider_results"],
                        authority, owner.upper() + "_MAPS")

_COMMON_KEYS = {"contract", "version", "predecessor_contract", "predecessor_version", "input_digest",
    "activation", "effects", "prompt_descriptors", "cell_bindings", "provider_results"}

class IntegrationOwnerV3:
    CONTRACT = "r6.integration-owner.v3"
    KEYS = _COMMON_KEYS | {"joined_rows", "bundle_digest"}
    @classmethod
    def build(cls, bundle: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
        BundleOwnerV3.validate(bundle)
        _validate_cell_maps(authority["prompt_descriptors"], authority["cell_bindings"],
                            authority["provider_results"], authority, "INTEGRATION_AUTHORITY")
        output = {**_stage_common("integration", bundle, authority), "joined_rows": 2,
                  "bundle_digest": digest(bundle)}
        cls.validate(output, bundle, authority)
        return _envelope("integration", bundle, output, authority)
    @classmethod
    def validate(cls, value: Mapping[str, Any], predecessor: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_output(value, predecessor, cls.KEYS, "integration", authority)
        require(value["joined_rows"] == 2 and value["bundle_digest"] == digest(predecessor), "INTEGRATION_SEMANTICS")
    @classmethod
    def validate_input(cls, envelope: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_envelope(envelope, cls.CONTRACT, BundleOwnerV3.CONTRACT, authority, "INTEGRATION_ENVELOPE")
        cls.validate(envelope["output"], envelope["input"], authority)

class DesignOwnerV3:
    CONTRACT = "r6.design-owner.v3"
    KEYS = _COMMON_KEYS | {"arms", "budget"}
    @classmethod
    def build(cls, prior: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
        IntegrationOwnerV3.validate_input(prior, authority); source = prior["output"]
        output = {**_stage_common("design", source, authority), "arms": list(CELLS),
            "budget": {"currency": "USD", "per_arm_max_usd": 0.02, "aggregate_max_usd": 0.04,
                "user_approved": True, "billed": False, "prompt_utf8_bytes": 526, "prompt_tokens": None}}
        require(output["input_digest"] == prior["receipt"]["output_digest"], "DESIGN_INHERITED_DIGEST")
        cls.validate(output, source, authority); return _envelope("design", source, output, authority)
    @classmethod
    def validate(cls, value: Mapping[str, Any], predecessor: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_output(value, predecessor, cls.KEYS, "design", authority)
        require(value["arms"] == list(CELLS) and value["budget"] == {"currency": "USD",
            "per_arm_max_usd": 0.02, "aggregate_max_usd": 0.04, "user_approved": True,
            "billed": False, "prompt_utf8_bytes": 526, "prompt_tokens": None}, "DESIGN_SEMANTICS")
    @classmethod
    def validate_input(cls, envelope: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_envelope(envelope, cls.CONTRACT, IntegrationOwnerV3.CONTRACT, authority, "DESIGN_ENVELOPE")
        cls.validate(envelope["output"], envelope["input"], authority)

class MaterializationOwnerV3:
    CONTRACT = "r6.materialization-owner.v3"
    KEYS = _COMMON_KEYS | {"scheduled_at", "installed"}
    @classmethod
    def build(cls, prior: Mapping[str, Any], authority: Mapping[str, Any], scheduled: datetime) -> dict[str, Any]:
        DesignOwnerV3.validate_input(prior, authority); source = prior["output"]
        output = {**_stage_common("materialization", source, authority),
                  "scheduled_at": scheduled.isoformat(), "installed": False}
        require(output["input_digest"] == prior["receipt"]["output_digest"], "MATERIALIZATION_INHERITED_DIGEST")
        cls.validate(output, source, authority); return _envelope("materialization", source, output, authority)
    @classmethod
    def validate(cls, value: Mapping[str, Any], predecessor: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_output(value, predecessor, cls.KEYS, "materialization", authority)
        require(type(value["scheduled_at"]) is str and value["scheduled_at"].endswith("+00:00")
                and value["installed"] is False, "MATERIALIZATION_SEMANTICS")
    @classmethod
    def validate_input(cls, envelope: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_envelope(envelope, cls.CONTRACT, DesignOwnerV3.CONTRACT, authority, "MATERIALIZATION_ENVELOPE")
        cls.validate(envelope["output"], envelope["input"], authority)

class ProposalOwnerV3:
    CONTRACT = "r6.proposal-owner.v3"
    KEYS = _COMMON_KEYS | {"apply", "classification"}
    @classmethod
    def build(cls, prior: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
        MaterializationOwnerV3.validate_input(prior, authority); source = prior["output"]
        output = {**_stage_common("proposal", source, authority),
                  "apply": False, "classification": "INERT_V3_CANDIDATE"}
        require(output["input_digest"] == prior["receipt"]["output_digest"], "PROPOSAL_INHERITED_DIGEST")
        cls.validate(output, source, authority); return _envelope("proposal", source, output, authority)
    @classmethod
    def validate(cls, value: Mapping[str, Any], predecessor: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_output(value, predecessor, cls.KEYS, "proposal", authority)
        require(value["apply"] is False and value["classification"] == "INERT_V3_CANDIDATE", "PROPOSAL_SEMANTICS")
    @classmethod
    def validate_input(cls, envelope: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_envelope(envelope, cls.CONTRACT, MaterializationOwnerV3.CONTRACT, authority, "PROPOSAL_ENVELOPE")
        cls.validate(envelope["output"], envelope["input"], authority)

class ConfigOwnerV3:
    CONTRACT = "r6.config-owner.v3"
    KEYS = _COMMON_KEYS | {"load_required", "engine_validate_job_required"}
    @classmethod
    def build(cls, prior: Mapping[str, Any], authority: Mapping[str, Any]) -> dict[str, Any]:
        ProposalOwnerV3.validate_input(prior, authority); source = prior["output"]
        output = {**_stage_common("config", source, authority),
                  "load_required": True, "engine_validate_job_required": True}
        require(output["input_digest"] == prior["receipt"]["output_digest"], "CONFIG_INHERITED_DIGEST")
        cls.validate(output, source, authority); return _envelope("config", source, output, authority)
    @classmethod
    def validate(cls, value: Mapping[str, Any], predecessor: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_output(value, predecessor, cls.KEYS, "config", authority)
        require(value["load_required"] is True and value["engine_validate_job_required"] is True,
                "CONFIG_SEMANTICS")
    @classmethod
    def validate_input(cls, envelope: Mapping[str, Any], authority: Mapping[str, Any]) -> None:
        _validate_envelope(envelope, cls.CONTRACT, ProposalOwnerV3.CONTRACT, authority, "CONFIG_ENVELOPE")
        cls.validate(envelope["output"], envelope["input"], authority)

def verify_old166(repo_root: Path) -> dict[str, Any]:
    path = repo_root / "tuning/architecture/r6_data_quality_fable_v2_semantic_vertical_v2/predecessor-byte-lock-v1.json"
    raw = path.read_bytes(); lock = json.loads(raw)
    require(lock["member_count"] == 166 and len(lock["members"]) == 166, "OLD166_COUNT")
    for member in lock["members"]:
        data = (repo_root / member["path"]).read_bytes()
        require((len(data), hashlib.sha256(data).hexdigest()) == (member["bytes"], member["sha256"]),
                "OLD166_DRIFT")
    return {"member_count": 166, "lock_file_sha256": hashlib.sha256(raw).hexdigest(),
            "members_digest": digest(lock["members"])}

def render_config(scheduled: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    schedule = {"kind": "once", "at": scheduled.isoformat(), "grace_seconds": 240}
    config = {"schema_version": 2, "tick_seconds": 5, "heartbeat_seconds": 10,
        "stale_seconds": 60, "max_workers": 1,
        "retry": {"version": 2, "max_attempts": 1, "base_delay_seconds": 1,
                  "max_delay_seconds": 1, "deadline_seconds": 240, "jitter": "sha256-full-jitter-v1"},
        "model_profiles": {"fable-v3": {"provider": PROVIDER, "model": MODEL,
            "effort": "low", "timeout_seconds": 300,
            "auth_home": ".job-runtime/config/fable-v3-auth", "max_budget_usd": 0.02}},
        "allocation_files": [".job-runtime/config/fable-v3-allocation.json"], "source_paths": []}
    allocation = {"schema_version": 2, "jobs": [{"id": f"fable-v3-{cell}", "enabled": False,
        "schedule": schedule, "model_profile": "fable-v3",
        "prompt_file": ".job-runtime/config/prompts/fable-v3.txt",
        "replay_contract": {"version": 1, "effect": "none", "automatic_phases": ["not_started"],
            "slot_operation_scope": f"v3/{cell}", "reconciliation_adapter": None}} for cell in CELLS]}
    return config, allocation

def install_and_load_config(workspace: Path, prompt: bytes, config: Mapping[str, Any],
                            allocation: Mapping[str, Any]) -> list[dict[str, Any]]:
    base = workspace / ".job-runtime" / "config"
    workspace.chmod(0o700)
    (workspace / ".job-runtime").chmod(0o700)
    base.mkdir(mode=0o700, parents=True, exist_ok=True); base.chmod(0o700)
    (base / "prompts").mkdir(mode=0o700, parents=True, exist_ok=True); (base / "prompts").chmod(0o700)
    (base / "fable-v3-auth").mkdir(mode=0o700, exist_ok=True)
    prompt_path = base / "prompts" / "fable-v3.txt"; prompt_path.write_bytes(prompt); prompt_path.chmod(0o600)
    allocation_path = base / "fable-v3-allocation.json"; allocation_path.write_bytes(canonical_bytes(allocation)); allocation_path.chmod(0o600)
    config_path = base / "config-v3.json"; config_path.write_bytes(canonical_bytes(config)); config_path.chmod(0o600)
    old = Path.cwd(); os.chdir(workspace)
    try: _, jobs = load_config(config_path, workspace)
    finally: os.chdir(old)
    require(all(j["_prompt_capture"].sha256 == PROMPT_SHA256 and j["_prompt_capture"].length == 526 for j in jobs),
            "CONFIG_CAPTURE")
    store = PromptArtifactStore(workspace)
    for job in jobs:
        artifact = store.publish(job["_prompt_capture"], GENERATION, "native_v1")
        candidate = {k: v for k, v in job.items() if k != "_prompt_capture"}
        candidate.update({"replay_safe": False, "_provider": PROVIDER,
            "_retry_policy": RetryPolicyV2(1,1,1,240), "_prompt_artifact": artifact,
            "_resource_key": "r6-v3-provider-free"})
        validate_job(candidate)
    return jobs

def exercise_disposition(source_path: Path, workspace: Path, output_root: Path,
                         disposition: str, scheduled: datetime) -> dict[str, Any]:
    prompt, descriptor, _ = capture_actual_prompt(source_path)
    database, jobs, artifacts = run_engine(workspace, descriptor, disposition, scheduled,
                                f"case-{disposition.lower()}")
    bridge = ClosedDatabaseBridgeV3.snapshot(database, [job["id"] for job in jobs])
    bundle = BundleOwnerV3.build(bridge["rows"], artifacts, output_root)
    return {"prompt_bytes": prompt, "bridge": bridge, "bundle": bundle,
            "terminal_artifacts": artifacts}

def execute(*, repo_root: Path, source_path: Path, workspace: Path, output_root: Path,
            scheduled: datetime, fault: Optional[str] = None) -> dict[str, Any]:
    prompt, descriptor, prompt_view = capture_actual_prompt(source_path)
    old166 = verify_old166(repo_root)
    database, jobs, artifacts = run_engine(workspace, descriptor, "PASS", scheduled, "nominal")
    bridge = ClosedDatabaseBridgeV3.snapshot(database, [job["id"] for job in jobs])
    if fault == "bridge": bridge["rows"][0]["canonical_sha256"] = "0" * 64
    bundle = BundleOwnerV3.build(bridge["rows"], artifacts, output_root)
    descriptor_value = {"version": descriptor.version, "ref": descriptor.ref, "sha256": descriptor.sha256,
        "length": descriptor.length, "source_identity_sha256": descriptor.source_identity_sha256,
        "generation": descriptor.generation, "proof_origin": descriptor.provenance}
    authority = {"prompt_descriptors": {cell: dict(descriptor_value) for cell in CELLS},
        "cell_bindings": {cell["cell_id"]: cell["prompt_binding_sha256"] for cell in bundle["cells"]},
        "provider_results": {cell["cell_id"]: cell["provider_result_sha256"] for cell in bundle["cells"]}}
    _validate_cell_maps(authority["prompt_descriptors"], authority["cell_bindings"],
                        authority["provider_results"], authority, "ROOT_CELL_AUTHORITY")
    transitions: list[dict[str, Any]] = []
    if fault == "integration": raise VerticalV3Error("INJECTED_INTEGRATION_BOUNDARY")
    transitions.append(IntegrationOwnerV3.build(bundle, authority))
    if fault == "design": raise VerticalV3Error("INJECTED_DESIGN_BOUNDARY")
    transitions.append(DesignOwnerV3.build(transitions[-1], authority))
    if fault == "materialization": raise VerticalV3Error("INJECTED_MATERIALIZATION_BOUNDARY")
    transitions.append(MaterializationOwnerV3.build(transitions[-1], authority, scheduled))
    if fault == "proposal": raise VerticalV3Error("INJECTED_PROPOSAL_BOUNDARY")
    transitions.append(ProposalOwnerV3.build(transitions[-1], authority))
    if fault == "config": raise VerticalV3Error("INJECTED_CONFIG_BOUNDARY")
    transitions.append(ConfigOwnerV3.build(transitions[-1], authority))
    stage_outputs = [transition["output"] for transition in transitions]
    config, allocation = render_config(scheduled)
    loaded_jobs = install_and_load_config(workspace, prompt, config, allocation)
    packet = {"contract": "r6.semantic-evidence-packet.v3", "version": 3,
        "prompt_source": {"sha256": SOURCE_SHA256, "bytes": 2065,
            "fixture_ref": "shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_semantic_vertical_v3/prompt-source-v3.json"},
        "prompt": prompt_view, "prompt_raw_b64": base64.b64encode(prompt).decode("ascii"),
        "schema9_fingerprint": SCHEMA9_FINGERPRINT, "provider_rows": bridge["rows"],
        "database": bridge["receipt"], "bundle": bundle, "stage_outputs": stage_outputs,
        "transitions": transitions, "old166": old166,
        "config": {"sha256": digest(config), "allocation_sha256": digest(allocation),
            "load_job_count": len(loaded_jobs), "engine_validate_job": True},
        "interpreter": {"implementation": "CPython", "minimum": "3.9",
            "required_test_versions": ["3.9", "3.12"]},
        "tests": {"v3_commands": [
                "/usr/bin/python3 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.test_vertical -q",
                ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.test_vertical -q"],
            "combined_command": "/usr/bin/python3 -m unittest shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.test_vertical shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v1.test_vertical shared.job_runtime.tests.candidates.r6_data_quality_fable_v2_semantic_vertical_v2.test_vertical -q",
            "network": False},
        "effects": dict(EFFECTS), "sanitized": True}
    packet_sha = digest(packet)
    decision = {"contract": "r6.semantic-decision.v3", "packet_sha256": packet_sha,
        "decision": "PENDING_INDEPENDENT_REVIEW", "activation": False, "effects": dict(EFFECTS)}
    producer = {"contract": "r6.semantic-producer-receipt.v3", "packet_sha256": packet_sha,
        "status": "PENDING_INDEPENDENT_REVIEW", "source_closure_required": True}
    return {"prompt_bytes": prompt, "prompt": prompt_view, "bridge": bridge, "bundle": bundle,
        "stages": stage_outputs, "transitions": transitions, "config": config,
        "allocation": allocation, "packet": packet, "packet_sha256": packet_sha,
        "decision": decision, "producer_receipt": producer, "effects": dict(EFFECTS),
        "old166": old166, "terminal_artifacts": artifacts}

