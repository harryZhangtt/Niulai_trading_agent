from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import importlib.util
import json
import multiprocessing
import os
import signal
import subprocess
import sys
import time
import types
import unittest
from pathlib import Path

from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import contracts as contracts
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import runner as predecessor
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import CELL_ORDER, ContractError
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v4 import STATUS, default_run, execute_block, finalize_block
from shared.job_runtime.tests.candidates.r6_data_quality_2x2_runner_v1 import test_runner as pinned_tests

ROOT = Path(__file__).resolve().parents[5]
RUNNER_SOURCE = ROOT / "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v4/runner.py"
REVIEW = ROOT / "mentor/runtime/scheduler-midresponse-recovery-20261107/r6-data-quality-2x2-runner-v3-independent-review-fable-20261113-8e9a8076-open.json"
FROZEN_78 = {
    "tuning/architecture/r6_data_quality_fable_allocation_design_v1/decision-v1.json": (713, "363979805bcde0e4241fdaf85fedce33ae3846f0e548e80241f5a603d92f1563"),
    "tuning/architecture/r6_data_quality_fable_allocation_design_v1/producer-verification-v1.json": (1488, "536a9793b752ee4bd761d51022cc99cb48463d7e719e6a1a130f3e557ce65ea3"),
    "tuning/architecture/r6_data_quality_fable_allocation_design_v1/protocol-v1.json": (2966, "b307ad0a8550b77d7de9ed42cca92f5f2fa66677223278826c89e3bdf0257214"),
    "tuning/architecture/r6_data_quality_fable_allocation_design_v1/source-closure-v1.json": (1604, "b3ac5d54e652d6fc2a6e0ec0147311be5b89a6130e9f0a8e2e975efaa3079b5e"),
}


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _cell(function, name):
    cells = dict(zip(function.__code__.co_freevars, function.__closure__ or ()))
    return cells[name]


class CountingBoundary:
    def __init__(self, inner, counter: Path, crash_first: bool = False):
        self.inner = inner
        self.adapter = inner.adapter
        self.counter = Path(counter)
        self.crash_first = crash_first

    def __call__(self, _plan):
        raise AssertionError("parent boundary callable must never execute")


class ParentTrapBoundary:
    def __init__(self, inner):
        self.inner = inner
        self.adapter = inner.adapter
        self.called = False

    def __call__(self, _plan):
        self.called = True
        raise AssertionError("parent injected boundary executed")


def _execute_worker(start, ready, results, args, attack="none", reservation_fault=None):
    if attack in ("key", "liveness"):
        import shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 as v3_package
        from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v3 import reservation as v3_reservation

        v3_package.ReservationManager = None
        v3_reservation._reservation_key = lambda _bindings: "f" * 64
        if attack == "liveness":
            v3_reservation._observe_owner = lambda owner: {
                "version": 1,
                "outcome": "DEAD_EXACT_PROOF",
                "boot_outcome": "LIVE",
                "process_outcome": "DEAD_EXACT_PROOF",
                "reason": "PROCESS_START_TOKEN_MISMATCH",
                "owner_process_identity": owner["process_identity"],
                "pid": owner["pid"],
                "expected_boot_id": owner["boot_id"],
                "observed_boot_id": owner["boot_id"],
                "expected_start_token": owner["process_start_token"],
                "observed_start_token": "f" * 64,
                "observed_monotonic_ns": time.monotonic_ns(),
            }
    ready.put(os.getpid())
    start.wait(10)
    try:
        ref = execute_block(*args[:4], _fixture_boundaries=args[4], _reservation_fault=reservation_fault)
        results.put(("ok", ref["sha256"]))
    except Exception as exc:
        results.put(("error", str(exc)))


