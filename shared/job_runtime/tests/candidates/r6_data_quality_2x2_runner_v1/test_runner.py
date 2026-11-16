from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import (
    CELL_ORDER, CHECK_NAMES, FROZEN_INPUTS, KNOWN_BINDINGS, TOOL_POLICY, WEB_POLICY, ContractError,
)
from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.runner import (
    GRADING, P0_V9, _commit_execution_receipt, _evaluation_from_committed_bundle,
    _write_ref, default_run, execute_block, finalize_block,
)
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.adapters import claude_adapter, codex_adapter
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.artifacts import descriptor
from shared.job_runtime.candidates.r6_data_quality_attempt_envelope_v1.contracts import PROVIDER_BINDINGS, sha256_bytes, sha256_json
from shared.job_runtime.tests.candidates.r6_data_quality_2x2_evaluation_v3.test_evaluation_v3 import Root, grade
from shared.job_runtime.candidates.r6_data_quality_2x2_evaluation_v3 import harness as grading

try:
    from jsonschema import Draft202012Validator
except ImportError:
    Draft202012Validator = None

ROOT = Path(__file__).resolve().parents[5]
P0_FIX = ROOT / "shared/job_runtime/tests/fixtures/r6_data_quality_attempt_envelope_v1"
MATERIALS = {
    "ARM-A": json.loads((P0_FIX / "claude-research-material.json").read_text()),
    "ARM-B": json.loads((P0_FIX / "codex-research-material.json").read_text()),
}
ARTIFACTS = {
    "ARM-A": json.loads((P0_FIX / "claude-sanitized-publication.json").read_text()),
    "ARM-B": json.loads((P0_FIX / "codex-sanitized-publication.json").read_text()),
}
D = "d" * 64
RAW = b'{"raw":"runner-v6-synthetic"}'


def ref(name, status="CLEAN"):
    return {"artifact_id": name, "sha256": D, "bytes": 1, "status": status}


def grant():
    return {
        "version": 1, "scope": "PROVIDER_FREE_FIXTURE", "block_id": "fixture-block", "activation": False,
        "bindings": dict(KNOWN_BINDINGS), "engine": ref("engine"), "authority": ref("authority"),
        "authority_review": ref("authority-review"),
        "provider_final_grants": {"ARM-A": ref("a-grant"), "ARM-B": ref("b-grant")},
        "provider_final_reviews": {"ARM-A": ref("a-review"), "ARM-B": ref("b-review")},
        "catalog_evidence": {"ARM-A": ref("a-catalog"), "ARM-B": ref("b-catalog")},
        "catalog_reviews": {"ARM-A": ref("a-catalog-review"), "ARM-B": ref("b-catalog-review")},
        "limits": {"attempts_per_cell": 1, "retries": 0, "replays": 0, "status_queries": 0, "per_cell_budget_usd": "0.01", "combined_budget_usd": "0.04"},
        "frozen_inputs": dict(FROZEN_INPUTS), "sealed_window_id": "window",
        "block_window": {"start_ms": 100, "deadline_ms": 1800100},
        "tool_policy": copy.deepcopy(TOOL_POLICY), "web_policy": copy.deepcopy(WEB_POLICY),
        "exact_readback_required": True,
    }


def p0_readback(cell_id):
    return {
        "version": 1, "job_id": "job-" + cell_id, "slot_id": "slot-" + cell_id,
        "attempt_id": "attempt-" + cell_id, "operation_id": "operation/" + cell_id,
        "prompt_binding_sha256": D, "transaction": "BEGIN_IMMEDIATE_POST_WRITE_READBACK",
        "counts": {"job": 1, "slot": 1, "attempt": 1},
    }


def research_material(provider, cell_id, terminal, readback, artifact):
    value = copy.deepcopy(MATERIALS[provider])
    binding = {
        "cell_id": cell_id, "job_id": readback["job_id"], "slot_id": readback["slot_id"],
        "attempt_id": readback["attempt_id"], "operation_id": readback["operation_id"],
        "prompt_binding_sha256": D, "canonical_engine_readback_digest": sha256_json(readback),
        "source_cutoff_sha256": FROZEN_INPUTS["source_cutoff_sha256"],
        "blind_provider_label": provider,
        "provider_schema": PROVIDER_BINDINGS[provider]["provider_schema"],
        "publication_driver_identity_sha256": PROVIDER_BINDINGS[provider]["publication_driver_identity_sha256"],
    }
    for body in value.values():
        body["binding"] = copy.deepcopy(binding)
        body["provider_terminal"] = terminal
        body["raw_sha256"] = sha256_bytes(RAW)
        body["publication_artifact_sha256"] = sha256_json(artifact)
    for source in value["source_inventory"]["sources"]:
        source["source_cutoff_sha256"] = FROZEN_INPUTS["source_cutoff_sha256"]
    if terminal != "PASS":
        value["sanitized_output"]["answer"] = "Attempt retained terminal " + terminal + "."
        value["sanitized_output"]["complete"] = False
    return value


