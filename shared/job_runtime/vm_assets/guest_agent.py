"""Source-only Linux guest command agent with a bounded framed protocol.

The host supplies an already-connected binary stream.  This module does not open
network listeners, configure mounts, or discover credentials.  Commands and
arguments must be admitted by an explicit :class:`AgentPolicy`.
"""

from __future__ import annotations

import contextlib
import ctypes
import json
import os
import queue
import re
import select
import selectors
import signal
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Callable, Mapping, Protocol, Sequence

SCHEMA = "trading-agent.guest-exec"
VERSION = 1
_HEADER = struct.Struct(">IB")

FRAME_REQUEST = 1
FRAME_PROMPT = 2
FRAME_PROMPT_END = 3
FRAME_CANCEL = 4
FRAME_STDOUT = 16
FRAME_STDERR = 17
FRAME_EXIT = 18
FRAME_ERROR = 19
FRAME_POWEROFF = 20

_NONCE = re.compile(r"[0-9a-f]{64}\Z")
_RUN_KEYS = frozenset(
    {"schema", "version", "nonce", "nonce_digest", "request_id", "request_sha256",
     "artifact_generation", "action", "executable", "argv", "env", "timeout_ms", "strict_containment"}
)
_SHUTDOWN_KEYS = frozenset({"schema", "version", "nonce", "action"})


