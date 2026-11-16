"""Durable schedule admission and retry state, independent of models and jobs.

The supervisor owns process lifetime. Dispatchers own external execution and must
return transport receipts, not treat a model's statement as delivery evidence.
Unknown outcomes block a job until an operator reconciles its exact attempt.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import uuid
from zoneinfo import ZoneInfo

from .prompt_custody import PromptArtifactDescriptorV1
from .provider_contract import (
    FailureKind, Phase, Provider, ProviderResultV1, ReconciliationAdapter,
    ReconciliationProofV1, ReplayContractV1, ReplayEffect, ResultStatus,
    Submission, TerminalProof,
    validate_replay,
)
from .retry_policy import RetryDecision, RetryPolicyV2, decide_retry, validate_retry_policy
from .engine_schema import SCHEMA_VERSION, create_schema9, verify_schema9

UTC = timezone.utc
TERMINAL = ("succeeded", "failed", "unknown", "missed", "coalesced")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCOPE_PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class EngineError(ValueError):
    """Fixed, non-content diagnostic suitable for private operational logs."""


def require(test, code):
    if not test:
        raise EngineError(code)


def instant(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise EngineError("INVALID_AWARE_TIME") from None
    require(isinstance(value, datetime) and value.tzinfo is not None
            and value.utcoffset() is not None, "AWARE_TIME_REQUIRED")
    return value.astimezone(UTC)


def _int(value, low, high):
    return type(value) is int and low <= value <= high


def _encode_receipt(receipt):
    stack = [(receipt, 0, False)]
    active = set()
    nodes = 0
    while stack:
        value, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(value))
            continue
        nodes += 1
        require(nodes <= 10000 and depth <= 64, "INVALID_TRANSPORT_RECEIPT")
        if isinstance(value, (dict, list, tuple)):
            identity = id(value)
            require(identity not in active, "INVALID_TRANSPORT_RECEIPT")
            active.add(identity)
            stack.append((value, depth, True))
            children = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
            for key, child in reversed(children):
                stack.append((child, depth + 1, False))
                if isinstance(value, dict):
                    stack.append((key, depth + 1, False))
    try:
        encoded = json.dumps(receipt, sort_keys=True, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise EngineError("INVALID_TRANSPORT_RECEIPT") from None
    require(len(encoded.encode("utf-8")) <= 65536, "RECEIPT_TOO_LARGE")
    return encoded


def _schedule_instant(value):
    require(isinstance(value, str) and re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value),
        "SCHEDULE_TIME_INVALID")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        raise EngineError("SCHEDULE_TIME_INVALID") from None


def _plain(value):
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value


def _canonical(value):
    try:
        return json.dumps(_plain(value), sort_keys=True, separators=(",", ":"),
                          ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise EngineError("CANONICAL_VALUE_INVALID") from None


def _sha256(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode("utf-8")).hexdigest()


def _circuit_scope_sha256(provider, profile, resource_hash):
    return _sha256(_canonical({
        "provider": provider, "profile": profile, "resource_hash": resource_hash,
    }))


def _artifact_values(descriptor):
    require(isinstance(descriptor, PromptArtifactDescriptorV1),
            "PROMPT_ARTIFACT_DESCRIPTOR_REQUIRED")
    return {
        "artifact_ref": descriptor.ref,
        "sha256": descriptor.sha256,
        "length": descriptor.length,
        "version": descriptor.version,
        "source_identity_sha256": descriptor.source_identity_sha256,
        "generation": descriptor.generation,
        "proof_origin": "native_v1",
    }


def _prompt_binding_sha256(job_id, slot_id, values):
    return _sha256(_canonical({
        "schema": 1, "job_id": job_id, "slot_id": slot_id,
        "artifact": {key: values[key] for key in (
            "artifact_ref", "sha256", "length", "version",
            "source_identity_sha256", "generation", "proof_origin")},
    }))


def _provider_result_json(result):
    """Match ProviderResultV1.canonical_sha256 bytes, including ASCII escaping."""
    require(isinstance(result, ProviderResultV1), "PROVIDER_RESULT_REQUIRED")
    try:
        encoded = json.dumps(_plain(result.to_mapping()), sort_keys=True,
                             separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise EngineError("PROVIDER_RESULT_CANONICAL_INVALID") from None
    require(_sha256(encoded) == result.canonical_sha256,
            "PROVIDER_RESULT_CANONICAL_MISMATCH")
    return encoded


def _replay_mapping(contract):
    return {
        "version": contract.version,
        "effect": contract.effect.value,
        "automatic_phases": [phase.value for phase in contract.automatic_phases],
        "slot_operation_scope": contract.slot_operation_scope,
        "reconciliation_adapter": contract.reconciliation_adapter,
    }


def _policy_mapping(policy):
    return {
        "version": policy.version,
        "max_attempts": policy.max_attempts,
        "base_delay_seconds": policy.base_delay_seconds,
        "max_delay_seconds": policy.max_delay_seconds,
        "deadline_seconds": policy.deadline_seconds,
        "jitter": policy.jitter,
    }


def _result_from_json(encoded):
    value = json.loads(encoded)
    retry_after = value.get("retry_after_at")
    if retry_after is not None:
        retry_after = instant(retry_after)
    return ProviderResultV1(
        provider=value["provider"], operation_id=value["operation_id"], phase=value["phase"],
        submission=value["submission"], terminal_proof=value["terminal_proof"],
        status=value["status"], code=value["code"], failure_kind=value["failure_kind"],
        http_status=value.get("http_status"), provider_should_retry=value.get("provider_should_retry"),
        retry_after_at=retry_after, retry_after_source=value.get("retry_after_source"),
        receipt=value.get("receipt"), version=value["version"])


def _proof_from_json(encoded):
    value = json.loads(encoded)
    return ReconciliationProofV1(
        attempt_id=value["attempt_id"], operation_id=value["operation_id"],
        slot_operation_scope=value["slot_operation_scope"],
        provider_result_sha256=value["provider_result_sha256"], outcome=value["outcome"],
        evidence_sha256=value["evidence_sha256"], recorded_at=instant(value["recorded_at"]),
        version=value["version"])


def _contract_from_json(encoded):
    value = json.loads(encoded)
    return ReplayContractV1(
        effect=value["effect"], automatic_phases=tuple(value["automatic_phases"]),
        slot_operation_scope=value["slot_operation_scope"],
        reconciliation_adapter=value.get("reconciliation_adapter"), version=value["version"])


def validate_job(job):
    require(isinstance(job, dict), "JOB_INVALID")
    require(isinstance(job.get("id"), str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", job["id"]), "JOB_ID_INVALID")
    require(type(job.get("enabled")) is bool and type(job.get("replay_safe")) is bool, "JOB_FLAGS_INVALID")
    # This is injected by infrastructure after allocation-schema validation.
    # Job allocations must not choose their own authentication/resource fence.
    if "_resource_key" in job:
        require(isinstance(job["_resource_key"], str) and 1 <= len(job["_resource_key"]) <= 2048,
                "RESOURCE_KEY_INVALID")
    require(not ({"_prompt_snapshot", "_prompt_sha256", "_prompt_capture", "_prompt_raw"} & set(job)),
            "RAW_PROMPT_MATERIAL_REJECTED")
    if "_prompt_artifact" in job:
        require(isinstance(job["_prompt_artifact"], PromptArtifactDescriptorV1),
                "PROMPT_ARTIFACT_DESCRIPTOR_REQUIRED")
    injected = {"_provider", "_replay_contract", "_retry_policy", "_circuit_scope"} & set(job)
    if injected:
        require({"_provider", "_replay_contract", "_retry_policy"} <= set(job),
                "TYPED_PROVIDER_CONFIG_INCOMPLETE")
        try:
            provider = Provider(job["_provider"])
            require(isinstance(job["_replay_contract"], ReplayContractV1), "REPLAY_CONTRACT_INVALID")
            validate_retry_policy(job["_retry_policy"])
        except (ValueError, TypeError):
            raise EngineError("TYPED_PROVIDER_CONFIG_INVALID") from None
        require(provider.value == str(provider.value), "PROVIDER_INVALID")
        require(isinstance(job.get("_prompt_artifact"), PromptArtifactDescriptorV1),
                "PROMPT_ARTIFACT_REQUIRED")
        if "_circuit_scope" in job:
            circuit = job["_circuit_scope"]
            require(type(circuit) is dict and set(circuit) == {
                "profile", "resource_hash", "failure_threshold", "open_seconds", "probe_seconds"
            }, "CIRCUIT_SCOPE_INVALID")
            require(isinstance(circuit["profile"], str) and _SCOPE_PART.fullmatch(circuit["profile"])
                    and isinstance(circuit["resource_hash"], str) and _SHA256.fullmatch(circuit["resource_hash"])
                    and _int(circuit["failure_threshold"], 1, 100)
                    and type(circuit["open_seconds"]) in (int, float) and 0 < circuit["open_seconds"] <= 86400 * 30
                    and type(circuit["probe_seconds"]) in (int, float) and 0 < circuit["probe_seconds"] <= 3600,
                    "CIRCUIT_SCOPE_INVALID")
    s = job.get("schedule")
    require(isinstance(s, dict), "JOB_SCHEDULE_INVALID")
    kind = s.get("kind")
    if kind == "interval":
        require(set(s) <= {"kind", "seconds", "grace_seconds"} and _int(s.get("seconds"), 1, 86400 * 365), "INTERVAL_INVALID")
        require(_int(s.get("grace_seconds", s["seconds"]), 1, 86400 * 7), "GRACE_INVALID")
    elif kind == "daily":
        require(set(s) == {"kind", "timezone", "times", "grace_seconds"}, "DAILY_KEYS_INVALID")
        require(isinstance(s["timezone"], str), "TIMEZONE_INVALID")
        try:
            ZoneInfo(s["timezone"])
        except (ValueError, KeyError):
            raise EngineError("TIMEZONE_INVALID") from None
        times = s["times"]
        require(isinstance(times, list) and 1 <= len(times) <= 24
                and all(isinstance(t, str) and re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", t) for t in times)
                and len(set(times)) == len(times), "DAILY_TIMES_INVALID")
        require(_int(s["grace_seconds"], 1, 86400 * 7), "GRACE_INVALID")
    elif kind == "once":
        require(set(s) == {"kind", "at", "grace_seconds"}, "ONCE_KEYS_INVALID")
        _schedule_instant(s["at"])
        require(_int(s["grace_seconds"], 1, 86400 * 7), "GRACE_INVALID")
    elif kind == "sequence":
        require(set(s) == {"kind", "timestamps", "grace_seconds"}, "SEQUENCE_KEYS_INVALID")
        timestamps = s["timestamps"]
        require(isinstance(timestamps, list) and 1 <= len(timestamps) <= 128
                and all(isinstance(value, str) for value in timestamps), "SEQUENCE_TIMESTAMPS_INVALID")
        parsed = [_schedule_instant(value) for value in timestamps]
        require(all(left < right for left, right in zip(parsed, parsed[1:])),
                "SEQUENCE_TIMESTAMPS_INVALID")
        require(_int(s["grace_seconds"], 1, 86400 * 7), "GRACE_INVALID")
    else:
        raise EngineError("SCHEDULE_KIND_INVALID")


def _private_state(path, workspace_root):
    root = Path(workspace_root).resolve(strict=True)
    allowed = root / ".job-runtime"
    p = Path(os.path.abspath(path))
    require(".." not in Path(path).parts and p.is_relative_to(allowed)
            and p.resolve().is_relative_to(allowed.resolve()), "STATE_OUTSIDE_WORKSPACE")
    for x in [p, *p.parents]:
        if x == root:
            break
        require(not x.is_symlink(), "STATE_SYMLINK_REJECTED")
        if x.exists():
            require(x.is_dir() and x.stat().st_uid == os.getuid(), "STATE_OWNER_INVALID")
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    for x in [p, *p.parents]:
        if x == root:
            break
        x.chmod(0o700)
    return p


class Engine:
    """A synchronous durable dispatcher; safe for competing tick processes.

    ``tick`` never automatically retries a dispatcher exception. Only an
    explicit ``retryable`` response for a replay-safe job authorizes retry.
    The supervisor must not use ``recover_running`` while an old worker lives.
    """

    def __init__(self, state_dir, jobs, retry_policy, dispatcher, workspace_root=None, clock=None,
                 max_workers=2, reconciliation_adapters=None):
        self.workspace = Path(workspace_root or Path(__file__).resolve().parents[2]).resolve(strict=True)
        self.state = _private_state(state_dir, self.workspace)
        require(isinstance(jobs, list), "JOBS_INVALID")
        for job in jobs:
            validate_job(job)
        require(len({j["id"] for j in jobs}) == len(jobs), "DUPLICATE_JOB_ID")
        legacy_retry = (type(retry_policy) is dict and set(retry_policy) == {
            "max_attempts", "backoff_seconds", "max_backoff_seconds"})
        if legacy_retry:
            require(_int(retry_policy["max_attempts"], 1, 10)
                    and _int(retry_policy["backoff_seconds"], 1, 3600)
                    and _int(retry_policy["max_backoff_seconds"], retry_policy["backoff_seconds"], 86400),
                    "RETRY_POLICY_INVALID")
            global_retry_policy = None
        else:
            try:
                global_retry_policy = validate_retry_policy(retry_policy)
            except (TypeError, ValueError):
                raise EngineError("RETRY_POLICY_INVALID") from None
        typed_modes = ["_provider" in job for job in jobs]
        require(not any(typed_modes) or all(typed_modes), "MIXED_JOB_POLICY_MODES")
        if global_retry_policy is not None:
            require(all(typed_modes), "V2_POLICY_REQUIRES_TYPED_JOBS")
        require(callable(dispatcher), "DISPATCHER_REQUIRED")
        require(_int(max_workers, 1, 8), "MAX_WORKERS_INVALID")
        require(reconciliation_adapters is None or type(reconciliation_adapters) is dict,
                "RECONCILIATION_ADAPTERS_INVALID")
        self._reconciliation_adapters = dict(reconciliation_adapters or {})
        require(all(isinstance(identity, str) and _SCOPE_PART.fullmatch(identity)
                    and isinstance(adapter, ReconciliationAdapter)
                    for identity, adapter in self._reconciliation_adapters.items()),
                "RECONCILIATION_ADAPTERS_INVALID")
        self.jobs = {}
        for source in jobs:
            typed = {key: source[key] for key in (
                "_provider", "_replay_contract", "_retry_policy", "_circuit_scope",
                "_prompt_artifact") if key in source}
            plain = {key: value for key, value in source.items() if key not in typed}
            copied = json.loads(json.dumps(plain))
            copied.update(typed)
            if "_provider" in copied:
                copied["_provider"] = Provider(copied["_provider"])
                copied["_retry_policy"] = validate_retry_policy(copied["_retry_policy"])
            self.jobs[copied["id"]] = copied
        circuit_configs = {}
        for configured in self.jobs.values():
            contract = configured.get("_replay_contract")
            if contract is not None and contract.effect is ReplayEffect.RECONCILE_BEFORE_REPLAY:
                require(contract.reconciliation_adapter in self._reconciliation_adapters,
                        "RECONCILIATION_ADAPTER_NOT_REGISTERED")
            circuit = configured.get("_circuit_scope")
            if circuit is not None:
                key = (configured["_provider"].value, circuit["profile"], circuit["resource_hash"])
                encoded = _canonical(circuit)
                require(key not in circuit_configs or circuit_configs[key] == encoded,
                        "CIRCUIT_SCOPE_CONFIG_CONFLICT")
                circuit_configs[key] = encoded
        self.retry = dict(retry_policy) if legacy_retry else None
        self.global_retry_policy = global_retry_policy
        self.dispatcher = dispatcher
        self.max_workers = max_workers
        self.clock = clock or (lambda: datetime.now(UTC))
        self.instance_id = str(uuid.uuid4())
        self.path = self.state / "schedule.sqlite"
        require(not self.path.is_symlink(), "DATABASE_SYMLINK_REJECTED")
        fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self._db() as db:
            self._migrate(db)

    def _migration_execute(self, db, statement):
        """Schema creation seam retained for deterministic failure injection."""
        return db.execute(statement)

    def _migrate(self, db):
        version = db.execute("PRAGMA user_version").fetchone()[0]
        require(version <= SCHEMA_VERSION, "DATABASE_SCHEMA_TOO_NEW")
        objects = db.execute(
            "SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchone()[0]
        if version == SCHEMA_VERSION:
            try:
                verify_schema9(db)
            except (sqlite3.Error, ValueError):
                raise EngineError("DATABASE_SCHEMA_FINGERPRINT_MISMATCH") from None
            return
        if version != 0 or objects:
            raise EngineError("DATABASE_SIDEFILE_MIGRATION_REQUIRED")
        try:
            create_schema9(db, execute=self._migration_execute)
            verify_schema9(db)
        except (sqlite3.Error, ValueError):
            raise

    @staticmethod
    def _mark_schema9_evidence(db, now):
        db.execute(
            "INSERT OR IGNORE INTO metadata(key,value) VALUES('schema9_evidence_write_at',?)",
            (datetime.fromtimestamp(now, UTC).isoformat(),))

    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA journal_mode=DELETE")
        return db

    def heartbeat(self, now):
        value = instant(now).isoformat()
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES('heartbeat',?)", (value,))
        return value

    def _insert(self, db, slot_id, job_id, scheduled, expiry, now, status=None, code=None,
                job=None):
        status = status or ("ready" if now <= expiry else "missed")
        code = code or ("DUE" if status == "ready" else "GRACE_EXPIRED")
        prompt = None
        if job is not None and "_provider" in job:
            prompt = _artifact_values(job["_prompt_artifact"])
            prompt["binding_sha256"] = _prompt_binding_sha256(job_id, slot_id, prompt)
            db.execute(
                "INSERT OR IGNORE INTO prompt_artifacts(ref,sha256,length,version,"
                "source_identity_sha256,generation,proof_origin) VALUES(?,?,?,?,?,?,?)",
                tuple(prompt[key] for key in (
                    "artifact_ref", "sha256", "length", "version",
                    "source_identity_sha256", "generation", "proof_origin")))
            stored = db.execute(
                "SELECT * FROM prompt_artifacts WHERE ref=?",
                (prompt["artifact_ref"],)).fetchone()
            require(stored is not None and stored["ref"] == prompt["artifact_ref"]
                    and all(stored[key] == prompt[key] for key in (
                        "sha256", "length", "version", "source_identity_sha256",
                        "generation", "proof_origin")),
                    "PROMPT_ARTIFACT_METADATA_CONFLICT")
        self._mark_schema9_evidence(db, now)
        columns = ["slot_id", "job_id", "scheduled_at", "expires_at", "status",
                   "updated_at", "code"]
        values = [slot_id, job_id, scheduled, expiry, status, now, code]
        if prompt is not None:
            columns.extend(("artifact_ref", "sha256", "length", "version",
                            "source_identity_sha256", "binding_sha256", "generation",
                            "proof_origin"))
            values.extend(prompt[key] for key in columns[-8:])
            typed = self._typed_slot_values(job, {
                "scheduled_at": scheduled, "expires_at": expiry})
            columns.extend(typed)
            values.extend(typed.values())
        marks = ",".join("?" for _ in columns)
        db.execute(f"INSERT OR IGNORE INTO slots({','.join(columns)}) VALUES({marks})", values)

    def _allocate(self, db, job, now):
        s, job_id = job["schedule"], job["id"]
        digest = hashlib.sha256(json.dumps(s, sort_keys=True).encode()).hexdigest()
        previous = db.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
        if previous:
            require(previous["schedule_hash"] == digest, "SCHEDULE_CHANGE_REQUIRES_NEW_JOB_ID")
            require(now >= previous["cursor"], "CLOCK_MOVED_BACKWARDS")
        cursor = previous["cursor"] if previous else None
        if previous is None:
            db.execute("INSERT INTO jobs VALUES(?,?,?)", (job_id, digest, now))
        if s["kind"] == "interval":
            seconds = s["seconds"]
            index = math.floor(now / seconds)
            scheduled = index * seconds
            if cursor is None or scheduled > math.floor(cursor / seconds) * seconds:
                if cursor is not None:
                    first = math.floor(cursor / seconds) + 1
                    skipped = index - first
                    if skipped > 0:
                        self._insert(db, f"{job_id}:coalesced:{first}-{index - 1}", job_id, first * seconds,
                                     scheduled, now, "coalesced", f"INTERVALS_COALESCED_{min(skipped, 999999)}",
                                     job=job)
                self._insert(db, f"{job_id}:interval:{index}", job_id, scheduled,
                             scheduled + s.get("grace_seconds", seconds), now, job=job)
        elif s["kind"] == "once":
            scheduled = instant(s["at"]).timestamp()
            if scheduled <= now:
                self._insert(db, f"{job_id}:once:{instant(s['at']).isoformat()}", job_id,
                             scheduled, scheduled + s["grace_seconds"], now, job=job)
        elif s["kind"] == "sequence":
            for index, value in enumerate(s["timestamps"]):
                scheduled = instant(value).timestamp()
                if scheduled > now or (cursor is not None and scheduled <= cursor):
                    continue
                self._insert(db, f"{job_id}:sequence:{index}", job_id,
                             scheduled, scheduled + s["grace_seconds"], now, job=job)
        else:
            zone = ZoneInfo(s["timezone"])
            today = datetime.fromtimestamp(now, UTC).astimezone(zone).date()
            day = datetime.fromtimestamp(cursor, UTC).astimezone(zone).date() if cursor is not None else today
            # Long outages are coalesced to a bounded daily history. Every
            # currently eligible slot remains included; old history is one row.
            if (today - day).days > 366:
                self._insert(db, f"{job_id}:coalesced-days:{day}:{today}", job_id, cursor,
                             now, now, "coalesced", "OLD_DAYS_COALESCED", job=job)
                day = today - timedelta(days=366)
            while day <= today:
                for slot in sorted(s["times"]):
                    hour, minute = map(int, slot.split(":"))
                    local = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone, fold=0)
                    scheduled = local.astimezone(UTC).timestamp()
                    if scheduled > now or (cursor is not None and scheduled <= cursor):
                        continue
                    slot_id = f"{job_id}:daily:{day.isoformat()}:{slot}"
                    roundtrip = datetime.fromtimestamp(scheduled, UTC).astimezone(zone)
                    if (roundtrip.hour, roundtrip.minute, roundtrip.date()) != (hour, minute, day):
                        self._insert(db, slot_id, job_id, scheduled, scheduled, now, "missed",
                                     "LOCAL_TIME_NONEXISTENT", job=job)
                    else:
                        self._insert(db, slot_id, job_id, scheduled,
                                     scheduled + s["grace_seconds"], now, job=job)
                day += timedelta(days=1)
        db.execute("UPDATE jobs SET schedule_hash=?,cursor=? WHERE job_id=?",
                   (digest, now, job_id))

    def _typed_slot_values(self, job, row):
        if "_provider" not in job:
            return None
        contract = job["_replay_contract"]
        policy = job["_retry_policy"]
        contract_json = _canonical(_replay_mapping(contract))
        policy_json = _canonical(_policy_mapping(policy))
        deadline = row["expires_at"]
        if policy.deadline_seconds is not None:
            deadline = min(deadline, row["scheduled_at"] + policy.deadline_seconds)
        circuit = job.get("_circuit_scope")
        circuit_json = _canonical(circuit) if circuit is not None else None
        return {
            "provider": Provider(job["_provider"]).value,
            "replay_contract": contract_json,
            "replay_contract_sha256": _sha256(contract_json),
            "retry_policy": policy_json,
            "retry_policy_fingerprint": policy.fingerprint,
            "retry_deadline": deadline,
            "circuit_profile": circuit.get("profile") if circuit else None,
            "circuit_resource_hash": circuit.get("resource_hash") if circuit else None,
            "circuit_config": circuit_json,
            "circuit_config_sha256": _sha256(circuit_json) if circuit_json else None,
        }

    def _pinned_typed_config(self, row, artifact_row=None):
        if row["provider"] is None:
            return None
        require(_sha256(row["replay_contract"]) == row["replay_contract_sha256"],
                "REPLAY_CONTRACT_DIGEST_MISMATCH")
        policy = validate_retry_policy(json.loads(row["retry_policy"]))
        require(policy.fingerprint == row["retry_policy_fingerprint"],
                "RETRY_POLICY_FINGERPRINT_MISMATCH")
        circuit = json.loads(row["circuit_config"]) if row["circuit_config"] is not None else None
        if circuit is not None:
            require(_sha256(row["circuit_config"]) == row["circuit_config_sha256"],
                    "CIRCUIT_CONFIG_DIGEST_MISMATCH")
        origin = row["proof_origin"]
        require(origin in {"native_v1", "backfilled_v8"},
                "PROMPT_BINDING_NON_DISPATCHABLE")
        values = {key: row[key] for key in (
            "artifact_ref", "sha256", "length", "version",
            "source_identity_sha256", "generation", "proof_origin", "binding_sha256")}
        require(all(values[key] is not None for key in values), "PROMPT_BINDING_MISSING")
        require(_prompt_binding_sha256(row["job_id"], row["slot_id"], values)
                == values["binding_sha256"], "PROMPT_BINDING_CORRUPT")
        require(artifact_row is not None and artifact_row["ref"] == values["artifact_ref"]
                and all(artifact_row[key] == values[key] for key in (
                    "sha256", "length", "version", "source_identity_sha256",
                    "generation", "proof_origin")),
                "PROMPT_ARTIFACT_METADATA_MISSING")
        try:
            artifact = PromptArtifactDescriptorV1(
                values["version"], values["artifact_ref"], values["sha256"],
                values["length"], values["source_identity_sha256"],
                values["generation"], values["proof_origin"])
        except (TypeError, ValueError):
            raise EngineError("PROMPT_BINDING_CORRUPT") from None
        return {"provider": Provider(row["provider"]),
                "contract": _contract_from_json(row["replay_contract"]),
                "policy": policy, "deadline": row["retry_deadline"], "circuit": circuit,
                "prompt_artifact": artifact,
                "prompt_binding_sha256": values["binding_sha256"]}

    def _circuit_admit(self, db, provider, circuit, now, attempt_id):
        if circuit is None:
            return True, None, None, None
        key = (provider.value, circuit["profile"], circuit["resource_hash"])
        scope_sha = _circuit_scope_sha256(*key)
        config_sha = _sha256(_canonical(circuit))
        row = db.execute("SELECT * FROM circuits WHERE provider=? AND profile=? AND resource_hash=?", key).fetchone()
        if row is None:
            db.execute("INSERT INTO circuits VALUES(?,?,?,?,?,0,'closed',0,NULL,NULL,NULL,?)",
                       (*key, scope_sha, config_sha, now))
            return True, None, 0, "closed"
        require(row["scope_sha256"] == scope_sha, "CIRCUIT_SCOPE_DIGEST_MISMATCH")
        if row["config_sha256"] is None:
            db.execute("UPDATE circuits SET config_sha256=? WHERE provider=? AND profile=? AND resource_hash=? AND config_sha256 IS NULL",
                       (config_sha, *key))
            row = db.execute("SELECT * FROM circuits WHERE provider=? AND profile=? AND resource_hash=?", key).fetchone()
        require(row["config_sha256"] == config_sha, "CIRCUIT_SCOPE_CONFIG_DRIFT")
        if row["state"] == "closed":
            return True, None, row["generation"], "closed"
        if row["state"] == "open" and row["opened_until"] is not None and row["opened_until"] > now:
            return False, None, None, None
        if row["state"] == "half_open" and row["probe_expires"] is not None and row["probe_expires"] > now:
            return False, None, None, None
        expiry = now + circuit["probe_seconds"]
        changed = db.execute(
            "UPDATE circuits SET state='half_open',generation=generation+1,probe_owner=?,probe_expires=?,updated_at=? "
            "WHERE provider=? AND profile=? AND resource_hash=? AND generation=? AND "
            "(state='open' OR (state='half_open' AND (probe_expires IS NULL OR probe_expires<=?)))",
            (attempt_id, expiry, now, *key, row["generation"], now)).rowcount
        if changed != 1:
            return False, None, None, None
        current = db.execute("SELECT generation FROM circuits WHERE provider=? AND profile=? AND resource_hash=?", key).fetchone()
        return True, attempt_id, current["generation"], "half_open"

    def _claim(self, job, now):
        if isinstance(job, str):
            require(job in self.jobs, "JOB_NOT_FOUND")
            job = self.jobs[job]
        job_id = job["id"]
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM slots WHERE job_id=? AND status IN ('running','unknown') LIMIT 1", (job_id,)).fetchone():
                return None
            db.execute("UPDATE slots SET status='missed',code='GRACE_EXPIRED',updated_at=? WHERE job_id=? AND status IN ('ready','retry_wait') AND expires_at<?", (now, job_id, now))
            row = db.execute("SELECT * FROM slots WHERE job_id=? AND status IN ('ready','retry_wait') AND (next_attempt_at IS NULL OR next_attempt_at<=?) ORDER BY scheduled_at,slot_id LIMIT 1", (job_id, now)).fetchone()
            if not row:
                return None
            expected = self._typed_slot_values(job, row)
            if expected is not None:
                if row["provider"] is None or row["proof_origin"] == "legacy_unbound":
                    self._mark_schema9_evidence(db, now)
                    db.execute(
                        "UPDATE slots SET status='failed',code='PROMPT_BINDING_NON_DISPATCHABLE',"
                        "updated_at=? WHERE slot_id=?", (now, row["slot_id"]))
                    return None
                require(all(row[name] == value for name, value in expected.items()),
                        "TYPED_SLOT_CONFIG_DRIFT")
            elif row["provider"] is not None:
                raise EngineError("TYPED_SLOT_CONFIG_MISSING")
            artifact_row = None
            if row["artifact_ref"] is not None:
                artifact_row = db.execute(
                    "SELECT * FROM prompt_artifacts WHERE ref=?",
                    (row["artifact_ref"],)).fetchone()
            try:
                pinned = self._pinned_typed_config(row, artifact_row)
            except EngineError as error:
                if row["provider"] is None:
                    raise
                code = str(error)
                if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
                    code = "PROMPT_BINDING_INVALID"
                self._mark_schema9_evidence(db, now)
                db.execute("UPDATE slots SET status='failed',code=?,updated_at=? WHERE slot_id=?",
                           (code, now, row["slot_id"]))
                return None
            attempt_id = str(uuid.uuid4())
            admitted, probe_token, circuit_generation, admission_state = self._circuit_admit(
                db, pinned["provider"] if pinned else None,
                pinned["circuit"] if pinned else None, now, attempt_id)
            if not admitted:
                return None
            number = row["attempts"] + 1
            self._mark_schema9_evidence(db, now)
            db.execute("UPDATE slots SET status='running',attempts=?,updated_at=?,code='DISPATCHING' WHERE slot_id=?", (number, now, row["slot_id"]))
            if pinned:
                db.execute('''INSERT INTO attempts(
                    attempt_id,slot_id,attempt_no,started_at,ended_at,status,code,receipt,
                    artifact_ref,sha256,length,version,source_identity_sha256,binding_sha256,
                    generation,proof_origin) VALUES(?,?,?,?,NULL,'running','DISPATCHING',NULL,
                    ?,?,?,?,?,?,?,?)''',
                    (attempt_id, row["slot_id"], number, now,
                     row["artifact_ref"], row["sha256"], row["length"], row["version"],
                     row["source_identity_sha256"], row["binding_sha256"],
                     row["generation"], row["proof_origin"]))
            else:
                db.execute("INSERT INTO attempts(attempt_id,slot_id,attempt_no,started_at,ended_at,status,code,receipt,proof_origin) VALUES(?,?,?,?,NULL,'running','DISPATCHING',NULL,'legacy_unbound')",
                           (attempt_id, row["slot_id"], number, now))
            context = {"slot_id": row["slot_id"], "attempt_id": attempt_id,
                       "scheduled_at": datetime.fromtimestamp(row["scheduled_at"], UTC).isoformat(),
                       "attempt_no": number, "expires_at": row["expires_at"],
                       "scheduled_epoch": row["scheduled_at"]}
            if pinned:
                operation_id = f"attempt/{attempt_id}/prompt/{pinned['prompt_binding_sha256']}"
                require(len(operation_id) <= 128, "PROVIDER_OPERATION_ID_TOO_LONG")
                context.update({"operation_id": operation_id,
                                "prompt_artifact": pinned["prompt_artifact"],
                                "prompt_binding_sha256": pinned["prompt_binding_sha256"],
                                "_typed_config": pinned, "_probe_token": probe_token,
                                "_circuit_generation": circuit_generation,
                                "_circuit_admission_state": admission_state})
            return context

    def _update_circuit(self, db, pinned, probe_token, admitted_generation,
                        admission_state, result, now):
        circuit = pinned["circuit"]
        if circuit is None:
            return
        key = (pinned["provider"].value, circuit["profile"], circuit["resource_hash"])
        row = db.execute("SELECT * FROM circuits WHERE provider=? AND profile=? AND resource_hash=?", key).fetchone()
        if row is None or admitted_generation is None:
            return
        permanent = result.failure_kind in {FailureKind.AUTH, FailureKind.CONFIG, FailureKind.MODEL,
                                            FailureKind.POLICY, FailureKind.LOCAL_CONFIG}
        transient = result.safe_retry_candidate and not permanent
        if admission_state == "half_open":
            if (row["state"] != "half_open" or row["generation"] != admitted_generation
                    or probe_token is None or row["probe_owner"] != probe_token
                    or row["probe_expires"] is None or row["probe_expires"] <= now):
                return
            if result.status is ResultStatus.SUCCEEDED or permanent:
                db.execute("UPDATE circuits SET state='closed',generation=generation+1,transient_failures=0,opened_until=NULL,probe_owner=NULL,probe_expires=NULL,updated_at=? WHERE provider=? AND profile=? AND resource_hash=? AND state='half_open' AND generation=? AND probe_owner=?",
                           (now, *key, admitted_generation, probe_token))
            else:
                failures = row["transient_failures"] + (1 if transient else 0)
                db.execute("UPDATE circuits SET state='open',generation=generation+1,transient_failures=?,opened_until=?,probe_owner=NULL,probe_expires=NULL,updated_at=? WHERE provider=? AND profile=? AND resource_hash=? AND state='half_open' AND generation=? AND probe_owner=?",
                           (failures, now + circuit["open_seconds"], now, *key,
                            admitted_generation, probe_token))
            return
        if admission_state != "closed" or row["state"] != "closed" or row["generation"] != admitted_generation:
            return
        if result.status is ResultStatus.SUCCEEDED:
            db.execute("UPDATE circuits SET transient_failures=0,opened_until=NULL,probe_owner=NULL,probe_expires=NULL,updated_at=? WHERE provider=? AND profile=? AND resource_hash=? AND state='closed' AND generation=?",
                       (now, *key, admitted_generation))
            return
        if not transient:
            return
        failures = row["transient_failures"] + 1
        if failures >= circuit["failure_threshold"]:
            db.execute("UPDATE circuits SET state='open',generation=generation+1,transient_failures=?,opened_until=?,probe_owner=NULL,probe_expires=NULL,updated_at=? WHERE provider=? AND profile=? AND resource_hash=? AND state='closed' AND generation=?",
                       (failures, now + circuit["open_seconds"], now, *key, admitted_generation))
        else:
            db.execute("UPDATE circuits SET transient_failures=?,updated_at=? WHERE provider=? AND profile=? AND resource_hash=? AND state='closed' AND generation=?",
                       (failures, now, *key, admitted_generation))

    def _finish_typed(self, job, context, result, now):
        pinned = context["_typed_config"]
        policy = pinned["policy"]
        now_dt = datetime.fromtimestamp(now, UTC)
        deadline = datetime.fromtimestamp(pinned["deadline"], UTC)
        decision = decide_retry(result, policy, slot_id=context["slot_id"],
                                attempt=context["attempt_no"], now=now_dt, deadline=deadline)
        authorized = decision.disposition != "retry" or validate_replay(pinned["contract"], result)
        if decision.disposition == "retry" and not authorized:
            decision = RetryDecision("unknown", "REPLAY_AUTHORITY_ABSENT", context["attempt_no"], policy.fingerprint)
        result_json = _provider_result_json(result)
        result_sha = result.canonical_sha256
        decision_value = {
            "disposition": decision.disposition, "reason": decision.reason,
            "attempt": decision.attempt, "policy_fingerprint": decision.policy_fingerprint,
            "delay_seconds": decision.delay_seconds,
            "selected_next_at": decision.selected_next_at.astimezone(UTC).isoformat() if decision.selected_next_at else None,
            "persistable_next_at": decision.persistable_next_at.astimezone(UTC).isoformat() if decision.persistable_next_at else None,
        }
        decision_json = _canonical(decision_value)
        if decision.disposition == "succeeded":
            status, code, next_at = "succeeded", result.code, None
        elif decision.disposition == "terminal_failed":
            status, code, next_at = "failed", decision.reason, None
        elif decision.disposition == "retry":
            status, code = "retry_wait", decision.reason
            next_at = decision.persistable_next_at.timestamp()
        else:
            status, code, next_at = "unknown", decision.reason, None
        receipt = _encode_receipt(_plain(result.receipt)) if result.receipt else None
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM attempts WHERE attempt_id=?", (context["attempt_id"],)).fetchone()
            require(row and row["status"] == "running", "ATTEMPT_NO_LONGER_OWNED")
            db.execute("INSERT INTO provider_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (context["attempt_id"], context["slot_id"], result_json, result_sha,
                        result.provider.value, result.operation_id, result.phase.value,
                        result.submission.value, result.terminal_proof.value, result.status.value,
                        result.failure_kind.value, now, context["prompt_binding_sha256"]))
            retry_after = result.retry_after_at.astimezone(UTC).timestamp() if result.retry_after_at else None
            db.execute("INSERT INTO retry_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (context["attempt_id"], context["slot_id"], decision_json, policy.fingerprint,
                        policy.version, decision.delay_seconds, retry_after, next_at,
                        deadline.timestamp(), now, context["prompt_binding_sha256"]))
            db.execute("UPDATE attempts SET status=?,code=?,receipt=?,ended_at=? WHERE attempt_id=?",
                       (status, code, receipt, now, context["attempt_id"]))
            changed = db.execute("UPDATE slots SET status=?,code=?,operation_id=?,next_attempt_at=?,updated_at=? WHERE slot_id=? AND status='running'",
                                 (status, code, result.operation_id, next_at, now, context["slot_id"])).rowcount
            require(changed == 1, "SLOT_NO_LONGER_OWNED")
            self._update_circuit(
                db, pinned, context.get("_probe_token"),
                context.get("_circuit_generation"),
                context.get("_circuit_admission_state"), result, now)
        return status

    def _finish(self, job, context, result, now):
        if "_provider" in job:
            pinned = context["_typed_config"]
            if not isinstance(result, ProviderResultV1):
                result = ProviderResultV1(
                    pinned["provider"], context["operation_id"], Phase.NOT_STARTED,
                    Submission.NOT_SUBMITTED, TerminalProof.ABSENT, ResultStatus.UNKNOWN,
                    "TYPED_PROVIDER_RESULT_REQUIRED", failure_kind=FailureKind.UNKNOWN)
            elif (result.provider != pinned["provider"]
                  or result.operation_id != context["operation_id"]):
                result = ProviderResultV1(
                    pinned["provider"], context["operation_id"], Phase.NOT_STARTED,
                    Submission.NOT_SUBMITTED, TerminalProof.ABSENT, ResultStatus.UNKNOWN,
                    "PROVIDER_RESULT_BINDING_MISMATCH", failure_kind=FailureKind.UNKNOWN)
            return self._finish_typed(job, context, result, now)
        if isinstance(result, ProviderResultV1):
            result = {"status": "unknown", "code": "UNEXPECTED_TYPED_PROVIDER_RESULT"}
        if not isinstance(result, dict) or result.get("status") not in ("succeeded", "retryable", "failed", "unknown"):
            result = {"status": "unknown", "code": "INVALID_DISPATCH_RESULT"}
        status = result["status"]
        code = result.get("code", "COMPLETED" if status == "succeeded" else "DISPATCH_FAILED")
        if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code):
            code = "INVALID_DISPATCH_CODE"
        receipt = result.get("receipt")
        try:
            encoded = _encode_receipt(receipt) if isinstance(receipt, dict) and receipt else None
        except EngineError:
            status, code, encoded = "unknown", "INVALID_TRANSPORT_RECEIPT", None
        if status == "succeeded" and encoded is None:
            status, code = "unknown", "TRANSPORT_RECEIPT_REQUIRED"
        next_at = None
        if status == "retryable":
            if not job["replay_safe"]:
                status, code = "failed", "NON_REPLAY_SAFE_RETRY_BLOCKED"
            elif context["attempt_no"] >= self.retry["max_attempts"]:
                status, code = "failed", "RETRY_LIMIT_EXHAUSTED"
            else:
                delay = min(self.retry["backoff_seconds"] * 2 ** (context["attempt_no"] - 1), self.retry["max_backoff_seconds"])
                next_at = now + delay
                if next_at > context["expires_at"]:
                    status, code, next_at = "failed", "RETRY_WINDOW_EXPIRED", None
                else:
                    status = "retry_wait"
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM attempts WHERE attempt_id=?", (context["attempt_id"],)).fetchone()
            require(row and row["status"] == "running", "ATTEMPT_NO_LONGER_OWNED")
            db.execute("UPDATE attempts SET status=?,code=?,receipt=?,ended_at=? WHERE attempt_id=?", (status, code, encoded, now, context["attempt_id"]))
            db.execute("UPDATE slots SET status=?,code=?,next_attempt_at=?,updated_at=? WHERE slot_id=? AND status='running'", (status, code, next_at, now, context["slot_id"]))
        return status

    def tick(self, now):
        now = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            for job in self.jobs.values():
                if job["enabled"]:
                    self._allocate(db, job, now)
            db.execute("INSERT OR REPLACE INTO metadata VALUES('heartbeat',?)", (datetime.fromtimestamp(now, UTC).isoformat(),))
        summary = {"dispatched": 0, "succeeded": 0, "retry_wait": 0, "failed": 0, "unknown": 0}
        def dispatch_job(job):
            # Claims happen when a worker actually starts, not when a long queue
            # is submitted. A queued slot may expire before capacity is free.
            claimed_at = max(now, instant(self.clock()).timestamp())
            context = self._claim(job, claimed_at)
            if context is None:
                return None
            try:
                result = self.dispatcher(job, {
                    key: value for key, value in context.items()
                    if key not in ("expires_at", "scheduled_epoch") and not key.startswith("_")
                })
            except Exception:
                if "_provider" in job:
                    result = ProviderResultV1(
                        job["_provider"], context["operation_id"], Phase.NOT_STARTED,
                        Submission.NOT_SUBMITTED, TerminalProof.ABSENT, ResultStatus.UNKNOWN,
                        "DISPATCH_EXCEPTION_OUTCOME_UNKNOWN", failure_kind=FailureKind.UNKNOWN)
                else:
                    result = {"status": "unknown", "code": "DISPATCH_EXCEPTION_OUTCOME_UNKNOWN"}
            ended = max(claimed_at, instant(self.clock()).timestamp())
            return self._finish(job, context, result, ended)

        # The transport adapter must enforce its own subprocess/network timeout.
        # Threads are joined before returning; the engine never detaches work
        # whose outcome could later be falsely treated as safe to retry.
        groups = {}
        for job in self.jobs.values():
            if job["enabled"]:
                key = ("shared", job["_resource_key"]) if "_resource_key" in job else ("job", job["id"])
                groups.setdefault(key, []).append(job)

        def dispatch_group(jobs):
            # Jobs sharing a single-writer credential cache queue here without
            # claiming a slot or consuming an external retry attempt. Other
            # resource groups can still use the remaining worker capacity.
            return [dispatch_job(job) for job in jobs]

        if groups:
            with ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="job-runtime") as pool:
                for statuses in pool.map(dispatch_group, groups.values()):
                    for status in statuses:
                        if status is not None:
                            summary["dispatched"] += 1
                            summary[status] += 1
        return summary

    def recover_running(self, now):
        """Only call after supervisor proves no prior worker can still execute."""
        at = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            running = db.execute(
                "SELECT a.*,s.provider,s.retry_policy_fingerprint FROM attempts a "
                "JOIN slots s ON s.slot_id=a.slot_id WHERE a.status='running'").fetchall()
            count = len(running)
            for attempt in running:
                if attempt["provider"] is None:
                    continue
                operation_id = (f"attempt/{attempt['attempt_id']}/prompt/"
                                f"{attempt['binding_sha256']}")
                result = ProviderResultV1(
                    attempt["provider"], operation_id, Phase.TERMINAL,
                    Submission.POSSIBLY_SUBMITTED, TerminalProof.ABSENT, ResultStatus.UNKNOWN,
                    "PROCESS_EXITED_OUTCOME_UNKNOWN", failure_kind=FailureKind.UNKNOWN)
                result_json = _provider_result_json(result)
                db.execute("INSERT INTO provider_results VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (attempt["attempt_id"], attempt["slot_id"], result_json, result.canonical_sha256,
                            result.provider.value, result.operation_id, result.phase.value,
                            result.submission.value, result.terminal_proof.value, result.status.value,
                            result.failure_kind.value, at, attempt["binding_sha256"]))
                decision_json = _canonical({
                    "disposition": "unknown", "reason": "PROCESS_EXITED_OUTCOME_UNKNOWN",
                    "attempt": attempt["attempt_no"],
                    "policy_fingerprint": attempt["retry_policy_fingerprint"],
                    "delay_seconds": None, "selected_next_at": None, "persistable_next_at": None})
                db.execute("INSERT INTO retry_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (attempt["attempt_id"], attempt["slot_id"], decision_json,
                            attempt["retry_policy_fingerprint"], 2, None, None, None, None, at,
                            attempt["binding_sha256"]))
            db.execute("UPDATE slots SET status='unknown',code='PROCESS_EXITED_OUTCOME_UNKNOWN',updated_at=? WHERE status='running'", (at,))
            db.execute("UPDATE attempts SET status='unknown',code='PROCESS_EXITED_OUTCOME_UNKNOWN',ended_at=? WHERE status='running'", (at,))
        return count

    def record_reconciliation_proof(self, proof, evidence, evidence_ref,
                                    adapter_identity, adapter_version, now, *, adapter=None):
        """Invoke the registered owner and immutably bind its absence proof."""
        require(isinstance(proof, ReconciliationProofV1), "RECONCILIATION_PROOF_REQUIRED")
        require(adapter is not None and self._reconciliation_adapters.get(adapter_identity) is adapter,
                "RECONCILIATION_CAPABILITY_REQUIRED")
        owned_proof = adapter.reconcile(
            attempt_id=proof.attempt_id, operation_id=proof.operation_id,
            slot_operation_scope=proof.slot_operation_scope)
        require(isinstance(owned_proof, ReconciliationProofV1)
                and owned_proof.canonical_sha256 == proof.canonical_sha256,
                "RECONCILIATION_OWNER_PROOF_MISMATCH")
        require(isinstance(evidence_ref, str) and 1 <= len(evidence_ref) <= 512
                and isinstance(adapter_identity, str) and _SCOPE_PART.fullmatch(adapter_identity)
                and isinstance(adapter_version, str) and _SCOPE_PART.fullmatch(adapter_version),
                "RECONCILIATION_IDENTITY_INVALID")
        if isinstance(evidence, bytes):
            evidence_bytes = evidence
        else:
            evidence_bytes = _canonical(evidence).encode("utf-8")
        require(0 < len(evidence_bytes) <= 65536, "RECONCILIATION_EVIDENCE_INVALID")
        evidence_sha = _sha256(evidence_bytes)
        require(proof.evidence_sha256 == evidence_sha, "RECONCILIATION_EVIDENCE_MISMATCH")
        proof_json = _canonical(proof.to_mapping())
        proof_sha = _sha256(proof_json)
        at = instant(now)
        require(proof.recorded_at <= at, "FUTURE_RECONCILIATION_PROOF")
        reconciliation_id = proof_sha
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (proof.attempt_id,)).fetchone()
            require(attempt is not None, "RECONCILIATION_ATTEMPT_REQUIRED")
            slot = db.execute("SELECT * FROM slots WHERE slot_id=?", (attempt["slot_id"],)).fetchone()
            result_row = db.execute("SELECT * FROM provider_results WHERE attempt_id=?", (proof.attempt_id,)).fetchone()
            require(slot is not None and result_row is not None and slot["replay_contract"],
                    "RECONCILIATION_TYPED_ATTEMPT_REQUIRED")
            contract = _contract_from_json(slot["replay_contract"])
            result = _result_from_json(result_row["canonical_json"])
            require(contract.effect is ReplayEffect.RECONCILE_BEFORE_REPLAY
                    and contract.reconciliation_adapter == adapter_identity,
                    "RECONCILIATION_ADAPTER_MISMATCH")
            require(slot["status"] == "unknown" and attempt["status"] == "unknown",
                    "UNKNOWN_ATTEMPT_REQUIRED")
            require(_sha256(result_row["canonical_json"]) == result_row["canonical_sha256"]
                    == result.canonical_sha256
                    and _sha256(slot["replay_contract"]) == slot["replay_contract_sha256"],
                    "RECONCILIATION_STORED_DIGEST_MISMATCH")
            require(proof.operation_id == result_row["operation_id"]
                    and proof.slot_operation_scope == contract.slot_operation_scope
                    and proof.provider_result_sha256 == result_row["canonical_sha256"],
                    "RECONCILIATION_BINDING_MISMATCH")
            require(validate_replay(
                contract, result, reconciliation_proof=proof,
                expected_attempt_id=proof.attempt_id,
                expected_provider_result_sha256=result_row["canonical_sha256"],
                expected_evidence_sha256=evidence_sha,
                expected_proof_sha256=proof_sha), "REPLAY_NOT_AUTHORIZED")
            require(proof.recorded_at.timestamp() >= attempt["started_at"],
                    "RECONCILIATION_PROOF_PREDATES_ATTEMPT")
            existing = db.execute("SELECT * FROM reconciliation_records WHERE attempt_id=?", (proof.attempt_id,)).fetchone()
            if existing:
                require(existing["proof_sha256"] == proof_sha and existing["evidence_sha256"] == evidence_sha,
                        "RECONCILIATION_CONFLICT")
                return {"reconciliation_id": existing["reconciliation_id"], "created": False}
            db.execute("INSERT INTO reconciliation_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (reconciliation_id, proof.attempt_id, slot["slot_id"], proof.operation_id,
                        proof.slot_operation_scope, proof_json, proof_sha, evidence_bytes,
                        evidence_ref, evidence_sha, adapter_identity, adapter_version, at.timestamp(),
                        attempt["binding_sha256"]))
        return {"reconciliation_id": reconciliation_id, "created": True}

    # Short alias retained for callers that name the record by artifact type.
    record_reconciliation = record_reconciliation_proof

    def authorize_reconciled_retry(self, attempt_id, now):
        """Consume one DB-owned proof and move its exact unknown slot to retry_wait."""
        require(isinstance(attempt_id, str) and attempt_id, "RECONCILIATION_ATTEMPT_REQUIRED")
        at = instant(now)
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(attempt and attempt["status"] == "unknown", "UNKNOWN_ATTEMPT_REQUIRED")
            slot = db.execute("SELECT * FROM slots WHERE slot_id=?", (attempt["slot_id"],)).fetchone()
            require(slot and slot["status"] == "unknown" and slot["replay_contract"]
                    and slot["retry_policy"], "UNKNOWN_SLOT_REQUIRED")
            latest = db.execute("SELECT attempt_id FROM attempts WHERE slot_id=? ORDER BY attempt_no DESC LIMIT 1",
                                (slot["slot_id"],)).fetchone()
            require(latest and latest["attempt_id"] == attempt_id, "RECONCILIATION_REPLACED_ATTEMPT")
            record = db.execute("SELECT * FROM reconciliation_records WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(record is not None, "RECONCILIATION_PROOF_REQUIRED")
            require(db.execute("SELECT 1 FROM reconciliation_consumptions WHERE reconciliation_id=?",
                               (record["reconciliation_id"],)).fetchone() is None,
                    "RECONCILIATION_ALREADY_CONSUMED")
            result_row = db.execute("SELECT * FROM provider_results WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(result_row is not None, "PROVIDER_RESULT_REQUIRED")
            result = _result_from_json(result_row["canonical_json"])
            proof = _proof_from_json(record["proof_json"])
            contract = _contract_from_json(slot["replay_contract"])
            require(_sha256(result_row["canonical_json"]) == result_row["canonical_sha256"]
                    == result.canonical_sha256, "PROVIDER_RESULT_DIGEST_MISMATCH")
            require(_sha256(slot["replay_contract"]) == slot["replay_contract_sha256"],
                    "REPLAY_CONTRACT_DIGEST_MISMATCH")
            require(_sha256(record["proof_json"]) == record["proof_sha256"] == proof.canonical_sha256,
                    "RECONCILIATION_PROOF_DIGEST_MISMATCH")
            require(_sha256(bytes(record["evidence_bytes"])) == record["evidence_sha256"]
                    == proof.evidence_sha256, "RECONCILIATION_EVIDENCE_MISMATCH")
            require(record["attempt_id"] == attempt_id and record["slot_id"] == slot["slot_id"]
                    and record["operation_id"] == result.operation_id
                    and record["slot_operation_scope"] == contract.slot_operation_scope,
                    "RECONCILIATION_BINDING_MISMATCH")
            require(proof.recorded_at.timestamp() >= attempt["started_at"]
                    and proof.recorded_at <= at, "RECONCILIATION_TIME_INVALID")
            require(validate_replay(
                contract, result, reconciliation_proof=proof,
                expected_attempt_id=attempt_id,
                expected_provider_result_sha256=result_row["canonical_sha256"],
                expected_evidence_sha256=record["evidence_sha256"],
                expected_proof_sha256=record["proof_sha256"]), "REPLAY_NOT_AUTHORIZED")
            policy = validate_retry_policy(json.loads(slot["retry_policy"]))
            candidate = ProviderResultV1(
                result.provider, result.operation_id, Phase.CONNECTING, Submission.NOT_SUBMITTED,
                TerminalProof.ABSENT, ResultStatus.RETRYABLE, "RECONCILIATION_ABSENCE_VERIFIED",
                failure_kind=FailureKind.CONNECTION)
            deadline = datetime.fromtimestamp(slot["retry_deadline"], UTC) if slot["retry_deadline"] is not None else None
            decision = decide_retry(candidate, policy, slot_id=slot["slot_id"],
                                    attempt=attempt["attempt_no"], now=at, deadline=deadline)
            require(decision.disposition == "retry", "RECONCILED_RETRY_NOT_SCHEDULABLE")
            decision_id = f"{attempt_id}:reconciliation"
            decision_json = _canonical({
                "disposition": decision.disposition, "reason": "RECONCILIATION_ABSENT_RETRY",
                "attempt": decision.attempt, "policy_fingerprint": decision.policy_fingerprint,
                "delay_seconds": decision.delay_seconds,
                "selected_next_at": decision.selected_next_at.isoformat(),
                "persistable_next_at": decision.persistable_next_at.isoformat(),
            })
            next_at = decision.persistable_next_at.timestamp()
            db.execute("INSERT INTO retry_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (decision_id, slot["slot_id"], decision_json, policy.fingerprint, policy.version,
                        decision.delay_seconds, None, next_at,
                        deadline.timestamp() if deadline else None, at.timestamp(),
                        attempt["binding_sha256"]))
            db.execute("INSERT INTO reconciliation_consumptions VALUES(?,?,?,?,?)",
                       (record["reconciliation_id"], attempt_id, decision_id, at.timestamp(),
                        attempt["binding_sha256"]))
            changed = db.execute("UPDATE slots SET status='retry_wait',code='RECONCILIATION_ABSENT_RETRY',next_attempt_at=?,updated_at=? WHERE slot_id=? AND status='unknown'",
                                 (next_at, at.timestamp(), slot["slot_id"])).rowcount
            require(changed == 1, "UNKNOWN_SLOT_REQUIRED")
        return {"slot_id": slot["slot_id"], "status": "retry_wait",
                "next_attempt_at": decision.persistable_next_at.isoformat(),
                "retry_decision_id": decision_id}

    reconcile_unknown_for_retry = authorize_reconciled_retry

    def resolve_unknown(self, slot_id, outcome, receipt, now):
        """Manual evidence handoff; never a timed automatic reset or resend."""
        require(outcome in ("failed", "succeeded") and isinstance(receipt, dict) and receipt, "RECONCILIATION_EVIDENCE_REQUIRED")
        encoded = _encode_receipt(receipt)
        at = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM slots WHERE slot_id=?", (slot_id,)).fetchone()
            require(row and row["status"] == "unknown", "UNKNOWN_SLOT_REQUIRED")
            db.execute("UPDATE slots SET status=?,code='OPERATOR_RECONCILED',updated_at=? WHERE slot_id=?", (outcome, at, slot_id))
            db.execute("UPDATE attempts SET status=?,code='OPERATOR_RECONCILED',receipt=?,ended_at=? WHERE slot_id=? AND status='unknown'", (outcome, encoded, at, slot_id))

    def reconcile_failed_delivery(self, slot_id, receipt, now):
        """Record independent delivery evidence for a final-format false negative.

        The caller must actually verify the exact business message and canonical
        payload through authenticated transport. This method performs no remote
        lookup, dispatch, retry or reset, and never rewrites the failed attempt.
        """
        allowed = {'BUSINESS_FINAL_VALUE_INVALID', 'BUSINESS_FINAL_JSON_REQUIRED', 'BUSINESS_FINAL_FIELDS_REJECTED'}
        require(isinstance(receipt, dict) and receipt.get('evidence_type') == 'independent_business_delivery_verification',
                'INDEPENDENT_DELIVERY_EVIDENCE_REQUIRED')
        message, payload = receipt.get('message_id'), receipt.get('payload_digest')
        require(isinstance(message, str) and re.fullmatch(r'[a-fA-F0-9]{8,64}', message)
                and isinstance(payload, str) and re.fullmatch(r'[a-fA-F0-9]{64}', payload), 'DELIVERY_IDENTIFIERS_INVALID')
        verified = instant(receipt.get('verified_at'));at = instant(now)
        require(verified <= at, 'FUTURE_DELIVERY_VERIFICATION')
        encoded = _encode_receipt(receipt)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM delivery_reconciliations WHERE slot_id=?', (slot_id,)).fetchone()
            if old:
                require(old['message_id'] == message.lower() and old['payload_digest'] == payload.lower(),
                        'DELIVERY_RECONCILIATION_CONFLICT')
                created = False
            else:
                slot = db.execute('SELECT * FROM slots WHERE slot_id=?', (slot_id,)).fetchone()
                require(slot and slot['status'] == 'failed' and slot['code'] in allowed, 'FAILED_FORMAT_SLOT_REQUIRED')
                attempt = db.execute('SELECT * FROM attempts WHERE slot_id=? ORDER BY attempt_no DESC LIMIT 1', (slot_id,)).fetchone()
                require(attempt and attempt['status'] == 'failed' and attempt['code'] == slot['code'], 'FAILED_FORMAT_ATTEMPT_REQUIRED')
                prior = json.loads(attempt['receipt'] or 'null')
                require(isinstance(prior, dict) and prior.get('turn_completed') is True
                        and type(prior.get('exit_code')) is int and prior['exit_code'] == 0,
                        'COMPLETED_MODEL_TRANSPORT_REQUIRED')
                require(verified.timestamp() >= attempt['started_at'], 'VERIFICATION_PREDATES_ATTEMPT')
                db.execute('INSERT INTO delivery_reconciliations VALUES(?,?,?,?,?,?,?,?)',
                           (slot_id, attempt['attempt_id'], message.lower(), payload.lower(),
                            verified.isoformat(), at.timestamp(), encoded,
                            attempt['binding_sha256']))
                db.execute("UPDATE slots SET status='succeeded',code='OPERATOR_VERIFIED_DELIVERY',next_attempt_at=NULL,updated_at=? WHERE slot_id=?",
                           (at.timestamp(), slot_id))
                created = True
        return {'slot_id': slot_id, 'status': 'succeeded', 'code': 'OPERATOR_VERIFIED_DELIVERY',
                'message_id': message.lower(), 'payload_digest': payload.lower(), 'reconciliation_created': created}

    def begin_provider_output_custody(self, attempt_id, now):
        """Start metadata-only output custody for one exact bound attempt."""
        require(isinstance(attempt_id, str) and attempt_id, "OUTPUT_CUSTODY_ATTEMPT_REQUIRED")
        at = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM attempts WHERE attempt_id=?", (attempt_id,)).fetchone()
            require(attempt is not None and attempt["status"] == "running",
                    "OUTPUT_CUSTODY_RUNNING_ATTEMPT_REQUIRED")
            self._mark_schema9_evidence(db, at)
            existing = db.execute("SELECT * FROM provider_output_custody WHERE attempt_id=?",
                                  (attempt_id,)).fetchone()
            if existing is None:
                db.execute("""INSERT INTO provider_output_custody VALUES(
                    ?,?,?,'pending',0,0,?,NULL,?,'OUTPUT_PENDING')""",
                           (attempt_id, attempt["slot_id"], attempt["binding_sha256"], at, at))
                created = True
            else:
                require(existing["state"] == "pending"
                        and existing["prompt_binding_sha256"] == attempt["binding_sha256"],
                        "OUTPUT_CUSTODY_CONFLICT")
                created = False
        return {"attempt_id": attempt_id, "state": "pending", "created": created}

    def finish_provider_output_custody(self, attempt_id, state, output_count,
                                       output_bytes, code, now):
        """Seal output metadata; no provider bytes are accepted or retained."""
        require(state in {"complete", "failed", "unknown"}, "OUTPUT_CUSTODY_STATE_INVALID")
        require(_int(output_count, 0, 1_000_000) and _int(output_bytes, 0, 1 << 40),
                "OUTPUT_CUSTODY_COUNTS_INVALID")
        require(isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", code),
                "OUTPUT_CUSTODY_CODE_INVALID")
        at = instant(now).timestamp()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM provider_output_custody WHERE attempt_id=?",
                             (attempt_id,)).fetchone()
            require(row is not None and row["state"] == "pending",
                    "OUTPUT_CUSTODY_PENDING_REQUIRED")
            changed = db.execute("""UPDATE provider_output_custody SET state=?,output_count=?,
                output_bytes=?,completed_at=?,updated_at=?,code=?
                WHERE attempt_id=? AND state='pending'""",
                (state, output_count, output_bytes, at, at, code, attempt_id)).rowcount
            require(changed == 1, "OUTPUT_CUSTODY_PENDING_REQUIRED")
        return {"attempt_id": attempt_id, "state": state, "output_count": output_count,
                "output_bytes": output_bytes, "code": code}

    def provider_output_custody(self, attempt_id):
        """Return content-free output custody metadata for service/model integration."""
        with self._db() as db:
            row = db.execute("""SELECT attempt_id,slot_id,state,output_count,output_bytes,
                started_at,completed_at,updated_at,code FROM provider_output_custody
                WHERE attempt_id=?""", (attempt_id,)).fetchone()
            return dict(row) if row else None

    def status(self):
        """Content-free summary; raw receipts and job prompts stay private."""
        with self._db() as db:
            heartbeat = db.execute("SELECT value FROM metadata WHERE key='heartbeat'").fetchone()
            counts = {row["status"]: row["n"] for row in db.execute("SELECT status,count(*) n FROM slots GROUP BY status")}
            jobs = []
            for job_id, job in self.jobs.items():
                latest = db.execute("SELECT slot_id,status,code,attempts,scheduled_at,updated_at FROM slots WHERE job_id=? ORDER BY scheduled_at DESC LIMIT 1", (job_id,)).fetchone()
                jobs.append({"id": job_id, "enabled": job["enabled"], "latest": dict(latest) if latest else None})
            return {"heartbeat": heartbeat[0] if heartbeat else None, "counts": counts, "jobs": jobs}
