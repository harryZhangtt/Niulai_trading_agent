"""Held executable and totalized provider-free local process effect for v5."""
from __future__ import annotations
from dataclasses import dataclass
import ctypes
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Optional

from .contracts import (
    BINARY_REF, MODEL, PROVIDER, SAFE_ARGV, canonical_bytes, require, sha256_bytes,
)
from .ferry import LoopbackFerry

_ZERO = "0" * 64


class _ProcBsdInfo(ctypes.Structure):
    _fields_ = [
        ("pbi_flags", ctypes.c_uint32), ("pbi_status", ctypes.c_uint32),
        ("pbi_xstatus", ctypes.c_uint32), ("pbi_pid", ctypes.c_uint32),
        ("pbi_ppid", ctypes.c_uint32), ("pbi_uid", ctypes.c_uint32),
        ("pbi_gid", ctypes.c_uint32), ("pbi_ruid", ctypes.c_uint32),
        ("pbi_rgid", ctypes.c_uint32), ("pbi_svuid", ctypes.c_uint32),
        ("pbi_svgid", ctypes.c_uint32), ("rfu_1", ctypes.c_uint32),
        ("pbi_comm", ctypes.c_char * 16), ("pbi_name", ctypes.c_char * 32),
        ("pbi_nfiles", ctypes.c_uint32), ("pbi_pgid", ctypes.c_uint32),
        ("pbi_pjobc", ctypes.c_uint32), ("e_tdev", ctypes.c_uint32),
        ("e_tpgid", ctypes.c_uint32), ("pbi_nice", ctypes.c_int32),
        ("pbi_start_tvsec", ctypes.c_uint64),
        ("pbi_start_tvusec", ctypes.c_uint64),
    ]


def _process_start_token(pid: int) -> bytes:
    if pid <= 0:
        raise ProcessLookupError(pid)
    if sys.platform == "darwin":
        library = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        function = library.proc_pidinfo
        function.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64,
                             ctypes.c_void_p, ctypes.c_int]
        function.restype = ctypes.c_int
        info = _ProcBsdInfo()
        count = function(pid, 3, 0, ctypes.byref(info), ctypes.sizeof(info))
        if count != ctypes.sizeof(info):
            error = ctypes.get_errno()
            if error in (3,):
                raise ProcessLookupError(pid)
            raise OSError(error, "proc_pidinfo")
        return ("darwin:%d:%d:%d" %
                (pid, info.pbi_start_tvsec, info.pbi_start_tvusec)).encode("ascii")
    stat_path = Path("/proc") / str(pid) / "stat"
    raw = stat_path.read_text(encoding="ascii")
    close = raw.rfind(")")
    fields = raw[close + 2:].split()
    if close < 0 or len(fields) <= 19:
        raise OSError("PROCESS_START_TOKEN_UNAVAILABLE")
    boot = (Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
            if Path("/proc/sys/kernel/random/boot_id").exists() else "unknown")
    return ("linux:%d:%s:%s" % (pid, boot, fields[19])).encode("ascii")


def _token_sha(pid: int) -> str:
    return sha256_bytes(_process_start_token(pid))


def _same_process(pid: int, expected_sha256: str) -> bool:
    if pid <= 0 or expected_sha256 == _ZERO:
        return False
    try:
        return _token_sha(pid) == expected_sha256
    except (ProcessLookupError, FileNotFoundError):
        return False
    except (OSError, PermissionError):
        return True


def _write_all(fd: int, raw: bytes) -> None:
    view = memoryview(raw)
    offset = 0
    while offset < len(view):
        written = os.write(fd, view[offset:])
        if written <= 0:
            raise OSError("WRITE_ZERO")
        offset += written


