"""Disabled provider-free Claude integration v8 with marker-bound recovery."""
from __future__ import annotations
import copy
import json
import os
import secrets
import stat
import tempfile
from pathlib import Path
from typing import Optional

from shared.job_runtime.candidates.r6_one_off_evidence_v1 import (
    execute_provider_free, materialize_provider_free_case,
)
from .authority import ValidatedAuthority, load_pinned
from .contracts import (
    ContractError, PROVIDER, PUBLICATION_ORDERING, blank_seal, canonical_bytes,
    sha256_bytes, validate_seal,
)
from .process import _PinnedProviderEffect
from .state import (
    STATE_PROTOCOL, AuthorityRecord, NoTerminalClaimDurabilityError,
    PreviousOutcomeUnknownError, _commit as commit_state, _entries,
    _initialize as initialize_state, _open_fixed_root, _poison as poison_state,
    _read as read_state,
)

FENCE_PENDING_NAME = "unknown-fence-v8.pending.json"
FENCE_NAME = "unknown-fence-v8.commit.json"
PUBLIC_PENDING_NAME = "post-run-seal-v8.pending.json"
PUBLIC_NAME = "post-run-seal-v8.commit.json"
LEGACY_FENCE_NAME = "unknown-fence-v4.json"
LEGACY_PUBLIC_NAME = "post-run-seal-v4.json"
_ORDERING = PUBLICATION_ORDERING


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _terminal(raw: bytes) -> dict:
    try:
        lines = [json.loads(line) for line in raw.decode("utf-8", "strict").splitlines()
                 if line.strip()]
    except (UnicodeError, ValueError, TypeError):
        return {"recognized": False, "exactly_one": False, "state": "truncated",
                "parser": "claude-stream-json-v1"}
    items = [item for item in lines
             if type(item) is dict and item.get("type") == "result"]
    expected = {"type", "subtype", "is_error", "model", "result"}
    ok = (len(items) == 1 and set(items[0]) == expected and
          items[0]["subtype"] == "success" and items[0]["is_error"] is False and
          items[0]["model"] == "claude-opus-5-5")
    return {"recognized": ok, "exactly_one": len(items) == 1,
            "state": "exact" if ok else "truncated",
            "parser": "claude-stream-json-v1"}