def _alias_worker(start, ready, results, args, reload_first=False):
    module = importlib.import_module("shared.job_runtime.candidates.r6_data_quality_2x2_runner_v4.runner")
    if reload_first:
        target = importlib.reload(module).execute_block
    else:
        spec = importlib.util.spec_from_file_location("runner_v4_test_alias", RUNNER_SOURCE)
        alias = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(alias)
        target = alias.execute_block
    ready.put(os.getpid())
    start.wait(10)
    try:
        ref = target(*args[:4], _fixture_boundaries=args[4])
        results.put(("ok", ref["sha256"]))
    except Exception as exc:
        results.put(("error", str(exc)))


class RunnerV4Tests(unittest.TestCase):
    def setUp(self):
        self.case = pinned_tests.V6("test_history_and_exports")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.base = Path(self.case.bundle.name)
        self.counter = self.base / "boundary-count.log"

    def reset_case(self):
        self.case.doCleanups()
        self.setUp()

    def boundaries(self, *, count=False, crash_first=False, trap=False):
        values = {
            arm: pinned_tests.Boundary(arm, self.case, self.base)
            for arm in ("ARM-A", "ARM-B")
        }
        if count or crash_first:
            values = {
                arm: CountingBoundary(boundary, self.counter, crash_first=crash_first)
                for arm, boundary in values.items()
            }
        if trap:
            values = {arm: ParentTrapBoundary(boundary) for arm, boundary in values.items()}
        return values

    def args(self, boundaries, bundle=None):
        return (
            self.case.registry,
            self.case.root.path,
            self.case.mapref,
            self.base / "bundles" if bundle is None else Path(bundle),
            boundaries,
        )

    def lines(self):
        if not self.counter.exists():
            return []
        return self.counter.read_text(encoding="ascii").splitlines()

    def events(self):
        root = self.case.root.path / ".r6-data-quality-runner-v4-reservations"
        return [] if not root.exists() else sorted(root.iterdir())

    def event_count(self, prefix):
        return sum(path.name.startswith(prefix + "-") for path in self.events())

    def fork_context(self):
        self.assertIn("fork", multiprocessing.get_all_start_methods())
        return multiprocessing.get_context("fork")

    def wait_for_claim(self, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            claims = [p for p in self.events() if p.name.startswith("claim-")]
            if claims:
                return json.loads(claims[0].read_text(encoding="ascii"))
            time.sleep(0.01)
        self.fail("reservation claim was not published")

    def test_disabled_status_exact_review_and_frozen_78_history(self):
        state = default_run()
        self.assertEqual(STATUS, "P0_V10_RECLOSURE_REQUIRED")
        self.assertEqual(state["p0_schema_status"], "P0_V10_REQUIRED")
        self.assertEqual(state["consumer_status"], "P0_V10_RECLOSURE_REQUIRED")
        self.assertEqual(state["fresh_independent_review"], "PENDING")
        self.assertEqual(state["orchestrator_rebind"], "PENDING")
        self.assertFalse(state["activation"])
        self.assertFalse(state["countable"])
        raw = REVIEW.read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (22021, "e11ca7dd9b35a21e8d57ef9398c4aa713a77c45d00986b3f4c3d1ca693b06afe"))
        for relative, expected in FROZEN_78.items():
            body = (ROOT / relative).read_bytes()
            self.assertEqual((len(body), hashlib.sha256(body).hexdigest()), expected)
        producer = json.loads((ROOT / "tuning/architecture/r6_data_quality_fable_allocation_design_v1/producer-verification-v1.json").read_text())
        self.assertEqual(producer["tests"]["python3.12"]["combined"], {"discovered": 78, "passed": 78, "skipped": 0})

    def test_nominal_fixed_order_one_attempt_zero_retry_replay_status_and_human_finalization(self):
        boundaries = self.boundaries(count=True)
        ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        execution = self.case.execution(ref)
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual([cell["cell_id"] for cell in execution["cells"]], list(CELL_ORDER))
        self.assertEqual(execution["attempted_variant_count"], 4)
        self.assertTrue(all(cell["denominator_included"] and not cell["replay_allowed"] for cell in execution["cells"]))
        grant_ref = json.loads((self.case.root.path / "auth/registry.json").read_text())["block_grant_ref"]
        grant = json.loads((self.case.root.path / grant_ref["path"]).read_text())
        self.assertEqual(grant["limits"]["attempts_per_cell"], 1)
        self.assertEqual({key: grant["limits"][key] for key in ("retries", "replays", "status_queries")}, {"retries": 0, "replays": 0, "status_queries": 0})
        finalized = finalize_block(ref, self.case.root.path, self.case.grade_refs(ref), self.case.opening())
        self.assertEqual(finalized["status"], "FIXTURE_NOT_COUNTABLE")
        self.assertFalse(finalized["countable"])

    def test_parent_boundary_callable_cannot_inject_child_boundary(self):
        boundaries = self.boundaries(trap=True)
        ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.case.execution(ref)["attempted_variant_count"], 4)
        self.assertTrue(all(not boundary.called for boundary in boundaries.values()))
        self.assertEqual(self.case.calls, [])

    def test_true_multiprocess_competing_start_has_one_claim_admission_and_four_effects(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        start, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
        workers = [ctx.Process(target=_execute_worker, args=(start, ready, results, args)) for _ in range(2)]
        for worker in workers:
            worker.start()
        self.assertEqual(len({ready.get(timeout=10), ready.get(timeout=10)}), 2)
        start.set()
        for worker in workers:
            worker.join(30)
            self.assertEqual(worker.exitcode, 0)
        observed = [results.get(timeout=5), results.get(timeout=5)]
        self.assertTrue(any(status == "ok" for status, _ in observed), observed)
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual(self.event_count("claim"), 1)
        self.assertEqual(self.event_count("admit"), 1)

    def test_v3_key_split_finding_true_multiprocess_reproduction_is_closed(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        start, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
        workers = [
            ctx.Process(target=_execute_worker, args=(start, ready, results, args, "none")),
            ctx.Process(target=_execute_worker, args=(start, ready, results, args, "key")),
        ]
        for worker in workers:
            worker.start()
        self.assertEqual(len({ready.get(timeout=10), ready.get(timeout=10)}), 2)
        start.set()
        for worker in workers:
            worker.join(30)
            self.assertEqual(worker.exitcode, 0)
        observed = [results.get(timeout=5), results.get(timeout=5)]
        self.assertTrue(any(status == "ok" for status, _ in observed), observed)
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual((self.event_count("claim"), self.event_count("admit")), (1, 1))

    def test_v3_forged_liveness_finding_true_multiprocess_live_owner_no_takeover(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        start, ready, owner_results = ctx.Event(), ctx.Queue(), ctx.Queue()
        owner = ctx.Process(target=_execute_worker, args=(start, ready, owner_results, args, "none", "stop_after_reservation"))
        owner.start()
        ready.get(timeout=10)
        start.set()
        claim = self.wait_for_claim()
        child_pid = claim["owner"]["pid"]
        attack_start, attack_ready, attack_results = ctx.Event(), ctx.Queue(), ctx.Queue()
        attacker = ctx.Process(target=_execute_worker, args=(attack_start, attack_ready, attack_results, args, "liveness"))
        try:
            attacker.start()
            attack_ready.get(timeout=10)
            attack_start.set()
            attacker.join(20)
            self.assertEqual(attacker.exitcode, 0)
            status, detail = attack_results.get(timeout=5)
            self.assertEqual(status, "error")
            self.assertIn("OWNER_ACTIVE_NO_TAKEOVER", detail)
            self.assertEqual(self.event_count("recover"), 0)
        finally:
            try:
                os.kill(child_pid, signal.SIGCONT)
            except ProcessLookupError:
                pass
        owner.join(30)
        if owner.is_alive():
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            owner.terminate()
            owner.join(5)
        self.assertEqual(owner.exitcode, 0)
        self.assertEqual(owner_results.get(timeout=5)[0], "ok")
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual((self.event_count("claim"), self.event_count("admit")), (1, 1))

    def test_child_exit_43_pre_admission_recovers_with_zero_effects(self):
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_43"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _reservation_fault="crash_after_reservation")
        self.assertEqual(self.lines(), [])
        ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(ref["path"], "receipt/block-v6.json")
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual(self.event_count("recover"), 1)

    def test_pre_admission_recovery_with_destination_residue_fails_closed(self):
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_43"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _reservation_fault="crash_after_reservation")
        target = self.base / "bundles" / CELL_ORDER[0]
        target.mkdir(parents=True, mode=0o700)
        (target / (CELL_ORDER[0] + ".attempt-bundle.json")).write_bytes(b"{}")
        os.chmod(target / (CELL_ORDER[0] + ".attempt-bundle.json"), 0o600)
        with self.assertRaisesRegex(ContractError, "ZERO_EFFECTS_NOT_PROVEN"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])

    def test_child_exit_43_post_admission_is_durable_unknown_no_replay(self):
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_43"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _reservation_fault="crash_after_admission")
        with self.assertRaisesRegex(ContractError, "UNKNOWN_NO_REPLAY"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        with self.assertRaisesRegex(ContractError, "UNKNOWN_NO_REPLAY"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.event_count("unknown"), 1)

    def test_child_exit_42_after_first_boundary_is_unknown_and_never_replays(self):
        crashing = self.boundaries(count=True, crash_first=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_42"):
            execute_block(*self.args(crashing)[:4], _fixture_boundaries=crashing)
        self.assertEqual(self.lines(), [CELL_ORDER[0]])
        safe = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "UNKNOWN_NO_REPLAY"):
            execute_block(*self.args(safe)[:4], _fixture_boundaries=safe)
        self.assertEqual(self.lines(), [CELL_ORDER[0]])

    def test_receipt_stage_fsync_crash_reconciles_without_replay(self):
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_44"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _receipt_fault="crash_after_stage_fsync")
        self.assertEqual(self.lines(), list(CELL_ORDER))
        ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(ref["path"], "receipt/block-v6.json")
        self.assertEqual(self.lines(), list(CELL_ORDER))

    def test_receipt_post_link_crash_reconciles_without_replay(self):
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_44"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _receipt_fault="crash_post_link")
        self.assertEqual(self.lines(), list(CELL_ORDER))
        ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(ref["path"], "receipt/block-v6.json")
        self.assertEqual(self.lines(), list(CELL_ORDER))

    def test_exclusive_on_disk_source_drift_fails_before_claim_and_restores_exact_bytes(self):
        lock = RUNNER_SOURCE.with_name(".runner-v4-source-drift.lock")
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        original = RUNNER_SOURCE.read_bytes()
        original_sha = hashlib.sha256(original).hexdigest()
        try:
            os.write(lock_fd, str(os.getpid()).encode("ascii"))
            os.fsync(lock_fd)
            RUNNER_SOURCE.write_bytes(original + b"\n# injected-source-drift\n")
            with self.assertRaisesRegex(ContractError, "RUNNER_V4_SOURCE_PIN_MISMATCH"):
                boundaries = self.boundaries(count=True)
                execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
            self.assertEqual(self.events(), [])
        finally:
            RUNNER_SOURCE.write_bytes(original)
            os.close(lock_fd)
            lock.unlink(missing_ok=True)
        restored = RUNNER_SOURCE.read_bytes()
        self.assertEqual((len(restored), hashlib.sha256(restored).hexdigest()), (len(original), original_sha))

    def test_closure_cell_child_bypass_cannot_skip_durable_receipt(self):
        run_child_cell = _cell(execute_block, "run_child")
        original = run_child_cell.cell_contents
        forged = {"kind": "execution_receipt_v6", "path": "receipt/block-v6.json", "sha256": "f" * 64, "canonical_content_sha256": "f" * 64, "bytes": 1, "immutable_at_ms": 1}
        run_child_cell.cell_contents = lambda *_args, **_kwargs: {"receipt": forged}
        try:
            boundaries = self.boundaries(trap=True)
            with self.assertRaisesRegex(ContractError, "RUNNER_V4_RECEIPT_READ_FAILED"):
                execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
            self.assertTrue(all(not boundary.called for boundary in boundaries.values()))
            self.assertEqual(self.events(), [])
        finally:
            run_child_cell.cell_contents = original

    def test_closure_cell_malformed_child_responses_fail_authenticated_validation(self):
        run_child = _cell(execute_block, "run_child").cell_contents
        subprocess_cell = _cell(run_child, "subprocess_run")
        original = subprocess_cell.cell_contents

        def malformed(*args, **_kwargs):
            return subprocess.CompletedProcess(args[0], 0, stdout=b"{}", stderr=b"")

        def same_pid_signed(*args, **kwargs):
            request = json.loads(kwargs["input"].decode("ascii"))
            body = {"version": 1, "request_sha256": hashlib.sha256(kwargs["input"]).hexdigest(), "source_sha256": request["expected_self"]["sha256"], "child_pid": os.getpid(), "result": {}}
            body["hmac_sha256"] = hmac.new(bytes.fromhex(request["secret"]), _canonical(body), hashlib.sha256).hexdigest()
            return subprocess.CompletedProcess(args[0], 0, stdout=_canonical(body), stderr=b"")

        try:
            for fake, code in ((malformed, "RECEIPT_SHAPE"), (same_pid_signed, "RECEIPT_SHAPE")):
                with self.subTest(fake=fake.__name__):
                    subprocess_cell.cell_contents = fake
                    boundaries = self.boundaries(count=True)
                    with self.assertRaisesRegex(ContractError, code):
                        execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
                    self.assertEqual(self.lines(), [])
                    self.assertEqual(self.events(), [])
        finally:
            subprocess_cell.cell_contents = original

    def test_function_global_package_and_sys_modules_attacks_cannot_replace_child(self):
        import shared.job_runtime.candidates.r6_data_quality_2x2_runner_v4 as package
        from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v4 import runner as module

        held = execute_block
        sentinel = object()
        old_package = package.execute_block
        old_global = module.__dict__.get("run_child", sentinel)
        names = (
            "shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.runner",
            "shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts",
            "shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3.harness",
        )
        old_modules = {name: sys.modules.get(name) for name in names}
        try:
            package.execute_block = lambda *_a, **_k: {"bypass": True}
            module.run_child = lambda *_a, **_k: {"bypass": True}
            for name in names:
                sys.modules[name] = types.ModuleType(name)
            boundaries = self.boundaries(count=True)
            ref = held(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
            self.assertEqual(ref["kind"], "execution_receipt_v6")
            self.assertEqual(self.lines(), list(CELL_ORDER))
        finally:
            package.execute_block = old_package
            if old_global is sentinel:
                module.__dict__.pop("run_child", None)
            else:
                module.run_child = old_global
            for name, value in old_modules.items():
                if value is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = value

    def test_alias_and_reload_competitors_share_one_child_reservation(self):
        ctx = self.fork_context()
        boundaries = self.boundaries(count=True)
        args = self.args(boundaries)
        start, ready, results = ctx.Event(), ctx.Queue(), ctx.Queue()
        workers = [
            ctx.Process(target=_alias_worker, args=(start, ready, results, args, False)),
            ctx.Process(target=_alias_worker, args=(start, ready, results, args, True)),
        ]
        for worker in workers:
            worker.start()
        self.assertEqual(len({ready.get(timeout=10), ready.get(timeout=10)}), 2)
        start.set()
        for worker in workers:
            worker.join(30)
            self.assertEqual(worker.exitcode, 0)
        observed = [results.get(timeout=5), results.get(timeout=5)]
        self.assertTrue(any(status == "ok" for status, _ in observed), observed)
        self.assertEqual(self.lines(), list(CELL_ORDER))
        self.assertEqual((self.event_count("claim"), self.event_count("admit")), (1, 1))

    def test_direct_malformed_isolated_child_request_exits_70_without_effects(self):
        completed = subprocess.run(
            [sys.executable, "-I", str(RUNNER_SOURCE), "--r6-v4-child"],
            input=b"{}",
            capture_output=True,
            cwd="/",
            env={"PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C", "LANG": "C"},
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 70)
        self.assertEqual((completed.stdout, completed.stderr), (b"", b""))
        self.assertEqual(self.events(), [])

    def test_parent_rereads_durable_receipt_and_rejects_post_child_tamper(self):
        run_child = _cell(execute_block, "run_child").cell_contents
        subprocess_cell = _cell(run_child, "subprocess_run")
        original = subprocess_cell.cell_contents

        def tamper_after_child(*args, **kwargs):
            completed = original(*args, **kwargs)
            request = json.loads(kwargs["input"].decode("ascii"))
            receipt = Path(request["payload"]["owner_root"]) / "receipt/block-v6.json"
            if receipt.exists():
                receipt.write_bytes(receipt.read_bytes() + b" ")
            return completed

        subprocess_cell.cell_contents = tamper_after_child
        try:
            boundaries = self.boundaries(count=True)
            with self.assertRaisesRegex(ContractError, "RUNNER_V4_RECEIPT_REF_BINDING"):
                execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
            self.assertEqual(self.lines(), list(CELL_ORDER))
        finally:
            subprocess_cell.cell_contents = original

    def test_changed_destination_cannot_create_second_reservation(self):
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "RUNNER_V4_CHILD_EXIT_43"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _reservation_fault="crash_after_reservation")
        with self.assertRaisesRegex(ContractError, "RESERVATION_CLAIM_BINDING"):
            execute_block(self.case.registry, self.case.root.path, self.case.mapref, self.base / "alternate", _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.event_count("claim"), 1)

    def test_reservation_symlink_and_short_write_fail_closed(self):
        boundaries = self.boundaries(count=True)
        external = self.base / "external"
        external.mkdir(mode=0o755)
        (self.case.root.path / ".r6-data-quality-runner-v4-reservations").symlink_to(external, target_is_directory=True)
        with self.assertRaises(ContractError):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])
        self.reset_case()
        boundaries = self.boundaries(count=True)
        with self.assertRaisesRegex(ContractError, "INJECTED_SHORT_WRITE"):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries, _reservation_fault="claim_short_write")
        with self.assertRaises(ContractError):
            execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        self.assertEqual(self.lines(), [])

    def test_imported_dependency_and_mutable_frozen_input_drift_fail_before_claim(self):
        boundaries = self.boundaries(count=True)
        original_file = predecessor.__file__
        predecessor.__file__ = str(self.base / "alternate-runner.py")
        try:
            with self.assertRaisesRegex(ContractError, "RUNNER_V4_IMPORTED_SOURCE_MISMATCH"):
                execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        finally:
            predecessor.__file__ = original_file
        original_inputs = contracts.FROZEN_INPUTS
        contracts.FROZEN_INPUTS = {**original_inputs, "effort": "mutated"}
        try:
            with self.assertRaisesRegex(ContractError, "RUNNER_V4_FROZEN_INPUT_MUTATION"):
                execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        finally:
            contracts.FROZEN_INPUTS = original_inputs
        self.assertEqual(self.lines(), [])
        self.assertEqual(self.events(), [])

    def test_human_finalization_rejects_missing_cell_grades(self):
        boundaries = self.boundaries()
        ref = execute_block(*self.args(boundaries)[:4], _fixture_boundaries=boundaries)
        grades = self.case.grade_refs(ref)
        grades[CELL_ORDER[0]] = []
        with self.assertRaises(ContractError):
            finalize_block(ref, self.case.root.path, grades, self.case.opening())


if __name__ == "__main__":
    unittest.main()
