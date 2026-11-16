from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import stat
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v2 import commitment as subject
from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3 import harness
from shared.job_runtime.tests.candidates.r6_data_quality_2x2_evaluation_v3.test_evaluation_v3 import Root, grade

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None


REAL_WORKSPACE = Path(__file__).resolve().parents[5]


class BlindMapCommitmentV2(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace / "runtime").mkdir(mode=0o700)
        self.root_patch = mock.patch.object(subject, "WORKSPACE_ROOT", self.workspace)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    @contextmanager
    def pinned_sources(self):
        original = subject._verify_pinned_sources

        def verify():
            old = subject.WORKSPACE_ROOT
            try:
                subject.WORKSPACE_ROOT = REAL_WORKSPACE
                original()
            finally:
                subject.WORKSPACE_ROOT = old

        with mock.patch.object(subject, "_verify_pinned_sources", side_effect=verify):
            yield

    @property
    def root(self):
        return subject.WORKSPACE_ROOT / subject.RUNTIME_RELATIVE_ROOT

    def create(self):
        with self.pinned_sources():
            return subject.create_commitment()

    def validate(self):
        with self.pinned_sources():
            return subject.validate_commitment()

    def test_nominal_marker_bound_pair_and_no_replace(self):
        commitment = self.create()
        self.assertEqual(set(os.listdir(self.root)), {subject.PRIVATE_MAP_NAME, subject.COMMITMENT_NAME, subject.RECEIPT_NAME})
        for name in os.listdir(self.root):
            status = os.lstat(self.root / name)
            self.assertTrue(stat.S_ISREG(status.st_mode))
            self.assertEqual(stat.S_IMODE(status.st_mode), 0o600)
            self.assertEqual(status.st_uid, os.getuid())
        self.assertEqual(self.validate(), commitment)
        receipt = json.loads((self.root / subject.RECEIPT_NAME).read_text())
        self.assertTrue(receipt["complete"])
        for key, name in (("map_ref", subject.PRIVATE_MAP_NAME), ("commitment_ref", subject.COMMITMENT_NAME)):
            raw = (self.root / name).read_bytes()
            self.assertEqual(receipt[key], {"path": name, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
        with self.assertRaisesRegex(subject.CommitmentError, "COMPLETE_TRANSACTION_EXISTS"):
            self.create()
        packets = None
        with self.pinned_sources():
            packets = subject.build_pre_call_packets()
        self.assertEqual(tuple(packets), subject.CELL_IDS)
        bindings = [packet["commitment_binding"] for packet in packets.values()]
        self.assertTrue(all(binding == bindings[0] for binding in bindings))
        self.assertEqual(len({packet["blind_alias"] for packet in packets.values()}), 4)
        self.assertEqual(set(inspect.signature(subject.create_commitment).parameters), set())
        self.assertEqual(set(inspect.signature(subject.validate_commitment).parameters), set())
        self.assertEqual(set(inspect.signature(subject.recover_incomplete).parameters), set())

    def test_preexisting_conflict_is_recovered_and_retry_succeeds(self):
        self.root.mkdir(mode=0o700)
        conflict = self.root / subject.COMMITMENT_NAME
        conflict.write_bytes(b"conflict")
        os.chmod(conflict, 0o600)
        with self.assertRaisesRegex(subject.CommitmentError, "TRANSACTION_RECOVERED_RETRY"):
            self.create()
        self.assertEqual(os.listdir(self.root), [])
        self.create()
        self.validate()

    def test_crash_residues_recover_deterministically(self):
        for residue in ("stage", "one-final", "mixed-finals"):
            with self.subTest(residue=residue), tempfile.TemporaryDirectory() as td:
                workspace = Path(td).resolve()
                (workspace / "runtime").mkdir(mode=0o700)
                subject.WORKSPACE_ROOT = workspace
                root = workspace / subject.RUNTIME_RELATIVE_ROOT
                root.mkdir(mode=0o700)
                if residue == "stage":
                    path = root / (".stage-" + "0" * 32 + "-map.json")
                    path.write_bytes(b"partial")
                    os.chmod(path, 0o600)
                elif residue == "one-final":
                    path = root / subject.PRIVATE_MAP_NAME
                    path.write_bytes(b"partial")
                    os.chmod(path, 0o600)
                else:
                    for name in (subject.PRIVATE_MAP_NAME, subject.COMMITMENT_NAME):
                        path = root / name
                        path.write_bytes(b"partial")
                        os.chmod(path, 0o600)
                recovered = subject.recover_incomplete()
                self.assertTrue(recovered["status"].startswith("RECOVERED"))
                self.assertFalse(any(name in os.listdir(root) for name in (subject.PRIVATE_MAP_NAME, subject.COMMITMENT_NAME, subject.RECEIPT_NAME)))
                with self.pinned_sources():
                    subject.create_commitment()
                    subject.validate_commitment()
        subject.WORKSPACE_ROOT = self.workspace

    def _retry_after_failure(self):
        with self.pinned_sources():
            recovered = subject.recover_incomplete()
            self.assertIn(recovered["status"], ("CLEAN", "RECOVERED_INCOMPLETE", "RECOVERED_INVALID"))
            if recovered["status"].startswith("RECOVERED"):
                with self.assertRaisesRegex(subject.CommitmentError, "TRANSACTION_RECOVERED_RETRY"):
                    pass
            subject.create_commitment()
            subject.validate_commitment()

    def test_zero_and_positive_short_writes_cleanup_and_retry(self):
        real_write = os.write
        first = True

        def zero_once(fd, data):
            nonlocal first
            if first:
                first = False
                return 0
            return real_write(fd, data)

        with self.pinned_sources(), mock.patch.object(subject.os, "write", side_effect=zero_once):
            with self.assertRaisesRegex(subject.CommitmentError, "ARTIFACT_ZERO_WRITE"):
                subject.create_commitment()
        self.assertFalse(any(subject.STAGE_RE.fullmatch(name) or name in (subject.PRIVATE_MAP_NAME, subject.COMMITMENT_NAME, subject.RECEIPT_NAME) for name in os.listdir(self.root)))
        real_calls = []

        def short(fd, data):
            real_calls.append(len(data))
            return real_write(fd, data[: max(1, min(5, len(data)))])

        with self.pinned_sources(), mock.patch.object(subject.os, "write", side_effect=short):
            subject.create_commitment()
            subject.validate_commitment()
        self.assertGreater(len(real_calls), 3)

    def test_every_forward_fsync_boundary_cleanup_and_retry(self):
        file_boundaries = ("map_stage_file", "commitment_stage_file", "receipt_file")
        dir_boundaries = ("root_parent_create", "map_stage_stage_dir", "commitment_stage_stage_dir", "map_namespace_dir", "commitment_namespace_dir", "receipt_commit_dir")
        for kind, boundary in [("file", x) for x in file_boundaries] + [("dir", x) for x in dir_boundaries]:
            with self.subTest(kind=kind, boundary=boundary), tempfile.TemporaryDirectory() as td:
                workspace = Path(td).resolve()
                (workspace / "runtime").mkdir(mode=0o700)
                subject.WORKSPACE_ROOT = workspace
                original = subject._fsync_file if kind == "file" else subject._fsync_dir
                fired = False

                def inject(fd, seen_boundary):
                    nonlocal fired
                    if not fired and seen_boundary == boundary:
                        fired = True
                        raise OSError("injected fsync")
                    return original(fd, seen_boundary)

                patch_target = "_fsync_file" if kind == "file" else "_fsync_dir"
                with self.pinned_sources(), mock.patch.object(subject, patch_target, side_effect=inject):
                    with self.assertRaises(subject.CommitmentError):
                        subject.create_commitment()
                with self.pinned_sources():
                    recovery = subject.recover_incomplete()
                    if recovery["status"].startswith("RECOVERED"):
                        with self.assertRaisesRegex(subject.CommitmentError, "TRANSACTION_RECOVERED_RETRY"):
                            subject.create_commitment()
                    subject.create_commitment()
                    subject.validate_commitment()
        subject.WORKSPACE_ROOT = self.workspace

    def test_link_readback_and_cleanup_fsync_failures_are_recoverable(self):
        failures = ("link", "readback", "cleanup")
        for failure in failures:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as td:
                workspace = Path(td).resolve()
                (workspace / "runtime").mkdir(mode=0o700)
                subject.WORKSPACE_ROOT = workspace
                with self.pinned_sources():
                    if failure == "link":
                        with mock.patch.object(subject.os, "link", side_effect=OSError("injected link")):
                            with self.assertRaises(subject.CommitmentError):
                                subject.create_commitment()
                    elif failure == "readback":
                        original = subject._read_name
                        fired = False

                        def fail_once(*args, **kwargs):
                            nonlocal fired
                            if not fired:
                                fired = True
                                raise subject.CommitmentError("INJECTED_READBACK")
                            return original(*args, **kwargs)

                        with mock.patch.object(subject, "_read_name", side_effect=fail_once):
                            with self.assertRaises(subject.CommitmentError):
                                subject.create_commitment()
                    else:
                        real_write = subject.os.write
                        write_fired = False
                        cleanup_fired = False

                        def zero_once(fd, data):
                            nonlocal write_fired
                            if not write_fired:
                                write_fired = True
                                return 0
                            return real_write(fd, data)

                        original_dir = subject._fsync_dir

                        def cleanup_fail_once(fd, boundary):
                            nonlocal cleanup_fired
                            if boundary == "cleanup_dir" and not cleanup_fired:
                                cleanup_fired = True
                                raise OSError("cleanup fsync")
                            return original_dir(fd, boundary)

                        with mock.patch.object(subject.os, "write", side_effect=zero_once), mock.patch.object(subject, "_fsync_dir", side_effect=cleanup_fail_once):
                            with self.assertRaises(subject.CommitmentError):
                                subject.create_commitment()
                    subject.recover_incomplete()
                    subject.create_commitment()
                    subject.validate_commitment()
        subject.WORKSPACE_ROOT = self.workspace

    def _evaluation_fixture(self):
        legacy_root = Root()
        self.addCleanup(legacy_root.close)
        mapping = {harness.ALIASES[cell]: {"cell_id": cell, "provider": harness.CELL_MAP[cell][0], "addon": harness.CELL_MAP[cell][1]} for cell in harness.CELL_ORDER}
        mapref = legacy_root.mapref(mapping, "fixture-nonce")
        authority = legacy_root.authority()
        evaluation_packets = {}
        for cell in harness.CELL_ORDER:
            alias = harness.ALIASES[cell]
            evaluation_packets[cell] = harness.build_blind_packet(legacy_root.store, alias, legacy_root.bundle(alias), mapref, 200, 60)
        grades = {cell: [grade("G1", evaluation_packets[cell], authority, 300 + i * 2), grade("G2", evaluation_packets[cell], authority, 301 + i * 2)] for i, cell in enumerate(harness.CELL_ORDER)}
        return evaluation_packets, grades, authority

    def _bound_fixture(self):
        self.create()
        with self.pinned_sources():
            pre_packets = subject.build_pre_call_packets()
            evaluation_packets, grades, authority = self._evaluation_fixture()
            grade_bindings = {cell: [subject.build_grade_binding(pre_packets[cell], evaluation_packets[cell], value) for value in grades[cell]] for cell in subject.CELL_IDS}
            bound = subject.build_bound_metrics(pre_packets, evaluation_packets, grades, grade_bindings, authority)
        return pre_packets, evaluation_packets, grades, grade_bindings, bound, authority

    @contextmanager
    def trusted_live(self, authority):
        authority.fixture = False
        authority.registry = dict(authority.registry, registry_kind="LIVE", countable=True)
        review_sha = authority.registry_review_ref["sha256"]
        with mock.patch.object(harness, "TRUSTED_LIVE_REGISTRY_REVIEW_SHA256S", frozenset({review_sha})):
            yield

    def _authorize(self, fixture, authority=None):
        pre_packets, evaluation_packets, grades, grade_bindings, bound, original_authority = fixture
        authority = authority or original_authority
        with self.pinned_sources():
            return subject.authorize_opening(pre_packets, evaluation_packets, grades, grade_bindings, bound["metrics"], bound["binding"], authority)

    def test_fixture_noncountable_and_pending_human_authority_deny_before_map(self):
        fixture = self._bound_fixture()
        authority = fixture[-1]
        original_read = subject._read_complete_pair
        reads = []

        def track(read_map):
            reads.append(read_map)
            return original_read(read_map)

        with mock.patch.object(subject, "_read_complete_pair", side_effect=track):
            with self.assertRaisesRegex(subject.CommitmentError, "OPENING_FIXTURE_AUTHORITY_DENIED"):
                self._authorize(fixture)
        self.assertNotIn(True, reads)
        authority.fixture = False
        with mock.patch.object(subject, "_read_complete_pair", side_effect=track):
            with self.assertRaisesRegex(subject.CommitmentError, "OPENING_NONCOUNTABLE_AUTHORITY_DENIED"):
                self._authorize(fixture)
        authority.registry = dict(authority.registry, registry_kind="LIVE", countable=True)
        with mock.patch.object(subject, "_read_complete_pair", side_effect=track):
            with self.assertRaisesRegex(subject.CommitmentError, "OPENING_PENDING_HUMAN_AUTHORITY_DENIED"):
                self._authorize(fixture)
        self.assertNotIn(True, reads)

    def test_bound_provider_free_opening_remains_disabled(self):
        fixture = self._bound_fixture()
        with self.trusted_live(fixture[-1]):
            result = self._authorize(fixture)
        self.assertFalse(result["activation"])
        self.assertFalse(result["countable"])
        self.assertEqual({item["cell_id"] for item in result["mapping"]}, set(subject.CELL_IDS))

    def test_unbound_alias_commitment_and_metric_substitution_fail_before_map(self):
        fixture = self._bound_fixture()
        pre_packets, evaluation_packets, grades, grade_bindings, bound, authority = fixture
        with self.trusted_live(authority):
            swapped = copy.deepcopy(pre_packets)
            first, second = subject.CELL_IDS[:2]
            body_a = {k: v for k, v in swapped[first].items() if k not in ("artifact_sha256", "artifact_bytes")}
            body_b = {k: v for k, v in swapped[second].items() if k not in ("artifact_sha256", "artifact_bytes")}
            body_a["blind_alias"], body_b["blind_alias"] = body_b["blind_alias"], body_a["blind_alias"]
            swapped[first], swapped[second] = subject.seal(body_a), subject.seal(body_b)
            with self.pinned_sources():
                swapped_bindings = {cell: [subject.build_grade_binding(swapped[cell], evaluation_packets[cell], value) for value in grades[cell]] for cell in subject.CELL_IDS}
                swapped_bound = subject.build_bound_metrics(swapped, evaluation_packets, grades, swapped_bindings, authority)
            swapped_fixture = (swapped, evaluation_packets, grades, swapped_bindings, swapped_bound, authority)
            with self.assertRaisesRegex(subject.CommitmentError, "OPENING_ALIAS_MAP_BINDING"):
                self._authorize(swapped_fixture)
            bad_packet = copy.deepcopy(pre_packets)
            body = {k: v for k, v in bad_packet[first].items() if k not in ("artifact_sha256", "artifact_bytes")}
            body["commitment_binding"] = dict(body["commitment_binding"], canonical_digest="0" * 64)
            bad_packet[first] = subject.seal(body)
            with self.assertRaisesRegex(subject.CommitmentError, "BOUND_PACKET_COMMITMENT"):
                self._authorize((bad_packet, evaluation_packets, grades, grade_bindings, bound, authority))
            bad_metrics = copy.deepcopy(bound["metrics"])
            bad_metrics["artifact_sha256"] = "0" * 64
            with self.assertRaises((subject.CommitmentError, harness.ContractError)):
                with self.pinned_sources():
                    subject.authorize_opening(pre_packets, evaluation_packets, grades, grade_bindings, bad_metrics, bound["binding"], authority)

    def test_second_and_post_grade_map_cannot_open_same_packets(self):
        fixture = self._bound_fixture()
        authority = fixture[-1]
        first_workspace = subject.WORKSPACE_ROOT
        with tempfile.TemporaryDirectory() as td:
            second_workspace = Path(td).resolve()
            (second_workspace / "runtime").mkdir(mode=0o700)
            subject.WORKSPACE_ROOT = second_workspace
            with self.pinned_sources():
                subject.create_commitment()
            with self.trusted_live(authority):
                with self.assertRaisesRegex(subject.CommitmentError, "BOUND_PACKET_COMMITMENT"):
                    self._authorize(fixture)
        subject.WORKSPACE_ROOT = first_workspace
        # Replace the committed transaction only after packets, grades, and metrics exist.
        for name in (subject.RECEIPT_NAME, subject.PRIVATE_MAP_NAME, subject.COMMITMENT_NAME):
            (self.root / name).unlink()
        with self.pinned_sources():
            subject.create_commitment()
        with self.trusted_live(authority):
            with self.assertRaisesRegex(subject.CommitmentError, "BOUND_PACKET_COMMITMENT"):
                self._authorize(fixture)

    @unittest.skipIf(Draft202012Validator is None, "jsonschema unavailable")
    def test_six_strict_draft_2020_12_schemas(self):
        self.create()
        with self.pinned_sources():
            packets = subject.build_pre_call_packets()
        root = Path(subject.__file__).resolve().parent
        paths = sorted(root.glob("*.schema.json"))
        self.assertEqual(len(paths), 6)
        for path in paths:
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            self.assertFalse(schema["additionalProperties"])
        Draft202012Validator(json.loads((root / "pre-call-packet-v2.schema.json").read_text())).validate(next(iter(packets.values())))


if __name__ == "__main__":
    unittest.main()