class ProtocolError(Exception):
    """A protocol failure carrying only a stable, non-sensitive wire code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _Stream:
    def __init__(self, stream: BinaryIO | socket.socket):
        self.stream = stream
        self._write_lock = threading.Lock()

    def read(self, size: int) -> bytes:
        if hasattr(self.stream, "recv"):
            return self.stream.recv(size)  # type: ignore[union-attr]
        return self.stream.read(size)  # type: ignore[union-attr]

    def write_all(self, data: bytes) -> None:
        with self._write_lock:
            if hasattr(self.stream, "sendall"):
                self.stream.sendall(data)  # type: ignore[union-attr]
                return
            self.stream.write(data)  # type: ignore[union-attr]
            flush = getattr(self.stream, "flush", None)
            if flush is not None:
                flush()

    def fileno(self) -> int | None:
        try:
            return self.stream.fileno()  # type: ignore[union-attr]
        except (AttributeError, OSError):
            return None


def _read_exact(stream: _Stream, size: int, deadline: float | None = None) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    descriptor = stream.fileno()
    while remaining:
        if deadline is not None:
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise ProtocolError("frame_timeout")
            if descriptor is not None:
                readable, _, _ = select.select([descriptor], [], [], wait)
                if not readable:
                    raise ProtocolError("frame_timeout")
        chunk = stream.read(remaining)
        if not chunk:
            raise ProtocolError("truncated_frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO | socket.socket | _Stream, max_payload: int,
               deadline: float | None = None) -> tuple[int, bytes]:
    wrapped = stream if isinstance(stream, _Stream) else _Stream(stream)
    header = _read_exact(wrapped, _HEADER.size, deadline)
    length, kind = _HEADER.unpack(header)
    if length > max_payload:
        raise ProtocolError("frame_too_large")
    return kind, _read_exact(wrapped, length, deadline)


def encode_frame(kind: int, payload: bytes = b"") -> bytes:
    if not isinstance(payload, bytes):
        raise TypeError("payload must be bytes")
    return _HEADER.pack(len(payload), kind) + payload


def write_frame(stream: BinaryIO | socket.socket | _Stream, kind: int, payload: bytes = b"") -> None:
    wrapped = stream if isinstance(stream, _Stream) else _Stream(stream)
    wrapped.write_all(encode_frame(kind, payload))


def _json_no_duplicates(payload: bytes) -> object:
    def object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolError("duplicate_key")
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8")
        return json.loads(text, object_pairs_hook=object_pairs)
    except ProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProtocolError("invalid_request") from None


def _wire_json(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


@dataclass(frozen=True)
class AllowedCommand:
    """One executable and the complete argv vectors it may receive."""

    path: str
    argv: frozenset[tuple[str, ...]]

    def __post_init__(self) -> None:
        if not os.path.isabs(self.path):
            raise ValueError("allowed executable path must be absolute")
        if not self.argv:
            raise ValueError("at least one argv vector must be allowed")


@dataclass(frozen=True)
class AgentPolicy:
    commands: Mapping[str, AllowedCommand]
    env_keys: frozenset[str] = frozenset()
    max_frame_bytes: int = 64 * 1024
    max_prompt_bytes: int = 8 * 1024 * 1024
    max_output_bytes: int = 8 * 1024 * 1024
    output_frame_bytes: int = 32 * 1024
    max_timeout_ms: int = 10 * 60 * 1000
    terminate_grace_seconds: float = 0.5

    def __post_init__(self) -> None:
        limits = (self.max_frame_bytes, self.max_prompt_bytes, self.max_output_bytes, self.output_frame_bytes)
        if any(not isinstance(value, int) or value <= 0 for value in limits):
            raise ValueError("byte limits must be positive integers")
        if self.output_frame_bytes > self.max_frame_bytes:
            raise ValueError("output frame limit exceeds protocol frame limit")


class ContainmentController(Protocol):
    """Injected delegated cgroup controller; implementations own their cgroup."""

    def available(self) -> bool: ...
    def attach(self, pid: int) -> None: ...
    def kill_all(self) -> None: ...
    def empty(self) -> bool: ...


CGROUP2_SUPER_MAGIC = 0x63677270


def _fstatfs_magic(descriptor: int) -> int:
    buffer = ctypes.create_string_buffer(256)
    function = ctypes.CDLL(None, use_errno=True).fstatfs
    if function(descriptor, ctypes.byref(buffer)) != 0:
        raise OSError(ctypes.get_errno(), "fstatfs")
    return ctypes.c_long.from_buffer(buffer).value


class DelegatedCgroupV2:
    """Race-safe adapter for an already-delegated cgroup-v2 directory."""

    def __init__(self, path: str, *, fstatfs_magic: Callable[[int], int] = _fstatfs_magic):
        self.path = Path(path)
        self._fstatfs_magic = fstatfs_magic

    def _directory(self) -> int:
        return os.open(self.path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) |
                       getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))

    @staticmethod
    def _open(directory: int, name: str, flags: int) -> int:
        return os.open(name, flags | getattr(os, "O_NOFOLLOW", 0) |
                       getattr(os, "O_CLOEXEC", 0), dir_fd=directory)

    def available(self) -> bool:
        try:
            directory = self._directory()
            try:
                if self._fstatfs_magic(directory) != CGROUP2_SUPER_MAGIC:
                    return False
                # Required files are opened through the same held cgroup2 dirfd.
                fds = [self._open(directory, name, os.O_RDONLY if name == "cgroup.controllers" else os.O_WRONLY)
                       for name in ("cgroup.controllers", "cgroup.procs", "cgroup.kill")]
                for descriptor in fds: os.close(descriptor)
                return True
            finally:
                os.close(directory)
        except OSError:
            return False

    def attach(self, pid: int) -> None:
        directory = self._directory()
        try:
            descriptor = self._open(directory, "cgroup.procs", os.O_RDWR)
            try:
                os.write(descriptor, str(pid).encode("ascii"))
                os.lseek(descriptor, 0, os.SEEK_SET)
                members = {int(item) for item in os.read(descriptor, 1_048_576).split()}
                if pid not in members:
                    raise OSError("cgroup_membership_unconfirmed")
            finally:
                os.close(descriptor)
        finally:
            os.close(directory)

    def kill_all(self) -> None:
        directory = self._directory()
        try:
            descriptor = self._open(directory, "cgroup.kill", os.O_WRONLY)
            try: os.write(descriptor, b"1")
            finally: os.close(descriptor)
        finally:
            os.close(directory)

    def empty(self) -> bool:
        try:
            directory = self._directory()
            try:
                descriptor = self._open(directory, "cgroup.procs", os.O_RDONLY)
                try: return not os.read(descriptor, 1_048_576).strip()
                finally: os.close(descriptor)
            finally:
                os.close(directory)
        except OSError:
            return False


@dataclass(frozen=True)
class _Request:
    nonce: str
    nonce_digest: str
    request_id: str
    request_sha256: str
    artifact_generation: str
    executable: str
    argv: tuple[str, ...]
    env: dict[str, str]
    timeout_ms: int
    strict_containment: bool


def _validate_common(data: object) -> dict[str, object]:
    if not isinstance(data, dict):
        raise ProtocolError("invalid_request")
    if data.get("schema") != SCHEMA or data.get("version") != VERSION:
        raise ProtocolError("unsupported_protocol")
    nonce = data.get("nonce")
    if not isinstance(nonce, str) or _NONCE.fullmatch(nonce) is None:
        raise ProtocolError("invalid_nonce")
    return data


def _parse_request(payload: bytes, policy: AgentPolicy) -> _Request | tuple[str, str]:
    data = _validate_common(_json_no_duplicates(payload))
    action = data.get("action")
    if action == "shutdown":
        if frozenset(data) != _SHUTDOWN_KEYS:
            raise ProtocolError("invalid_request")
        return ("shutdown", data["nonce"])  # type: ignore[return-value]
    if action != "run" or frozenset(data) != _RUN_KEYS:
        raise ProtocolError("invalid_request")

    executable = data.get("executable")
    bindings = [data.get(key) for key in ("nonce_digest", "request_sha256", "artifact_generation")]
    request_id = data.get("request_id")
    if (not all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) for value in bindings)
            or not isinstance(request_id, str)
            or re.fullmatch(r"[0-9a-f-]{36}", request_id) is None):
        raise ProtocolError("invalid_binding")
    argv = data.get("argv")
    env = data.get("env")
    timeout_ms = data.get("timeout_ms")
    strict = data.get("strict_containment")
    if not isinstance(executable, str) or executable not in policy.commands:
        raise ProtocolError("command_not_allowed")
    if (
        not isinstance(argv, list)
        or not all(isinstance(item, str) and "\x00" not in item for item in argv)
        or tuple(argv) not in policy.commands[executable].argv
    ):
        raise ProtocolError("arguments_not_allowed")
    if not isinstance(env, dict) or not all(
        isinstance(key, str)
        and isinstance(value, str)
        and key in policy.env_keys
        and "\x00" not in key
        and "=" not in key
        and "\x00" not in value
        for key, value in env.items()
    ):
        raise ProtocolError("environment_not_allowed")
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= policy.max_timeout_ms:
        raise ProtocolError("invalid_timeout")
    if type(strict) is not bool:
        raise ProtocolError("invalid_request")
    return _Request(
        nonce=data["nonce"],  # type: ignore[arg-type]
        nonce_digest=bindings[0],  # type: ignore[arg-type]
        request_id=request_id,
        request_sha256=bindings[1],  # type: ignore[arg-type]
        artifact_generation=bindings[2],  # type: ignore[arg-type]
        executable=executable,
        argv=tuple(argv),
        env=dict(env),
        timeout_ms=timeout_ms,
        strict_containment=strict,
    )


def _proc_descendants(root_pid: int) -> set[int]:
    """Best-effort Linux /proc descendant snapshot for non-strict cleanup."""
    if not Path("/proc").is_dir():
        return set()
    parents: dict[int, int] = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return set()
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            fields = (entry / "stat").read_text(encoding="ascii", errors="replace").split()
            parents[int(entry.name)] = int(fields[3])
        except (OSError, ValueError, IndexError):
            continue
    descendants: set[int] = set()
    frontier = {root_pid}
    while frontier:
        children = {pid for pid, parent in parents.items() if parent in frontier and pid not in descendants}
        descendants.update(children)
        frontier = children
    return descendants


def _bounded_wait(process: subprocess.Popen[bytes], deadline: float) -> int:
    while time.monotonic() < deadline:
        value = process.poll()
        if value is not None:
            return value
        time.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    raise ProtocolError("process_reap_timeout")


def _terminate_and_reap(process: subprocess.Popen[bytes], controller: ContainmentController | None,
                        grace: float) -> int:
    _signal_tree(process, signal.SIGTERM, controller)
    try:
        return _bounded_wait(process, time.monotonic() + grace)
    except ProtocolError:
        _signal_tree(process, signal.SIGKILL, controller)
        return _bounded_wait(process, time.monotonic() + grace)


def _signal_tree(process: subprocess.Popen[bytes], sig: int, controller: ContainmentController | None) -> None:
    if controller is not None:
        try:
            controller.kill_all()
        except OSError:
            pass
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    for pid in _proc_descendants(process.pid):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


@dataclass
class GuestAgent:
    policy: AgentPolicy
    containment: ContainmentController | None = None
    poweroff: Callable[[], None] | None = None
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen
    _active_lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def _send_error(self, stream: _Stream, code: str, nonce: str | None = None) -> None:
        body: dict[str, object] = {"schema": SCHEMA, "version": VERSION, "error": code}
        if nonce is not None:
            body["nonce"] = nonce
        stream.write_all(encode_frame(FRAME_ERROR, _wire_json(body)))

    def serve_once(self, supplied_stream: BinaryIO | socket.socket) -> bool:
        """Serve one request.  Return False after a shutdown request."""
        stream = _Stream(supplied_stream)
        nonce: str | None = None
        try:
            kind, payload = read_frame(stream, self.policy.max_frame_bytes)
            if kind != FRAME_REQUEST:
                raise ProtocolError("expected_request")
            request = _parse_request(payload, self.policy)
            if isinstance(request, tuple):
                nonce = request[1]
                self._poweroff_marker(stream, nonce, "shutdown")
                return False
            nonce = request.nonce
            self._run(stream, request)
            return False
        except ProtocolError as exc:
            self._send_error(stream, exc.code, nonce)
            return True
        except (BrokenPipeError, ConnectionError, OSError):
            return True

    def _poweroff_marker(self, stream: _Stream, nonce: str, reason: str,
                         request: _Request | None = None) -> None:
        body: dict[str, object] = {"schema": SCHEMA, "version": VERSION, "nonce": nonce,
                                  "requested": True, "reason": reason}
        if request is not None:
            body.update({"nonce_digest": request.nonce_digest, "request_id": request.request_id,
                         "request_sha256": request.request_sha256,
                         "artifact_generation": request.artifact_generation})
        stream.write_all(encode_frame(FRAME_POWEROFF, _wire_json(body)))
        if self.poweroff is not None:
            try:
                self.poweroff()
            except Exception:
                pass

    def _run(self, stream: _Stream, request: _Request) -> None:
        controller = self.containment
        if request.strict_containment and (controller is None or not controller.available()):
            raise ProtocolError("strict_containment_unavailable")
        if not self._active_lock.acquire(blocking=False):
            raise ProtocolError("busy")

        process: subprocess.Popen[bytes] | None = None
        reason = "exit"
        output_total = 0
        prompt_total = 0
        started = time.monotonic()
        queue_frames = self.policy.max_output_bytes // self.policy.output_frame_bytes + 3
        events: queue.Queue[tuple[int, bytes | None]] = queue.Queue(maxsize=queue_frames)
        control: queue.Queue[str] = queue.Queue(maxsize=1)
        readers: list[threading.Thread] = []
        try:
            command = self.policy.commands[request.executable]
            preexec_fn: Callable[[], None] | None = None
            if request.strict_containment:
                assert controller is not None

                def attach_before_exec() -> None:
                    controller.attach(os.getpid())

                preexec_fn = attach_before_exec
            try:
                process = self.popen(
                    [command.path, *request.argv],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=request.env,
                    start_new_session=True,
                    preexec_fn=preexec_fn,
                )
            except (OSError, ValueError, subprocess.SubprocessError):
                raise ProtocolError("spawn_failed") from None

            # Parent-side attachment is idempotent for cgroup.procs and closes the
            # non-strict race; strict mode was already attached before exec.
            if controller is not None:
                try:
                    controller.attach(process.pid)
                except OSError:
                    _signal_tree(process, signal.SIGKILL, controller)
                    _bounded_wait(process, time.monotonic() + self.policy.terminate_grace_seconds)
                    raise ProtocolError("containment_attach_failed") from None

            assert process.stdin is not None and process.stdout is not None and process.stderr is not None
            deadline = started + request.timeout_ms / 1000.0
            stdin_fd = process.stdin.fileno()
            stream_fd = stream.fileno()
            os.set_blocking(stdin_fd, False)
            pending_frames: list[tuple[int, bytes]] = []
            while True:
                try:
                    if pending_frames:
                        kind, payload = pending_frames.pop(0)
                    else:
                        kind, payload = read_frame(stream, self.policy.max_frame_bytes, deadline)
                except ProtocolError as error:
                    if error.code == "frame_timeout":
                        reason = "timeout"
                        break
                    raise
                if kind == FRAME_PROMPT:
                    prompt_total += len(payload)
                    if prompt_total > self.policy.max_prompt_bytes:
                        raise ProtocolError("prompt_too_large")
                    view = memoryview(payload)
                    while view:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            reason = "timeout"
                            break
                        readable = [stream_fd] if stream_fd is not None else []
                        ready_read, ready_write, _ = select.select(readable, [stdin_fd], [], remaining)
                        if stream_fd is not None and stream_fd in ready_read:
                            control_kind, control_payload = read_frame(
                                stream, self.policy.max_frame_bytes, deadline)
                            if control_kind == FRAME_CANCEL and not control_payload:
                                reason = "cancelled"
                                break
                            if control_kind in (FRAME_PROMPT, FRAME_PROMPT_END):
                                pending_frames.append((control_kind, control_payload))
                                continue
                            raise ProtocolError("unexpected_frame")
                        if stdin_fd in ready_write:
                            try:
                                written = os.write(stdin_fd, view)
                                view = view[written:]
                            except BlockingIOError:
                                continue
                            except BrokenPipeError:
                                view = view[len(view):]
                    if reason != "exit":
                        break
                elif kind == FRAME_PROMPT_END:
                    if payload:
                        raise ProtocolError("invalid_prompt_end")
                    process.stdin.close()
                    break
                elif kind == FRAME_CANCEL and not payload:
                    process.stdin.close()
                    reason = "cancelled"
                    break
                else:
                    raise ProtocolError("unexpected_frame")

            def collect(kind: int, pipe: BinaryIO) -> None:
                try:
                    while True:
                        chunk = pipe.read(self.policy.output_frame_bytes)
                        if not chunk:
                            break
                        events.put((kind, chunk))
                finally:
                    events.put((kind, None))

            readers.extend(
                [
                    threading.Thread(target=collect, args=(FRAME_STDOUT, process.stdout), daemon=True),
                    threading.Thread(target=collect, args=(FRAME_STDERR, process.stderr), daemon=True),
                ]
            )
            for reader in readers:
                reader.start()

            control_thread: threading.Thread | None = None
            fd = stream.fileno()
            if fd is not None and reason != "cancelled":
                def watch_control() -> None:
                    try:
                        kind, payload = read_frame(stream, self.policy.max_frame_bytes)
                        control.put("cancel" if kind == FRAME_CANCEL and not payload else "protocol")
                    except ProtocolError:
                        control.put("protocol")
                    except (OSError, ConnectionError):
                        control.put("disconnect")

                control_thread = threading.Thread(target=watch_control, daemon=True)
                control_thread.start()

            closed = 0
            while closed < 2 or process.poll() is None:
                now = time.monotonic()
                if reason == "cancelled":
                    break
                if now >= deadline:
                    reason = "timeout"
                    break
                try:
                    message = control.get_nowait()
                    reason = "cancelled" if message == "cancel" else "protocol_error"
                    break
                except queue.Empty:
                    pass
                try:
                    kind, chunk = events.get(timeout=min(0.05, max(0.001, deadline - now)))
                except queue.Empty:
                    continue
                if chunk is None:
                    closed += 1
                    continue
                output_total += len(chunk)
                if output_total > self.policy.max_output_bytes:
                    reason = "output_limit"
                    break
                stream.write_all(encode_frame(kind, chunk))

            if reason != "exit":
                returncode = _terminate_and_reap(
                    process, controller, self.policy.terminate_grace_seconds)
            else:
                current = process.poll()
                returncode = current if current is not None else _bounded_wait(
                    process, time.monotonic() + self.policy.terminate_grace_seconds)

            # Every post-kill drain is bounded by one absolute deadline. Missing
            # reader closure becomes a visible drain timeout, never a hang.
            drain_deadline = time.monotonic() + self.policy.terminate_grace_seconds
            while closed < 2 and time.monotonic() < drain_deadline:
                try:
                    kind, chunk = events.get(timeout=max(0.001, drain_deadline - time.monotonic()))
                except queue.Empty:
                    break
                if chunk is None:
                    closed += 1
                elif reason == "exit":
                    output_total += len(chunk)
                    if output_total > self.policy.max_output_bytes:
                        reason = "output_limit"
                    else:
                        stream.write_all(encode_frame(kind, chunk))
            if closed < 2 and reason == "exit":
                reason = "drain_timeout"
            for reader in readers:
                reader.join(timeout=max(0.0, drain_deadline - time.monotonic()))

            if controller is not None and not controller.empty():
                controller.kill_all()
            metadata = {
                "schema": SCHEMA,
                "version": VERSION,
                "nonce": request.nonce,
                "nonce_digest": request.nonce_digest,
                "request_id": request.request_id,
                "request_sha256": request.request_sha256,
                "artifact_generation": request.artifact_generation,
                "reason": reason,
                "returncode": returncode,
                "signal": -returncode if returncode < 0 else None,
                "timed_out": reason == "timeout",
                "cancelled": reason == "cancelled",
                "output_bytes": min(output_total, self.policy.max_output_bytes),
            }
            stream.write_all(encode_frame(FRAME_EXIT, _wire_json(metadata)))
            self._poweroff_marker(stream, request.nonce, "completed", request)
        except ProtocolError:
            if process is not None and process.poll() is None:
                _signal_tree(process, signal.SIGKILL, controller)
                _bounded_wait(process, time.monotonic() + self.policy.terminate_grace_seconds)
            raise
        finally:
            if process is not None and process.poll() is None:
                _signal_tree(process, signal.SIGKILL, controller)
                with contextlib.suppress(ProtocolError):
                    _bounded_wait(process, time.monotonic() + self.policy.terminate_grace_seconds)
            if process is not None:
                for pipe in (process.stdin, process.stdout, process.stderr):
                    if pipe is not None:
                        with contextlib.suppress(OSError, ValueError):
                            pipe.close()
                for reader in readers:
                    reader.join(timeout=self.policy.terminate_grace_seconds)
            if controller is not None:
                try:
                    if not controller.empty():
                        controller.kill_all()
                except OSError:
                    pass
            self._active_lock.release()


def serve(
    supplied_stream: BinaryIO | socket.socket,
    policy: AgentPolicy,
    *,
    containment: ContainmentController | None = None,
    poweroff: Callable[[], None] | None = None,
) -> None:
    """Serve framed requests until a shutdown request or stream failure."""
    agent = GuestAgent(policy=policy, containment=containment, poweroff=poweroff)
    while agent.serve_once(supplied_stream):
        pass
