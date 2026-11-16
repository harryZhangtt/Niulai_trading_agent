"""Exact-source protocol-v3 Gmail adapter for LLM candidate 1.0.2."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import sys
import time
import types
from typing import Any, Mapping

RUNTIME_CONTEXT_VERSION = 3
REQUIRED_SERVICE_PROTOCOL_VERSION = 2
CANDIDATE_VERSION = "1.0.2"
CANDIDATE_FINGERPRINT = "978efbf0cf440595c1e2aad992e5a32a5ef9b26517f29b8029ff806c0e3d710f"
CANDIDATE_ID = "llm-engineering-guidance-1.0.2"
PROFILE_NAME = "llm-engineering-candidate-1-0-2-gmail-only"
GMAIL_CONNECTOR = "connector_2128aebfecb84f64a069897515042a44"
PROMPT_PATH = "tuning/evals/llm-engineering-guidance-v2/live-scheduler-email-prompt.md"
PROMPT_SHA256 = "7ca28576b3b84d3024ef4268ae7e843ede4139bb78541c084e875f522788c8ae"
PROMPT_LENGTH = 1064
EMAIL_SYNC_PATH = "tuning/evals/information_fetch/live_e2e/email_sync.py"
EMAIL_SYNC_SHA256 = "eaffb3fa4fca54889e8f8cfe101b4a86f08f4dab095ebc28efffa5bf0d29e6aa"

_CANDIDATE_SOURCE_HASHES = {
    "candidate.json": "8e7e8d1847e908b53d6049586b2402ebc0447a6cf462e53618a8e07b8238f3e4",
    "leakage-policy.json": "3cb38ea2e7665bf0234a837a410d9358ba2e3cab4132cdb6b61a897451e0e0cb",
    "model-view-contract.json": "5586baecde4734b65a6ab69dc266940eaf113170743c46e02cfca84148252d50",
    "schemas/solver-output-v2.schema.json": "7257705b6451f0c4a09cfe3701b120661df3b44c527ef864bf5570ee2d931606",
    "schemas/solver-result-receipt-v2.schema.json": "ae59b8a8ad8a6c851a24107d25510094923c0f523eabeb63c8fda9c1d28d84da",
    "solver-output-contract.json": "0d1760f9ae24f7f9c14f07172287001734405623375d6d8b3804e15db0e8a3e9",
    "solver-system-prompt.md": "ee24f8dfda9906cd72dbee9759bb7357639b647e95b600167f44324c0de7d598",
    "validate.py": "57bdc1ad177be1f2e6922c33c50ac811a69dea0d31f3ebef3af06b15ce7ce097",
}
_BASE_CORPUS_HASHES = {
    "catalog.json": "3e2ae06a02a0f70b3ca3c616c472c52c89db865eb20a2169b9fa8051152ff694",
    "decision-contract.json": "d775fe9212be8f39c9ad08a3d819b9c7c2f5eb49317e0bfe60b89bef16e9f6d7",
    "diagram-index.json": "c9f1ca75a2741fe4deb63f057908b10037cff7194b379ad16981aadd14684784",
    "knowledge-cards.json": "fefabbe32f5698b72e018c300d0f0ca323c0fcec594228302522a768aa2673ac",
    "source-ledger.json": "8d4e6e775d3834cb57b806656da8e9ba994281e20b1c2b16e899cf631223c283",
}
_RECEIPT_KEYS = {
    "schema_version", "kind", "candidate_version", "candidate_fingerprint",
    "job_id", "schedule", "request_id", "scope", "recipient",
    "recipient_sha256", "profile_email", "profile_email_sha256",
    "explicit_user_authorization",
}
_AUTH_REF_KEYS = {"path", "sha256"}
_AUTH_RECORD_KEYS = {
    "schema_version", "kind", "authority_id", "authorized", "authorized_at",
    "user_instruction_sha256", "action",
}
_ACTION_KEYS = {
    "candidate_fingerprint", "job_id", "schedule", "request_id",
    "recipient_sha256", "profile_email_sha256", "effect",
}
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_SHA256 = re.compile(r"[a-f0-9]{64}")


class CandidateAdapterError(ValueError):
    """Stable local failure code; sensitive details are never surfaced."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CandidateAdapterError(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _strict_json(raw: bytes, code: str) -> Any:
    def pairs(items):
        value = {}
        for key, item in items:
            _require(key not in value, code)
            value[key] = item
        return value
    try:
        return json.loads(raw, object_pairs_hook=pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise CandidateAdapterError(code) from None


def _read_exact(path: Path, expected: str, code: str, maximum: int = 4 * 1024 * 1024) -> bytes:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        _require(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= maximum, code)
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(131072, remaining))
            _require(bool(chunk), code)
            chunks.append(chunk)
            remaining -= len(chunk)
        _require(os.read(descriptor, 1) == b"", code)
        after = os.fstat(descriptor)
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
        raw = b"".join(chunks)
        _require(identity(before) == identity(after) and _sha(raw) == expected, code)
        return raw
    except OSError:
        raise CandidateAdapterError(code) from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_email_sync(workspace: Path):
    """Execute only the pinned bytes, without importing its package initializer."""
    path = workspace / EMAIL_SYNC_PATH
    raw = _read_exact(path, EMAIL_SYNC_SHA256, "CANDIDATE_EMAIL_SYNC_DRIFT")
    name = f"_candidate_email_sync_{os.getpid()}_{time.monotonic_ns()}"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        code = compile(raw, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
        return module
    except CandidateAdapterError:
        raise
    except Exception:
        raise CandidateAdapterError("CANDIDATE_EMAIL_SYNC_LOAD_FAILED") from None
    finally:
        sys.modules.pop(name, None)


def _verify_local_closure(workspace: Path) -> None:
    prompt = _read_exact(workspace / PROMPT_PATH, PROMPT_SHA256,
                         "CANDIDATE_PROMPT_DRIFT", maximum=65536)
    _require(len(prompt) == PROMPT_LENGTH, "CANDIDATE_PROMPT_DRIFT")
    corpus = workspace / "mentor/references/llm-engineering"
    candidate_root = corpus / "candidates/1.0.2"
    for relative, expected in _CANDIDATE_SOURCE_HASHES.items():
        _read_exact(candidate_root / relative, expected, "CANDIDATE_SOURCE_DRIFT")
    for relative, expected in _BASE_CORPUS_HASHES.items():
        _read_exact(corpus / relative, expected, "CANDIDATE_BASE_CORPUS_DRIFT")
    candidate = _strict_json((candidate_root / "candidate.json").read_bytes(),
                             "CANDIDATE_SOURCE_DRIFT")
    _require(candidate.get("candidate_version") == CANDIDATE_VERSION
             and candidate.get("fingerprint") == {
                 "algorithm": "sha256-canonical-json-v1",
                 "sha256": CANDIDATE_FINGERPRINT,
             }, "CANDIDATE_SOURCE_DRIFT")
    _require(candidate.get("base_knowledge_corpus", {}).get("file_sha256")
             == _BASE_CORPUS_HASHES, "CANDIDATE_BASE_CORPUS_DRIFT")


def _options(value: object) -> dict[str, str]:
    _require(isinstance(value, Mapping) and set(value) == {"activation_receipt"},
             "CANDIDATE_OPTIONS_INVALID")
    path = value["activation_receipt"]
    _require(isinstance(path, str) and path, "CANDIDATE_OPTIONS_INVALID")
    relative = Path(path)
    _require(not relative.is_absolute() and ".." not in relative.parts
             and len(relative.parts) >= 4
             and relative.parts[:2] == (".job-runtime", "acceptance")
             and relative.suffix == ".json", "ACTIVATION_RECEIPT_PATH_INVALID")
    return {"activation_receipt": path}


def _context(value: object, *, require_job: bool) -> dict[str, Any]:
    _require(isinstance(value, Mapping), "CANDIDATE_CONTEXT_INVALID")
    context = dict(value)
    required = {"slot_id", "attempt_id", "scheduled_at"}
    if require_job:
        required.add("job_id")
    _require(required <= set(context) and all(
        isinstance(context[key], str) and context[key] for key in required),
        "CANDIDATE_CONTEXT_INVALID")
    return context


def _private_json(workspace: Path, relative: str, code: str,
                  expected: str | None = None) -> tuple[dict[str, Any], str]:
    path = workspace / relative
    try:
        resolved = path.resolve(strict=True)
        state = (workspace / ".job-runtime").resolve(strict=True)
        _require(resolved.is_relative_to(state), code)
        for item in (path, *path.parents):
            if item == workspace:
                break
            _require(not item.is_symlink(), code)
        info = path.stat()
        _require(info.st_uid == os.getuid() and stat.S_ISREG(info.st_mode)
                 and stat.S_IMODE(info.st_mode) & 0o077 == 0
                 and 0 < info.st_size <= 65536, code)
        raw = path.read_bytes()
    except OSError:
        raise CandidateAdapterError(code) from None
    digest = _sha(raw)
    _require(expected is None or digest == expected, code)
    value = _strict_json(raw, code)
    _require(isinstance(value, dict), code)
    return value, digest


def _activation(options: Mapping[str, str], workspace: Path,
                context: Mapping[str, Any], *, job_id: str) -> dict[str, Any]:
    receipt, digest = _private_json(workspace, options["activation_receipt"],
                                    "ACTIVATION_RECEIPT_INVALID")
    _require(set(receipt) == _RECEIPT_KEYS
             and receipt["schema_version"] == 1
             and receipt["kind"] == "llm_engineering_1_0_2_live_email_activation"
             and receipt["candidate_version"] == CANDIDATE_VERSION
             and receipt["candidate_fingerprint"] == CANDIDATE_FINGERPRINT,
             "ACTIVATION_RECEIPT_IDENTITY_INVALID")
    _require(receipt["job_id"] == job_id, "ACTIVATION_RECEIPT_JOB_INVALID")
    schedule = receipt["schedule"]
    _require(isinstance(schedule, dict)
             and set(schedule) == {"kind", "at", "grace_seconds"}
             and schedule["kind"] == "once"
             and type(schedule["grace_seconds"]) is int
             and 1 <= schedule["grace_seconds"] <= 900
             and schedule["at"] == context["scheduled_at"],
             "ACTIVATION_RECEIPT_SCHEDULE_INVALID")
    try:
        scheduled = datetime.fromisoformat(schedule["at"].replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise CandidateAdapterError("ACTIVATION_RECEIPT_SCHEDULE_INVALID") from None
    _require(scheduled.tzinfo is not None and scheduled.utcoffset() is not None,
             "ACTIVATION_RECEIPT_SCHEDULE_INVALID")
    _require(isinstance(receipt["request_id"], str)
             and _SAFE_ID.fullmatch(receipt["request_id"]), "ACTIVATION_RECEIPT_INVALID")
    _require(isinstance(receipt["scope"], str) and receipt["scope"].strip()
             and len(receipt["scope"]) <= 500, "ACTIVATION_RECEIPT_INVALID")
    for field in ("recipient", "profile_email"):
        value = receipt[field]
        _require(isinstance(value, str) and value == value.lower()
                 and _EMAIL.fullmatch(value)
                 and receipt[field + "_sha256"] == _sha(value.encode()),
                 "ACTIVATION_RECEIPT_EMAIL_INVALID")
    reference = receipt["explicit_user_authorization"]
    _require(isinstance(reference, dict) and set(reference) == _AUTH_REF_KEYS
             and isinstance(reference["path"], str)
             and isinstance(reference["sha256"], str)
             and _SHA256.fullmatch(reference["sha256"]),
             "ACTIVATION_AUTHORIZATION_REF_INVALID")
    authorization, _ = _private_json(workspace, reference["path"],
                                      "EXPLICIT_USER_AUTHORIZATION_INVALID",
                                      expected=reference["sha256"])
    _require(set(authorization) == _AUTH_RECORD_KEYS
             and authorization["schema_version"] == 1
             and authorization["kind"] == "explicit_user_one_off_email_authorization"
             and authorization["authorized"] is True
             and isinstance(authorization["authority_id"], str)
             and _SAFE_ID.fullmatch(authorization["authority_id"])
             and isinstance(authorization["user_instruction_sha256"], str)
             and _SHA256.fullmatch(authorization["user_instruction_sha256"]),
             "EXPLICIT_USER_AUTHORIZATION_INVALID")
    try:
        authorized = datetime.fromisoformat(
            authorization["authorized_at"].replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        raise CandidateAdapterError("EXPLICIT_USER_AUTHORIZATION_INVALID") from None
    _require(authorized.tzinfo is not None and authorized.utcoffset() is not None,
             "EXPLICIT_USER_AUTHORIZATION_INVALID")
    expected_action = {
        "candidate_fingerprint": CANDIDATE_FINGERPRINT,
        "job_id": receipt["job_id"], "schedule": receipt["schedule"],
        "request_id": receipt["request_id"],
        "recipient_sha256": receipt["recipient_sha256"],
        "profile_email_sha256": receipt["profile_email_sha256"],
        "effect": "one_gmail_send_and_exact_raw_readback",
    }
    _require(isinstance(authorization["action"], dict)
             and set(authorization["action"]) == _ACTION_KEYS
             and authorization["action"] == expected_action,
             "EXPLICIT_USER_AUTHORIZATION_ACTION_INVALID")
    return {**receipt, "receipt_sha256": digest,
            "authorization_sha256": reference["sha256"]}


def _profile_contract(runtime: Mapping[str, Any]) -> None:
    profile = _plain(runtime.get("model_profile"))
    _require(runtime.get("version") == RUNTIME_CONTEXT_VERSION
             and runtime.get("model_profile_name") == PROFILE_NAME
             and isinstance(profile, dict)
             and profile.get("executor") == "business"
             and profile.get("phase") == "business"
             and profile.get("apps") == [GMAIL_CONNECTOR]
             and profile.get("shell") is False
             and profile.get("approval_mode") == "automatic_review"
             and "writable_roots" not in profile,
             "CANDIDATE_PROFILE_CONTRACT_INVALID")


def _runtime_prompt(runtime: Mapping[str, Any]) -> None:
    _require(runtime.get("prompt_sha256") == PROMPT_SHA256
             and runtime.get("prompt_length") == PROMPT_LENGTH,
             "CANDIDATE_RUNTIME_PROMPT_INVALID")


def _outbox_path(workspace: Path, activation: Mapping[str, Any]) -> Path:
    identity = _sha((activation["job_id"] + ":" + activation["request_id"] + ":"
                     + activation["receipt_sha256"] + ":"
                     + activation["authorization_sha256"]).encode())[:32]
    return workspace / ".job-runtime/candidates/llm-engineering-guidance-1.0.2" / (identity + ".sqlite")


def _summary(email, activation: Mapping[str, Any], context: Mapping[str, Any]):
    result = {
        "execution_status": "unverified", "scheduled_at": context["scheduled_at"],
        "actual_timing": "future scheduler attempt; acceptance requires exact Gmail raw readback",
        "job_id": activation["job_id"], "session_id": context["slot_id"],
        "verified_outputs": ["candidate 1.0.2 package and base corpus hashes"],
        "coverage": "candidate-specific provider-free live-scheduler email path only",
        "failure_codes": [],
        "recovery": "unknown delivery remains fenced; reconciliation is required before any replay",
        "evidence_refs": [f"activation:{activation['receipt_sha256'][:24]}"],
    }
    return email.build_host_summary(
        host="codex", run_id=context["slot_id"], candidate_id=CANDIDATE_ID,
        scope=activation["scope"], sender="codex_supervisor", mode="scheduled",
        request_id=activation["request_id"], slot_id=context["slot_id"], result=result)


def _runtime_attestation(email, context: Mapping[str, Any], runtime: Mapping[str, Any]):
    service = _plain(runtime.get("service_generation"))
    adapter = _plain(runtime.get("adapter_generation"))
    _require(isinstance(service, dict) and isinstance(service.get("service"), dict)
             and isinstance(adapter, dict), "CANDIDATE_RUNTIME_CONTEXT_INVALID")
    source = service["service"].get("source_sha256")
    candidate = adapter.get("source_sha256")
    _require(isinstance(source, str) and _SHA256.fullmatch(source)
             and isinstance(candidate, str) and _SHA256.fullmatch(candidate),
             "CANDIDATE_RUNTIME_CONTEXT_INVALID")
    generation = _sha(json.dumps(service, sort_keys=True, separators=(",", ":")).encode())
    return email.GmailRuntimeAttestation(
        job_id=context["job_id"], slot_id=context["slot_id"],
        attempt_id=context["attempt_id"], service_source_sha256=source,
        service_generation_sha256=generation, adapter_source_sha256=candidate)


def _claim_attestation(email, context: Mapping[str, Any], claim: Mapping[str, Any], *, job_id: str):
    fields = ("host", "run", "candidate")
    _require(claim.get("job_id") == job_id
             and claim.get("slot_id") == context["slot_id"]
             and claim.get("attempt_id") == context["attempt_id"]
             and all(isinstance(claim.get(field), str)
                     and _SHA256.fullmatch(claim[field]) for field in fields),
             "CANDIDATE_CLAIM_BINDING_INVALID")
    _require(claim["candidate"] == _sha(Path(__file__).read_bytes()),
             "CANDIDATE_SOURCE_ATTESTATION_DRIFT")
    return email.GmailRuntimeAttestation(
        job_id=job_id, slot_id=context["slot_id"], attempt_id=context["attempt_id"],
        service_source_sha256=claim["host"], service_generation_sha256=claim["run"],
        adapter_source_sha256=claim["candidate"])


def _outbox(email, workspace: Path, activation: Mapping[str, Any]):
    return email.AcceptanceOutbox(_outbox_path(workspace, activation), workspace)


def _prepared_payload(email, activation, workspace, context, runtime):
    attestation = _runtime_attestation(email, context, runtime)
    summary = _summary(email, activation, context)
    message = summary.message(activation["recipient"])
    claim = email.build_gmail_claim(
        summary, activation["recipient"], profile_email=activation["profile_email"],
        runtime_attestation=attestation)
    digest = email.host_payload_digest(message, claim)
    outbox = _outbox(email, workspace, activation)
    key = email.host_notification_key(summary.host, summary.run_id, summary.candidate_id)
    existing = outbox.get(key)
    if existing is not None:
        status = existing.get("status")
        if status == "accepted" and existing.get("verified_digest"):
            return {"status": "succeeded", "code": "CANDIDATE_GMAIL_ALREADY_VERIFIED",
                    "receipt": {"duplicate_suppressed": True, "business_delivery": False}}
        if status in {"sending", "unknown", "accepted"}:
            return {"status": "unknown", "code": "CANDIDATE_GMAIL_RECONCILIATION_REQUIRED",
                    "receipt": {"duplicate_suppressed": True}}
        _require(status == "prepared" and existing.get("digest") == digest,
                 "CANDIDATE_OUTBOX_CONFLICT")
    else:
        outbox.prepare(key, message, recipient=activation["recipient"],
                       profile_email=activation["profile_email"], payload_digest=digest)
    return {"candidate_version": CANDIDATE_VERSION, "notification": message,
            "profile_email": activation["profile_email"], "gmail_claim": claim}


def prepare(options: object, workspace: str | Path, context: object,
            runtime: Mapping[str, Any]) -> dict[str, Any]:
    try:
        root = Path(workspace).resolve(strict=True)
        checked_options = _options(options)
        checked_context = _context(context, require_job=True)
        _verify_local_closure(root)
        _profile_contract(runtime)
        _runtime_prompt(runtime)
        email = _load_email_sync(root)
        activation = _activation(checked_options, root, checked_context,
                                 job_id=checked_context["job_id"])
        return _prepared_payload(email, activation, root, checked_context, runtime)
    except CandidateAdapterError as error:
        return {"status": "failed", "code": str(error),
                "receipt": {"dispatch_phase": "not_dispatched"}}
    except (OSError, ValueError, TypeError):
        return {"status": "failed", "code": "CANDIDATE_GMAIL_PREPARATION_FAILED",
                "receipt": {"dispatch_phase": "not_dispatched"}}


def commit_dispatch(options: object, workspace: str | Path, context: object,
                    claim: Mapping[str, Any]) -> Mapping[str, str]:
    root = Path(workspace).resolve(strict=True)
    checked_options = _options(options)
    checked_context = _context(context, require_job=True)
    _verify_local_closure(root)
    email = _load_email_sync(root)
    activation = _activation(checked_options, root, checked_context,
                             job_id=checked_context["job_id"])
    attestation = _claim_attestation(email, checked_context, claim,
                                     job_id=activation["job_id"])
    summary = _summary(email, activation, checked_context)
    expected = email.build_gmail_claim(
        summary, activation["recipient"], profile_email=activation["profile_email"],
        runtime_attestation=attestation)
    _require(dict(claim) == expected, "CANDIDATE_CLAIM_BINDING_INVALID")
    key = email.host_notification_key(summary.host, summary.run_id, summary.candidate_id)
    return _outbox(email, root, activation).claim(key, checked_context["attempt_id"])


def release_not_dispatched(options: object, workspace: str | Path, context: object,
                           claim: Mapping[str, Any] | None = None) -> None:
    try:
        if claim is None:
            return
        root = Path(workspace).resolve(strict=True)
        checked_options = _options(options)
        checked_context = _context(context, require_job=True)
        email = _load_email_sync(root)
        activation = _activation(checked_options, root, checked_context,
                                 job_id=checked_context["job_id"])
        attestation = _claim_attestation(email, checked_context, claim,
                                         job_id=activation["job_id"])
        summary = _summary(email, activation, checked_context)
        expected = email.build_gmail_claim(
            summary, activation["recipient"], profile_email=activation["profile_email"],
            runtime_attestation=attestation)
        if dict(claim) != expected:
            return
        digest = email.host_payload_digest(summary.message(activation["recipient"]), claim)
        key = email.host_notification_key(summary.host, summary.run_id, summary.candidate_id)
        outbox = _outbox(email, root, activation)
        with sqlite3.connect(outbox.path, timeout=10) as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM outbox WHERE key=? AND digest=? AND status='prepared'",
                       (key, digest))
    except Exception:
        return


def verify(options: object, workspace: str | Path, context: object,
           result: object) -> dict[str, Any]:
    try:
        root = Path(workspace).resolve(strict=True)
        checked_options = _options(options)
        checked_context = _context(context, require_job=False)
        _verify_local_closure(root)
        email = _load_email_sync(root)
        _require(isinstance(result, Mapping), "CANDIDATE_RESULT_INVALID")
        receipt = result.get("receipt")
        _require(isinstance(receipt, Mapping), "CANDIDATE_RESULT_INVALID")
        claim = receipt.get("gmail_claim")
        _require(isinstance(claim, Mapping), "CANDIDATE_RESULT_INVALID")
        activation = _activation(checked_options, root, checked_context,
                                 job_id=claim.get("job_id"))
        attestation = _claim_attestation(email, checked_context, claim,
                                         job_id=activation["job_id"])
        summary = _summary(email, activation, checked_context)
        reconciled = email.reconcile_codex_host_delivery(
            summary=summary, recipient=activation["recipient"],
            profile_email=activation["profile_email"], runtime_attestation=attestation,
            outbox=_outbox(email, root, activation), receipt=receipt)
        evidence = reconciled["verification"]
        return {"verified": True, "code": "CANDIDATE_GMAIL_RAW_READBACK_VERIFIED",
                "receipt": {"message_id": evidence["message_id"],
                            "readback_verified_at": evidence["readback_verified_at"],
                            "raw_readback_sha256": evidence["raw_readback_sha256"],
                            "verification_sha256": evidence["verification_sha256"],
                            "candidate_version": CANDIDATE_VERSION}}
    except (CandidateAdapterError, OSError, ValueError, TypeError, KeyError):
        return {"verified": False, "code": "CANDIDATE_GMAIL_POSTCONDITION_FAILED"}
