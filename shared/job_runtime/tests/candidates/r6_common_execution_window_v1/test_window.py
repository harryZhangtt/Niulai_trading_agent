from __future__ import annotations

import copy
import inspect
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

try:
    from jsonschema import Draft202012Validator, ValidationError
except ImportError:  # The candidate has no runtime/test dependency beyond stdlib.
    Draft202012Validator = None
    ValidationError = Exception

from shared.job_runtime.candidates.r6_common_execution_window_v1 import window as w


def seal(body):
    result = copy.deepcopy(body)
    raw = w.canonical_bytes(result)
    result["seal"] = {"bytes": len(raw), "sha256": w._sha256(raw)}
    return result


def fixture_receipt():
    start_wall = 1_700_000_000_000_000_000
    start_mono = 10_000_000_000
    jobs = []
    chars = "ABCD"
    for index, cell in enumerate(w.CELL_ORDER):
        offset = w.ADMISSION_OFFSETS_SECONDS[index] * 1_000_000_000
        ch = chars[index]
        jobs.append({
            "ordinal": index + 1,
            "cell_id": cell,
            "job_id": "job_" + ch * 32,
            "slot_id": "slot_" + ch * 32,
            "attempt_id": "attempt_" + ch * 32,
            "operation_id": "operation_" + ch * 32,
            "admission_deadline_utc_ns": start_wall + offset,
            "admission_deadline_monotonic_ns": start_mono + offset,
        })
    return seal({
        "version": "r6-common-execution-window-receipt-v1",
        "status": "ISSUED",
        "immutable": True,
        "block_id": "block_" + "B" * 32,
        "window_id": "window_" + "W" * 32,
        "root": w.RUNTIME_RELATIVE_ROOT.as_posix(),
        "block_duration_seconds": 1800,
        "concurrency": 1,
        "cell_order": list(w.CELL_ORDER),
        "start_utc_ns": start_wall,
        "deadline_utc_ns": start_wall + w.BLOCK_DURATION_NS,
        "start_monotonic_ns": start_mono,
        "deadline_monotonic_ns": start_mono + w.BLOCK_DURATION_NS,
        "clock_pair_span_ns": 10,
        "issuer_pid": 101,
        "issuer_process_token": "e" * 64,
        "jobs": jobs,
        "template_sha256": "f" * 64,
        "authority_pins": {
            "final_block_grant": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "g1": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "g2": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "fresh_review": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "p0_v10": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "runner_v2": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "provider_authority": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
            "human_authority": {"path": "fixture/pin.json", "bytes": 1, "sha256": "a" * 64},
        },
        "reissue_allowed": False,
        "extension_allowed": False,
        "replay_allowed": False,
    })


def terminal(receipt, index, state="PASS"):
    job = receipt["jobs"][index]
    return seal({
        "version": "r6-common-execution-window-terminal-v1",
        "window_id": receipt["window_id"],
        "cell_id": job["cell_id"],
        "ordinal": job["ordinal"],
        "job_id": job["job_id"],
        "slot_id": job["slot_id"],
        "attempt_id": job["attempt_id"],
        "operation_id": job["operation_id"],
        "terminal_state": state,
        "immutable": True,
    })


