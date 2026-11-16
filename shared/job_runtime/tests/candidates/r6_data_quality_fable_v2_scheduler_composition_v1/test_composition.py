from __future__ import annotations
import ast
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from shared.job_runtime.engine import validate_job
from shared.job_runtime.candidates.r6_data_quality_fable_v2_scheduler_composition_v1.composition import (
    CELLS, EFFECTS_V1, JOB_IDS, PROMPT_BYTES, PROMPT_SHA256, RUNTIME_ROOTS,
    SOURCE_SHA256, TEST_RUNTIME, CompositionError, execute, packet_sha256,
    runtime_manifest, verify_evidence_packet, verify_packet)
from shared.job_runtime.candidates.r6_data_quality_fable_v2_semantic_vertical_v3.vertical import (
    ConfigOwnerV3, DesignOwnerV3, IntegrationOwnerV3, MaterializationOwnerV3,
    ProposalOwnerV3, VerticalV3Error)

ROOT = Path(__file__).resolve().parents[5]
SOURCE = ROOT / "shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_scheduler_composition_v1/prompt-source-v1.json"
AT = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)

class SchedulerCompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".job-runtime")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.root.chmod(0o700)
        self.counter = 0

    def run_gate(self, *, dispositions=None, crash=False):
        self.counter += 1
        workspace = self.root / f"workspace-{self.counter}"; workspace.mkdir(mode=0o700)
        return execute(repo_root=ROOT, source_path=SOURCE, workspace=workspace,
            output_root=self.root / f"bundle-{self.counter}", scheduled=AT,
            dispositions=dispositions, second_cell_crash=crash)

    def assert_descriptor_continuity(self, result):
        packet = result["packet"]
        for index, cell in enumerate(CELLS):
            job_descriptor = packet["cas_jobs"][index]["prompt_artifact"]
            custody_descriptor = packet["cas_custody"][index]["descriptor"]
            row = packet["provider_rows"][index]
            row_descriptor = {"version": row["version"], "ref": row["artifact_ref"],
                "sha256": row["sha256"], "length": row["length"],
                "source_identity_sha256": row["source_identity_sha256"],
                "generation": row["generation"], "proof_origin": row["proof_origin"]}
            self.assertEqual(job_descriptor, custody_descriptor)
            self.assertEqual(job_descriptor, row_descriptor)
            self.assertEqual(job_descriptor, packet["authority"]["prompt_descriptors"][cell])
            self.assertEqual(row["prompt_binding_sha256"],
                packet["authority"]["cell_bindings"][cell])
        verify_packet(packet, ROOT)

    def test_nominal_real_load_cas_resource_engine_and_owners(self):
        result = self.run_gate()
        self.assertEqual([job["id"] for job in result["loaded_jobs"]], list(JOB_IDS))
        self.assertTrue(all(job["enabled"] is False for job in result["loaded_jobs"]))
        self.assertTrue(all(job["_prompt_capture"].sha256 == PROMPT_SHA256
                            and job["_prompt_capture"].length == 526 for job in result["loaded_jobs"]))
        for job in result["enriched_jobs"]:
            validate_job(job)
            self.assertEqual(job["_provider"], "claude_host")
            self.assertEqual(job["_retry_policy"].max_attempts, 1)
            self.assertEqual(job["_replay_contract"].effect.value, "none")
            self.assertRegex(job["_resource_key"], r"^[0-9a-f]{64}$")
        self.assertEqual([cell["disposition"] for cell in result["bundle"]["cells"]], ["PASS", "PASS"])
        self.assertEqual(len(result["transitions"]), 5)
        self.assert_descriptor_continuity(result)
        self.assertTrue(all(value == 0 for value in result["effects"].values()))

    def test_genuine_malformed_crosses_persisted_parser_boundary(self):
        result = self.run_gate(dispositions={"control": "PASS", "treatment": "MALFORMED"})
        treatment = result["bundle"]["cells"][1]
        self.assertEqual(treatment["disposition"], "MALFORMED")
        raw = result["artifacts"][treatment["terminal_artifact_ref"]].raw
        self.assertEqual(raw, b'{"terminal":')
        row = json.loads(result["bridge"]["rows"][1]["canonical_json"])
        self.assertEqual(row["receipt"]["parser_disposition"], "MALFORMED")
        self.assertIsNone(row["receipt"]["parsed_terminal"])
        self.assert_descriptor_continuity(result)

    def test_unknown_and_missing_are_truthful_and_fenced(self):
        result = self.run_gate(dispositions={"control": "UNKNOWN", "treatment": "MISSING"})
        self.assertEqual([cell["disposition"] for cell in result["bundle"]["cells"]], ["UNKNOWN", "MISSING"])
        self.assertTrue(all(cell["unknown_fenced"] for cell in result["bundle"]["cells"]))
        rows = [json.loads(row["canonical_json"]) for row in result["bridge"]["rows"]]
        self.assertEqual([row["status"] for row in rows], ["unknown", "unknown"])
        self.assertEqual([row["failure_kind"] for row in rows], ["unknown", "missing_terminal"])
        self.assert_descriptor_continuity(result)

    def test_native_operations_schema9_and_snapshot_cleanup(self):
        result = self.run_gate()
        packet = result["packet"]
        self.assertEqual(packet["schema9_fingerprint"], packet["database"]["schema_fingerprint"])
        self.assertEqual(packet["cleanup"], {"sidecars": [], "snapshots": []})
        for row in packet["provider_rows"]:
            self.assertIn(row["prompt_binding_sha256"], row["operation_id"])
            self.assertEqual(row["prompt_binding_sha256"], json.loads(row["canonical_json"])["receipt"]["binding_sha256"])
        encoded = json.dumps(packet)
        self.assertNotIn("st_ino", encoded); self.assertNotIn("st_dev", encoded); self.assertNotIn("st_mtime", encoded)

    def test_second_cell_crash_recovers_without_replacing_bytes(self):
        result = self.run_gate(crash=True)
        receipt = result["packet"]["second_cell_crash"]
        self.assertEqual(receipt["fault"], "SIGKILL_AFTER_SECOND_CELL_RAW_FSYNC")
        self.assertEqual(receipt["signal"], 9)
        self.assertEqual(receipt["synchronization"], "external_fifo_reader_handshake")
        self.assertTrue(receipt["actual_process_interruption"])
        self.assertTrue(receipt["existing_files_unchanged"] and receipt["recovered"])
        self.assertIn("treatment/treatment.raw", receipt["preexisting_sha256"])
        self.assertNotIn("treatment/treatment.bundle.json", receipt["preexisting_sha256"])
        self.assertEqual([cell["disposition"] for cell in result["bundle"]["cells"]], ["PASS", "PASS"])
        bad = copy.deepcopy(result["packet"]); bad["second_cell_crash"]["signal"] = 15
        bad["packet_sha256"] = packet_sha256(bad)
        with self.assertRaisesRegex(CompositionError, "PACKET_CRASH_RECEIPT"):
            verify_packet(bad, ROOT)
        bad = copy.deepcopy(result["packet"])
        bad["second_cell_crash"]["preexisting_sha256"]["treatment/treatment.raw"] = "0" * 64
        bad["packet_sha256"] = packet_sha256(bad)
        with self.assertRaisesRegex(CompositionError, "PACKET_CRASH_RECEIPT"):
            verify_packet(bad, ROOT)

    def test_complete_authority_and_transition_mutations_fail(self):
        result = self.run_gate()
        authority = result["authority"]
        owners = (IntegrationOwnerV3, DesignOwnerV3, MaterializationOwnerV3,
                  ProposalOwnerV3, ConfigOwnerV3)
        for owner, transition in zip(owners, result["transitions"]):
            owner.validate(transition["output"], transition["input"], authority)
            for map_name in ("cell_bindings", "provider_results"):
                bad = dict(transition["output"]); changed = dict(bad[map_name]); changed["treatment"] = "a" * 64; bad[map_name] = changed
                with self.assertRaises(VerticalV3Error): owner.validate(bad, transition["input"], authority)
            bad = dict(transition["output"]); descriptors = {cell: dict(value) for cell, value in bad["prompt_descriptors"].items()}; descriptors["control"]["generation"] = "wrong"; bad["prompt_descriptors"] = descriptors
            with self.assertRaises(VerticalV3Error): owner.validate(bad, transition["input"], authority)
        builders = ((DesignOwnerV3.build, result["transitions"][0]),
            (lambda envelope, auth: MaterializationOwnerV3.build(envelope, auth, AT), result["transitions"][1]),
            (ProposalOwnerV3.build, result["transitions"][2]), (ConfigOwnerV3.build, result["transitions"][3]))
        for builder, envelope in builders:
            bad = dict(envelope); receipt = dict(envelope["receipt"]); receipt["output_digest"] = "b" * 64; bad["receipt"] = receipt
            with self.assertRaises(VerticalV3Error): builder(bad, authority)


    def test_packet_verifier_rejects_all_descriptor_cas_mismatches(self):
        for dispositions in (None, {"control": "PASS", "treatment": "MALFORMED"},
                             {"control": "UNKNOWN", "treatment": "MISSING"}):
            result = self.run_gate(dispositions=dispositions)
            self.assert_descriptor_continuity(result)
            mutations = []
            for section in ("cas_jobs", "cas_custody", "provider_rows", "authority"):
                bad = copy.deepcopy(result["packet"])
                if section == "cas_jobs":
                    bad[section][0]["prompt_artifact"]["source_identity_sha256"] = "1" * 64
                elif section == "cas_custody":
                    bad[section][0]["descriptor"]["source_identity_sha256"] = "2" * 64
                elif section == "provider_rows":
                    bad[section][0]["source_identity_sha256"] = "3" * 64
                else:
                    bad[section]["prompt_descriptors"]["control"]["source_identity_sha256"] = "4" * 64
                bad["packet_sha256"] = packet_sha256(bad)
                mutations.append(bad)
            for bad in mutations:
                with self.assertRaisesRegex(CompositionError, "PACKET_DESCRIPTOR_CONTINUITY"):
                    verify_packet(bad, ROOT)

    def test_packet_digest_manifest_runtime_and_retained_fixture(self):
        result = self.run_gate()
        packet = result["packet"]
        self.assertEqual(packet["packet_sha256"], packet_sha256(packet))
        manifest = runtime_manifest(ROOT)
        self.assertEqual(packet["runtime_manifest"], manifest)
        self.assertEqual(tuple(manifest["roots"]), RUNTIME_ROOTS)
        paths = {member["path"] for member in manifest["members"]}
        self.assertTrue(set(RUNTIME_ROOTS).issubset(paths))
        script = """import json,sys
from pathlib import Path
import shared.job_runtime.candidates.r6_data_quality_fable_v2_scheduler_composition_v1.composition
root=Path.cwd().resolve(); found=[]
for module in sys.modules.values():
    value=getattr(module,'__file__',None)
    if value:
        path=Path(value).resolve()
        try: rel=path.relative_to(root).as_posix()
        except ValueError: continue
        if rel.startswith('shared/') and rel.endswith('.py'): found.append(rel)
print(json.dumps(sorted(set(found))))
"""
        loaded = set(json.loads(subprocess.check_output(["/usr/bin/python3", "-c", script],
            text=True, cwd=ROOT)))
        self.assertTrue(loaded.issubset(paths), sorted(loaded - paths))
        for required in ("shared/job_runtime/__init__.py", "shared/exact_source.py",
                         "shared/job_runtime/providers/__init__.py",
                         "shared/job_runtime/candidates/r6_data_quality_fable_v2_semantic_vertical_v3/__init__.py"):
            self.assertIn(required, paths)
        self.assertEqual(packet["test_runtime"], TEST_RUNTIME)
        retained = ROOT / "shared/job_runtime/tests/fixtures/r6_data_quality_fable_v2_scheduler_composition_v1/evidence-packet-v1.json"
        raw = retained.read_bytes(); value = json.loads(raw)
        verify_evidence_packet(value, ROOT)
        for mutate in (lambda p: p.__setitem__("extra", None),
                       lambda p: p.pop("malformed_injection"),
                       lambda p: p["test_results"]["python3.9.6_scheduler"].__setitem__("passed", 999)):
            bad = copy.deepcopy(value); mutate(bad); bad["packet_sha256"] = packet_sha256(bad)
            with self.assertRaises(CompositionError):
                verify_evidence_packet(bad, ROOT)
        for case_name, relabeled in (("nominal_second_cell_crash", {"control": "FAIL", "treatment": "PASS"}),
                                     ("malformed_injection", {"control": "PASS", "treatment": "PASS"}),
                                     ("unknown_missing_injection", {"control": "PASS", "treatment": "MISSING"})):
            bad = copy.deepcopy(value); bad[case_name]["dispositions"] = relabeled
            bad[case_name]["packet_sha256"] = packet_sha256(bad[case_name])
            bad["packet_sha256"] = packet_sha256(bad)
            with self.assertRaises(CompositionError):
                verify_evidence_packet(bad, ROOT)
        arch = ROOT / "tuning/architecture/r6_data_quality_fable_v2_scheduler_composition_v1"
        for name in ("protocol-v1.json", "decision-v1.json", "producer-verification-v1.json",
                     "portability-v1.json", "packet-verifier-v1.json", "source-closure-v1.json"):
            self.assertEqual(json.loads((arch / name).read_text())["packet_sha256"], value["packet_sha256"])
        protocol = json.loads((arch / "protocol-v1.json").read_text())
        self.assertEqual(protocol["packet_file_sha256"], hashlib.sha256(raw).hexdigest())
        closure = json.loads((arch / "source-closure-v1.json").read_text())
        for member in closure["members"]:
            data = (ROOT / member["path"]).read_bytes()
            self.assertEqual((len(data), hashlib.sha256(data).hexdigest()),
                             (member["bytes"], member["sha256"]))

    def test_packet_verifier_rejects_embedded_digest_mutations(self):
        result = self.run_gate()
        mutations = []
        for mutate in (
            lambda p: p.__setitem__("extra", None),
            lambda p: p.pop("config"),
            lambda p: p["cas_jobs"].append(copy.deepcopy(p["cas_jobs"][0])),
            lambda p: p["cas_custody"].pop(),
            lambda p: p["provider_rows"].append(copy.deepcopy(p["provider_rows"][0])),
            lambda p: p["bundle"]["cells"].pop(),
            lambda p: p["raw_artifacts"].__setitem__("extra", copy.deepcopy(next(iter(p["raw_artifacts"].values())))),
            lambda p: p["transitions"].pop(),
            lambda p: p["transitions"].reverse(),
            lambda p: p["stage_outputs"].append(copy.deepcopy(p["stage_outputs"][0])),
            lambda p: p["config"].__setitem__("sha256", "9" * 64),
            lambda p: p["allocation"].__setitem__("loaded_job_ids", ["wrong"]),
            lambda p: p["allocation"]["document"].__setitem__("extra", None),
            lambda p: p["allocation"]["document"]["jobs"][0].__setitem__("extra", None),
            lambda p: p["allocation"]["document"]["jobs"][0].pop("prompt_file"),
            lambda p: p["cas_jobs"][0].__setitem__("extra", None),
            lambda p: p["cas_jobs"][0].pop("circuit_scope"),
            lambda p: p["provider_rows"][0].__setitem__("extra", None),
            lambda p: p["provider_rows"][0].pop("terminal_proof"),
            lambda p: p["dispositions"].__setitem__("treatment", "FAIL"),
            lambda p: p["cas_custody"][0].__setitem__("verified", False),
            lambda p: p["cas_custody"][0].__setitem__("lease_closed", False),
            lambda p: p["cas_custody"][0].__setitem__("opened_bytes", 525),
            lambda p: p["cas_jobs"][0].__setitem__("enabled", True),
            lambda p: p.__setitem__("test_enabled_job_ids", [JOB_IDS[0]]),
            lambda p: p["old166"].__setitem__("member_count", 165),
            lambda p: p["semantic_review"].__setitem__("file_sha256", "4" * 64),
            lambda p: p["semantic_review"].__setitem__("verdict", "PENDING"),
            lambda p: p["semantic_review"]["reviewed"].__setitem__("source_sha256", "5" * 64),
            lambda p: p["raw_artifacts"][next(iter(p["raw_artifacts"]))].__setitem__("sha256", "0" * 64),
            lambda p: p["bundle"]["cells"][0].__setitem__("bundle_sha256", "1" * 64),
            lambda p: p["provider_rows"][0].__setitem__("canonical_sha256", "2" * 64),
            lambda p: p["transitions"][0]["receipt"].__setitem__("output_digest", "3" * 64),
        ):
            bad = copy.deepcopy(result["packet"]); mutate(bad); bad["packet_sha256"] = packet_sha256(bad)
            mutations.append(bad)
        for bad in mutations:
            with self.assertRaises((CompositionError, VerticalV3Error)):
                verify_packet(bad, ROOT)

    def test_source_prompt_and_cas_faults_fail_closed(self):
        raw = SOURCE.read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (2065, SOURCE_SHA256))
        self.assertEqual((len(json.loads(raw)["prompt_utf8"].encode()),
                          hashlib.sha256(json.loads(raw)["prompt_utf8"].encode()).hexdigest()),
                         (PROMPT_BYTES, PROMPT_SHA256))
        bad_source = self.root / "bad-source.json"; bad_source.write_bytes(raw + b" ")
        workspace = self.root / "bad-workspace"; workspace.mkdir(mode=0o700)
        with self.assertRaisesRegex(CompositionError, "SOURCE_FIXTURE"):
            execute(repo_root=ROOT, source_path=bad_source, workspace=workspace,
                output_root=self.root / "bad-bundle", scheduled=AT)

    def test_python_versions_static_zero_effect_and_no_live_imports(self):
        source_file = ROOT / "shared/job_runtime/candidates/r6_data_quality_fable_v2_scheduler_composition_v1/composition.py"
        tree = ast.parse(source_file.read_text()); imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imports.add(node.module.split(".")[0])
        self.assertTrue(imports.isdisjoint({"anthropic", "requests", "urllib", "socket", "smtplib", "subprocess"}))
        self.assertEqual(EFFECTS_V1, {"provider":0,"network":0,"email":0,"business":0,"ixic":0,"publication":0})
        binaries = {"3.9": Path("/usr/bin/python3"),
            "3.12": ROOT / ".job-runtime/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"}
        for version, binary in binaries.items():
            observed = subprocess.check_output([str(binary), "-c", "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')"], text=True).strip()
            self.assertEqual(observed, version)
            subprocess.run([str(binary), "-m", "py_compile", str(source_file)], check=True,
                cwd=ROOT, env={**os.environ, "PYTHONPYCACHEPREFIX": str(self.root / ("pycache-" + version))})

if __name__ == "__main__": unittest.main()
