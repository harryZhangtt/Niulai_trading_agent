"""Bounded provider-free CLI for acquisition acceptance publication/readback.

This command never invokes providers, models, schedulers, email, or credentials. It
publishes only a finalized narrow live-session result that the existing acceptance
boundary independently reopens and validates.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import uuid

from investment.research import datasource
from investment.research.acquisition_acceptance import (
    AcquisitionAcceptanceError,
    _contains_secret,
    _path_ref,
    _readback,
    _reopen_finalized_session,
    _verify_checker,
    _verify_host_config,
    publish_acquisition_acceptance,
)
from shared.research_sources.artifacts import ROOT, SourceError, read


VERSION = "acquisition-acceptance-cli-1"
MAX_OUTPUT_BYTES = 16 * 1024
_SUBJECT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}")
_SHA256 = re.compile(r"[a-f0-9]{64}")
_PRIVATE_PATH = re.compile(r"(?:/Users/|/home/|/private/|/tmp/|[A-Za-z]:[/\\])")
_ALLOWED_PATH_ROOTS = (
    ROOT / ".research-sources",
    ROOT / ".niulai-state/reports",
    ROOT / "investment/runtime",
)


class AcquisitionAcceptanceCliError(ValueError):
    """Stable, credential-free CLI rejection."""


class _Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise AcquisitionAcceptanceCliError("ACQ_ACCEPTANCE_CLI_ARGUMENT_INVALID")


def _need(condition, code):
    if not condition:
        raise AcquisitionAcceptanceCliError(code)


def _safe_text(value, code):
    _need(isinstance(value, str) and not _contains_secret(value)
          and not _PRIVATE_PATH.search(value), code)
    return value


def _subject(value):
    _need(isinstance(value, str) and _SUBJECT.fullmatch(value)
          and not _contains_secret(value), "ACQ_ACCEPTANCE_CLI_SUBJECT_INVALID")
    return value.upper()


def _execution_id(value):
    try:
        parsed = uuid.UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_EXECUTION_INVALID") from None
    _need(str(parsed) == value and not _contains_secret(value),
          "ACQ_ACCEPTANCE_CLI_EXECUTION_INVALID")
    return value


def _inside_allowed(path):
    return any(path.is_relative_to(root) and path != root
               for root in _ALLOWED_PATH_ROOTS)


def _secure_mode(info, *, directory):
    _need(info.st_uid == os.getuid() and not info.st_mode & (stat.S_IWGRP | stat.S_IWOTH),
          "ACQ_ACCEPTANCE_CLI_PATH_INVALID")
    _need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode),
          "ACQ_ACCEPTANCE_CLI_PATH_INVALID")


def _open_directory_components(path):
    """Open every workspace-relative directory component without following links."""
    path = Path(os.path.abspath(path))
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_PATH_INVALID") from None
    descriptor = os.open(
        ROOT, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0))
    try:
        _secure_mode(os.fstat(descriptor), directory=True)
        for part in relative.parts:
            _need(part not in {"", ".", ".."},
                  "ACQ_ACCEPTANCE_CLI_PATH_INVALID")
            child = os.open(
                part,
                os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0),
                dir_fd=descriptor,
            )
            _secure_mode(os.fstat(child), directory=True)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except (OSError, AcquisitionAcceptanceCliError):
        os.close(descriptor)
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_PATH_INVALID") from None


@contextmanager
def _held_directory(path):
    descriptor = _open_directory_components(path)
    try:
        before = os.fstat(descriptor)
        _secure_mode(before, directory=True)
        yield descriptor
        after = os.fstat(descriptor)
        _secure_mode(after, directory=True)
        _need((before.st_dev, before.st_ino, before.st_uid, before.st_gid,
               stat.S_IMODE(before.st_mode))
              == (after.st_dev, after.st_ino, after.st_uid, after.st_gid,
                  stat.S_IMODE(after.st_mode)),
              "ACQ_ACCEPTANCE_CLI_PATH_CHANGED")
    finally:
        os.close(descriptor)


def _assert_descriptor_path(path, descriptor):
    current = _open_directory_components(path)
    try:
        held = os.fstat(descriptor)
        observed = os.fstat(current)
        _secure_mode(held, directory=True)
        _secure_mode(observed, directory=True)
        _need((held.st_dev, held.st_ino, held.st_uid, held.st_gid,
               stat.S_IMODE(held.st_mode))
              == (observed.st_dev, observed.st_ino, observed.st_uid,
                  observed.st_gid, stat.S_IMODE(observed.st_mode)),
              "ACQ_ACCEPTANCE_CLI_PATH_CHANGED")
    finally:
        os.close(current)


def _session_root(value):
    path = Path(os.path.abspath(value))
    _need(_inside_allowed(path), "ACQ_ACCEPTANCE_CLI_SESSION_INVALID")
    try:
        with _held_directory(path) as directory:
            descriptor = os.open("session.json", os.O_RDONLY | os.O_NOFOLLOW,
                                 dir_fd=directory)
            try:
                info = os.fstat(descriptor)
                _secure_mode(info, directory=False)
            finally:
                os.close(descriptor)
    except (OSError, AcquisitionAcceptanceCliError):
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_SESSION_INVALID") from None
    return path


def _registry_path(value, *, must_exist):
    path = Path(os.path.abspath(value))
    _need(_inside_allowed(path) and path.suffix == ".json"
          and path != Path(os.path.abspath(datasource.REGISTRY)),
          "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID")
    try:
        context = _held_directory(path.parent)
        directory = context.__enter__()
    except (OSError, AcquisitionAcceptanceCliError):
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID") from None
    try:
        if must_exist:
            try:
                descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW,
                                     dir_fd=directory)
            except OSError:
                raise AcquisitionAcceptanceCliError(
                    "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID") from None
            try:
                info = os.fstat(descriptor)
                _secure_mode(info, directory=False)
                _need(info.st_size <= 256 * 1024,
                      "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID")
            finally:
                os.close(descriptor)
        else:
            try:
                info = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                info = None
            if info is not None:
                _secure_mode(info, directory=False)
    finally:
        context.__exit__(None, None, None)
    return path


def _publication_root(value):
    path = Path(os.path.abspath(value))
    _need(_inside_allowed(path), "ACQ_ACCEPTANCE_CLI_PUBLICATION_INVALID")
    try:
        with _held_directory(path):
            pass
    except (OSError, AcquisitionAcceptanceCliError):
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_PUBLICATION_INVALID") from None
    return path


def _nonoverlap(paths):
    resolved = [Path(os.path.abspath(path)) for path in paths]
    _need(len(set(resolved)) == len(resolved), "ACQ_ACCEPTANCE_CLI_ROOT_OVERLAP")
    for left in resolved:
        for right in resolved:
            if left == right:
                continue
            _need(not left.is_relative_to(right) and not right.is_relative_to(left),
                  "ACQ_ACCEPTANCE_CLI_ROOT_OVERLAP")


def _serialize(result):
    _need(isinstance(result, dict), "ACQ_ACCEPTANCE_CLI_RESULT_INVALID")
    try:
        raw = json.dumps(result, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        raise AcquisitionAcceptanceCliError(
            "ACQ_ACCEPTANCE_CLI_RESULT_INVALID") from None
    text = raw.decode(errors="ignore")
    _need(len(raw) + 1 <= MAX_OUTPUT_BYTES, "ACQ_ACCEPTANCE_CLI_OUTPUT_LIMIT")
    _need(not _contains_secret(text) and not _PRIVATE_PATH.search(text)
          and str(ROOT) not in text, "ACQ_ACCEPTANCE_CLI_PRIVATE_OUTPUT")
    return raw


def _sealed_case(result):
    driver = read(result.get("driver_ref"))
    host = read(driver.get("host_run_ref"))
    config = read(host.get("config_ref"))
    context = read(config.get("baseline_ref"))
    readiness = read(context.get("readiness_ref"))
    case = readiness.get("packet", {}).get("case", {})
    issuer = case.get("issuer_id")
    case_id = case.get("case_id")
    _need(isinstance(issuer, str) and _SUBJECT.fullmatch(issuer)
          and isinstance(case_id, str) and 1 <= len(case_id) <= 96
          and not _contains_secret(issuer + case_id),
          "ACQ_ACCEPTANCE_CLI_CASE_INVALID")
    return issuer.upper(), case_id


def _validated_session(session_root, expected_execution_id, subject):
    state, result_ref, result, identities = _reopen_finalized_session(session_root)
    _need(identities["execution_id"] == expected_execution_id,
          "ACQ_ACCEPTANCE_CLI_EXECUTION_MISMATCH")
    sealed_subject, case_id = _sealed_case(result)
    _need(subject == sealed_subject, "ACQ_ACCEPTANCE_CLI_SUBJECT_MISMATCH")
    driver_ref, config_ref = _verify_host_config(result, identities)
    reconciliation_ref, verdict = _verify_checker(state, result)
    _need(verdict.get("status") == "pass"
          and verdict.get("complete_chains") == verdict.get("credited_units") == 1
          and verdict.get("live_acceptance_eligible") is True,
          "ACQ_ACCEPTANCE_CLI_CHECKER_INVALID")
    return (state, result_ref, result, identities, driver_ref, config_ref,
            reconciliation_ref, case_id)


def describe():
    return {
        "version": VERSION,
        "commands": ["describe", "publish", "verify"],
        "side_effects": {
            "describe": [],
            "verify": [],
            "publish": ["content_addressed_projection", "isolated_registry_entry"],
        },
        "prohibited": [
            "provider_call", "model_call", "scheduler_action", "email",
            "credential_read", "default_registry_mutation",
        ],
        "claim_limit": (
            "Provider-free acceptance publication/readback only; not provider "
            "quality, investment quality, production readiness, or alpha."
        ),
    }


def publish(*, session_root, subject, expected_execution_id,
            registry_path, publication_root):
    session_root = _session_root(session_root)
    subject = _subject(subject)
    expected_execution_id = _execution_id(expected_execution_id)
    registry_path = _registry_path(registry_path, must_exist=False)
    publication_root = _publication_root(publication_root)
    _nonoverlap((session_root, registry_path.parent, publication_root))
    with ExitStack() as stack:
        session_fd = stack.enter_context(_held_directory(session_root))
        registry_fd = stack.enter_context(_held_directory(registry_path.parent))
        publication_fd = stack.enter_context(_held_directory(publication_root))

        def path_guard():
            _assert_descriptor_path(session_root, session_fd)
            _assert_descriptor_path(registry_path.parent, registry_fd)
            _assert_descriptor_path(publication_root, publication_fd)

        path_guard()
        _validated_session(session_root, expected_execution_id, subject)
        path_guard()
        result = publish_acquisition_acceptance(
            session_root, subject=subject, registry_path=registry_path,
            publication_directory=publication_root, _path_guard=path_guard,
            _registry_directory_fd=registry_fd,
            _publication_directory_fd=publication_fd)
        path_guard()
    _need(result.get("execution_id") == expected_execution_id
          and result.get("checker_status") == "pass"
          and result.get("complete_chains") == result.get("credited_units") == 1
          and result.get("actual_dispatches") == 3
          and result.get("live_acceptance_eligible") is True,
          "ACQ_ACCEPTANCE_CLI_PUBLICATION_INVALID")
    return {"version": VERSION, **result}


@contextmanager
def _locked_registry(registry_path):
    with _held_directory(registry_path.parent) as directory:
        lock_name = registry_path.name + ".lock"
        descriptor = None
        locked = False
        try:
            descriptor = os.open(
                lock_name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                0o600, dir_fd=directory)
            _secure_mode(os.fstat(descriptor), directory=False)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            locked = True
            source = os.open(registry_path.name, os.O_RDONLY | os.O_NOFOLLOW,
                             dir_fd=directory)
            try:
                before = os.fstat(source)
                _secure_mode(before, directory=False)
                _need(before.st_size <= 256 * 1024,
                      "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID")
                raw = b""
                while len(raw) <= 256 * 1024:
                    chunk = os.read(source, min(65536, 256 * 1024 + 1 - len(raw)))
                    if not chunk:
                        break
                    raw += chunk
                _need(len(raw) <= 256 * 1024,
                      "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID")
            finally:
                os.close(source)
            yield raw
            current = os.stat(registry_path.name, dir_fd=directory,
                              follow_symlinks=False)
            _need((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                  == (current.st_dev, current.st_ino, current.st_size,
                      current.st_mtime_ns),
                  "ACQ_ACCEPTANCE_CLI_REGISTRY_CHANGED")
        except OSError:
            raise AcquisitionAcceptanceCliError(
                "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID") from None
        finally:
            if descriptor is not None:
                try:
                    if locked:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)


def verify(*, session_root, subject, expected_execution_id, registry_path):
    session_root = _session_root(session_root)
    subject = _subject(subject)
    expected_execution_id = _execution_id(expected_execution_id)
    registry_path = _registry_path(registry_path, must_exist=True)
    _nonoverlap((session_root, registry_path.parent))
    with ExitStack() as stack:
        session_fd = stack.enter_context(_held_directory(session_root))
        _assert_descriptor_path(session_root, session_fd)
        raw = stack.enter_context(_locked_registry(registry_path))
        _assert_descriptor_path(session_root, session_fd)
        (state, result_ref, result, identities, _driver_ref, config_ref,
         reconciliation_ref, case_id) = _validated_session(
            session_root, expected_execution_id, subject)
        try:
            registry = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            raise AcquisitionAcceptanceCliError(
                "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID") from None
        _need(isinstance(registry, dict), "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID")
        rows = registry.get("acquisition_comparison_refs", [])
        _need(isinstance(rows, list), "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID")
        matches = []
        for row in rows:
            if not isinstance(row, dict) or row.get("subject") != subject:
                continue
            try:
                envelope = read(row.get("report_ref"))
            except (SourceError, OSError, TypeError, ValueError):
                raise AcquisitionAcceptanceCliError(
                    "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID") from None
            if envelope.get("execution_id") == expected_execution_id:
                matches.append((row, envelope))
        _need(len(matches) == 1, "ACQ_ACCEPTANCE_CLI_PUBLICATION_NOT_FOUND")
        row, envelope = matches[0]
        _need(envelope.get("result_sha256") == result_ref["sha256"]
              and envelope.get("driver_ref") == result.get("driver_ref")
              and envelope.get("config_sha256") == config_ref["sha256"]
              and envelope.get("reconciliation_ref") == reconciliation_ref
              and envelope.get("host_profile_ref") == result.get("host_profile_ref")
              and envelope.get("credential_readiness_ref")
                  == result.get("credential_readiness_ref")
              and envelope.get("live_acceptance_eligible") is True,
              "ACQ_ACCEPTANCE_CLI_CONTEXT_MISMATCH")
        registry_ref = {"path": str(registry_path),
                        "sha256": hashlib.sha256(raw).hexdigest()}
        trace = _readback(registry_ref, row["report_ref"], subject, identities)
        _assert_descriptor_path(session_root, session_fd)
        accounting = trace.get("accounting", {})
    output = {
        "version": VERSION,
        "status": "verified",
        **identities,
        "subject": subject,
        "case_id": case_id,
        "result_sha256": result_ref["sha256"],
        "envelope_sha256": row["report_ref"]["sha256"],
        "registry_sha256": hashlib.sha256(raw).hexdigest(),
        "checker_status": trace.get("checker_verdict"),
        "complete_chains": accounting.get("complete_chains"),
        "credited_units": accounting.get("credited_units"),
        "actual_dispatches": accounting.get("actual_dispatches"),
        "live_acceptance_eligible": trace.get("live_acceptance_eligible"),
        "cryptographic_remote_attestation": False,
        "scope": "provider_free_publication_verification_only",
    }
    _need(output["checker_status"] == "pass"
          and output["complete_chains"] == output["credited_units"] == 1
          and output["actual_dispatches"] == 3
          and output["live_acceptance_eligible"] is True
          and _SHA256.fullmatch(output["registry_sha256"]),
          "ACQ_ACCEPTANCE_CLI_READBACK_INVALID")
    return output


def _emit(result):
    raw = _serialize(result)
    sys.stdout.buffer.write(raw + b"\n")


def main():
    parser = _Parser(description=__doc__, add_help=False)
    parser.add_argument("command", choices=("describe", "publish", "verify"))
    parser.add_argument("--session-root")
    parser.add_argument("--subject")
    parser.add_argument("--expected-execution-id")
    parser.add_argument("--registry")
    parser.add_argument("--publication-root")
    os.umask(0o077)
    try:
        args = parser.parse_args()
        if args.command == "describe":
            result = describe()
        else:
            _need(all((args.session_root, args.subject,
                       args.expected_execution_id, args.registry)),
                  "ACQ_ACCEPTANCE_CLI_ARGUMENT_REQUIRED")
            if args.command == "publish":
                _need(args.publication_root is not None,
                      "ACQ_ACCEPTANCE_CLI_ARGUMENT_REQUIRED")
                result = publish(
                    session_root=args.session_root, subject=args.subject,
                    expected_execution_id=args.expected_execution_id,
                    registry_path=args.registry,
                    publication_root=args.publication_root)
            else:
                _need(args.publication_root is None,
                      "ACQ_ACCEPTANCE_CLI_ARGUMENT_INVALID")
                result = verify(
                    session_root=args.session_root, subject=args.subject,
                    expected_execution_id=args.expected_execution_id,
                    registry_path=args.registry)
        _emit(result)
    except Exception as error:
        code = (str(error) if isinstance(
            error, (AcquisitionAcceptanceCliError,
                    AcquisitionAcceptanceError, SourceError))
                and re.fullmatch(r"[A-Z][A-Z0-9_]{2,99}", str(error))
                else "ACQ_ACCEPTANCE_CLI_FAILED")
        _emit({"status": "failed", "code": code})
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
