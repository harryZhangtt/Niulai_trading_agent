from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

_GUEST_AGENT_PATH = Path(__file__).parents[1] / "vm_assets" / "guest_agent.py"
_SPEC = importlib.util.spec_from_file_location("guest_agent_under_test", _GUEST_AGENT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

from guest_agent_under_test import (
    AgentPolicy,
    AllowedCommand,
    CGROUP2_SUPER_MAGIC,
    DelegatedCgroupV2,
    FRAME_CANCEL,
    FRAME_ERROR,
    FRAME_EXIT,
    FRAME_POWEROFF,
    FRAME_PROMPT,
    FRAME_PROMPT_END,
    FRAME_REQUEST,
    FRAME_STDERR,
    FRAME_STDOUT,
    GuestAgent,
    ProtocolError,
    SCHEMA,
    VERSION,
    encode_frame,
    read_frame,
)

NONCE = "0123456789abcdef" * 4


def request(**changes: object) -> bytes:
    body: dict[str, object] = {
        "schema": SCHEMA,
        "version": VERSION,
        "nonce": NONCE,
        "nonce_digest": hashlib.sha256(NONCE.encode()).hexdigest(),
        "request_id": "12345678-1234-4234-8234-123456789abc",
        "request_sha256": "1" * 64,
        "artifact_generation": "2" * 64,
        "action": "run",
        "executable": "python",
        "argv": ["-c", "import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d); sys.stderr.buffer.write(b'err')"],
        "env": {},
        "timeout_ms": 2000,
        "strict_containment": False,
    }
    body.update(changes)
    return json.dumps(body, separators=(",", ":")).encode()


ECHO_ARGV = (
    "-c",
    "import sys; d=sys.stdin.buffer.read(); sys.stdout.buffer.write(d); sys.stderr.buffer.write(b'err')",
)
SLEEP_ARGV = ("-c", "import time; time.sleep(30)")
OUTPUT_ARGV = ("-c", "import sys; sys.stdout.buffer.write(b'x'*100000)")
EXIT1_ARGV = ("-c", "raise SystemExit(1)")
SIGNAL_ARGV = ("-c", "import os,signal; os.kill(os.getpid(), signal.SIGTERM)")
ENV_ARGV = ("-c", "import os,sys; sys.stdout.write(os.environ['SAFE'])")
DOUBLE_FORK_ARGV = (
    "-c",
    "import os,time; p=os.fork(); (os.fork() if p==0 else None); time.sleep(30)",
)


def policy(**changes: object) -> AgentPolicy:
    values: dict[str, object] = {
        "commands": {
            "python": AllowedCommand(
                path=sys.executable,
                argv=frozenset({ECHO_ARGV, SLEEP_ARGV, OUTPUT_ARGV, EXIT1_ARGV, SIGNAL_ARGV,
                                ENV_ARGV, DOUBLE_FORK_ARGV}),
            )
        },
        "env_keys": frozenset({"SAFE"}),
        "max_frame_bytes": 65536,
        "output_frame_bytes": 4096,
        "terminate_grace_seconds": 0.1,
    }
    values.update(changes)
    return AgentPolicy(**values)  # type: ignore[arg-type]


def collect(peer: socket.socket) -> list[tuple[int, bytes]]:
    frames: list[tuple[int, bytes]] = []
    while True:
        kind, payload = read_frame(peer, 65536)
        frames.append((kind, payload))
        if kind in (FRAME_ERROR, FRAME_POWEROFF):
            return frames


def transact(agent: GuestAgent, frames: list[bytes]) -> list[tuple[int, bytes]]:
    server, peer = socket.socketpair()
    thread = threading.Thread(target=agent.serve_once, args=(server,))
    thread.start()
    try:
        peer.sendall(b"".join(frames))
        result = collect(peer)
    finally:
        peer.close()
        server.close()
        thread.join(3)
    assert not thread.is_alive()
    return result


class FakeContainment:
    def __init__(self, available: bool = True):
        self.is_available = available
        self.pid: int | None = None
        self.killed = False

    def available(self) -> bool:
        return self.is_available

    def attach(self, pid: int) -> None:
        self.pid = pid

    def kill_all(self) -> None:
        self.killed = True

    def empty(self) -> bool:
        return self.killed or self.pid is None


class FramingTests(unittest.TestCase):
    def test_truncated_frame(self) -> None:
        left, right = socket.socketpair()
        right.sendall(struct.pack(">IB", 5, FRAME_REQUEST) + b"xx")
        right.close()
        with self.assertRaisesRegex(ProtocolError, "truncated_frame"):
            read_frame(left, 100)
        left.close()

    def test_oversize_frame_rejected_before_payload(self) -> None:
        left, right = socket.socketpair()
        right.sendall(struct.pack(">IB", 101, FRAME_REQUEST))
        with self.assertRaisesRegex(ProtocolError, "frame_too_large"):
            read_frame(left, 100)
        left.close()
        right.close()

    def test_duplicate_json_key_has_fixed_error(self) -> None:
        raw = (
            b'{"schema":"' + SCHEMA.encode() + b'","version":1,"nonce":"' + NONCE.encode()
            + b'","action":"shutdown","action":"shutdown"}'
        )
        frames = transact(GuestAgent(policy()), [encode_frame(FRAME_REQUEST, raw)])
        self.assertEqual(frames[0][0], FRAME_ERROR)
        self.assertEqual(json.loads(frames[0][1])["error"], "duplicate_key")

    def test_schema_is_exact_and_unknown_keys_fail(self) -> None:
        frames = transact(
            GuestAgent(policy()),
            [encode_frame(FRAME_REQUEST, request(extra="no"))],
        )
        self.assertEqual(json.loads(frames[0][1])["error"], "invalid_request")


class ExecutionTests(unittest.TestCase):
    def test_prompt_is_streamed_only_to_stdin_and_outputs_are_separate(self) -> None:
        secret = b"prompt-secret-not-metadata"
        frames = transact(
            GuestAgent(policy()),
            [
                encode_frame(FRAME_REQUEST, request()),
                encode_frame(FRAME_PROMPT, secret[:8]),
                encode_frame(FRAME_PROMPT, secret[8:]),
                encode_frame(FRAME_PROMPT_END),
            ],
        )
        stdout = b"".join(payload for kind, payload in frames if kind == FRAME_STDOUT)
        stderr = b"".join(payload for kind, payload in frames if kind == FRAME_STDERR)
        self.assertEqual(stdout, secret)
        self.assertEqual(stderr, b"err")
        metadata = b"".join(payload for kind, payload in frames if kind in (FRAME_EXIT, FRAME_POWEROFF))
        self.assertNotIn(secret, metadata)
        exit_data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
        self.assertEqual(exit_data["reason"], "exit")
        self.assertEqual(exit_data["returncode"], 0)
        self.assertEqual(frames[-1][0], FRAME_POWEROFF)

    def test_environment_requires_key_allowlist_and_diagnostic_has_no_value(self) -> None:
        secret = "credential-value-must-not-leak"
        frames = transact(
            GuestAgent(policy()),
            [
                encode_frame(FRAME_REQUEST, request(argv=list(ENV_ARGV), env={"TOKEN": secret})),
                encode_frame(FRAME_PROMPT_END),
            ],
        )
        self.assertEqual(json.loads(frames[0][1])["error"], "environment_not_allowed")
        self.assertNotIn(secret.encode(), frames[0][1])

    def test_argv_is_exactly_allowlisted_and_never_shell_interpreted(self) -> None:
        marker = tempfile.mktemp(prefix="guest-agent-marker-")
        try:
            frames = transact(
                GuestAgent(policy()),
                [
                    encode_frame(
                        FRAME_REQUEST,
                        request(argv=["-c", "pass", ";touch", marker]),
                    )
                ],
            )
            self.assertEqual(json.loads(frames[0][1])["error"], "arguments_not_allowed")
            self.assertFalse(Path(marker).exists())
        finally:
            Path(marker).unlink(missing_ok=True)

    def test_timeout_kills_reaps_process_and_reports_metadata(self) -> None:
        children: list[subprocess.Popen[bytes]] = []

        def recording_popen(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
            child = subprocess.Popen(*args, **kwargs)  # type: ignore[arg-type]
            children.append(child)
            return child

        frames = transact(
            GuestAgent(policy(), popen=recording_popen),
            [
                encode_frame(FRAME_REQUEST, request(argv=list(SLEEP_ARGV), timeout_ms=50)),
                encode_frame(FRAME_PROMPT_END),
            ],
        )
        data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
        self.assertEqual(data["reason"], "timeout")
        self.assertTrue(data["timed_out"])
        self.assertEqual(len(children), 1)
        self.assertIsNotNone(children[0].poll())

    def test_cancel_kills_process(self) -> None:
        frames = transact(
            GuestAgent(policy()),
            [
                encode_frame(FRAME_REQUEST, request(argv=list(SLEEP_ARGV))),
                encode_frame(FRAME_PROMPT_END),
                encode_frame(FRAME_CANCEL),
            ],
        )
        data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
        self.assertEqual(data["reason"], "cancelled")
        self.assertTrue(data["cancelled"])

    def test_cancel_interrupts_blocked_child_stdin_write(self) -> None:
        frames = transact(
            GuestAgent(policy(max_prompt_bytes=131072)),
            [encode_frame(FRAME_REQUEST, request(argv=list(SLEEP_ARGV), timeout_ms=2000)),
             encode_frame(FRAME_PROMPT, b"x" * 65536), encode_frame(FRAME_CANCEL)],
        )
        data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
        self.assertEqual(data["reason"], "cancelled")
        self.assertTrue(data["cancelled"])

    def test_nonzero_and_signal_exit_metadata_are_preserved(self) -> None:
        for argv, code, sig in ((EXIT1_ARGV, 1, None), (SIGNAL_ARGV, -15, 15)):
            with self.subTest(argv=argv):
                frames = transact(GuestAgent(policy()), [
                    encode_frame(FRAME_REQUEST, request(argv=list(argv))),
                    encode_frame(FRAME_PROMPT_END)])
                data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
                self.assertEqual(data["returncode"], code)
                self.assertEqual(data["signal"], sig)
                self.assertNotEqual(data["returncode"], 0)

    def test_output_limit_stops_child_and_bounds_frames(self) -> None:
        maximum = 8192
        frames = transact(
            GuestAgent(policy(max_output_bytes=maximum)),
            [
                encode_frame(FRAME_REQUEST, request(argv=list(OUTPUT_ARGV))),
                encode_frame(FRAME_PROMPT_END),
            ],
        )
        self.assertTrue(all(len(payload) <= 4096 for kind, payload in frames if kind in (FRAME_STDOUT, FRAME_STDERR)))
        self.assertLessEqual(sum(len(payload) for kind, payload in frames if kind in (FRAME_STDOUT, FRAME_STDERR)), maximum)
        data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
        self.assertEqual(data["reason"], "output_limit")

    def test_prompt_limit_kills_started_child_and_returns_fixed_error(self) -> None:
        frames = transact(
            GuestAgent(policy(max_prompt_bytes=3)),
            [encode_frame(FRAME_REQUEST, request()), encode_frame(FRAME_PROMPT, b"four")],
        )
        self.assertEqual(json.loads(frames[0][1])["error"], "prompt_too_large")


class ContainmentTests(unittest.TestCase):
    def test_all_process_reaping_is_deadline_bounded(self) -> None:
        source = _GUEST_AGENT_PATH.read_text()
        self.assertNotIn("process.wait(", source)
        self.assertIn("process_reap_timeout", source)
        self.assertIn("_bounded_wait", source)


    def test_cgroup2_rejects_wrong_filesystem_magic(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            for name in ("cgroup.controllers", "cgroup.procs", "cgroup.kill"):
                Path(folder, name).write_text("")
            self.assertFalse(DelegatedCgroupV2(folder, fstatfs_magic=lambda _fd: 0).available())
            self.assertTrue(DelegatedCgroupV2(
                folder, fstatfs_magic=lambda _fd: CGROUP2_SUPER_MAGIC).available())

    def test_stalled_prompt_frame_obeys_absolute_deadline(self) -> None:
        server, peer = socket.socketpair()
        thread = threading.Thread(target=GuestAgent(policy()).serve_once, args=(server,))
        thread.start()
        try:
            peer.sendall(encode_frame(FRAME_REQUEST, request(argv=list(SLEEP_ARGV), timeout_ms=50)))
            peer.sendall(struct.pack(">IB", 100, FRAME_PROMPT) + b"partial")
            frames = collect(peer)
            data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
            self.assertEqual(data["reason"], "timeout")
        finally:
            peer.close(); server.close(); thread.join(2)
        self.assertFalse(thread.is_alive())

    def test_strict_mode_fails_before_spawn_without_delegated_cgroup(self) -> None:
        called = False

        def forbidden_popen(*args: object, **kwargs: object):
            nonlocal called
            called = True
            raise AssertionError("must not spawn")

        agent = GuestAgent(policy(), popen=forbidden_popen)  # type: ignore[arg-type]
        frames = transact(
            agent,
            [encode_frame(FRAME_REQUEST, request(strict_containment=True))],
        )
        self.assertEqual(json.loads(frames[0][1])["error"], "strict_containment_unavailable")
        self.assertFalse(called)

    @unittest.skipUnless(hasattr(os, "fork"), "requires fork")
    def test_injected_containment_cleans_double_fork_fixture(self) -> None:
        controller = FakeContainment()
        frames = transact(
            GuestAgent(policy(), containment=controller),
            [
                encode_frame(
                    FRAME_REQUEST,
                    request(argv=list(DOUBLE_FORK_ARGV), timeout_ms=50, strict_containment=True),
                ),
                encode_frame(FRAME_PROMPT_END),
            ],
        )
        data = json.loads(next(payload for kind, payload in frames if kind == FRAME_EXIT))
        self.assertEqual(data["reason"], "timeout")
        self.assertIsNotNone(controller.pid)
        self.assertTrue(controller.killed)

    def test_shutdown_emits_poweroff_marker(self) -> None:
        called: list[bool] = []
        shutdown = json.dumps(
            {"schema": SCHEMA, "version": VERSION, "nonce": NONCE, "action": "shutdown"},
            separators=(",", ":"),
        ).encode()
        frames = transact(
            GuestAgent(policy(), poweroff=lambda: called.append(True)),
            [encode_frame(FRAME_REQUEST, shutdown)],
        )
        self.assertEqual(frames[0][0], FRAME_POWEROFF)
        self.assertTrue(json.loads(frames[0][1])["requested"])
        self.assertEqual(called, [True])


if __name__ == "__main__":
    unittest.main()
