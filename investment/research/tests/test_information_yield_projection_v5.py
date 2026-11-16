import copy
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from investment.research import information_yield_projection_v5 as projection
from investment.research.information_yield_projection_v5 import ProjectionV5Error, project_result_custody_v1
from shared.research_sources.artifacts import ROOT
from shared.research_sources.information_yield_v5_contracts import ArtifactRefV5, canonical_v5, digest_v5
from tuning.evals.information_fetch.information_yield._v5_support import build_v5_batch
from tuning.evals.information_fetch.information_yield.evaluator_v5 import evaluate_fresh_eiy_evaluation_v5
from tuning.evals.information_fetch.information_yield.publisher_v1 import publish_eiy_result_v1
from tuning.evals.information_fetch.information_yield.policy_v5 import canonical_policy_ref_v5


class InformationYieldProjectionV5Tests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "tuning/runtime/test-tmp"
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent, prefix="eiy-v5-projection-")
        self.addCleanup(self.temp.cleanup)
        self.publication = Path(self.temp.name) / "information-yield-v5"
        self.root_patch = patch.object(projection, "PUBLICATION_ROOT", self.publication)
        self.root_patch.start(); self.addCleanup(self.root_patch.stop)
        _fixtures, fresh, _manifest, _custody = build_v5_batch(self)
        issued = evaluate_fresh_eiy_evaluation_v5(fresh_evaluation=fresh)
        self.receipt = publish_eiy_result_v1(issued, publication_root=self.publication)
        self.evaluation_id = "eval-v3"
        self.index_path = self._path(self.receipt["index_ref"])
        self.index = self._json(self.index_path)
        self.custody_path = self._path(self.receipt["custody_ref"])
        self.custody = self._json(self.custody_path)
        self.context_path = self._path(self.custody["context_ref"])
        self.result_path = self._path(self.custody["result_ref"])
        self.context = self._json(self.context_path)
        self.result = self._json(self.result_path)

    def _path(self, ref):
        return ArtifactRefV5.from_mapping(ref).resolve(ROOT)

    def _json(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        raw = canonical_v5(value) + b"\n"
        path.write_bytes(raw)
        return ArtifactRefV5(path.relative_to(ROOT).as_posix(), sha256(raw).hexdigest()).to_mapping()

    def _resign_context(self, context):
        core = {key: value for key, value in context.items()
                if key not in {"context_sha256", "fact_set_sha256", "fact_bindings"}}
        context_sha = digest_v5(core)
        for binding in context["fact_bindings"]:
            binding["context_sha256"] = context_sha
        context["context_sha256"] = context_sha
        context["fact_set_sha256"] = digest_v5(context["fact_bindings"])

    def _publish_corruption(self, *, context_mutator=None, result_mutator=None,
                            custody_mutator=None, index_mutator=None):
        context = copy.deepcopy(self.context); result = copy.deepcopy(self.result)
        custody = copy.deepcopy(self.custody); index = copy.deepcopy(self.index)
        if context_mutator:
            context_mutator(context)
        self._resign_context(context)
        result.update({"context_sha256": context["context_sha256"],
                       "fact_set_sha256": context["fact_set_sha256"],
                       "policy_sha256": context["policy_sha256"],
                       "gate_authority_sha256": context["gate_authority_sha256"],
                       "source_closure_sha256": context["source_closure_sha256"]})
        if result_mutator:
            result_mutator(result)
        result["result_sha256"] = digest_v5({key: value for key, value in result.items()
                                             if key != "result_sha256"})
        object_dir = self.publication / "objects" / result["result_sha256"]
        context_ref = self._write(object_dir / "context.json", context)
        result_ref = self._write(object_dir / "result.json", result)
        custody.update({"context_ref": context_ref, "result_ref": result_ref,
                        "context_sha256": context["context_sha256"],
                        "fact_set_sha256": context["fact_set_sha256"],
                        "result_sha256": result["result_sha256"],
                        "policy_sha256": result["policy_sha256"],
                        "gate_authority_sha256": result["gate_authority_sha256"],
                        "source_closure_sha256": result["source_closure_sha256"],
                        "claim_limits": list(result["claim_limits"])})
        if custody_mutator:
            custody_mutator(custody)
        custody["custody_sha256"] = digest_v5({key: value for key, value in custody.items()
                                               if key != "custody_sha256"})
        custody_ref = self._write(object_dir / "custody.json", custody)
        index.update({"custody_ref": custody_ref, "result_sha256": result["result_sha256"],
                      "context_sha256": context["context_sha256"],
                      "policy_sha256": result["policy_sha256"]})
        if index_mutator:
            index_mutator(index)
        self._write(self.publication / "index" / f"{self.evaluation_id}.json", index)
        return context, result, custody, index

    def _restore(self):
        self._publish_corruption()

    def test_actual_lane_a_nominal_summary_and_planned_set_order(self):
        value = project_result_custody_v1(self.evaluation_id)
        self.assertEqual((value["wire_version"], value["publication"], value["verdict"]),
                         ("information-yield-wire-5", "information-yield-v5", "pass"))
        self.assertEqual(value["counts"], {"planned": 7, "confirmation": 6, "development": 1})
        self.assertEqual(len(value["policy_gates"]), 18)
        planned_ids = [row["case_id"] for row in self.context["planned_cases"]]
        self.assertNotEqual(planned_ids, self.context["populations"]["E"])
        self.assertEqual(set(planned_ids), set(self.context["populations"]["E"]))
        self.assertEqual([row["case_id"] for row in self.context["fact_bindings"]], planned_ids)
        public = json.dumps(value)
        for forbidden in ('"path"', "registry_ref", "result_ref", "canonical_policy_ref", "raw_result"):
            self.assertNotIn(forbidden, public)

    def test_actual_lane_a_detail_and_identity_only_api(self):
        value = project_result_custody_v1(self.evaluation_id, case_id="case-2", arm="F")
        self.assertEqual(value["selection"], {"case_id": "case-2", "arm": "F"})
        self.assertEqual(value["case"]["case_id"], "case-2")
        self.assertEqual(value["selected_arm"], value["case"]["arms"]["F"])
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_NOT_FOUND"):
            project_result_custody_v1(self.evaluation_id, case_id="missing")
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_IDENTITY_CONFLICT"):
            project_result_custody_v1(self.evaluation_id, arm="F")
        parser = projection.SafeParser(add_help=False); parser.add_argument("--evaluation-id")
        with self.assertRaises(ProjectionV5Error):
            parser.parse_args(["--result-ref", "synthetic"])

    def test_relative_ref_aliases_and_wrong_fixed_root_fail_closed(self):
        index = copy.deepcopy(self.index)
        for alias in (str(self.custody_path), "tuning/runtime/./alias.json", "tuning/runtime/.hidden/custody.json"):
            with self.subTest(alias=alias):
                index["custody_ref"] = {"path": alias, "sha256": self.receipt["custody_ref"]["sha256"]}
                self._write(self.publication / "index" / f"{self.evaluation_id}.json", index)
                with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_INDEX_INVALID"):
                    project_result_custody_v1(self.evaluation_id)
        self._restore()
        alternate = self.publication / "alias-custody.json"
        alternate.write_bytes(self.custody_path.read_bytes())
        alias_ref = ArtifactRefV5(alternate.relative_to(ROOT).as_posix(), sha256(alternate.read_bytes()).hexdigest()).to_mapping()
        index = copy.deepcopy(self.index); index["custody_ref"] = alias_ref
        self._write(self.publication / "index" / f"{self.evaluation_id}.json", index)
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_CUSTODY_INVALID"):
            project_result_custody_v1(self.evaluation_id)

    def test_descriptor_walk_rejects_symlink_nonregular_and_oversized_files(self):
        target = self.publication / "symlink-target.json"
        target.write_bytes(self.context_path.read_bytes())
        self.context_path.unlink(); self.context_path.symlink_to(target)
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_CONTEXT_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)
        self.context_path.unlink(); self._restore()
        shutil.rmtree(self.context_path, ignore_errors=True) if self.context_path.is_dir() else self.context_path.unlink()
        self.context_path.mkdir()
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_CONTEXT_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)
        shutil.rmtree(self.context_path); self._restore()
        self.context_path.write_bytes(b"x" * (projection.MAX_ARTIFACT_BYTES + 1))
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_CONTEXT_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)

    def test_policy_context_and_result_corruption_have_fixed_codes(self):
        alternate = self.publication / "alternate-policy.json"; alternate.write_text("{}\n", encoding="utf-8")
        alternate_ref = ArtifactRefV5(alternate.relative_to(ROOT).as_posix(), sha256(alternate.read_bytes()).hexdigest()).to_mapping()
        self._publish_corruption(custody_mutator=lambda value: value.update(canonical_policy_ref=alternate_ref))
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_POLICY_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)
        self._restore(); self.context_path.write_bytes(self.context_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_CONTEXT_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)
        self._restore(); result_path = self._path(self._json(self.custody_path)["result_ref"])
        result_path.write_bytes(result_path.read_bytes() + b" ")
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_RESULT_DRIFT"):
            project_result_custody_v1(self.evaluation_id)

    def test_gate_population_and_precedence_corruptions_fail_closed(self):
        mutations = {
            "gate-order": (lambda value: value["policy_gates"].reverse(), "EIY_PROJECTION_V5_RESULT_DRIFT"),
            "gate-population": (lambda value: value["policy_gates"][0].update(population="E"), "EIY_PROJECTION_V5_RESULT_DRIFT"),
            "gate-case-ids": (lambda value: value["policy_gates"][0].update(population_case_ids=["case-2"]), "EIY_PROJECTION_V5_AUTHORITY_MISMATCH"),
            "population": (lambda value: value["populations"]["D"].clear(), "EIY_PROJECTION_V5_AUTHORITY_MISMATCH"),
            "precedence": (lambda value: value.update(verdict="reject"), "EIY_PROJECTION_V5_AUTHORITY_MISMATCH"),
        }
        for label, (mutation, code) in mutations.items():
            with self.subTest(label=label):
                self._publish_corruption(result_mutator=mutation)
                with self.assertRaisesRegex(ProjectionV5Error, code):
                    project_result_custody_v1(self.evaluation_id)

    def test_fact_bindings_must_follow_planned_order(self):
        def reorder(context):
            context["fact_bindings"][0], context["fact_bindings"][1] = context["fact_bindings"][1], context["fact_bindings"][0]
        self._publish_corruption(context_mutator=reorder)
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_AUTHORITY_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)

    def test_private_nested_value_and_output_bound_fail_closed(self):
        self._publish_corruption(result_mutator=lambda value: value["policy_gates"][0].update(observed={"private_note": "synthetic"}))
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_RESULT_DRIFT"):
            project_result_custody_v1(self.evaluation_id)
        self._restore()
        with patch.object(projection, "MAX_OUTPUT_BYTES", 64):
            with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_OUTPUT_LIMIT"):
                project_result_custody_v1(self.evaluation_id)

    def test_missing_and_now_index_fail_closed(self):
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_NOT_FOUND"):
            project_result_custody_v1("missing")
        index = copy.deepcopy(self.index); index["publication_kind"] = "now_diagnostic"
        self._write(self.publication / "index" / f"{self.evaluation_id}.json", index)
        with self.assertRaisesRegex(ProjectionV5Error, "EIY_PROJECTION_V5_AUTHORITY_MISMATCH"):
            project_result_custody_v1(self.evaluation_id)


if __name__ == "__main__":
    unittest.main()
