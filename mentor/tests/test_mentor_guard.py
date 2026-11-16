import copy
import fcntl
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock
from types import SimpleNamespace

from mentor import mentor_guard as guard


def sha(data):
    return hashlib.sha256(data).hexdigest()


def hold_flock(path, ready, seconds):
    descriptor = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        ready.set()
        time.sleep(seconds)
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


class MentorGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for path in ("mentor", "mentor/runtime", ".claude"):
            (self.root / path).mkdir(exist_ok=True)
        files = {
            "mentor/AGENTS.md": "# Mentor\nPreserve evidence.\n",
            "mentor/ROUTING.md": "# Router\nLoad selectively.\n",
            "mentor/mentor_guard.py": Path(guard.__file__).read_text(),
        }
        for name, text in files.items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            target.chmod(0o644)
        (self.root / ".claude/settings.json").write_text('{"hooks":{}}\n')
        (self.root / ".claude/settings.json").chmod(0o644)
        lock = {
            "schema_version": 1,
            "kind": "mentor_enforcement_lock",
            "guard_version": "mentor-guard-v1",
            "receipt_ttl_seconds": 3600,
            "context_paths": ["mentor/AGENTS.md", "mentor/ROUTING.md"],
            "files": [{"path": name, "sha256": sha((self.root / name).read_bytes()),
                       "max_bytes": 65536} for name in sorted(files)],
        }
        raw = guard.canonical(lock) + b"\n"
        (self.root / "mentor/enforcement-lock.json").write_bytes(raw)
        (self.root / "mentor/enforcement-lock.json").chmod(0o644)
        self.lock_sha = sha(raw)
        self.patch = mock.patch.object(guard, "SCRIPT_ROOT", self.root)
        self.patch.start(); self.addCleanup(self.patch.stop)
        self.event = {"hook_event_name": "SessionStart", "source": "startup",
                      "session_id": "session-a", "transcript_path": "/tmp/transcript-a",
                      "cwd": str(self.root)}

    def invoke(self, event, mode, expected):
        return guard.process(event, mode, expected, self.lock_sha, self.root)

    def initialize(self, event=None):
        return self.invoke(event or self.event, "lifecycle", "SessionStart")

    def run_cli(self, mode, event, *, lock_sha=None):
        output = io.StringIO()
        argv = ["mentor_guard.py", "--mode", mode, "--event", event["hook_event_name"],
                "--lock-sha256", lock_sha or self.lock_sha]
        with mock.patch.object(guard.sys, "argv", argv), \
                mock.patch.object(guard.sys, "stdin", SimpleNamespace(
                    buffer=io.BytesIO(guard.canonical(event)))), \
                mock.patch.object(guard.sys, "stdout", output), \
                mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": str(self.root)}):
            guard.main()
        return json.loads(output.getvalue())

    def test_unregistered_cached_commands_do_not_block_or_write_receipts(self):
        for mode, event in (("gate-prompt", "UserPromptSubmit"),
                            ("gate-tool", "PreToolUse"),
                            ("pre-compact", "PreCompact"),
                            ("lifecycle", "SessionStart"),
                            ("session-end", "SessionEnd")):
            payload = dict(self.event, hook_event_name=event, tool_name="Bash")
            self.assertEqual(self.run_cli(mode, payload, lock_sha="0" * 64), {})
        self.assertFalse((self.root / "mentor/runtime/enforcement").exists())

    def test_registered_guard_never_blocks_prompt_recovery_without_receipt(self):
        settings = {"hooks": {"UserPromptSubmit": [{"hooks": [{
            "type": "command", "command": "python3", "args": [
                "${CLAUDE_PROJECT_DIR}/mentor/mentor_guard.py"]}]}]}}
        (self.root / ".claude/settings.json").write_text(json.dumps(settings))
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        result = self.run_cli("gate-prompt", prompt)
        self.assertNotIn("decision", result)
        self.assertTrue(result["continue"])
        self.assertIn("MENTOR_GUARD_LOCKED", result["systemMessage"])

    def test_lifecycle_writes_bound_receipt_and_gates_prompt_and_tool(self):
        result = self.initialize()
        self.assertEqual(result["systemMessage"], "MENTOR_INIT_OK source=startup")
        self.assertIn("MENTOR_GUARD_OK", result["hookSpecificOutput"]["additionalContext"])
        prompt = dict(self.event, hook_event_name="UserPromptSubmit", prompt="SECRET_CANARY")
        allowed = self.invoke(prompt, "gate-prompt", "UserPromptSubmit")
        self.assertIn("MENTOR_GUARD_OK", allowed["hookSpecificOutput"]["additionalContext"])
        tool = dict(self.event, hook_event_name="PreToolUse", tool_name="Write",
                    tool_input={"file_path": "/private/SECRET_CANARY"})
        self.assertEqual(self.invoke(tool, "gate-tool", "PreToolUse"), {})
        receipt_path = self.root / "mentor/runtime/enforcement" / (sha(b"session-a") + ".json")
        receipt = json.loads(receipt_path.read_text())
        serialized = json.dumps(receipt)
        self.assertNotIn("session-a", serialized)
        self.assertNotIn("transcript-a", serialized)
        self.assertNotIn("SECRET_CANARY", serialized)

    def test_missing_failed_or_copied_receipt_preserves_recovery_but_denies_exact_mutators(self):
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        warning = self.invoke(prompt, "gate-prompt", "UserPromptSubmit")
        self.assertNotIn("decision", warning)
        self.assertTrue(warning["continue"])
        self.initialize()
        copied = dict(prompt, session_id="session-b")
        self.assertNotIn("decision", self.invoke(copied, "gate-prompt", "UserPromptSubmit"))
        wrong_transcript = dict(prompt, transcript_path="/tmp/other")
        self.assertNotIn("decision", self.invoke(wrong_transcript, "gate-prompt", "UserPromptSubmit"))
        compact = dict(copied, hook_event_name="PreCompact", trigger="manual")
        compact_warning = self.invoke(compact, "pre-compact", "PreCompact")
        self.assertNotIn("decision", compact_warning)
        self.assertTrue(compact_warning["continue"])
        for mutator in sorted(guard.MUTATING_EFFECT_TOOLS):
            tool = dict(copied, hook_event_name="PreToolUse", tool_name=mutator)
            decision = self.invoke(tool, "gate-tool", "PreToolUse")["hookSpecificOutput"]
            self.assertEqual(decision["permissionDecision"], "deny")
            self.assertNotEqual(decision["permissionDecision"], "allow")
        diagnostic_inputs = {
            "Read": {"file_path": str(self.root / "mentor/AGENTS.md")},
            "Grep": {"path": str(self.root / "mentor/ROUTING.md"), "pattern": "Router"},
            "Glob": {"path": str(self.root), "pattern": "mentor/mentor_guard.py"},
        }
        for recovery_surface, tool_input in diagnostic_inputs.items():
            tool = dict(copied, hook_event_name="PreToolUse", tool_name=recovery_surface,
                        tool_input=tool_input)
            self.assertEqual(self.invoke(tool, "gate-tool", "PreToolUse"), {})
        for recovery_surface in sorted(guard.RECOVERY_ORCHESTRATION_TOOLS):
            tool = dict(copied, hook_event_name="PreToolUse", tool_name=recovery_surface)
            self.assertEqual(self.invoke(tool, "gate-tool", "PreToolUse"), {})

    def test_failed_receipt_denies_unknown_effect_tools_and_protected_reads(self):
        copied = dict(self.event, session_id="missing", hook_event_name="PreToolUse")
        for tool_name, tool_input in (
                ("GmailSend", {}), ("mcp__market__query", {}), ("BrowserNavigate", {}),
                ("GitHubCreateIssue", {}), ("FutureEffectTool", {}),
                ("Agent", {"isolation": "remote"}),
                ("Agent", {"isolation": "worktree"}), ("Task", {})):
            result = self.invoke(dict(copied, tool_name=tool_name, tool_input=tool_input),
                                 "gate-tool", "PreToolUse")
            self.assertEqual(result["hookSpecificOutput"]["permissionDecision"], "deny")
        protected = dict(copied, tool_name="Read",
                         tool_input={"file_path": str(self.root / "niulai-private/state.json")})
        self.assertEqual(self.invoke(protected, "gate-tool", "PreToolUse")
                         ["hookSpecificOutput"]["permissionDecision"], "deny")
        receipt = dict(copied, tool_name="Read", tool_input={
            "file_path": str(self.root / "mentor/runtime/enforcement/secret.json")})
        self.assertEqual(self.invoke(receipt, "gate-tool", "PreToolUse")
                         ["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_failed_receipt_diagnostics_anchor_to_cwd_and_exact_topology(self):
        nested = self.root / "private-area"
        fake = nested / "mentor/AGENTS.md"
        fake.parent.mkdir(parents=True)
        fake.write_text("protected fake")
        base = dict(self.event, session_id="missing", cwd=str(nested),
                    hook_event_name="PreToolUse", tool_name="Read")
        denied = self.invoke(dict(base, tool_input={"file_path": "mentor/AGENTS.md"}),
                             "gate-tool", "PreToolUse")
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        for variant in ("../mentor/AGENTS.md", "./../mentor/./AGENTS.md",
                        str(self.root / "mentor/AGENTS.md")):
            allowed = self.invoke(dict(base, tool_input={"file_path": variant}),
                                  "gate-tool", "PreToolUse")
            self.assertEqual(allowed, {}, variant)
        policy = self.root / "mentor/AGENTS.md"
        outside = self.root / "policy-copy"
        outside.write_bytes(policy.read_bytes())
        policy.unlink(); policy.symlink_to(outside)
        changed = self.invoke(dict(base, tool_input={"file_path": "../mentor/AGENTS.md"}),
                              "gate-tool", "PreToolUse")
        self.assertEqual(changed["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_malformed_subagent_type_fails_visibly_without_receipt(self):
        event = dict(self.event, hook_event_name="SubagentStart", agent_id="child-1",
                     agent_type="../../bad type")
        result = self.invoke(event, "lifecycle", "SubagentStart")
        self.assertTrue(result["continue"])
        self.assertIn("E_AGENT_TYPE", result["systemMessage"])
        receipt = self.root / "mentor/runtime/enforcement" / (sha(b"session-a") + ".json")
        self.assertFalse(receipt.exists())

    def test_every_official_source_is_used_and_unknown_source_fails(self):
        for source in sorted(guard.OFFICIAL_SOURCES):
            event = dict(self.event, source=source)
            result = self.initialize(event)
            self.assertEqual(result["systemMessage"], f"MENTOR_INIT_OK source={source}")
        bad = self.initialize(dict(self.event, source="unknown"))
        self.assertIn("MENTOR_GUARD_LOCKED", bad["systemMessage"])

    def test_lock_contention_is_bounded_and_recovery_stays_available(self):
        self.initialize()
        state = self.root / "mentor/runtime/enforcement"
        lock_path = state / (sha(b"session-a") + ".lock")
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        holder = context.Process(target=hold_flock, args=(str(lock_path), ready, 5.0))
        holder.start()
        self.addCleanup(lambda: holder.is_alive() and holder.terminate())
        self.assertTrue(ready.wait(1))
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        started = time.monotonic()
        warning = self.invoke(prompt, "gate-prompt", "UserPromptSubmit")
        self.assertLess(time.monotonic() - started, 0.75)
        self.assertTrue(warning["continue"])
        self.assertIn("E_LOCK_BUSY", warning["systemMessage"])
        for mode, hook, extra in (("pre-compact", "PreCompact", {"trigger": "manual"}),
                                  ("session-end", "SessionEnd", {})):
            started = time.monotonic()
            result = self.invoke(dict(self.event, hook_event_name=hook, **extra), mode, hook)
            self.assertLess(time.monotonic() - started, 0.75)
            self.assertTrue(result["continue"])
            self.assertIn("E_LOCK_BUSY", result["systemMessage"])
        denied = self.invoke(dict(prompt, hook_event_name="PreToolUse", tool_name="Write",
                                  tool_input={"file_path": str(self.root / "x")}),
                             "gate-tool", "PreToolUse")
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        recovery = self.invoke(dict(prompt, hook_event_name="PreToolUse", tool_name="SendMessage",
                                    tool_input={}), "gate-tool", "PreToolUse")
        self.assertEqual(recovery, {})
        holder.terminate(); holder.join(2)
        self.assertFalse(holder.is_alive())
        refreshed = self.initialize(dict(self.event, source="resume"))
        self.assertEqual(refreshed["systemMessage"], "MENTOR_INIT_OK source=resume")
        receipt = json.loads((state / (sha(b"session-a") + ".json")).read_text())
        self.assertEqual((receipt["generation"], receipt["state"]), (2, "ready"))

    def test_compact_invalidation_requires_compact_lifecycle_refresh(self):
        self.initialize()
        pre = dict(self.event, hook_event_name="PreCompact", trigger="manual")
        self.assertEqual(self.invoke(pre, "pre-compact", "PreCompact"), {})
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        warning = self.invoke(prompt, "gate-prompt", "UserPromptSubmit")
        self.assertNotIn("decision", warning)
        self.assertTrue(warning["continue"])
        refreshed = self.initialize(dict(self.event, source="compact"))
        self.assertEqual(refreshed["systemMessage"], "MENTOR_INIT_OK source=compact")
        self.assertNotIn("decision", self.invoke(prompt, "gate-prompt", "UserPromptSubmit"))

    def test_source_config_and_lock_drift_warns_on_prompts_and_fails_closed_on_tools(self):
        self.initialize()
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        (self.root / "mentor/ROUTING.md").write_text("changed")
        warning = self.invoke(prompt, "gate-prompt", "UserPromptSubmit")
        self.assertNotIn("decision", warning)
        tool = dict(prompt, hook_event_name="PreToolUse", tool_name="Write")
        self.assertEqual(
            self.invoke(tool, "gate-tool", "PreToolUse")["hookSpecificOutput"]["permissionDecision"],
            "deny",
        )
        (self.root / "mentor/ROUTING.md").write_text("# Router\nLoad selectively.\n")
        (self.root / ".claude/settings.json").write_text('{"hooks":{"changed":[]}}\n')
        self.assertNotIn("decision", self.invoke(prompt, "gate-prompt", "UserPromptSubmit"))
        refreshed = self.invoke(self.event, "lifecycle", "SessionStart")
        self.assertEqual(refreshed["systemMessage"], "MENTOR_INIT_OK source=startup")

    def test_symlink_and_world_writable_source_are_rejected(self):
        route = self.root / "mentor/ROUTING.md"
        outside = self.root / "outside"; outside.write_text(route.read_text())
        route.unlink(); route.symlink_to(outside)
        self.assertIn("MENTOR_GUARD_LOCKED", self.initialize()["systemMessage"])
        route.unlink(); route.write_text("# Router\nLoad selectively.\n"); route.chmod(0o666)
        self.assertIn("MENTOR_GUARD_LOCKED", self.initialize()["systemMessage"])

    def test_symlinked_source_parent_is_rejected(self):
        mentor = self.root / "mentor"
        real = self.root / "real-mentor"
        mentor.rename(real)
        mentor.symlink_to(real, target_is_directory=True)
        self.assertIn("MENTOR_GUARD_LOCKED", self.initialize()["systemMessage"])

    def test_post_model_switch_and_subagent_lifecycle_are_bound(self):
        for hook, extra in (("PostModelSwitch", {}),
                            ("SubagentStart", {"agent_id": "child-1", "agent_type": "Explore"})):
            event = dict(self.event, hook_event_name=hook, **extra)
            result = self.invoke(event, "lifecycle", hook)
            self.assertIn("MENTOR_INIT_OK", result["systemMessage"])
            self.assertEqual(result["hookSpecificOutput"]["hookEventName"], hook)

    def test_lifecycle_recovers_corrupt_receipt_with_explicit_generation_reset(self):
        self.initialize()
        receipt_path = self.root / "mentor/runtime/enforcement" / (sha(b"session-a") + ".json")
        receipt_path.write_bytes(b'{"schema_version":')
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        warning = self.invoke(prompt, "gate-prompt", "UserPromptSubmit")
        self.assertTrue(warning["continue"])
        self.assertIn("MENTOR_GUARD_LOCKED", warning["systemMessage"])
        refreshed = self.initialize(dict(self.event, source="resume"))
        self.assertEqual(refreshed["systemMessage"], "MENTOR_INIT_OK source=resume")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["generation"], 1)
        self.assertEqual(receipt["state"], "ready")
        self.assertEqual(receipt["lifecycle_source"], "resume")
        self.assertNotIn("decision", self.invoke(prompt, "gate-prompt", "UserPromptSubmit"))

    def test_lifecycle_resets_exact_empty_receipt_and_lock_directories(self):
        self.initialize()
        state = self.root / "mentor/runtime/enforcement"
        stem = sha(b"session-a")
        receipt_path = state / (stem + ".json")
        lock_path = state / (stem + ".lock")
        receipt_path.unlink(); receipt_path.mkdir()
        lock_path.unlink(); lock_path.mkdir()
        refreshed = self.initialize(dict(self.event, source="resume"))
        self.assertEqual(refreshed["systemMessage"], "MENTOR_INIT_OK source=resume")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual((receipt["generation"], receipt["state"]), (1, "ready"))
        self.assertTrue(lock_path.is_file())

    def test_nonempty_or_symlink_candidate_nodes_fail_closed_without_following(self):
        state = self.root / "mentor/runtime/enforcement"
        state.mkdir(parents=True, exist_ok=True)
        stem = sha(b"session-a")
        receipt_path = state / (stem + ".json")
        lock_path = state / (stem + ".lock")
        target = self.root / "outside-canary"
        target.write_text("SECRET_CANARY")
        receipt_path.symlink_to(target)
        result = self.initialize()
        self.assertIn("MENTOR_GUARD_LOCKED", result["systemMessage"])
        self.assertEqual(target.read_text(), "SECRET_CANARY")
        self.assertTrue(receipt_path.is_symlink())
        receipt_path.unlink()
        target.unlink()
        receipt_path.symlink_to(target)
        result = self.initialize()
        self.assertIn("MENTOR_GUARD_LOCKED", result["systemMessage"])
        self.assertTrue(receipt_path.is_symlink())
        self.assertFalse(target.exists())
        receipt_path.unlink()
        target.write_text("SECRET_CANARY")
        lock_path.unlink()
        lock_path.symlink_to(target)
        result = self.initialize()
        self.assertIn("MENTOR_GUARD_LOCKED", result["systemMessage"])
        self.assertEqual(target.read_text(), "SECRET_CANARY")
        self.assertTrue(lock_path.is_symlink())
        lock_path.unlink()
        receipt_path.mkdir(); (receipt_path / "child").write_text("keep")
        result = self.initialize()
        self.assertIn("MENTOR_GUARD_LOCKED", result["systemMessage"])
        self.assertEqual((receipt_path / "child").read_text(), "keep")

    def test_concurrent_lifecycle_self_heals_occupied_lock_without_regression(self):
        state = self.root / "mentor/runtime/enforcement"
        state.mkdir(parents=True, exist_ok=True)
        lock_path = state / (sha(b"session-a") + ".lock")
        lock_path.mkdir()
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.initialize()))
                   for _ in range(6)]
        for item in threads: item.start()
        for item in threads: item.join()
        self.assertEqual(len(results), 6)
        self.assertTrue(all("MENTOR_INIT_OK" in item["systemMessage"] for item in results),
                        results)
        receipt_path = state / (sha(b"session-a") + ".json")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["generation"], 6)
        self.assertEqual(receipt["state"], "ready")

    def test_concurrent_first_lifecycle_all_succeed_and_generations_match(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.initialize()))
                   for _ in range(16)]
        for item in threads: item.start()
        for item in threads: item.join()
        self.assertEqual(len(results), 16)
        self.assertTrue(all("MENTOR_INIT_OK" in item["systemMessage"] for item in results),
                        results)
        receipt_path = self.root / "mentor/runtime/enforcement" / (sha(b"session-a") + ".json")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["generation"], 16)
        prompt = dict(self.event, hook_event_name="UserPromptSubmit")
        self.assertNotIn("decision", self.invoke(prompt, "gate-prompt", "UserPromptSubmit"))

    def test_concurrent_compact_cannot_regress_lifecycle_generation(self):
        self.initialize()
        validated = threading.Event()
        release = threading.Event()
        original = guard._validated_receipt

        def pause_after_validation(event, *args, **kwargs):
            result = original(event, *args, **kwargs)
            if event.get("hook_event_name") == "PreCompact":
                validated.set()
                release.wait(2)
            return result

        compact_result = []
        lifecycle_result = []
        compact = dict(self.event, hook_event_name="PreCompact", trigger="manual")
        with mock.patch.object(guard, "_validated_receipt", side_effect=pause_after_validation):
            first = threading.Thread(target=lambda: compact_result.append(
                self.invoke(compact, "pre-compact", "PreCompact")))
            first.start()
            self.assertTrue(validated.wait(1))
            second = threading.Thread(target=lambda: lifecycle_result.append(self.initialize()))
            second.start()
            release.set()
            first.join(2); second.join(2)
        self.assertEqual(compact_result, [{}])
        self.assertIn("MENTOR_INIT_OK", lifecycle_result[0]["systemMessage"])
        receipt_path = self.root / "mentor/runtime/enforcement" / (sha(b"session-a") + ".json")
        receipt = json.loads(receipt_path.read_text())
        self.assertEqual(receipt["generation"], 2)
        self.assertEqual(receipt["state"], "ready")

    def test_atomic_failure_is_sanitized_and_temp_removed(self):
        target = self.root / "mentor/runtime/enforcement/test.json"
        with mock.patch.object(guard.os, "replace", side_effect=OSError("SECRET_CANARY")):
            with self.assertRaisesRegex(guard.GuardError, "E_WRITE"):
                guard._atomic(target, {"x": 1})
        self.assertEqual(list(target.parent.glob(".*.tmp")), [])

    def test_malformed_input_failure_contains_no_canary(self):
        result = guard.process({"hook_event_name": "SessionStart", "source": "startup",
                                "session_id": "../SECRET_CANARY", "transcript_path": "x",
                                "cwd": str(self.root)}, "lifecycle", "SessionStart",
                               self.lock_sha, self.root)
        text = json.dumps(result)
        self.assertIn("MENTOR_GUARD_LOCKED", text)
        self.assertNotIn("SECRET_CANARY", text)


if __name__ == "__main__":
    unittest.main()
