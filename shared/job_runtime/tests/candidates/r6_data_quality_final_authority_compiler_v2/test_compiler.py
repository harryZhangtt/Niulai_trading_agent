from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import pkgutil
import tempfile
import unittest
from unittest import mock

import shared.job_runtime.candidates.r6_data_quality_final_authority_compiler_v2 as package


_STATUS = "DISABLED_AUTHORITY_COMPILER_V2_PENDING_FIXED_PINS_AND_FRESH_REVIEW"
_ORDER = ("R6DQ-7F2C91A4", "R6DQ-1B8E43D7", "R6DQ-C4A7095E", "R6DQ-92D6F0B3")
_COMMON_PROMPT = {"path": "mentor/runtime/scheduler-midresponse-recovery-20261107/schema9-isolated-canary-q1-ab-payload-v1.json", "bytes": 526, "sha256": "3c75beab1bca33029e8de266e36468543d5d3ef2910916d66cc7c4d9bbc0df6b", "transport": "native_stdin_exact_once"}
_TOOL = {"version": "tool-policy-v7", "clean_review_sha256": "10a073d131cee84e9e7d439b9e19b015c323d68d991919ad5ff6e3daf980e150", "bytedcli_allowed": False}
_WINDOW = {"not_before": "2026-11-11T00:00:00Z", "deadline": "2026-11-12T00:00:00Z", "block_seconds": 1800}
_LIMITS = {"concurrency": 1, "requests": 1, "retries": 0, "replays": 0, "status_queries": 0}
_CELLS = {
    "R6DQ-7F2C91A4": {"order": 0, "provider": "CLAUDE", "addon": "CONDITION-X", "addon_state": "OFF", "model": "claude-opus-5-5", "effort": "low", "provider_identity": {"boundary": "claude-v8", "provider": "claude_host", "transport": "claude_ferry", "binary_sha256": "abc9feeeca8091d51b623291e044cf0528c2f6b74e0c1d6ef671d52c73f7cd3c"}, "offset": 450},
    "R6DQ-1B8E43D7": {"order": 1, "provider": "CODEX", "addon": "CONDITION-Y", "addon_state": "ON", "model": "gpt-6.1-sol", "effort": "low", "provider_identity": {"boundary": "codex-v6", "provider": "codex_cli", "adapter": "CodexAttemptAdapterV9", "schema": "stage-b-execution-v3", "publication_driver": "AtomicPublisher.publish", "binary_sha256": "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc"}, "offset": 900},
    "R6DQ-C4A7095E": {"order": 2, "provider": "CLAUDE", "addon": "CONDITION-Y", "addon_state": "ON", "model": "claude-opus-5-5", "effort": "low", "provider_identity": {"boundary": "claude-v8", "provider": "claude_host", "transport": "claude_ferry", "binary_sha256": "abc9feeeca8091d51b623291e044cf0528c2f6b74e0c1d6ef671d52c73f7cd3c"}, "offset": 1350},
    "R6DQ-92D6F0B3": {"order": 3, "provider": "CODEX", "addon": "CONDITION-X", "addon_state": "OFF", "model": "gpt-6.1-sol", "effort": "low", "provider_identity": {"boundary": "codex-v6", "provider": "codex_cli", "adapter": "CodexAttemptAdapterV9", "schema": "stage-b-execution-v3", "publication_driver": "AtomicPublisher.publish", "binary_sha256": "030316ecfbb41f4e7946e584b0063ef333b7a36cd312ba349f2f6869e39b62cc"}, "offset": 1800},
}


class _DraftError(ValueError):
    pass


def _require(condition, code):
    if not condition:
        raise _DraftError(code)


