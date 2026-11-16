"""Provider-free tests for the bounded acquisition acceptance CLI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock
import uuid

import investment.research.acquisition_acceptance as acceptance_module
import investment.research.acquisition_acceptance_cli as cli_module
from investment.research.acquisition_acceptance_cli import (
    AcquisitionAcceptanceCliError,
    describe,
    publish,
    verify,
)
from investment.research.tests import test_acquisition_live_session as live_fixture
from shared.research_sources.artifacts import ROOT
from shared.research_sources.host_adapter_contracts import OperationalEvidenceSource


class AcquisitionAcceptanceCliTests(unittest.TestCase):
    def fixture(self, *, run_kind="narrow",
                source=OperationalEvidenceSource.HOST_RETURNED):
        fixture = live_fixture.LiveSessionTests(
            methodName=(
                "test_full_cooperative_cli_path_has_three_dispatches_and_checker_1_of_1"
            ))
        fixture.operational_source = source
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.cli("init", payload=fixture.v2_spec(run_kind))
        search = fixture.cli("next")
        fixture.operational_capture(
            search,
            {**fixture.capture_identity(), "status": "returned",
             "observed_backend": "native_tools.web__run"},
            f"Official results: {live_fixture.PDF_URL} and {live_fixture.HTML_URL}",
        )
        if run_kind == "smoke":
            fixture.cli("finalize")
            return fixture
        primary = fixture.cli("next")
        fixture.operational_capture(
            primary,
            {**fixture.capture_identity(), "status": "returned",
             "diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"},
             "observed_backend": "native_tools.web__run"},
            {"diagnostic": {"code": "HOST_WEB_BODY_TOO_LARGE"}},
        )
        alternate = fixture.cli("next")
        fixture.operational_capture(
            alternate,
            {**fixture.capture_identity(), "status": "returned",
             "observed_backend": "native_tools.web__run"},
            f"Synthetic source ({live_fixture.HTML_URL})\nL0: {live_fixture.BODY}",
        )
        fixture.cli("assess", payload={
            "operation_id": alternate["operation_id"],
            "assessor_version": "assessment-author",
            "assessments": [{
                "question_id": live_fixture.QUESTION_ID,
                "quote": live_fixture.QUOTE,
                "disposition": "candidate_support",
            }],
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

    @staticmethod
    def paths(fixture):
        registry_root = fixture.root / "acceptance-registry"
        publication = fixture.root / "acceptance-publication"
        registry_root.mkdir(mode=0o700)
        publication.mkdir(mode=0o700)
        return registry_root / "registry.json", publication

    def test_describe_is_bounded_and_side_effect_free(self):
        result = describe()
        self.assertEqual(result["commands"], ["describe", "publish", "verify"])
        self.assertEqual(result["side_effects"]["verify"], [])
        self.assertIn("provider_call", result["prohibited"])
        self.assertLess(len(json.dumps(result).encode()), 16 * 1024)

    def test_publish_verify_and_exact_replay(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        first = publish(
            session_root=fixture.session, subject="SYN",
            expected_execution_id=fixture.execution_id,
            registry_path=registry, publication_root=publication)
        second = publish(
            session_root=fixture.session, subject="SYN",
            expected_execution_id=fixture.execution_id,
            registry_path=registry, publication_root=publication)
        checked = verify(
            session_root=fixture.session, subject="SYN",
            expected_execution_id=fixture.execution_id,
            registry_path=registry)
        self.assertFalse(first["idempotent_replay"])
        self.assertTrue(second["idempotent_replay"])
        self.assertEqual(first["envelope_sha256"], second["envelope_sha256"])
        self.assertEqual((checked["status"], checked["checker_status"],
                          checked["complete_chains"], checked["credited_units"],
                          checked["actual_dispatches"]),
                         ("verified", "pass", 1, 1, 3))
        self.assertTrue(checked["live_acceptance_eligible"])
        self.assertNotIn(str(fixture.root), json.dumps(first) + json.dumps(checked))

    def test_cli_publish_and_verify_return_only_sanitized_json(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        base = [sys.executable, "-m",
                "investment.research.acquisition_acceptance_cli"]
        common = ["--session-root", str(fixture.session), "--subject", "SYN",
                  "--expected-execution-id", fixture.execution_id,
                  "--registry", str(registry)]
        published = subprocess.run(
            [*base, "publish", *common, "--publication-root", str(publication)],
            cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True, capture_output=True, timeout=30)
        self.assertEqual(published.returncode, 0, published.stdout + published.stderr)
        verified = subprocess.run(
            [*base, "verify", *common], cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            text=True, capture_output=True, timeout=30)
        self.assertEqual(verified.returncode, 0, verified.stdout + verified.stderr)
        for result in (published, verified):
            value = json.loads(result.stdout)
            self.assertNotIn(str(fixture.root), result.stdout)
            self.assertLess(len(result.stdout.encode()), 16 * 1024)
            self.assertIn(value["status"], {"published", "verified"})

    def test_rejects_identity_mismatch_and_verify_before_publish(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_EXECUTION_MISMATCH"):
            publish(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=str(uuid.uuid4()),
                registry_path=registry, publication_root=publication)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID"):
            verify(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=registry)

    def test_smoke_and_synthetic_runs_cannot_publish(self):
        smoke = self.fixture(run_kind="smoke")
        registry, publication = self.paths(smoke)
        with self.assertRaisesRegex(Exception, "ACQ_ACCEPTANCE_SMOKE_NOT_PUBLISHABLE"):
            publish(
                session_root=smoke.session, subject="SYN",
                expected_execution_id=smoke.execution_id,
                registry_path=registry, publication_root=publication)
        with self.assertRaisesRegex(Exception, "LIVE_CUSTODY_CREDENTIAL_STALE"):
            self.fixture(source=OperationalEvidenceSource.SYNTHETIC)

    def test_rejects_symlink_session_and_registry_outside_runtime_roots(self):
        fixture = self.fixture()
        link = fixture.root / "session-link"
        link.symlink_to(fixture.session, target_is_directory=True)
        registry, publication = self.paths(fixture)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_SESSION_INVALID"):
            publish(
                session_root=link, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=registry, publication_root=publication)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID"):
            publish(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=ROOT / "docs/unsafe-registry.json",
                publication_root=publication)

    def test_intermediate_symlink_component_is_rejected(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        alias = fixture.root / "session-parent-link"
        alias.symlink_to(fixture.root, target_is_directory=True)
        redirected = alias / fixture.session.name
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_SESSION_INVALID"):
            publish(
                session_root=redirected, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=registry, publication_root=publication)

    def test_ancestor_replacement_after_validation_has_no_redirected_effect(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        moved = fixture.root / "held-publication"
        original = cli_module._validated_session

        def replace_after_validation(*args, **kwargs):
            result = original(*args, **kwargs)
            publication.rename(moved)
            publication.mkdir(mode=0o700)
            return result

        with mock.patch.object(
                cli_module, "_validated_session",
                side_effect=replace_after_validation):
            with self.assertRaisesRegex(
                    AcquisitionAcceptanceCliError,
                    "ACQ_ACCEPTANCE_CLI_PATH_CHANGED"):
                publish(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry, publication_root=publication)
        self.assertEqual(list(publication.iterdir()), [])
        self.assertEqual(list(moved.iterdir()), [])
        self.assertFalse(registry.exists())

    def test_publication_replacement_during_envelope_save_is_not_redirected(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        moved = fixture.root / "held-publication-save"
        original = acceptance_module._save_at
        swapped = False

        def replace_then_save(directory_fd, directory_path, child_name, value,
                              **kwargs):
            nonlocal swapped
            if child_name == "envelopes" and not swapped:
                publication.rename(moved)
                publication.mkdir(mode=0o700)
                swapped = True
            return original(directory_fd, directory_path, child_name, value,
                            **kwargs)

        with mock.patch.object(
                acceptance_module, "_save_at", side_effect=replace_then_save):
            with self.assertRaisesRegex(
                    AcquisitionAcceptanceCliError,
                    "ACQ_ACCEPTANCE_CLI_PATH_CHANGED"):
                publish(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry, publication_root=publication)
        self.assertEqual(list(publication.iterdir()), [])
        self.assertFalse(registry.exists())
        self.assertTrue((moved / "envelopes").is_dir())

    def test_registry_replacement_during_register_is_not_redirected(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        parent = registry.parent
        moved = fixture.root / "held-registry-register"
        original = acceptance_module._register
        swapped = False

        def replace_then_register(*args, **kwargs):
            nonlocal swapped
            if not swapped:
                parent.rename(moved)
                parent.mkdir(mode=0o700)
                swapped = True
            return original(*args, **kwargs)

        with mock.patch.object(
                acceptance_module, "_register", side_effect=replace_then_register):
            with self.assertRaisesRegex(
                    AcquisitionAcceptanceCliError,
                    "ACQ_ACCEPTANCE_CLI_PATH_CHANGED"):
                publish(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry, publication_root=publication)
        self.assertEqual(list(parent.iterdir()), [])
        self.assertFalse((parent / "registry.json").exists())
        self.assertFalse((moved / "registry.json").exists())

    def test_envelope_child_replacement_before_register_withholds_registry(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        moved = publication / "held-envelopes-before-register"
        original = acceptance_module._register
        swapped = False

        def replace_child_then_register(*args, **kwargs):
            nonlocal swapped
            if not swapped:
                child = publication / "envelopes"
                child.rename(moved)
                child.mkdir(mode=0o700)
                swapped = True
            return original(*args, **kwargs)

        with mock.patch.object(
                acceptance_module, "_register",
                side_effect=replace_child_then_register):
            with self.assertRaisesRegex(
                    acceptance_module.AcquisitionAcceptanceError,
                    "ACQ_ACCEPTANCE_PUBLICATION_CHANGED"):
                publish(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry, publication_root=publication)
        self.assertFalse(registry.exists())
        self.assertEqual(list((publication / "envelopes").iterdir()), [])
        self.assertTrue(any(moved.iterdir()))

    def test_envelope_child_replacement_after_registry_write_rolls_back(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        moved = publication / "held-envelopes-after-register"
        original = acceptance_module._atomic_registry_at
        swapped = False

        def write_then_replace(*args, **kwargs):
            nonlocal swapped
            result = original(*args, **kwargs)
            if not swapped:
                child = publication / "envelopes"
                child.rename(moved)
                child.mkdir(mode=0o700)
                swapped = True
            return result

        with mock.patch.object(
                acceptance_module, "_atomic_registry_at",
                side_effect=write_then_replace):
            with self.assertRaisesRegex(
                    acceptance_module.AcquisitionAcceptanceError,
                    "ACQ_ACCEPTANCE_PUBLICATION_CHANGED"):
                publish(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry, publication_root=publication)
        self.assertFalse(registry.exists())
        self.assertEqual(list((publication / "envelopes").iterdir()), [])
        self.assertTrue(any(moved.iterdir()))

    def test_canonical_datasource_registry_is_rejected_explicitly(self):
        fixture = self.fixture()
        _registry, publication = self.paths(fixture)
        with self.assertRaisesRegex(
                AcquisitionAcceptanceCliError,
                "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID"):
            publish(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=cli_module.datasource.REGISTRY,
                publication_root=publication)

    def test_subject_must_match_sealed_issuer_and_reject_secret_shape(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_SUBJECT_MISMATCH"):
            publish(
                session_root=fixture.session, subject="TST",
                expected_execution_id=fixture.execution_id,
                registry_path=registry, publication_root=publication)
        for secret_subject in (
                "access_token", "ghp_ABCDEFGHIJKLMNOPQRSTUVWX",
                "github_pat_ABCDEFGHIJKLMNOPQRST",
                "GITHUB_PAT_ABCDEFGHIJKLMNOPQRST"):
            with self.subTest(secret_subject=secret_subject[:8]):
                with self.assertRaisesRegex(
                        AcquisitionAcceptanceCliError,
                        "ACQ_ACCEPTANCE_CLI_SUBJECT_INVALID"):
                    publish(
                        session_root=fixture.session, subject=secret_subject,
                        expected_execution_id=fixture.execution_id,
                        registry_path=registry, publication_root=publication)

    def test_session_registry_and_publication_roots_must_be_isolated_and_private(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_ROOT_OVERLAP"):
            publish(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=registry, publication_root=fixture.session)
        nested = fixture.session / "registry-root"
        nested.mkdir(mode=0o700)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_ROOT_OVERLAP"):
            publish(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=nested / "registry.json",
                publication_root=publication)
        registry.parent.chmod(0o770)
        try:
            with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                        "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID"):
                publish(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry, publication_root=publication)
        finally:
            registry.parent.chmod(0o700)

    def test_argparse_failure_is_fixed_bounded_json_without_input_echo(self):
        canary = "bearer SYNTHETIC_SECRET_CANARY"
        result = subprocess.run(
            [sys.executable, "-m",
             "investment.research.acquisition_acceptance_cli", "describe",
             "--unexpected", canary],
            cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.stdout.count(b"\n"), 1)
        self.assertLessEqual(len(result.stdout), cli_module.MAX_OUTPUT_BYTES)
        self.assertNotIn(canary.encode(), result.stdout)
        self.assertEqual(json.loads(result.stdout), {
            "status": "failed", "code": "ACQ_ACCEPTANCE_CLI_ARGUMENT_INVALID"})

    def test_describe_emits_one_exact_bounded_json_line(self):
        result = subprocess.run(
            [sys.executable, "-m",
             "investment.research.acquisition_acceptance_cli", "describe"],
            cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, b"")
        self.assertTrue(result.stdout.endswith(b"\n"))
        self.assertEqual(result.stdout.count(b"\n"), 1)
        self.assertLessEqual(len(result.stdout), cli_module.MAX_OUTPUT_BYTES)
        self.assertEqual(json.loads(result.stdout)["version"],
                         "acquisition-acceptance-cli-1")

    def test_verify_rejects_lock_symlink_and_registry_change_during_readback(self):
        fixture = self.fixture()
        registry, publication = self.paths(fixture)
        publish(
            session_root=fixture.session, subject="SYN",
            expected_execution_id=fixture.execution_id,
            registry_path=registry, publication_root=publication)
        lock = registry.with_name(registry.name + ".lock")
        lock.unlink()
        outside = fixture.root / "outside-lock"
        outside.write_text("outside")
        lock.symlink_to(outside)
        with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                    "ACQ_ACCEPTANCE_CLI_REGISTRY_INVALID"):
            verify(
                session_root=fixture.session, subject="SYN",
                expected_execution_id=fixture.execution_id,
                registry_path=registry)
        lock.unlink()
        original = cli_module._readback

        def mutate(*args, **kwargs):
            value = original(*args, **kwargs)
            registry.write_text(registry.read_text() + " ")
            return value

        with mock.patch.object(cli_module, "_readback", side_effect=mutate):
            with self.assertRaisesRegex(AcquisitionAcceptanceCliError,
                                        "ACQ_ACCEPTANCE_CLI_REGISTRY_CHANGED"):
                verify(
                    session_root=fixture.session, subject="SYN",
                    expected_execution_id=fixture.execution_id,
                    registry_path=registry)


if __name__ == "__main__":
    unittest.main()