class WindowContractTests(unittest.TestCase):
    def setUp(self):
        self.receipt = fixture_receipt()

    def assertCode(self, code, fn, *args, **kwargs):
        with self.assertRaises(w.WindowError) as caught:
            fn(*args, **kwargs)
        self.assertEqual(code, caught.exception.code)

    def pair(self, seconds, wall_delta_ns=0):
        return w.ClockPair(
            wall_utc_ns=self.receipt["start_utc_ns"] + seconds * 1_000_000_000 + wall_delta_ns,
            monotonic_ns=self.receipt["start_monotonic_ns"] + seconds * 1_000_000_000,
            pair_span_ns=10,
        )

    def runtime_root(self, temp):
        parent = Path(temp) / "runtime"
        parent.mkdir(mode=0o700)
        return parent / "r6_common_execution_window_v1"

    def test_public_surface_is_zero_argument_and_rejects_injection(self):
        for fn in (w.prepare_window_template, w.issue_live_window, w.recover_live_window, w.validate_live_window, w.admit_next_cell):
            self.assertEqual([], list(inspect.signature(fn).parameters), fn.__name__)
        with self.assertRaises(TypeError):
            w.issue_live_window(clock=object())
        with self.assertRaises(TypeError):
            w.validate_live_window(now=0)
        with self.assertRaises(TypeError):
            w.recover_live_window(root=Path("/tmp"))
        with self.assertRaises(TypeError):
            w.admit_next_cell(window_id="chosen")

    def test_disabled_issue_stops_before_clock_ids_or_io(self):
        with mock.patch.object(w, "_trusted_clock_pair", side_effect=AssertionError("clock called")), \
             mock.patch.object(w, "_new_id", side_effect=AssertionError("id minted")), \
             mock.patch.object(w, "_publish_at", side_effect=AssertionError("io called")):
            self.assertCode(w.STATUS, w.issue_live_window)
        self.assertFalse((w.CANONICAL_ROOT / w.RECEIPT_NAME).exists())
        self.assertFalse((w.CANONICAL_ROOT / w.MARKER_NAME).exists())

    def test_template_is_exact_pinned_disabled_and_owner_private(self):
        value = w.prepare_window_template()
        self.assertEqual(w.STATUS, value["status"])
        self.assertFalse(value["activation"])
        self.assertEqual(1800, value["block_duration_seconds"])
        self.assertEqual(1, value["concurrency"])
        self.assertEqual(list(w.CELL_ORDER), value["cell_order"])
        self.assertEqual([450, 900, 1350, 1800], value["admission_offsets_seconds"])
        self.assertEqual(11, len(value["source_pins"]))
        self.assertEqual(8, len(value["pending_pins"]))
        self.assertEqual(0o600, stat.S_IMODE(os.lstat(w.TEMPLATE_PATH).st_mode))
        self.assertIn("p0_v10", value["pending_pins"])
        self.assertIn("runner_v2", value["pending_pins"])
        self.assertIn("provider_authority", value["pending_pins"])
        self.assertIn("human_authority", value["pending_pins"])

    def test_all_schemas_are_strict_draft_2020_12(self):
        schema_dir = w.TEMPLATE_PATH.parent / "schemas"
        schemas = {}
        for path in schema_dir.glob("*.schema.json"):
            schema = json.loads(path.read_text())
            self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
            self.assertFalse(schema["additionalProperties"])
            self.assertIsInstance(schema.get("required"), list)
            schemas[path.name] = schema
        template_value = w.prepare_window_template()
        w._validate_template(template_value)
        w._validate_live_receipt(self.receipt)
        t = terminal(self.receipt, 0)
        w._validate_terminal(t, self.receipt, 0)
        decision = w._evaluate_admission(self.receipt, [], None, self.pair(1), current_pid=7, process_token="p")
        self.assertEqual(set(schemas["admission-decision-v1.schema.json"]["required"]), set(decision))
        if Draft202012Validator is not None:
            for schema in schemas.values():
                Draft202012Validator.check_schema(schema)
            Draft202012Validator(schemas["window-template-v1.schema.json"]).validate(template_value)
            Draft202012Validator(schemas["window-receipt-v1.schema.json"]).validate(self.receipt)
            Draft202012Validator(schemas["terminal-receipt-v1.schema.json"]).validate(t)
            Draft202012Validator(schemas["admission-decision-v1.schema.json"]).validate(decision)
            bad = copy.deepcopy(decision)
            bad["extra"] = True
            with self.assertRaises(ValidationError):
                Draft202012Validator(schemas["admission-decision-v1.schema.json"]).validate(bad)

    def test_receipt_enforces_exact_order_concurrency_and_duration(self):
        w._validate_live_receipt(self.receipt)
        for field, value, code in (
            ("cell_order", list(reversed(w.CELL_ORDER)), "WINDOW_ORDER"),
            ("concurrency", 2, "WINDOW_CONCURRENCY"),
            ("block_duration_seconds", 1799, "WINDOW_DURATION"),
        ):
            bad = copy.deepcopy(self.receipt)
            bad[field] = value
            bad = seal({k: v for k, v in bad.items() if k != "seal"})
            self.assertCode(code, w._validate_live_receipt, bad)

    def test_clock_rollback_jump_stale_and_future_are_denied(self):
        w._validate_clock(self.receipt, self.pair(0))
        rollback = w.ClockPair(self.receipt["start_utc_ns"], self.receipt["start_monotonic_ns"] - 1, 1)
        self.assertCode("MONOTONIC_ROLLBACK_OR_REBOOT", w._validate_clock, self.receipt, rollback)
        self.assertCode("WALL_CLOCK_JUMP", w._validate_clock, self.receipt, self.pair(1, wall_delta_ns=2_000_000_000))
        self.assertCode("WALL_WINDOW_BOUNDS", w._validate_clock, self.receipt, self.pair(1801))
        future_wall = w.ClockPair(self.receipt["start_utc_ns"] - 1, self.receipt["start_monotonic_ns"], 1)
        self.assertCode("WALL_WINDOW_BOUNDS", w._validate_clock, self.receipt, future_wall)

    def test_cell_deadline_edge_is_inclusive_then_denied(self):
        edge = self.pair(450)
        decision = w._evaluate_admission(self.receipt, [], None, edge, current_pid=7, process_token="p")
        self.assertEqual(w.CELL_ORDER[0], decision["cell_id"])
        past = w.ClockPair(edge.wall_utc_ns + 1, edge.monotonic_ns + 1, 1)
        self.assertCode("CELL_MONOTONIC_DEADLINE", w._evaluate_admission, self.receipt, [], None, past, current_pid=7, process_token="p")

    def test_previous_terminal_is_exact_and_unknown_fences_later_cells(self):
        first = terminal(self.receipt, 0)
        decision = w._evaluate_admission(self.receipt, [first], None, self.pair(451), current_pid=7, process_token="p")
        self.assertEqual(w.CELL_ORDER[1], decision["cell_id"])
        wrong = copy.deepcopy(first)
        wrong["attempt_id"] = self.receipt["jobs"][1]["attempt_id"]
        wrong = seal({k: v for k, v in wrong.items() if k != "seal"})
        self.assertCode("TERMINAL_IDENTITY", w._evaluate_admission, self.receipt, [wrong], None, self.pair(451), current_pid=7, process_token="p")
        unknown = terminal(self.receipt, 0, "UNKNOWN")
        self.assertCode("UNKNOWN_FORBIDS_LATER_CELLS", w._evaluate_admission, self.receipt, [unknown], None, self.pair(451), current_pid=7, process_token="p")

    def test_concurrency_restart_and_pid_reuse_are_fail_closed(self):
        active = {"version": "r6-common-execution-window-active-v1", "window_id": self.receipt["window_id"], "ordinal": 1, "cell_id": w.CELL_ORDER[0], "pid": 77, "process_token": "token-a", "immutable": True}
        self.assertCode("CONCURRENCY_ONE_ACTIVE", w._evaluate_admission, self.receipt, [], active, self.pair(1), current_pid=77, process_token="token-a")
        self.assertCode("PID_REUSE_UNKNOWN", w._evaluate_admission, self.receipt, [], active, self.pair(1), current_pid=77, process_token="token-b")
        self.assertCode("ACTIVE_PROCESS_RESTART_UNKNOWN", w._evaluate_admission, self.receipt, [], active, self.pair(1), current_pid=88, process_token="token-b")

    def test_publish_full_write_reopen_hash_modes_recovery_and_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            result = w._publish_at(root, self.receipt)
            self.assertEqual(self.receipt, result)
            self.assertEqual(0o700, stat.S_IMODE(os.lstat(root).st_mode))
            self.assertEqual(0o600, stat.S_IMODE(os.lstat(root / w.RECEIPT_NAME).st_mode))
            self.assertEqual(0o600, stat.S_IMODE(os.lstat(root / w.MARKER_NAME).st_mode))
            with mock.patch.object(w.secrets, "token_urlsafe", side_effect=AssertionError("fresh id minted")):
                self.assertEqual(self.receipt, w._recover_at(root))
            self.assertCode("SINGLE_ISSUANCE_ONLY", w._publish_at, root, self.receipt)

    def test_short_writes_are_completed_and_zero_write_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            def short(fd, data):
                return os.write(fd, data[:7])
            self.assertEqual(self.receipt, w._publish_at(root, self.receipt, write_fn=short))
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            self.assertCode("WRITE_ZERO_OR_INVALID", w._publish_at, root, self.receipt, write_fn=lambda _fd, _data: 0)

    def test_crash_stages_never_reissue_and_committed_marker_recovers_exact(self):
        for stage in ("receipt_stage_fsynced", "receipt_published", "marker_stage_fsynced"):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                root = self.runtime_root(temp)
                self.assertCode("INJECTED_CRASH_" + stage.upper(), w._publish_at, root, self.receipt, crash_after=stage)
                self.assertCode("INCOMPLETE_WINDOW_NO_REISSUE", w._recover_at, root)
                self.assertCode("SINGLE_ISSUANCE_ONLY", w._publish_at, root, self.receipt)
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            self.assertCode("INJECTED_CRASH_MARKER_PUBLISHED", w._publish_at, root, self.receipt, crash_after="marker_published")
            self.assertEqual(self.receipt, w._recover_at(root))

    def test_symlink_root_wrong_root_mode_and_receipt_mode_are_denied(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp) / "runtime"
            parent.mkdir(mode=0o700)
            real = parent / "real"
            real.mkdir(mode=0o700)
            root = parent / "r6_common_execution_window_v1"
            root.symlink_to(real, target_is_directory=True)
            self.assertCode("ROOT_TYPE", w._publish_at, root, self.receipt)
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            root.mkdir(mode=0o755)
            self.assertCode("ROOT_MODE", w._publish_at, root, self.receipt)
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            w._publish_at(root, self.receipt)
            os.chmod(root / w.RECEIPT_NAME, 0o644)
            self.assertCode("ARTIFACT_MODE", w._recover_at, root)

    def test_commit_marker_is_last_and_hash_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = self.runtime_root(temp)
            w._publish_at(root, self.receipt)
            marker = json.loads((root / w.MARKER_NAME).read_text())
            raw = (root / w.RECEIPT_NAME).read_bytes()
            self.assertTrue(marker["committed"])
            self.assertEqual(len(raw), marker["receipt_bytes"])
            self.assertEqual(w._sha256(raw), marker["receipt_sha256"])
            tampered = bytearray(raw)
            tampered[-1] = ord(" ")
            (root / w.RECEIPT_NAME).write_bytes(bytes(tampered))
            os.chmod(root / w.RECEIPT_NAME, 0o600)
            self.assertCode("COMMIT_RECEIPT_MISMATCH", w._recover_at, root)


if __name__ == "__main__":
    unittest.main()