def _cell(cell_id):
    spec = _CELLS[cell_id]
    return {"artifact_kind": "NON_AUTHORIZING_CELL_GRANT_DRAFT", "status": _STATUS, "activation": False, "authority_effect": "NONE", "self_minted": False, "cell_id": cell_id, "order_index": spec["order"], "provider": {"port": spec["provider"], **spec["provider_identity"]}, "addon": {"label": spec["addon"], "state": spec["addon_state"]}, "model": {"id": spec["model"], "effort": spec["effort"]}, "budget": {"currency": "USD", "hard_cap": "0.01"}, "window": {**_WINDOW, "admission_offset_seconds": spec["offset"]}, "prompt": dict(_COMMON_PROMPT), "tool_policy": dict(_TOOL), "p0": {"version": "P0-v10", "clean_pin_required": True}, "limits": dict(_LIMITS), "countable": False}


def _block():
    return {"artifact_kind": "NON_AUTHORIZING_BLOCK_GRANT_DRAFT", "status": _STATUS, "activation": False, "authority_effect": "NONE", "self_minted": False, "block_id": "R6-DQ-FINAL-FOUR-CELL-BLOCK-V1", "cell_order": list(_ORDER), "cells": [_cell(i) for i in _ORDER], "limits": {"concurrency": 1, "requests_per_cell": 1, "total_requests": 4, "retries": 0, "replays": 0, "status_queries": 0}, "countability": "ALL_FOUR_OR_NONE", "partial_block": False, "bytedcli_allowed": False}


def _validate_cell(value):
    fields = {"artifact_kind", "status", "activation", "authority_effect", "self_minted", "cell_id", "order_index", "provider", "addon", "model", "budget", "window", "prompt", "tool_policy", "p0", "limits", "countable"}
    _require(type(value) is dict and set(value) == fields, "CELL_DRAFT_SHAPE")
    _require(value["artifact_kind"] == "NON_AUTHORIZING_CELL_GRANT_DRAFT" and value["status"] == _STATUS, "CELL_DRAFT_STATUS")
    _require(value["activation"] is False and value["authority_effect"] == "NONE" and value["self_minted"] is False and value["countable"] is False, "CELL_DRAFT_MUST_NOT_AUTHORIZE")
    spec = _CELLS.get(value["cell_id"]); _require(spec is not None, "CELL_ID")
    _require(value["order_index"] == spec["order"], "CELL_ORDER_DRIFT")
    _require(value["provider"] == {"port": spec["provider"], **spec["provider_identity"]}, "CELL_PROVIDER_DRIFT")
    _require(value["addon"] == {"label": spec["addon"], "state": spec["addon_state"]}, "CELL_ADDON_DRIFT")
    _require(value["model"] == {"id": spec["model"], "effort": spec["effort"]}, "CELL_MODEL_DRIFT")
    _require(value["budget"] == {"currency": "USD", "hard_cap": "0.01"}, "CELL_BUDGET_DRIFT")
    _require(value["window"] == {**_WINDOW, "admission_offset_seconds": spec["offset"]}, "CELL_WINDOW_DRIFT")
    _require(value["prompt"] == _COMMON_PROMPT and value["tool_policy"] == _TOOL, "CELL_POLICY_DRIFT")
    _require(value["p0"] == {"version": "P0-v10", "clean_pin_required": True} and value["limits"] == _LIMITS, "CELL_LIMIT_DRIFT")


def _validate_block(value):
    fields = {"artifact_kind", "status", "activation", "authority_effect", "self_minted", "block_id", "cell_order", "cells", "limits", "countability", "partial_block", "bytedcli_allowed"}
    _require(type(value) is dict and set(value) == fields, "BLOCK_DRAFT_SHAPE")
    _require(value["artifact_kind"] == "NON_AUTHORIZING_BLOCK_GRANT_DRAFT" and value["status"] == _STATUS, "BLOCK_DRAFT_STATUS")
    _require(value["activation"] is False and value["authority_effect"] == "NONE" and value["self_minted"] is False, "BLOCK_DRAFT_MUST_NOT_AUTHORIZE")
    _require(value["block_id"] == "R6-DQ-FINAL-FOUR-CELL-BLOCK-V1" and tuple(value["cell_order"]) == _ORDER, "BLOCK_ORDER_DRIFT")
    _require(type(value["cells"]) is list and len(value["cells"]) == 4, "PARTIAL_BLOCK_FORBIDDEN")
    for expected_id, cell in zip(_ORDER, value["cells"]):
        _validate_cell(cell); _require(cell["cell_id"] == expected_id, "BLOCK_CELL_SWAP")
    _require(value["limits"] == {"concurrency": 1, "requests_per_cell": 1, "total_requests": 4, "retries": 0, "replays": 0, "status_queries": 0}, "BLOCK_LIMIT_DRIFT")
    _require(value["countability"] == "ALL_FOUR_OR_NONE" and value["partial_block"] is False and value["bytedcli_allowed"] is False, "BLOCK_MUST_NOT_AUTHORIZE")


