"""Provider-free post-run acquisition acceptance publication tests."""
import json
import os
import unittest

from investment.research.acquisition_acceptance import (
    AcquisitionAcceptanceError,
    _atomic_registry_at,
    _open_private_directory,
    publish_acquisition_acceptance,
)
from investment.research.tests import test_acquisition_live_session as live_fixture
from shared.job_runtime.service import atomic
from shared.research_sources.artifacts import read, save


class AcquisitionAcceptanceTests(unittest.TestCase):
    def finalized_session(self):
        fixture = live_fixture.LiveSessionTests(methodName="test_full_cooperative_cli_path_has_three_dispatches_and_checker_1_of_1")
        fixture.operational_source = live_fixture.OperationalEvidenceSource.HOST_RETURNED
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.cli("init", payload=fixture.v2_spec("narrow"))
        search = fixture.cli("next")
        fixture.operational_capture(search,
                    {**fixture.capture_identity(), "status": "returned",
                     "observed_backend": "native_tools.web__run"},
                    f"Official results: {live_fixture.PDF_URL} and {live_fixture.HTML_URL}")
        primary = fixture.cli("next")
        fixture.operational_capture(primary,
                    {**fixture.capture_identity(), "status": "returned",
                     "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"},
                     "observed_backend": "native_tools.web__run"},
                    {"diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"}})
        alternate = fixture.cli("next")
        fixture.operational_capture(alternate,
                    {**fixture.capture_identity(), "status": "returned",
                     "observed_backend": "native_tools.web__run"},
                    f"Synthetic source ({live_fixture.HTML_URL})\nL0: {live_fixture.BODY}")
        fixture.cli("assess", payload={
            "operation_id": alternate["operation_id"],
            "assessor_version": "assessment-author",
            "assessments": [{"question_id": live_fixture.QUESTION_ID,
                             "quote": live_fixture.QUOTE,
                             "disposition": "candidate_support"}],
        })
        fixture.operational_review({
            "reviewer_id": "independent-reviewer",
            "assessment_author_id": "assessment-author",
            "live_operator_id": "hosted-operator",
            "disposition": "approve",
            "checks": {"question_relevance": True, "literal_support": True,
                       "canonical_lineage": True},
            "reason": "The bounded question, literal quote and lineage agree.",
        })
        fixture.cli("finalize")
        return fixture

    def publish(self, fixture):
        registry_root = fixture.root / "acceptance-registry"
        registry_root.mkdir(mode=0o700, exist_ok=True)
        return publish_acquisition_acceptance(
            fixture.session, subject="SYN",
            registry_path=registry_root / "datasource-registry.json",
            publication_directory=fixture.root / "acceptance-publication")

    def test_publishes_bounded_envelope_registers_and_exactly_reads_back(self):
        fixture = self.finalized_session()
        first = self.publish(fixture)
        second = self.publish(fixture)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["envelope_sha256"], second["envelope_sha256"])
        self.assertEqual((first["checker_status"], first["complete_chains"],
                          first["credited_units"], first["actual_dispatches"]),
                         ("pass", 1, 1, 3))
        self.assertTrue(first["live_acceptance_eligible"])
        self.assertFalse(first["cryptographic_remote_attestation"])
        self.assertEqual(first["actual_dispatches"], 3)

        registry = json.loads((fixture.root / "acceptance-registry/datasource-registry.json").read_text())
        self.assertEqual(len(registry["acquisition_comparison_refs"]), 1)
        envelope = read(registry["acquisition_comparison_refs"][0]["report_ref"])
        self.assertEqual(envelope["execution_id"], fixture.execution_id)
        self.assertEqual(envelope["host_profile_sha256"], first["host_profile_sha256"])
        self.assertEqual(envelope["config_sha256"], first["config_sha256"])
        self.assertEqual(envelope["checker_verdict"]["complete_chains"], 1)
        self.assertEqual(envelope["checker_verdict"]["credited_units"], 1)
        self.assertEqual(len(envelope["host_invocation_refs"]), 3)
        self.assertEqual(envelope["trust_policy"], "operational_host_evidence")
        self.assertTrue(envelope["live_acceptance_eligible"])
        self.assertFalse(envelope["cryptographic_remote_attestation"])
        public = json.dumps(envelope)
        for forbidden in ("Synthetic canonical disclosure states", "hosted-operator",
                          "opaque_receipt_id", "credential_values_present", "raw_result"):
            self.assertNotIn(forbidden, public)

    def test_same_subject_execution_cannot_be_rebound_to_changed_envelope(self):
        fixture = self.finalized_session()
        first = self.publish(fixture)
        registry_path = fixture.root / "acceptance-registry/datasource-registry.json"
        registry = json.loads(registry_path.read_text())
        original = read(registry["acquisition_comparison_refs"][0]["report_ref"])
        conflicting = save(fixture.root / "acceptance-publication/envelopes",
                           {**original, "scope": "different"})
        registry["acquisition_comparison_refs"][0]["report_ref"] = conflicting
        atomic(registry_path, registry)
        with self.assertRaisesRegex(AcquisitionAcceptanceError,
                                    "ACQ_ACCEPTANCE_PUBLICATION_CONFLICT"):
            self.publish(fixture)
        self.assertEqual(first["execution_id"], fixture.execution_id)

    def test_rejects_result_whose_host_profile_is_not_config_bound(self):
        fixture = self.finalized_session()
        state_path = fixture.session / "session.json"
        state = json.loads(state_path.read_text())
        result = read(state["final_ref"])
        unrelated = save(fixture.root / "session/artifacts", {
            "kind": "acquisition_host_profile",
            "profile": {"configured_backend": result["configured_backend"],
                        "mcp": None, "credential": {
                            "credential_value_present": False,
                            "profile_ref": "different-profile"}},
        })
        changed = save(fixture.root / "session/artifacts",
                       {**result, "host_profile_ref": unrelated})
        state["host_profile_ref"] = unrelated
        state["final_ref"] = changed
        atomic(state_path, state)
        with self.assertRaisesRegex(AcquisitionAcceptanceError,
                                    "ACQ_ACCEPTANCE_CONTEXT_BINDING_INVALID"):
            self.publish(fixture)

    def test_core_rejects_unsealed_subject_and_default_registry(self):
        fixture = self.finalized_session()
        with self.assertRaisesRegex(AcquisitionAcceptanceError,
                                    "ACQ_ACCEPTANCE_CASE_INVALID"):
            publish_acquisition_acceptance(
                fixture.session, subject="TST",
                registry_path=fixture.root / "acceptance-registry/registry.json",
                publication_directory=fixture.root / "publication")
        with self.assertRaisesRegex(AcquisitionAcceptanceError,
                                    "ACQ_ACCEPTANCE_REGISTRY_REQUIRED"):
            publish_acquisition_acceptance(
                fixture.session, subject="SYN", registry_path=None,
                publication_directory=fixture.root / "publication")

    def test_core_rejects_secret_shaped_identity_before_publication(self):
        for secret in (
                "access_token",
                "sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "ghr_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234",
                "github_pat_ABCDEFGHIJKLMNOPQRSTUVWX",
                "GITHUB_PAT_ABCDEFGHIJKLMNOPQRSTUVWX",
                "eyJAAAAAAAAAAAAAAAAAAAA.BBBBBBBBBBBBBBBB.CCCCCCCCCCCCCCCC"):
            with self.subTest(secret=secret[:8]):
                fixture = self.finalized_session()
                state_path = fixture.session / "session.json"
                state = json.loads(state_path.read_text())
                result = read(state["final_ref"])
                changed = save(fixture.root / "session/artifacts",
                               {**result, "trace_id": secret})
                state["identities"] = {**state["identities"],
                                       "trace_id": secret}
                state["final_ref"] = changed
                atomic(state_path, state)
                publication = fixture.root / "publication"
                with self.assertRaisesRegex(
                        AcquisitionAcceptanceError,
                        "ACQ_ACCEPTANCE_IDENTITY_INVALID"):
                    publish_acquisition_acceptance(
                        fixture.session, subject="SYN",
                        registry_path=fixture.root / "acceptance-registry/registry.json",
                        publication_directory=publication)
                self.assertFalse(publication.exists())
                self.assertFalse((fixture.root / "acceptance-registry/registry.json").exists())

    def test_core_rejects_equal_and_nested_roots_before_effects(self):
        cases = ("equal", "registry-under-session", "publication-ancestor")
        for case in cases:
            with self.subTest(case=case):
                fixture = self.finalized_session()
                registry_root = fixture.root / "acceptance-registry"
                registry_root.mkdir(mode=0o700)
                registry = registry_root / "registry.json"
                publication = fixture.root / "acceptance-publication"
                if case == "equal":
                    publication = fixture.session
                elif case == "registry-under-session":
                    registry = fixture.session / "nested-registry.json"
                else:
                    publication = fixture.root
                with self.assertRaisesRegex(
                        AcquisitionAcceptanceError,
                        "ACQ_ACCEPTANCE_ROOT_OVERLAP"):
                    publish_acquisition_acceptance(
                        fixture.session, subject="SYN",
                        registry_path=registry,
                        publication_directory=publication)
                self.assertFalse(registry.exists())
                if publication not in (fixture.session, fixture.root):
                    self.assertFalse(publication.exists())

    def test_registry_lock_rejects_symlink_fifo_and_insecure_mode(self):
        for kind in ("symlink", "fifo", "insecure"):
            with self.subTest(kind=kind):
                fixture = self.finalized_session()
                registry = fixture.root / "acceptance-registry/datasource-registry.json"
                registry.parent.mkdir(mode=0o700, exist_ok=True)
                lock = registry.with_name(registry.name + ".lock")
                if kind == "symlink":
                    target = fixture.root / "outside-lock"
                    target.write_text("outside")
                    lock.symlink_to(target)
                elif kind == "fifo":
                    os.mkfifo(lock, 0o600)
                else:
                    lock.write_text("")
                    lock.chmod(0o666)
                with self.assertRaisesRegex(
                        AcquisitionAcceptanceError,
                        "ACQ_ACCEPTANCE_REGISTRY_LOCK_INVALID"):
                    self.publish(fixture)

    def test_dirfd_write_stays_in_held_directory_after_ancestor_swap(self):
        fixture = self.finalized_session()
        original = fixture.root / "registry-parent"
        original.mkdir(mode=0o700)
        descriptor = _open_private_directory(original, create=False)
        moved = fixture.root / "held-registry-parent"
        outside = fixture.root / "outside-parent"
        outside.mkdir(mode=0o700)
        original.rename(moved)
        original.symlink_to(outside, target_is_directory=True)
        try:
            _atomic_registry_at(descriptor, "registry.json", {"schema_version": 1})
        finally:
            os.close(descriptor)
        self.assertTrue((moved / "registry.json").is_file())
        self.assertFalse((outside / "registry.json").exists())


if __name__ == "__main__":
    unittest.main()