def fixture_adapter(label, base, mode=None):
    owner = base / ("owner-a" if label == "ARM-A" else "owner-b")
    public = base / ("public-a" if label == "ARM-A" else "public-b")
    tamper = mode == "tamper_owner"
    if label == "ARM-A":
        return claude_adapter(owner, public, owner_tamper_on_publish=tamper)
    return codex_adapter(owner, public, owner_tamper_on_publish=tamper)


class Boundary:
    def __init__(self, label, test, base, mode=None):
        self.label = label
        self.test = test
        self.mode = mode
        self.adapter = fixture_adapter(label, base, mode)

    def __call__(self, plan):
        self.test.calls.append(plan["cell_id"])
        cell_id, index = plan["cell_id"], plan["order_index"]
        if self.mode == "policy" and index == 0:
            plan["tool_policy"]["roster"][0]["version"] = "MUTATED"
        terminal = self.mode if self.mode in ("STOP", "UNKNOWN") and index == 0 else "PASS"
        readback = p0_readback(cell_id)
        artifact = copy.deepcopy(ARTIFACTS[self.label])
        material = research_material(self.label, cell_id, terminal, readback, artifact)
        if self.mode == "missing_refs" and index == 0:
            material.pop("factual_evidence")
        if self.mode == "tampered_evidence" and index == 0:
            material["citation_inventory"]["citations"][0]["source_id"] = "missing-source"
        output = {
            "model_readback": plan["model"],
            "engine_sha256": "e" * 64 if self.mode == "engine" and index == 0 else D,
            "readback": {key: readback[key] for key in ("job_id", "slot_id", "attempt_id", "operation_id", "prompt_binding_sha256")},
            "p0_readback": readback, "raw": RAW, "provider_publication_artifact": artifact,
            "research_material": material, "terminal_state": terminal,
            "dq_checks": [{"name": name, "status": "PASS", "code": "CHECK_PASS"} for name in CHECK_NAMES] if plan["checks_enabled"] else None,
            "cell_window": {"start_ms": 100 + index * 100, "end_ms": 150 + index * 100},
            "tool_readback": copy.deepcopy(plan["tool_policy"]), "web_readback": copy.deepcopy(plan["web_policy"]),
        }
        if self.mode == "grading" and index == 0:
            output["grading_inputs"] = {}
        return output


