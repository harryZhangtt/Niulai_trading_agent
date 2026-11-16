"""Bounded anonymous-pipe transport for model subprocesses.

This module owns no prompt custody type.  It consumes an iterator supplied by the
model adapter and returns only bounded in-memory child output plus byte-accounting.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import selectors
import subprocess
import time
from typing import Iterable


@dataclass(frozen=True)
class PipeResult:
    stdout: bytes
    stderr: bytes
    reason: str | None
    source_sha256: str
    source_length: int
    sent_length: int
    source_complete: bool


def pump(process: subprocess.Popen, chunks: Iterable[bytes], *, deadline: float,
         maximum: int, cancel_event, terminate, final_path=None) -> PipeResult:
    """Multiplex chunked stdin/stdout/stderr with bounded memory and cleanup."""
    selector = selectors.DefaultSelector()
    output = bytearray()
    errors = bytearray()
    digest = hashlib.sha256()
    source_length = sent = 0
    source_complete = False
    reason = None
    pending = memoryview(b'')
    iterator = iter(chunks)

    def close(pipe) -> None:
        try:
            selector.unregister(pipe)
        except (KeyError, ValueError):
            pass
        if pipe is not None and not pipe.closed:
            pipe.close()

    def next_chunk() -> None:
        nonlocal pending, source_complete, source_length
        while not pending and not source_complete:
            try:
                value = next(iterator)
            except StopIteration:
                source_complete = True
                return
            if not isinstance(value, (bytes, bytearray, memoryview)):
                raise TypeError('MODEL_PROMPT_CHUNK_INVALID')
            value = bytes(value)
            if not value:
                continue
            if len(value) > 65536 or source_length + len(value) > 512 * 1024:
                raise ValueError('MODEL_PROMPT_CHUNK_INVALID')
            digest.update(value)
            source_length += len(value)
            pending = memoryview(value)

    try:
        for pipe, kind, event in (
                (process.stdin, 'stdin', selectors.EVENT_WRITE),
                (process.stdout, 'stdout', selectors.EVENT_READ),
                (process.stderr, 'stderr', selectors.EVENT_READ)):
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, event, kind)
        next_chunk()
        if source_complete:
            close(process.stdin)
        while selector.get_map():
            if time.monotonic() >= deadline:
                reason = 'MODEL_DEADLINE_EXCEEDED'
            elif cancel_event is not None and cancel_event.is_set():
                reason = 'MODEL_CANCELLED'
            elif final_path is not None:
                try:
                    if os.stat(final_path,follow_symlinks=False).st_size > maximum:
                        reason = 'MODEL_OUTPUT_LIMIT_EXCEEDED'
                except FileNotFoundError:
                    reason = 'MODEL_FINAL_RESPONSE_MISSING'
            if reason:
                terminate(process)
                break
            if process.poll() is not None and process.stdin is not None and not process.stdin.closed:
                reason = 'MODEL_PROMPT_DELIVERY_INCOMPLETE'
                close(process.stdin)
            for key, _ in selector.select(.05):
                if key.data == 'stdin':
                    try:
                        written = os.write(key.fileobj.fileno(), pending[:65536])
                    except BlockingIOError:
                        continue
                    except (BrokenPipeError, ConnectionResetError):
                        reason = 'MODEL_PROMPT_DELIVERY_INCOMPLETE'
                        close(key.fileobj)
                        continue
                    if written <= 0:
                        reason = 'MODEL_PROMPT_DELIVERY_INCOMPLETE'
                        close(key.fileobj)
                        continue
                    sent += written
                    pending = pending[written:]
                    if not pending:
                        next_chunk()
                        if source_complete:
                            close(key.fileobj)
                else:
                    target = output if key.data == 'stdout' else errors
                    allowance = maximum + 1 - len(output) - len(errors)
                    try:
                        chunk = os.read(key.fileobj.fileno(), min(65536, max(1, allowance)))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        close(key.fileobj)
                        continue
                    target.extend(chunk)
                    if len(output) + len(errors) > maximum:
                        reason = 'MODEL_OUTPUT_LIMIT_EXCEEDED'
                        terminate(process)
                        break
            if reason and process.poll() is None:
                terminate(process)
            if reason and process.poll() is not None:
                # Continue draining already-buffered output, but stdin stays closed.
                for registered in list(selector.get_map().values()):
                    if registered.data == 'stdin':
                        close(registered.fileobj)
            if process.poll() is not None and all(
                    registered.data == 'stdin' for registered in selector.get_map().values()):
                break
        if process.poll() is None:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                reason = reason or 'MODEL_DEADLINE_EXCEEDED'
                terminate(process)
        if sent != source_length or not source_complete:
            reason = reason or 'MODEL_PROMPT_DELIVERY_INCOMPLETE'
        return PipeResult(bytes(output), bytes(errors), reason, digest.hexdigest(),
                          source_length, sent, source_complete)
    except BaseException:
        if process.poll() is None:
            terminate(process)
        raise
    finally:
        selector.close()
        for pipe in (process.stdin, process.stdout, process.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()
