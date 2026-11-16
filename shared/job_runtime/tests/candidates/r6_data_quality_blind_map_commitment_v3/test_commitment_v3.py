from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v3 import chronology, transaction

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


REAL_WORKSPACE = Path(__file__).resolve().parents[5]


class BlindMapCommitmentV3(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace / "runtime").mkdir(mode=0o700)
        self.tx_patch = mock.patch.object(transaction, "WORKSPACE_ROOT", self.workspace)
        self.chron_patch = mock.patch.object(chronology, "WORKSPACE_ROOT", self.workspace)
        self.tx_patch.start(); self.chron_patch.start()
        self.addCleanup(self.tx_patch.stop); self.addCleanup(self.chron_patch.stop)

    @contextmanager
    def pinned_sources(self):
        tx_original = transaction._verify_pinned_sources
        chron_original = chronology._verify_pinned_sources

        def tx_verify():
            old = transaction.WORKSPACE_ROOT
            try:
                transaction.WORKSPACE_ROOT = REAL_WORKSPACE
                tx_original()
            finally:
                transaction.WORKSPACE_ROOT = old

        def chron_verify():
            old = chronology.WORKSPACE_ROOT
            try:
                chronology.WORKSPACE_ROOT = REAL_WORKSPACE
                chron_original()
            finally:
                chronology.WORKSPACE_ROOT = old

        with mock.patch.object(transaction, "_verify_pinned_sources", side_effect=tx_verify), mock.patch.object(chronology, "_verify_pinned_sources", side_effect=chron_verify):
            yield

    def create(self):
        with self.pinned_sources():
            return transaction.create_commitment()

    def test_transaction_v3_marker_pair_and_recovery(self):
        commitment = self.create()
        root = transaction._root_path()
        self.assertEqual(set(os.listdir(root)), {transaction.PRIVATE_MAP_NAME, transaction.COMMITMENT_NAME, transaction.RECEIPT_NAME})
        with self.pinned_sources():
            self.assertEqual(transaction.validate_commitment(), commitment)
        receipt = json.loads((root / transaction.RECEIPT_NAME).read_text())
        self.assertEqual(receipt["version"], 3)
        self.assertEqual(receipt["map_ref"]["mode"], "0600")
        self.assertEqual(receipt["commitment_ref"]["mode"], "0600")
        for name in (transaction.PRIVATE_MAP_NAME, transaction.COMMITMENT_NAME, transaction.RECEIPT_NAME):
            self.assertEqual(oct(os.stat(root / name).st_mode & 0o777), "0o600")
        # Zero write leaves no authoritative residue and retry succeeds.
        for name in (transaction.RECEIPT_NAME, transaction.PRIVATE_MAP_NAME, transaction.COMMITMENT_NAME):
            (root / name).unlink()
        real_write = os.write
        fired = False
        def zero_once(fd, data):
            nonlocal fired
            if not fired:
                fired = True
                return 0
            return real_write(fd, data)
        with self.pinned_sources(), mock.patch.object(transaction.os, "write", side_effect=zero_once):
            with self.assertRaises(transaction.CommitmentError):
                transaction.create_commitment()
        with self.pinned_sources():
            transaction.recover_incomplete()
            transaction.create_commitment()
            transaction.validate_commitment()

    def test_public_opening_has_no_inputs_and_pending_authority_denies_before_map(self):
        self.create()
        self.assertEqual(set(inspect.signature(chronology.authorize_opening).parameters), set())
        original = transaction._read_complete_pair
        private_reads = []
        def track(read_map):
            private_reads.append(read_map)
            if read_map:
                raise AssertionError("private map read before authentic chain")
            return original(read_map)
        with self.pinned_sources(), mock.patch.object(transaction, "_read_complete_pair", side_effect=track):
            result = chronology.authorize_opening()
        self.assertEqual(result["decision"], "DENY_BEFORE_PRIVATE_MAP_READ")
        self.assertEqual(result["reason"], "AUTHENTIC_HUMAN_AUTHORITY_ABSENT_OR_PENDING")
        self.assertFalse(result["private_map_read"])
        self.assertNotIn(True, private_reads)

    def test_forged_authority_and_full_post_grade_rebind_deny_before_map(self):
        self.create()
        examples = chronology.build_schema_examples()
        # A fully self-consistent synthetic chain is not authentic authority.
        chronology.validate_chain_values(examples["chain_values"])
        fake_registry = SimpleNamespace(ContractError=ValueError, validate_registry_attestations=lambda: {"decision": "forged-live"})
        original = transaction._read_complete_pair
        private_reads = []
        def track(read_map):
            private_reads.append(read_map)
            if read_map:
                raise AssertionError("forged chain reached private map")
            return original(read_map)
        with self.pinned_sources(), mock.patch.object(chronology.importlib, "import_module", return_value=fake_registry), mock.patch.object(transaction, "_read_complete_pair", side_effect=track):
            result = chronology.authorize_opening()
        self.assertEqual(result["reason"], "FIXED_HUMAN_VALIDATOR_SUBSTITUTION")
        self.assertNotIn(True, private_reads)
        # Full post-grade rebinding to a new commitment remains synthetic and denied.
        rebound = copy.deepcopy(examples["chain_values"])
        new_binding = copy.deepcopy(examples["binding"])
        new_binding["canonical_digest"] = "f" * 64
        rebound[chronology.BLOCK_GRANT_PATH]["commitment_binding"] = new_binding
        for cell in chronology.CELL_IDS:
            rebound[chronology.ATTEMPT_PATHS[cell]]["commitment_binding"] = new_binding
        rebound[chronology.METRICS_PATH]["commitment_binding"] = new_binding
        rebound[chronology.MANIFEST_PATH]["commitment_binding"] = new_binding
        # Exact original grant refs now fail: rebinding cannot rewrite chronology retroactively.
        with self.assertRaises(chronology.ChronologyError):
            chronology.validate_chain_values(rebound)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema unavailable")
    def test_all_eleven_schemas_positive_four_malformed_and_nested_extras(self):
        self.create()
        root = Path(chronology.__file__).resolve().parent
        schemas = {path.name: Draft202012Validator(json.loads(path.read_text())) for path in root.glob("*.schema.json")}
        self.assertEqual(len(schemas), 11)
        for validator in schemas.values():
            Draft202012Validator.check_schema(validator.schema)
            self.assertFalse(validator.schema["additionalProperties"])
        examples = chronology.build_schema_examples()
        _, commitment, private_map, _ = transaction._read_complete_pair(read_map=True)
        receipt = json.loads((transaction._root_path() / transaction.RECEIPT_NAME).read_text())
        positives = {
            "blind-map-v3.schema.json": private_map,
            "blind-map-commitment-v3.schema.json": commitment,
            "transaction-receipt-v3.schema.json": receipt,
            "artifact-ref-v3.schema.json": examples["grant"]["human_authority_refs"][0],
            "block-grant-v3.schema.json": examples["grant"],
            "block-grant-review-v3.schema.json": examples["grant_review"],
            "attempt-receipt-v3.schema.json": examples["attempt"],
            "evaluation-packet-record-v3.schema.json": examples["packet"],
            "human-grade-record-v3.schema.json": examples["grade"],
            "derived-metrics-record-v3.schema.json": examples["metrics"],
            "chronology-manifest-v3.schema.json": examples["manifest"],
        }
        for name, value in positives.items():
            schemas[name].validate(value)
        chronology.validate_chain_values(examples["chain_values"])
        attempts = {cell: examples["chain_values"][chronology.ATTEMPT_PATHS[cell]] for cell in chronology.CELL_IDS}
        packets = {cell: examples["chain_values"][chronology.PACKET_PATHS[cell]] for cell in chronology.CELL_IDS}
        grades = {(cell, role): examples["chain_values"][chronology.GRADE_PATHS[(cell, role)]] for cell in chronology.CELL_IDS for role in ("G1", "G2")}
        chronology._validate_external_artifacts(attempts, packets, grades, examples["metrics"], examples["external_artifacts"])
        probes = []
        empty_grade = copy.deepcopy(examples["grade"]); empty_grade["cell_id"] = ""; probes.append(("human-grade-record-v3.schema.json", empty_grade))
        empty_metric_cell = copy.deepcopy(examples["metrics"]); empty_metric_cell["cells"][0]["cell_id"] = ""; probes.append(("derived-metrics-record-v3.schema.json", empty_metric_cell))
        empty_grade_refs = copy.deepcopy(examples["metrics"]); empty_grade_refs["cells"][0]["grade_record_refs"] = []; probes.append(("derived-metrics-record-v3.schema.json", empty_grade_refs))
        wrong_receipt = copy.deepcopy(examples["grant"]); wrong_receipt["commitment_binding"]["receipt_ref"]["path"] = "unexpected.json"; probes.append(("block-grant-v3.schema.json", wrong_receipt))
        for name, value in probes:
            self.assertTrue(list(schemas[name].iter_errors(value)), name)
        nested = copy.deepcopy(examples["metrics"]); nested["cells"][0]["packet_record_ref"]["extra"] = True
        self.assertTrue(list(schemas["derived-metrics-record-v3.schema.json"].iter_errors(nested)))
        duplicate = copy.deepcopy(examples["manifest"]); duplicate["attempt_receipt_refs"][1] = duplicate["attempt_receipt_refs"][0]
        self.assertTrue(list(schemas["chronology-manifest-v3.schema.json"].iter_errors(duplicate)))
        bad_external = copy.deepcopy(examples["external_artifacts"]); first_cell = chronology.CELL_IDS[0]; bad_external[chronology.RESULT_PATHS[first_cell]]["payload_sha256"] = "0" * 64
        with self.assertRaises(chronology.ChronologyError):
            chronology._validate_external_artifacts(attempts, packets, grades, examples["metrics"], bad_external)
        sequence = copy.deepcopy(examples["chain_values"]); sequence[chronology.PACKET_PATHS[chronology.CELL_IDS[0]]]["produced_sequence"] = 1
        with self.assertRaises(chronology.ChronologyError):
            chronology.validate_chain_values(sequence)

    def test_value_suppressing_leak_scan(self):
        self.create()
        with self.pinned_sources():
            clean = chronology.scan_label_leaks()
        rendered = json.dumps(clean, sort_keys=True)
        private = json.loads((transaction._root_path() / transaction.PRIVATE_MAP_NAME).read_text())
        labels = [item["label"] for item in private["cells"]]
        self.assertTrue(all(label not in rendered for label in labels))
        self.assertFalse(clean["label_values_disclosed"])
        leak = self.workspace / "neutral.txt"
        leak.write_text(labels[0])
        with self.pinned_sources():
            detected = chronology.scan_label_leaks()
        rendered = json.dumps(detected, sort_keys=True)
        self.assertEqual(detected["total_matching_paths"], 1)
        self.assertTrue(all(label not in rendered for label in labels))

    def test_v1_v2_open_history_unchanged(self):
        expected = {
            "runtime/r6_data_quality_blind_map_commitment_v1/owner-private-canonical-map-v1.json": (807, "fd7d7adfe3e7c53d5b4293426ae6d07c1fdd2aa1fbbe39d031183e2587862e7a"),
            "runtime/r6_data_quality_blind_map_commitment_v2/owner-private-canonical-map-v2.json": (897, "8c0affb05319a96f4044a5cc663827b6b6c7613e6cddc0c4d08ca23ae169515d"),
            "tuning/architecture/r6_data_quality_blind_map_commitment_v1/producer-verification-v1.json": (4925, "5a2a437464476bb102d224e247354c2d15ec27b62fdcdd845d7fc768a617f648"),
            "tuning/architecture/r6_data_quality_blind_map_commitment_v2/producer-verification-v2.json": (6790, "65598f229232900a9b7380f3fb1ef6eead71a6364fdee5f472d2462b5f0d8461"),
        }
        for relative, identity in expected.items():
            raw = (REAL_WORKSPACE / relative).read_bytes()
            self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), identity)


if __name__ == "__main__":
    unittest.main()
