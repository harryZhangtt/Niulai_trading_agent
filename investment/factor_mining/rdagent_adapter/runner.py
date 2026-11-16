"""Trusted synthetic-fixture runner for exercising the host adapter boundary.

This is not a generated-code sandbox and cannot run RD-Agent. The executable and
worker script are fixed by this module; request data cannot choose either.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import stat
import subprocess
import sys
import time

from . import contracts


SYNTHETIC_WORKER = Path(__file__).resolve().with_name("synthetic_worker.py")
SYNTHETIC_MODES = {
    "success", "missing-output", "nonzero", "disk-canary-nonzero", "reserved-names",
    "oversized", "secret-canary", "timeout", "symlink",
}
MAX_FIXED_WORKER_OUTPUT = 2 * 1024 * 1024 + 4096


class RunnerError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise RunnerError(code)


def _safe_root(path):
    root = Path(path).absolute()
    require(root.parent.is_dir() and root.parent.resolve() == root.parent,
            "ATTEMPT_ROOT_PARENT_INVALID")
    if not root.exists():
        try:
            os.mkdir(root, 0o700)
        except FileExistsError:
            pass
    require(root.is_dir() and not root.is_symlink() and root.resolve() == root,
            "ATTEMPT_ROOT_INVALID")
    for name in ("attempts", "evidence", "receipts"):
        child = root / name
        try:
            os.mkdir(child, 0o700)
        except FileExistsError:
            pass
        require(child.is_dir() and not child.is_symlink(), "ATTEMPT_ROOT_INVALID")
    return root


def _attempt_directory(root, request):
    identity = contracts.request_sha256(request)
    attempt_id = f"{request['request_id']}-{identity[:16]}"
    path = root / "attempts" / attempt_id
    if (root / "receipts" / (attempt_id + ".json")).exists():
        raise RunnerError("ATTEMPT_EXISTS")
    try:
        os.mkdir(path, 0o700)
    except FileExistsError:
        raise RunnerError("ATTEMPT_EXISTS") from None
    for child in ("home", "tmp", "artifacts"):
        os.mkdir(path / child, 0o700)
    return attempt_id, path


def _group_exists(process_group):
    try:
        os.killpg(process_group, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _signal_group(process_group, selected_signal):
    try:
        os.killpg(process_group, selected_signal)
        return True
    except ProcessLookupError:
        return True
    except PermissionError:
        return False


def _cleanup_process_group(process, process_group):
    permitted = _signal_group(process_group, signal.SIGTERM)
    try:
        process.wait(timeout=0.5)
    except subprocess.TimeoutExpired:
        permitted = _signal_group(process_group, signal.SIGKILL) and permitted
        try:
            process.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            return False
    if not _group_exists(process_group):
        return permitted
    permitted = _signal_group(process_group, signal.SIGKILL) and permitted
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if not _group_exists(process_group):
            return permitted
        time.sleep(0.02)
    return False


def _stage_failure(code):
    status = "timed_out" if code == "RUNTIME_TIMEOUT" else "failed"
    return [{"id": stage_id, "status": status if index == 0 else "skipped",
             "duration_seconds": 0.0, "evidence_sha256": None}
            for index, stage_id in enumerate(contracts.STAGE_IDS)]


def _failure_receipt(request, code, wall_seconds, cleanup_verified):
    effective_code = code if cleanup_verified else "PROCESS_CLEANUP_FAILED"
    return {
        "schema_version": 1, "kind": "rdagent_factor_receipt",
        "request_sha256": contracts.request_sha256(request),
        "status": "timed_out" if effective_code == "RUNTIME_TIMEOUT" else "failed",
        "execution_mode": "synthetic-fixture", "engine": contracts.engine_contract(),
        "stages": _stage_failure(effective_code), "artifacts": [],
        "failure_code": effective_code,
        "resources": {"wall_seconds": wall_seconds, "cpu_seconds": 0.0, "peak_rss_bytes": 0},
        "process_group_cleanup_verified": cleanup_verified,
    }


def _open_relative(root_fd, relative):
    path = Path(relative)
    contracts._relative_path(relative)
    current = os.dup(root_fd)
    try:
        for part in path.parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                              dir_fd=current)
            os.close(current)
            current = next_fd
        return os.open(path.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                       dir_fd=current)
    except FileNotFoundError:
        raise RunnerError("ARTIFACT_MISSING") from None
    except OSError:
        raise RunnerError("ARTIFACT_INVALID") from None
    finally:
        os.close(current)


def _copy_verified_artifacts(root, attempt_id, attempt, receipt, request):
    evidence = root / "evidence" / attempt_id
    os.mkdir(evidence, 0o700)
    attempt_fd = os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    total = 0
    copied = []
    expected = sorted(request["task"]["expected_factor_ids"])
    try:
        for artifact in receipt["artifacts"]:
            try:
                descriptor = _open_relative(attempt_fd, artifact["path"])
            except RunnerError as error:
                if str(error) == "ARTIFACT_MISSING" and artifact["kind"] == "generated-code":
                    raise RunnerError("FACTOR_CODE_MISSING") from None
                if str(error) == "ARTIFACT_MISSING" and artifact["kind"] == "factor-data":
                    raise RunnerError("FACTOR_OUTPUT_MISSING") from None
                raise
            output_path = evidence / (artifact["id"] + ".artifact")
            output = os.open(output_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            observed = hashlib.sha256()
            size = 0
            factor_payload = bytearray() if artifact["kind"] == "factor-data" else None
            try:
                details = os.fstat(descriptor)
                require(stat.S_ISREG(details.st_mode) and details.st_size > 0,
                        "ARTIFACT_INVALID")
                while size < details.st_size:
                    chunk = os.read(descriptor, min(65536, details.st_size - size))
                    require(chunk, "ARTIFACT_INVALID")
                    observed.update(chunk)
                    size += len(chunk)
                    total += len(chunk)
                    require(total <= request["limits"]["artifact_bytes"],
                            "ARTIFACT_INVALID")
                    if factor_payload is not None:
                        factor_payload.extend(chunk)
                    view = memoryview(chunk)
                    while view:
                        view = view[os.write(output, view):]
                os.fsync(output)
            finally:
                os.close(descriptor)
                os.close(output)
            require(size == artifact["size_bytes"] and observed.hexdigest() == artifact["sha256"],
                    "ARTIFACT_INVALID")
            require(sorted(artifact["factor_ids"]) == expected, "ARTIFACT_INVALID")
            if factor_payload is not None:
                payload = contracts.loads_strict(bytes(factor_payload), request["limits"]["artifact_bytes"],
                                                 "ARTIFACT_INVALID")
                require(isinstance(payload, dict) and set(payload) == {"factor_ids", "rows"} and
                        sorted(payload["factor_ids"]) == expected and isinstance(payload["rows"], list) and
                        payload["rows"], "ARTIFACT_INVALID")
            copied.append({**artifact, "path": str(Path("evidence") / attempt_id / output_path.name)})
    finally:
        os.close(attempt_fd)
    return copied


def _atomic_receipt(root, attempt_id, receipt):
    payload = contracts.canonical(receipt)
    directory = root / "receipts"
    temporary = directory / (".tmp-" + attempt_id)
    final = directory / (attempt_id + ".json")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            require(written > 0, "RECEIPT_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, final, follow_symlinks=False)
    except FileExistsError:
        raise RunnerError("ATTEMPT_EXISTS") from None
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
    return final


def _remove_child_state(path):
    if path.exists():
        shutil.rmtree(path)


def run_synthetic(request, mode, root_path):
    request = contracts.validate_request(request)
    require(isinstance(mode, str) and mode in SYNTHETIC_MODES, "SYNTHETIC_MODE_INVALID")
    root = _safe_root(root_path)
    attempt_id, attempt = _attempt_directory(root, request)
    environment = {"HOME": str(attempt / "home"), "TMPDIR": str(attempt / "tmp"),
                   "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "PATH": "/usr/bin:/bin"}
    started = time.monotonic()
    process = None
    cleanup = True
    failure_code = None
    output = b""
    try:
        process = subprocess.Popen(
            [str(Path(sys.executable).resolve()), "-I", str(SYNTHETIC_WORKER), mode],
            cwd=attempt, env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, start_new_session=True)
        process_group = process.pid
        try:
            output, _ = process.communicate(input=contracts.canonical(request),
                                            timeout=request["limits"]["timeout_seconds"])
        except subprocess.TimeoutExpired:
            failure_code = "RUNTIME_TIMEOUT"
            cleanup = _cleanup_process_group(process, process_group)
        else:
            cleanup = _cleanup_process_group(process, process_group)
            if process.returncode != 0:
                failure_code = "RUNTIME_NONZERO"
            elif len(output) > request["limits"]["stdout_bytes"]:
                failure_code = "RUNTIME_OUTPUT_OVERSIZE"
        for stream in (process.stdin, process.stdout):
            if stream is not None and not stream.closed:
                stream.close()
        if len(output) > MAX_FIXED_WORKER_OUTPUT:
            failure_code = "RUNTIME_OUTPUT_OVERSIZE"
        if failure_code is None:
            try:
                receipt = contracts.parse_receipt(output, request)
                require(receipt["execution_mode"] == "synthetic-fixture", "RUNTIME_OUTPUT_INVALID")
                receipt["artifacts"] = _copy_verified_artifacts(root, attempt_id, attempt, receipt, request)
                receipt["resources"]["wall_seconds"] = time.monotonic() - started
                receipt["process_group_cleanup_verified"] = cleanup
                receipt = contracts.validate_receipt(receipt, request)
                _remove_child_state(attempt)
            except (contracts.ContractError, RunnerError, OSError, ValueError) as error:
                if (isinstance(error, RunnerError) and str(error) in
                        {"FACTOR_CODE_MISSING", "FACTOR_OUTPUT_MISSING", "ARTIFACT_INVALID"}):
                    failure_code = str(error)
                else:
                    failure_code = "RUNTIME_OUTPUT_INVALID"
        if failure_code is not None:
            receipt = _failure_receipt(request, failure_code, time.monotonic() - started, cleanup)
            _remove_child_state(attempt)
            _remove_child_state(root / "evidence" / attempt_id)
        path = _atomic_receipt(root, attempt_id, contracts.validate_receipt(receipt, request))
        return {"receipt": receipt,
                "receipt_path": str(Path("receipts") / path.name),
                "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "attempt_id": attempt_id}
    except Exception:
        if process is not None and process.poll() is None:
            cleanup = _cleanup_process_group(process, process.pid)
        _remove_child_state(attempt)
        _remove_child_state(root / "evidence" / attempt_id)
        failure = _failure_receipt(request, "RUNTIME_NONZERO", time.monotonic() - started, cleanup)
        try:
            path = _atomic_receipt(root, attempt_id, contracts.validate_receipt(failure, request))
        except Exception:
            raise RunnerError("HOST_RECEIPT_PUBLICATION_FAILED") from None
        return {"receipt": failure, "receipt_path": str(Path("receipts") / path.name),
                "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "attempt_id": attempt_id}
