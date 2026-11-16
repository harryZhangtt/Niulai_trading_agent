"""Provider-free publication of one finalized live acquisition acceptance.

This boundary only reopens immutable artifacts produced by ``acquisition_live_session``.
It never invokes a provider and publishes only the bounded driver projection accepted by
``investment.research.datasource``.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from investment.research import acquisition_projection, datasource
from investment.research.acquisition_trace import check_acquisition_trace
from shared.research_sources.artifacts import (
    INVESTMENT_STATE,
    ROOT,
    SourceError,
    encoded,
    private_path,
    read,
    require,
    save,
)


VERSION = "acquisition-acceptance-1"
MAX_REGISTRY_BYTES = 256 * 1024
EXPECTED_DISPATCHES = 3
_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
_SECRET_TEXT = re.compile(
    r"(?i)(?:\bbearer\s+\S+|"
    r"\b(?:sk|ghp|gho|ghu|ghs|ghr)[-_][A-Za-z0-9_-]{8,}|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}|"
    r"\b(?:api[_ -]?key|access[_ -]?token|refresh[_ -]?token|password|"
    r"client[_ -]?secret|credential|private[_ -]?key)\b|"
    r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)"
)


class AcquisitionAcceptanceError(SourceError):
    """A finalized run is not safe or complete enough to publish."""


def _need(condition, code):
    if not condition:
        raise AcquisitionAcceptanceError(code)


def _contains_secret(value):
    return isinstance(value, str) and _SECRET_TEXT.search(value) is not None


def _safe_identifier(value):
    return isinstance(value, str) and bool(value) and not _contains_secret(value)


def _require_nonoverlap(*paths):
    absolute = [Path(os.path.abspath(path)) for path in paths]
    _need(len(set(absolute)) == len(absolute),
          "ACQ_ACCEPTANCE_ROOT_OVERLAP")
    for index, left in enumerate(absolute):
        for right in absolute[index + 1:]:
            _need(not left.is_relative_to(right)
                  and not right.is_relative_to(left),
                  "ACQ_ACCEPTANCE_ROOT_OVERLAP")


def _json_file(path, *, code, maximum=MAX_REGISTRY_BYTES):
    path = private_path(path)
    _need(path.is_file() and not path.is_symlink() and path.stat().st_size <= maximum, code)
    try:
        value = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        raise AcquisitionAcceptanceError(code) from None
    _need(isinstance(value, dict), code)
    return value


def _path_ref(path):
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _reopen_finalized_session(directory):
    directory = private_path(directory)
    state = _json_file(directory / "session.json", code="ACQ_ACCEPTANCE_SESSION_INVALID")
    _need(state.get("version") == "acquisition-live-session-1"
          and state.get("phase") == "finalized"
          and isinstance(state.get("final_ref"), dict),
          "ACQ_ACCEPTANCE_SESSION_NOT_FINALIZED")
    result_ref = state["final_ref"]
    result = read(result_ref)
    _need(result.get("kind") == "acquisition_live_session_result"
          and result.get("version") == "acquisition-live-session-1",
          "ACQ_ACCEPTANCE_RESULT_INVALID")
    identities = {key: result.get(key) for key in ("experiment_id", "execution_id", "trace_id")}
    _need(all(_safe_identifier(value) for value in identities.values())
          and identities == state.get("identities"), "ACQ_ACCEPTANCE_IDENTITY_INVALID")
    _need(result.get("run_kind") == "narrow",
          "ACQ_ACCEPTANCE_SMOKE_NOT_PUBLISHABLE")
    _need(result.get("session_spec_version") == "acquisition-live-session-2"
          and result.get("compatibility_only") is False,
          "ACQ_ACCEPTANCE_V2_REQUIRED")
    _need(result.get("host_adapter") == state.get("host_adapter")
          and result.get("host_identity") == state.get("host_identity")
          and result.get("configured_backend") == state.get("configured_backend")
          and result.get("host_profile_ref") == state.get("host_profile_ref")
          and result.get("credential_readiness_ref") == state.get("credential_readiness_ref")
          and result.get("mcp_status") == "not_used"
          and result.get("trust_policy") == "operational_host_evidence"
          and result.get("live_acceptance_eligible") is True
          and result.get("cryptographic_remote_attestation") is False,
          "ACQ_ACCEPTANCE_HOST_BINDING_INVALID")
    proposal_refs = state.get("proposal_refs")
    dispatch_refs = result.get("dispatch_refs")
    host_invocation_refs = result.get("host_invocation_refs")
    review_refs = result.get("review_refs")
    _need(all(isinstance(rows, list) for rows in (
              proposal_refs, dispatch_refs, host_invocation_refs, review_refs))
          and len(proposal_refs) == EXPECTED_DISPATCHES
          and len(dispatch_refs) == EXPECTED_DISPATCHES
          and len(host_invocation_refs) == EXPECTED_DISPATCHES
          and len(review_refs) == 1
          and result.get("trust_policy") == "operational_host_evidence",
          "ACQ_ACCEPTANCE_ROSTER_INVALID")
    return state, result_ref, result, identities


def _verify_host_config(result, identities):
    driver_ref = result.get("driver_ref")
    driver = read(driver_ref)
    _need(driver.get("kind") == "acquisition_driver_run"
          and all(driver.get(key) == value for key, value in identities.items()),
          "ACQ_ACCEPTANCE_DRIVER_BINDING_INVALID")
    host = read(driver.get("host_run_ref"))
    config_ref = host.get("config_ref")
    config = read(config_ref)
    _need(host.get("kind") == "acquisition_eval_run"
          and host.get("execution_id") == identities["execution_id"]
          and host.get("backend") == result.get("configured_backend")
          and host.get("config_sha256") == config_ref.get("sha256")
          and config.get("execution_id") == identities["execution_id"]
          and config.get("backend") == result.get("configured_backend"),
          "ACQ_ACCEPTANCE_CONFIG_BINDING_INVALID")
    context = read(config.get("baseline_ref"))
    profile_ref = result.get("host_profile_ref")
    credential_ref = result.get("credential_readiness_ref")
    _need(context.get("kind") == "live_readiness_context"
          and context.get("host_profile_ref") == profile_ref
          and context.get("credential_readiness_ref") == credential_ref,
          "ACQ_ACCEPTANCE_CONTEXT_BINDING_INVALID")
    profile_artifact = read(profile_ref)
    credential_artifact = read(credential_ref)
    profile = profile_artifact.get("profile", {})
    credential = credential_artifact.get("receipt", {})
    _need(profile_artifact.get("kind") == "acquisition_host_profile"
          and credential_artifact.get("kind") == "acquisition_credential_readiness"
          and profile.get("configured_backend") == result.get("configured_backend")
          and profile.get("mcp") is None
          and profile.get("credential", {}).get("credential_value_present") is False
          and credential.get("status") == "ready"
          and credential.get("credential_values_present") is False
          and credential.get("profile_ref") == profile.get("credential", {}).get("profile_ref"),
          "ACQ_ACCEPTANCE_HOST_PROFILE_INVALID")
    return driver_ref, config_ref


def _verify_checker(state, result):
    reconciliation_ref = result.get("reconciliation_ref")
    reconciliation = read(reconciliation_ref)
    _need(reconciliation.get("kind") == "acquisition_terminal_reconciliation"
          and reconciliation.get("status") == "pass"
          and reconciliation.get("live_acceptance_eligible") is True
          and reconciliation.get("driver_ref") == result.get("driver_ref")
          and reconciliation.get("dispatch_refs") == result.get("dispatch_refs")
          and reconciliation.get("host_invocation_refs")
              == result.get("host_invocation_refs")
          and reconciliation.get("trust_policy") == result.get("trust_policy")
          and reconciliation.get("host_session_id") == result.get("host_identity")
          and reconciliation.get("host_adapter") == result.get("host_adapter")
          and reconciliation.get("review_refs") == result.get("review_refs")
          and reconciliation.get("expected_dispatches") == EXPECTED_DISPATCHES
          and reconciliation.get("actual_dispatches") == EXPECTED_DISPATCHES
          and isinstance(reconciliation.get("gates"), list)
          and reconciliation["gates"]
          and all(row.get("passed") is True for row in reconciliation["gates"]),
          "ACQ_ACCEPTANCE_RECONCILIATION_INVALID")
    arguments = {
        "driver_ref": result["driver_ref"],
        "dispatch_refs": result["dispatch_refs"],
        "host_invocation_refs": result["host_invocation_refs"],
        "review_refs": result["review_refs"],
        "proposal_refs": state["proposal_refs"],
        "expected_dispatches": EXPECTED_DISPATCHES,
        "reconciliation_ref": reconciliation_ref,
        "host_profile_ref": result["host_profile_ref"],
        "credential_readiness_ref": result["credential_readiness_ref"],
        "trust_policy": result["trust_policy"],
        "host_session_id": result["host_identity"],
        "host_adapter": result["host_adapter"],
    }
    full = check_acquisition_trace(**arguments)
    saved = result.get("checker_verdict")
    _need(saved == full and full.get("status") == "pass"
          and full.get("complete_chains") == full.get("credited_units") == 1
          and full.get("live_acceptance_eligible") is True
          and result.get("live_acceptance_eligible") is True,
          "ACQ_ACCEPTANCE_CHECKER_INVALID")
    return reconciliation_ref, full


def _open_private_child(directory_fd, name):
    _need(isinstance(name, str) and re.fullmatch(r"[a-z0-9-]{1,64}", name),
          "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
    try:
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
            dir_fd=directory_fd)
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=directory_fd)
        descriptor = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
            dir_fd=directory_fd)
    _secure_directory(os.fstat(descriptor))
    return descriptor


def _save_at(directory_fd, directory_path, child_name, value, *,
             keep_directory=False):
    raw = encoded(value)
    _need(len(raw) <= 8 * 1024 * 1024,
          "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
    sha256 = hashlib.sha256(raw).hexdigest()
    final_name = sha256 + ".json"
    child_fd = _open_private_child(directory_fd, child_name)
    temporary = f".{final_name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = None
    held_child_fd = None
    try:
        try:
            existing = _read_regular_at(
                child_fd, final_name, 8 * 1024 * 1024,
                "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
        except FileNotFoundError:
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600, dir_fd=child_fd)
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                _need(written > 0, "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = None
            try:
                os.link(temporary, final_name, src_dir_fd=child_fd,
                        dst_dir_fd=child_fd, follow_symlinks=False)
            except FileExistsError:
                existing = _read_regular_at(
                    child_fd, final_name, 8 * 1024 * 1024,
                    "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
                _need(existing == raw, "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
            os.fsync(child_fd)
        else:
            _need(existing == raw, "ACQ_ACCEPTANCE_PUBLICATION_INVALID")
        if keep_directory:
            held_child_fd = os.dup(child_fd)
    except OSError:
        raise AcquisitionAcceptanceError(
            "ACQ_ACCEPTANCE_PUBLICATION_INVALID") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=child_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass
        os.close(child_fd)
    reference = {"path": str(directory_path / child_name / final_name),
                 "sha256": sha256}
    return (reference, held_child_fd) if keep_directory else reference


def _assert_child_directory(parent_fd, child_name, held_child_fd):
    current = _open_private_child(parent_fd, child_name)
    try:
        held = os.fstat(held_child_fd)
        observed = os.fstat(current)
        _secure_directory(held)
        _secure_directory(observed)
        _need((held.st_dev, held.st_ino, held.st_uid, held.st_gid,
               stat.S_IMODE(held.st_mode))
              == (observed.st_dev, observed.st_ino, observed.st_uid,
                  observed.st_gid, stat.S_IMODE(observed.st_mode)),
              "ACQ_ACCEPTANCE_PUBLICATION_CHANGED")
    finally:
        os.close(current)


def _validate_registry(registry, directory, directory_fd=None):
    candidate_ref = (_save_at(directory_fd, directory, "registry-validation", registry)
                     if directory_fd is not None
                     else save(directory / "registry-validation", registry))
    datasource._registry(datasource.Reader(), candidate_ref)


def _secure_directory(info):
    _need(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
          and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH),
          "ACQ_ACCEPTANCE_REGISTRY_INVALID")


def _secure_regular(info, code):
    _need(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
          and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH), code)


def _open_private_directory(path, *, create):
    """Open every workspace-relative component with no-follow semantics."""
    path = Path(os.path.abspath(path))
    private_path(path)
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        raise AcquisitionAcceptanceError("ACQ_ACCEPTANCE_REGISTRY_INVALID") from None
    descriptor = os.open(ROOT, os.O_RDONLY | os.O_NOFOLLOW
                         | getattr(os, "O_DIRECTORY", 0))
    try:
        _secure_directory(os.fstat(descriptor))
        for part in relative.parts:
            _need(part not in {"", ".", ".."},
                  "ACQ_ACCEPTANCE_REGISTRY_INVALID")
            try:
                child = os.open(part, os.O_RDONLY | os.O_NOFOLLOW
                                | getattr(os, "O_DIRECTORY", 0),
                                dir_fd=descriptor)
            except FileNotFoundError:
                _need(create, "ACQ_ACCEPTANCE_REGISTRY_INVALID")
                os.mkdir(part, 0o700, dir_fd=descriptor)
                child = os.open(part, os.O_RDONLY | os.O_NOFOLLOW
                                | getattr(os, "O_DIRECTORY", 0),
                                dir_fd=descriptor)
            _secure_directory(os.fstat(child))
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_regular_at(directory_fd, name, maximum, code):
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                         dir_fd=directory_fd)
    try:
        before = os.fstat(descriptor)
        _secure_regular(before, code)
        _need(0 < before.st_size <= maximum, code)
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            _need(chunk, code)
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(descriptor)
        _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
              == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), code)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _registry_ref_at(directory_fd, path):
    raw = _read_regular_at(directory_fd, path.name, MAX_REGISTRY_BYTES,
                           "ACQ_ACCEPTANCE_REGISTRY_INVALID")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _atomic_registry_at(directory_fd, name, value):
    payload = encoded(value)
    _need(len(payload) <= MAX_REGISTRY_BYTES,
          "ACQ_ACCEPTANCE_REGISTRY_TOO_LARGE")
    try:
        existing = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except FileNotFoundError:
        existing = None
    if existing is not None:
        _secure_regular(existing, "ACQ_ACCEPTANCE_REGISTRY_INVALID")
    temporary = f".{name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                             | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            _need(written > 0, "ACQ_ACCEPTANCE_REGISTRY_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        os.fsync(directory_fd)
    except OSError:
        raise AcquisitionAcceptanceError("ACQ_ACCEPTANCE_REGISTRY_WRITE_FAILED") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        except OSError:
            pass


@contextmanager
def _registry_lock(directory_fd, name):
    try:
        descriptor = os.open(name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW
                             | os.O_NONBLOCK, 0o600, dir_fd=directory_fd)
        _secure_regular(os.fstat(descriptor),
                        "ACQ_ACCEPTANCE_REGISTRY_LOCK_INVALID")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except (OSError, AcquisitionAcceptanceError):
        try:
            os.close(descriptor)
        except (NameError, OSError):
            pass
        raise AcquisitionAcceptanceError(
            "ACQ_ACCEPTANCE_REGISTRY_LOCK_INVALID") from None
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _register(registry_path, entry, envelope, directory, *,
              registry_directory_fd=None, publication_directory_fd=None,
              report_directory_fd=None, path_guard=None):
    registry_path = private_path(registry_path)
    if path_guard is not None:
        path_guard()
    if report_directory_fd is not None:
        _assert_child_directory(
            publication_directory_fd, "envelopes", report_directory_fd)
    parent_fd = (os.dup(registry_directory_fd)
                 if registry_directory_fd is not None
                 else _open_private_directory(registry_path.parent, create=True))
    try:
        with _registry_lock(parent_fd, registry_path.name + ".lock"):
            try:
                raw = _read_regular_at(parent_fd, registry_path.name,
                                       MAX_REGISTRY_BYTES,
                                       "ACQ_ACCEPTANCE_REGISTRY_INVALID")
            except FileNotFoundError:
                registry = {"schema_version": 1}
                registry_existed = False
            else:
                registry_existed = True
                try:
                    registry = json.loads(raw)
                except (UnicodeError, json.JSONDecodeError):
                    raise AcquisitionAcceptanceError(
                        "ACQ_ACCEPTANCE_REGISTRY_INVALID") from None
                _need(isinstance(registry, dict),
                      "ACQ_ACCEPTANCE_REGISTRY_INVALID")
                _validate_registry(registry, directory, publication_directory_fd)
            rows = list(registry.get("acquisition_comparison_refs", []))
            same_key = []
            for row in rows:
                if not isinstance(row, dict) or row.get("subject") != entry["subject"]:
                    continue
                try:
                    prior = read(row.get("report_ref"))
                except (SourceError, OSError, ValueError, TypeError):
                    raise AcquisitionAcceptanceError(
                        "ACQ_ACCEPTANCE_REGISTRY_INVALID") from None
                if prior.get("execution_id") == envelope["execution_id"]:
                    same_key.append(row)
            _need(len(same_key) <= 1, "ACQ_ACCEPTANCE_PUBLICATION_CONFLICT")
            if same_key:
                _need(same_key[0] == entry,
                      "ACQ_ACCEPTANCE_PUBLICATION_CONFLICT")
                if report_directory_fd is not None:
                    _assert_child_directory(
                        publication_directory_fd, "envelopes",
                        report_directory_fd)
                return True, _registry_ref_at(parent_fd, registry_path)
            rows.append(entry)
            candidate = {**registry, "schema_version": 1,
                         "acquisition_comparison_refs": rows}
            _validate_registry(candidate, directory, publication_directory_fd)
            if path_guard is not None:
                path_guard()
            if report_directory_fd is not None:
                _assert_child_directory(
                    publication_directory_fd, "envelopes", report_directory_fd)
            _atomic_registry_at(parent_fd, registry_path.name, candidate)
            try:
                if report_directory_fd is not None:
                    _assert_child_directory(
                        publication_directory_fd, "envelopes",
                        report_directory_fd)
            except Exception:
                if registry_existed:
                    _atomic_registry_at(parent_fd, registry_path.name, registry)
                else:
                    try:
                        os.unlink(registry_path.name, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                    except FileNotFoundError:
                        pass
                raise
            return False, _registry_ref_at(parent_fd, registry_path)
    finally:
        os.close(parent_fd)


def _readback(registry_ref, envelope_ref, subject, identities):
    reader = datasource.Reader()
    registry = datasource._registry(reader, registry_ref)
    matches = [row for row in registry.get("acquisition_comparison_refs", [])
               if row.get("subject") == subject and row.get("report_ref") == envelope_ref]
    _need(len(matches) == 1, "ACQ_ACCEPTANCE_READBACK_REGISTRY_MISMATCH")
    comparison, sources = acquisition_projection.project(
        reader, envelope_ref, subject, text=datasource.text,
        identifier=datasource.identifier, timestamp=datasource.timestamp,
        sha=datasource.sha, source_dto=datasource.source_dto,
        numeric_metrics=datasource.numeric_metrics, aggregate=datasource.aggregate)
    reader.coherent()
    trace = comparison.get("driver_trace", {})
    accounting = trace.get("accounting", {})
    _need(comparison.get("status") == "qualified"
          and all(trace.get(key) == value for key, value in identities.items())
          and trace.get("checker_verdict") == "pass"
          and accounting.get("logical_operations") == EXPECTED_DISPATCHES
          and accounting.get("actual_dispatches") == EXPECTED_DISPATCHES
          and accounting.get("complete_chains") == accounting.get("credited_units") == 1
          and len(trace.get("units", [])) == 1
          and len(sources) == 1,
          "ACQ_ACCEPTANCE_READBACK_MISMATCH")
    return trace


def publish_acquisition_acceptance(
        session_directory, *, subject, registry_path=None, publication_directory=None,
        _path_guard=None, _registry_directory_fd=None,
        _publication_directory_fd=None):
    """Publish and independently read back one finalized live-session result.

    The idempotency key is ``(subject, execution_id)``. Replaying identical bytes
    succeeds; attempting to bind that key to a different envelope fails closed.
    """
    _need(isinstance(subject, str) and _SUBJECT.fullmatch(subject),
          "ACQ_ACCEPTANCE_SUBJECT_INVALID")
    subject = subject.upper()
    _need(registry_path is not None, "ACQ_ACCEPTANCE_REGISTRY_REQUIRED")
    registry_path = Path(os.path.abspath(registry_path))
    publication_directory = Path(os.path.abspath(
        publication_directory or (INVESTMENT_STATE / "acquisition-acceptance")))
    session_directory = Path(os.path.abspath(session_directory))

    state, result_ref, result, identities = _reopen_finalized_session(session_directory)
    driver_ref, config_ref = _verify_host_config(result, identities)
    reconciliation_ref, public_verdict = _verify_checker(state, result)
    context = read(read(driver_ref)["host_run_ref"])
    config = read(context["config_ref"])
    readiness_context = read(config["baseline_ref"])
    readiness = read(readiness_context["readiness_ref"])
    case = readiness.get("packet", {}).get("case", {})
    case_id = case.get("case_id")
    issuer_id = case.get("issuer_id")
    _need(datasource.identifier(case_id, None) is not None
          and isinstance(issuer_id, str) and _SUBJECT.fullmatch(issuer_id)
          and not _contains_secret(issuer_id)
          and subject == issuer_id.upper(),
          "ACQ_ACCEPTANCE_CASE_INVALID")
    persisted_identifiers = [
        *identities.values(), issuer_id, case_id,
        result.get("host_identity"), result.get("host_adapter"),
    ]
    _need(all(_safe_identifier(value) for value in persisted_identifiers),
          "ACQ_ACCEPTANCE_IDENTITY_INVALID")
    _require_nonoverlap(
        session_directory, registry_path.parent, publication_directory)
    if _path_guard is not None:
        _path_guard()
    publication_directory = private_path(publication_directory, create=True)
    publication_fd = (os.dup(_publication_directory_fd)
                      if _publication_directory_fd is not None
                      else _open_private_directory(publication_directory, create=True))

    envelope = {
        "kind": "acquisition_driver_projection",
        "schema_version": 1,
        "publication_version": VERSION,
        "subject": subject,
        "case_id": case_id,
        **identities,
        "result_sha256": result_ref["sha256"],
        "host_profile_sha256": result["host_profile_ref"]["sha256"],
        "config_sha256": config_ref["sha256"],
        "driver_ref": driver_ref,
        "dispatch_refs": result["dispatch_refs"],
        "host_invocation_refs": result["host_invocation_refs"],
        "review_refs": result["review_refs"],
        "proposal_refs": state["proposal_refs"],
        "reconciliation_ref": reconciliation_ref,
        "host_profile_ref": result["host_profile_ref"],
        "credential_readiness_ref": result["credential_readiness_ref"],
        "trust_policy": result["trust_policy"],
        "host_session_id": result["host_identity"],
        "host_adapter": result["host_adapter"],
        "live_acceptance_eligible": result["live_acceptance_eligible"],
        "cryptographic_remote_attestation": False,
        "expected_dispatches": EXPECTED_DISPATCHES,
        "checker_verdict": public_verdict,
        "scope": "live_structural_acceptance_not_provider_quality_investment_quality_or_alpha",
    }
    envelope_directory_fd = None
    try:
        _need(len(encoded(envelope)) <= 64 * 1024,
              "ACQ_ACCEPTANCE_ENVELOPE_TOO_LARGE")
        if _path_guard is not None:
            _path_guard()
        envelope_ref, envelope_directory_fd = _save_at(
            publication_fd, publication_directory, "envelopes", envelope,
            keep_directory=True)
        _assert_child_directory(
            publication_fd, "envelopes", envelope_directory_fd)
        entry = {"subject": subject, "report_ref": envelope_ref}
        if _path_guard is not None:
            _path_guard()
        replay, registry_ref = _register(
            registry_path, entry, envelope, publication_directory,
            registry_directory_fd=_registry_directory_fd,
            publication_directory_fd=publication_fd,
            report_directory_fd=envelope_directory_fd,
            path_guard=_path_guard)
        _assert_child_directory(
            publication_fd, "envelopes", envelope_directory_fd)
        if _path_guard is not None:
            _path_guard()
        trace = _readback(registry_ref, envelope_ref, subject, identities)
        _assert_child_directory(
            publication_fd, "envelopes", envelope_directory_fd)
        if _path_guard is not None:
            _path_guard()
    finally:
        if envelope_directory_fd is not None:
            os.close(envelope_directory_fd)
        os.close(publication_fd)
    return {
        "status": "published", "idempotent_replay": replay,
        **identities, "subject": subject, "case_id": case_id,
        "result_sha256": result_ref["sha256"],
        "envelope_sha256": envelope_ref["sha256"],
        "registry_sha256": registry_ref["sha256"],
        "host_profile_sha256": result["host_profile_ref"]["sha256"],
        "config_sha256": config_ref["sha256"],
        "checker_status": trace["checker_verdict"],
        "complete_chains": trace["accounting"]["complete_chains"],
        "credited_units": trace["accounting"]["credited_units"],
        "actual_dispatches": trace["accounting"]["actual_dispatches"],
        "live_acceptance_eligible": trace["live_acceptance_eligible"],
        "cryptographic_remote_attestation": False,
        "scope": envelope["scope"],
    }


publish = publish_acquisition_acceptance
