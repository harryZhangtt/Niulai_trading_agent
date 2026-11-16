from __future__ import annotations
import copy
import json
import unittest
from pathlib import Path

from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v1.harness import (
    ALIASES, CELL_MAP, CELL_ORDER, DIMENSIONS, HARD_GATES, LEVELS, ContractError,
    authorize_unblinding, build_blind_packet, derive_block_metrics,
    derive_cell_metrics, evaluate_cell, preflight_readiness, seal_grade,
    sha256_json, validate_grade, validate_metric_artifact,
)

D = "d" * 64


def ref(kind, i=1, t=100):
    return {"kind": kind, "path": "fixture/%s-%s.json" % (kind, i), "sha256": ("%064x" % i), "bytes": i, "immutable_at_ms": t}


def refs():
    return [ref(x, i + 1) for i, x in enumerate((
        "sanitized_output", "evidence_record", "source_inventory", "citation_inventory",
        "deterministic_gate_report", "raw_custody_receipt"))]


def evidence(cell, unknown=False, empty=False, false_new=False):
    provider, addon = CELL_MAP[cell]
    facts = [] if empty else [provider.lower() + "-base"]
    if addon == "ON" and not empty:
        facts.append(provider.lower() + "-new")
    return {
        "version": 1, "cell_id": cell, "retained": True,
        "unknown_fields": ["atomic_claim_count"] if unknown else [],
        "requested_field_count": 6,
        "cited_source_count": 0 if empty else 6,
        "fresh_eligible_source_count": 0 if empty else 5,
        "requested_fields_without_eligible_citation": 6 if empty else 0,
        "metadata_correct_count": 0 if empty else 54,
        "depth_supported_field_count": 0 if empty else 5,
        "atomic_claim_count": "UNKNOWN" if unknown else len(facts),
        "verified_atomic_claim_count": "UNKNOWN" if unknown else len(facts),
        "citation_count": 0 if empty else 6,
        "citation_match_count": 0 if empty else 5,
        "uncited_numeric_claim_count": 0,
        "covered_required_field_count": 0 if empty else 6,
        "correct_fact_ids": facts,
        "false_fact_ids": ([provider.lower() + "-false-new"] if false_new and addon == "ON" else []),
        "resolved_conflict_ids": [],
        "provider_cost_usd": 0.005,
        "metered_tool_cost_usd": 0.001,
        "elapsed_ms": 1000, "provider_time_ms": 700, "tool_time_ms": 200,
        "artifact_refs": refs(),
    }


def packet(cell, t=200):
    return build_blind_packet(cell, refs(), t)


def grade(role, p, reviewer, t=300, levels=None, gates=None):
    dims = {x: "L3_STRONG" for x in DIMENSIONS}
    if levels:
        dims.update(levels)
    h = {x: "PASS" for x in HARD_GATES}
    if gates:
        h.update(gates)
    packet_hashes = [x["sha256"] for x in p["refs"]]
    comments = {x: "fixture evidence reviewed" for x in DIMENSIONS}
    comments["hard_gates"] = "fixture deterministic gates reviewed"
    return seal_grade({
        "version": 1, "grade_id": "%s/%s" % (p["blind_alias"], role),
        "cell_blind_alias": p["blind_alias"], "packet_sha256": p["artifact_sha256"],
        "grader_role": role, "reviewer_kind": "FIXTURE_HUMAN",
        "human_reviewer_id": reviewer, "blind": True, "countable": False,
        "dimensions": dims, "hard_gates": h, "evidence_refs": packet_hashes,
        "comments": comments,
        "independence_attestation": {"no_contact_with_other_graders": True,
            "no_provider_identity_access": True, "no_mapping_access": True,
            "no_conflict_of_interest": True, "attested_at_ms": t - 1},
        "packet_committed_at_ms": p["committed_at_ms"], "produced_at_ms": t,
    })


def gates(fail=None):
    return {x: ("FAIL" if x == fail else "PASS") for x in HARD_GATES}


