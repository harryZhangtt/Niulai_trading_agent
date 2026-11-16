from __future__ import annotations

import base64
import json
import unittest
from unittest.mock import patch

from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2 import (
    ClaudeFixturePort, CodexFixturePort, DestinationSnapshot, FourCellFixtureOrchestrator,
    UnresolvedSuccessorBinding, verify_target_signatures,
)
from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2.contracts import (
    CELL_PLANS, P0_ARGUMENT_NAMES, P0_OPTIONAL_ARGUMENT_NAMES,
    RUNNER_ARGUMENT_NAMES, RUNNER_OPTIONAL_ARGUMENT_NAMES,
)
from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2.target_handoffs import (
    P0_SOURCE, RUNNER_SOURCE, SourcePin, TargetSignatureDrift, _read_pin,
    build_p0_handoff, build_runner_handoff,
)
from shared.job_runtime.candidates.r6_common_four_cell_orchestrator_v2.authority import verify_authority
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1 import pipeline
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 import runner

class TargetHandoffTests(unittest.TestCase):
    def setUp(self):
        self.grant = verify_authority()["grant"]

    def result(self):
        return FourCellFixtureOrchestrator(ClaudeFixturePort(), CodexFixturePort()).run(DestinationSnapshot.empty())

    def test_source_pinned_current_signatures(self):
        value = verify_target_signatures()
        self.assertEqual(value["p0"]["required"], list(P0_ARGUMENT_NAMES))
        self.assertEqual(value["p0"]["optional"], list(P0_OPTIONAL_ARGUMENT_NAMES))
        self.assertEqual(value["runner"]["required"], list(RUNNER_ARGUMENT_NAMES))
        self.assertEqual(value["runner"]["optional"], list(RUNNER_OPTIONAL_ARGUMENT_NAMES))
        self.assertEqual(P0_SOURCE.sha256, "9a129560ce2bcc8f90daa5b5280d0b67c75ebd21072a123493fa6d5a6cca018e")
        self.assertEqual(RUNNER_SOURCE.sha256, "bc45fceff79a1106ef66c09376075f3bb72a235ac4a23ca69b7344f914ff0bff")

    def test_p0_manifest_uses_actual_signature_and_values(self):
        for handoff in self.result()["p0_handoffs"]:
            self.assertEqual(handoff["required_argument_names"], list(P0_ARGUMENT_NAMES))
            args = handoff["argument_values"]
            self.assertTrue({"adapter", "bundle_root", "readback", "raw", "provider_publication_artifact", "research_material"} <= set(args))
            self.assertFalse({"raw_sha256", "publication_artifact_sha256", "research_material_sha256"} & set(args))
            self.assertEqual(args["adapter"]["status"], "UNRESOLVED_BUILD_TIME_BINDING")
            self.assertEqual(args["bundle_root"]["status"], "UNRESOLVED_BUILD_TIME_BINDING")
            self.assertTrue(base64.b64decode(args["raw"]["data"]))
            self.assertIsInstance(json.loads(args["provider_publication_artifact"]["data"]), dict)
            self.assertEqual(set(json.loads(args["research_material"]["data"])), {"sanitized_output", "factual_evidence", "source_inventory", "citation_inventory"})

    def test_typed_p0_values_and_invocation_fail_closed(self):
        plan = dict(zip(("cell_id", "order_index", "provider_port", "blind_addon_label", "checks_enabled", "destination_id"), CELL_PLANS[0]))
        admission = ClaudeFixturePort().admit(dict(plan))
        handoff = build_p0_handoff(plan, admission, self.grant["successor_pins"]["p0_attempt_envelope"])
        for name, kind in (("raw", bytes), ("readback", dict), ("provider_publication_artifact", dict), ("research_material", dict)):
            self.assertIsInstance(handoff.required_arguments[name], kind)
        with self.assertRaisesRegex(UnresolvedSuccessorBinding, "P0_FINAL_SUCCESSOR_PIN_UNRESOLVED"):
            handoff.invoke()

    def test_runner_manifest_has_every_required_value_and_fails_closed(self):
        result = self.result(); handoff = result["evaluation_handoff"]
        self.assertEqual(handoff["required_argument_names"], list(RUNNER_ARGUMENT_NAMES))
        self.assertEqual(set(handoff["argument_values"]), set(RUNNER_ARGUMENT_NAMES))
        self.assertTrue(all(v["status"] == "UNRESOLVED_BUILD_TIME_BINDING" for v in handoff["argument_values"].values()))
        typed = build_runner_handoff(result["p0_handoffs"], self.grant["successor_pins"]["evaluation_runner"])
        with self.assertRaisesRegex(UnresolvedSuccessorBinding, "RUNNER_FINAL_SUCCESSOR_PIN_UNRESOLVED"):
            typed.invoke()

    def test_p0_missing_extra_and_renamed_required_args_report_drift(self):
        base = "adapter,bundle_root,*,cell_id,blind_addon_label,checks_enabled,job_id,slot_id,attempt_id,operation_id,prompt_binding_sha256,readback,raw,provider_publication_artifact,research_material,terminal_state,source_cutoff_sha256,dq_checks=None,claimed_readback_digest=None,retention_fault=None"
        variants = [base.replace(",source_cutoff_sha256", ""), base.replace(",source_cutoff_sha256", ",source_cutoff_sha256,extra_required"), base.replace("source_cutoff_sha256", "renamed_source_cutoff")]
        for signature in variants:
            scope = {}; exec("def fake(" + signature + "):\n return None", scope)
            with self.subTest(signature=signature), patch.object(pipeline, "execute", scope["fake"]):
                with self.assertRaisesRegex(TargetSignatureDrift, "P0_SIGNATURE_DRIFT"):
                    verify_target_signatures()

    def test_runner_missing_extra_and_renamed_required_args_report_drift(self):
        variants = ["authority_registry_ref,owner_root,map_commitment_ref,*,_fixture_boundaries=None,_receipt_fault=None", "authority_registry_ref,owner_root,map_commitment_ref,bundle_root,extra_required,*,_fixture_boundaries=None,_receipt_fault=None", "authority_registry_ref,owner_root,map_commitment_ref,renamed_bundle_root,*,_fixture_boundaries=None,_receipt_fault=None"]
        for signature in variants:
            scope = {}; exec("def fake(" + signature + "):\n return None", scope)
            with self.subTest(signature=signature), patch.object(runner, "execute_block", scope["fake"]):
                with self.assertRaisesRegex(TargetSignatureDrift, "RUNNER_SIGNATURE_DRIFT"):
                    verify_target_signatures()

    def test_target_source_pin_drift_fails_before_adaptation(self):
        with self.assertRaisesRegex(TargetSignatureDrift, "TARGET_SOURCE_DRIFT"):
            _read_pin(SourcePin(P0_SOURCE.relative_path, P0_SOURCE.size, "0" * 64))

if __name__ == "__main__":
    unittest.main()
