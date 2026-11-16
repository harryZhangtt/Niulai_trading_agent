from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v1 import commitment as subject
from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3.harness import ALIASES, CELL_MAP, CELL_ORDER, ContractError, build_blind_packet
from shared.job_runtime.tests.candidates.r6_data_quality_2x2_evaluation_v3.test_evaluation_v3 import Root, grade

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


class BlindMapCommitmentV1(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace / "runtime").mkdir(mode=0o700)
        self.patch_root = mock.patch.object(subject, "WORKSPACE_ROOT", self.workspace)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)

    @property
    def root(self):
        return self.workspace / subject.RUNTIME_RELATIVE_ROOT

    @property
    def private_path(self):
        return self.root / subject.PRIVATE_MAP_NAME

    @property
    def commitment_path(self):
        return self.root / subject.COMMITMENT_NAME

    def create(self):
        with mock.patch.object(subject, "_verify_pinned_sources", wraps=subject._verify_pinned_sources):
            # Pinned sources remain under the real workspace for tests.
            with mock.patch.object(subject, "WORKSPACE_ROOT", Path(__file__).resolve().parents[5]):
                # Redirect only after source verification through a scoped helper.
                subject._verify_pinned_sources()
        real_workspace = Path(__file__).resolve().parents[5]
        original = subject._verify_pinned_sources
        def verify():
            old = subject.WORKSPACE_ROOT
            try:
                subject.WORKSPACE_ROOT = real_workspace
                original()
            finally:
                subject.WORKSPACE_ROOT = old
        with mock.patch.object(subject, "_verify_pinned_sources", side_effect=verify):
            return subject.create_commitment()

    def validate(self):
        real_workspace = Path(__file__).resolve().parents[5]
        original = subject._verify_pinned_sources
        def verify():
            old = subject.WORKSPACE_ROOT
            try:
                subject.WORKSPACE_ROOT = real_workspace
                original()
            finally:
                subject.WORKSPACE_ROOT = old
        with mock.patch.object(subject, "_verify_pinned_sources", side_effect=verify):
            return subject.validate_commitment()

    def test_nominal_atomic_private_map_and_sanitized_commitment(self):
        commitment = self.create()
        self.assertEqual(set(commitment), {"version", "schema", "canonical_digest", "canonical_bytes"})
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.private_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.commitment_path.stat().st_mode), 0o600)
        map_raw = self.private_path.read_bytes()
        self.assertEqual(len(map_raw), commitment["canonical_bytes"])
        self.assertEqual(hashlib.sha256(map_raw).hexdigest(), commitment["canonical_digest"])
        private_map = json.loads(map_raw)
        self.assertEqual({x["cell_id"] for x in private_map["cells"]}, set(subject.CELL_IDS))
        labels = [x["label"] for x in private_map["cells"]]
        self.assertEqual(labels, sorted(labels))
        self.assertEqual(len(set(labels)), 4)
        self.assertEqual(self.validate(), commitment)
        self.assertEqual(set(inspect.signature(subject.create_commitment).parameters), set())
        self.assertEqual(set(inspect.signature(subject.validate_commitment).parameters), set())
        self.assertEqual(set(inspect.signature(subject.authorize_opening).parameters), {"packets", "grades", "authority"})

    def test_no_replace_preserves_first_artifacts(self):
        first = self.create()
        first_map = self.private_path.read_bytes()
        first_commitment = self.commitment_path.read_bytes()
        with self.assertRaisesRegex(subject.CommitmentError, "ARTIFACT_EXISTS_NO_REPLACE"):
            self.create()
        self.assertEqual(self.private_path.read_bytes(), first_map)
        self.assertEqual(self.commitment_path.read_bytes(), first_commitment)
        self.assertEqual(json.loads(first_commitment), first)

    def test_full_write_loop_and_fsyncs(self):
        real_write = os.write
        calls = []
        def partial(fd, data):
            calls.append(len(data))
            return real_write(fd, data[: max(1, min(7, len(data)))])
        real_fsync = os.fsync
        syncs = []
        def fsync(fd):
            syncs.append(fd)
            return real_fsync(fd)
        with mock.patch.object(subject.os, "write", side_effect=partial), mock.patch.object(subject.os, "fsync", side_effect=fsync):
            self.create()
        self.assertGreater(len(calls), 2)
        self.assertGreaterEqual(len(syncs), 5)  # root parent + file/root for both artifacts
        self.validate()

    def test_traversal_symlink_nonregular_mode_owner_and_substitution_fail(self):
        self.create()
        with self.assertRaisesRegex(subject.CommitmentError, "PATH_NOT_FIXED"):
            subject._read_file("../" + subject.PRIVATE_MAP_NAME)
        os.chmod(self.private_path, 0o644)
        with self.assertRaisesRegex(subject.CommitmentError, "ARTIFACT_MODE"):
            self.validate()
        os.chmod(self.private_path, 0o600)
        target = self.root / "neutral.json"
        self.private_path.rename(target)
        self.private_path.symlink_to(target)
        with self.assertRaisesRegex(subject.CommitmentError, "ARTIFACT_OPEN_NOFOLLOW"):
            self.validate()
        self.private_path.unlink()
        target.rename(self.private_path)
        with mock.patch.object(subject.os, "getuid", return_value=os.getuid() + 1):
            with self.assertRaisesRegex(subject.CommitmentError, "ROOT_OWNER"):
                subject._read_file(subject.PRIVATE_MAP_NAME)
        raw = bytearray(self.private_path.read_bytes())
        raw[-2] = ord("0") if raw[-2] != ord("0") else ord("1")
        self.private_path.write_bytes(bytes(raw))
        os.chmod(self.private_path, 0o600)
        with self.assertRaises(subject.CommitmentError):
            self.validate()
        self.private_path.unlink()
        self.private_path.mkdir(mode=0o700)
        with self.assertRaisesRegex(subject.CommitmentError, "ARTIFACT_NOT_REGULAR"):
            self.validate()

    def test_root_symlink_substitution_fails(self):
        target = self.workspace / "neutral-root"
        target.mkdir(mode=0o700)
        self.root.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(subject.CommitmentError, "ROOT_SYMLINK"):
            self.create()

    def test_duplicate_label_cell_and_order_leakage_fail(self):
        self.create()
        private_map = json.loads(self.private_path.read_text())
        duplicate_label = json.loads(json.dumps(private_map))
        duplicate_label["cells"][1]["label"] = duplicate_label["cells"][0]["label"]
        with self.assertRaisesRegex(subject.CommitmentError, "MAP_LABEL_DUPLICATE"):
            subject._validate_private_map(duplicate_label)
        duplicate_cell = json.loads(json.dumps(private_map))
        duplicate_cell["cells"][1]["cell_id"] = duplicate_cell["cells"][0]["cell_id"]
        with self.assertRaisesRegex(subject.CommitmentError, "MAP_CELL_DUPLICATE"):
            subject._validate_private_map(duplicate_cell)
        leaking = {**private_map, "cells": [{"label": f"{index:032x}", "cell_id": cell} for index, cell in enumerate(subject.CELL_IDS, 1)]}
        with self.assertRaisesRegex(subject.CommitmentError, "MAP_ORDER_LEAKAGE"):
            subject._validate_private_map(leaking)
        named = {**private_map, "cells": [{"label": f"BLIND-{i}", "cell_id": cell} for i, cell in enumerate(subject.CELL_IDS, 1)]}
        with self.assertRaisesRegex(subject.CommitmentError, "MAP_LABEL_OPAQUE"):
            subject._validate_private_map(named)

    def test_strict_draft_2020_12_schemas(self):
        commitment = self.create()
        source_dir = Path(subject.__file__).resolve().parent
        map_schema = json.loads((source_dir / "blind-map-v1.schema.json").read_text())
        commitment_schema = json.loads((source_dir / "blind-map-commitment-v1.schema.json").read_text())
        for schema in (map_schema, commitment_schema):
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["required"]), set(schema["properties"]))
        item_schema = map_schema["properties"]["cells"]["items"]
        self.assertFalse(item_schema["additionalProperties"])
        self.assertEqual(set(item_schema["required"]), set(item_schema["properties"]))
        self.assertEqual((map_schema["properties"]["cells"]["minItems"], map_schema["properties"]["cells"]["maxItems"]), (4, 4))
        if Draft202012Validator is not None:
            Draft202012Validator.check_schema(map_schema)
            Draft202012Validator.check_schema(commitment_schema)
            private_map = json.loads(self.private_path.read_text())
            Draft202012Validator(map_schema).validate(private_map)
            Draft202012Validator(commitment_schema).validate(commitment)
            bad = dict(commitment, provider="forbidden")
            self.assertTrue(list(Draft202012Validator(commitment_schema).iter_errors(bad)))

    def _evaluation_fixture(self):
        root = Root()
        self.addCleanup(root.close)
        mapping = {ALIASES[cell]: {"cell_id": cell, "provider": CELL_MAP[cell][0], "addon": CELL_MAP[cell][1]} for cell in CELL_ORDER}
        mapref = root.mapref(mapping, "fixture-nonce")
        authority = root.authority()
        packets = {}
        for cell in CELL_ORDER:
            alias = ALIASES[cell]
            packets[cell] = build_blind_packet(root.store, alias, root.bundle(alias), mapref, 200, 60)
        grades = {cell: [grade("G1", packets[cell], authority, 300 + i * 2), grade("G2", packets[cell], authority, 301 + i * 2)] for i, cell in enumerate(CELL_ORDER)}
        return packets, grades, authority

    def _authorize(self, packets, grades, authority):
        real_workspace = Path(__file__).resolve().parents[5]
        original = subject._verify_pinned_sources
        def verify():
            old = subject.WORKSPACE_ROOT
            try:
                subject.WORKSPACE_ROOT = real_workspace
                original()
            finally:
                subject.WORKSPACE_ROOT = old
        with mock.patch.object(subject, "_verify_pinned_sources", side_effect=verify):
            return subject.authorize_opening(packets, grades, authority)

    def test_opening_requires_immutable_gates_g1_g2_conditional_g3_and_metrics(self):
        self.create()
        packets, grades, authority = self._evaluation_fixture()
        result = self._authorize(packets, grades, authority)
        self.assertFalse(result["activation"])
        self.assertFalse(result["countable"])
        self.assertTrue(result["derived_metrics"]["immutable"])
        self.assertEqual({x["cell_id"] for x in result["mapping"]}, set(subject.CELL_IDS))
        cell = CELL_ORDER[0]
        disagree = dict(grades)
        disagree[cell] = [grade("G1", packets[cell], authority, 300, dim={"accuracy": "L4_EXCEPTIONAL"}), grade("G2", packets[cell], authority, 301, dim={"accuracy": "L1_WEAK"})]
        with mock.patch.object(subject, "_read_private_map", side_effect=AssertionError("private map opened early")) as read_map:
            with self.assertRaisesRegex(ContractError, "G3_REQUIREMENT"):
                self._authorize(packets, disagree, authority)
            read_map.assert_not_called()
        disagree[cell].append(grade("G3", packets[cell], authority, 302))
        self.assertFalse(self._authorize(packets, disagree, authority)["countable"])

    def test_opening_rejects_cell_order_and_grade_substitution_before_private_read(self):
        self.create()
        packets, grades, authority = self._evaluation_fixture()
        reversed_packets = dict(reversed(tuple(packets.items())))
        with mock.patch.object(subject, "_read_private_map", side_effect=AssertionError("private map opened early")) as read_map:
            with self.assertRaisesRegex(subject.CommitmentError, "OPENING_FOUR_CELL_ORDER"):
                self._authorize(reversed_packets, grades, authority)
            read_map.assert_not_called()
        bad_grades = dict(grades)
        bad_grades[CELL_ORDER[0]] = bad_grades[CELL_ORDER[0]][:1]
        with mock.patch.object(subject, "_read_private_map", side_effect=AssertionError("private map opened early")) as read_map:
            with self.assertRaisesRegex(ContractError, "G1_G2_REQUIRED"):
                self._authorize(packets, bad_grades, authority)
            read_map.assert_not_called()


if __name__ == "__main__":
    unittest.main()