class EvaluationContractTests(unittest.TestCase):
    def test_preflight_storage_and_intake_schemas_before_calls(self):
        result = preflight_readiness({"version": 1, "activation": False,
            "provider_calls_permitted": False, "root": "runtime/r6-eval",
            "atomic_create": True, "no_replace": True,
            "artifact_kinds": list(("sanitized_output", "evidence_record", "source_inventory",
                "citation_inventory", "deterministic_gate_report", "raw_custody_receipt",
                "blind_packet", "grade", "metric", "unblind"))})
        self.assertEqual(result["status"], "PASS_PROVIDER_FREE_PREFLIGHT")
        self.assertFalse(result["provider_calls_permitted"])

    def test_missing_g1_or_g2(self):
        p = packet(CELL_ORDER[0])
        with self.assertRaisesRegex(ContractError, "G1_G2_REQUIRED"):
            evaluate_cell(p, [grade("G1", p, "fixture-human-g1")], gates(), True)

    def test_nonindependence(self):
        p = packet(CELL_ORDER[0])
        gs = [grade("G1", p, "same"), grade("G2", p, "same", 301)]
        with self.assertRaisesRegex(ContractError, "G1_G2_NONINDEPENDENT"):
            evaluate_cell(p, gs, gates(), True)

    def test_prepacket_grade(self):
        p = packet(CELL_ORDER[0], 300)
        g = grade("G1", p, "g1", 301)
        body = {k: v for k, v in g.items() if k not in ("artifact_sha256", "artifact_bytes")}
        body["produced_at_ms"] = 300
        body["independence_attestation"]["attested_at_ms"] = 300
        bad = seal_grade({k: v for k, v in body.items() if k != "immutable"})
        with self.assertRaisesRegex(ContractError, "GRADE_PREPACKET"):
            validate_grade(bad, p, True)

    def test_dimension_gap_over_one_requires_g3(self):
        p = packet(CELL_ORDER[0])
        gs = [grade("G1", p, "g1", levels={"accuracy": "L0_UNUSABLE"}),
              grade("G2", p, "g2", 301, levels={"accuracy": "L2_ADEQUATE"})]
        with self.assertRaisesRegex(ContractError, "G3_REQUIREMENT"):
            evaluate_cell(p, gs, gates(), True)

    def test_hard_gate_disagreement_requires_g3(self):
        p = packet(CELL_ORDER[0])
        gs = [grade("G1", p, "g1"), grade("G2", p, "g2", 301,
              gates={"reference_parseability": "FAIL"})]
        with self.assertRaisesRegex(ContractError, "G3_REQUIREMENT"):
            evaluate_cell(p, gs, gates(), True)

    def test_invalid_g3_deterministic_override(self):
        p = packet(CELL_ORDER[0])
        gs = [grade("G1", p, "g1", gates={"reference_parseability": "FAIL"}),
              grade("G2", p, "g2", 301), grade("G3", p, "g3", 302)]
        with self.assertRaisesRegex(ContractError, "G3_HARD_GATE_OVERRIDE"):
            evaluate_cell(p, gs, gates("reference_parseability"), True)

    def test_missing_blind_packet_artifact_refs(self):
        with self.assertRaisesRegex(ContractError, "PACKET_REF_MISSING"):
            build_blind_packet(CELL_ORDER[0], refs()[:-1], 200)

    def test_denominator_unknown_na_and_false_new_fact(self):
        off = evidence("R6DQ-7F2C91A4", empty=True)
        on = evidence("R6DQ-C4A7095E", empty=True, false_new=True)
        metric = derive_cell_metrics(on, off)
        self.assertEqual(metric["metrics"]["incremental_information_value"]["status"], "NOT_APPLICABLE")
        self.assertEqual(metric["metrics"]["incremental_information_value"]["signed_false_new_fact_count"], -1)
        unknown = derive_cell_metrics(evidence("R6DQ-7F2C91A4", unknown=True))
        self.assertEqual(unknown["metrics"]["accuracy"]["status"], "UNKNOWN")
        self.assertEqual(unknown["metrics"]["freshness"]["denominator"], 6)

    def test_metric_tamper(self):
        e = evidence(CELL_ORDER[0])
        m = derive_cell_metrics(e)
        bad = copy.deepcopy(m)
        bad["metrics"]["accuracy"]["numerator"] = 0
        with self.assertRaises(ContractError):
            validate_metric_artifact(bad, e)

    def test_unblind_early(self):
        packets, grades_by, dg, ev = {}, {}, {}, {}
        for i, cell in enumerate(CELL_ORDER):
            packets[cell] = packet(cell, 200 + i)
            grades_by[cell] = [grade("G1", packets[cell], "g1-" + cell, 300 + i * 2),
                               grade("G2", packets[cell], "g2-" + cell, 301 + i * 2)]
            dg[cell] = gates(); ev[cell] = evidence(cell)
        bm = derive_block_metrics(ev)
        mapping = {ALIASES[c]: {"cell_id": c, "provider": CELL_MAP[c][0], "addon": CELL_MAP[c][1]} for c in CELL_ORDER}
        nonce = "fixture-nonce"
        with self.assertRaisesRegex(ContractError, "UNBLIND_EARLY"):
            authorize_unblinding(packets, grades_by, dg, bm, ev, mapping, nonce,
                sha256_json({"mapping": mapping, "nonce": nonce}), 302, True)

    def test_valid_four_cell_fixture_not_countable(self):
        packets, grades_by, dg, ev = {}, {}, {}, {}
        for i, cell in enumerate(CELL_ORDER):
            packets[cell] = packet(cell, 200 + i)
            grades_by[cell] = [grade("G1", packets[cell], "g1-" + cell, 300 + i * 2),
                               grade("G2", packets[cell], "g2-" + cell, 301 + i * 2)]
            dg[cell] = gates(); ev[cell] = evidence(cell, false_new=True)
        bm = derive_block_metrics(ev)
        for cell in CELL_ORDER:
            provider, addon = CELL_MAP[cell]
            off = next((ev[c] for c in CELL_ORDER if CELL_MAP[c] == (provider, "OFF")), None)
            validate_metric_artifact(bm["cell_metrics"][cell], ev[cell], off if addon == "ON" else None)
        mapping = {ALIASES[c]: {"cell_id": c, "provider": CELL_MAP[c][0], "addon": CELL_MAP[c][1]} for c in CELL_ORDER}
        nonce = "fixture-nonce"
        opened = authorize_unblinding(packets, grades_by, dg, bm, ev, mapping, nonce,
            sha256_json({"mapping": mapping, "nonce": nonce}), 1000, True)
        self.assertEqual(opened["status"], "FIXTURE_NOT_COUNTABLE")
        self.assertFalse(opened["countable"])
        self.assertEqual(bm["contrasts"]["accuracy"]["interaction"]["status"], "VALUE")

    def test_live_intake_rejects_fixture_humans(self):
        p = packet(CELL_ORDER[0])
        with self.assertRaisesRegex(ContractError, "LIVE_FAKE_HUMAN_FORBIDDEN"):
            validate_grade(grade("G1", p, "fixture-human"), p, False)

    def test_fixture_manifest_declares_non_countability(self):
        path = Path(__file__).resolve().parents[2] / "fixtures/r6_data_quality_2x2_evaluation_v1/cases.json"
        data = json.loads(path.read_text())
        self.assertTrue(all(x["reviewer_kind"] == "FIXTURE_HUMAN" and x["countable"] is False for x in data["fixture_humans"]))


if __name__ == "__main__":
    unittest.main()
