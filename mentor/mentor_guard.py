#!/usr/bin/env python3
"""Hash-bound, project-local mentor lifecycle receipt and pre-action gate.

This is an accidental-drift/runtime sequencing boundary, not protection from the
same OS user or a host mode that skips project hooks.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import time

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
LOCK_RELATIVE = Path("mentor/enforcement-lock.json")
SETTINGS_RELATIVE = Path(".claude/settings.json")
STATE_RELATIVE = Path("mentor/runtime/enforcement")
MAX_INPUT = 128 * 1024
MAX_LOCK = 128 * 1024
MAX_SOURCE = 64 * 1024
MAX_RECEIPT = 32 * 1024
MAX_CONTEXT = 12 * 1024
LOCK_WAIT_SECONDS = 0.25
LOCK_RETRY_SECONDS = 0.01
OFFICIAL_SOURCES = {"startup", "resume", "clear", "compact", "fork"}
SKILLS = ("development-discipline", "research-supervisor", "progress-and-recovery",
          "experiment-design", "evidence-and-overfitting", "evaluation-design")
# On receipt failure, preserve only explicitly bounded diagnosis and orchestration.
# Everything else is denied because an unknown tool may mutate state or emit an
# external effect (for example Gmail, MCP, GitHub, or browser tools).
MUTATING_EFFECT_TOOLS = {"Bash", "Edit", "Write", "NotebookEdit"}
DIAGNOSTIC_TOOLS = {"Read", "Glob", "Grep"}
RECOVERY_ORCHESTRATION_TOOLS = {
    "TaskOutput", "TaskStop", "TaskNotification", "SendMessage",
}
DIAGNOSTIC_EXACT = {
    "CLAUDE.md", "AGENTS.md", ".claude/settings.json", "mentor/AGENTS.md",
    "mentor/ROUTING.md", "mentor/mentor_guard.py", "mentor/session_init.py",
    "mentor/enforcement-lock.json",
}
ID = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
SHA = re.compile(r"[a-f0-9]{64}\Z")
RECEIPT_KEYS = {
    "schema_version", "kind", "state", "session_sha256", "transcript_sha256",
    "root_sha256", "root_device", "root_inode", "generation", "lifecycle_event",
    "lifecycle_source", "nonce", "lock_sha256", "policy_sha256", "guard_sha256",
    "config_sha256", "issued_at", "expires_at", "agent_id_sha256", "agent_type",
}


class GuardError(ValueError):
    pass


def require(condition, code):
    if not condition:
        raise GuardError(code)


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False).encode()
    except (TypeError, ValueError, UnicodeError):
        raise GuardError("E_JSON") from None


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def digest(value):
    return digest_bytes(canonical(value))


def loads_strict(raw, maximum=MAX_INPUT):
    if isinstance(raw, str):
        raw = raw.encode()
    require(type(raw) is bytes and 0 < len(raw) <= maximum, "E_INPUT")
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "E_JSON_DUPLICATE")
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _v: (_ for _ in ()).throw(GuardError("E_JSON")))
    except GuardError:
        raise
    except (TypeError, ValueError, UnicodeError):
        raise GuardError("E_JSON") from None
    require(type(value) is dict, "E_INPUT")
    return value


def _sha_text(value, code="E_HASH"):
    require(type(value) is str and SHA.fullmatch(value), code)
    return value


def _safe_relative(value):
    require(type(value) is str and 1 <= len(value) <= 240, "E_PATH")
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts and
            all(part not in {"", "."} for part in path.parts), "E_PATH")
    return path


def _diagnostic_path(root, cwd, value):
    """Return an exact canonical policy path, anchored at the event cwd."""
    if type(value) is not str or not value or type(cwd) is not str or not cwd:
        return None
    try:
        supplied_cwd = Path(cwd)
        if not supplied_cwd.is_absolute():
            return None
        cwd_path = Path(os.path.abspath(supplied_cwd))
        if cwd_path.resolve(strict=True) != cwd_path:
            return None
        cwd_relative = cwd_path.relative_to(root)
        current = root
        for part in cwd_relative.parts:
            current = current / part
            info = current.lstat()
            if (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or
                    info.st_uid != os.getuid()):
                return None
        supplied = Path(value)
        raw_candidate = supplied if supplied.is_absolute() else cwd_path / supplied
        candidate = Path(os.path.abspath(raw_candidate))
        if raw_candidate.resolve(strict=True) != candidate:
            return None
        relative = candidate.relative_to(root)
        text = str(relative)
        if text not in DIAGNOSTIC_EXACT:
            return None
        # Prove unchanged topology without following a symlink at any component.
        current = root
        for index, part in enumerate(relative.parts):
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
                return None
            if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
                return None
            if index == len(relative.parts) - 1 and not stat.S_ISREG(info.st_mode):
                return None
        return text if candidate.resolve(strict=True) == root / relative else None
    except (OSError, ValueError, TypeError):
        return None


def _failure_tool_allowed(event, root):
    """Keep redline orchestration and path-bounded diagnostics available."""
    tool = event.get("tool_name")
    if tool in RECOVERY_ORCHESTRATION_TOOLS:
        return True
    tool_input = event.get("tool_input")
    cwd = event.get("cwd")
    if tool not in DIAGNOSTIC_TOOLS or type(tool_input) is not dict:
        return False
    if tool == "Read":
        return _diagnostic_path(root, cwd, tool_input.get("file_path")) is not None
    if tool == "Grep":
        return _diagnostic_path(root, cwd, tool_input.get("path")) is not None
    # Glob is safe only when both its search root and literal pattern identify one
    # allowlisted file; wildcard scans could expose protected state.
    if tool == "Glob":
        pattern = tool_input.get("pattern")
        search_root = tool_input.get("path", cwd)
        if type(pattern) is not str or any(char in pattern for char in "*?[]{}"):
            return False
        try:
            base = Path(search_root)
            candidate = base / pattern
        except TypeError:
            return False
        return _diagnostic_path(root, cwd, str(candidate)) is not None
    return False


def _safe_read(root, relative, maximum, code):
    relative = _safe_relative(str(relative))
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        try:
            info = current.lstat()
        except OSError:
            raise GuardError(code) from None
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode) and
                info.st_uid == os.getuid(), code)
    target = root / relative
    try:
        descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        raise GuardError(code) from None
    try:
        before = os.fstat(descriptor)
        require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid() and
                not (before.st_mode & (stat.S_IWGRP | stat.S_IWOTH)) and
                0 < before.st_size <= maximum, code)
        chunks, remaining = [], before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            require(chunk, code)
            chunks.append(chunk); remaining -= len(chunk)
        after = os.fstat(descriptor)
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns), code)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _root_identity(root):
    supplied = Path(root).absolute()
    require(supplied.is_dir() and not supplied.is_symlink(), "E_ROOT")
    resolved = supplied.resolve()
    require(resolved == supplied and resolved == SCRIPT_ROOT, "E_ROOT")
    info = resolved.stat()
    require(info.st_uid == os.getuid(), "E_ROOT")
    return resolved, info, digest({"realpath": str(resolved), "device": info.st_dev,
                                  "inode": info.st_ino})


def _cwd_ok(root, event):
    try:
        Path(event["cwd"]).resolve().relative_to(root)
    except (KeyError, OSError, ValueError, TypeError):
        raise GuardError("E_CWD") from None


def _load_lock(root, expected_sha):
    raw = _safe_read(root, LOCK_RELATIVE, MAX_LOCK, "E_LOCK")
    require(digest_bytes(raw) == _sha_text(expected_sha, "E_LOCK"), "E_LOCK")
    value = loads_strict(raw, MAX_LOCK)
    expected = {"schema_version", "kind", "guard_version", "receipt_ttl_seconds",
                "context_paths", "files"}
    require(set(value) == expected and value["schema_version"] == 1 and
            value["kind"] == "mentor_enforcement_lock" and
            type(value["guard_version"]) is str and
            type(value["receipt_ttl_seconds"]) is int and
            60 <= value["receipt_ttl_seconds"] <= 172800 and
            type(value["context_paths"]) is list and
            type(value["files"]) is list and value["files"], "E_LOCK")
    entries, seen = {}, set()
    for item in value["files"]:
        require(type(item) is dict and set(item) == {"path", "sha256", "max_bytes"}, "E_LOCK")
        path = str(_safe_relative(item["path"])); _sha_text(item["sha256"], "E_LOCK")
        require(path not in seen and type(item["max_bytes"]) is int and
                1 <= item["max_bytes"] <= MAX_SOURCE, "E_LOCK")
        seen.add(path); entries[path] = item
    require(value["context_paths"] == ["mentor/AGENTS.md", "mentor/ROUTING.md"] and
            all(path in entries for path in value["context_paths"]) and
            "mentor/mentor_guard.py" in entries, "E_LOCK")
    return value, raw, entries


def _validate_sources(root, lock, entries):
    data, hashes = {}, {}
    for path in sorted(entries):
        raw = _safe_read(root, path, entries[path]["max_bytes"], "E_SOURCE")
        actual = digest_bytes(raw)
        require(actual == entries[path]["sha256"], "E_SOURCE_DRIFT")
        hashes[path] = actual
        if path in lock["context_paths"]:
            try:
                data[path] = raw.decode("utf-8")
            except UnicodeError:
                raise GuardError("E_SOURCE") from None
    require(sum(len(value.encode()) for value in data.values()) <= MAX_CONTEXT, "E_CONTEXT")
    return data, hashes, digest({"files": hashes})


def _settings_sha(root):
    return digest_bytes(_safe_read(root, SETTINGS_RELATIVE, MAX_SOURCE, "E_CONFIG"))


def _state_root(root):
    state = root / STATE_RELATIVE
    try:
        state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        require(state.parent.is_dir() and not state.parent.is_symlink() and
                state.parent.stat().st_uid == os.getuid(), "E_STATE")
        # mkdir is the atomic first-creator boundary; exist_ok makes concurrent
        # first lifecycle events converge without a check-then-create race.
        state.mkdir(mode=0o700, exist_ok=True)
        require(state.is_dir() and not state.is_symlink() and
                state.stat().st_uid == os.getuid(), "E_STATE")
        os.chmod(state, 0o700)
    except GuardError:
        raise
    except OSError:
        raise GuardError("E_STATE") from None
    return state


def _session(event):
    session = event.get("session_id")
    require(type(session) is str and ID.fullmatch(session), "E_SESSION")
    transcript = event.get("transcript_path")
    require(type(transcript) is str and 1 <= len(transcript) <= 4096, "E_SESSION")
    return digest_bytes(session.encode()), digest_bytes(transcript.encode())


def _receipt_path(state, session_sha):
    return state / (session_sha + ".json")


def _reset_exact_nonregular(path):
    """Remove one owner-owned candidate node without following links or recursion."""
    try:
        before = path.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        raise GuardError("E_STATE") from None
    if stat.S_ISREG(before.st_mode):
        return False
    require(before.st_uid == os.getuid() and not stat.S_ISLNK(before.st_mode), "E_STATE")
    quarantine = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.invalid"
    try:
        os.rename(path, quarantine)
        after = quarantine.lstat()
        require((before.st_dev, before.st_ino, before.st_mode, before.st_uid) ==
                (after.st_dev, after.st_ino, after.st_mode, after.st_uid) and
                not stat.S_ISLNK(after.st_mode), "E_STATE_RACE")
        if stat.S_ISDIR(after.st_mode):
            os.rmdir(quarantine)  # Intentionally fails closed for nonempty directories.
        else:
            os.unlink(quarantine)
        return True
    except FileNotFoundError:
        return False
    except GuardError:
        try:
            if os.path.lexists(quarantine) and not os.path.lexists(path):
                os.rename(quarantine, path)
        except OSError:
            pass
        raise
    except OSError:
        # Restore a quarantined node when possible; never recurse or follow it.
        try:
            if os.path.lexists(quarantine) and not os.path.lexists(path):
                os.rename(quarantine, path)
        except OSError:
            pass
        raise GuardError("E_STATE") from None


def _flock_bounded(descriptor):
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except OSError as error:
            if error.errno not in {errno.EACCES, errno.EAGAIN}:
                raise GuardError("E_STATE") from None
            if time.monotonic() >= deadline:
                raise GuardError("E_LOCK_BUSY") from None
            time.sleep(LOCK_RETRY_SECONDS)


@contextmanager
def _session_lock(state, session_sha):
    path = state / (session_sha + ".lock")
    directory = descriptor = None
    try:
        directory = os.open(state, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        directory_info = os.fstat(directory)
        require(stat.S_ISDIR(directory_info.st_mode) and
                directory_info.st_uid == os.getuid(), "E_STATE")
        # Serialize repair of the lock node itself. Release this directory lock
        # only after the regular per-session lock has been acquired.
        _flock_bounded(directory)
        _reset_exact_nonregular(path)
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid(), "E_STATE")
        _flock_bounded(descriptor)
        fcntl.flock(directory, fcntl.LOCK_UN)
        os.close(directory); directory = None
        yield
    except GuardError:
        raise
    except OSError:
        raise GuardError("E_STATE") from None
    finally:
        if directory is not None:
            try: fcntl.flock(directory, fcntl.LOCK_UN); os.close(directory)
            except OSError: pass
        if descriptor is not None:
            try: fcntl.flock(descriptor, fcntl.LOCK_UN); os.close(descriptor)
            except OSError: pass


def _atomic(path, value):
    payload = canonical(value) + b"\n"
    temp = path.parent / f".{path.name}.{os.getpid()}.{secrets.token_hex(8)}.tmp"
    descriptor = None
    try:
        descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view); require(written > 0, "E_WRITE")
            view = view[written:]
        os.fsync(descriptor); os.close(descriptor); descriptor = None
        os.replace(temp, path); os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try: os.fsync(directory)
        finally: os.close(directory)
    except GuardError:
        raise
    except OSError:
        raise GuardError("E_WRITE") from None
    finally:
        if descriptor is not None:
            try: os.close(descriptor)
            except OSError: pass
        try: temp.unlink(missing_ok=True)
        except OSError: pass


def _load_receipt(path):
    value = loads_strict(_safe_read(path.parent.parent.parent, str(path.relative_to(path.parent.parent.parent)),
                                    MAX_RECEIPT, "E_RECEIPT"), MAX_RECEIPT)
    require(set(value) == RECEIPT_KEYS and type(value["schema_version"]) is int and
            value["schema_version"] == 1 and value["kind"] == "mentor_enforcement_receipt" and
            value["state"] in {"ready", "compact_pending", "model_switch_pending", "revoked"} and
            type(value["generation"]) is int and value["generation"] >= 1 and
            type(value["root_device"]) is int and type(value["root_inode"]) is int and
            type(value["lifecycle_event"]) is str and type(value["lifecycle_source"]) is str and
            type(value["issued_at"]) is int and type(value["expires_at"]) is int and
            value["issued_at"] <= value["expires_at"] and
            type(value["nonce"]) is str and SHA.fullmatch(value["nonce"]) and
            (value["agent_id_sha256"] is None or
             type(value["agent_id_sha256"]) is str and SHA.fullmatch(value["agent_id_sha256"])) and
            (value["agent_type"] is None or type(value["agent_type"]) is str and
             ID.fullmatch(value["agent_type"])), "E_RECEIPT")
    for key in ("session_sha256", "transcript_sha256", "root_sha256", "lock_sha256",
                "policy_sha256", "guard_sha256", "config_sha256"):
        _sha_text(value[key], "E_RECEIPT")
    return value


def _lifecycle_source(event, expected_event):
    if expected_event == "SessionStart":
        source = event.get("source")
        require(source in OFFICIAL_SOURCES, "E_SOURCE_EVENT")
        return source
    if expected_event == "PostModelSwitch": return "model-switch"
    if expected_event == "SubagentStart": return "subagent-start"
    raise GuardError("E_EVENT")


def _capsule(lock_sha, policy_sha, generation):
    return (f"MENTOR_GUARD_OK v1 generation={generation} lock={lock_sha[:12]} "
            f"policy={policy_sha[:12]}. Preserve accepted deliverables; distinguish facts, "
            "assumptions and unverified claims; require evidence for completion; keep protected "
            "data protected; distinguish source quality from demonstrated investment alpha.")


def lifecycle(event, expected_event, expected_lock_sha, root):
    require(event.get("hook_event_name") == expected_event, "E_EVENT")
    root, info, root_sha = _root_identity(root); _cwd_ok(root, event)
    session_sha, transcript_sha = _session(event)
    lock, _raw, entries = _load_lock(root, expected_lock_sha)
    contexts, hashes, policy_sha = _validate_sources(root, lock, entries)
    config_sha = _settings_sha(root)
    state = _state_root(root); path = _receipt_path(state, session_sha)
    with _session_lock(state, session_sha):
        # A lifecycle event is the recovery authority for its own receipt. Keep a
        # valid generation monotonic; if an existing receipt is unreadable or
        # schema-incompatible, reset explicitly to generation 1 and replace it
        # atomically while still holding the session lock.
        generation = 1
        if os.path.lexists(path):
            try:
                generation = _load_receipt(path)["generation"] + 1
            except GuardError:
                generation = 1
                _reset_exact_nonregular(path)
        now = int(time.time())
        agent_id = event.get("agent_id")
        agent_type = event.get("agent_type")
        if expected_event == "SubagentStart":
            require(type(agent_type) is str and ID.fullmatch(agent_type), "E_AGENT_TYPE")
        else:
            require(agent_type is None or type(agent_type) is str and ID.fullmatch(agent_type),
                    "E_AGENT_TYPE")
        receipt = {
            "schema_version": 1, "kind": "mentor_enforcement_receipt", "state": "ready",
            "session_sha256": session_sha, "transcript_sha256": transcript_sha,
            "root_sha256": root_sha, "root_device": info.st_dev, "root_inode": info.st_ino,
            "generation": generation, "lifecycle_event": expected_event,
            "lifecycle_source": _lifecycle_source(event, expected_event),
            "nonce": secrets.token_hex(32), "lock_sha256": expected_lock_sha,
            "policy_sha256": policy_sha, "guard_sha256": hashes["mentor/mentor_guard.py"],
            "config_sha256": config_sha, "issued_at": now,
            "expires_at": now + lock["receipt_ttl_seconds"],
            "agent_id_sha256": None if agent_id is None else digest_bytes(str(agent_id).encode()),
            "agent_type": agent_type,
        }
        _atomic(path, receipt)
    capsule = _capsule(expected_lock_sha, policy_sha, generation)
    context = capsule + "\n\n" + "\n\n".join(
        f"SOURCE: {name}\n{contexts[name]}" for name in lock["context_paths"])
    return {"systemMessage": f"MENTOR_INIT_OK source={receipt['lifecycle_source']}",
            "hookSpecificOutput": {"hookEventName": expected_event,
                                   "additionalContext": context}}


def _validated_receipt(event, expected_lock_sha, root, required_state="ready",
                       lock_held=False):
    root, info, root_sha = _root_identity(root); _cwd_ok(root, event)
    session_sha, transcript_sha = _session(event)
    if not lock_held:
        with _session_lock(_state_root(root), session_sha):
            return _validated_receipt(event, expected_lock_sha, root, required_state,
                                      lock_held=True)
    lock, _raw, entries = _load_lock(root, expected_lock_sha)
    _contexts, hashes, policy_sha = _validate_sources(root, lock, entries)
    receipt = _load_receipt(_receipt_path(_state_root(root), session_sha))
    now = int(time.time())
    require(receipt["state"] == required_state and receipt["session_sha256"] == session_sha and
            receipt["transcript_sha256"] == transcript_sha and receipt["root_sha256"] == root_sha and
            receipt["root_device"] == info.st_dev and receipt["root_inode"] == info.st_ino and
            receipt["lock_sha256"] == expected_lock_sha and receipt["policy_sha256"] == policy_sha and
            receipt["guard_sha256"] == hashes["mentor/mentor_guard.py"] and
            receipt["config_sha256"] == _settings_sha(root) and
            receipt["issued_at"] <= now <= receipt["expires_at"], "E_RECEIPT_STALE")
    return root, lock, receipt, policy_sha


def gate_prompt(event, expected_lock_sha, root):
    require(event.get("hook_event_name") == "UserPromptSubmit", "E_EVENT")
    _root, _lock, receipt, policy_sha = _validated_receipt(event, expected_lock_sha, root)
    return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                   "additionalContext": _capsule(expected_lock_sha, policy_sha,
                                                                  receipt["generation"])}}


def gate_tool(event, expected_lock_sha, root):
    require(event.get("hook_event_name") == "PreToolUse", "E_EVENT")
    _validated_receipt(event, expected_lock_sha, root)
    return {}


def _transition_receipt(event, expected_lock_sha, root, new_state):
    """Validate and update one receipt while holding its lifecycle lock."""
    resolved, _info, _root_sha = _root_identity(root)
    session_sha, _transcript_sha = _session(event)
    state = _state_root(resolved)
    path = _receipt_path(state, session_sha)
    with _session_lock(state, session_sha):
        _root, _lock, receipt, _policy = _validated_receipt(
            event, expected_lock_sha, resolved, lock_held=True)
        generation = receipt["generation"]
        # Re-read under the same lock immediately before publication. This makes
        # stale validation unable to overwrite a newer lifecycle generation.
        current = _load_receipt(path)
        require(current["generation"] == generation and current == receipt,
                "E_RECEIPT_RACE")
        updated = dict(receipt)
        updated["state"] = new_state
        _atomic(path, updated)


def pre_compact(event, expected_lock_sha, root):
    require(event.get("hook_event_name") == "PreCompact" and
            event.get("trigger") in {"manual", "auto"}, "E_EVENT")
    _transition_receipt(event, expected_lock_sha, root, "compact_pending")
    return {}


def session_end(event, expected_lock_sha, root):
    require(event.get("hook_event_name") == "SessionEnd", "E_EVENT")
    _transition_receipt(event, expected_lock_sha, root, "revoked")
    return {}


def failure(mode, expected_event, code):
    reason = f"MENTOR_GUARD_LOCKED {code}"
    # Guard failures may deny risky tool execution, but prompt submission and
    # compaction are recovery surfaces and must remain available.
    if mode == "gate-tool":
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "deny",
                                       "permissionDecisionReason": reason}}
    return {"continue": True, "systemMessage": reason,
            "hookSpecificOutput": {"hookEventName": expected_event,
                                   "additionalContext": reason +
                                   ". Initialization is not verified; do not perform substantive work."}}


def process(event, mode, expected_event, expected_lock_sha, root):
    try:
        if mode == "lifecycle": return lifecycle(event, expected_event, expected_lock_sha, root)
        if mode == "gate-prompt": return gate_prompt(event, expected_lock_sha, root)
        if mode == "gate-tool": return gate_tool(event, expected_lock_sha, root)
        if mode == "pre-compact": return pre_compact(event, expected_lock_sha, root)
        if mode == "session-end": return session_end(event, expected_lock_sha, root)
        raise GuardError("E_MODE")
    except GuardError as error:
        if mode == "gate-tool" and _failure_tool_allowed(event, Path(root).resolve()):
            return {}
        return failure(mode, expected_event, str(error))
    except Exception:
        if mode == "gate-tool" and _failure_tool_allowed(event, Path(root).resolve()):
            return {}
        return failure(mode, expected_event, "E_INTERNAL")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True,
                        choices=("lifecycle", "gate-prompt", "gate-tool", "pre-compact", "session-end"))
    parser.add_argument("--event", required=True)
    parser.add_argument("--lock-sha256", required=True)
    args = parser.parse_args()
    try:
        project = os.environ.get("CLAUDE_PROJECT_DIR", "")
        root, _info, _root_sha = _root_identity(project)
        settings = loads_strict(_safe_read(root, SETTINGS_RELATIVE, MAX_SOURCE, "E_CONFIG"),
                                MAX_SOURCE)
        hooks = settings.get("hooks", {})
        require(type(hooks) is dict, "E_CONFIG")
        # Claude may retain a command registered before the user rolls it back.
        # Unregistration disables that cached command without minting a receipt.
        if b"mentor/mentor_guard.py" not in canonical(hooks):
            sys.stdout.write("{}\n")
            return
        raw = sys.stdin.buffer.read(MAX_INPUT + 1)
        event = loads_strict(raw, MAX_INPUT)
        result = process(event, args.mode, args.event, args.lock_sha256, project)
    except Exception:
        result = failure(args.mode, args.event, "E_INPUT")
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
