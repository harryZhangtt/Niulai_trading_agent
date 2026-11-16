"""Canonical-Engine-owned provider-free R6 O1 one-off vertical runner."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from shared.job_runtime.engine import Engine
from shared.job_runtime.prompt_custody import PromptArtifactDescriptorV1
from shared.job_runtime.provider_contract import (
    FailureKind, Phase, Provider, ProviderResultV1, ReplayContractV1, ReplayEffect,
    ResultStatus, Submission, TerminalProof,
)
from shared.job_runtime.retry_policy import RetryPolicyV2

from .contracts import (
    ContractError, canonical_bytes, no_effects, request_fingerprint, require,
    sha256_bytes, sha256_json, validate_binding, validate_evidence, validate_grant,
)
from .custody import (
    AdmissionLedger, CustodyError, CustodySession, atomic_private_write,
)
from .publication import publish_evidence

UTC = timezone.utc
_STATIC_ROLE_NAMES = {
    "binary": "held-binary.bin", "argv": "argv.json", "config": "config.json",
    "parser": "parser.json", "prompt": "prompt.txt",
}
_OUTPUT_ROLE_NAMES = {
    "raw": "raw.bin", "terminal": "terminal.json", "cleanup": "cleanup.json",
}
_SOURCE_FILES = (
    "__init__.py", "contracts.py", "custody.py", "runner.py", "publication.py",
    "one-off-grant-v1.schema.json", "engine-execution-binding-v1.schema.json",
    "r6-evidence-v1.schema.json", "publication-receipt-v1.schema.json",
)


class RunnerError(ContractError):
    """Fixed, provider-free runner failure."""


def _runner_require(condition: bool, code: str) -> None:
    if not condition:
        raise RunnerError(code)


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RunnerError("RUNNER_TIME_INVALID") from None
    _runner_require(parsed.tzinfo is not None and parsed.utcoffset() is not None,
                    "RUNNER_TIME_INVALID")
    return parsed.astimezone(UTC)


def _mkdir_private(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def _write_seed(path: Path, value: bytes) -> None:
    _runner_require(type(value) is bytes and value, "SEED_VALUE_INVALID")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                 0o600)
    try:
        offset = 0
        while offset < len(value):
            written = os.write(fd, value[offset:])
            _runner_require(written > 0, "SEED_WRITE_FAILED")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)


def source_generation_sha256() -> str:
    root = Path(__file__).resolve().parent
    members = []
    for name in _SOURCE_FILES:
        path = root / name
        raw = path.read_bytes()
        members.append({"name": name, "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()})
    return sha256_json({"version": 1, "members": members})


@dataclass
class Counters:
    dispatch: int = 0
    admission: int = 0
    admission_stop: int = 0
    upstream: int = 0
    retry: int = 0
    replay: int = 0
    status_query: int = 0
    reconstruction_dispatch: int = 0

    def public(self) -> Dict[str, int]:
        return {
            "dispatch": self.dispatch, "admission": self.admission,
            "admission_stop": self.admission_stop, "upstream": self.upstream,
            "retry": self.retry, "replay": self.replay,
            "status_query": self.status_query,
            "reconstruction_dispatch": self.reconstruction_dispatch,
        }


@dataclass
class PreparedCase:
    workspace: Path
    private_root: Path
    custody_root: Path
    output_root: Path
    admission_root: Path
    binding_root: Path
    public_root: Path
    engine_state: Path
    grant: Dict[str, Any]
    custody: CustodySession

    def inject_drift(self, role: str) -> None:
        descriptor = self.custody.descriptor(role)
        path = self.custody_root / descriptor.name
        with path.open("r+b", buffering=0) as stream:
            stream.seek(0)
            original = stream.read(1)
            stream.seek(0)
            stream.write(b"X" if original != b"X" else b"Y")
            stream.flush()
            os.fsync(stream.fileno())

    def close(self) -> None:
        self.custody.close()


@dataclass(frozen=True)
class Execution:
    grant: Dict[str, Any]
    evidence: Dict[str, Any]
    binding: Optional[Dict[str, Any]]
    publication: Dict[str, Any]


Transport = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def _fresh_identity(prefix: str, blocked: Sequence[str], bytes_count: int) -> str:
    blocked_set = set(blocked)
    for _ in range(8):
        value = prefix + secrets.token_hex(bytes_count)
        if value not in blocked_set:
            return value
    raise RunnerError("FRESH_IDENTITY_UNAVAILABLE")


def materialize_provider_free_case(
        workspace: Path, scenario: str, historical_job_ids: Sequence[str] = (),
        historical_nonces: Sequence[str] = (),
        created_at: Optional[datetime] = None) -> PreparedCase:
    """Create one fresh disposable synthetic grant; never creates live authority."""
    workspace = Path(workspace)
    _runner_require(not workspace.exists(), "WORKSPACE_MUST_BE_FRESH")
    workspace.mkdir(mode=0o700, parents=True)
    workspace.chmod(0o700)
    private_root = workspace / ".job-runtime" / "r6-one-off-evidence-v1"
    custody_root = private_root / "custody"
    output_root = private_root / "raw"
    admission_root = private_root / "admission"
    binding_root = private_root / "binding"
    public_root = private_root / "public"
    engine_state = private_root / "engine"
    for path in (workspace / ".job-runtime", private_root, custody_root,
                 output_root, admission_root, binding_root, public_root):
        _mkdir_private(path)
    logical_job_id = _fresh_identity("r6o1-", historical_job_ids, 16)
    preflight_nonce = _fresh_identity("", historical_nonces, 32)
    created = (created_at or datetime.now(UTC)).astimezone(UTC)
    slot = created + timedelta(minutes=5)
    deadline = slot + timedelta(minutes=1)
    config = canonical_bytes({
        "version": 1, "mode": "provider_free", "scenario": scenario,
        "workers": 1, "attempts": 1, "retries": 0,
    })
    allocation = canonical_bytes({
        "version": 1, "kind": "future_once", "slot_at": slot.isoformat(),
        "deadline_at": deadline.isoformat(), "provider_authorized": False,
    })
    parser = canonical_bytes({
        "version": 1, "terminal": "synthetic_exact_v1",
        "partial_is_success": False,
    })
    argv = canonical_bytes({
        "version": 1, "argv": ["injected-provider-free-transport"],
        "subprocess": False,
    })
    prompt = ("Return the exact synthetic terminal for scenario " + scenario + "\n").encode("utf-8")
    binary = b"provider-free descriptor only; never executable\n"
    payloads = {
        "binary": binary, "argv": argv, "config": config,
        "parser": parser, "prompt": prompt,
    }
    for role, name in _STATIC_ROLE_NAMES.items():
        _write_seed(custody_root / name, payloads[role])
    custody = CustodySession.seal(custody_root, dict(_STATIC_ROLE_NAMES))
    descriptors = [item.public() for item in custody.descriptors]
    grant = {
        "version": 1, "kind": "PROVIDER_FREE_PERMANENTLY_NONAUTHORIZING",
        "logical_job_id": logical_job_id, "preflight_nonce": preflight_nonce,
        "created_at": created.isoformat(), "slot_at": slot.isoformat(),
        "deadline_at": deadline.isoformat(), "scenario": scenario,
        "config_sha256": sha256_bytes(config),
        "allocation_sha256": sha256_bytes(allocation),
        "prompt_sha256": sha256_bytes(prompt),
        "treatment_fingerprint": sha256_json({
            "version": 1, "scenario": scenario, "transport": "injected",
            "countable": False,
        }),
        "source_generation_sha256": source_generation_sha256(),
        "custody": descriptors, "max_workers": 1, "max_attempts": 1,
        "request_retries": 0, "stream_retries": 0, "replay_safe": False,
        "enabled": False, "capability_open": False,
        "provider_authorized": False, "countable": False,
        "effects": no_effects(),
    }
    validate_grant(grant, historical_job_ids, historical_nonces)
    atomic_private_write(private_root, "grant.json", canonical_bytes(grant))
    return PreparedCase(
        workspace, private_root, custody_root, output_root, admission_root,
        binding_root, public_root, engine_state, grant, custody,
    )


def _prompt_descriptor(grant: Mapping[str, Any]) -> PromptArtifactDescriptorV1:
    prompt = next(item for item in grant["custody"] if item["role"] == "prompt")
    identity = sha256_json({
        "kind": "provider_free_custody", "name": prompt["name"],
        "logical_job_id": grant["logical_job_id"],
    })
    return PromptArtifactDescriptorV1(
        1, "pa1:sha256:%s:%d" % (prompt["sha256"], prompt["bytes"]),
        prompt["sha256"], prompt["bytes"], identity,
        grant["source_generation_sha256"], "native_v1",
    )


def _job(grant: Mapping[str, Any], provider: Provider) -> Tuple[Dict[str, Any], RetryPolicyV2]:
    policy = RetryPolicyV2(1, 1, 1, deadline_seconds=60)
    contract = ReplayContractV1(
        ReplayEffect.NONE, (Phase.NOT_STARTED,), "r6-o1/provider-free",
    )
    return ({
        "id": grant["logical_job_id"], "enabled": True, "replay_safe": False,
        "schedule": {"kind": "once", "at": grant["slot_at"], "grace_seconds": 60},
        "_provider": provider.value, "_replay_contract": contract,
        "_retry_policy": policy, "_prompt_artifact": _prompt_descriptor(grant),
    }, policy)


def _transport_result(value: Any, scenario: str) -> Mapping[str, Any]:
    _runner_require(type(value) is dict and set(value) ==
                    {"terminal", "cleanup", "raw"},
                    "INJECTED_TRANSPORT_RESULT_INVALID")
    expected = {
        "nominal": ("exact", "complete"),
        "post_admission_unknown": ("truncated", "fault"),
    }[scenario]
    _runner_require((value["terminal"], value["cleanup"]) == expected and
                    type(value["raw"]) is bytes and value["raw"],
                    "INJECTED_TRANSPORT_RESULT_INVALID")
    return value


def _write_output_custody(prepared: PreparedCase, observed: Mapping[str, Any]) -> CustodySession:
    terminal = canonical_bytes({"version": 1, "state": observed["terminal"]})
    cleanup = canonical_bytes({"version": 1, "state": observed["cleanup"]})
    atomic_private_write(prepared.output_root, _OUTPUT_ROLE_NAMES["raw"], observed["raw"])
    atomic_private_write(prepared.output_root, _OUTPUT_ROLE_NAMES["terminal"], terminal)
    atomic_private_write(prepared.output_root, _OUTPUT_ROLE_NAMES["cleanup"], cleanup)
    session = CustodySession.seal(prepared.output_root, dict(_OUTPUT_ROLE_NAMES))
    session.verify()
    return session


def _atomic_engine_binding(engine: Engine, grant: Mapping[str, Any],
                           binding_root: Path, provider: Provider) -> Dict[str, Any]:
    db = sqlite3.connect(engine.path, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("BEGIN IMMEDIATE")
        job_id = grant["logical_job_id"]
        counts = {
            "job": db.execute("SELECT COUNT(*) FROM jobs WHERE job_id=?", (job_id,)).fetchone()[0],
            "slot": db.execute("SELECT COUNT(*) FROM slots WHERE job_id=?", (job_id,)).fetchone()[0],
            "attempt": db.execute("SELECT COUNT(*) FROM attempts a JOIN slots s ON s.slot_id=a.slot_id WHERE s.job_id=?", (job_id,)).fetchone()[0],
            "provider_result": db.execute("SELECT COUNT(*) FROM provider_results p JOIN attempts a ON a.attempt_id=p.attempt_id JOIN slots s ON s.slot_id=a.slot_id WHERE s.job_id=?", (job_id,)).fetchone()[0],
        }
        _runner_require(all(value == 1 for value in counts.values()),
                        "ENGINE_BINDING_MULTIPLICITY")
        row = db.execute("""SELECT s.slot_id,s.operation_id,s.status AS slot_status,
            s.binding_sha256 AS slot_binding,a.attempt_id,a.status AS attempt_status,
            a.binding_sha256 AS attempt_binding,p.operation_id AS result_operation,
            p.status AS result_status,p.prompt_binding_sha256 AS result_binding,
            p.canonical_sha256 AS result_sha256,p.provider AS result_provider,
            s.provider AS slot_provider
            FROM slots s JOIN attempts a ON a.slot_id=s.slot_id
            JOIN provider_results p ON p.attempt_id=a.attempt_id
            WHERE s.job_id=?""", (job_id,)).fetchone()
        _runner_require(row is not None, "ENGINE_BINDING_MISSING")
        operation_equal = row["operation_id"] == row["result_operation"]
        prompt_equal = (row["slot_binding"] == row["attempt_binding"] ==
                        row["result_binding"])
        _runner_require(operation_equal and prompt_equal,
                        "ENGINE_BINDING_EQUALITY_FAILED")
        _runner_require(row["slot_provider"] == row["result_provider"] == provider.value,
                        "ENGINE_PROVIDER_BINDING_FAILED")
        _runner_require(row["slot_status"] == row["attempt_status"] ==
                        row["result_status"] and row["slot_status"] in
                        ("succeeded", "unknown"), "ENGINE_STATUS_CONFLICT")
        binding = {
            "version": 1, "logical_job_id": job_id, "provider": provider.value,
            "preflight_nonce": grant["preflight_nonce"],
            "scenario": grant["scenario"], "slot_id": row["slot_id"],
            "attempt_id": row["attempt_id"], "operation_id": row["operation_id"],
            "prompt_sha256": grant["prompt_sha256"],
            "prompt_binding_sha256": row["slot_binding"],
            "config_sha256": grant["config_sha256"],
            "allocation_sha256": grant["allocation_sha256"],
            "treatment_fingerprint": grant["treatment_fingerprint"],
            "source_generation_sha256": grant["source_generation_sha256"],
            "result_sha256": row["result_sha256"],
            "engine_status": row["slot_status"], "counts": counts,
            "operation_equal": True, "prompt_binding_equal": True,
            "transaction": "BEGIN_IMMEDIATE_SINGLE_READBACK",
            "receipt_durable": True,
        }
        validate_binding(binding)
        atomic_private_write(binding_root, "engine-execution-binding.json",
                             canonical_bytes(binding))
        db.commit()
        return binding
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def _evidence(grant: Mapping[str, Any], decision: str, code: str,
              counters: Counters, binding: Optional[Mapping[str, Any]],
              terminal: str, cleanup: str, second_admission: str) -> Dict[str, Any]:
    engine = {"slot_id": None, "attempt_id": None,
              "operation_id": None, "status": None}
    if binding is not None:
        engine = {
            "slot_id": binding["slot_id"], "attempt_id": binding["attempt_id"],
            "operation_id": binding["operation_id"],
            "status": binding["engine_status"],
        }
    evidence = {
        "version": 1, "scenario": grant["scenario"], "decision": decision,
        "code": code, "countable": False,
        "logical_job_id": grant["logical_job_id"],
        "preflight_nonce_sha256": sha256_bytes(grant["preflight_nonce"].encode("ascii")),
        "engine": engine, "counters": counters.public(), "terminal": terminal,
        "cleanup": cleanup, "second_admission": second_admission,
        "external_effects": no_effects(), "raw_private": True,
        "public_allowlist_only": True,
    }
    validate_evidence(evidence)
    return evidence


def execute_provider_free(prepared: PreparedCase, transport: Transport,
                          historical_job_ids: Sequence[str] = (),
                          historical_nonces: Sequence[str] = (), *,
                          provider: Provider | str = Provider.CODEX_CLI) -> Execution:
    """Execute exactly one injected provider-free case; this cannot authorize live use."""
    counters = Counters()
    try:
        provider = Provider(provider)
    except (TypeError, ValueError):
        raise RunnerError("PROVIDER_IDENTITY_INVALID") from None
    grant = prepared.grant
    validate_grant(grant, historical_job_ids, historical_nonces)
    try:
        prepared.custody.verify()
    except CustodyError:
        evidence = _evidence(
            grant, "STOP", "SEALED_DIGEST_DRIFT", counters, None,
            "absent", "not_started", "NOT_APPLICABLE")
        _, publication = publish_evidence(evidence, prepared.public_root)
        return Execution(dict(grant), evidence, None, publication)

    _runner_require(grant["scenario"] in ("nominal", "post_admission_unknown"),
                    "EXECUTABLE_SCENARIO_INVALID")
    job, policy = _job(grant, provider)
    ledger = AdmissionLedger(prepared.admission_root)
    output_session = None
    captured = {}

    def dispatch(_configured: Mapping[str, Any], context: Mapping[str, Any]) -> ProviderResultV1:
        nonlocal output_session
        counters.dispatch += 1
        _runner_require(counters.dispatch == 1 and
                        context["prompt_artifact"].sha256 == grant["prompt_sha256"],
                        "DISPATCH_MULTIPLICITY_INVALID")
        request = {
            "version": 1, "logical_job_id": grant["logical_job_id"],
            "preflight_nonce": grant["preflight_nonce"],
            "attempt_id": context["attempt_id"],
            "operation_id": context["operation_id"],
            "prompt_binding_sha256": context["prompt_binding_sha256"],
            "prompt_sha256": grant["prompt_sha256"], "scenario": grant["scenario"],
        }
        fingerprint = request_fingerprint(request)
        ledger.admit(context["operation_id"], fingerprint, context["attempt_id"])
        counters.admission += 1
        counters.upstream += 1
        observed = _transport_result(transport(request), grant["scenario"])
        output_session = _write_output_custody(prepared, observed)
        captured.update({
            "request_fingerprint": fingerprint,
            "operation_id": context["operation_id"],
            "attempt_id": context["attempt_id"],
            "terminal": observed["terminal"], "cleanup": observed["cleanup"],
        })
        try:
            ledger.admit(context["operation_id"], fingerprint, context["attempt_id"])
        except CustodyError as error:
            _runner_require(str(error) == "CUSTODY_NO_OVERWRITE",
                            "SECOND_ADMISSION_UNEXPECTED")
            counters.admission_stop += 1
        else:
            raise RunnerError("SECOND_ADMISSION_NOT_STOPPED")
        if observed["terminal"] == "exact" and observed["cleanup"] == "complete":
            return ProviderResultV1(
                provider, context["operation_id"], Phase.TERMINAL,
                Submission.DEFINITELY_SUBMITTED, TerminalProof.VERIFIED,
                ResultStatus.SUCCEEDED, "SYNTHETIC_TERMINAL_VERIFIED",
                failure_kind=FailureKind.NONE,
                receipt={"injected": True, "terminal_exact": True,
                         "cleanup_complete": True, "admission_single_use": True},
            )
        return ProviderResultV1(
            provider, context["operation_id"], Phase.STREAMING,
            Submission.DEFINITELY_SUBMITTED, TerminalProof.ABSENT,
            ResultStatus.UNKNOWN, "SYNTHETIC_TERMINAL_TRUNCATED",
            failure_kind=FailureKind.MISSING_TERMINAL,
            receipt={"injected": True, "terminal_truncated": True,
                     "cleanup_fault": True, "admission_single_use": True},
        )

    engine = Engine(
        prepared.engine_state, [job], policy, dispatch,
        workspace_root=prepared.workspace, clock=lambda: _instant(grant["slot_at"]),
        max_workers=1,
    )
    summary = engine.tick(_instant(grant["slot_at"]))
    expected_status = "succeeded" if grant["scenario"] == "nominal" else "unknown"
    _runner_require(summary["dispatched"] == 1 and summary[expected_status] == 1,
                    "ENGINE_EXECUTION_UNEXPECTED")
    binding = _atomic_engine_binding(engine, grant, prepared.binding_root, provider)
    _runner_require(binding["engine_status"] == expected_status,
                    "ENGINE_BINDING_STATUS_UNEXPECTED")
    restarted = Engine(
        prepared.engine_state, [job], policy,
        lambda *_args: (_ for _ in ()).throw(RunnerError("RECONSTRUCTION_DISPATCHED")),
        workspace_root=prepared.workspace, clock=lambda: _instant(grant["slot_at"]),
        max_workers=1,
    )
    reconstruction = restarted.tick(_instant(grant["slot_at"]))
    counters.reconstruction_dispatch += reconstruction["dispatched"]
    _runner_require(counters.reconstruction_dispatch == 0 and counters.dispatch == 1,
                    "RECONSTRUCTION_REPLAYED")
    if output_session is not None:
        output_session.verify()
        output_session.close()
    decision = "PASS" if expected_status == "succeeded" else "UNKNOWN"
    code = "EXACT_TERMINAL_VERIFIED" if decision == "PASS" else "TERMINAL_OR_CLEANUP_AMBIGUOUS"
    evidence = _evidence(
        grant, decision, code, counters, binding, captured["terminal"],
        captured["cleanup"], "STOP")
    _, publication = publish_evidence(evidence, prepared.public_root)
    return Execution(dict(grant), evidence, binding, publication)


__all__ = [
    "Counters", "Execution", "PreparedCase", "RunnerError", "Transport",
    "execute_provider_free", "materialize_provider_free_case",
    "source_generation_sha256",
]