class NamespaceTests(unittest.TestCase):
    def test_exact_public_namespace_and_zero_argument_signature(self):
        public = {name for name in vars(package) if not name.startswith("_")}
        self.assertEqual(public, {"compile_deny_report"})
        self.assertEqual(package.__all__, ["compile_deny_report"])
        self.assertEqual(list(inspect.signature(package.compile_deny_report).parameters), [])
        with self.assertRaises(TypeError): package.compile_deny_report(Path("/caller/root"))
        with self.assertRaises(TypeError): package.compile_deny_report(clock="caller", policy="caller")

    def test_no_cli_or_importable_code_submodule(self):
        self.assertIsNone(importlib.util.find_spec(package.__name__ + ".__main__"))
        self.assertEqual(list(pkgutil.iter_modules(package.__path__)), [])
        source = Path(package.__file__).read_text()
        self.assertNotIn("r6_data_quality_final_authority_compiler_v1 import", source)
        self.assertNotIn("from .compiler", source)
        for name in ("DENY", "STATUS", "ContractError", "main", "compiler", "drafts", "validate_block_draft", "validate_cell_draft"):
            self.assertFalse(hasattr(package, name), name)


class DenyOnlyTests(unittest.TestCase):
    def test_report_is_exactly_deny_only_with_no_effects(self):
        result = package.compile_deny_report()
        self.assertEqual(result["version"], "r6-data-quality-final-authority-deny-report-v2")
        self.assertEqual(result["status"], _STATUS)
        self.assertEqual(result["decision"], "DENY")
        self.assertFalse(result["activation"]); self.assertFalse(result["authority_issued"]); self.assertFalse(result["countable"])
        self.assertTrue(all(v == 0 for v in result["effects"].values()))
        self.assertFalse({"grant", "block_grant", "cell_grants"} & set(result))

    def test_exact_open_blockers_and_current_codex_pin(self):
        result = package.compile_deny_report(); missing = {x["name"]: x for x in result["missing_pins"]}
        self.assertIn("codex_v6_clean_pending_p0_v10", result["verified_pin_names"])
        self.assertIn("claude_v9_clean_pending_p0_v10", result["verified_pin_names"])
        self.assertNotIn("claude_v9_clean", missing)
        self.assertEqual(result["missing_pin_count"], 24)
        expected = {"runner_v8_open_review": (6255, "145265647df2a9231d7b64f3b7c70c7266403b38cb15ad98e38deef3a6d588f5"), "blind_map_v5_open_review": (23467, "a76216d40b8af7617e7169f0969ab15bd69e3333dce6b6e9543af77612f783e8"), "blind_map_v6_open_review": (15753, "3a1d63397c2c5732ec1f4a5f9b92a620e5da93cb6ede31ec4826ceb8adeed084"), "claude_v8_open_review": (10896, "65e425cab9b0fd7ed9381e0f8019360fad0e5c0f2da432c3b5c4e4c27c16df0d"), "claude_metadata_preflight_v1_open_review": (13066, "548ae003bf8a29f21b60753942b3414895c058daf68b9a656839d7b0fad319b5"), "runner_v2_open_review": (13206, "c2669dec8fd1e32f616a6d97ce1e75f6de9a736d106814db1c99f8328215cff1"), "runner_v3_open_review": (22021, "e11ca7dd9b35a21e8d57ef9398c4aa713a77c45d00986b3f4c3d1ca693b06afe"), "runner_v4_open_review": (13161, "ca0966ea04e432f0ea990742a8daa6cd628def5b7b2af7540a752aeaa734775e"), "execution_window_v2_open_review": (9149, "5c3a37d8823ff1950f3a0d2e1131120101b54af6dbf57ad2e11cb0d1bd8047d7"), "compiler_v1_open_review": (15882, "1a022d5bf7da25707bff7d3312f2721f3d414b37352ece3bf69a57e1b5a2ddf9")}
        self.assertIn("claude_v8_open_review", missing)
        for name,(size,digest) in expected.items():
            self.assertEqual(missing[name]["reason"], "VERIFIED_OPEN_BLOCKER_NOT_AUTHORITY")
            self.assertEqual((missing[name]["required_bytes"], missing[name]["required_sha256"]), (size,digest))

    def test_exact_window_v2_missing_entry(self):
        result = package.compile_deny_report(); missing = {x["name"]: x for x in result["missing_pins"]}
        self.assertEqual(missing["execution_window_v4_clean"], {"name": "execution_window_v4_clean", "path": "tuning/architecture/r6_common_execution_window_v4/independent-review-v4-clean.json", "required_bytes": None, "required_sha256": None, "required_mode": "0644", "review_of": None, "conditional": None, "reason": "ARTIFACT_ABSENT_AND_PIN_DIGEST_NOT_ADOPTED"})

    def test_wrong_generation_window_can_never_satisfy_v2(self):
        paths = {pin.path for pin in package._FUTURE_PINS}
        self.assertNotIn("tuning/architecture/r6_common_execution_window_v1/independent-review-v1-final-clean.json", paths)
        self.assertNotIn("mentor/runtime/scheduler-midresponse-recovery-20261107/r6-common-execution-window-v2-fresh-independent-review.json", paths)
        self.assertNotIn("tuning/architecture/r6_common_execution_window_v3/independent-review-v3-clean.json", paths)
        self.assertIn("tuning/architecture/r6_common_execution_window_v4/independent-review-v4-clean.json", paths)
        self.assertIn("execution_window_v4_clean", {x["name"] for x in package.compile_deny_report()["missing_pins"]})
        self.assertNotIn("execution_window_v3_clean", {x["name"] for x in package.compile_deny_report()["missing_pins"]})

    def test_all_future_successors_humans_and_adoption_are_missing(self):
        names = {x["name"] for x in package.compile_deny_report()["missing_pins"]}
        required = {"blind_map_v7_clean", "runner_v5_clean", "p0_v10_clean", "claude_metadata_preflight_v2_clean", "codex_v6_p0_v10_clean", "execution_window_v4_clean", "common_orchestrator_v3_clean", "human_registry_authentic", "human_registry_authentic_review", "g1_authentic", "g1_authentic_review", "g2_authentic", "g2_authentic_review", "authority_last_adoption"}
        self.assertTrue(required <= names)
        self.assertNotIn("runner_v3_clean", names)
        self.assertNotIn("runner_v4_clean", names)
        self.assertNotIn("blind_map_v6_clean", names)
        self.assertNotIn("claude_metadata_preflight_v1_clean", names)
        self.assertNotIn("g3_authentic", names)
        with mock.patch.object(package, "_g3_required", return_value=True): conditional = {x["name"] for x in package.compile_deny_report()["missing_pins"]}
        self.assertTrue({"g3_authentic", "g3_authentic_review"} <= conditional)


