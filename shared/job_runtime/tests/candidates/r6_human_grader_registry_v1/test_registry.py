from __future__ import annotations
import ast
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from shared.job_runtime.candidates.r6_human_grader_registry_v1 import registry as kit

ROOT = Path(__file__).resolve().parents[5]
TEMPLATE_PATHS = [kit.REGISTRY_PATH] + [kit.GRANT_PATHS[r] for r in ("G1", "G2", "G3")]


class Workspace:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        os.chmod(self.root, 0o700)
        for ref in [kit.ROLE_ASSIGNMENT] + list(kit.EVALUATION.values()):
            self.copy(ref["path"], int(ref["mode"], 8))
        for rel in TEMPLATE_PATHS:
            self.copy(rel, 0o600)

    def close(self):
        self.tmp.cleanup()

    def copy(self, rel, mode):
        dst = self.root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, dst)
        os.chmod(dst, mode)

    def read(self, rel):
        return json.loads((self.root / rel).read_text())

    def write(self, rel, value, mode=0o600):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        os.chmod(path, mode)

    def sign_subjects(self, roles=("G1", "G2"), signature="opaque-human-attestation-123"):
        registry = self.read(kit.REGISTRY_PATH)
        registry.update(status="HUMAN_SIGNED_ATTESTATION", attested_at="2030-01-01T00:00:00Z", human_signature_attestation=signature)
        self.write(kit.REGISTRY_PATH, registry)
        raw = (self.root / kit.REGISTRY_PATH).read_bytes()
        registry_sha = hashlib.sha256(raw).hexdigest()
        self.review("REGISTRY", kit.REGISTRY_PATH, "HGRV-A001", signature)
        for index, role in enumerate(roles, 2):
            grant = self.read(kit.GRANT_PATHS[role])
            grant.update(status="HUMAN_SIGNED_ATTESTATION", countable=True, registry_subject_sha256=registry_sha, attested_at="2030-01-01T00:00:00Z", human_signature_attestation=signature + role)
            self.write(kit.GRANT_PATHS[role], grant)
            self.review(role, kit.GRANT_PATHS[role], "HGRV-A00%d" % index, signature + "-review-" + role)

    def review(self, key, subject_path, reviewer, signature):
        raw = (self.root / subject_path).read_bytes()
        value = {
            "version": "r6-human-grader-independent-review-v1",
            "artifact_kind": "INDEPENDENT_HUMAN_ATTESTATION_REVIEW",
            "status": "CLEAN",
            "subject_path": subject_path,
            "subject_sha256": hashlib.sha256(raw).hexdigest(),
            "subject_bytes": len(raw),
            "reviewer_opaque_id": reviewer,
            "independent_human_reviewer": True,
            "independent_of_all_graders": True,
            "conflict_disclosure": "NO_KNOWN_CONFLICT",
            "review_created_by_human": True,
            "reviewed_at": "2030-01-02T00:00:00Z",
            "human_signature_attestation": signature,
        }
        self.write(kit.REVIEW_PATHS[key], value)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.ws = Workspace()
        self.addCleanup(self.ws.close)

    def test_templates_are_pending_nonauthorizing_and_have_no_review_placeholders(self):
        for rel in TEMPLATE_PATHS:
            value = json.loads((ROOT / rel).read_text())
            self.assertEqual(value["status"], "PENDING_HUMAN_SIGNATURE")
            self.assertFalse(value["activation"])
            if value["artifact_kind"] == "HUMAN_GRADER_ROLE_GRANT":
                self.assertFalse(value["countable"])
            self.assertNotIn("human_signature_attestation", value)
            self.assertEqual((ROOT / rel).stat().st_mode & 0o777, 0o600)
        for rel in kit.REVIEW_PATHS.values():
            self.assertFalse((ROOT / rel).exists())
        with self.assertRaisesRegex(kit.ContractError, "PENDING_HUMAN_SIGNATURE"):
            kit.validate_registry_attestations(self.ws.root)

    def test_complete_fixture_human_declarations_remain_noncountable_and_inert(self):
        self.ws.sign_subjects()
        report = kit.validate_registry_attestations(self.ws.root)
        self.assertEqual(report["validated_roles"], ["G1", "G2"])
        self.assertFalse(report["activation"])
        self.assertFalse(report["countable"])
        self.assertFalse(report["provider_calls_permitted"])
        self.assertEqual(set(report["effects"].values()), {0})
        fixture = json.loads((ROOT / "shared/job_runtime/tests/fixtures/r6_human_grader_registry_v1/fixture-human-noncountable.json").read_text())
        self.assertTrue(fixture["fixture_human"])
        self.assertFalse(fixture["countable"])

    def test_coherent_fixture_relabel_is_rejected(self):
        self.ws.sign_subjects(signature="fixture-human-self-mint-123")
        with self.assertRaisesRegex(kit.ContractError, "HUMAN_SIGNATURE"):
            kit.validate_registry_attestations(self.ws.root)

    def test_duplicate_human_or_role_and_g1_equals_g2_are_rejected(self):
        self.ws.sign_subjects()
        registry = self.ws.read(kit.REGISTRY_PATH)
        registry["roles"][1]["human_reviewer_id"] = registry["roles"][0]["human_reviewer_id"]
        self.ws.write(kit.REGISTRY_PATH, registry)
        with self.assertRaisesRegex(kit.ContractError, "ROLE_BINDING|DUPLICATE"):
            kit.validate_registry_attestations(self.ws.root)
        workspace = Workspace()
        self.addCleanup(workspace.close)
        workspace.sign_subjects()
        grant = workspace.read(kit.GRANT_PATHS["G2"])
        grant["human_reviewer_id"] = kit.ROLE_IDS["G1"]
        workspace.write(kit.GRANT_PATHS["G2"], grant)
        with self.assertRaisesRegex(kit.ContractError, "ROLE_OR_ID"):
            kit.validate_registry_attestations(workspace.root)

    def test_missing_signature_and_conflict_blind_independence_fields_fail_closed(self):
        for field, value, code in (
            ("human_signature_attestation", None, "FIELDS"),
            ("human_signature_attestation", "human name and email@example.invalid", "HUMAN_SIGNATURE"),
            ("conflict_disclosure", "DISCLOSED_CONFLICT", "CONFLICT"),
            ("no_blind_map_access", False, "BLIND_ACKNOWLEDGEMENT"),
            ("independence", {"human_is_independent": False, "independent_from_other_graders": True, "no_joint_grading": True}, "INDEPENDENCE"),
        ):
            with self.subTest(field=field):
                workspace = Workspace()
                self.addCleanup(workspace.close)
                workspace.sign_subjects()
                grant = workspace.read(kit.GRANT_PATHS["G1"])
                if value is None:
                    del grant[field]
                else:
                    grant[field] = value
                workspace.write(kit.GRANT_PATHS["G1"], grant)
                with self.assertRaisesRegex(kit.ContractError, code):
                    kit.validate_registry_attestations(workspace.root)

    def test_g3_is_required_only_when_triggered(self):
        self.ws.sign_subjects()
        self.assertEqual(kit.validate_registry_attestations(self.ws.root, False)["validated_roles"], ["G1", "G2"])
        with self.assertRaisesRegex(kit.ContractError, "G3_PENDING_HUMAN_SIGNATURE"):
            kit.validate_registry_attestations(self.ws.root, True)
        self.ws.sign_subjects(("G1", "G2", "G3"))
        self.assertEqual(kit.validate_registry_attestations(self.ws.root, True)["validated_roles"], ["G1", "G2", "G3"])

    def test_fixed_path_hash_bytes_mode_and_nofollow(self):
        self.ws.sign_subjects()
        assignment = self.ws.root / kit.ROLE_ASSIGNMENT["path"]
        assignment.write_bytes(assignment.read_bytes() + b"\n")
        with self.assertRaisesRegex(kit.ContractError, "HASH|BYTES"):
            kit.validate_registry_attestations(self.ws.root)
        mode_workspace = Workspace(); self.addCleanup(mode_workspace.close); mode_workspace.sign_subjects()
        os.chmod(mode_workspace.root / kit.REGISTRY_PATH, 0o644)
        with self.assertRaisesRegex(kit.ContractError, "MODE"):
            kit.validate_registry_attestations(mode_workspace.root)
        link_workspace = Workspace(); self.addCleanup(link_workspace.close); link_workspace.sign_subjects()
        subject = link_workspace.root / kit.REGISTRY_PATH
        target = link_workspace.root / "neutral.json"
        subject.rename(target); subject.symlink_to(target)
        with self.assertRaisesRegex(kit.ContractError, "NOFOLLOW"):
            kit.validate_registry_attestations(link_workspace.root)

    def test_fixed_review_path_and_binding_are_required(self):
        self.ws.sign_subjects()
        review = self.ws.root / kit.REVIEW_PATHS["REGISTRY"]
        review.unlink()
        with self.assertRaisesRegex(kit.ContractError, "REGISTRY_REVIEW_MISSING"):
            kit.validate_registry_attestations(self.ws.root)
        self.ws.sign_subjects()
        value = self.ws.read(kit.REVIEW_PATHS["G1"])
        value["subject_sha256"] = "0" * 64
        self.ws.write(kit.REVIEW_PATHS["G1"], value)
        with self.assertRaisesRegex(kit.ContractError, "SUBJECT_BINDING"):
            kit.validate_registry_attestations(self.ws.root)

    def test_package_has_no_provider_or_minting_surface(self):
        package = ROOT / "shared/job_runtime/candidates/r6_human_grader_registry_v1"
        imports = []
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Import): imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom): imports.append(node.module or "")
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotIn(node.func.id, ("open", "exec", "eval"))
        self.assertFalse(any(name.startswith(("anthropic", "openai", "requests", "httpx")) for name in imports))
        self.assertFalse(any("r6_human_grader_registry_v1" in p.read_text() for p in (ROOT / "shared/job_runtime").glob("*.py")))

    def test_four_draft_2020_12_recursively_closed_schemas(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema Draft202012Validator unavailable")
        schemas = list((ROOT / "shared/job_runtime/candidates/r6_human_grader_registry_v1/schemas").glob("*.json"))
        self.assertEqual(len(schemas), 4)
        def walk(value):
            if isinstance(value, dict):
                if value.get("type") == "object":
                    self.assertIs(value.get("additionalProperties"), False)
                for child in value.values(): walk(child)
            elif isinstance(value, list):
                for child in value: walk(child)
        for path in schemas:
            schema = json.loads(path.read_text())
            Draft202012Validator.check_schema(schema)
            walk(schema)
        registry_schema = json.loads((ROOT / "shared/job_runtime/candidates/r6_human_grader_registry_v1/schemas/registry-subject-v1.schema.json").read_text())
        Draft202012Validator(registry_schema).validate(json.loads((ROOT / kit.REGISTRY_PATH).read_text()))


if __name__ == "__main__":
    unittest.main()
