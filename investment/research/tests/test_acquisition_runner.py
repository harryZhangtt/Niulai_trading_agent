import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
import unittest

from investment.research.acquisition_runner import (
    HostedAcquisitionRunner,
    HostedProviderResponse,
    RunnerError,
    verify_dispatch_receipt,
)
from shared.research_sources.acquisition_contracts import (
    AcquisitionIdentity,
    DispatchIdentity,
    DispatchState,
    ExactArguments,
    RunIdentity,
)
from shared.research_sources.artifacts import SOURCE_STATE, read


class Clock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


class CountingProvider:
    def __init__(self, response=None, error=None):
        self.calls = []
        self.response = response or HostedProviderResponse([b"synthetic result"])
        self.error = error

    def __call__(self, arguments, absolute_deadline):
        self.calls.append((arguments, absolute_deadline))
        if self.error:
            raise self.error
        return self.response


class ClosableChunks:
    def __init__(self, chunks):
        self._chunks = iter(chunks)
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self._chunks)

    def close(self):
        self.closed = True


class AcquisitionRunnerTests(unittest.TestCase):
    def setUp(self):
        parent = SOURCE_STATE / "tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clock = Clock()

    @staticmethod
    def identity(dispatch_id="dispatch-1"):
        return AcquisitionIdentity(
            RunIdentity("experiment-1", "execution-1", "trace-1"),
            DispatchIdentity("operation-1", "attempt-1", dispatch_id),
        )

    @staticmethod
    def arguments():
        return ExactArguments.from_mapping({
            "open": [{"ref_id": "https://example.test/disclosure.pdf"}],
            "response_length": "long",
        })

    def runner(self, provider, name="runner", *, limit=65536, run_deadline=200.0):
        return HostedAcquisitionRunner(
            self.root / name,
            provider=provider,
            configured_backend="injected.synthetic.backend",
            run_deadline=run_deadline,
            raw_byte_limit=limit,
            monotonic=self.clock,
        )

    def test_public_cooperative_methods_own_external_state(self):
        provider = CountingProvider()
        runner = self.runner(provider, "cooperative")
        identity = self.identity("dispatch-cooperative")
        arguments = self.arguments()
        ticket = runner.begin_external_invocation(
            identity, arguments, absolute_deadline=150.0)
        self.assertEqual(ticket["arguments"], arguments.canonical_json)
        self.assertEqual(ticket["state"], "invocation_started")
        receipt = runner.capture_external_result(
            identity.dispatch.dispatch_id, b'"bounded host result"',
            observed_backend="reported.synthetic.backend")
        self.assertEqual(receipt["state"], "captured")
        self.assertEqual(verify_dispatch_receipt(receipt["dispatch_ref"])["dispatch_id"],
                         identity.dispatch.dispatch_id)
        self.assertEqual(provider.calls, [])

    def test_public_cooperative_unknown_and_late_capture_never_replay(self):
        provider = CountingProvider()
        runner = self.runner(provider, "cooperative-unknown")
        identity = self.identity("dispatch-cooperative-unknown")
        runner.begin_external_invocation(identity, self.arguments(), absolute_deadline=150.0)
        fenced = runner.fence_external_unknown(
            identity.dispatch.dispatch_id, "HOST_WEB_RESULT_UNKNOWN")
        self.assertEqual(fenced["state"], "possibly_dispatched")
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DISPATCH_FENCED"):
            runner.claim(identity.dispatch.dispatch_id)

        late = self.runner(provider, "cooperative-late")
        late_id = self.identity("dispatch-cooperative-late")
        late.begin_external_invocation(late_id, self.arguments(), absolute_deadline=150.0)
        self.clock.value = 151.0
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DEADLINE_AFTER_DISPATCH"):
            late.capture_external_result(
                late_id.dispatch.dispatch_id, b'"late"', observed_backend=None)
        self.assertEqual(late.journal(late_id.dispatch.dispatch_id)[-1]["state"],
                         "possibly_dispatched")

    def test_invokes_exact_claimed_bytes_once_and_captures_privately(self):
        provider = CountingProvider(HostedProviderResponse(
            [b"first ", b"second"], observed_backend="reported.synthetic.backend"
        ))
        runner = self.runner(provider)
        arguments = self.arguments()
        prepared = runner.prepare(self.identity(), arguments)
        self.assertEqual(prepared["arguments_sha256"], arguments.sha256)
        claimed = runner.claim("dispatch-1")
        self.assertEqual(claimed, arguments.canonical_json)

        receipt = runner.invoke("dispatch-1", call_deadline=150.0)

        self.assertEqual(provider.calls, [(arguments.canonical_json, 150.0)])
        self.assertEqual(receipt["state"], "captured")
        self.assertEqual(receipt["configured_backend"], "injected.synthetic.backend")
        self.assertEqual(receipt["observed_backend"], "reported.synthetic.backend")
        self.assertEqual(receipt["raw_bytes"], len(b"first second"))
        dispatch = read(receipt["dispatch_ref"])
        self.assertEqual(dispatch["kind"], "acquisition_dispatch_receipt")
        self.assertEqual((dispatch["operation_id"], dispatch["attempt_id"],
                          dispatch["dispatch_id"]),
                         ("operation-1", "attempt-1", "dispatch-1"))
        self.assertTrue(dispatch["invocation_started"])
        self.assertNotIn("raw_ref", dispatch)
        raw_path = Path(receipt["raw_ref"]["path"])
        self.assertEqual(raw_path.read_bytes(), b"first second")
        self.assertTrue(raw_path.is_relative_to(self.root))
        self.assertEqual(stat.S_IMODE(raw_path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(raw_path.stat().st_mode), 0o600)
        self.assertFalse(any(path.name.startswith(".raw-pending-")
                             for path in raw_path.parent.iterdir()))
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DISPATCH_FENCED"):
            runner.invoke("dispatch-1", call_deadline=160.0)
        self.assertEqual(len(provider.calls), 1)

    def test_claimed_restart_is_fenced_until_authoritative_not_dispatched_evidence(self):
        provider = CountingProvider()
        runner = self.runner(provider, "fence")
        runner.prepare(self.identity("dispatch-fence"), self.arguments())
        runner.claim("dispatch-fence")

        restarted = self.runner(provider, "fence")
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DISPATCH_FENCED"):
            restarted.claim("dispatch-fence")
        self.assertEqual(provider.calls, [])

        evidence = hashlib.sha256(b"caller assertion is not authority").hexdigest()
        with self.assertRaisesRegex(RunnerError, "NEGATIVE_EVIDENCE_UNTRUSTED"):
            restarted.record_definitely_not_dispatched(
                "dispatch-fence", evidence_sha256=evidence
            )
        self.assertEqual(restarted.journal("dispatch-fence")[-1]["state"], "claimed")
        self.assertEqual(provider.calls, [])

    def test_deadline_before_invocation_proves_zero_dispatches(self):
        provider = CountingProvider()
        runner = self.runner(provider, "deadline", run_deadline=99.0)
        runner.prepare(self.identity("dispatch-deadline"), self.arguments())
        runner.claim("dispatch-deadline")

        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DEADLINE_BEFORE_DISPATCH"):
            runner.invoke("dispatch-deadline", call_deadline=180.0)

        self.assertEqual(provider.calls, [])
        self.assertEqual([row["state"] for row in runner.journal("dispatch-deadline")], [
            "prepared", "claimed", "definitely_not_dispatched",
        ])

    def test_provider_exception_is_sanitized_and_fenced_as_possible_dispatch(self):
        secret = "synthetic-secret-token-DO-NOT-LEAK"
        provider = CountingProvider(error=RuntimeError(secret))
        runner = self.runner(provider, "unknown")
        runner.prepare(self.identity("dispatch-unknown"), self.arguments())
        runner.claim("dispatch-unknown")

        with self.assertRaisesRegex(RunnerError, "^ACQ_RUNNER_PROVIDER_OUTCOME_UNKNOWN$") as caught:
            runner.invoke("dispatch-unknown", call_deadline=150.0)

        self.assertNotIn(secret, str(caught.exception))
        journal_bytes = next((self.root / "unknown").glob("*.jsonl")).read_bytes()
        self.assertNotIn(secret.encode(), journal_bytes)
        self.assertEqual(runner.journal("dispatch-unknown")[-1]["state"],
                         "possibly_dispatched")
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DISPATCH_FENCED"):
            runner.claim("dispatch-unknown")
        self.assertEqual(len(provider.calls), 1)

    def test_reconciliation_closes_unknown_without_calling_provider(self):
        provider = CountingProvider(error=RuntimeError("synthetic failure"))
        runner = self.runner(provider, "reconcile")
        dispatch_id = "dispatch-reconcile"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)
        with self.assertRaises(RunnerError):
            runner.invoke(dispatch_id, call_deadline=150.0)
        calls_before = len(provider.calls)

        evidence = hashlib.sha256(b"immutable host receipt").hexdigest()
        receipt = runner.reconcile_captured(dispatch_id, evidence_sha256=evidence)

        self.assertEqual(receipt["status"], "reconciled")
        self.assertEqual(len(provider.calls), calls_before)
        self.assertEqual(runner.journal(dispatch_id)[-1]["state"], "captured")

    def test_raw_bound_is_hard_and_temporary_file_and_iterator_are_cleaned(self):
        chunks = ClosableChunks([b"1234", b"56789"])
        provider = CountingProvider(HostedProviderResponse(chunks))
        runner = self.runner(provider, "bounded", limit=8)
        dispatch_id = "dispatch-bounded"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)

        receipt = runner.invoke(dispatch_id, call_deadline=150.0)

        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["code"], "ACQ_RUNNER_RAW_LIMIT_EXCEEDED")
        self.assertTrue(chunks.closed)
        raw_directory = self.root / "bounded" / "raw"
        self.assertEqual(list(raw_directory.iterdir()), [])
        self.assertEqual(len(provider.calls), 1)

    def test_deadline_during_stream_closes_iterator_and_never_exposes_raw(self):
        clock = self.clock

        class DeadlineChunks(ClosableChunks):
            def __next__(self):
                value = super().__next__()
                clock.value = 151.0
                return value

        chunks = DeadlineChunks([b"partial synthetic body"])
        provider = CountingProvider(HostedProviderResponse(chunks))
        runner = self.runner(provider, "stream-deadline")
        dispatch_id = "dispatch-stream-deadline"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)

        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DEADLINE_AFTER_DISPATCH"):
            runner.invoke(dispatch_id, call_deadline=150.0)

        self.assertTrue(chunks.closed)
        self.assertEqual(list((self.root / "stream-deadline" / "raw").iterdir()), [])
        self.assertEqual(runner.journal(dispatch_id)[-1]["state"], "possibly_dispatched")

    def test_restart_recovers_invocation_started_to_unknown_and_cleans_orphans(self):
        provider = CountingProvider()
        runner = self.runner(provider, "recover-started")
        dispatch_id = "dispatch-recover-started"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)
        with runner._lock(dispatch_id):
            runner._append(dispatch_id, DispatchState.INVOCATION_STARTED)
        dispatch_raw = runner.raw_directory / dispatch_id
        dispatch_raw.mkdir(mode=0o700)
        orphan = dispatch_raw / ("f" * 64 + ".bin")
        orphan.write_bytes(b"orphan")
        pending = dispatch_raw / ".raw-pending-dead"
        pending.write_bytes(b"pending")

        restarted = self.runner(provider, "recover-started")
        self.assertEqual(restarted.journal(dispatch_id)[-1]["state"], "possibly_dispatched")
        result = restarted.recover_started(dispatch_id)

        self.assertEqual(result["state"], "possibly_dispatched")
        self.assertFalse(orphan.exists())
        self.assertFalse(pending.exists())
        with self.assertRaisesRegex(RunnerError, "DISPATCH_FENCED"):
            restarted.claim(dispatch_id)
        self.assertEqual(provider.calls, [])

    def test_captured_journal_receipt_gap_is_recoverable_without_redispatch(self):
        provider = CountingProvider()
        runner = self.runner(provider, "recover-receipt")
        dispatch_id = "dispatch-recover-receipt"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)
        evidence = hashlib.sha256(b"captured-before-receipt").hexdigest()
        with runner._lock(dispatch_id):
            runner._append(dispatch_id, DispatchState.INVOCATION_STARTED)
            runner._append(dispatch_id, DispatchState.CAPTURED,
                           evidence_sha256=evidence, status="captured",
                           configured_backend="injected.synthetic.backend",
                           observed_backend=None, raw_bytes=0)

        restarted = self.runner(provider, "recover-receipt")
        receipt = restarted.recover_captured_receipt(dispatch_id)

        verified = verify_dispatch_receipt(receipt["dispatch_ref"])
        self.assertEqual(verified["dispatch_id"], dispatch_id)
        self.assertEqual(verified["evidence_sha256"], evidence)
        self.assertEqual(provider.calls, [])

    def test_noncooperative_provider_is_bounded_and_fenced_without_worker(self):
        def blocking_provider(_arguments, _deadline):
            time.sleep(1)
            return HostedProviderResponse([b"late"])

        deadline = time.monotonic() + 0.05
        runner = HostedAcquisitionRunner(
            self.root / "blocked-provider", provider=blocking_provider,
            configured_backend="injected.synthetic.backend",
            run_deadline=deadline, raw_byte_limit=1024,
        )
        dispatch_id = "dispatch-blocked"
        runner.prepare(self.identity(dispatch_id), self.arguments())
        runner.claim(dispatch_id)
        started = time.monotonic()
        with self.assertRaisesRegex(RunnerError, "DEADLINE_AFTER_DISPATCH"):
            runner.invoke(dispatch_id, call_deadline=deadline)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(runner.journal(dispatch_id)[-1]["state"], "possibly_dispatched")
        self.assertFalse(any(path.name.startswith(".raw-pending-")
                             for path in runner.raw_directory.iterdir()))

    def test_unvalidated_dispatch_id_cannot_escape_private_runner_root(self):
        provider = CountingProvider()
        runner = self.runner(provider, "paths")

        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_DISPATCH_ID_INVALID"):
            runner.claim("../escape")

        self.assertEqual(provider.calls, [])
        self.assertFalse((self.root / "escape.lock").exists())

    def test_journal_is_append_only_hash_chained_and_projection_hides_arguments(self):
        provider = CountingProvider()
        runner = self.runner(provider, "journal")
        dispatch_id = "dispatch-journal"
        arguments = self.arguments()
        runner.prepare(self.identity(dispatch_id), arguments)
        runner.claim(dispatch_id)
        runner.invoke(dispatch_id, call_deadline=150.0)

        path = next((self.root / "journal").glob("*.jsonl"))
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual([row["sequence"] for row in rows], list(range(len(rows))))
        self.assertEqual(rows[1]["previous_event_sha256"], rows[0]["event_sha256"])
        projection = runner.journal(dispatch_id)
        self.assertNotIn("arguments_b64", repr(projection))
        self.assertNotIn("example.test", repr(projection))
        self.assertNotIn("raw_ref", repr(projection))
        self.assertNotIn(str(self.root), repr(projection))

        rows[0]["configured_backend"] = "tampered"
        path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n")
        with self.assertRaisesRegex(RunnerError, "ACQ_RUNNER_JOURNAL_INVALID"):
            runner.journal(dispatch_id)


if __name__ == "__main__":
    unittest.main()