def _write_all(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("WRITE_ZERO")
        offset += written


def _read_held(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ContractError("PUBLICATION_NOT_REGULAR")
        chunks = []
        while True:
            part = os.read(fd, 65536)
            if not part:
                break
            chunks.append(part)
        os.fsync(fd)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _quarantine_write(fd: int, raw: bytes) -> None:
    _write_all(fd, raw)


def _quarantine_fsync(fd: int) -> None:
    os.fsync(fd)


def _write_quarantine_notice(path: Path) -> Path:
    """Best-effort poison notice; terminal authority never depends on this file."""
    notice = path.with_name(".%s.poison.%s" % (path.name, secrets.token_hex(12)))
    fd = os.open(notice, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _quarantine_write(fd, b'{"authority":"generation-v8","state":"POISONED"}')
        _quarantine_fsync(fd)
    finally:
        os.close(fd)
    _fsync_directory(path.parent)
    return notice


def _revoke_or_quarantine(path: Path) -> None:
    """Attempt every cleanup layer; authority correctness never depends on success."""
    if not _lexists(path):
        return
    errors = []
    try:
        path.unlink()
    except BaseException as exc:
        errors.append(exc)
        quarantine = path.with_name(".%s.quarantine.%s" % (path.name, secrets.token_hex(12)))
        try:
            os.rename(path, quarantine)
        except BaseException as rename_exc:
            errors.append(rename_exc)
            try:
                _write_quarantine_notice(path)
            except BaseException as notice_exc:
                errors.append(notice_exc)
    for _ in range(2):
        try:
            _fsync_directory(path.parent)
            break
        except BaseException as sync_exc:
            errors.append(sync_exc)
    if _lexists(path):
        errors.append(ContractError("PROJECTION_REVOKE_VISIBLE"))
    if errors:
        raise ContractError("PROJECTION_REVOKE_COMPOUND_FAILED") from errors[-1]

def _publish_verified(path: Path, raw: bytes) -> bytes:
    """No-replace publish; every post-link failure revokes the visible name."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if _lexists(path):
        raise ContractError("PUBLICATION_NO_OVERWRITE")
    fd, stage_name = tempfile.mkstemp(
        prefix=".%s.stage." % path.name, dir=os.fspath(path.parent))
    stage = Path(stage_name)
    linked = False
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, raw)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.link(stage, path, follow_symlinks=False)
        linked = True
        stage.unlink()
        _fsync_directory(path.parent)
        readback = _read_held(path)
        if (len(readback) != len(raw) or readback != raw or
                sha256_bytes(readback) != sha256_bytes(raw)):
            raise ContractError("PUBLICATION_READBACK_MISMATCH")
        _fsync_directory(path.parent)
        return readback
    except BaseException as exc:
        if linked and _lexists(path):
            try:
                _revoke_or_quarantine(path)
            except BaseException as revoke_exc:
                raise ContractError("PUBLICATION_REVOKE_FAILED") from revoke_exc
        raise exc
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            stage.unlink()
        except FileNotFoundError:
            pass


def _publication_basis(seal: dict) -> dict:
    value = copy.deepcopy(seal)
    value["publication"] = {
        "sanitized": True, "atomic": True, "file_fsynced": True,
        "directory_fsynced": True, "final_reopened_nofollow": True,
        "readback_verified": True, "ordering": _ORDERING, "public_sha256": "0" * 64,
    }
    return value


def _published_seal(seal: dict) -> dict:
    value = _publication_basis(seal)
    value["publication"]["public_sha256"] = sha256_bytes(
        canonical_bytes(_publication_basis(value)))
    validate_seal(value)
    return value


def _pending_wrapper(seal: dict, kind: str) -> dict:
    return {"version": 8, "state": "PENDING_NONAUTHORITATIVE",
        "authoritative": False, "kind": kind,
        "candidate_seal": seal,
        "candidate_seal_sha256": sha256_bytes(canonical_bytes(seal))}


def _marker_wrapper(seal: dict, kind: str, pending_raw: bytes) -> dict:
    return {"version": 8, "state": "COMMITTED_PROJECTION",
        "authoritative": False, "kind": kind,
        "pending_sha256": sha256_bytes(pending_raw), "seal": seal,
        "seal_sha256": sha256_bytes(canonical_bytes(seal))}


def _decode_exact(raw: bytes, code: str) -> dict:
    try:
        value = json.loads(raw.decode("ascii", "strict"))
    except (UnicodeError, ValueError, TypeError):
        raise ContractError(code + "_JSON") from None
    if type(value) is not dict or canonical_bytes(value) != raw:
        raise ContractError(code + "_CANONICAL")
    return value


def _read_commit(pending_path: Path, marker_path: Path, kind: str) -> dict:
    marker_raw = _read_held(marker_path)
    marker = _decode_exact(marker_raw, "COMMIT_MARKER")
    if (set(marker) != {"version", "state", "authoritative", "kind",
            "pending_sha256", "seal", "seal_sha256"} or
            marker["version"] != 8 or marker["state"] != "COMMITTED_PROJECTION" or
            marker["authoritative"] is not False or marker["kind"] != kind):
        raise ContractError("COMMIT_MARKER_SCHEMA")
    pending_raw = _read_held(pending_path)
    pending = _decode_exact(pending_raw, "PENDING_DATA")
    if (set(pending) != {"version", "state", "authoritative", "kind",
            "candidate_seal", "candidate_seal_sha256"} or
            pending["version"] != 8 or pending["state"] != "PENDING_NONAUTHORITATIVE" or
            pending["authoritative"] is not False or pending["kind"] != kind):
        raise ContractError("PENDING_DATA_SCHEMA")
    if (marker["pending_sha256"] != sha256_bytes(pending_raw) or
            marker["seal_sha256"] != sha256_bytes(canonical_bytes(marker["seal"])) or
            pending["candidate_seal_sha256"] !=
                sha256_bytes(canonical_bytes(pending["candidate_seal"])) or
            pending["candidate_seal"] != marker["seal"]):
        raise ContractError("COMMIT_PAIR_HASH")
    seal = marker["seal"]
    validate_seal(seal)
    if kind == "PASS" and seal["status"] != "PASS":
        raise ContractError("COMMIT_PASS_STATE")
    if kind == "UNKNOWN_FENCE" and not (seal["status"] == "UNKNOWN" and
            seal["unknown_fence"]["durability"] == "DURABLE"):
        raise ContractError("COMMIT_FENCE_STATE")
    return seal


def _publish_committed(pending_path: Path, marker_path: Path,
                       seed: dict, kind: str) -> dict:
    seal = _published_seal(seed)
    pending_raw = canonical_bytes(_pending_wrapper(seal, kind))
    _publish_verified(pending_path, pending_raw)
    marker_raw = canonical_bytes(_marker_wrapper(seal, kind, pending_raw))
    marker_complete = False
    try:
        _publish_verified(marker_path, marker_raw)
        marker_complete = True
        readback = _read_commit(pending_path, marker_path, kind)
        if readback != seal:
            raise ContractError("COMMIT_PAIR_READBACK")
        return readback
    except BaseException:
        if (marker_complete or _lexists(marker_path)) and _lexists(marker_path):
            _revoke_or_quarantine(marker_path)
        raise


def _nondurable_unknown(code: str, seed: Optional[dict] = None) -> dict:
    """Only valid when no generation authority was durably initialized."""
    seal = copy.deepcopy(seed if seed is not None else blank_seal())
    seal["status"] = "UNKNOWN"
    seal["code"] = code if code.endswith("_NON_DURABLE") else code + "_NON_DURABLE"
    seal["unknown_fence"] = {"durable": False, "durability": "NON_DURABLE",
        "retry": False, "replay": False, "status_calls": 0}
    seal["publication"] = {"sanitized": True, "atomic": False,
        "file_fsynced": False, "directory_fsynced": False,
        "final_reopened_nofollow": False, "readback_verified": False,
        "ordering": "NONE", "public_sha256": "0" * 64}
    seal["state_authority"] = {"protocol": STATE_PROTOCOL,
        "generation_sha256": "0" * 64, "state": "ABSENT",
        "precedence": "AUTHORITY_BEFORE_PROJECTIONS", "source_pinned": True}
    validate_seal(seal)
    return seal


def _ledger_absent(exc: BaseException) -> bool:
    return isinstance(exc, ContractError) and str(exc) == "STATE_LEDGER_ABSENT"


def _recover(root) -> Optional[dict]:
    """Consult the held fixed-root ledger before projections or freshness."""
    try:
        record = read_state(root.fd)
    except BaseException as exc:
        if _ledger_absent(exc):
            legacy_or_projection = any(_lexists(path) for path in (
                root.path / FENCE_PENDING_NAME, root.path / FENCE_NAME,
                root.path / "public" / PUBLIC_PENDING_NAME,
                root.path / "public" / PUBLIC_NAME,
                root.path / LEGACY_FENCE_NAME,
                root.path / "public" / LEGACY_PUBLIC_NAME))
            return (_nondurable_unknown("PROJECTION_WITHOUT_STATE_AUTHORITY")
                    if legacy_or_projection else None)
        if isinstance(exc, (PreviousOutcomeUnknownError,
                            NoTerminalClaimDurabilityError)):
            raise
        raise PreviousOutcomeUnknownError("STATE_AUTHORITY_INVALID") from exc
    if record.state in ("UNKNOWN", "POISONED"):
        return record.terminal
    try:
        projection = _read_commit(root.path / "public" / PUBLIC_PENDING_NAME,
                                  root.path / "public" / PUBLIC_NAME, "PASS")
        if projection != record.terminal:
            raise ContractError("PASS_PROJECTION_AUTHORITY_MISMATCH")
        return record.terminal
    except BaseException:
        poisoned = poison_state(root.fd, record)
        if poisoned.state != "POISONED" or poisoned.terminal != record.poison:
            raise NoTerminalClaimDurabilityError("POISON_NOT_EXACTLY_PROVED")
        return poisoned.terminal

def _engine(captured: dict, binding: dict) -> dict:
    request = captured.get("request", {})
    value = {"provider": binding.get("provider"),
        "job_id": binding.get("logical_job_id", request.get("logical_job_id")),
        "slot_id": binding.get("slot_id"),
        "attempt_id": binding.get("attempt_id", request.get("attempt_id")),
        "operation_id": binding.get("operation_id", request.get("operation_id")),
        "prompt_binding_sha256": binding.get(
            "prompt_binding_sha256", request.get("prompt_binding_sha256")),
        "readback_digest": None, "status": binding.get("engine_status", "unknown")}
    value["readback_digest"] = sha256_bytes(canonical_bytes(value))
    return value


def _seal(authority: ValidatedAuthority, captured: dict, binding: dict,
          status: str, code: str) -> dict:
    seal = blank_seal(code)
    seal.update({"status": status, "cell_id": authority.grant["cell_id"],
        "engine": _engine(captured, binding),
        "authority": {"grant_sha256": authority.grant_sha256,
            "grant_review_sha256": authority.grant_review_sha256,
            "registry_sha256": authority.registry_sha256,
            "registry_review_sha256": authority.registry_review_sha256,
            "scope_sha256": authority.scope_sha256, "clock_id": authority.clock_id,
            "validated_before_effect": True, "post_receipt_required_pregrant": False}})
    for key in ("process", "ferry", "custody", "cleanup", "terminal"):
        if key in captured:
            seal[key] = captured[key]
    return seal



def _bind_state(seal: dict, generation_sha256: str, state: str) -> dict:
    value = copy.deepcopy(seal)
    value["state_authority"] = {"protocol": STATE_PROTOCOL,
        "generation_sha256": generation_sha256, "state": state,
        "precedence": "AUTHORITY_BEFORE_PROJECTIONS", "source_pinned": True}
    return value


def _unknown_seed(authority: ValidatedAuthority, captured: dict, binding: dict,
                  generation_sha256: str, code: str, state: str = "UNKNOWN") -> dict:
    value = _bind_state(_seal(authority, captured, binding, "UNKNOWN", code),
                        generation_sha256, state)
    value["unknown_fence"] = {"durable": True, "durability": "DURABLE",
        "retry": False, "replay": False, "status_calls": 0}
    validate_seal(value)
    return value


def _commit_or_observe(root, record: AuthorityRecord,
                       state: str, terminal: dict) -> dict:
    return commit_state(root.fd, record.generation_sha256, state, terminal).terminal


def _finalize_unknown(root, record: AuthorityRecord) -> dict:
    """Return only the exact pre-effect UNKNOWN baseline stored and reread."""
    try:
        _publish_committed(root.path / FENCE_PENDING_NAME,
                           root.path / FENCE_NAME,
                           record.terminal, "UNKNOWN_FENCE")
    except BaseException:
        pass
    proved = read_state(root.fd)
    if proved.record_sha256 != record.record_sha256 or proved.terminal != record.terminal:
        raise NoTerminalClaimDurabilityError("UNKNOWN_TERMINAL_NOT_EXACTLY_PROVED")
    return proved.terminal


def _finalize_pass(root, record: AuthorityRecord, seed: dict) -> dict:
    value = _bind_state(seed, record.generation_sha256, "PASS")
    projected = _publish_committed(root.path / "public" / PUBLIC_PENDING_NAME,
                                   root.path / "public" / PUBLIC_NAME,
                                   value, "PASS")
    return _commit_or_observe(root, record, "PASS", projected)

def _publish_pass(pending: Path, marker: Path, seed: dict) -> dict:
    return _publish_committed(pending, marker, seed, "PASS")


def run() -> dict:
    """Run the one fixed, source-pinned provider-free boundary at most once."""
    try:
        root = _open_fixed_root(create=False)
    except BaseException as exc:
        if not (isinstance(exc, ContractError) and
                str(exc) == "STATE_ROOT_COMPONENT_ABSENT"):
            raise
        root = _open_fixed_root(create=True)
    with root:
        recovered = _recover(root)
        if recovered is not None:
            return recovered
        if _entries(root.fd):
            return _nondurable_unknown("WORKSPACE_MUST_BE_FRESH")
        try:
            authority = load_pinned()
        except BaseException as exc:
            stopped = blank_seal(str(exc) if isinstance(exc, ContractError)
                                 else "PINNED_AUTHORITY_INVALID")
            validate_seal(stopped)
            return stopped

        generation_sha256 = sha256_bytes(secrets.token_bytes(32))
        baseline = _unknown_seed(authority, {}, {}, generation_sha256,
                                 "GENERATION_PRECOMMIT_UNKNOWN")
        poison = _unknown_seed(authority, {}, {}, generation_sha256,
                               "GENERATION_POISONED", "POISONED")
        try:
            record = initialize_state(root.fd, generation_sha256, baseline, poison)
        except (NoTerminalClaimDurabilityError, PreviousOutcomeUnknownError):
            raise
        except BaseException as exc:
            raise NoTerminalClaimDurabilityError(
                "STATE_AUTHORITY_INITIALIZATION_FAILED") from exc

        try:
            prepared = materialize_provider_free_case(root.path / "engine", "nominal")
        except BaseException:
            return _finalize_unknown(root, record)
        captured = {}
        shared = None
        execution_error = None
        effect = _PinnedProviderEffect()

        def transport(request):
            captured["request"] = dict(request)
            fingerprint = sha256_bytes(canonical_bytes(request))
            observed = effect.execute(root.path, authority.binary_path,
                authority.grant["binary"], fingerprint,
                authority.grant["timeout_seconds"])
            captured.update(observed)
            captured["terminal"] = _terminal(observed["stdout"])
            process = observed["process"]
            ferry = observed["ferry"]
            cleanup = observed["cleanup"]
            good = (observed["boundary_error"] is None and process["starts"] == 1 and
                process["exit_code"] == 0 and process["timed_out"] is False and
                process["provider"] == PROVIDER and captured["terminal"]["recognized"] and
                all(cleanup[key] is True for key in ("process_group_reaped",
                    "verified_copy_removed", "listener_closed", "descriptors_closed")) and
                cleanup["exception_count"] == 0 and process["pid_gone"] and
                process["descendants_reaped"] and ferry["provider"] == PROVIDER and
                ferry["admissions"] == ferry["upstream_attempts"] == 1 and
                ferry["second_rejections"] == 0)
            return {"terminal": "exact" if good else "truncated",
                    "cleanup": "complete" if good else "fault",
                    "raw": b'{"type":"boundary.completed"}' if good else
                    b'{"type":"boundary.partial"}'}

        try:
            shared = execute_provider_free(prepared, transport, provider=PROVIDER)
        except BaseException as exc:
            execution_error = exc
        binding = shared.binding if shared and shared.binding else {}
        if execution_error is not None:
            return _finalize_unknown(root, record)
        request = captured.get("request", {})
        readback_match = (binding.get("provider") == PROVIDER and
            request.get("prompt_binding_sha256") == binding.get("prompt_binding_sha256"))
        process = captured.get("process", {})
        ferry = captured.get("ferry", {})
        cleanup = captured.get("cleanup", {})
        exact = bool(shared and shared.evidence["decision"] == "PASS" and readback_match and
            process.get("exit_code") == 0 and captured.get("boundary_error") is None and
            captured.get("terminal", {}).get("recognized") and
            all(cleanup.get(key) is True for key in ("process_group_reaped",
                "verified_copy_removed", "listener_closed", "descriptors_closed")) and
            cleanup.get("exception_count") == 0 and
            ferry.get("admissions") == ferry.get("upstream_attempts") == 1 and
            ferry.get("second_rejections") == 0)
        if not exact:
            return _finalize_unknown(root, record)
        pass_seed = _seal(authority, captured, binding, "PASS",
                          "EXACT_CLAUDE_HOST_TERMINAL_FERRY_ENGINE_EXIT_VERIFIED")
        try:
            return _finalize_pass(root, record, pass_seed)
        except (NoTerminalClaimDurabilityError, PreviousOutcomeUnknownError):
            raise
        except BaseException:
            return _finalize_unknown(root, record)

def _p0_output(seal: dict) -> dict:
    validate_seal(seal)
    state_authority = seal["state_authority"]["state"]
    durability = seal["unknown_fence"]["durability"]
    engine_provider = seal["engine"]["provider"]
    if seal["status"] == "UNKNOWN" and durability == "DURABLE":
        engine_provider = seal["process"]["provider"]
    return {"version": 8, "schema": "r6-one-off-claude-live-integration-v8",
        "cell_id": seal["cell_id"], "status": seal["status"],
        "state_authority": state_authority, "durability": durability,
        "engine_provider": engine_provider,
        "engine_readback_digest": seal["engine"]["readback_digest"],
        "post_run_seal_sha256": sha256_bytes(canonical_bytes(seal)),
        "raw_included": False, "path_included": False,
        "secret_included": False, "replay_allowed": False}