class V6(unittest.TestCase):
    def setUp(self):
        self.root = Root()
        self.addCleanup(self.root.close)
        self.auth = self.root.authority()
        self.mapping = {
            "BLIND-01": {"cell_id": CELL_ORDER[0], "provider": "CLAUDE", "addon": "OFF"},
            "BLIND-02": {"cell_id": CELL_ORDER[1], "provider": "CODEX", "addon": "ON"},
            "BLIND-03": {"cell_id": CELL_ORDER[2], "provider": "CLAUDE", "addon": "ON"},
            "BLIND-04": {"cell_id": CELL_ORDER[3], "provider": "CODEX", "addon": "OFF"},
        }
        self.nonce = "fixture-nonce"
        self.mapref = self.root.mapref(self.mapping, self.nonce)
        self.bundle = tempfile.TemporaryDirectory()
        self.addCleanup(self.bundle.cleanup)
        self.calls = []
        self.registry = self.authority()

    def authority(self, fake=False):
        grant_ref = self.root.write("block_grant_v6", grant(), path="auth/block.json")
        review_ref = self.root.write("block_review_v6", {"version": 6, "status": "CLEAN", "subject_sha256": grant_ref["canonical_content_sha256"]}, path="auth/blockreview.json")
        provider_grants, provider_reviews, catalogs, catalog_reviews = [], [], [], []
        for index, cell_id in enumerate(CELL_ORDER):
            item = self.root.write("provider_grant_v6", {"version": 6, "cell_id": cell_id, "status": "FAKE" if fake and index == 0 else "FIXTURE_AUTHORIZED"}, path="auth/p%d.json" % index)
            provider_grants.append(item)
            provider_reviews.append(self.root.write("provider_review_v6", {"version": 6, "status": "CLEAN", "subject_sha256": item["canonical_content_sha256"]}, path="auth/pr%d.json" % index))
            catalog = self.root.write("catalog_v6", {"version": 6, "cell_id": cell_id, "status": "FIXTURE_CATALOG"}, path="auth/c%d.json" % index)
            catalogs.append(catalog)
            catalog_reviews.append(self.root.write("catalog_review_v6", {"version": 6, "status": "CLEAN", "subject_sha256": catalog["canonical_content_sha256"]}, path="auth/cr%d.json" % index))
        body = {
            "version": 6, "fixture": True, "block_grant_ref": grant_ref, "block_review_ref": review_ref,
            "provider_grant_refs": provider_grants, "provider_review_refs": provider_reviews,
            "catalog_refs": catalogs, "catalog_review_refs": catalog_reviews,
            "grading_registry_ref": self.auth.registry_ref, "grading_registry_review_ref": self.auth.registry_review_ref,
            "grading_grant_pairs": {key: [value["grant_ref"], value["review_ref"]] for key, value in self.auth.grants.items()},
        }
        return self.root.write("authority_registry_v6", body, path="auth/registry.json")

    def execute(self, mode=None, registry=None, receipt_fault=None):
        base = Path(self.bundle.name)
        boundaries = {
            "ARM-A": Boundary("ARM-A", self, base, mode),
            "ARM-B": Boundary("ARM-B", self, base, mode),
        }
        return execute_block(registry or self.registry, self.root.path, self.mapref, base / "bundles", _fixture_boundaries=boundaries, _receipt_fault=receipt_fault)

    def grade_refs(self, execution_ref):
        execution = json.loads((self.root.path / execution_ref["path"]).read_text())
        result = {}
        for cell_id in CELL_ORDER:
            packet = execution["packets"][cell_id]
            grades = [grade("G1", packet, self.auth, packet["committed_at_ms"] + 10), grade("G2", packet, self.auth, packet["committed_at_ms"] + 11)]
            result[cell_id] = [self.root.write("human_grade_v3", item) for item in grades]
        return result

    def opening(self, timestamp=1000):
        return self.root.write("blind_opening_v6", {"version": 6, "mapping": self.mapping, "nonce": self.nonce, "opened_at_ms": timestamp}, path="open/result.json")

    def execution(self, execution_ref):
        return json.loads((self.root.path / execution_ref["path"]).read_text())

    def synthetic_execution_receipt(self):
        store = grading.ArtifactStore(self.root.path)
        cells, packets = [], {}
        for index, cell_id in enumerate(CELL_ORDER):
            provider = "ARM-A" if index in (0, 2) else "ARM-B"
            readback = p0_readback(cell_id)
            artifact = copy.deepcopy(ARTIFACTS[provider])
            material = research_material(provider, cell_id, "PASS", readback, artifact)
            evidence = {}
            for name, item in material.items():
                raw = json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
                evidence[name] = {"body": item, "canonical_sha256": hashlib.sha256(raw).hexdigest(), "ref": descriptor("provider/%s/%s.json" % (cell_id, name), raw)}
            raw_ref = descriptor("provider/%s/provider-terminal.raw" % cell_id, RAW)
            bundle = {
                "research_evidence": evidence,
                "envelope": {"retained": True, "readback_match": True},
                "denominator_record": {"included": True, "replay_allowed": False},
                "normalized_attempt": {"terminal_state": "PASS", "source_cutoff_sha256": FROZEN_INPUTS["source_cutoff_sha256"], "no_replay": True},
                "raw_custody_receipt": {"raw_sha256": sha256_bytes(RAW), "raw_ref": raw_ref},
            }
            values, provenance = _evaluation_from_committed_bundle("BLIND-%02d" % (index + 1), bundle)
            refs = []
            end_ms = 150 + index * 100
            for ref_index, kind in enumerate(grading.REF_KINDS, 1):
                refs.append(_write_ref(self.root.path, kind, "cell%02d/ref%02d.json" % (index + 1, ref_index), values[kind], end_ms))
            packet = grading.build_blind_packet(store, "BLIND-%02d" % (index + 1), refs, self.mapref, end_ms + 1, 100)
            packets[cell_id] = packet
            cells.append({
                "cell_id": cell_id, "order_index": index, "blind_alias": "BLIND-%02d" % (index + 1),
                "terminal_state": "PASS", "denominator_included": True, "replay_allowed": False,
                "bundle_digest": sha256_json({"cell_id": cell_id, "synthetic": True}),
                "bundle_receipt": {"path": cell_id + ".attempt-bundle.json", "sha256": sha256_json({"receipt": cell_id}), "bytes": 1, "primitive": "LINK_NO_REPLACE_SINGLE_FILE", "file_fsync": True, "parent_dir_fsync": True, "no_overwrite": True, "recovered_fault": None},
                "p0_evidence": provenance, "grading_refs": refs, "engine_exact": True,
                "errors": [], "packet_sha256": packet["artifact_sha256"],
            })
        body = {
            "version": 6, "block_id": "fixture-block", "status": "PENDING_HUMAN_GRADING", "countable": False,
            "authority_registry_ref": dict(self.registry), "p0_v9_contract": copy.deepcopy(P0_V9),
            "grading_bindings": copy.deepcopy(GRADING), "map_commitment_ref": dict(self.mapref),
            "owner_root_id": store.root_id(), "cell_order": list(CELL_ORDER), "denominator_cell_count": 4,
            "attempted_variant_count": 4, "partial_comparison": False, "cells": cells,
            "packets": packets, "fixture": True, "immutable": True,
        }
        committed_at = max(packet["committed_at_ms"] for packet in packets.values()) + 1
        return _commit_execution_receipt(self.root.path, body, committed_at), body

    def test_exact_p0_v7_derivation_then_human_finalize_fixture(self):
        execution_ref = self.execute()
        self.assertEqual(self.calls, list(CELL_ORDER))
        execution = self.execution(execution_ref)
        self.assertEqual(execution["status"], "PENDING_HUMAN_GRADING")
        self.assertEqual(execution["p0_v9_contract"]["sha256"], "51f36fb46eb7a74994abf0a23152ce5d1f3fd7f4e8687aa900d1328e3b9aae1e")
        self.assertEqual(execution["p0_v9_contract"]["review_sha256"], "0a150a6221ba082ae38eae6951bff43fc904996a99623e425d36059e431ec2e6")
        self.assertEqual(execution["p0_v9_contract"]["review_status"], "OPEN")
        first = execution["cells"][0]
        intake = json.loads((self.root.path / first["grading_refs"][0]["path"]).read_text())
        evidence = json.loads((self.root.path / first["grading_refs"][1]["path"]).read_text())
        sources = json.loads((self.root.path / first["grading_refs"][2]["path"]).read_text())
        self.assertEqual(intake["text"], MATERIALS["ARM-A"]["sanitized_output"]["answer"])
        self.assertEqual(sources["sources"][0]["url"], MATERIALS["ARM-A"]["source_inventory"]["sources"][0]["url"])
        states = [item["state"] for key in ("freshness_items", "richness_items", "depth_items", "accuracy_claims", "citation_items", "source_coverage_items") for item in evidence[key]]
        self.assertTrue(states and set(states) == {"UNKNOWN"})
        self.assertTrue(all(evidence[key]["state"] == "MISSING" for key in ("provider_cost_usd", "metered_tool_cost_usd", "elapsed_ms", "provider_time_ms", "tool_time_ms")))
        result = finalize_block(execution_ref, self.root.path, self.grade_refs(execution_ref), self.opening())
        self.assertFalse(result["countable"])
        self.assertEqual(result["status"], "FIXTURE_NOT_COUNTABLE")

    def test_all_destination_collisions_precede_boundary(self):
        owner_relatives = ["receipt/block-v6.json", "receipt/.stage-block-v6.json"] + [
            "cell%02d/ref%02d.json" % (cell_index, ref_index)
            for cell_index in range(1, 5) for ref_index in range(1, 7)
        ]
        bundle_relatives = [
            cell_id + "/" + name
            for cell_id in CELL_ORDER
            for name in (cell_id + ".attempt-bundle.json", ".stage-" + cell_id + ".attempt-bundle.json")
        ]
        for target_kind, relative in ([('owner', item) for item in owner_relatives] + [('bundle', item) for item in bundle_relatives]):
            with self.subTest(target_kind=target_kind, relative=relative):
                base = self.root.path if target_kind == "owner" else Path(self.bundle.name) / "bundles"
                if target_kind == "bundle":
                    base.mkdir(mode=0o700, exist_ok=True)
                    os.chmod(base, 0o700)
                target = base / relative
                target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                os.chmod(target.parent, 0o700)
                target.write_text("{}")
                os.chmod(target, 0o600)
                try:
                    with self.assertRaisesRegex(ContractError, "TARGET_COLLISION"):
                        self.execute()
                    self.assertEqual(self.calls, [])
                finally:
                    self.root.close(); self.setUp()

    def test_public_execute_restart_reconciles_final_stage_and_post_link_without_boundary(self):
        for state in ("final_only", "stage_only", "post_link"):
            with self.subTest(state=state):
                original, _body = self.synthetic_execution_receipt()
                final = self.root.path / "receipt/block-v6.json"
                stage = self.root.path / "receipt/.stage-block-v6.json"
                if state == "stage_only":
                    os.rename(final, stage)
                elif state == "post_link":
                    os.link(final, stage)
                self.calls = []
                recovered = self.execute()
                self.assertEqual(self.calls, [])
                self.assertEqual(recovered["path"], "receipt/block-v6.json")
                self.assertEqual(recovered["sha256"], original["sha256"])
                self.assertTrue(final.exists())
                self.assertFalse(stage.exists())
                self.assertEqual(final.stat().st_nlink, 1)
                self.root.close(); self.setUp()

    def test_finalize_rejects_self_consistent_forged_receipt_ref_and_accepts_canonical(self):
        canonical_ref, body = self.synthetic_execution_receipt()
        forged = copy.deepcopy(body)
        forged["block_id"] = "coherent-forgery"
        forged_ref = _write_ref(self.root.path, "execution_receipt_v6", "receipt/coherent-forged-v6.json", forged, canonical_ref["immutable_at_ms"])
        grades = self.grade_refs(canonical_ref)
        opening = self.opening()
        with self.assertRaisesRegex(ContractError, "EXECUTION_REF_SOURCE_PIN"):
            finalize_block(forged_ref, self.root.path, grades, opening)
        result = finalize_block(canonical_ref, self.root.path, grades, opening)
        self.assertFalse(result["countable"])
        self.assertEqual(result["status"], "FIXTURE_NOT_COUNTABLE")

    def test_finalize_rejects_canonical_receipt_symlink_even_with_exact_bytes(self):
        canonical_ref, _body = self.synthetic_execution_receipt()
        final = self.root.path / canonical_ref["path"]
        raw = final.read_bytes()
        target = self.root.path / "receipt/symlink-target.json"
        target.write_bytes(raw)
        os.chmod(target, 0o600)
        final.unlink()
        final.symlink_to(target)
        with self.assertRaisesRegex(ContractError, "REF_OPEN_NOFOLLOW"):
            finalize_block(canonical_ref, self.root.path, {}, self.opening())

    def test_finalize_rejects_every_authenticated_receipt_pin_mutation(self):
        mutations = [
            ("block_id", lambda body: body.__setitem__("block_id", "other-block")),
            ("p0", lambda body: body["p0_v9_contract"].__setitem__("sha256", "0" * 64)),
            ("grading", lambda body: body["grading_bindings"]["producer"].__setitem__("sha256", "0" * 64)),
            ("owner_root", lambda body: body.__setitem__("owner_root_id", "0" * 64)),
            ("immutable", lambda body: body.__setitem__("immutable", False)),
            ("authority", lambda body: body["authority_registry_ref"].__setitem__("path", "auth/missing.json")),
            ("map", lambda body: body["map_commitment_ref"].__setitem__("path", "map/missing.json")),
            ("cell_order", lambda body: body["cell_order"].reverse()),
            ("denominator", lambda body: body.__setitem__("denominator_cell_count", 3)),
            ("provenance_uid", lambda body: body["cells"][0]["p0_evidence"]["research_evidence"]["sanitized_output"]["owner_ref"].__setitem__("owner_uid", os.getuid() + 1)),
            ("cell_packet", lambda body: body["cells"][0].__setitem__("packet_sha256", "0" * 64)),
            ("packet_seal", lambda body: body["packets"][CELL_ORDER[0]].__setitem__("artifact_sha256", "0" * 64)),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                original, body = self.synthetic_execution_receipt()
                final = self.root.path / original["path"]
                final.unlink()
                mutate(body)
                forged = _commit_execution_receipt(self.root.path, body, original["immutable_at_ms"])
                with self.assertRaises(ContractError):
                    finalize_block(forged, self.root.path, {}, self.opening())
                self.root.close(); self.setUp()

    @unittest.skipUnless(Draft202012Validator is not None, "jsonschema unavailable")
    def test_block_grant_schema_rejects_every_safety_contradiction(self):
        package = ROOT / "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1"
        schema = json.loads((package / "block-grant-v1.schema.json").read_text())
        validator = Draft202012Validator(schema)
        variants = []
        mutations = [
            lambda item: item.__setitem__("version", 2),
            lambda item: item.__setitem__("scope", "EXTERNAL_FOUR_CELL_LIVE"),
            lambda item: item.__setitem__("activation", True),
            lambda item: item["bindings"].__setitem__("p0_producer", "0" * 64),
            lambda item: item["limits"].__setitem__("retries", 1),
            lambda item: item["limits"].__setitem__("replays", 1),
            lambda item: item["limits"].__setitem__("status_queries", 1),
            lambda item: item["limits"].__setitem__("combined_budget_usd", "1.00"),
            lambda item: item["frozen_inputs"].__setitem__("effort", "high"),
            lambda item: item["block_window"].__setitem__("deadline_ms", 1800101),
            lambda item: item["tool_policy"]["roster"][0].__setitem__("call_ceiling", 3),
            lambda item: item["web_policy"].__setitem__("call_ceiling", 3),
            lambda item: item.__setitem__("exact_readback_required", False),
        ]
        for mutate in mutations:
            item = grant(); mutate(item); variants.append(item)
        for item in variants:
            self.assertFalse(validator.is_valid(item), item)
            with self.assertRaises(ContractError):
                from shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1.contracts import validate_block_grant
                validate_block_grant(item, fixture=True)

    def test_bundle_symlink_rejected_without_target_mode_mutation(self):
        bundle_root = Path(self.bundle.name) / "bundles"
        bundle_root.mkdir(mode=0o700)
        target = Path(self.bundle.name) / "unrelated-target"
        target.mkdir(mode=0o755)
        os.chmod(target, 0o755)
        (bundle_root / CELL_ORDER[-1]).symlink_to(target, target_is_directory=True)
        before = stat.S_IMODE(os.lstat(target).st_mode)
        with self.assertRaisesRegex(ContractError, "OWNER_DIRECTORY_UNSAFE"):
            self.execute()
        after = stat.S_IMODE(os.lstat(target).st_mode)
        self.assertEqual((before, after), (0o755, 0o755))
        self.assertFalse(any((bundle_root / cell_id).exists() for cell_id in CELL_ORDER[:-1]))
        self.assertEqual(self.calls, [])

    def test_tampered_missing_and_owner_ref_evidence_reject(self):
        for mode in ("tampered_evidence", "missing_refs", "tamper_owner"):
            with self.subTest(mode=mode):
                with self.assertRaises(Exception):
                    self.execute(mode)
                self.assertEqual(self.calls, [CELL_ORDER[0]])
                self.root.close(); self.setUp()

    def test_stop_and_unknown_retained_without_replay_or_finalization(self):
        for terminal in ("STOP", "UNKNOWN"):
            with self.subTest(terminal=terminal):
                execution_ref = self.execute(terminal)
                execution = self.execution(execution_ref)
                self.assertEqual(self.calls, list(CELL_ORDER))
                self.assertEqual(execution["status"], "INCONCLUSIVE_NOT_FINALIZABLE")
                self.assertEqual(execution["cells"][0]["terminal_state"], terminal)
                self.assertTrue(execution["cells"][0]["denominator_included"])
                self.assertFalse(execution["cells"][0]["replay_allowed"])
                self.assertEqual(execution["denominator_cell_count"], 4)
                with self.assertRaisesRegex(ContractError, "EXECUTION_RECEIPT_INVALID"):
                    finalize_block(execution_ref, self.root.path, {}, self.opening())
                self.root.close(); self.setUp()

    def test_exact_committed_evidence_transform_never_synthesizes_grades(self):
        cell_id = CELL_ORDER[0]
        readback = p0_readback(cell_id)
        artifact = copy.deepcopy(ARTIFACTS["ARM-A"])
        material = research_material("ARM-A", cell_id, "PASS", readback, artifact)
        evidence = {}
        for name, body in material.items():
            raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
            evidence[name] = {"body": body, "canonical_sha256": hashlib.sha256(raw).hexdigest(), "ref": descriptor("evidence/" + name + ".json", raw)}
        raw_ref = descriptor("raw/provider-terminal.raw", RAW)
        bundle = {
            "research_evidence": evidence,
            "envelope": {"retained": True, "readback_match": True},
            "denominator_record": {"included": True, "replay_allowed": False},
            "normalized_attempt": {"terminal_state": "PASS", "source_cutoff_sha256": FROZEN_INPUTS["source_cutoff_sha256"], "no_replay": True},
            "raw_custody_receipt": {"raw_sha256": sha256_bytes(RAW), "raw_ref": raw_ref},
        }
        values, provenance = _evaluation_from_committed_bundle("BLIND-01", bundle)
        self.assertEqual(values["sanitized_output"]["text"], material["sanitized_output"]["answer"])
        self.assertEqual(values["source_inventory"]["sources"][0]["url"], material["source_inventory"]["sources"][0]["url"])
        self.assertEqual(values["citation_inventory"]["citations"][0]["id"], material["citation_inventory"]["citations"][0]["citation_id"])
        states = [item["state"] for key in ("freshness_items", "richness_items", "depth_items", "accuracy_claims", "citation_items", "source_coverage_items") for item in values["evidence_record"][key]]
        states.extend(item["state"] for item in values["evidence_record"]["incremental_facts"])
        self.assertEqual(set(states), {"UNKNOWN"})
        self.assertTrue(all(values["evidence_record"][key] == {"state": "MISSING", "value": None} for key in ("provider_cost_usd", "metered_tool_cost_usd", "elapsed_ms", "provider_time_ms", "tool_time_ms")))
        self.assertEqual(provenance["research_evidence"]["sanitized_output"]["owner_ref"], evidence["sanitized_output"]["ref"])
        self.assertNotIn("grades", values)
        self.assertNotIn("metrics", values)

    def test_atomic_receipt_primitive_recovers_without_p0_dependency(self):
        for index, fault in enumerate(("short_write", "crash_after_stage_fsync", "crash_post_link"), 1):
            with self.subTest(fault=fault):
                target = Path(self.bundle.name) / ("receipt-only-%d" % index)
                target.mkdir(mode=0o700)
                value = {"fixture": True, "fault": fault, "immutable": True}
                receipt = _commit_execution_receipt(target, value, 100 + index, fault)
                path = target / receipt["path"]
                raw = path.read_bytes()
                self.assertEqual(json.loads(raw), value)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt["sha256"])
                self.assertEqual(path.stat().st_nlink, 1)
                self.assertFalse((target / "receipt/.stage-block-v6.json").exists())

    def test_real_process_receipt_crash_recovery(self):
        value = {"fixture": True, "immutable": True, "receipt": "v6"}
        source = Path(self.bundle.name) / "receipt-input.json"
        source.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
        worker = Path(__file__).with_name("_receipt_crash_worker.py")
        for fault in ("crash_after_stage_fsync", "crash_post_link"):
            with self.subTest(fault=fault):
                target = Path(self.bundle.name) / ("real-" + fault)
                target.mkdir(mode=0o700)
                env = dict(os.environ)
                env["PYTHONDONTWRITEBYTECODE"] = "1"
                proc = subprocess.run([sys.executable, str(worker), str(source), str(target), fault], cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
                self.assertLess(proc.returncode, 0, (fault, proc.returncode, proc.stderr.decode("utf-8", errors="replace")))
                stage = target / "receipt/.stage-block-v6.json"
                final = target / "receipt/block-v6.json"
                self.assertTrue(stage.exists())
                if fault == "crash_after_stage_fsync":
                    self.assertFalse(final.exists())
                else:
                    self.assertTrue(final.exists())
                    self.assertEqual((stage.stat().st_dev, stage.stat().st_ino), (final.stat().st_dev, final.stat().st_ino))
                    self.assertEqual(final.stat().st_nlink, 2)
                receipt = _commit_execution_receipt(target, value, 200)
                self.assertTrue(final.exists())
                self.assertFalse(stage.exists())
                self.assertEqual(final.stat().st_nlink, 1)
                self.assertEqual(hashlib.sha256(final.read_bytes()).hexdigest(), receipt["sha256"])

    def test_receipt_short_write_and_crash_windows_recover_without_boundary_replay(self):
        for fault in ("short_write", "crash_after_stage_fsync", "crash_post_link"):
            with self.subTest(fault=fault):
                execution_ref = self.execute(receipt_fault=fault)
                self.assertEqual(self.calls, list(CELL_ORDER))
                self.assertEqual(self.execution(execution_ref)["status"], "PENDING_HUMAN_GRADING")
                self.assertFalse((self.root.path / "receipt/.stage-block-v6.json").exists())
                self.root.close(); self.setUp()

    def test_forged_receipt_engine_policy_and_provider_grading_retain_inconclusive(self):
        execution_ref = self.execute()
        path = self.root.path / execution_ref["path"]
        path.write_text("{}")
        os.chmod(path, 0o600)
        with self.assertRaisesRegex(ContractError, "REF_HASH_BYTES"):
            finalize_block(execution_ref, self.root.path, {}, self.opening())
        for mode, error in (("engine", "ENGINE_READBACK_MISMATCH"), ("policy", "POLICY_MUTATION_OR_DRIFT"), ("grading", "PROVIDER_GRADING_REF_FORBIDDEN")):
            self.root.close(); self.setUp()
            item = self.execution(self.execute(mode))
            self.assertEqual(item["status"], "INCONCLUSIVE_NOT_FINALIZABLE")
            self.assertIn(error, item["cells"][0]["errors"])
        self.assertEqual(TOOL_POLICY["roster"][0]["version"], "provider-native-frozen-v1")

    def test_fake_authority_and_open_p0_review_fail_closed(self):
        self.root.close(); self.setUp()
        bad = self.authority(fake=True)
        self.calls = []
        with self.assertRaisesRegex(ContractError, "PROVIDER_AUTHORITY"):
            self.execute(registry=bad)
        self.assertEqual(self.calls, [])
        self.assertEqual(KNOWN_BINDINGS["p0_review"], "0a150a6221ba082ae38eae6951bff43fc904996a99623e425d36059e431ec2e6")
        self.assertEqual(KNOWN_BINDINGS["p0_review_status"], "OPEN")
        self.assertEqual(default_run()["countable"], False)

    def test_missing_grade_and_early_open_remain_rejected(self):
        execution_ref = self.execute()
        grades = self.grade_refs(execution_ref)
        grades[CELL_ORDER[0]] = grades[CELL_ORDER[0]][:1]
        with self.assertRaises(ContractError):
            finalize_block(execution_ref, self.root.path, grades, self.opening())
        grades = self.grade_refs(execution_ref)
        with self.assertRaises(ContractError):
            finalize_block(execution_ref, self.root.path, grades, self.opening(1))

    def test_history_and_exports(self):
        import shared.job_runtime.candidates.r6_data_quality_2x2_runner_v1 as package
        self.assertEqual(set(package.__all__), {"default_run", "execute_block", "finalize_block"})
        index = json.loads((ROOT / "tuning/architecture/r6_data_quality_2x2_runner_v1/history/history-index-v7.json").read_text())
        self.assertEqual(len(index["rows"]), 7)
        row = index["rows"][-1]
        raw = (ROOT / row["path"]).read_bytes()
        self.assertEqual((len(raw), hashlib.sha256(raw).hexdigest()), (row["bytes"], row["sha256"]))

    @unittest.skipUnless(Draft202012Validator is not None, "jsonschema unavailable")
    def test_closed_schemas_validate_receipt_and_grant(self):
        execution_ref, _body = self.synthetic_execution_receipt()
        execution = self.execution(execution_ref)
        package = ROOT / "shared/job_runtime/candidates/r6_data_quality_2x2_runner_v1"
        for name, value in (("execution-receipt-v6.schema.json", execution), ("block-grant-v1.schema.json", grant())):
            schema = json.loads((package / name).read_text())
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(value)
            bad = copy.deepcopy(value)
            bad["extra"] = True
            self.assertFalse(Draft202012Validator(schema).is_valid(bad))


if __name__ == "__main__":
    unittest.main()