class SecurePinTests(unittest.TestCase):
    def _pin(self, root, value, expected="CLEAN", mode=0o600):
        raw=json.dumps(value,sort_keys=True,separators=(",",":")).encode(); path=root/"fixed.json"; path.write_bytes(raw); os.chmod(path,mode)
        return package._Pin("test", "fixed.json", len(raw), hashlib.sha256(raw).hexdigest(), mode, ((("status",), expected),))

    def test_stale_sha_mode_forged_status_and_duplicate_keys_fail(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); pin=self._pin(root,{"status":"CLEAN"})
            with mock.patch.object(package,"_WORKSPACE_ROOT",root): self.assertEqual(package._secure_read(root,pin)["status"],"CLEAN")
            stale=package._Pin("test","fixed.json",pin.bytes,"0"*64,0o600,pin.expectations)
            with mock.patch.object(package,"_WORKSPACE_ROOT",root), self.assertRaisesRegex(package._ContractError,"SHA256_DRIFT"): package._secure_read(root,stale)
            forged=self._pin(root,{"status":"FORGED_CLEAN"})
            with mock.patch.object(package,"_WORKSPACE_ROOT",root), self.assertRaisesRegex(package._ContractError,"STATUS_NOT_CLEAN"): package._secure_read(root,forged)
            os.chmod(root/"fixed.json",0o644)
            with mock.patch.object(package,"_WORKSPACE_ROOT",root), self.assertRaisesRegex(package._ContractError,"MODE_DRIFT"): package._secure_read(root,forged)
            raw=b'{"status":"CLEAN","status":"CLEAN"}'; (root/"fixed.json").write_bytes(raw); os.chmod(root/"fixed.json",0o600)
            dup=package._Pin("test","fixed.json",len(raw),hashlib.sha256(raw).hexdigest(),0o600)
            with mock.patch.object(package,"_WORKSPACE_ROOT",root), self.assertRaisesRegex(package._ContractError,"DUPLICATE_JSON_KEY"): package._secure_read(root,dup)

    def test_nofollow_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); target=root/"target.json"; target.write_text('{"status":"CLEAN"}'); os.chmod(target,0o600); (root/"fixed.json").symlink_to(target); raw=target.read_bytes()
            pin=package._Pin("test","fixed.json",len(raw),hashlib.sha256(raw).hexdigest(),0o600)
            with mock.patch.object(package,"_WORKSPACE_ROOT",root), self.assertRaisesRegex(package._ContractError,"NOFOLLOW"): package._secure_read(root,pin)


