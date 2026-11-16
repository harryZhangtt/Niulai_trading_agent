from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import multiprocessing
import os
import re
import stat
import tempfile
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v6 import chronology, transaction
from shared.job_runtime.tests.candidates.r6_data_quality_blind_map_commitment_v6.fixtures import _build_examples

REAL = Path(__file__).resolve().parents[5]
OPEN_REVIEW = REAL / "mentor/runtime/scheduler-midresponse-recovery-20261107/claude-r6-data-quality-blind-map-commitment-v5-independent-review-open-v1-fable-20261113.json"


def _schema_errors(schema, value, path="$", *, conditional=False):
    """Validate the closed Draft-2020 subset used by these eleven schemas."""
    errors = []
    if "const" in schema and value != schema["const"]: errors.append(path + ":const")
    if "enum" in schema and value not in schema["enum"]: errors.append(path + ":enum")
    kind = schema.get("type")
    valid_type = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }.get(kind, True)
    if not valid_type: return errors + [path + ":type"]
    if isinstance(value, str):
        if "pattern" in schema and re.fullmatch(schema["pattern"], value) is None: errors.append(path + ":pattern")
        if len(value) < schema.get("minLength", 0): errors.append(path + ":minLength")
        if "maxLength" in schema and len(value) > schema["maxLength"]: errors.append(path + ":maxLength")
    if isinstance(value, int) and not isinstance(value, bool):
        if value < schema.get("minimum", value): errors.append(path + ":minimum")
        if value > schema.get("maximum", value): errors.append(path + ":maximum")
    if isinstance(value, dict):
        required = schema.get("required", ())
        errors += [path + "." + key + ":required" for key in required if key not in value]
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            errors += [path + "." + key + ":additional" for key in value if key not in properties]
        for key, child in properties.items():
            if key in value: errors += _schema_errors(child, value[key], path + "." + key)
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0): errors.append(path + ":minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]: errors.append(path + ":maxItems")
        if schema.get("uniqueItems"):
            rendered = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(rendered) != len(set(rendered)): errors.append(path + ":uniqueItems")
        prefix = schema.get("prefixItems", ())
        for index, child in enumerate(prefix[:len(value)]): errors += _schema_errors(child, value[index], f"{path}[{index}]")
        items = schema.get("items")
        if items is False and len(value) > len(prefix): errors.append(path + ":itemsFalse")
        elif isinstance(items, dict):
            start = len(prefix) if prefix else 0
            for index in range(start, len(value)): errors += _schema_errors(items, value[index], f"{path}[{index}]")
    for child in schema.get("allOf", ()): errors += _schema_errors(child, value, path)
    if "oneOf" in schema:
        matches = sum(not _schema_errors(child, value, path, conditional=True) for child in schema["oneOf"])
        if matches != 1: errors.append(path + ":oneOf")
    if "if" in schema:
        branch = "then" if not _schema_errors(schema["if"], value, path, conditional=True) else "else"
        if branch in schema: errors += _schema_errors(schema[branch], value, path)
    return errors


def _hold_reservation(workspace: str, ready, release, result) -> None:
    transaction.WORKSPACE_ROOT = Path(workspace)
    transaction._ensure_root()
    txid = "a" * 32
    try:
        identity = transaction._acquire_reservation(txid, "CREATE")
        ready.set(); release.wait(10)
        transaction._release_reservation(txid, identity)
        result.put("released")
    except BaseException as exc:
        result.put(type(exc).__name__ + ":" + str(exc))


def _race_creator(workspace: str, start, result) -> None:
    transaction.WORKSPACE_ROOT = Path(workspace)
    transaction._verify_pinned_sources = lambda: None
    start.wait(10)
    try:
        transaction.create_commitment(); result.put("success")
    except transaction.CommitmentError as exc:
        result.put("deny:" + str(exc))


class V6(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve(); (self.workspace / "runtime").mkdir(mode=0o700)
        self.tp = mock.patch.object(transaction, "WORKSPACE_ROOT", self.workspace)
        self.cp = mock.patch.object(chronology, "WORKSPACE_ROOT", self.workspace)
        self.tp.start(); self.cp.start(); self.addCleanup(self.tp.stop); self.addCleanup(self.cp.stop)

    @contextmanager
    def pins(self):
        original = transaction._verify_pinned_sources
        def verify():
            old = transaction.WORKSPACE_ROOT
            try: transaction.WORKSPACE_ROOT = REAL; original()
            finally: transaction.WORKSPACE_ROOT = old
        with mock.patch.object(transaction, "_verify_pinned_sources", side_effect=verify): yield

    def create(self):
        with self.pins(): return transaction.create_commitment()

    def schemas(self):
        root = Path(chronology.__file__).resolve().parent
        return {p.name: json.loads(p.read_text()) for p in root.glob("*.schema.json")}

    def _opening_probe(self, g3_required: bool, *, include_g3_pins=True, report_overrides=None,
                       wrong_transaction=False, mutate=None):
        ex = _build_examples(g3_required)
        if mutate: mutate(ex)
        values = {**ex["chain_values"], **ex["external_artifacts"]}
        chain_pins = {p: chronology._value_ref(p, v) for p, v in values.items()}
        names = ("REGISTRY", "REGISTRY_REVIEW", "G1", "G1_REVIEW", "G2", "G2_REVIEW") + (("G3", "G3_REVIEW") if g3_required and include_g3_pins else ())
        human_pins = {chronology.HUMAN_PATHS[n]: ex["human_pins"][chronology.HUMAN_PATHS[n]] for n in names}
        events = []
        class Store:
            def read(self, path): events.append(("chain", path)); return values[path]
        class RegistryError(ValueError): pass
        class Registry:
            ContractError = RegistryError
            def validate_registry_attestations(self, root, g3_triggered=False):
                events.append(("registry", root, g3_triggered))
                report = {"decision": "VALIDATED_FOR_SEPARATE_EXPLICIT_PINNING_NOT_LIVE", "g3_triggered": g3_triggered, "validated_roles": ["G1", "G2"] + (["G3"] if g3_triggered else []), "activation": False, "countable": False}
                report.update(report_overrides or {}); return report
            def _secure_read(self, root, path, mode, code):
                pin = human_pins[path]; events.append(("human", path)); return {}, pin["sha256"], pin["bytes"]
        aliases = {c: ex["chain_values"][chronology.ATTEMPT_PATHS[c]]["blind_alias"] for c in chronology.CELL_IDS}
        private_map = {"cell_order": list(chronology.CELL_IDS), "labels": [aliases[c] for c in chronology.CELL_IDS]}
        wrong = dict(ex["binding"], transaction_id="f" * 32)
        def pair(read_map, **kwargs):
            events.append(("private", read_map))
            return {}, {}, private_map if read_map else None, wrong if wrong_transaction else ex["binding"]
        with mock.patch.object(chronology, "AUTHENTIC_CHAIN_PINS", chain_pins), mock.patch.object(chronology, "AUTHENTIC_HUMAN_PINS", human_pins), mock.patch.object(chronology, "_FixedArtifactStore", return_value=Store()), mock.patch.object(chronology, "_load_fixed_human_validator", return_value=Registry()), mock.patch.object(transaction, "_read_complete_pair", side_effect=pair):
            result = chronology.authorize_opening()
        return result, events, ex, chain_pins, human_pins

    def test_zero_arg_current_pins_and_compiled_validator(self):
        self.assertEqual({}, dict(inspect.signature(chronology.authorize_opening).parameters))
        with mock.patch.object(transaction, "_read_complete_pair", side_effect=AssertionError("private transaction read")):
            result = chronology.authorize_opening()
        self.assertEqual("DENY_BEFORE_PRIVATE_MAP_READ", result["decision"]); self.assertFalse(result["private_map_read"])
        loaded = chronology._load_fixed_human_validator()
        self.assertIs(loaded.validate_registry_attestations.__globals__, loaded.__dict__)
        self.assertTrue(loaded.__name__.endswith("_v6"))

    def test_wrong_current_transaction_denies_before_map(self):
        result, events, *_ = self._opening_probe(False, wrong_transaction=True)
        self.assertEqual("DENY_BEFORE_PRIVATE_MAP_READ", result["decision"])
        self.assertEqual([False], [event[1] for event in events if event[0] == "private"])

    def test_g3_false_and_true_exact_artifact_authority(self):
        for required, external_count, grade_count in ((False, 21, 8), (True, 25, 12)):
            result, events, ex, pins, human = self._opening_probe(required)
            self.assertEqual("FIXED_CHAIN_VALIDATED_STILL_DISABLED", result["decision"])
            self.assertEqual(("chain", chronology.MANIFEST_PATH), events[0])
            self.assertEqual([False, True], [event[1] for event in events if event[0] == "private"])
            self.assertEqual(external_count, len(ex["external_artifacts"])); self.assertEqual(grade_count, len(ex["manifest"]["human_grade_record_refs"]))
            if not required:
                self.assertTrue(chronology.G3_EXTERNAL_ARTIFACT_PATHS.isdisjoint(pins))
                self.assertNotIn(chronology.HUMAN_PATHS["G3"], human)
                self.assertFalse(any(path in pins for path in (chronology.GRADE_PATHS[(cell, "G3")] for cell in chronology.CELL_IDS)))

    def test_g3_pending_noncountable_digest_and_authority_mismatch_deny_pre_map(self):
        cases = [
            {"report_overrides": {"decision": "PENDING"}},
            {"report_overrides": {"countable": True}},
            {"include_g3_pins": False},
        ]
        for kwargs in cases:
            result, events, *_ = self._opening_probe(True, **kwargs)
            self.assertEqual("DENY_BEFORE_PRIVATE_MAP_READ", result["decision"]); self.assertFalse(any(e[0] == "private" for e in events))
        def digest_mismatch(ex):
            path = chronology.GRADE_ARTIFACT_PATHS[(chronology.CELL_IDS[0], "G3")]
            ex["external_artifacts"][path] = dict(ex["external_artifacts"][path], payload_sha256="f" * 64)
        result, events, *_ = self._opening_probe(True, mutate=digest_mismatch)
        self.assertEqual("DENY_BEFORE_PRIVATE_MAP_READ", result["decision"]); self.assertFalse(any(e[0] == "private" for e in events))
        def authority_mismatch(ex):
            grade = ex["chain_values"][chronology.GRADE_PATHS[(chronology.CELL_IDS[0], "G3")]]
            grade["human_grant_ref"] = dict(grade["human_grant_ref"], sha256="e" * 64)
        result, events, *_ = self._opening_probe(True, mutate=authority_mismatch)
        self.assertEqual("DENY_BEFORE_PRIVATE_MAP_READ", result["decision"]); self.assertFalse(any(e[0] == "private" for e in events))

    def test_global_chronology_and_resealed_interleaving_reject(self):
        for required in (False, True): self.assertEqual("VALID_CHAIN_VALUES_NOT_AUTHORITY", chronology.validate_chain_values(_build_examples(required)["chain_values"])["status"])
        ex = _build_examples(); bad = copy.deepcopy(ex["chain_values"]); cell = chronology.CELL_IDS[0]
        bad[chronology.PACKET_PATHS[cell]]["produced_sequence"] = 9
        for role, seq in (("G1", 12), ("G2", 13)):
            grade = bad[chronology.GRADE_PATHS[(cell, role)]]; grade["produced_sequence"] = seq
            grade["packet_record_ref"] = chronology._value_ref(chronology.PACKET_PATHS[cell], bad[chronology.PACKET_PATHS[cell]])
        metrics = bad[chronology.METRICS_PATH]
        metrics["cells"][0]["packet_record_ref"] = chronology._value_ref(chronology.PACKET_PATHS[cell], bad[chronology.PACKET_PATHS[cell]])
        metrics["cells"][0]["grade_record_refs"] = [chronology._value_ref(chronology.GRADE_PATHS[(cell, r)], bad[chronology.GRADE_PATHS[(cell, r)]]) for r in ("G1", "G2")]
        manifest = bad[chronology.MANIFEST_PATH]; manifest["evaluation_packet_record_refs"][0] = chronology._value_ref(chronology.PACKET_PATHS[cell], bad[chronology.PACKET_PATHS[cell]])
        for role in ("G1", "G2"):
            index = ("G1", "G2").index(role) * 4; manifest["human_grade_record_refs"][index] = chronology._value_ref(chronology.GRADE_PATHS[(cell, role)], bad[chronology.GRADE_PATHS[(cell, role)]])
        manifest["derived_metrics_record_ref"] = chronology._value_ref(chronology.METRICS_PATH, metrics)
        with self.assertRaises(chronology.ChronologyError): chronology.validate_chain_values(bad)

    def test_eleven_schemas_positive_conditionals_and_prior_negative_probes(self):
        self.create(); schemas = self.schemas(); self.assertEqual(12, len(schemas))
        for schema in schemas.values(): self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"]); self.assertFalse(schema["additionalProperties"])
        ex = _build_examples(); g3 = _build_examples(True)
        _, commitment, pmap, _ = transaction._read_complete_pair(True)
        receipt = json.loads((transaction._root_path() / transaction.RECEIPT_NAME).read_text())
        released_name = next(name for name in os.listdir(transaction._root_path()) if transaction.RELEASED_RE.fullmatch(name))
        released_lock = json.loads((transaction._root_path() / released_name).read_text())
        positives = {"transaction-lock-v6.schema.json": released_lock, "blind-map-v6.schema.json": pmap, "blind-map-commitment-v6.schema.json": commitment, "transaction-receipt-v6.schema.json": receipt, "artifact-ref-v6.schema.json": ex["grant"]["human_authority_refs"][0], "block-grant-v6.schema.json": ex["grant"], "block-grant-review-v6.schema.json": ex["grant_review"], "attempt-receipt-v6.schema.json": ex["attempt"], "evaluation-packet-record-v6.schema.json": ex["packet"], "human-grade-record-v6.schema.json": ex["grade"], "derived-metrics-record-v6.schema.json": ex["metrics"], "chronology-manifest-v6.schema.json": ex["manifest"]}
        for name, value in positives.items(): self.assertFalse(_schema_errors(schemas[name], value), name)
        self.assertFalse(_schema_errors(schemas["derived-metrics-record-v6.schema.json"], g3["metrics"])); self.assertFalse(_schema_errors(schemas["chronology-manifest-v6.schema.json"], g3["manifest"]))
        conditional = copy.deepcopy(ex["manifest"]); conditional["g3_required"] = True
        self.assertTrue(_schema_errors(schemas["chronology-manifest-v6.schema.json"], conditional))
        probes = []
        value = copy.deepcopy(pmap); value["design_identity"] = "0" * 64; probes.append(("blind-map-v6.schema.json", value))
        value = copy.deepcopy(pmap); value["labels"][1] = value["labels"][0]; probes.append(("blind-map-v6.schema.json", value))
        value = copy.deepcopy(pmap); value["cell_order"] = list(reversed(value["cell_order"])); probes.append(("blind-map-v6.schema.json", value))
        value = copy.deepcopy(ex["packet"]); value["attempt_receipt_ref"]["path"] = chronology.ATTEMPT_PATHS[chronology.CELL_IDS[1]]; probes.append(("evaluation-packet-record-v6.schema.json", value))
        value = copy.deepcopy(ex["grade"]); value["human_grant_ref"]["path"] = chronology.HUMAN_PATHS["G2"]; value["human_grant_review_ref"]["path"] = chronology.HUMAN_PATHS["G2_REVIEW"]; value["grade_artifact_ref"]["path"] = chronology.GRADE_ARTIFACT_PATHS[(chronology.CELL_IDS[0], "G2")]; probes.append(("human-grade-record-v6.schema.json", value))
        value = copy.deepcopy(ex["metrics"]); value["cells"][1]["cell_id"] = value["cells"][0]["cell_id"]; probes.append(("derived-metrics-record-v6.schema.json", value))
        value = copy.deepcopy(ex["manifest"]); value["human_grade_record_refs"][0], value["human_grade_record_refs"][1] = value["human_grade_record_refs"][1], value["human_grade_record_refs"][0]; probes.append(("chronology-manifest-v6.schema.json", value))
        value = copy.deepcopy(ex["attempt"]); value["commitment_binding"]["receipt_ref"]["mode"] = "0644"; probes.append(("attempt-receipt-v6.schema.json", value))
        value = copy.deepcopy(ex["metrics"]); value["cells"][2]["packet_record_ref"]["extra"] = True; probes.append(("derived-metrics-record-v6.schema.json", value))
        value = copy.deepcopy(ex["manifest"]); value["human_grade_record_refs"][3]["extra"] = True; probes.append(("chronology-manifest-v6.schema.json", value))
        value = copy.deepcopy(ex["grant"]); value["human_authority_refs"][0]["path"] = "wrong.json"; probes.append(("block-grant-v6.schema.json", value))
        value = copy.deepcopy(receipt); value["map_ref"]["mode"] = "0644"; probes.append(("transaction-receipt-v6.schema.json", value))
        for name, value in probes: self.assertTrue(_schema_errors(schemas[name], value), name)
        self.assertEqual(transaction.COMMITMENT_SCHEMA_ID, commitment["schema"])

    def test_transaction_self_binding_receipt_last_and_no_delete_helpers(self):
        commitment = self.create(); root = transaction._root_path()
        receipt_raw, receipt_identity = transaction._read_name(transaction.RECEIPT_NAME)
        receipt = json.loads(receipt_raw); map_raw, map_identity = transaction._read_name(transaction.PRIVATE_MAP_NAME); commitment_raw, commitment_identity = transaction._read_name(transaction.COMMITMENT_NAME)
        self.assertEqual(receipt["artifact_identity"], transaction._identity_value(receipt_identity))
        self.assertEqual(receipt["map_identity"], transaction._identity_value(map_identity)); self.assertEqual(receipt["commitment_identity"], transaction._identity_value(commitment_identity))
        self.assertEqual(receipt["transaction_id"], json.loads(map_raw)["transaction_id"]); self.assertEqual(receipt["transaction_id"], json.loads(commitment_raw)["transaction_id"])
        self.assertEqual(transaction.COMMITMENT_SCHEMA_ID, commitment["schema"])
        source = Path(transaction.__file__).read_text(); tree = ast.parse(source)
        self.assertNotIn("seal", vars(transaction)); self.assertNotIn("verify_seal", vars(transaction)); self.assertNotIn("_name_identity", vars(transaction))
        self.assertFalse([node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr in ("unlink", "remove", "rmdir")])
        self.assertFalse(any(transaction.STAGE_RE.fullmatch(name) for name in os.listdir(root)))

    def test_multiprocess_creation_and_recovery_cannot_inspect_live_transaction(self):
        self.assertIn("fork", multiprocessing.get_all_start_methods()); ctx = multiprocessing.get_context("fork")
        transaction._ensure_root(); ready, release, result = ctx.Event(), ctx.Event(), ctx.Queue()
        holder = ctx.Process(target=_hold_reservation, args=(str(self.workspace), ready, release, result)); holder.start(); self.assertTrue(ready.wait(5))
        with mock.patch.object(transaction, "_verify_pinned_sources"), mock.patch.object(transaction, "_read_name", side_effect=AssertionError("inspected live transaction")):
            with self.assertRaisesRegex(transaction.CommitmentError, "TRANSACTION_LOCKED_NO_INSPECTION"): transaction.create_commitment()
            with self.assertRaisesRegex(transaction.CommitmentError, "TRANSACTION_LOCKED_NO_INSPECTION"): transaction.recover_incomplete()
        release.set(); holder.join(10); self.assertEqual(0, holder.exitcode); self.assertEqual("released", result.get(timeout=2))
        start, results = ctx.Event(), ctx.Queue(); processes = [ctx.Process(target=_race_creator, args=(str(self.workspace), start, results)) for _ in range(2)]
        for process in processes: process.start()
        start.set()
        for process in processes: process.join(10); self.assertEqual(0, process.exitcode)
        outcomes = [results.get(timeout=2) for _ in processes]
        self.assertEqual(1, outcomes.count("success")); self.assertEqual(1, sum(x.startswith("deny:") for x in outcomes))

    def test_cleanup_only_owned_and_inode_replacement_fences_without_delete(self):
        transaction._ensure_root(); txa, txb = "a" * 32, "b" * 32
        namea, nameb = f".stage-{txa}-map.json", f".stage-{txb}-map.json"
        _, ida, _ = transaction._write_bound(namea, lambda own: {"version": 6, "transaction_id": txa, "artifact_identity": transaction._identity_value(own)}, transient=True)
        _, idb, _ = transaction._write_bound(nameb, lambda own: {"version": 6, "transaction_id": txb, "artifact_identity": transaction._identity_value(own)}, transient=True)
        transaction._cleanup_owned({namea: (txa, ida)})
        self.assertTrue((transaction._root_path() / nameb).exists()); self.assertEqual(idb, transaction._read_name(nameb, transient=True)[1])
        root = transaction._root_path(); replacement = f".stage-{'c'*32}-map.json"
        _, original_identity, _ = transaction._write_bound(replacement, lambda own: {"version": 6, "transaction_id": "c" * 32, "artifact_identity": transaction._identity_value(own)}, transient=True)
        (root / replacement).unlink(); (root / replacement).write_bytes(b"replacement"); os.chmod(root / replacement, 0o600)
        with self.assertRaisesRegex(transaction.CommitmentError, "CLEANUP_IDENTITY_FENCED"):
            transaction._quarantine_owned(replacement, "c" * 32, original_identity, transient=True)
        self.assertTrue(any(name.startswith(f".quarantine-{'c'*32}-") for name in os.listdir(root)))

    def test_fixed_reads_are_bounded_before_allocation(self):
        self.create(); receipt = transaction._root_path() / transaction.RECEIPT_NAME
        receipt.unlink(); receipt.write_bytes(b"x" * 11_000_000); os.chmod(receipt, 0o600)
        with mock.patch.object(transaction.os, "read", side_effect=AssertionError("unbounded read")) as read:
            with self.assertRaisesRegex(transaction.CommitmentError, "ARTIFACT_OVERSIZE"): transaction._read_name(transaction.RECEIPT_NAME)
            read.assert_not_called()
        chronology_dir = transaction._root_path() / "chronology"; chronology_dir.mkdir(mode=0o700)
        manifest = chronology_dir / Path(chronology.MANIFEST_PATH).name; manifest.write_bytes(b"x" * (chronology.CHAIN_SCHEMA_MAX_BYTES["manifest"] + 1)); os.chmod(manifest, 0o600)
        pin = {"path": chronology.MANIFEST_PATH, "bytes": manifest.stat().st_size, "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(), "mode": "0600"}
        with mock.patch.object(chronology, "AUTHENTIC_CHAIN_PINS", {chronology.MANIFEST_PATH: pin}), mock.patch.object(chronology.os, "read", side_effect=AssertionError("unbounded chain read")) as read:
            with self.assertRaisesRegex(chronology.ChronologyError, "CHAIN_SCHEMA_MAX_BYTES"): chronology._FixedArtifactStore().read(chronology.MANIFEST_PATH)
            read.assert_not_called()

    def test_leak_scan_fail_closed_large_unreadable_symlink_and_value_suppression(self):
        self.create(); root = transaction._root_path(); _, _, private, _ = transaction._read_complete_pair(True); label = private["labels"][0]
        clean = chronology.scan_label_leaks(); self.assertEqual(("PASS", "CLEAN"), (clean["status"], clean["decision"]))
        leaked = self.workspace / "untracked-leak.txt"; leaked.write_text(label)
        result = chronology.scan_label_leaks(); self.assertEqual(("FAIL", "DENY", 1), (result["status"], result["decision"], result["total_matching_paths"])); self.assertNotIn(label, json.dumps(result, sort_keys=True)); leaked.unlink()
        (self.workspace / "logs").mkdir(); (self.workspace / "logs" / "oversize.log").write_bytes(b"x" * 11_000_000)
        unreadable = self.workspace / "tracked-unreadable.txt"; unreadable.write_text("safe"); unreadable.chmod(0)
        symlink = self.workspace / "runtime" / "map-link"; symlink.symlink_to(root / transaction.PRIVATE_MAP_NAME)
        opened_private = []
        real_open = chronology.os.open
        def track(path, *args, **kwargs):
            if isinstance(path, str) and "owner-private-canonical-map-" in path: opened_private.append(path)
            return real_open(path, *args, **kwargs)
        with mock.patch.object(chronology.os, "open", side_effect=track): result = chronology.scan_label_leaks()
        self.assertEqual(("ERROR", "DENY"), (result["status"], result["decision"])); self.assertGreaterEqual(result["errors_by_kind"]["oversize"], 1); self.assertGreaterEqual(result["errors_by_kind"]["symlink"], 1); self.assertGreaterEqual(result["errors_by_kind"]["unreadable"], 1); self.assertEqual([transaction.PRIVATE_MAP_NAME], opened_private)
        unreadable.chmod(0o600)

    def test_public_surface_effect_free_and_history_exact(self):
        public = [name for name, value in vars(chronology).items() if not name.startswith("_") and callable(value)]
        self.assertFalse([name for name in public if any(token in name.lower() for token in ("build", "example", "fixture"))])
        self.assertEqual({"CommitmentError", "authorize_opening", "create_commitment", "recover_incomplete", "scan_label_leaks", "validate_commitment"}, set(__import__("shared.job_runtime.candidates.r6_data_quality_blind_map_commitment_v6", fromlist=[""]).__all__))
        imports = {node.names[0].name.split(".")[0] for node in ast.walk(ast.parse(Path(chronology.__file__).read_text())) if isinstance(node, ast.Import)} | {(node.module or "").split(".")[0] for node in ast.walk(ast.parse(Path(chronology.__file__).read_text())) if isinstance(node, ast.ImportFrom)}
        self.assertTrue(imports.isdisjoint({"subprocess", "socket", "requests", "httpx", "smtplib", "bytedcli"}))
        raw = OPEN_REVIEW.read_bytes(); self.assertEqual((23467, "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8"), (len(raw), hashlib.sha256(raw).hexdigest()))
        review = json.loads(raw); self.assertEqual(13, len(review["findings"])); self.assertEqual([f"OPEN-V5-{i:02d}" for i in range(1, 14)], [item["id"] for item in review["findings"]])
        for row in review["reviewed_subjects"]:
            path = REAL / row["path"]; data = path.read_bytes(); self.assertEqual((row["bytes"], row["sha256"], row["mode"]), (len(data), hashlib.sha256(data).hexdigest(), format(stat.S_IMODE(os.lstat(path).st_mode), "04o")), row["path"])
        # Historical public runtime evidence only; never read any owner-private map.
        producer = json.loads((REAL / "tuning/architecture/r6_data_quality_blind_map_commitment_v5/producer-verification-v5.json").read_text())
        for row in producer["runtime_bindings"]:
            if "owner-private" in row["path"]: continue
            data = (REAL / row["path"]).read_bytes(); self.assertEqual((row["bytes"], row["sha256"]), (len(data), hashlib.sha256(data).hexdigest()))


if __name__ == "__main__": unittest.main()
