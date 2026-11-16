"""Disjoint provider-free semantic runtime chain over the reviewed Fable contracts.

This module never imports a provider client.  Engine dispatch receives deterministic
in-process ProviderResultV1 values, while every provider/network/publication effect
remains fenced at zero.  The reviewed v1 A/B bundle runtime is reused unchanged;
its historical one-byte frozen input is reported separately from the real 526-byte
prompt used by Engine so the two lineages cannot be confused.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import stat
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.bundle import BundleError, read_bundle
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.contracts import (
    CELL_ORDER, DQ_CHECKS, FROZEN_INPUTS, MODEL_ID, canonical_bytes as ab_canonical_bytes,
    sha256_json as ab_sha256_json, validate_result,
)
from shared.job_runtime.candidates.r6_data_quality_fable_ab_v1.runner import run_pair
from shared.job_runtime.engine import Engine, validate_job
from shared.job_runtime.engine_schema import SCHEMA9_FINGERPRINT, prompt_binding_sha256, verify_schema9
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import (
    FailureKind, Phase, ProviderResultV1, ReplayContractV1, ReplayEffect,
    ResultStatus, Submission, TerminalProof,
)
from shared.job_runtime.retry_policy import RetryPolicyV2

PROMPT_SHA256 = "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b"
SOURCE_SHA256 = "26d9a937f50dc22dade3251831e7860b4a7188c3001d5717ed4aac4d4ccac01a"
PROMPT_BYTES = 526
MODEL = "claude-fable-5-1"
PROVIDER = "claude_host"
JOB_IDS = ("fable-v2-0", "fable-v2-1")
RESOURCE_KEY = "fable-v2-serialized"
PROFILE = "fable-v2"
GENERATION = "schema9-isolated-canary-q1-ab-payload-v1"
PROMPT_FILE = ".job-runtime/config/prompts/fable-v2.txt"
ALLOCATION_FILE = ".job-runtime/config/fable-v2-allocation.json"
AUTH_HOME = ".job-runtime/config/fable-v2-auth"
RUBRIC_SHA256 = "81069b2ce57f30e56d70e7a2edd4672991838ebce1e2369b48effb8adde53d8f"
EFFECTS = {"provider": 0, "network": 0, "service": 0, "email": 0,
           "publication": 0, "scheduler": 0}
TERMINALS = ("PASS", "FAIL", "STOP", "MALFORMED", "MISSING", "UNKNOWN")
STATUS_BINDING = {
    "PASS": ResultStatus.SUCCEEDED, "FAIL": ResultStatus.FAILED,
    "STOP": ResultStatus.FAILED, "MALFORMED": ResultStatus.FAILED,
    "MISSING": ResultStatus.UNKNOWN, "UNKNOWN": ResultStatus.UNKNOWN,
}
MANIFESTS = (
    ("r6_data_quality_fable_ab_v2", "6bca8d52cd031a535b7222646c9f6c89d83f5c2c4d2a90de360dfafbcee44f70"),
    ("r6_data_quality_fable_adapter_v2", "5561430bfb65394468ee8fbb792493fc07c60a61cd1351af2a42df79970cfff5"),
    ("r6_data_quality_fable_allocation_bridge_v2", "3b2b006cdcb9e33c3a9ca1c6f045359bf38d8e9ee58f02a33e989a707d10f895"),
    ("r6_data_quality_fable_allocation_integration_v2", "b39bbd17ccfc54f8c47ddd964066a28af63bfb1260de96efb56f74b6a897ee2d"),
    ("r6_data_quality_fable_allocation_design_v2", "cd3aec4d07366cd0d1bcf6c91216ed850090ac19e3ca84e5f45111f16f370e12"),
    ("r6_data_quality_fable_allocation_materialization_v2", "8fb533abda3955a2c67e2cb2c61d11fde7d773e9503533ff2883a5cb58de3687"),
    ("r6_data_quality_fable_installation_proposal_v2", "bfb199b7cc793ad4a1d75b4120a97173a4ca357e4bc1031b191b4ab6b7c9b982"),
    ("r6_data_quality_fable_config_translation_v2", "ad6cbf3b89d79fcd6acac334cffb4fa76917c5589372aa638be6bc2216d6890d"),
)
SHA = re.compile(r"[0-9a-f]{64}\Z")

class VerticalError(ValueError):
    """Fixed diagnostic for the isolated candidate."""

def require(value: bool, code: str) -> None:
    if not value:
        raise VerticalError(code)

def plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(item) for item in value]
    return value

def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(plain(value), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise VerticalError("CANONICAL_JSON") from None

def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()

def utc_second(value: datetime, code: str) -> datetime:
    require(type(value) is datetime and value.tzinfo is not None and value.utcoffset() is not None,
            code)
    require(value.utcoffset().total_seconds() == 0 and value.microsecond == 0, code)
    return value.astimezone(timezone.utc)

def iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")

def _safe_regular(path: Path, *, mode: int, code: str) -> tuple[bytes, os.stat_result]:
    path = Path(path)
    try:
        before = path.lstat()
    except OSError:
        raise VerticalError(code) from None
    require(stat.S_ISREG(before.st_mode) and not path.is_symlink() and before.st_uid == os.getuid()
            and stat.S_IMODE(before.st_mode) == mode and before.st_nlink == 1, code)
    raw = path.read_bytes()
    after = path.lstat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), code)
    return raw, before

def capture_prompt(source_path: Path) -> tuple[PromptArtifactDescriptorV1, bytes, Mapping[str, Any]]:
    raw, _ = _safe_regular(Path(source_path), mode=0o600, code="PROMPT_SOURCE_CUSTODY")
    require(hashlib.sha256(raw).hexdigest() == SOURCE_SHA256, "PROMPT_SOURCE_HASH")
    try:
        value = json.loads(raw)
        text = value["prompt_utf8"]
        prompt = text.encode("utf-8")
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise VerticalError("PROMPT_SOURCE_FORMAT") from None
    require(len(prompt) == PROMPT_BYTES and hashlib.sha256(prompt).hexdigest() == PROMPT_SHA256,
            "PROMPT_BINDING")
    descriptor = PromptArtifactDescriptorV1(
        1, f"pa1:sha256:{PROMPT_SHA256}:{PROMPT_BYTES}", PROMPT_SHA256, PROMPT_BYTES,
        SOURCE_SHA256, GENERATION, "native_v1")
    custody = {"logical_path": f"{source_path}:prompt_utf8", "sha256": PROMPT_SHA256,
               "bytes": PROMPT_BYTES, "source_sha256": SOURCE_SHA256,
               "source_generation": GENERATION, "prompt_utf8_bytes": PROMPT_BYTES}
    return descriptor, prompt, MappingProxyType(custody)

def _checks(enabled: bool) -> list[dict[str, str]] | None:
    if not enabled:
        return None
    return [{"name": name, "status": "PASS", "code": "CHECK_PASS"} for name in DQ_CHECKS]

def _provider_result(index: int, context: Mapping[str, Any], terminal: str = "PASS") -> ProviderResultV1:
    require(terminal in TERMINALS, "TERMINAL_INVALID")
    if terminal == "STOP":
        phase, submission, proof, failure = (Phase.NOT_STARTED, Submission.NOT_SUBMITTED,
                                             TerminalProof.ABSENT, FailureKind.CONFIG)
    elif terminal in ("MISSING", "UNKNOWN"):
        phase, submission, proof = (Phase.TERMINAL, Submission.POSSIBLY_SUBMITTED,
                                    TerminalProof.ABSENT)
        failure = FailureKind.MISSING_TERMINAL if terminal == "MISSING" else FailureKind.UNKNOWN
    else:
        phase, submission, proof = (Phase.TERMINAL, Submission.DEFINITELY_SUBMITTED,
                                    TerminalProof.VERIFIED)
        failure = FailureKind.NONE if terminal == "PASS" else FailureKind.PROVIDER
    receipt = {
        "version": 2, "cell_id": CELL_ORDER[index], "configured_model": MODEL,
        "provider_reported_model": MODEL, "artifact_sha256": PROMPT_SHA256,
        "artifact_utf8_bytes": PROMPT_BYTES, "source_sha256": SOURCE_SHA256,
        "terminal_state": terminal, "terminal_ascii": f"semantic-v2-{index}-{terminal}",
        "dq_checks": _checks(index == 1),
    }
    return ProviderResultV1(
        PROVIDER, context["operation_id"], phase, submission, proof,
        STATUS_BINDING[terminal], f"FABLE_SEMANTIC_V2_{terminal}",
        failure_kind=failure, receipt=receipt)

def build_jobs(descriptor: PromptArtifactDescriptorV1, scheduled: datetime,
               grace_seconds: int, *, enabled: bool) -> list[dict[str, Any]]:
    schedule = {"kind": "once", "at": iso(scheduled), "grace_seconds": grace_seconds}
    jobs = []
    for index, job_id in enumerate(JOB_IDS):
        job = {
            "id": job_id, "enabled": enabled, "replay_safe": False, "schedule": dict(schedule),
            "_provider": PROVIDER,
            "_replay_contract": ReplayContractV1(ReplayEffect.NONE, (Phase.NOT_STARTED,),
                                                   f"fable/v2/{index}"),
            "_retry_policy": RetryPolicyV2(1, 1, 1, grace_seconds),
            "_prompt_artifact": descriptor, "_resource_key": RESOURCE_KEY,
        }
        validate_job(job)
        jobs.append(job)
    return jobs

def run_engine(state_root: Path, jobs: Sequence[dict[str, Any]], when: datetime,
               *, terminal: str = "PASS") -> tuple[Path, Mapping[str, Any]]:
    require(all(job["enabled"] is True for job in jobs), "ENGINE_JOBS_NOT_ENABLED")
    def dispatch(job: Mapping[str, Any], context: Mapping[str, Any]) -> ProviderResultV1:
        return _provider_result(JOB_IDS.index(job["id"]), context, terminal)
    root = Path(state_root)
    engine = Engine(root, list(jobs), {"max_attempts": 1, "backoff_seconds": 1,
                                      "max_backoff_seconds": 1}, dispatch,
                    workspace_root=root.parents[1], clock=lambda: when, max_workers=1)
    summary = engine.tick(when)
    require(summary["dispatched"] == 2, "ENGINE_DISPATCH_COUNT")
    return engine.path, MappingProxyType(dict(summary))

def source_expectation(path: Path) -> Mapping[str, Any]:
    raw, meta = _safe_regular(path, mode=0o600, code="DB_SOURCE_CUSTODY")
    return MappingProxyType({"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                             "st_dev": meta.st_dev, "st_ino": meta.st_ino,
                             "st_mtime_ns": meta.st_mtime_ns})

def snapshot_bridge(database: Path, expectation: Mapping[str, Any],
                    quiescence: Mapping[str, Any]) -> Mapping[str, Any]:
    require(dict(quiescence) == {"engine_closed": True, "active_service": False,
                                 "sidecars_absent": True}, "DB_QUIESCENCE_REQUIRED")
    database = Path(database)
    for suffix in ("-wal", "-shm", "-journal"):
        require(not Path(str(database) + suffix).exists(), "DB_NOT_QUIESCENT")
    raw, meta = _safe_regular(database, mode=0o600, code="DB_SOURCE_CUSTODY")
    observed = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw),
                "st_dev": meta.st_dev, "st_ino": meta.st_ino,
                "st_mtime_ns": meta.st_mtime_ns}
    require(observed == dict(expectation), "DB_SOURCE_DESCRIPTOR_MISMATCH")
    snapshot = database.with_name(f".{database.name}.semantic-v2-snapshot")
    require(not snapshot.exists(), "DB_SNAPSHOT_EXISTS")
    fd = -1
    try:
        fd = os.open(snapshot, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600)
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            require(count > 0, "DB_SNAPSHOT_WRITE")
            view = view[count:]
        os.fsync(fd)
        os.close(fd); fd = -1
        snap_raw, _ = _safe_regular(snapshot, mode=0o600, code="DB_SNAPSHOT_CUSTODY")
        require(snap_raw == raw, "DB_SNAPSHOT_DIGEST")
        connection = sqlite3.connect(f"file:{snapshot}?mode=ro&immutable=1", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN")
            connection.execute("PRAGMA query_only=ON")
            schema = verify_schema9(connection)
            joined = [dict(row) for row in connection.execute(
                """SELECT p.attempt_id,p.slot_id,p.canonical_json,p.canonical_sha256,
                p.provider,p.operation_id,p.phase,p.submission,p.terminal_proof,p.status,
                p.failure_kind,p.recorded_at,p.prompt_binding_sha256,s.job_id,s.artifact_ref,
                s.sha256,s.length,s.version,s.source_identity_sha256,s.generation,s.proof_origin
                FROM provider_results p JOIN attempts a ON a.attempt_id=p.attempt_id
                JOIN slots s ON s.slot_id=p.slot_id AND s.slot_id=a.slot_id
                WHERE s.job_id IN (?,?) ORDER BY s.job_id""", JOB_IDS)]
            connection.commit()
        finally:
            connection.close()
        require(schema == SCHEMA9_FINGERPRINT and len(joined) == 2, "DB_ENGINE_ROWS")
        rows, expected = [], []
        for index, item in enumerate(joined):
            descriptor = {key: item[key] for key in ("artifact_ref", "sha256", "length", "version",
                                                       "source_identity_sha256", "generation", "proof_origin")}
            require(item["job_id"] == JOB_IDS[index] and descriptor == {
                "artifact_ref": f"pa1:sha256:{PROMPT_SHA256}:{PROMPT_BYTES}",
                "sha256": PROMPT_SHA256, "length": PROMPT_BYTES, "version": 1,
                "source_identity_sha256": SOURCE_SHA256, "generation": GENERATION,
                "proof_origin": "native_v1"}, "DB_DESCRIPTOR_PROVENANCE")
            binding = prompt_binding_sha256(JOB_IDS[index], item["slot_id"], descriptor)
            require(item["prompt_binding_sha256"] == binding and
                    item["operation_id"] == f"attempt/{item['attempt_id']}/prompt/{binding}",
                    "DB_NATIVE_OPERATION")
            rows.append({key: item[key] for key in (
                "attempt_id", "slot_id", "canonical_json", "canonical_sha256", "provider",
                "operation_id", "phase", "submission", "terminal_proof", "status",
                "failure_kind", "recorded_at", "prompt_binding_sha256")})
            expected.append({"cell_id": CELL_ORDER[index], "job_id": JOB_IDS[index],
                             "attempt_id": item["attempt_id"], "slot_id": item["slot_id"],
                             "prompt_binding_sha256": binding, **descriptor})
        return MappingProxyType({"rows": tuple(MappingProxyType(row) for row in rows),
                                 "expected": tuple(MappingProxyType(item) for item in expected),
                                 "receipt": MappingProxyType({
                                     "status": "PASS_CLOSED_QUIESCENT_DESCRIPTOR_SNAPSHOT",
                                     "schema_fingerprint": schema, "source_sha256": observed["sha256"],
                                     "snapshot_sha256": hashlib.sha256(snap_raw).hexdigest(),
                                     "source_descriptor": observed, "row_count": 2})})
    except (sqlite3.Error, OSError) as exc:
        raise VerticalError("DB_SNAPSHOT_BRIDGE_FAILED") from None
    finally:
        if fd >= 0:
            os.close(fd)
        if snapshot.exists():
            snapshot.unlink()

def _decode_row(row: Mapping[str, Any], expected: Mapping[str, Any], index: int) -> Mapping[str, Any]:
    row = dict(row); expected = dict(expected)
    require(set(row) == {"attempt_id", "slot_id", "canonical_json", "canonical_sha256", "provider",
                         "operation_id", "phase", "submission", "terminal_proof", "status",
                         "failure_kind", "recorded_at", "prompt_binding_sha256"}, "ENGINE_ROW_SHAPE")
    require(type(row["recorded_at"]) in (int, float) and type(row["recorded_at"]) is not bool
            and (type(row["recorded_at"]) is int or math.isfinite(row["recorded_at"])), "ENGINE_ROW_TIME")
    require(expected["cell_id"] == CELL_ORDER[index] and expected["job_id"] == JOB_IDS[index],
            "ADAPTER_EXPECTED_ORDER")
    descriptor = {key: expected[key] for key in ("artifact_ref", "sha256", "length", "version",
                                                   "source_identity_sha256", "generation", "proof_origin")}
    require(descriptor == {"artifact_ref": f"pa1:sha256:{PROMPT_SHA256}:{PROMPT_BYTES}",
                            "sha256": PROMPT_SHA256, "length": PROMPT_BYTES, "version": 1,
                            "source_identity_sha256": SOURCE_SHA256, "generation": GENERATION,
                            "proof_origin": "native_v1"}, "ADAPTER_DESCRIPTOR_PROVENANCE")
    binding = prompt_binding_sha256(JOB_IDS[index], expected["slot_id"], descriptor)
    operation = f"attempt/{expected['attempt_id']}/prompt/{binding}"
    require(expected["prompt_binding_sha256"] == binding and row["prompt_binding_sha256"] == binding
            and row["attempt_id"] == expected["attempt_id"] and row["slot_id"] == expected["slot_id"]
            and row["provider"] == PROVIDER and row["operation_id"] == operation,
            "ADAPTER_ROW_PROVENANCE")
    encoded = row["canonical_json"].encode("utf-8")
    require(hashlib.sha256(encoded).hexdigest() == row["canonical_sha256"], "ENGINE_ROW_DIGEST")
    try:
        result = ProviderResultV1(**json.loads(row["canonical_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        raise VerticalError("ENGINE_TYPED_PROVIDER_RESULT") from None
    require(result.canonical_sha256 == row["canonical_sha256"], "ENGINE_RESULT_DIGEST")
    require((result.provider.value, result.operation_id, result.phase.value, result.submission.value,
             result.terminal_proof.value, result.status.value, result.failure_kind.value) ==
            (row["provider"], row["operation_id"], row["phase"], row["submission"],
             row["terminal_proof"], row["status"], row["failure_kind"]), "ENGINE_RESULT_ROW_BINDING")
    receipt = plain(result.receipt)
    require(type(receipt) is dict and set(receipt) == {
        "version", "cell_id", "configured_model", "provider_reported_model", "artifact_sha256",
        "artifact_utf8_bytes", "source_sha256", "terminal_state", "terminal_ascii", "dq_checks"},
        "ADAPTER_RECEIPT_SHAPE")
    require(receipt["version"] == 2 and receipt["cell_id"] == CELL_ORDER[index]
            and receipt["configured_model"] == MODEL and receipt["provider_reported_model"] == MODEL
            and receipt["artifact_sha256"] == PROMPT_SHA256
            and receipt["artifact_utf8_bytes"] == PROMPT_BYTES
            and receipt["source_sha256"] == SOURCE_SHA256, "ADAPTER_RECEIPT_PROVENANCE")
    terminal = receipt["terminal_state"]
    require(terminal in TERMINALS and result.status == STATUS_BINDING[terminal], "ADAPTER_TERMINAL_BINDING")
    try:
        raw = receipt["terminal_ascii"].encode("ascii")
    except (AttributeError, UnicodeError):
        raise VerticalError("ADAPTER_RAW_ASCII") from None
    require(len(raw) <= 1048576, "ADAPTER_RAW_SIZE")
    return MappingProxyType({"cell_id": CELL_ORDER[index], "attempt_id": row["attempt_id"],
                             "terminal": terminal, "raw": raw, "dq_checks": receipt["dq_checks"]})

def adapt_provider_rows(rows: Sequence[Mapping[str, Any]], expected: Sequence[Mapping[str, Any]],
                        bundle_root: Path, *, fault: str | None = None) -> Mapping[str, Any]:
    require(type(rows) in (tuple, list) and len(rows) == 2 and type(expected) in (tuple, list)
            and len(expected) == 2, "ADAPTER_ROW_COUNT")
    decoded = [_decode_row(rows[index], expected[index], index) for index in range(2)]
    require(len({item["attempt_id"] for item in decoded}) == 2, "ADAPTER_DUPLICATE_ATTEMPT")
    root = Path(bundle_root)
    require(root.is_absolute() and not root.exists(), "OUTPUT_FRESH_ROOT_REQUIRED")
    parent = root.parent
    require(parent.is_dir() and not parent.is_symlink() and parent.stat().st_uid == os.getuid()
            and stat.S_IMODE(parent.stat().st_mode) == 0o700, "OUTPUT_PARENT_CUSTODY")
    by_cell = {item["cell_id"]: item for item in decoded}
    def outcome(plan: Mapping[str, Any]) -> Mapping[str, Any]:
        item = by_cell[plan["cell_id"]]
        return {"plan_echo": dict(plan), "attempt_id": item["attempt_id"],
                "terminal_state": item["terminal"],
                "attempt_count": 0 if item["terminal"] == "STOP" else 1,
                "raw": item["raw"], "dq_checks": item["dq_checks"]}
    try:
        result = run_pair(outcome, root, fault_cell=CELL_ORDER[1] if fault == "after_raw" else "")
        validate_result(result)
        before = {path.relative_to(root).as_posix(): path.read_bytes()
                  for path in root.rglob("*") if path.is_file()}
        if fault == "output_tamper":
            target = root / CELL_ORDER[0] / f"{CELL_ORDER[0]}.bundle.json"
            target.write_bytes(target.read_bytes() + b" ")
        restarted = run_pair(outcome, root)
        after = {path.relative_to(root).as_posix(): path.read_bytes()
                 for path in root.rglob("*") if path.is_file()}
        require(before == after and result == restarted, "OUTPUT_RESTART_DRIFT")
        descriptors = []
        for cell in CELL_ORDER:
            raw_path = root / cell / f"{cell}.raw"
            bundle_path = root / cell / f"{cell}.bundle.json"
            raw, _ = _safe_regular(raw_path, mode=0o600, code="OUTPUT_RAW_CUSTODY")
            bundle, _ = _safe_regular(bundle_path, mode=0o600, code="OUTPUT_BUNDLE_CUSTODY")
            read_bundle(bundle_path, hashlib.sha256(bundle).hexdigest())
            descriptors.append({"cell_id": cell, "raw_sha256": hashlib.sha256(raw).hexdigest(),
                                "raw_bytes": len(raw), "bundle_file_sha256": hashlib.sha256(bundle).hexdigest(),
                                "bundle_bytes": len(bundle)})
        return MappingProxyType({"result": result, "descriptors": tuple(descriptors),
                                 "restart_verified": True, "legacy_ab_prompt_sha256": FROZEN_INPUTS["prompt_sha256"],
                                 "runtime_prompt_sha256": PROMPT_SHA256})
    except BundleError as exc:
        raise VerticalError("OUTPUT_CUSTODY_OR_RESTART") from None

def _synthetic_rows(descriptor: PromptArtifactDescriptorV1, terminal: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, expected = [], []
    for index in range(2):
        slot = f"slot-semantic-{terminal.lower()}-{index}"
        attempt = f"attempt-semantic-{terminal.lower()}-{index}"
        values = {"artifact_ref": descriptor.ref, "sha256": descriptor.sha256,
                  "length": descriptor.length, "version": descriptor.version,
                  "source_identity_sha256": descriptor.source_identity_sha256,
                  "generation": descriptor.generation, "proof_origin": descriptor.provenance}
        binding = prompt_binding_sha256(JOB_IDS[index], slot, values)
        context = {"operation_id": f"attempt/{attempt}/prompt/{binding}"}
        result = _provider_result(index, context, terminal)
        encoded = json.dumps(plain(result.to_mapping()), sort_keys=True, separators=(",", ":"))
        rows.append({"attempt_id": attempt, "slot_id": slot, "canonical_json": encoded,
                     "canonical_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
                     "provider": result.provider.value, "operation_id": result.operation_id,
                     "phase": result.phase.value, "submission": result.submission.value,
                     "terminal_proof": result.terminal_proof.value, "status": result.status.value,
                     "failure_kind": result.failure_kind.value, "recorded_at": 1.0,
                     "prompt_binding_sha256": binding})
        expected.append({"cell_id": CELL_ORDER[index], "job_id": JOB_IDS[index],
                         "slot_id": slot, "attempt_id": attempt, "prompt_binding_sha256": binding,
                         **values})
    return rows, expected

def exercise_disposition(source_path: Path, bundle_root: Path, terminal: str) -> Mapping[str, Any]:
    descriptor, _, _ = capture_prompt(source_path)
    rows, expected = _synthetic_rows(descriptor, terminal)
    return adapt_provider_rows(rows, expected, bundle_root)

def _load_manifest_lineage(repo_root: Path) -> tuple[Mapping[str, Any], ...]:
    records = []
    parent = "ROOT_ACTUAL_PROMPT_LINEAGE"
    for name, expected_sha in MANIFESTS:
        path = repo_root / "shared/job_runtime/tests/fixtures" / name / "manifest-v2.json"
        raw = path.read_bytes()
        observed = hashlib.sha256(raw).hexdigest()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise VerticalError("MANIFEST_JSON") from None
        require(digest(value) == expected_sha and value["stage"] == name
                and value["parent_sha256"] == parent, "MANIFEST_CANONICAL_LINEAGE")
        require(value["prompt"]["sha256"] == PROMPT_SHA256 and value["prompt"]["bytes"] == PROMPT_BYTES,
                "MANIFEST_PROMPT_BINDING")
        records.append(MappingProxyType({"stage": name, "canonical_output_sha256": expected_sha,
                                         "file_sha256": observed}))
        parent = expected_sha
    return tuple(records)

def _semantic_lineage(manifests: Sequence[Mapping[str, Any]], outputs: Sequence[Any],
                      prompt_root_sha256: str) -> tuple[Mapping[str, Any], ...]:
    require(len(manifests) == len(outputs) == len(MANIFESTS), "LINEAGE_COUNT")
    records = []
    parent = prompt_root_sha256
    for manifest, output in zip(manifests, outputs):
        output_sha = digest(output)
        receipt = {"stage": manifest["stage"], "parent_semantic_output_sha256": parent,
                   "consumed_canonical_output_sha256": manifest["canonical_output_sha256"],
                   "actual_output_sha256": output_sha}
        receipt["semantic_receipt_sha256"] = digest(receipt)
        records.append(MappingProxyType(receipt))
        parent = output_sha
    return tuple(records)

def render_data(when: datetime, not_before: datetime, scheduled: datetime, deadline: datetime,
                custody: Mapping[str, Any], integration: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    evaluation = utc_second(when, "TIME_EVALUATION")
    lower = utc_second(not_before, "TIME_NOT_BEFORE")
    at = utc_second(scheduled, "TIME_SCHEDULED")
    upper = utc_second(deadline, "TIME_DEADLINE")
    require(evaluation <= lower <= at <= upper and evaluation < at, "TIME_ORDER")
    window = int((upper - lower).total_seconds())
    grace = int((upper - at).total_seconds())
    require(0 < window <= 300 and 0 < grace <= 300, "TIME_WINDOW")
    schedule = {"kind": "once", "at": iso(at), "grace_seconds": grace}
    design = {"kind": "R6_FABLE_SEMANTIC_VERTICAL_V2_DESIGN_DATA", "activation": False,
              "countable": False, "model": MODEL, "provider": PROVIDER,
              "prompt": dict(custody), "integration_sha256": digest(integration),
              "cells": list(CELL_ORDER), "jobs": list(JOB_IDS), "effects": dict(EFFECTS)}
    materialized = {"kind": "R6_FABLE_SEMANTIC_VERTICAL_V2_MATERIALIZATION_DATA",
                    "activation": False, "countable": False, "design_sha256": digest(design),
                    "evaluation_time": iso(evaluation), "not_before": iso(lower),
                    "scheduled_at": iso(at), "deadline": iso(upper), "window_seconds": window,
                    "schedule": schedule, "installed_jobs": [], "installed_schedules": [],
                    "effects": dict(EFFECTS)}
    proposal = {"schema": "r6-data-quality-fable-semantic-v2-proposal-data",
                "classification": "DATA_ONLY_NOT_CONFIG_V2_NOT_ENGINE_INSTALLABLE",
                "activation": False, "apply": False, "countable": False,
                "materialized_sha256": digest(materialized), "prompt": dict(custody),
                "jobs": [{"id": JOB_IDS[index], "cell_id": CELL_ORDER[index], "enabled": False,
                           "schedule": dict(schedule), "model": MODEL, "provider": PROVIDER}
                          for index in range(2)],
                "installed_jobs": [], "installed_schedules": [], "effects": dict(EFFECTS)}
    retry = {"version": 2, "max_attempts": 1, "base_delay_seconds": 1,
             "max_delay_seconds": 1, "deadline_seconds": grace}
    config = {"schema_version": 2, "tick_seconds": 5, "heartbeat_seconds": 10,
              "stale_seconds": 60, "max_workers": 1, "retry": retry,
              "model_profiles": {PROFILE: {"provider": PROVIDER, "model": MODEL, "effort": "low",
                                              "timeout_seconds": 300, "auth_home": AUTH_HOME,
                                              "max_budget_usd": 0.02}},
              "allocation_files": [ALLOCATION_FILE], "source_paths": []}
    allocation = {"schema_version": 2, "jobs": [
        {"id": JOB_IDS[index], "enabled": False, "schedule": dict(schedule),
         "model_profile": PROFILE, "prompt_file": PROMPT_FILE,
         "replay_contract": {"version": 1, "effect": "none",
                             "automatic_phases": ["not_started"],
                             "slot_operation_scope": f"fable/v2/{index}",
                             "reconciliation_adapter": None}}
        for index in range(2)]}
    translation = {"config": config, "allocation": allocation,
                   "proposal_sha256": digest(proposal),
                   "budget": {"currency": "USD", "per_arm_max_budget_usd": 0.02,
                              "aggregate_ceiling_usd": 0.04, "user_approved": True,
                              "billed_authority": False, "prompt_utf8_bytes": PROMPT_BYTES,
                              "token_evidence": "UNMEASURED_PROVIDER_FREE"}}
    return design, materialized, proposal, config, allocation, translation

def execute(*, repo_root: Path, source_path: Path, workspace_root: Path, output_root: Path,
            evaluation: datetime, not_before: datetime, scheduled: datetime, deadline: datetime,
            fault: str | None = None) -> Mapping[str, Any]:
    repo_root = Path(repo_root).resolve()
    descriptor, prompt, custody = capture_prompt(source_path)
    if fault == "prompt":
        raise VerticalError("INJECTED_PROMPT_BOUNDARY")
    manifests = _load_manifest_lineage(repo_root)
    grace = int((utc_second(deadline, "TIME_DEADLINE") - utc_second(scheduled, "TIME_SCHEDULED")).total_seconds())
    jobs = build_jobs(descriptor, utc_second(scheduled, "TIME_SCHEDULED"), grace, enabled=True)
    state = Path(workspace_root) / ".job-runtime" / "semantic-v2-engine"
    database, summary = run_engine(state, jobs, utc_second(scheduled, "TIME_SCHEDULED"))
    expectation = source_expectation(database)
    bridge = snapshot_bridge(database, expectation,
                             {"engine_closed": True, "active_service": False, "sidecars_absent": True})
    if fault == "db_snapshot":
        bad = dict(expectation); bad["sha256"] = "0" * 64
        snapshot_bridge(database, bad,
                        {"engine_closed": True, "active_service": False, "sidecars_absent": True})
    rows = [dict(item) for item in bridge["rows"]]
    expected = [dict(item) for item in bridge["expected"]]
    if fault == "engine_row":
        rows[0]["canonical_sha256"] = "0" * 64
    if fault == "adapter":
        expected[0]["sha256"] = "0" * 64
    integration = adapt_provider_rows(rows, expected, Path(output_root),
                                      fault="output_tamper" if fault == "output_custody" else None)
    if fault == "integration":
        raise VerticalError("INJECTED_INTEGRATION_BOUNDARY")
    rendered = render_data(evaluation, not_before, scheduled, deadline, custody, integration)
    design, materialized, proposal, config, allocation, translation = rendered
    if fault == "schedule":
        render_data(evaluation, not_before, scheduled.replace(microsecond=1), deadline, custody, integration)
    if fault == "config":
        bad = dict(config); bad["schema_version"] = 1
        require(bad["schema_version"] == 2, "INJECTED_CONFIG_BOUNDARY")
    prompt_root = digest({"prompt": dict(custody), "prompt_raw_sha256": hashlib.sha256(prompt).hexdigest()})
    outputs = (integration["result"], {"engine_summary": summary, "adapter": integration},
               bridge, integration, design, materialized, proposal, translation)
    lineage = _semantic_lineage(manifests, outputs, prompt_root)
    return MappingProxyType({
        "version": 2, "activation": False, "countable": False, "effects": MappingProxyType(dict(EFFECTS)),
        "prompt": custody, "prompt_bytes": prompt, "engine_summary": summary,
        "database_descriptor": expectation, "bridge": bridge, "integration": integration,
        "design": design, "materialized": materialized, "proposal": proposal,
        "config": config, "allocation": allocation, "translation": translation,
        "budget": translation["budget"], "manifest_lineage": manifests,
        "semantic_lineage": lineage, "final_sha256": lineage[-1]["semantic_receipt_sha256"],
    })