class DraftAndSchemaTests(unittest.TestCase):
    def test_exact_test_only_draft_passes_but_authorizing_adversaries_fail(self):
        value=_block(); _validate_block(value)
        cases=[]
        a=copy.deepcopy(value); a["self_minted"]=True; cases.append(a)
        b=copy.deepcopy(value); b["cells"].pop(); b["cell_order"].pop(); cases.append(b)
        c=copy.deepcopy(value); c["bytedcli_allowed"]=True; cases.append(c)
        d=copy.deepcopy(value); d["cells"][0]["budget"]["hard_cap"]="0.02"; cases.append(d)
        e=copy.deepcopy(value); e["cells"][0],e["cells"][1]=e["cells"][1],e["cells"][0]; cases.append(e)
        f=copy.deepcopy(value); f["cells"][0]["provider"]=copy.deepcopy(f["cells"][1]["provider"]); cases.append(f)
        g=copy.deepcopy(value); g["limits"]["status_queries"]=1; cases.append(g)
        for case in cases:
            with self.assertRaises(_DraftError): _validate_block(case)

    def test_strict_non_authorizing_root_level_schemas(self):
        root=Path(package.__file__).parent; schemas={p.name:json.loads(p.read_text()) for p in root.glob("*.schema.json")}
        self.assertEqual(set(schemas), {"block-grant-draft-v2.schema.json", "cell-grant-draft-v2.schema.json", "deny-report-v2.schema.json", "missing-pin-list-v2.schema.json"})
        for value in schemas.values(): self.assertEqual(value["$schema"],"https://json-schema.org/draft/2020-12/schema")
        self.assertFalse(schemas["deny-report-v2.schema.json"]["additionalProperties"])
        self.assertFalse(schemas["missing-pin-list-v2.schema.json"]["items"]["additionalProperties"])
        self.assertEqual(schemas["block-grant-draft-v2.schema.json"]["const"]["activation"],False)
        self.assertEqual(len(schemas["cell-grant-draft-v2.schema.json"]["oneOf"]),4)


if __name__ == "__main__":
    unittest.main()
