import copy
import hashlib
import json
import multiprocessing
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from investment.factor_mining.rdagent_adapter.v2 import contracts as runner_contracts
from investment.factor_mining.rdagent_adapter.v2 import fixed_worker, runner
from tuning.factor_mining.admission_authority import authority
from tuning.factor_mining.evaluator import contract as evaluator_contract


ROOT = Path(__file__).resolve().parents[4]
DATASET = ROOT / "factor/dataset/fixtures/synthetic-pit-v1"
TEST_RUNTIME = ROOT / "tuning/runtime/admission-authority-tests"
TEST_RUNTIME.mkdir(parents=True, exist_ok=True)
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def runner_worker(workspace, nonce, dataset_event, queue):
    try:
        opened = authority.open_fixture_authority(workspace)
        records, _checkpoint = opened._verify()
        dataset = next(record for record in records if record["event_sha256"] == dataset_event)
        nonce_sha = hashlib.sha256(bytes.fromhex(nonce)).hexdigest()
        issued = next(record for record in records
                      if record["event"]["event_type"] == "fixture_nonce_issued" and
                      record["event"]["payload"]["nonce_sha256"] == nonce_sha)
        payload = dataset["event"]["payload"]
        binding = {"authority_id": runner_contracts.AUTHORITY_ID,
                   "authority_policy_sha256": runner_contracts.AUTHORITY_POLICY_SHA256,
                   "genesis_sha256": runner_contracts.GENESIS_SHA256,
                   "admission_policy_sha256": runner_contracts.ADMISSION_POLICY_SHA256,
                   "dataset_event_sha256": dataset_event,
                   "nonce_event_sha256": issued["event_sha256"],
                   "nonce_sha256": nonce_sha,
                   "builder_receipt_sha256": payload["builder_receipt_sha256"],
                   "observation_set_sha256": payload["observation_set_sha256"],
                   "feature_snapshot_sha256": payload["feature_snapshot_sha256"],
                   "evaluation_population_sha256": payload["evaluation_population_sha256"],
                   "split_fingerprints": payload["split_fingerprints"],
                   "semantic_config_sha256": SHA_A}
        request = {"schema_version": 2, "kind": "rdagent_synthetic_runner_request",
                   "request_id": "concurrent-authority-run", "purpose": runner_contracts.PURPOSE,
                   "authority_binding": binding, "engine": runner_contracts.engine_contract(),
                   "limits": {"artifact_bytes": 65536}}
        result = runner.run_fixed(request, nonce, runner.RunnerState(), opened)
        value = opened.record_fixture_runner_receipt(
            nonce, request, result["receipt"], result["artifact"])
        queue.put(("ok", value["event_sha256"]))
    except Exception as error:
        queue.put(("error", str(error)))


class AuthorityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEST_RUNTIME)
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "workspace"
        self.workspace.mkdir()

    def provision(self):
        authority.provision_fixture_authority(self.workspace)
        return authority.open_fixture_authority(self.workspace)

    def path(self, name):
        return self.workspace / authority.LEDGER_RELATIVE_PATH / name

    def fresh_authority(self, name):
        workspace = Path(self.temp.name) / name
        workspace.mkdir()
        authority.provision_fixture_authority(workspace)
        return workspace, authority.open_fixture_authority(workspace)

    def forge_event(self, opened, event_type, payload):
        records, checkpoint = opened._verify()
        sequence = checkpoint["sequence"] + 1
        event = {"schema_version": 1, "kind": "factor_authority_event",
                 "authority_id": authority.AUTHORITY_ID, "epoch": 1, "sequence": sequence,
                 "previous_event_sha256": checkpoint["last_event_sha256"],
                 "previous_chain_sha256": checkpoint["chain_sha256"],
                 "event_type": event_type, "created_at": "2026-11-05T00:00:00Z",
                 "payload": payload}
        authority._validate_event(event)
        event_sha = authority.digest(event)
        chain = authority._event_chain(checkpoint["chain_sha256"], event_sha)
        authority._atomic_write(opened.root / "events" /
                                authority._event_filename(sequence, event_sha),
                                authority._record_bytes(event))
        updated = authority._checkpoint(opened.genesis_sha, opened.binding, sequence,
                                        event_sha, chain)
        authority._atomic_write(opened.root / "checkpoint.json",
                                authority._record_bytes(updated), replace=True)
        return {"event": event, "event_sha256": event_sha, "chain_sha256": chain}

    def issue_request(self, opened):
        dataset = opened.bind_fixture_dataset(DATASET)
        issued = opened.issue_fixture_nonce(dataset["event_sha256"], SHA_A)
        payload = dataset["event"]["payload"]
        binding = {"authority_id": runner_contracts.AUTHORITY_ID,
                   "authority_policy_sha256": runner_contracts.AUTHORITY_POLICY_SHA256,
                   "genesis_sha256": runner_contracts.GENESIS_SHA256,
                   "admission_policy_sha256": runner_contracts.ADMISSION_POLICY_SHA256,
                   "dataset_event_sha256": dataset["event_sha256"],
                   "nonce_event_sha256": issued["event_sha256"],
                   "nonce_sha256": issued["nonce_sha256"],
                   "builder_receipt_sha256": payload["builder_receipt_sha256"],
                   "observation_set_sha256": payload["observation_set_sha256"],
                   "feature_snapshot_sha256": payload["feature_snapshot_sha256"],
                   "evaluation_population_sha256": payload["evaluation_population_sha256"],
                   "split_fingerprints": payload["split_fingerprints"],
                   "semantic_config_sha256": SHA_A}
        request = {"schema_version": 2, "kind": "rdagent_synthetic_runner_request",
                   "request_id": "synthetic-authority-unit-run",
                   "purpose": runner_contracts.PURPOSE,
                   "authority_binding": binding,
                   "engine": runner_contracts.engine_contract(),
                   "limits": {"artifact_bytes": 65536}}
        return dataset, issued, runner_contracts.validate_request(request)

    def run_actual(self, opened):
        dataset, issued, request = self.issue_request(opened)
        result = runner.run_fixed(request, issued["nonce"], runner.RunnerState(), opened)
        return dataset, issued, request, result

    def test_tracked_policy_genesis_and_status_are_exact_and_blocked(self):
        policy, policy_sha = authority.load_policy()
        genesis, genesis_sha = authority.load_genesis()
        self.assertEqual(policy_sha, genesis["authority_policy_sha256"])
        self.assertRegex(genesis_sha, r"^[a-f0-9]{64}$")
        self.assertEqual(policy["admission_policy_sha256"], authority.ADMISSION_POLICY_SHA256)
        self.assertEqual(policy["ledger_relative_path"], authority.LEDGER_RELATIVE_PATH)
        self.assertEqual(policy["blockers"], authority.BLOCKERS)
        self.assertTrue(all(policy[key] is None for key in authority.NULL_POLICIES))
        self.assertFalse(any(policy[key] for key in
                             ("real_protocols_allowed", "protected_outcomes_allowed",
                              "performance_publication_allowed", "ev_publication_allowed",
                              "kelly_publication_allowed")))
        with self.assertRaisesRegex(authority.AuthorityError, "NOT_PROVISIONED|LOCK_INVALID"):
            authority.open_fixture_authority(self.workspace)
        opened = self.provision()
        self.assertEqual(opened.status()["sequence"], 0)
        self.assertFalse(opened.status()["active"])
        with self.assertRaisesRegex(authority.AuthorityError, "PRODUCTION_BLOCKED"):
            opened.assert_active()
        with self.assertRaisesRegex(authority.AuthorityError, "PUBLICATION_BLOCKED"):
            opened.authorize("performance_publication", {})

    def test_fixture_dataset_nonce_runner_and_evaluator_are_bound_once(self):
        opened = self.provision()
        dataset_event, issued, request = self.issue_request(opened)
        verified = opened.verify_fixture_binding(issued["nonce"], request["authority_binding"])
        result = runner.run_fixed(request, issued["nonce"], runner.RunnerState(), opened)
        payload = dataset_event["event"]["payload"]
        self.assertEqual(payload["purpose"], authority.FIXTURE_PURPOSE)
        self.assertEqual(payload["trust_class"], "synthetic")
        self.assertEqual(payload["performance_claim"], "withheld")
        self.assertNotIn("label", str(payload).lower())
        self.assertEqual(verified["nonce_event"]["event_sha256"], issued["event_sha256"])
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_ALREADY_CLAIMED"):
            opened.verify_fixture_binding(issued["nonce"], request["authority_binding"])
        runner_event = opened.record_fixture_runner_receipt(
            issued["nonce"], request, result["receipt"], result["artifact"])
        self.assertEqual(opened.verify_fixture_runner_event(
            runner_event["event_sha256"], request, result["receipt"],
            result["artifact"])["event_sha256"], runner_event["event_sha256"])
        evaluator_request = evaluator_contract.create_request(
            request, result["receipt"], result["artifact"],
            runner_event["event_sha256"], opened)
        evaluator_receipt = evaluator_contract.create_receipt(evaluator_request)
        evaluator = opened.record_fixture_evaluator_receipt(
            runner_event["event_sha256"], evaluator_request, evaluator_receipt)
        self.assertEqual(evaluator["event"]["payload"]["scientific_verdict"], "withheld")
        self.assertEqual(opened.status()["sequence"], 5)
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_REUSED"):
            opened.record_fixture_runner_receipt(
                issued["nonce"], request, result["receipt"], result["artifact"])
        with self.assertRaisesRegex(authority.AuthorityError, "EVALUATOR_REUSED"):
            opened.record_fixture_evaluator_receipt(
                runner_event["event_sha256"], evaluator_request, evaluator_receipt)
        with self.assertRaisesRegex(authority.AuthorityError, "HASH_ONLY_RECEIPT_REJECTED"):
            opened.record_fixture_runner(issued["nonce"], SHA_B)
        with self.assertRaisesRegex(authority.AuthorityError, "HASH_ONLY_RECEIPT_REJECTED"):
            opened.record_fixture_evaluator(issued["nonce"], runner_event["event_sha256"], SHA_C)

    def test_wrong_dataset_semantics_nonce_and_receipt_bindings_fail(self):
        opened = self.provision()
        dataset_event = opened.bind_fixture_dataset(DATASET)
        with self.assertRaisesRegex(authority.AuthorityError, "DATASET_EVENT_UNKNOWN"):
            opened.issue_fixture_nonce(SHA_A, SHA_B)
        non_synthetic = Path(self.temp.name) / "non-synthetic"
        shutil.copytree(DATASET, non_synthetic)
        descriptor = json.loads((non_synthetic / "dataset.json").read_text())
        descriptor["provenance"] = "acquired_public"
        (non_synthetic / "dataset.json").write_bytes(
            json.dumps(descriptor, sort_keys=True, separators=(",", ":")).encode() + b"\n")
        with self.assertRaisesRegex(authority.AuthorityError, "DATASET_INVALID"):
            opened.bind_fixture_dataset(non_synthetic)
        _dataset, issued, request, result = self.run_actual(opened)
        wrong_binding = copy.deepcopy(request)
        wrong_binding["authority_binding"]["observation_set_sha256"] = SHA_B
        with self.assertRaisesRegex(authority.AuthorityError, "FIXTURE_BINDING_MISMATCH"):
            opened.verify_fixture_binding(issued["nonce"], wrong_binding["authority_binding"])
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_MISMATCH"):
            opened.verify_fixture_binding("f" * 64, request["authority_binding"])
        with self.assertRaisesRegex(authority.AuthorityError, "RUNNER_RECEIPT_INVALID"):
            opened.record_fixture_runner_receipt(issued["nonce"], request, {}, None)
        with self.assertRaisesRegex(authority.AuthorityError, "RUNNER_ARTIFACT_MISMATCH"):
            opened.record_fixture_runner_receipt(
                issued["nonce"], request, result["receipt"], b"forged")
        unknown = copy.deepcopy(result["receipt"]); unknown["status"] = "unknown"
        with self.assertRaisesRegex(authority.AuthorityError, "RUNNER_RECEIPT_INVALID"):
            opened.record_fixture_runner_receipt(
                issued["nonce"], request, unknown, result["artifact"])
        runner_event = opened.record_fixture_runner_receipt(
            issued["nonce"], request, result["receipt"], result["artifact"])
        with self.assertRaisesRegex(authority.AuthorityError, "RUNNER_EVENT_UNKNOWN"):
            opened.verify_fixture_runner_event(SHA_A, request, result["receipt"], result["artifact"])
        evaluator_request = evaluator_contract.create_request(
            request, result["receipt"], result["artifact"],
            runner_event["event_sha256"], opened)
        evaluator_receipt = evaluator_contract.create_receipt(evaluator_request)
        wrong_evaluator = copy.deepcopy(evaluator_receipt)
        wrong_evaluator["runner_receipt_sha256"] = SHA_A
        with self.assertRaisesRegex(authority.AuthorityError, "EVALUATOR_RECEIPT_INVALID"):
            opened.record_fixture_evaluator_receipt(
                runner_event["event_sha256"], evaluator_request, wrong_evaluator)

    def test_failed_actual_runner_receipt_is_truthfully_recorded_and_not_evaluable(self):
        opened = self.provision()
        _dataset, issued, request = self.issue_request(opened)
        opened.claim_fixture_nonce(issued["nonce"], request["authority_binding"])
        receipt = runner._failure_receipt(request)
        result = {"receipt": receipt, "receipt_sha256": runner_contracts.digest(receipt),
                  "artifact": None}
        self.assertEqual(result["receipt"]["status"], "failed")
        event = opened.record_fixture_runner_receipt(
            issued["nonce"], request, result["receipt"], result["artifact"])
        payload = event["event"]["payload"]
        self.assertEqual(payload["terminal_status"], "failed")
        self.assertEqual(payload["failure_code"], "FIXED_WORKER_REJECTED")
        self.assertIsNone(payload["artifact_sha256"])
        self.assertEqual(payload["artifact_size_bytes"], 0)
        self.assertEqual(opened.verify_fixture_runner_event(
            event["event_sha256"], request, result["receipt"], None)["event_sha256"],
            event["event_sha256"])
        with self.assertRaises(evaluator_contract.EvaluatorError):
            evaluator_contract.create_request(
                request, result["receipt"], None, event["event_sha256"], opened)

    def test_mutated_event_stale_missing_checkpoint_and_skipped_sequence_fail(self):
        opened = self.provision()
        initial_checkpoint = self.path("checkpoint.json").read_bytes()
        event = opened.bind_fixture_dataset(DATASET)
        event_path = next(self.path("events").iterdir())
        value = json.loads(event_path.read_text())
        value["payload"]["performance_claim"] = "fabricated"
        event_path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")
        with self.assertRaisesRegex(authority.AuthorityError, "DATASET_PAYLOAD_INVALID"):
            authority.open_fixture_authority(self.workspace)

        other = Path(self.temp.name) / "stale"; other.mkdir()
        authority.provision_fixture_authority(other)
        stale = authority.open_fixture_authority(other)
        stale_dataset = stale.bind_fixture_dataset(DATASET)
        stale.issue_fixture_nonce(stale_dataset["event_sha256"], SHA_A)
        (other / authority.LEDGER_RELATIVE_PATH / "checkpoint.json").write_bytes(initial_checkpoint)
        with self.assertRaises(authority.AuthorityError):
            authority.open_fixture_authority(other)

        missing = Path(self.temp.name) / "missing"; missing.mkdir()
        authority.provision_fixture_authority(missing)
        (missing / authority.LEDGER_RELATIVE_PATH / "checkpoint.json").unlink()
        with self.assertRaisesRegex(authority.AuthorityError, "RECORD_UNAVAILABLE"):
            authority.open_fixture_authority(missing)

        skipped = Path(self.temp.name) / "skipped"; skipped.mkdir()
        authority.provision_fixture_authority(skipped)
        skip_open = authority.open_fixture_authority(skipped)
        skip_open.bind_fixture_dataset(DATASET)
        event_file = next((skipped / authority.LEDGER_RELATIVE_PATH / "events").iterdir())
        event_file.rename(event_file.with_name(event_file.name.replace("00000000000000000001", "00000000000000000002")))
        with self.assertRaisesRegex(authority.AuthorityError, "CHAIN_INVALID"):
            authority.open_fixture_authority(skipped)

    def test_copied_wrong_symlinked_or_mutated_authority_root_fails(self):
        self.provision()
        copied_workspace = Path(self.temp.name) / "copy"; copied_workspace.mkdir()
        destination = copied_workspace / authority.LEDGER_RELATIVE_PATH
        destination.parent.mkdir(parents=True)
        shutil.copytree(self.path("."), destination)
        with self.assertRaisesRegex(authority.AuthorityError, "PROVISION_INVALID|CHECKPOINT_INVALID"):
            authority.open_fixture_authority(copied_workspace)

        symlink_workspace = Path(self.temp.name) / "symlink"; symlink_workspace.mkdir()
        link = symlink_workspace / authority.LEDGER_RELATIVE_PATH
        link.parent.mkdir(parents=True)
        link.symlink_to(self.path("."), target_is_directory=True)
        with self.assertRaises(authority.AuthorityError):
            authority.open_fixture_authority(symlink_workspace)

        policy = json.loads(self.path("policy.json").read_text())
        policy["authority_id"] = "other-authority"
        self.path("policy.json").write_text(json.dumps(policy) + "\n")
        with self.assertRaisesRegex(authority.AuthorityError, "POLICY_MISMATCH"):
            authority.open_fixture_authority(self.workspace)

    def test_claim_crash_leaves_nonce_unknown_and_permanently_fenced(self):
        opened = self.provision()
        _dataset, issued, request = self.issue_request(opened)
        claim = opened.claim_fixture_nonce(issued["nonce"], request["authority_binding"])
        self.assertEqual(claim["event"]["payload"]["claim_status"],
                         "claimed-unknown-until-terminal")
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_ALREADY_CLAIMED"):
            opened.verify_fixture_binding(issued["nonce"], request["authority_binding"])
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_ALREADY_CLAIMED"):
            opened.claim_fixture_nonce(issued["nonce"], request["authority_binding"])
        reopened = authority.open_fixture_authority(self.workspace)
        self.assertEqual(reopened.status()["sequence"], 3)
        self.assertFalse(any(record["event"]["event_type"] == "fixture_runner_terminal"
                             for record in reopened._verify()[0]))

    def test_concurrent_runner_nonce_consumption_has_one_winner(self):
        opened = self.provision()
        dataset_event = opened.bind_fixture_dataset(DATASET)
        issued = opened.issue_fixture_nonce(dataset_event["event_sha256"], SHA_A)
        context = multiprocessing.get_context("fork")
        queue = context.Queue()
        workers = [context.Process(target=runner_worker,
                    args=(str(self.workspace), issued["nonce"],
                          dataset_event["event_sha256"], queue)) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(10)
        results = [queue.get(timeout=2) for _ in workers]
        self.assertEqual(sum(result[0] == "ok" for result in results), 1)
        self.assertEqual(sum(result == ("error", "ADAPTER_V2_NONCE_CLAIM_REJECTED")
                             for result in results), 1)
        reopened = authority.open_fixture_authority(self.workspace)
        records, _checkpoint = reopened._verify()
        self.assertEqual(sum(record["event"]["event_type"] == "fixture_nonce_claimed"
                             for record in records), 1)
        self.assertEqual(sum(record["event"]["event_type"] == "fixture_runner_terminal"
                             for record in records), 1)
        self.assertEqual(reopened.status()["sequence"], 4)

    def test_event_payloads_fail_closed_on_append_and_reconstruction(self):
        opened = self.provision()
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_PAYLOAD_SCHEMA"):
            opened._append("fixture_nonce_issued", {"nonce_sha256": SHA_A})
        malicious = {"purpose": authority.FIXTURE_PURPOSE, "trust_class": "synthetic",
                     "admission_policy_sha256": authority.ADMISSION_POLICY_SHA256,
                     "dataset_event_sha256": SHA_A, "semantic_config_sha256": SHA_B,
                     "nonce_sha256": SHA_C, "observation_set_sha256": SHA_A,
                     "feature_snapshot_sha256": SHA_B, "evaluation_population_sha256": SHA_C,
                     "split_fingerprints": {"development": SHA_A, "validation": SHA_B,
                                            "protected": SHA_C},
                     "protected_outcomes_allowed": True}
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_PAYLOAD_INVALID"):
            opened._append("fixture_nonce_issued", malicious)
        chosen = dict(malicious)
        chosen["protected_outcomes_allowed"] = False
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_DATASET_RELATION_INVALID"):
            opened._append("fixture_nonce_issued", chosen)

        event = {"schema_version": 1, "kind": "factor_authority_event",
                 "authority_id": authority.AUTHORITY_ID, "epoch": 1, "sequence": 1,
                 "previous_event_sha256": None,
                 "previous_chain_sha256": opened.genesis_sha,
                 "event_type": "fixture_nonce_issued",
                 "created_at": "2026-11-05T00:00:00Z",
                 "payload": {"nonce_sha256": SHA_A}}
        event_sha = authority.digest(event)
        chain = authority._event_chain(opened.genesis_sha, event_sha)
        event_path = self.path("events") / authority._event_filename(1, event_sha)
        event_path.write_bytes(authority._record_bytes(event))
        checkpoint = authority._checkpoint(opened.genesis_sha, opened.binding, 1, event_sha, chain)
        self.path("checkpoint.json").write_bytes(authority._record_bytes(checkpoint))
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_PAYLOAD_SCHEMA"):
            authority.open_fixture_authority(self.workspace)

    def test_reconstruction_replays_all_event_relationships(self):
        workspace, opened = self.fresh_authority("missing-dataset")
        dataset = opened.bind_fixture_dataset(DATASET)
        opened.issue_fixture_nonce(dataset["event_sha256"], SHA_A)
        nonce_payload = copy.deepcopy(opened._verify()[0][-1]["event"]["payload"])
        nonce_payload["dataset_event_sha256"] = SHA_A
        nonce_payload["nonce_sha256"] = SHA_B
        self.forge_event(opened, "fixture_nonce_issued", nonce_payload)
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_DATASET_RELATION_INVALID"):
            authority.open_fixture_authority(workspace)

        workspace, opened = self.fresh_authority("identity-mismatch")
        dataset = opened.bind_fixture_dataset(DATASET)
        opened.issue_fixture_nonce(dataset["event_sha256"], SHA_A)
        nonce_payload = copy.deepcopy(opened._verify()[0][-1]["event"]["payload"])
        nonce_payload["observation_set_sha256"] = SHA_A
        nonce_payload["nonce_sha256"] = SHA_B
        self.forge_event(opened, "fixture_nonce_issued", nonce_payload)
        with self.assertRaisesRegex(authority.AuthorityError, "NONCE_IDENTITY_MISMATCH"):
            authority.open_fixture_authority(workspace)

        workspace, opened = self.fresh_authority("unrelated-nonce")
        dataset, first, request, result = self.run_actual(opened)
        runner_event = opened.record_fixture_runner_receipt(
            first["nonce"], request, result["receipt"], result["artifact"])
        second = opened.issue_fixture_nonce(dataset["event_sha256"], SHA_A)
        runner_payload = copy.deepcopy(runner_event["event"]["payload"])
        runner_payload["nonce_sha256"] = second["nonce_sha256"]
        self.forge_event(opened, "fixture_runner_terminal", runner_payload)
        with self.assertRaisesRegex(authority.AuthorityError, "RUNNER_CLAIM_RELATION_INVALID"):
            authority.open_fixture_authority(workspace)

        workspace, opened = self.fresh_authority("duplicate-runner")
        _dataset, issued, request, result = self.run_actual(opened)
        runner_event = opened.record_fixture_runner_receipt(
            issued["nonce"], request, result["receipt"], result["artifact"])
        self.forge_event(opened, "fixture_runner_terminal",
                         copy.deepcopy(runner_event["event"]["payload"]))
        with self.assertRaisesRegex(authority.AuthorityError, "RUNNER_DUPLICATE"):
            authority.open_fixture_authority(workspace)

        workspace, opened = self.fresh_authority("duplicate-evaluator")
        _dataset, issued, request, result = self.run_actual(opened)
        runner_event = opened.record_fixture_runner_receipt(
            issued["nonce"], request, result["receipt"], result["artifact"])
        evaluator_request = evaluator_contract.create_request(
            request, result["receipt"], result["artifact"],
            runner_event["event_sha256"], opened)
        evaluator_receipt = evaluator_contract.create_receipt(evaluator_request)
        evaluator_event = opened.record_fixture_evaluator_receipt(
            runner_event["event_sha256"], evaluator_request, evaluator_receipt)
        self.forge_event(opened, "fixture_evaluator_terminal",
                         copy.deepcopy(evaluator_event["event"]["payload"]))
        with self.assertRaisesRegex(authority.AuthorityError, "EVALUATOR_DUPLICATE"):
            authority.open_fixture_authority(workspace)

    def test_workspace_and_ancestor_symlinks_fail_before_resolution(self):
        real_workspace = Path(self.temp.name) / "real-workspace"; real_workspace.mkdir()
        workspace_link = Path(self.temp.name) / "workspace-link"
        workspace_link.symlink_to(real_workspace, target_is_directory=True)
        with self.assertRaisesRegex(authority.AuthorityError, "WORKSPACE_SYMLINK"):
            authority.provision_fixture_authority(workspace_link)

        real_parent = Path(self.temp.name) / "real-parent"; real_parent.mkdir()
        nested = real_parent / "nested"; nested.mkdir()
        ancestor_link = Path(self.temp.name) / "ancestor-link"
        ancestor_link.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaisesRegex(authority.AuthorityError, "WORKSPACE_SYMLINK"):
            authority.provision_fixture_authority(ancestor_link / "nested")

    def test_event_enumeration_is_bounded_before_junk_validation(self):
        self.provision()
        events = self.path("events")
        for index in range(257):
            (events / f"junk-{index:03d}").write_text("junk")
        with self.assertRaisesRegex(authority.AuthorityError, "EVENT_LIMIT"):
            authority.open_fixture_authority(self.workspace)

    def test_atomic_write_normalizes_failures_and_cleans_temporaries(self):
        base = self.workspace / "atomic"; base.mkdir()
        def assert_clean(directory):
            self.assertEqual(list(directory.glob(".*.tmp")), [])

        target = base / "write.json"
        with mock.patch.object(authority.os, "open", side_effect=OSError("private-open")):
            with self.assertRaisesRegex(authority.AuthorityError, "WRITE_FAILED"):
                authority._atomic_write(target, b"value")
        assert_clean(base)

        with mock.patch.object(authority.os, "write", side_effect=OSError("private-write")):
            with self.assertRaisesRegex(authority.AuthorityError, "WRITE_FAILED"):
                authority._atomic_write(target, b"value")
        assert_clean(base)

        with mock.patch.object(authority.os, "fsync", side_effect=OSError("private-fsync")):
            with self.assertRaisesRegex(authority.AuthorityError, "WRITE_FAILED"):
                authority._atomic_write(target, b"value")
        assert_clean(base)

        with mock.patch.object(authority.os, "link", side_effect=OSError("private-link")):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN") as raised_link:
                authority._atomic_write(target, b"value")
        self.assertEqual(raised_link.exception.readback_state, "missing")
        assert_clean(base)

        replace_target = base / "replace.json"; replace_target.write_bytes(b"old")
        with mock.patch.object(authority.os, "replace", side_effect=OSError("private-replace")):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN") as raised_replace:
                authority._atomic_write(replace_target, b"value", replace=True)
        self.assertEqual(raised_replace.exception.readback_state, "different")
        self.assertEqual(replace_target.read_bytes(), b"old")
        assert_clean(base)

        fsync_target = base / "directory-fsync.json"
        with mock.patch.object(authority.os, "fsync", side_effect=[None, OSError("private-dir")]):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN") as raised:
                authority._atomic_write(fsync_target, b"value")
        self.assertEqual(raised.exception.destination, str(fsync_target))
        self.assertEqual(raised.exception.intended_bytes, b"value")
        self.assertEqual(raised.exception.intended_sha256,
                         hashlib.sha256(b"value").hexdigest())
        assert_clean(base)

        unlink_target = base / "unlink.json"
        real_unlink = authority.os.unlink
        calls = 0
        def fail_once(path):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("private-unlink")
            return real_unlink(path)
        with mock.patch.object(authority.os, "unlink", side_effect=fail_once):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN"):
                authority._atomic_write(unlink_target, b"value")
        assert_clean(base)

        conflict = base / "conflict.json"; conflict.write_bytes(b"old")
        with self.assertRaisesRegex(authority.AuthorityError, "IMMUTABLE_CONFLICT"):
            authority._atomic_write(conflict, b"new")
        assert_clean(base)

    def test_effect_then_raise_is_unknown_and_exact_retry_is_idempotent(self):
        base = self.workspace / "effect-then-raise"; base.mkdir()
        payload = b"intended-bytes"
        target = base / "event.json"
        real_link = authority.os.link
        def link_then_raise(source, destination, **kwargs):
            real_link(source, destination, **kwargs)
            raise OSError("post-link-private")
        with mock.patch.object(authority.os, "link", side_effect=link_then_raise):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN"):
                authority._atomic_write(target, payload)
        self.assertEqual(target.read_bytes(), payload)
        authority._atomic_write(target, payload)
        self.assertEqual(target.read_bytes(), payload)
        self.assertEqual(list(base.glob(".*.tmp")), [])

        checkpoint = base / "checkpoint.json"; checkpoint.write_bytes(b"old")
        real_replace = authority.os.replace
        def replace_then_raise(source, destination):
            real_replace(source, destination)
            raise OSError("post-replace-private")
        with mock.patch.object(authority.os, "replace", side_effect=replace_then_raise):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN"):
                authority._atomic_write(checkpoint, payload, replace=True)
        self.assertEqual(checkpoint.read_bytes(), payload)
        authority._atomic_write(checkpoint, payload, replace=True)
        self.assertEqual(checkpoint.read_bytes(), payload)

        drifted = base / "drifted-checkpoint.json"; drifted.write_bytes(b"old")
        def replace_drift_then_raise(source, destination):
            real_replace(source, destination)
            Path(destination).write_bytes(b"intervening-state")
            raise OSError("post-replace-drift-private")
        with mock.patch.object(authority.os, "replace", side_effect=replace_drift_then_raise):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN") as drift:
                authority._write_reconciled(drifted, payload, replace=True)
        self.assertEqual(drift.exception.readback_state, "different")
        self.assertEqual(drifted.read_bytes(), b"intervening-state")

    def test_append_reconciles_effect_then_raise_and_parent_fsync_faults(self):
        opened = self.provision()
        real_link = authority.os.link
        linked = False
        def link_then_raise_once(source, destination, **kwargs):
            nonlocal linked
            real_link(source, destination, **kwargs)
            if not linked:
                linked = True
                raise OSError("post-link-private")
        with mock.patch.object(authority.os, "link", side_effect=link_then_raise_once):
            dataset = opened.bind_fixture_dataset(DATASET)
        self.assertRegex(dataset["event_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(opened.status()["sequence"], 1)

        real_replace = authority.os.replace
        replaced = False
        def replace_then_raise_once(source, destination):
            nonlocal replaced
            real_replace(source, destination)
            if not replaced:
                replaced = True
                raise OSError("post-replace-private")
        with mock.patch.object(authority.os, "replace", side_effect=replace_then_raise_once):
            issued = opened.issue_fixture_nonce(dataset["event_sha256"], SHA_A)
        self.assertRegex(issued["event_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(opened.status()["sequence"], 2)

        direct = self.workspace / "parent-fsync.json"
        real_fsync = authority.os.fsync
        calls = 0
        def fsync_then_raise(descriptor):
            nonlocal calls
            calls += 1
            real_fsync(descriptor)
            if calls == 2:
                raise OSError("post-parent-fsync-private")
        with mock.patch.object(authority.os, "fsync", side_effect=fsync_then_raise):
            with self.assertRaisesRegex(authority.AuthorityWriteDurabilityUnknown,
                                        "WRITE_DURABILITY_UNKNOWN"):
                authority._atomic_write(direct, b"durable-intent")
        self.assertEqual(direct.read_bytes(), b"durable-intent")
        authority._atomic_write(direct, b"durable-intent")

    def test_pre_effect_checkpoint_failure_retries_and_one_orphan_recovers(self):
        opened = self.provision()
        original = authority._atomic_write
        failed = False
        def fail_checkpoint_once(path, payload, replace=False):
            nonlocal failed
            if Path(path).name == "checkpoint.json" and replace and not failed:
                failed = True
                raise authority.AuthorityWriteFailed()
            return original(path, payload, replace=replace)
        with mock.patch.object(authority, "_atomic_write", side_effect=fail_checkpoint_once):
            event = opened.bind_fixture_dataset(DATASET)
        self.assertRegex(event["event_sha256"], r"^[a-f0-9]{64}$")
        self.assertEqual(opened.status()["sequence"], 1)

        workspace, other = self.fresh_authority("checkpoint-orphan")
        def fail_checkpoint(path, payload, replace=False):
            if Path(path).name == "checkpoint.json" and replace:
                raise authority.AuthorityWriteFailed()
            return original(path, payload, replace=replace)
        with mock.patch.object(authority, "_atomic_write", side_effect=fail_checkpoint):
            with self.assertRaisesRegex(authority.AuthorityError, "WRITE_FAILED"):
                other.bind_fixture_dataset(DATASET)
        recovered = authority.open_fixture_authority(workspace)
        self.assertEqual(recovered.status()["sequence"], 1)
        self.assertEqual(len(recovered._verify()[0]), 1)

    def test_lock_io_failures_are_sanitized_and_cleanup_does_not_mask(self):
        opened = self.provision()
        with mock.patch.object(authority.os, "fstat", side_effect=OSError("private-fstat")):
            with self.assertRaisesRegex(authority.AuthorityError, "LOCK_INVALID"):
                with authority._exclusive_lock(opened.root):
                    pass
        with mock.patch.object(authority.fcntl, "flock", side_effect=OSError("private-flock")):
            with self.assertRaisesRegex(authority.AuthorityError, "LOCK_INVALID"):
                with authority._exclusive_lock(opened.root):
                    pass
        real_close = authority.os.close
        def close_then_raise(descriptor):
            real_close(descriptor)
            raise OSError("private-close")
        with mock.patch.object(authority.os, "close", side_effect=close_then_raise):
            with authority._exclusive_lock(opened.root):
                pass
        with mock.patch.object(authority.os, "fstat", side_effect=OSError("private-read")):
            with self.assertRaisesRegex(authority.AuthorityError, "RECORD_INVALID"):
                authority._read_json(authority.POLICY_PATH)
        with mock.patch.object(authority.os, "close", side_effect=close_then_raise):
            self.assertEqual(authority._read_json(authority.POLICY_PATH)["authority_id"],
                             authority.AUTHORITY_ID)

    def test_implementation_identity_binds_all_authority_methods_and_is_fresh_process_stable(self):
        first = authority.implementation_sha256()
        self.assertEqual(first, authority.implementation_sha256())
        def replacement(self, *_args, **_kwargs):
            return {"changed": True}
        for name in ("verify_fixture_binding", "claim_fixture_nonce", "_runner_material",
                     "verify_fixture_runner_event"):
            with self.subTest(method=name), mock.patch.object(
                    authority.FixtureAuthority, name, replacement):
                self.assertNotEqual(first, authority.implementation_sha256())
        script = ("from tuning.factor_mining.admission_authority import implementation_sha256;"
                  "print(implementation_sha256())")
        result = subprocess.run([sys.executable, "-B", "-c", script], cwd=ROOT,
                                capture_output=True, text=True, timeout=20, check=True)
        self.assertEqual(result.stdout.strip(), first)
        self.assertEqual(result.stderr, "")

    def test_schema_json_and_strict_type_guards(self):
        schemas = sorted(authority.PACKAGE.glob("*schema.json"))
        self.assertEqual(len(schemas), 5)
        for path in schemas:
            value = json.loads(path.read_text())
            self.assertEqual(set(value["required"]), set(value["properties"]))
        event_schema = json.loads((authority.PACKAGE / "authority-event-v1.schema.json").read_text())
        self.assertEqual(len(event_schema["allOf"]), 5)
        self.assertEqual({"dataset", "nonce", "claim", "runner", "evaluator"},
                         {key for key in event_schema["$defs"] if key not in {"sha", "splits"}})
        self.assertEqual(len(event_schema["$defs"]["runner"]["allOf"]), 2)
        self.assertEqual(event_schema["properties"]["created_at"]["pattern"], authority.TIME.pattern)
        for accepted in ("2026-11-05T00:00:00Z", "2026-11-05T00:00:00.123Z"):
            self.assertEqual(authority._timestamp(accepted), accepted)
        for rejected in ("2026-11-05", "2026-11-05 00:00:00Z",
                         "2026-11-05T00:00:00+00:00", "2026-02-30T00:00:00Z"):
            with self.subTest(timestamp=rejected), self.assertRaisesRegex(
                    authority.AuthorityError, "TIME_INVALID"):
                authority._timestamp(rejected)
        policy, _ = authority.load_policy()
        changed = copy.deepcopy(policy); changed["epoch"] = True
        with self.assertRaisesRegex(authority.AuthorityError, "POLICY_INVALID"):
            authority.validate_policy(changed)
        with self.assertRaisesRegex(authority.AuthorityError, "DUPLICATE_KEY"):
            authority.loads_strict('{"a":1,"a":2}')
        with self.assertRaisesRegex(authority.AuthorityError, "NONFINITE"):
            authority.loads_strict('{"a":NaN}')
        first_identity = authority.implementation_sha256()
        self.assertEqual(first_identity, authority.implementation_sha256())
        self.assertRegex(first_identity, r"^[a-f0-9]{64}$")
        with mock.patch.object(authority, "MAX_JSON", authority.MAX_JSON + 1):
            self.assertNotEqual(first_identity, authority.implementation_sha256())
        with mock.patch.object(authority.admission_policy_contract, "digest", return_value=SHA_A):
            with self.assertRaisesRegex(authority.AuthorityError, "ADMISSION_POLICY_MISMATCH"):
                authority.load_policy()


if __name__ == "__main__":
    unittest.main()
