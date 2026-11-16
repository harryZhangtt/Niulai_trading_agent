from __future__ import annotations

import copy
import importlib
import inspect
import json
import multiprocessing
import os
import queue
import stat
import subprocess
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import runner as predecessor
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import CELL_ORDER, ContractError
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 import (
    STATUS,
    default_run,
    execute_block,
    finalize_block,
)
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 import reservation
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3.runner import _bindings
from shared.job_runtime.tests.candidates.r6_data_quality_2x2_runner_v1 import test_runner as pinned_tests


class CountingBoundary:
    def __init__(self, inner, counter: Path, crash_first: bool = False):
        self.inner = inner
        self.adapter = inner.adapter
        self.counter = Path(counter)
        self.crash_first = crash_first

    def __call__(self, plan):
        raw = (plan["cell_id"] + "\n").encode("ascii")
        fd = os.open(self.counter, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            written = os.write(fd, raw)
            if written != len(raw):
                os._exit(91)
            os.fsync(fd)
        finally:
            os.close(fd)
        if self.crash_first and plan["order_index"] == 0:
            os._exit(42)
        return self.inner(plan)


def _race_worker(start, ready, results, args):
    ready.put(os.getpid())
    start.wait(10)
    try:
        ref = execute_block(*args[:4], _fixture_boundaries=args[4])
        results.put(("ok", ref["sha256"]))
    except Exception as exc:
        results.put(("error", str(exc)))



def _mutating_race_worker(start, ready, results, args, mode):
    import shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 as package
    module = importlib.import_module("shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3.runner")
    package.PREDECESSOR = {"sha256": "f" * 64}
    package.P0_V9_CLEAN = {"sha256": "e" * 64}
    module.PREDECESSOR = {"sha256": "d" * 64}
    module.P0_V9_CLEAN = {"sha256": "c" * 64}
    module.predecessor = {"runner": "alternate-imported-mapping"}
    module._sha = lambda _raw: "a" * 64
    module._canonical = lambda _value: b"alternate"
    module.ReservationManager = None
    module._bindings = lambda *_args, **_kwargs: ({"alternate": True}, "alternate", True)
    if mode == "reload":
        module = importlib.reload(module)
        module.PREDECESSOR = {"sha256": "b" * 64}
    ready.put(os.getpid())
    start.wait(10)
    try:
        ref = module.execute_block(*args[:4], _fixture_boundaries=args[4])
        results.put(("ok", ref["sha256"]))
    except Exception as exc:
        results.put(("error", str(exc)))

def _crash_worker(args, phase):
    def crash(_observed):
        os._exit(43)

    execute_block(*args[:4], _fixture_boundaries=args[4], _reservation_fault=phase, _fault_hook=crash)


def _boundary_crash_worker(args):
    execute_block(*args[:4], _fixture_boundaries=args[4])


def _receipt_crash_worker(args, fault):
    original = predecessor._commit_execution_receipt

    def crashing_commit(root, value, committed_at_ms, active_fault=None, crash_hook=None):
        return original(root, value, committed_at_ms, fault, crash_hook=lambda _phase: os._exit(44))

    predecessor._commit_execution_receipt = crashing_commit
    execute_block(*args[:4], _fixture_boundaries=args[4], _receipt_fault=fault)


class RunnerV3Tests(unittest.TestCase):
    def setUp(self):
        self.case = pinned_tests.V6("test_history_and_exports")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.base = Path(self.case.bundle.name)
        self.counter = self.base / "boundary-count.log"

    def boundaries(self, *, count=False, crash_first=False):
        values = {
            "ARM-A": pinned_tests.Boundary("ARM-A", self.case, self.base),
            "ARM-B": pinned_tests.Boundary("ARM-B", self.case, self.base),
        }
        if count or crash_first:
            values = {
                key: CountingBoundary(value, self.counter, crash_first=crash_first)
                for key, value in values.items()
            }
        return values

    def args(self, boundaries):
        return (
            self.case.registry,
            self.case.root.path,
            self.case.mapref,
            self.base / "bundles",
            boundaries,
        )

    def lines(self):
        if not self.counter.exists():
            return []
        return self.counter.read_text(encoding="ascii").splitlines()

    def fork_context(self):
        self.assertIn("fork", multiprocessing.get_all_start_methods())
        return multiprocessing.get_context("fork")

    def test_disabled_status_private_pins_and_pending_gates(self):
        import shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 as package
        from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 import runner

        status = default_run()
        self.assertEqual(status["status"], "P0_V10_RECLOSURE_REQUIRED")
        self.assertEqual(status["p0_schema_status"], "P0_V10_REQUIRED")
        self.assertEqual(status["consumer_status"], "P0_V10_RECLOSURE_REQUIRED")
        self.assertEqual(status["orchestrator_rebind"], "PENDING")
        self.assertEqual(status["fresh_independent_review"], "PENDING")
        self.assertFalse(status["activation"])
        self.assertEqual(STATUS, "P0_V10_RECLOSURE_REQUIRED")
        for namespace in (package, runner):
            self.assertFalse(hasattr(namespace, "PREDECESSOR"))
            self.assertFalse(hasattr(namespace, "P0_V9_CLEAN"))
            self.assertFalse(hasattr(namespace, "RUNNER_V8_OPEN_REVIEW"))
        self.assertNotIn("PREDECESSOR", package.__all__)
        pins = runner._verify_closed_sources()
        self.assertEqual(pins["runner_v2_open_review"], "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1")
        self.assertEqual(pins["p0_v9_contract"], "51f36fb46eb7a74994abf0a23152ce5d1f3fd7f4e8687aa900d1328e3b9aae1e")

    def test_nominal_fixed_order_single_attempt_and_human_finalization(self):
        boundaries = self.boundaries()
        execution_ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.case.calls, list(CELL_ORDER))
        execution = self.case.execution(execution_ref)
        self.assertEqual([cell["cell_id"] for cell in execution["cells"]], list(CELL_ORDER))
        self.assertTrue(all(cell["denominator_included"] and not cell["replay_allowed"] for cell in execution["cells"]))
        self.assertEqual(execution["attempted_variant_count"], 4)
        grade_refs = self.case.grade_refs(execution_ref)
        opening_ref = self.case.opening()
        finalized = finalize_block(execution_ref, self.case.root.path, grade_refs, opening_ref)
        self.assertEqual(finalized["status"], "FIXTURE_NOT_COUNTABLE")
        self.assertFalse(finalized["countable"])
        broken = copy.deepcopy(grade_refs)
        broken[CELL_ORDER[0]] = []
        with self.assertRaises(ContractError):
            finalize_block(execution_ref, self.case.root.path, broken, opening_ref)

    def test_true_multiprocess_competing_start_has_one_admission_and_one_four_cell_effect_set(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        start, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
        processes = [ctx.Process(target=_race_worker, args=(start, ready, results, args)) for _ in range(2)]
        for process in processes:
            process.start()
        self.assertEqual(len({ready.get(timeout=10), ready.get(timeout=10)}), 2)
        start.set()
        for process in processes:
            process.join(30)
            self.assertEqual(process.exitcode, 0)
        observed = [results.get(timeout=5), results.get(timeout=5)]
        self.assertTrue(any(status == "ok" for status, _ in observed), observed)
        lines = self.lines()
        self.assertEqual(lines, list(CELL_ORDER))
        self.assertEqual(lines.count(CELL_ORDER[0]), 1)
        events = self.case.root.path / ".r6-data-quality-runner-v3-reservations"
        self.assertEqual(len(list(events.glob("admit-*.json"))), 1)
        self.assertEqual(len(list(events.glob("claim-*.json"))), 1)

    def test_pre_admission_crash_recovers_only_with_zero_effects(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        process = ctx.Process(target=_crash_worker, args=(args, "crash_after_reservation"))
        process.start(); process.join(20)
        self.assertEqual(process.exitcode, 43)
        self.assertEqual(self.lines(), [])
        ref = execute_block(*args[:4], _fixture_boundaries=boundaries)
        self.assertEqual(ref["path"], "receipt/block-v6.json")
        self.assertEqual(self.lines(), list(CELL_ORDER))
        events = self.case.root.path / ".r6-data-quality-runner-v3-reservations"
        self.assertEqual(len(list(events.glob("recover-*.json"))), 1)

    def test_pre_admission_crash_with_destination_residue_fails_closed(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        process = ctx.Process(target=_crash_worker, args=(args, "crash_after_reservation"))
        process.start(); process.join(20)
        target = self.base / "bundles" / CELL_ORDER[0]
        target.mkdir(parents=True, mode=0o700)
        (target / (CELL_ORDER[0] + ".attempt-bundle.json")).write_bytes(b"{}")
        os.chmod(target / (CELL_ORDER[0] + ".attempt-bundle.json"), 0o600)
        with self.assertRaisesRegex(ContractError, "RESERVATION_ZERO_EFFECTS_NOT_PROVEN"):
            execute_block(*args[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])

    def test_post_admission_and_pre_first_boundary_crashes_are_durable_unknown(self):
        for phase in ("crash_after_admission", "crash_pre_first_boundary"):
            with self.subTest(phase=phase):
                self.case.doCleanups()
                self.setUp()
                ctx = self.fork_context()
                boundaries = self.boundaries(count=True)
                args = self.args(boundaries)
                process = ctx.Process(target=_crash_worker, args=(args, phase))
                process.start(); process.join(20)
                self.assertEqual(process.exitcode, 43)
                with self.assertRaisesRegex(ContractError, "UNKNOWN_NO_REPLAY"):
                    execute_block(*args[:4], _fixture_boundaries=boundaries)
                self.assertEqual(self.lines(), [])

    def test_crash_inside_first_boundary_never_replays(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(crash_first=True)
        args = self.args(boundaries)
        process = ctx.Process(target=_boundary_crash_worker, args=(args,))
        process.start(); process.join(20)
        self.assertEqual(process.exitcode, 42)
        self.assertEqual(self.lines(), [CELL_ORDER[0]])
        safe_boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "UNKNOWN_NO_REPLAY"):
            execute_block(*self.args(safe_boundaries)[:4], _fixture_boundaries=safe_boundaries)
        self.assertEqual(self.lines().count(CELL_ORDER[0]), 1)

    def test_receipt_stage_crashes_reconcile_without_boundary_replay(self):
        for fault in ("crash_after_stage_fsync", "crash_post_link"):
            with self.subTest(fault=fault):
                self.case.doCleanups()
                self.setUp()
                ctx = self.fork_context()
                boundaries = self.boundaries(count=True)
                args = self.args(boundaries)
                process = ctx.Process(target=_receipt_crash_worker, args=(args, fault))
                process.start(); process.join(30)
                self.assertEqual(process.exitcode, 44)
                self.assertEqual(self.lines(), list(CELL_ORDER))
                ref = execute_block(*args[:4], _fixture_boundaries=boundaries)
                self.assertEqual(ref["path"], "receipt/block-v6.json")
                self.assertEqual(self.lines(), list(CELL_ORDER))

    def test_active_stale_owner_is_never_stolen(self):
        boundaries = self.boundaries()
        bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
        with reservation.ReservationManager(self.case.root.path, bindings) as manager:
            claim = dict(manager._make_claim(None, None))
            claim["created_monotonic_ns"] = time.monotonic_ns() - reservation._LEASE_NS - 1
            claim["deadline_monotonic_ns"] = claim["created_monotonic_ns"] + reservation._LEASE_NS
            reservation._write_event(manager.directory_fd, manager._claim_name(), claim)
            with self.assertRaisesRegex(ContractError, "OWNER_ACTIVE_NO_TAKEOVER"):
                manager.acquire(lambda: self.fail("zero effects must not be consulted for active owner"))

    def test_pid_reuse_token_mismatch_requires_explicit_recovery_claim(self):
        boundaries = self.boundaries()
        bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
        proof = {"zero_effects": True, "admission_absent": True, "receipt_absent": True, "destinations_absent": True, "program_order_proof": True}
        with reservation.ReservationManager(self.case.root.path, bindings) as manager:
            claim = dict(manager._make_claim(None, None))
            owner = dict(claim["owner"])
            owner["process_start_token"] = "0" * 64
            core = {key: owner[key] for key in ("uid", "gid", "pid", "boot_id", "process_start_token", "nonce")}
            owner["process_identity"] = reservation._sha(reservation._canonical(core))
            claim["owner"] = owner
            raw, original_sha = reservation._write_event(manager.directory_fd, manager._claim_name(), claim)
            self.assertEqual(original_sha, reservation._sha(raw))
            handle, is_owner = manager.acquire(lambda: proof)
            self.assertTrue(is_owner)
            self.assertEqual(handle.claim["predecessor_claim_sha256"], original_sha)
            self.assertNotEqual(handle.process_identity, owner["process_identity"])
            self.assertTrue(manager._recovery_name(original_sha).startswith("recover-"))

    def test_caller_selected_destination_cannot_create_second_same_execution_reservation(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        process = ctx.Process(target=_crash_worker, args=(args, "crash_after_reservation"))
        process.start(); process.join(20)
        self.assertEqual(process.exitcode, 43)
        alternate = self.base / "alternate-bundles"
        with self.assertRaisesRegex(ContractError, "RESERVATION_CLAIM_BINDING"):
            execute_block(
                self.case.registry,
                self.case.root.path,
                self.case.mapref,
                alternate,
                _fixture_boundaries=boundaries,
            )
        self.assertEqual(self.lines(), [])

    def test_coherent_forged_claim_binding_fails_before_boundary(self):
        boundaries = self.boundaries(count=True)
        bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
        with reservation.ReservationManager(self.case.root.path, bindings) as manager:
            claim = dict(manager._make_claim(None, None))
            forged = dict(claim["bindings"])
            forged["destination_identity_sha256"] = "f" * 64
            claim["bindings"] = forged
            reservation._write_event(manager.directory_fd, manager._claim_name(), claim)
        with self.assertRaisesRegex(ContractError, "RESERVATION_CLAIM_BINDING"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])

    def test_reservation_symlink_mode_destination_path_and_short_write_faults_fail_closed(self):
        cases = ("reservation_symlink", "destination_symlink", "claim_short_write")
        for case in cases:
            with self.subTest(case=case):
                self.case.doCleanups()
                self.setUp()
                boundaries = self.boundaries(count=True)
                args = self.args(boundaries)
                if case == "reservation_symlink":
                    external = self.base / "external"
                    external.mkdir(mode=0o755)
                    link = self.case.root.path / ".r6-data-quality-runner-v3-reservations"
                    link.symlink_to(external, target_is_directory=True)
                    before = stat.S_IMODE(os.lstat(external).st_mode)
                    with self.assertRaises(ContractError):
                        execute_block(*args[:4], _fixture_boundaries=boundaries)
                    self.assertEqual(stat.S_IMODE(os.lstat(external).st_mode), before)
                elif case == "destination_symlink":
                    external = self.base / "external"
                    external.mkdir(mode=0o755)
                    (self.base / "bundles").symlink_to(external, target_is_directory=True)
                    with self.assertRaisesRegex(ContractError, "DESTINATION_ANCESTOR_UNSAFE"):
                        execute_block(*args[:4], _fixture_boundaries=boundaries)
                else:
                    with self.assertRaisesRegex(ContractError, "INJECTED_SHORT_WRITE"):
                        execute_block(*args[:4], _fixture_boundaries=boundaries, _reservation_fault="claim_short_write")
                    with self.assertRaises(ContractError):
                        execute_block(*args[:4], _fixture_boundaries=boundaries)
                self.assertEqual(self.lines(), [])

    def test_reservation_event_mode_tamper_fails_closed(self):
        boundaries = self.boundaries(count=True)
        bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
        with reservation.ReservationManager(self.case.root.path, bindings) as manager:
            claim = manager._make_claim(None, None)
            reservation._write_event(manager.directory_fd, manager._claim_name(), claim)
            path = self.case.root.path / ".r6-data-quality-runner-v3-reservations" / manager._claim_name()
            os.chmod(path, 0o644)
        with self.assertRaisesRegex(ContractError, "RESERVATION_EVENT_UNSAFE"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])


    def test_mutable_exports_and_module_reload_attack_still_one_key_claim_and_admission(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        start, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
        processes = [
            ctx.Process(target=_mutating_race_worker, args=(start, ready, results, args, "mutation")),
            ctx.Process(target=_mutating_race_worker, args=(start, ready, results, args, "reload")),
        ]
        for process in processes:
            process.start()
        self.assertEqual(len({ready.get(timeout=10), ready.get(timeout=10)}), 2)
        start.set()
        for process in processes:
            process.join(30)
            self.assertEqual(process.exitcode, 0)
        observed = [results.get(timeout=5), results.get(timeout=5)]
        self.assertTrue(any(status == "ok" for status, _ in observed), observed)
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual(self.lines().count(CELL_ORDER[0]), 1)
        events = self.case.root.path / ".r6-data-quality-runner-v3-reservations"
        self.assertEqual(len(list(events.glob("claim-*.json"))), 1)
        self.assertEqual(len(list(events.glob("admit-*.json"))), 1)

    def test_canonical_key_excludes_all_caller_selected_bound_identities(self):
        boundaries = self.boundaries()
        bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
        altered = copy.deepcopy(bindings)
        altered["authority_registry_ref_sha256"] = "1" * 64
        altered["map_commitment_ref_sha256"] = "2" * 64
        altered["destination_identity_sha256"] = "3" * 64
        altered["p0_owner_root_ids"] = {"ARM-A": "4" * 64, "ARM-B": "5" * 64}
        with reservation.ReservationManager(self.case.root.path, bindings) as first:
            key = first.key
        with reservation.ReservationManager(self.case.root.path, altered) as second:
            self.assertEqual(second.key, key)
        self.assertEqual(bindings["runner_v2_open_review_sha256"], "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1")

    def test_imported_module_and_mutable_contract_mapping_tamper_rejected_before_claim(self):
        from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 import runner
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        original_file = predecessor.__file__
        predecessor.__file__ = str(self.base / "alternate-runner.py")
        try:
            with self.assertRaisesRegex(ContractError, "RUNNER_V3_IMPORTED_SOURCE_MISMATCH"):
                execute_block(*args[:4], _fixture_boundaries=boundaries)
        finally:
            predecessor.__file__ = original_file
        original_inputs = runner._contracts_module.FROZEN_INPUTS
        runner._contracts_module.FROZEN_INPUTS = {**original_inputs, "effort": "mutated"}
        try:
            with self.assertRaisesRegex(ContractError, "RUNNER_V3_FROZEN_INPUT_MUTATION"):
                execute_block(*args[:4], _fixture_boundaries=boundaries)
        finally:
            runner._contracts_module.FROZEN_INPUTS = original_inputs
        self.assertEqual(self.lines(), [])
        self.assertFalse((self.case.root.path / ".r6-data-quality-runner-v3-reservations").exists())

    def test_production_api_has_no_liveness_observer_or_identity_injection(self):
        execute_parameters = set(inspect.signature(execute_block).parameters)
        acquire_parameters = set(inspect.signature(reservation.ReservationManager.acquire).parameters)
        forbidden = {"observer", "liveness_observer", "pid", "boot_id", "process_start_token", "clock", "deadline", "reservation_root"}
        self.assertFalse(execute_parameters & forbidden)
        self.assertFalse(acquire_parameters & forbidden)

    def test_owner_observation_outcomes_are_exact_tristate(self):
        owner = reservation._new_owner()
        live = reservation._observe_owner(owner)
        self.assertEqual(live["outcome"], "LIVE")
        self.assertEqual(live["boot_outcome"], "LIVE")
        with mock.patch.object(reservation, "_current_boot_identity", side_effect=ContractError("transient")):
            unknown = reservation._observe_owner(owner)
        self.assertEqual(unknown["outcome"], "INDETERMINATE")
        self.assertEqual(unknown["boot_outcome"], "INDETERMINATE")
        with mock.patch.object(reservation, "_current_boot_identity", return_value="f" * 64):
            dead_boot = reservation._observe_owner(owner)
        self.assertEqual(dead_boot["outcome"], "DEAD_EXACT_PROOF")
        self.assertEqual(dead_boot["boot_outcome"], "DEAD_EXACT_PROOF")
        with mock.patch.object(reservation, "_observe_process_start", return_value={"outcome": "DEAD_EXACT_PROOF", "reason": "PROCESS_START_TOKEN_MISMATCH", "observed_start_token": "e" * 64}):
            reused = reservation._observe_owner(owner)
        self.assertEqual(reused["outcome"], "DEAD_EXACT_PROOF")
        self.assertEqual(reused["process_outcome"], "DEAD_EXACT_PROOF")

    def test_process_observation_permission_errors_and_incomplete_tokens_are_indeterminate(self):
        pid = os.getpid()
        boot = reservation._current_boot_identity()
        token = reservation._new_owner()["process_start_token"]
        with mock.patch.object(reservation.Path, "is_dir", return_value=True), mock.patch.object(reservation.Path, "read_text", side_effect=PermissionError()):
            permission = reservation._observe_process_start(pid, boot, token)
        self.assertEqual(permission["outcome"], "INDETERMINATE")
        self.assertEqual(permission["reason"], "PROC_PERMISSION_DENIED")
        with mock.patch.object(reservation.Path, "is_dir", return_value=True), mock.patch.object(reservation.Path, "read_text", return_value="incomplete"):
            incomplete = reservation._observe_process_start(pid, boot, token)
        self.assertEqual(incomplete["outcome"], "INDETERMINATE")
        self.assertEqual(incomplete["reason"], "PROC_START_TOKEN_INCOMPLETE")
        with mock.patch.object(reservation.Path, "is_dir", return_value=False), mock.patch.object(reservation.subprocess, "run", side_effect=subprocess.TimeoutExpired("ps", 5)):
            transient = reservation._observe_process_start(pid, boot, token)
        self.assertEqual(transient["outcome"], "INDETERMINATE")
        self.assertEqual(transient["reason"], "PS_OBSERVATION_ERROR")
        missing = subprocess.CompletedProcess(["ps"], 1, stdout=b"", stderr=b"")
        with mock.patch.object(reservation.Path, "is_dir", return_value=False), mock.patch.object(reservation.subprocess, "run", return_value=missing), mock.patch.object(reservation.os, "kill", side_effect=ProcessLookupError()):
            dead = reservation._observe_process_start(999999, boot, token)
        self.assertEqual(dead["outcome"], "DEAD_EXACT_PROOF")
        self.assertEqual(dead["reason"], "PID_ABSENT_ESRCH")

    def test_live_owner_observation_failures_never_take_over_or_consult_zero_effects(self):
        reasons = ("BOOT_OBSERVATION_ERROR", "PROC_PERMISSION_DENIED", "PROC_READ_ERROR", "PROC_START_TOKEN_INCOMPLETE", "PS_OBSERVATION_ERROR", "PID_PERMISSION_DENIED")
        for reason in reasons:
            with self.subTest(reason=reason):
                self.case.doCleanups()
                self.setUp()
                boundaries = self.boundaries(count=True)
                bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
                with reservation.ReservationManager(self.case.root.path, bindings) as manager:
                    claim = manager._make_claim(None, None)
                    reservation._write_event(manager.directory_fd, manager._claim_name(), claim)
                    observed = {
                        "version": 1, "outcome": "INDETERMINATE", "boot_outcome": "INDETERMINATE",
                        "process_outcome": "INDETERMINATE", "reason": reason,
                        "owner_process_identity": claim["owner"]["process_identity"], "pid": claim["owner"]["pid"],
                        "expected_boot_id": claim["owner"]["boot_id"], "observed_boot_id": None,
                        "expected_start_token": claim["owner"]["process_start_token"], "observed_start_token": None,
                        "observed_monotonic_ns": time.monotonic_ns(),
                    }
                    with mock.patch.object(reservation, "_observe_owner", return_value=observed):
                        with self.assertRaisesRegex(ContractError, "LIVENESS_INDETERMINATE_NO_TAKEOVER"):
                            manager.acquire(lambda: self.fail("zero effects consulted under indeterminate liveness"))
                self.assertEqual(self.lines(), [])

    def test_coherent_forged_dead_proof_for_live_owner_is_rejected(self):
        boundaries = self.boundaries(count=True)
        bindings, _block, _fixture = _bindings(*self.args(boundaries)[:4], boundaries)
        proof = {"zero_effects": True, "admission_absent": True, "receipt_absent": True, "destinations_absent": True, "program_order_proof": True}
        with reservation.ReservationManager(self.case.root.path, bindings) as manager:
            claim = manager._make_claim(None, None)
            raw, claim_sha = reservation._write_event(manager.directory_fd, manager._claim_name(), claim)
            self.assertEqual(claim_sha, reservation._sha(raw))
            forged = dict(reservation._observe_owner(claim["owner"]))
            forged.update({"outcome": "DEAD_EXACT_PROOF", "boot_outcome": "LIVE", "process_outcome": "DEAD_EXACT_PROOF", "reason": "PROCESS_START_TOKEN_MISMATCH", "observed_start_token": "f" * 64})
            successor = manager._make_claim(claim_sha, proof, forged)
            reservation._write_event(manager.directory_fd, manager._recovery_name(claim_sha), successor)
            with self.assertRaisesRegex(ContractError, "FORGED_RECOVERY_OWNER_LIVE"):
                manager._read_chain()
        with self.assertRaisesRegex(ContractError, "FORGED_RECOVERY_OWNER_LIVE"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])


if __name__ == "__main__":
    unittest.main()
