from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import builtins
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from mentor.scheduler import WorkOrder
from mentor.scheduler import job_adapter
from mentor.scheduler.contracts import canonical_json_bytes, strict_json_loads
from mentor.scheduler.resilience_candidate import (
    CandidateInputs,
    CandidateSource,
    CandidateValidationError,
    ResilienceCandidateBundle,
    build_resilience_candidate,
    validate_candidate_bundle,
)
from shared.job_runtime.config import load
from shared.job_runtime.engine import validate_job

UTC = timezone.utc
ROOT = Path(__file__).resolve().parents[1]


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def plain(value):
    return json.loads(json.dumps(value))


class SchedulerResilienceCandidateTest(unittest.TestCase):
    def setUp(self):
        self.start = datetime(2035, 1, 2, 10, 0, tzinfo=UTC)
        self.profile = {
            "auth_home": "/synthetic/private-auth",
            "model": "synthetic-model",
            "timeout_seconds": 60,
        }
        self.inputs = CandidateInputs(
            work_order_id="resilience-canonical-new",
            logical_session_id="resilience-canonical-new",
            job_id="resilience-job-new",
            owner_id="resilience-canonical-new",
            work_order_path=".job-runtime/acceptance/resilience-new/work-order.json",
            state_directory=".job-runtime/acceptance/resilience-new/state",
            candidate_manifest_path=".job-runtime/acceptance/resilience-new/candidate-manifest.json",
            plan_path="plans/resilience-plan.md",
            plan_sha256="1" * 64,
            acceptance_path="plans/resilience-acceptance.json",
            acceptance_sha256="2" * 64,
            sources=(CandidateSource("candidate/source.py", "3" * 64),),
            expected_model_profile="resilience-profile",
            model_profile_sha256=job_adapter.profile_fingerprint(self.profile),
            prompt_file="prompts/resilience.md",
            slot_1=self.start + timedelta(minutes=10),
            slot_2=self.start + timedelta(minutes=20),
            starts_at=self.start,
            ends_at=self.start + timedelta(hours=1),
            turn_timeout_seconds=60,
            grace_seconds=120,
            forbidden_ids=("historical-work", "historical-job"),
        )

    def assert_invalid(self, inputs, code):
        with self.assertRaisesRegex(CandidateValidationError, "^" + code + "$"):
            build_resilience_candidate(inputs)

    def test_build_is_deterministic_redacted_immutable_and_performs_no_io(self):
        with mock.patch.object(builtins, "open", side_effect=AssertionError("I/O forbidden")), \
             mock.patch.object(Path, "open", side_effect=AssertionError("I/O forbidden")), \
             mock.patch.object(Path, "write_text", side_effect=AssertionError("I/O forbidden")), \
             mock.patch.object(Path, "write_bytes", side_effect=AssertionError("I/O forbidden")), \
             mock.patch.object(os, "open", side_effect=AssertionError("I/O forbidden")):
            first = build_resilience_candidate(self.inputs)
            second = build_resilience_candidate(self.inputs)
            documents = first.to_json_documents()
        self.assertEqual(first.spec_sha256, second.spec_sha256)
        self.assertEqual(documents, second.to_json_documents())
        self.assertEqual(repr(self.inputs), "CandidateInputs(<redacted>)")
        self.assertEqual(repr(first), "ResilienceCandidateBundle(<redacted>)")
        self.assertNotIn(self.inputs.plan_path, repr(self.inputs))
        self.assertNotIn(self.inputs.plan_sha256, repr(first))
        with self.assertRaises(FrozenInstanceError):
            self.inputs.job_id = "mutated"
        with self.assertRaisesRegex(TypeError, "CANDIDATE_BUNDLE_IMMUTABLE"):
            first.work_order["schema_version"] = 2
        with self.assertRaisesRegex(TypeError, "CANDIDATE_BUNDLE_IMMUTABLE"):
            first.allocation["jobs"][0]["enabled"] = True

    def test_exact_fixed_shapes_two_slots_disabled_and_canonical_documents(self):
        bundle = build_resilience_candidate(self.inputs)
        work = bundle.work_order
        job = bundle.allocation["jobs"][0]
        self.assertEqual(
            (
                work["work_order_id"],
                work["logical_session"]["logical_session_id"],
                job["adapter_config"]["owner_id"],
            ),
            (self.inputs.work_order_id,) * 3,
        )
        self.assertNotEqual(job["id"], self.inputs.work_order_id)
        self.assertEqual(set(work), {
            "schema_version", "work_order_id", "logical_session", "plan", "acceptance",
            "execution", "supervision", "evidence_policy", "completion",
        })
        self.assertEqual((work["logical_session"]["max_provider_threads"], work["execution"]["max_turns"]), (2, 2))
        self.assertEqual(work["supervision"], {
            "max_no_progress_cycles": 2, "max_repeated_actions": 2, "max_interventions": 0,
        })
        self.assertEqual(work["evidence_policy"], {
            "record_all_variants": True, "max_variants": 1,
            "max_reused_evaluations": 0, "worker_holdout_access": False,
        })
        self.assertEqual(work["completion"]["required_event_kinds"], ("provider_thread", "cycle"))
        self.assertIs(job["enabled"], False)
        self.assertIs(job["replay_safe"], True)
        self.assertEqual(job["adapter"], "mentor.scheduler.job_adapter:prepare")
        self.assertEqual(job["schedule"]["kind"], "sequence")
        self.assertEqual(len(job["schedule"]["timestamps"]), 2)
        self.assertEqual(set(job["adapter_config"]), job_adapter._OPTIONS)
        self.assertNotIn("email", json.dumps(bundle.allocation).lower())
        self.assertNotIn("business", json.dumps(bundle.allocation).lower())

        documents = bundle.to_json_documents()
        self.assertEqual(set(documents), {
            "work-order.json", "allocation.json", "candidate-manifest.json",
        })
        expected_values = (bundle.work_order, bundle.allocation, bundle.candidate_manifest)
        for name, value in zip(("work-order.json", "allocation.json", "candidate-manifest.json"), expected_values):
            self.assertTrue(documents[name].endswith(b"\n"))
            self.assertEqual(documents[name], canonical_json_bytes(plain(value)))
            self.assertEqual(strict_json_loads(documents[name].decode("utf-8")), plain(value))
        self.assertNotIn("acceptance.json", documents)
        self.assertIsNone(validate_candidate_bundle(bundle))

    def _materialize(self, workspace: Path, bundle: ResilienceCandidateBundle):
        for relative in (
            "plans", "prompts", "candidate", ".job-runtime", ".job-runtime/config",
            ".job-runtime/auth", ".job-runtime/acceptance",
            ".job-runtime/acceptance/resilience-new",
            ".job-runtime/acceptance/resilience-new/state",
        ):
            path = workspace / relative
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            path.chmod(0o700)
        plan = workspace / self.inputs.plan_path
        plan.write_text("# finite resilience plan\n", encoding="utf-8")
        acceptance = workspace / self.inputs.acceptance_path
        acceptance.write_text(json.dumps({
            "schema_version": 1,
            "criteria": [
                {"criterion_id": "closed-response", "critical": True},
                {"criterion_id": "frozen-binding", "critical": True},
            ],
        }), encoding="utf-8")
        source = workspace / self.inputs.sources[0].path
        source.write_text("VALUE = 1\n", encoding="utf-8")
        prompt = workspace / self.inputs.prompt_file
        prompt.write_text("Run one synthetic resilience cycle.\n", encoding="utf-8")
        prompt.chmod(0o600)
        return plan, acceptance, source

    def test_materialized_documents_parse_through_work_order_config_engine_and_adapter(self):
        parent = ROOT / "runtime/test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="resilience-candidate-", dir=parent) as temporary:
            workspace = Path(temporary)
            workspace.chmod(0o700)
            provisional = build_resilience_candidate(self.inputs)
            plan, acceptance, source = self._materialize(workspace, provisional)
            inputs = replace(
                self.inputs,
                plan_sha256=digest_bytes(plan.read_bytes()),
                acceptance_sha256=digest_bytes(acceptance.read_bytes()),
                sources=(CandidateSource(self.inputs.sources[0].path, digest_bytes(source.read_bytes())),),
                model_profile_sha256=job_adapter.profile_fingerprint({
                    **self.profile,
                    "auth_home": str(workspace / ".job-runtime/auth"),
                }),
            )
            profile = {**self.profile, "auth_home": str(workspace / ".job-runtime/auth")}
            bundle = build_resilience_candidate(inputs)
            documents = bundle.to_json_documents()
            (workspace / inputs.work_order_path).write_bytes(documents["work-order.json"])
            (workspace / inputs.candidate_manifest_path).write_bytes(documents["candidate-manifest.json"])
            allocation_path = workspace / ".job-runtime/config/allocation.json"
            allocation_path.write_bytes(documents["allocation.json"])
            allocation_path.chmod(0o600)
            config_path = workspace / ".job-runtime/config/runtime.json"
            config_path.write_bytes(canonical_json_bytes({
                "schema_version": 1,
                "tick_seconds": 1,
                "heartbeat_seconds": 1,
                "stale_seconds": 30,
                "max_workers": 1,
                "retry": {"max_attempts": 1, "backoff_seconds": 1, "max_backoff_seconds": 1},
                "model_profiles": {inputs.expected_model_profile: profile},
                "allocation_files": [".job-runtime/config/allocation.json"],
                "source_paths": [],
            }))
            config_path.chmod(0o600)
            order = WorkOrder.from_json(documents["work-order.json"].decode("utf-8"), workspace)
            loaded_config, jobs = load(config_path, workspace)
            self.assertEqual(order.work_order_id, inputs.work_order_id)
            self.assertEqual(loaded_config["schema_version"], 1)
            self.assertEqual(len(jobs), 1)
            validate_job(jobs[0])
            self.assertFalse(jobs[0]["enabled"])
            options = jobs[0]["adapter_config"]
            self.assertEqual(set(options), job_adapter._OPTIONS)
            manifest, snapshots, descriptors = job_adapter._candidate_open(options, workspace)
            try:
                self.assertEqual(manifest[3], options["candidate_manifest_sha256"])
                self.assertEqual(len(snapshots), 1)
            finally:
                for descriptor in descriptors:
                    os.close(descriptor)
            invalid = job_adapter.prepare(
                {**options, "extra": True}, workspace, {}, {}
            )
            self.assertEqual(invalid, {
                "status": "failed", "code": "MENTOR_JOB_OPTIONS_INVALID",
            })

    def test_spec_changes_for_work_order_allocation_manifest_and_profile_drift(self):
        baseline = build_resilience_candidate(self.inputs)
        changes = (
            replace(self.inputs, plan_sha256="4" * 64),
            replace(self.inputs, prompt_file="prompts/other.md"),
            replace(self.inputs, sources=(CandidateSource("candidate/source.py", "5" * 64),)),
            replace(self.inputs, model_profile_sha256="6" * 64),
        )
        for changed in changes:
            with self.subTest(changed=repr(changed)):
                self.assertNotEqual(build_resilience_candidate(changed).spec_sha256, baseline.spec_sha256)

        changed_work = plain(baseline.work_order)
        changed_work["plan"]["sha256"] = "7" * 64
        forged = ResilienceCandidateBundle(
            changed_work, baseline.allocation, baseline.candidate_manifest, baseline.spec_sha256
        )
        with self.assertRaisesRegex(CandidateValidationError, "^CANDIDATE_SPEC_MISMATCH$"):
            validate_candidate_bundle(forged)

    def test_invalid_identifiers_reuse_paths_hashes_sources_and_strict_ints(self):
        cases = (
            (replace(self.inputs, work_order_id="bad/id"), "CANDIDATE_ID_INVALID"),
            (replace(self.inputs, job_id="j" * 97), "CANDIDATE_ID_INVALID"),
            (replace(self.inputs, work_order_id="identity-other"), "CANDIDATE_IDENTITY_MISMATCH"),
            (replace(self.inputs, logical_session_id="identity-other"), "CANDIDATE_IDENTITY_MISMATCH"),
            (replace(self.inputs, owner_id="identity-other"), "CANDIDATE_IDENTITY_MISMATCH"),
            (replace(
                self.inputs,
                work_order_id="historical-work",
                logical_session_id="historical-work",
                owner_id="historical-work",
            ), "CANDIDATE_ID_REUSED"),
            (replace(self.inputs, work_order_path="work-order.json"), "CANDIDATE_PATH_INVALID"),
            (replace(self.inputs, state_directory=".job-runtime/acceptance/../state"), "CANDIDATE_PATH_INVALID"),
            (replace(self.inputs, candidate_manifest_path=".job-runtime/acceptance/x/manifest.json"), "CANDIDATE_PATH_INVALID"),
            (replace(self.inputs, prompt_file=".hidden/prompt.md"), "CANDIDATE_PATH_INVALID"),
            (replace(self.inputs, prompt_file="prompts/resilience.json"), "CANDIDATE_PATH_INVALID"),
            (replace(self.inputs, plan_sha256="A" * 64), "CANDIDATE_HASH_INVALID"),
            (replace(self.inputs, model_profile_sha256="0" * 63), "CANDIDATE_HASH_INVALID"),
            (replace(self.inputs, sources=()), "CANDIDATE_SOURCE_INVALID"),
            (replace(self.inputs, sources=(
                CandidateSource("candidate/source.py", "3" * 64),
                CandidateSource("candidate/source.py", "4" * 64),
            )), "CANDIDATE_SOURCE_INVALID"),
            (replace(self.inputs, turn_timeout_seconds=True), "CANDIDATE_TIMEOUT_INVALID"),
            (replace(self.inputs, grace_seconds=True), "CANDIDATE_GRACE_INVALID"),
            (replace(self.inputs, forbidden_ids=(["unhashable"],)), "CANDIDATE_ID_INVALID"),
            (replace(self.inputs, forbidden_ids=({"unhashable": True},)), "CANDIDATE_ID_INVALID"),
        )
        for value, code in cases:
            with self.subTest(code=code):
                self.assert_invalid(value, code)

        for field in ("work_order_id", "logical_session_id", "job_id", "owner_id"):
            current = getattr(self.inputs, field)
            with self.subTest(reused=field):
                self.assert_invalid(
                    replace(self.inputs, forbidden_ids=(current,)), "CANDIDATE_ID_REUSED"
                )

    def test_invalid_time_order_window_and_grace_matrix(self):
        naive = self.inputs.slot_1.replace(tzinfo=None)
        plus_one = timezone(timedelta(hours=1))
        cases = (
            (replace(self.inputs, slot_1=naive), "CANDIDATE_TIME_INVALID"),
            (replace(self.inputs, slot_1=self.inputs.slot_1.astimezone(plus_one)), "CANDIDATE_TIME_INVALID"),
            (replace(self.inputs, slot_1=self.inputs.slot_2), "CANDIDATE_TIME_INVALID"),
            (replace(self.inputs, slot_1=self.inputs.starts_at), "CANDIDATE_TIME_INVALID"),
            (replace(self.inputs, ends_at=self.inputs.starts_at), "CANDIDATE_WINDOW_INVALID"),
            (replace(self.inputs, ends_at=self.inputs.starts_at + timedelta(days=8)), "CANDIDATE_WINDOW_INVALID"),
            (replace(self.inputs, grace_seconds=0), "CANDIDATE_GRACE_INVALID"),
            (replace(self.inputs, grace_seconds=10_801), "CANDIDATE_GRACE_INVALID"),
            (replace(
                self.inputs,
                slot_2=self.inputs.ends_at - timedelta(seconds=30),
                grace_seconds=31,
            ), "CANDIDATE_GRACE_INVALID"),
        )
        for value, code in cases:
            with self.subTest(code=code):
                self.assert_invalid(value, code)

    def test_bundle_exact_keys_reject_extras_and_type_drift(self):
        baseline = build_resilience_candidate(self.inputs)
        mutations = []
        work = plain(baseline.work_order)
        work["extra"] = True
        mutations.append((work, baseline.allocation, baseline.candidate_manifest))
        allocation = plain(baseline.allocation)
        allocation["jobs"][0]["extra"] = True
        mutations.append((baseline.work_order, allocation, baseline.candidate_manifest))
        manifest = plain(baseline.candidate_manifest)
        manifest["extra"] = True
        mutations.append((baseline.work_order, baseline.allocation, manifest))
        bool_timeout = plain(baseline.work_order)
        bool_timeout["execution"]["turn_timeout_seconds"] = True
        mutations.append((bool_timeout, baseline.allocation, baseline.candidate_manifest))
        bool_schema = plain(baseline.work_order)
        bool_schema["schema_version"] = True
        mutations.append((bool_schema, baseline.allocation, baseline.candidate_manifest))
        bool_supervision = plain(baseline.work_order)
        bool_supervision["supervision"]["max_interventions"] = False
        mutations.append((bool_supervision, baseline.allocation, baseline.candidate_manifest))
        bool_manifest = plain(baseline.candidate_manifest)
        bool_manifest["schema_version"] = True
        mutations.append((baseline.work_order, baseline.allocation, bool_manifest))
        bool_allocation = plain(baseline.allocation)
        bool_allocation["schema_version"] = True
        mutations.append((baseline.work_order, bool_allocation, baseline.candidate_manifest))
        mismatched_owner = plain(baseline.allocation)
        mismatched_owner["jobs"][0]["adapter_config"]["owner_id"] = "identity-other"
        mutations.append((baseline.work_order, mismatched_owner, baseline.candidate_manifest))
        mismatched_logical = plain(baseline.work_order)
        mismatched_logical["logical_session"]["logical_session_id"] = "identity-other"
        mutations.append((mismatched_logical, baseline.allocation, baseline.candidate_manifest))
        base_options = plain(baseline.allocation)["jobs"][0]["adapter_config"]
        for left, right in (
            ("work_order_path", "state_directory"),
            ("work_order_path", "candidate_manifest_path"),
            ("state_directory", "candidate_manifest_path"),
        ):
            collision = plain(baseline.allocation)
            collision["jobs"][0]["adapter_config"][left] = base_options[right]
            mutations.append((baseline.work_order, collision, baseline.candidate_manifest))
        for work_value, allocation_value, manifest_value in mutations:
            with self.subTest():
                forged = ResilienceCandidateBundle(
                    work_value, allocation_value, manifest_value, baseline.spec_sha256
                )
                with self.assertRaisesRegex(CandidateValidationError, "^CANDIDATE_BUNDLE_INVALID$"):
                    validate_candidate_bundle(forged)


if __name__ == "__main__":
    unittest.main()