@dataclass(frozen=True)
class LocalOnlyProcessEffect:
    allow_numeric_loopback: bool = False

    @staticmethod
    def _group_gone(pgid: int) -> bool:
        if pgid <= 0:
            return True
        try:
            os.killpg(pgid, 0)
            return False
        except ProcessLookupError:
            return True
        except PermissionError:
            return False

    @classmethod
    def _eradicate(cls, pgid: int) -> bool:
        if pgid <= 0:
            return True
        if not cls._group_gone(pgid):
            try:
                os.killpg(pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            end = time.monotonic() + 0.25
            while time.monotonic() < end and not cls._group_gone(pgid):
                time.sleep(0.01)
        if not cls._group_gone(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        end = time.monotonic() + 2
        while time.monotonic() < end and not cls._group_gone(pgid):
            time.sleep(0.01)
        return cls._group_gone(pgid)

    @staticmethod
    def _child_pid(stderr: bytes) -> int:
        for line in stderr.decode("utf-8", "replace").splitlines():
            if line.startswith("CHILD_PID="):
                try:
                    return int(line.split("=", 1)[1])
                except ValueError:
                    return 0
        return 0

    def execute(self, root: Path, binary: Path,
                binary_descriptor: Mapping[str, object], fingerprint: str,
                scenario: str, timeout: int) -> dict:
        require(self.allow_numeric_loopback is True, "INJECTED_EFFECT_NOT_AUTHORIZED")
        owner = root / "owner-private"
        owner.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(owner, 0o700)
        private: Optional[Path] = None
        ferry: Optional[LoopbackFerry] = None
        process: Optional[subprocess.Popen] = None
        out_f = err_f = None
        pgid = 0
        starts = 0
        exit_code = None
        timed_out = False
        boundary_error = None
        stdout = b""
        stderr = b""
        copy_sha = _ZERO
        binary_sha = str(binary_descriptor["sha256"])
        process_token = _ZERO
        child_token = _ZERO
        child_pid = 0
        private_device = private_inode = private_mode = private_uid = 0
        cleanup_errors = []
        ferry_receipt = None
        removed = True
        group_reaped = True
        child_pid_gone = True
        pid_gone = True
        descriptors_closed = True
        source = binary
        stdout_path = owner / "stdout.raw"
        stderr_path = owner / "stderr.raw"
        try:
            if scenario == "path_swap":
                source = owner / "source-candidate"
                source.write_bytes(binary.read_bytes())
                os.chmod(source, int(binary_descriptor["mode"]))
            fd = os.open(source, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                info = os.fstat(fd)
                require(stat.S_ISREG(info.st_mode), "BINARY_NOT_REGULAR")
                require(info.st_uid == binary_descriptor["uid"] and
                        stat.S_IMODE(info.st_mode) == binary_descriptor["mode"],
                        "BINARY_METADATA_DRIFT")
                chunks = []
                while True:
                    part = os.read(fd, 1048576)
                    if not part:
                        break
                    chunks.append(part)
                raw = b"".join(chunks)
                copy_sha = sha256_bytes(raw)
                require(len(raw) == binary_descriptor["bytes"] and
                        copy_sha == binary_sha, "BINARY_IDENTITY_DRIFT")
            finally:
                os.close(fd)
            private = owner / ("held-claude-" + binary_sha[:16])
            fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                         getattr(os, "O_NOFOLLOW", 0), 0o700)
            try:
                _write_all(fd, raw)
                os.fsync(fd)
            finally:
                os.close(fd)
            os.chmod(private, 0o700)
            fd = os.open(private, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            try:
                private_info = os.fstat(fd)
                private_raw = b""
                while True:
                    part = os.read(fd, 1048576)
                    if not part:
                        break
                    private_raw += part
            finally:
                os.close(fd)
            require(stat.S_ISREG(private_info.st_mode) and
                    sha256_bytes(private_raw) == binary_sha, "BINARY_COPY_DRIFT")
            private_device = private_info.st_dev
            private_inode = private_info.st_ino
            private_mode = stat.S_IMODE(private_info.st_mode)
            private_uid = private_info.st_uid
            if scenario == "path_swap":
                source.write_bytes(b"#!/bin/sh\nexit 91\n")
                os.chmod(source, 0o700)
            ferry = LoopbackFerry(fingerprint)
            port = ferry.start()
            out_f = open(stdout_path, "xb", buffering=0)
            err_f = open(stderr_path, "xb", buffering=0)
            os.chmod(stdout_path, 0o600)
            os.chmod(stderr_path, 0o600)
            env = {"HOME": str(owner), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                "NO_COLOR": "1", "ANTHROPIC_BASE_URL":
                "http://127.0.0.1:%d" % port, "R6_FINGERPRINT": fingerprint,
                "R6_SCENARIO": scenario}
            process = subprocess.Popen(
                [str(private)] + list(SAFE_ARGV), stdin=subprocess.DEVNULL,
                stdout=out_f, stderr=err_f, env=env, shell=False,
                start_new_session=True, close_fds=True)
            starts = 1
            process_token = _token_sha(process.pid)
            pgid = os.getpgid(process.pid)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
            if timed_out:
                group_reaped = self._eradicate(pgid)
            if process.poll() is None:
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    self._eradicate(pgid)
                    process.wait(timeout=1)
            exit_code = process.returncode
            if scenario == "effect_exception":
                raise RuntimeError("INJECTED_EFFECT_EXCEPTION")
        except BaseException as exc:
            boundary_error = type(exc).__name__.upper()
        finally:
            if scenario == "cleanup_stream_exception" and ferry and ferry.admissions:
                cleanup_errors.append("STREAM_CLOSE")
            for stream in (out_f, err_f):
                if stream:
                    try:
                        stream.close()
                    except BaseException:
                        cleanup_errors.append("STREAM_CLOSE")
                        descriptors_closed = False
            try:
                if stderr_path.exists():
                    stderr = stderr_path.read_bytes()
                    child_pid = self._child_pid(stderr)
                    if child_pid > 0:
                        child_token = _token_sha(child_pid)
            except BaseException:
                cleanup_errors.append("CHILD_IDENTITY")
            if process and process.poll() is None:
                try:
                    process.wait(timeout=0.05)
                except BaseException:
                    pass
            if scenario == "cleanup_probe_exception" and ferry and ferry.admissions:
                cleanup_errors.append("PROCESS_PROBE")
            try:
                group_reaped = self._group_gone(pgid)
                if not group_reaped:
                    group_reaped = self._eradicate(pgid)
            except BaseException:
                cleanup_errors.append("PROCESS_PROBE")
                group_reaped = False
            try:
                if child_pid > 0 and _same_process(child_pid, child_token):
                    end = time.monotonic() + 2
                    while time.monotonic() < end and _same_process(child_pid, child_token):
                        time.sleep(0.01)
                child_pid_gone = not _same_process(child_pid, child_token)
                pid_gone = not _same_process(process.pid if process else 0, process_token)
            except BaseException:
                cleanup_errors.append("PID_PROBE")
                child_pid_gone = pid_gone = False
            if ferry:
                if scenario == "cleanup_ferry_exception" and ferry.admissions:
                    cleanup_errors.append("FERRY_CLOSE")
                try:
                    ferry_receipt = ferry.close()
                except BaseException:
                    cleanup_errors.append("FERRY_CLOSE")
                    ferry_receipt = ferry.snapshot(False, True)
            else:
                ferry_receipt = LoopbackFerry(fingerprint).snapshot(True, False)
            try:
                if stdout_path.exists():
                    stdout = stdout_path.read_bytes()
                if stderr_path.exists():
                    stderr = stderr_path.read_bytes()
            except BaseException:
                cleanup_errors.append("CUSTODY_READ")
            if scenario == "cleanup_unlink_exception" and ferry_receipt["admissions"]:
                cleanup_errors.append("PRIVATE_UNLINK")
            try:
                if private:
                    try:
                        private.unlink()
                    except FileNotFoundError:
                        pass
                    removed = not private.exists() and not private.is_symlink()
                if scenario == "path_swap" and source != binary:
                    try:
                        source.unlink()
                    except FileNotFoundError:
                        pass
                    removed = removed and not source.exists() and not source.is_symlink()
            except BaseException:
                cleanup_errors.append("PRIVATE_UNLINK")
                removed = False
            if scenario == "cleanup_fsync_exception" and ferry_receipt["admissions"]:
                cleanup_errors.append("OWNER_FSYNC")
            try:
                directory = os.open(owner, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except BaseException:
                cleanup_errors.append("OWNER_FSYNC")
            if scenario == "cleanup_probe_failure":
                group_reaped = False
                child_pid_gone = False
            admitted = ferry_receipt["admissions"] == 1
            if cleanup_errors:
                boundary_error = ("POST_ADMISSION_CLEANUP_EXCEPTION" if admitted else
                                  "PRE_ADMISSION_CLEANUP_EXCEPTION")
                ferry_receipt["cleanup_exception"] = True

        process_receipt = {
            "provider": PROVIDER, "model": MODEL, "binary_ref": BINARY_REF,
            "binary_descriptor": dict(binary_descriptor), "argv": list(SAFE_ARGV),
            "argv_sha256": sha256_bytes(canonical_bytes(list(SAFE_ARGV))),
            "starts": starts, "exit_code": exit_code, "timed_out": timed_out,
            "binary_sha256": binary_sha, "private_copy_sha256": copy_sha,
            "private_copy_device": private_device, "private_copy_inode": private_inode,
            "private_copy_mode": private_mode, "private_copy_uid": private_uid,
            "process_start_token_sha256": process_token,
            "child_start_token_sha256": child_token, "shell": False,
            "process_group": True, "descriptors_closed": descriptors_closed,
            "pid_gone": pid_gone, "child_pid": child_pid,
            "child_pid_gone": child_pid_gone, "cleanup_probe_after_parent_exit": True,
            "process_group_gone": group_reaped,
            "descendants_reaped": group_reaped and child_pid_gone,
            "cleanup_exception": bool(cleanup_errors),
        }
        custody = {"stdout_bytes": len(stdout), "stdout_sha256": sha256_bytes(stdout),
            "stderr_bytes": len(stderr), "stderr_sha256": sha256_bytes(stderr),
            "owner_private": True, "raw_public": False}
        cleanup = {"process_group_reaped": group_reaped,
            "verified_copy_removed": removed and scenario != "cleanup",
            "listener_closed": ferry_receipt["listener_closed"],
            "descriptors_closed": descriptors_closed,
            "exception_count": len(cleanup_errors)}
        return {"process": process_receipt, "ferry": ferry_receipt,
            "custody": custody, "cleanup": cleanup, "stdout": stdout,
            "boundary_error": boundary_error,
            "post_admission_cleanup_exception":
                ferry_receipt["admissions"] == 1 and bool(cleanup_errors)}
