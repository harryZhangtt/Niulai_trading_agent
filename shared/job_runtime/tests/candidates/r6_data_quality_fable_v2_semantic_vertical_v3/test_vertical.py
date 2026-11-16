from __future__ import annotations
import ast
import hashlib
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone

from shared.job_runtime.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.vertical import (
    BundleOwnerV3, CELLS, DISPOSITIONS, EFFECTS, OWNER_CHAIN, PROMPT_BYTES, PROMPT_SHA256,
    SOURCE_SHA256, ConfigOwnerV3, DesignOwnerV3, IntegrationOwnerV3,
    MaterializationOwnerV3, ProposalOwnerV3, TerminalRawArtifactV3,
    VerticalV3Error, execute, exercise_disposition)

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_semantic_vertical_v3/prompt-source-v3.json"
AT = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

def result_schema_fingerprint(packet):
    return packet["database"]["schema_fingerprint"]

class VerticalV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".job-runtime")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.root.chmod(0o700)
        self.workspace = self.root / "workspace"; self.workspace.mkdir(mode=0o700)
        (self.workspace / ".job-runtime").mkdir(mode=0o700)

    def run_nominal(self, suffix="nominal", fault=None):
        return execute(repo_root=ROOT, source_path=SOURCE, workspace=self.workspace,
            output_root=self.root / suffix, scheduled=AT, fault=fault)

    def test_nominal_full_vertical_and_packet(self):
        result = self.run_nominal()
        self.assertEqual((len(result["prompt_bytes"]), hashlib.sha256(result["prompt_bytes"]).hexdigest()),
                         (PROMPT_BYTES, PROMPT_SHA256))
        self.assertEqual(result["prompt"]["source_identity_sha256"], SOURCE_SHA256)
        self.assertEqual(result["old166"]["member_count"], 166)
        self.assertEqual(result["bridge"]["receipt"]["joined_rows"], 2)
        self.assertTrue(result["bridge"]["receipt"]["source_connection_closed"])
        self.assertTrue(result["bridge"]["receipt"]["snapshot_connection_closed"])
        self.assertEqual(result["bundle"]["contract"], BundleOwnerV3.CONTRACT)
        self.assertEqual([item["contract"] for item in result["stages"]],
                         [f"r6.{name}-owner.v3" for name in OWNER_CHAIN])
        self.assertEqual(len(result["transitions"]), len(OWNER_CHAIN))
        for transition in result["transitions"]:
            receipt = transition["receipt"]
            self.assertEqual(receipt["owner_version"], 3)
            for key in ("input_digest", "output_digest", "prompt_descriptor_map_digest"):
                self.assertRegex(receipt[key], r"^[0-9a-f]{64}$")
            self.assertEqual(tuple(receipt["cell_bindings"]), CELLS)
            self.assertEqual(tuple(receipt["provider_results"]), CELLS)
        budget = result["stages"][1]["budget"]
        self.assertEqual((budget["per_arm_max_usd"], budget["aggregate_max_usd"],
                          budget["user_approved"], budget["billed"], budget["prompt_utf8_bytes"],
                          budget["prompt_tokens"]), (.02, .04, True, False, 526, None))
        self.assertEqual(result["packet_sha256"], hashlib.sha256(json.dumps(result["packet"],
            sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest())
        self.assertEqual(result["decision"]["packet_sha256"], result["packet_sha256"])
        self.assertEqual(result["producer_receipt"]["status"], "PENDING_INDEPENDENT_REVIEW")
        self.assertTrue(all(value == 0 for value in result["effects"].values()))
        self.assertEqual(result["packet"]["config"]["load_job_count"], 2)
        self.assertTrue(result["packet"]["config"]["engine_validate_job"])

    def test_all_dispositions_cross_engine_parser_bundle(self):
        for disposition in DISPOSITIONS:
            workspace = self.root / ("ws-" + disposition.lower()); workspace.mkdir(mode=0o700)
            (workspace / ".job-runtime").mkdir(mode=0o700)
            result = exercise_disposition(SOURCE, workspace, self.root / ("out-" + disposition.lower()),
                                          disposition, AT)
            cells = result["bundle"]["cells"]
            self.assertEqual([cell["disposition"] for cell in cells], [disposition, disposition])
            self.assertTrue(all(cell["denominator_included"] for cell in cells))
            self.assertTrue(all(cell["prompt"]["sha256"] == PROMPT_SHA256 for cell in cells))
            self.assertTrue(all(cell["publication_attempts"] == 0 for cell in cells))
            self.assertEqual(all(cell["unknown_fenced"] for cell in cells),
                             disposition in ("MISSING", "UNKNOWN"))
            rows = result["bridge"]["rows"]
            self.assertTrue(all(json.loads(row["canonical_json"])["receipt"]["parser_disposition"]
                                == disposition for row in rows))
            if disposition == "MALFORMED":
                self.assertTrue(all(json.loads(row["canonical_json"])["receipt"]["parsed_terminal"]
                                    is None for row in rows))

    def test_raw_first_restart_and_no_replace(self):
        result = self.run_nominal("restart")
        before = {p.relative_to(self.root / "restart").as_posix(): p.read_bytes()
                  for p in (self.root / "restart").rglob("*") if p.is_file()}
        restarted = BundleOwnerV3.build(result["bridge"]["rows"], result["terminal_artifacts"], self.root / "restart")
        after = {p.relative_to(self.root / "restart").as_posix(): p.read_bytes()
                 for p in (self.root / "restart").rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(restarted, result["bundle"])
        crash_root = self.root / "crash-restart"
        with self.assertRaisesRegex(VerticalV3Error, "INJECTED_CRASH_AFTER_RAW"):
            BundleOwnerV3.build(result["bridge"]["rows"], result["terminal_artifacts"], crash_root, fault_after_raw=True)
        self.assertTrue((crash_root / "control" / "control.raw").is_file())
        recovered = BundleOwnerV3.build(result["bridge"]["rows"], result["terminal_artifacts"], crash_root)
        self.assertEqual(recovered, result["bundle"])

        rows = [dict(row) for row in result["bridge"]["rows"]]
        artifacts = dict(result["terminal_artifacts"])
        first_ref = json.loads(rows[0]["canonical_json"])["receipt"]["terminal_artifact_ref"]
        original = artifacts[first_ref]
        artifacts[first_ref] = TerminalRawArtifactV3(original.ref, original.raw + b"x",
            original.sha256, original.length, original.phase, original.submission)
        with self.assertRaisesRegex(VerticalV3Error, "BUNDLE_TERMINAL_ARTIFACT_MISMATCH"):
            BundleOwnerV3.build(rows, artifacts, self.root / "raw-mismatch")
        artifacts[first_ref] = original
        value = json.loads(rows[0]["canonical_json"])
        value["receipt"]["terminal_sha256"] = "0" * 64
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
        rows[0]["canonical_json"] = encoded
        rows[0]["canonical_sha256"] = hashlib.sha256(encoded.encode()).hexdigest()
        with self.assertRaisesRegex(VerticalV3Error, "BUNDLE_TERMINAL_ARTIFACT_MISMATCH"):
            BundleOwnerV3.build(rows, artifacts, self.root / "receipt-mismatch")


    def test_faults_each_owner_boundary(self):
        # Each durable Engine run gets its own workspace.
        for fault in ("integration", "design", "materialization", "proposal", "config"):
            workspace = self.root / ("fault-" + fault); workspace.mkdir(mode=0o700)
            (workspace / ".job-runtime").mkdir(mode=0o700)
            with self.assertRaises(VerticalV3Error):
                execute(repo_root=ROOT, source_path=SOURCE, workspace=workspace,
                    output_root=self.root / ("fault-out-" + fault), scheduled=AT, fault=fault)

        result = self.run_nominal("owner-corruption")
        authority = {key: result["stages"][0][key] for key in
                     ("prompt_descriptors", "cell_bindings", "provider_results")}
        owners = (IntegrationOwnerV3, DesignOwnerV3, MaterializationOwnerV3,
                  ProposalOwnerV3, ConfigOwnerV3)
        for owner, transition in zip(owners, result["transitions"]):
            predecessor, output = transition["input"], transition["output"]
            owner.validate(output, predecessor, authority)
            for key in tuple(output):
                bad = dict(output); bad.pop(key)
                with self.assertRaises(VerticalV3Error, msg=owner.CONTRACT + ":" + key):
                    owner.validate(bad, predecessor, authority)
            families = []
            bad = dict(output); bad["predecessor_contract"] = "wrong"; families.append(bad)
            bad = dict(output); bad["input_digest"] = "0" * 64; families.append(bad)
            for map_key in ("prompt_descriptors", "cell_bindings", "provider_results"):
                bad = dict(output); changed = dict(output[map_key]); changed.pop("treatment"); bad[map_key] = changed; families.append(bad)
            for cell in CELLS:
                bad = dict(output); changed = dict(output["cell_bindings"]); changed[cell] = "1" * 64; bad["cell_bindings"] = changed; families.append(bad)
                bad = dict(output); changed = dict(output["provider_results"]); changed[cell] = "2" * 64; bad["provider_results"] = changed; families.append(bad)
            for field, wrong in (("version", 2), ("ref", "wrong"), ("sha256", "5" * 64), ("length", 525),
                                 ("source_identity_sha256", "6" * 64), ("generation", "wrong"),
                                 ("proof_origin", "backfilled_v8")):
                bad = dict(output); descriptors = {cell: dict(value) for cell, value in output["prompt_descriptors"].items()}
                descriptors["control"][field] = wrong; bad["prompt_descriptors"] = descriptors; families.append(bad)
            semantic_key = {IntegrationOwnerV3:"joined_rows", DesignOwnerV3:"arms",
                MaterializationOwnerV3:"installed", ProposalOwnerV3:"apply",
                ConfigOwnerV3:"load_required"}[owner]
            bad = dict(output); bad[semantic_key] = None; families.append(bad)
            for bad in families:
                with self.assertRaises(VerticalV3Error, msg=owner.CONTRACT):
                    owner.validate(bad, predecessor, authority)
        builders = ((DesignOwnerV3.build, result["transitions"][0]),
            (lambda value, auth: MaterializationOwnerV3.build(value, auth, AT), result["transitions"][1]),
            (ProposalOwnerV3.build, result["transitions"][2]),
            (ConfigOwnerV3.build, result["transitions"][3]))
        for builder, envelope in builders:
            for key in tuple(envelope):
                missing = dict(envelope); missing.pop(key)
                with self.assertRaises(VerticalV3Error): builder(missing, authority)
            bad = dict(envelope); receipt = dict(envelope["receipt"]); receipt["output_digest"] = "3" * 64; bad["receipt"] = receipt
            with self.assertRaises(VerticalV3Error): builder(bad, authority)
            bad = dict(envelope); output = dict(envelope["output"]); output["input_digest"] = "4" * 64; bad["output"] = output
            with self.assertRaises(VerticalV3Error): builder(bad, authority)


    def test_generic_source_identity_is_strict_authority_input(self):
        result = self.run_nominal("generic-source-identity")
        authority = {key: {cell: (dict(value) if key == "prompt_descriptors" else value)
                           for cell, value in result["stages"][0][key].items()}
                     for key in ("prompt_descriptors", "cell_bindings", "provider_results")}
        for descriptor in authority["prompt_descriptors"].values():
            descriptor["source_identity_sha256"] = "a" * 64
        envelope = IntegrationOwnerV3.build(result["bundle"], authority)
        IntegrationOwnerV3.validate(envelope["output"], envelope["input"], authority)
        bad = dict(envelope["output"])
        descriptors = {cell: dict(value) for cell, value in bad["prompt_descriptors"].items()}
        descriptors["control"]["source_identity_sha256"] = "b" * 64
        bad["prompt_descriptors"] = descriptors
        with self.assertRaises(VerticalV3Error):
            IntegrationOwnerV3.validate(bad, envelope["input"], authority)

    def test_bundle_owner_has_no_arbitrary_callback_surface(self):
        parameters = inspect.signature(BundleOwnerV3.build).parameters
        self.assertNotIn("after_raw", parameters)
        self.assertFalse(any(parameter.kind in (inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD) for parameter in parameters.values()))
        source = inspect.getsource(BundleOwnerV3.build)
        self.assertNotIn("callback", source)
        self.assertNotIn("after_raw", source.replace("fault_after_raw", ""))

    def test_prompt_and_bridge_faults_fail_closed(self):
        tampered = self.root / "prompt-source.json"
        tampered.write_bytes(SOURCE.read_bytes() + b" ")
        workspace = self.root / "prompt-fault-ws"; workspace.mkdir(mode=0o700)
        (workspace / ".job-runtime").mkdir(mode=0o700)
        with self.assertRaisesRegex(VerticalV3Error, "PROMPT_SOURCE_HASH"):
            execute(repo_root=ROOT, source_path=tampered, workspace=workspace,
                    output_root=self.root / "prompt-fault-out", scheduled=AT)
        workspace2 = self.root / "bridge-fault-ws"; workspace2.mkdir(mode=0o700)
        (workspace2 / ".job-runtime").mkdir(mode=0o700)
        with self.assertRaisesRegex(VerticalV3Error, "BUNDLE_PROVIDER_RESULT_DIGEST"):
            execute(repo_root=ROOT, source_path=SOURCE, workspace=workspace2,
                    output_root=self.root / "bridge-fault-out", scheduled=AT, fault="bridge")

    def test_retained_packet_and_architecture_bindings(self):
        fixture = ROOT / "shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_semantic_vertical_v3/evidence-packet-v3.json"
        raw = fixture.read_bytes(); packet = json.loads(raw)
        canonical = json.dumps(packet, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        packet_sha = hashlib.sha256(canonical).hexdigest()
        arch = ROOT / "tuning/architecture/r6_data_quality_fable_v2_semantic_vertical_v3"
        for name in ("protocol-v3.json", "decision-v3.json", "producer-verification-v3.json",
                     "source-closure-v3.json"):
            self.assertEqual(json.loads((arch / name).read_text())["packet_sha256"], packet_sha)
        self.assertEqual(packet["prompt"]["sha256"], PROMPT_SHA256)
        self.assertEqual(packet["schema9_fingerprint"], result_schema_fingerprint(packet))
        self.assertTrue(packet["sanitized"])
        self.assertTrue(all(value == 0 for value in packet["effects"].values()))
        protocol = json.loads((arch / "protocol-v3.json").read_text())
        self.assertEqual(protocol["packet_file_sha256"], hashlib.sha256(raw).hexdigest())
        closure = json.loads((arch / "source-closure-v3.json").read_text())
        for member in closure["members"]:
            data = (ROOT / member["path"]).read_bytes()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()),
                             (member["bytes"], member["sha256"]))

    def test_source_closure_and_no_forbidden_imports(self):
        source_file = ROOT / "shared/job_runtime/candidates/r6_data_quality_fable_v2_semantic_vertical_v3/vertical.py"
        tree = ast.parse(source_file.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
        self.assertTrue(imports.isdisjoint({"anthropic", "requests", "urllib", "socket", "smtplib"}))
        text = source_file.read_text()
        self.assertNotIn("FROZEN_INPUTS", text)
        self.assertNotIn("r6_data_quality_fable_ab_v1", text)
        self.assertEqual(EFFECTS, {"provider": 0, "network": 0, "email": 0,
            "business": 0, "ixic": 0, "publication": 0})

    def test_python312_and_python39_compatibility_when_available(self):
        source_file = ROOT / "shared/job_runtime/candidates/r6_data_quality_fable_v2_semantic_vertical_v3/vertical.py"
        binaries = {"3.9": Path("/usr/bin/python3"),
                    "3.12": ROOT / ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"}
        for version, path in binaries.items():
            self.assertTrue(path.is_file(), "missing Python " + version)
            observed = subprocess.check_output([str(path), "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"], text=True).strip()
            self.assertEqual(observed, version)
            subprocess.run([str(path), "-m", "py_compile", str(source_file)], check=True,
                           cwd=ROOT, env={**os.environ, "PYTHONPYCACHEPREFIX": str(self.root / ("pycache-" + version))})

if __name__ == "__main__": unittest.main()
